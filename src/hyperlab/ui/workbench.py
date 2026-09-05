"""Local Qt instrument workbench. Camera and disk work never run on the GUI thread."""
from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import shutil
import time

import numpy as np
import psutil
from PySide6 import QtCore, QtGui, QtWidgets as W
import pyqtgraph as pg

from hyperlab.io import Cube, load_cube, make_synthetic_cube, save_cube
from hyperlab.ui.view import bayer_cell_rgb, display_levels, roi_rect


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2,
                      default=lambda v: v.tolist() if isinstance(v, np.ndarray) else str(v))


class Workbench(W.QMainWindow):
    def __init__(self, path=None, *, session_factory=None, benchmark_log=None):
        super().__init__()
        self.setWindowTitle('HyperLab — Live workbench')
        self.resize(1220, 820)
        self.setMinimumSize(960, 620)
        self.session_factory = session_factory
        self.session = None
        self.profile = None
        self.cube = None
        self.sequence = None
        self.displayed_frame = None
        self.display_mode = 'EMPTY'
        self.product = None
        self.product_source = None
        self.roi_results = []
        self.recent = []
        self.rois = []
        self.results = queue.Queue(maxsize=4)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='hyperlab-analysis')
        self.task_busy = False
        self.closing = False
        self.last_status = {}
        self.last_quality = 0.0
        self.last_log = 0.0
        self.last_frame_identity = None
        self.levels = None
        self.temporal_plot = deque(maxlen=300)
        self.output_dir = Path('local/experiments').resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.benchmark_log = Path(benchmark_log) if benchmark_log else None
        if self.benchmark_log:
            self.benchmark_log.parent.mkdir(parents=True, exist_ok=True)
        self._build()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        if path:
            QtCore.QTimer.singleShot(0, lambda: self.open_path(Path(path)))

    def button(self, text, callback, name=None):
        button = W.QPushButton(text)
        if name:
            button.setObjectName(name)
        button.clicked.connect(callback)
        return button

    def _build(self):
        pg.setConfigOptions(imageAxisOrder='row-major', antialias=False)
        root = W.QWidget()
        self.setCentralWidget(root)
        layout = W.QVBoxLayout(root)
        layout.setContentsMargins(14, 10, 14, 10)
        header = W.QHBoxLayout()
        title = W.QLabel('HyperLab')
        title.setStyleSheet('font-size:22px; font-weight:700; color:#123e52')
        header.addWidget(title)
        self.device_label = W.QLabel('Disconnected · mvBlueFOX3')
        header.addWidget(self.device_label)
        header.addStretch()
        self.mode_label = W.QLabel('EMPTY')
        self.mode_label.setStyleSheet('font-weight:600; padding:5px; background:#e6edf2; border-radius:4px')
        header.addWidget(self.mode_label)
        self.connect_button = self.button('Connect camera', self.connect_camera, 'connect')
        header.addWidget(self.connect_button)
        self.disconnect_button = self.button('Disconnect', self.disconnect, 'disconnect')
        header.addWidget(self.disconnect_button)
        header.addWidget(self.button('Open data…', self.open_dialog, 'open'))
        header.addWidget(self.button('Diagnostics', lambda: self.diagnostics.setVisible(not self.diagnostics.isVisible())))
        layout.addLayout(header)
        self.tabs = W.QTabBar()
        for text in ('Acquisition', 'Analysis', 'Calibration'):
            self.tabs.addTab(text)
        layout.addWidget(self.tabs)
        actions = W.QHBoxLayout()
        self.preview_button = self.button('▶ Start preview', self.start_preview, 'preview')
        self.preview_button.setStyleSheet('background:#147b83; color:white; font-weight:600; padding:9px 18px')
        self.stop_button = self.button('■ Stop acquisition', self.stop_preview, 'stop')
        self.save_button = self.button('Save current frame', self.snapshot, 'snapshot')
        self.record_button = self.button('Record…', self.record_dialog, 'record')
        self.freeze = W.QCheckBox('Freeze display')
        self.freeze.setToolTip('Freezes the display only; acquisition may continue. Save captures the raw frame currently displayed.')
        for item in (self.preview_button, self.stop_button, self.save_button, self.record_button, self.freeze):
            actions.addWidget(item)
        actions.addStretch()
        actions.addWidget(self.button('Fit', self.fit))
        actions.addWidget(self.button('1:1', self.one_to_one))
        self.side_toggle = self.button('Settings ▾', lambda: self.side_scroll.setVisible(not self.side_scroll.isVisible()))
        actions.addWidget(self.side_toggle)
        layout.addLayout(actions)
        split = W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.side_scroll = W.QScrollArea()
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setMinimumWidth(240)
        self.side_scroll.setMaximumWidth(310)
        self.sidebar = W.QStackedWidget()
        self.sidebar.setSizePolicy(W.QSizePolicy.Policy.Ignored, W.QSizePolicy.Policy.Preferred)
        self.side_scroll.setWidget(self.sidebar)
        split.addWidget(self.side_scroll)
        self._capture_panel()
        self._analysis_panel()
        self._calibration_panel()
        self.side_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for combo in self.sidebar.findChildren(W.QComboBox):
            combo.setSizePolicy(W.QSizePolicy.Policy.Ignored, W.QSizePolicy.Policy.Fixed)
        for label in self.sidebar.findChildren(W.QLabel):
            label.setWordWrap(True)
        for control in self.sidebar.findChildren(W.QAbstractSpinBox):
            control.setSizePolicy(W.QSizePolicy.Policy.Ignored, W.QSizePolicy.Policy.Fixed)
        self.tabs.currentChanged.connect(self.sidebar.setCurrentIndex)
        self.vertical = W.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.images = W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.graphics = pg.GraphicsLayoutWidget()
        self.plot = self.graphics.addPlot()
        self.plot.setLabel('bottom', 'Raw x', units='pixel')
        self.plot.setLabel('left', 'Raw y', units='pixel')
        for axis in ('bottom', 'left'):
            self.plot.getAxis(axis).enableAutoSIPrefix(False)
        self.plot.setAspectLocked(True)
        self.plot.invertY(True)
        self.image = pg.ImageItem(axisOrder='row-major')
        self.image.setAutoDownsample(True)
        self.plot.addItem(self.image)
        self.saturation_overlay = pg.ImageItem(axisOrder='row-major')
        self.plot.addItem(self.saturation_overlay)
        self.images.addWidget(self.graphics)
        self.derived_graphics = pg.GraphicsLayoutWidget()
        self.derived_plot = self.derived_graphics.addPlot(title='Derived values · invalid pixels are transparent')
        self.derived_plot.setAspectLocked(True)
        self.derived_plot.invertY(True)
        self.derived_image = pg.ImageItem(axisOrder='row-major')
        self.derived_plot.addItem(self.derived_image)
        self.colorbar = pg.ColorBarItem(values=(0, 1), colorMap=pg.colormap.get('viridis'))
        self.colorbar.setImageItem(self.derived_image, insert_in=self.derived_plot)
        self.images.addWidget(self.derived_graphics)
        self.derived_graphics.hide()
        self.vertical.addWidget(self.images)
        self.chart = pg.PlotWidget(background='w')
        self.chart.setLabel('left', 'DN / descriptive value')
        self.chart.showGrid(x=True, y=True, alpha=0.15)
        self.curves = [self.chart.plot(pen=pg.mkPen(c, width=2)) for c in ('#d47e22', '#247dc4')]
        self.vertical.addWidget(self.chart)
        self.vertical.setSizes([570, 140])
        split.addWidget(self.vertical)
        split.setStretchFactor(1, 1)
        split.setSizes([275, 920])
        layout.addWidget(split, 1)
        axis = W.QHBoxLayout()
        self.axis_label = W.QLabel('Fixed optical state · no data loaded')
        self.band = W.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.band.setRange(0, 0)
        self.band.valueChanged.connect(self.band_changed)
        axis.addWidget(self.axis_label)
        axis.addWidget(self.band, 1)
        layout.addLayout(axis)
        self.pixel_label = W.QLabel('Pixel: —')
        self.metrics_label = W.QLabel('Capture —  |  Display —  |  Writer —  |  Age —')
        self.metrics_label.setWordWrap(True)
        layout.addWidget(self.pixel_label)
        layout.addWidget(self.metrics_label)
        self.graphics.scene().sigMouseMoved.connect(self.pixel_hover)
        self.message = W.QLabel('Connect opens a real camera session. Preview is not recorded by default.')
        self.message.setWordWrap(True)
        self.statusBar().addWidget(self.message, 1)
        self.diagnostics = W.QDockWidget('Device, evidence and local output', self)
        detail = W.QWidget()
        dl = W.QVBoxLayout(detail)
        self.detail_text = W.QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        dl.addWidget(self.detail_text)
        self.output_edit = W.QLineEdit(str(self.output_dir))
        dl.addWidget(self.output_edit)
        dl.addWidget(self.button('Choose output folder', self.choose_output))
        dl.addWidget(self.button('Export session evidence', self.export_evidence))
        self.diagnostics.setWidget(detail)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.diagnostics)
        self.diagnostics.hide()
        self.setStyleSheet('QMainWindow {background:#f4f7f9;} QPushButton {padding:6px 8px;} '
                           'QGroupBox {font-weight:600; margin-top:10px;} QGroupBox::title {subcontrol-origin:margin;} '
                           'QLabel {color:#263e4b;} QTabBar::tab {padding:8px 22px;}')
        self.update_controls()

    def panel(self):
        panel = W.QWidget()
        form = W.QVBoxLayout(panel)
        form.setContentsMargins(10, 12, 10, 12)
        form.setSpacing(9)
        self.sidebar.addWidget(panel)
        return form

    def _capture_panel(self):
        form = self.panel()
        form.addWidget(W.QLabel('Fixed optical state · sensor imaging'))
        settings = W.QFormLayout()
        self.format = W.QComboBox()
        self.format.addItems(['BayerRG12', 'RGB8', 'BGR8'])
        self.exposure = W.QDoubleSpinBox()
        self.exposure.setRange(0.01, 1000)
        self.exposure.setDecimals(3)
        self.exposure.setValue(50)
        self.exposure.setSuffix(' ms')
        self.gain = W.QDoubleSpinBox()
        self.gain.setRange(0, 48)
        self.gain.setDecimals(3)
        self.gain.setSuffix(' dB')
        self.session_mode = W.QComboBox()
        self.session_mode.addItem('Manual measurement · fixed settings', 'measurement')
        self.session_mode.addItem('Preview · preserve automatic processing', 'preview')
        settings.addRow('Pixel format', self.format)
        settings.addRow('Exposure', self.exposure)
        settings.addRow('Gain', self.gain)
        form.addLayout(settings)
        form.addWidget(self.session_mode)
        self.apply_button = self.button('Apply on next start', self.apply_settings, 'apply_settings')
        form.addWidget(self.apply_button)
        self.readback_label = W.QLabel('Ranges and actual settings are read after connection')
        self.readback_label.setWordWrap(True)
        form.addWidget(self.readback_label)
        self.view_mode = W.QComboBox()
        self.view_mode.addItems(['Raw DN / RGB', 'CFA cell RGB · display derivative'])
        self.view_mode.currentIndexChanged.connect(lambda: self.render_current())
        form.addWidget(self.view_mode)
        self.auto_levels = W.QCheckBox('Auto display stretch · 1–99%')
        self.auto_levels.setChecked(True)
        self.auto_levels.toggled.connect(lambda: self.render_current())
        form.addWidget(self.auto_levels)
        ranges = W.QHBoxLayout()
        self.low = W.QDoubleSpinBox()
        self.high = W.QDoubleSpinBox()
        for control, value in ((self.low, 0), (self.high, 4095)):
            control.setRange(-1e12, 1e12)
            control.setValue(value)
            control.valueChanged.connect(lambda: self.render_current())
            ranges.addWidget(control)
        form.addLayout(ranges)
        self.overlay = W.QCheckBox('Saturation overlay · red')
        self.overlay.toggled.connect(lambda: self.render_current())
        form.addWidget(self.overlay)
        self.plot_mode = W.QComboBox()
        self.plot_mode.addItems(['Histogram (sampled)', 'ROI time trend', 'ROI channel / state curves'])
        form.addWidget(self.plot_mode)
        self.quality_label = W.QLabel('Quality: —')
        self.quality_label.setWordWrap(True)
        form.addWidget(self.quality_label)
        form.addWidget(W.QLabel('Recent saves · double-click to reopen'))
        self.recent_list = W.QListWidget()
        self.recent_list.setMaximumHeight(130)
        self.recent_list.itemDoubleClicked.connect(lambda item: self.open_path(Path(item.data(QtCore.Qt.ItemDataRole.UserRole))))
        form.addWidget(self.recent_list)
        form.addWidget(self.button('Open output folder', lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.output_dir)))))
        form.addStretch()

    def notify(self, text):
        self.message.setText(str(text))

    def background(self, function, callback, label):
        if self.task_busy:
            self.notify('A background operation is still running.')
            return
        self.task_busy = True
        self.notify(label)
        future = self.executor.submit(function)
        def completed(result):
            try:
                self.results.put((callback, result.result(), None))
            except Exception as error:
                self.results.put((callback, None, error))
        future.add_done_callback(completed)

    def requested_settings(self):
        return {'PixelFormat': self.format.currentText(),
                'ExposureTime': self.exposure.value() * 1000, 'Gain': self.gain.value()}

    def connect_camera(self):
        if self.session and self.session.state not in ('disconnected', 'error'):
            return
        from hyperlab.devices import discover_profile
        previous = self.session
        if previous:
            previous.close(wait=False)
        def discover():
            if previous and not previous.close(wait=True):
                raise RuntimeError('Previous camera session has not released its resources.')
            return discover_profile()
        self.background(discover, self._connect_profile, 'Checking the current device and runtime…')

    def _connect_profile(self, profile):
        if self.closing:
            return
        from hyperlab.acquisition.camera import CameraSession
        self.profile = profile
        factory = self.session_factory or CameraSession
        self.session = factory(profile['cti'], profile['serial'], settings=self.requested_settings(),
                               mode=self.session_mode.currentData())
        self.session.connect()
        self.device_label.setText(profile['name'])
        self.detail_text.setPlainText(json_text(profile))
        self.update_controls()

    def apply_settings(self):
        if self.session:
            self.session.set_settings(self.requested_settings(), mode=self.session_mode.currentData())
        self.notify('Settings apply on the next start. Actual values appear after camera readback.')

    def start_preview(self):
        if self.session:
            if self.task_busy:
                self.notify('Wait for the current file operation to finish.')
                return
            if self.sequence:
                self.sequence.close()
                self.sequence = None
            if self.cube is not None:
                self.cube.close()
                self.cube = None
            self.product = self.product_source = None
            self.derived_graphics.hide()
            self.temporal_plot.clear()
            self.band.blockSignals(True)
            self.band.setValue(0)
            self.band.setRange(0, 0)
            self.band.blockSignals(False)
            self.freeze.setChecked(False)
            self.last_frame_identity = None
            self.session.set_settings(self.requested_settings(), mode=self.session_mode.currentData())
            self.session.start_preview()

    def stop_preview(self):
        if self.session:
            self.session.stop_preview()
            self.notify('Stopping the stream and restoring session settings…')

    def disconnect(self):
        if self.session:
            self.session.disconnect()

    def snapshot(self):
        if self.displayed_frame is not None and self.session:
            directory = self.output_dir / ('frame_' + stamp())
            self.session.snapshot(directory, frame=self.displayed_frame)
            self.notify(f'Saving displayed frame {self.displayed_frame.identity}')
        elif self.cube is not None:
            cube = self.cube
            path = self.output_dir / ('copy_' + stamp() + '.npy')
            self.background(lambda: save_cube(cube, path), lambda _: self.add_recent(path), 'Saving a copy of the selected raw array…')

    def record_dialog(self):
        if not self.session:
            return
        if self.session.state == 'recording':
            self.session.stop_recording()
            return
        frame = self.session.latest_frame()
        if frame is None:
            return
        dialog = W.QDialog(self)
        dialog.setWindowTitle('Bounded recording · raw time sequence')
        form = W.QFormLayout(dialog)
        frames = W.QSpinBox()
        frames.setRange(1, 10000)
        frames.setValue(300)
        seconds = W.QDoubleSpinBox()
        seconds.setRange(1, 600)
        seconds.setValue(30)
        budget = W.QLabel()
        budget.setWordWrap(True)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok | W.QDialogButtonBox.StandardButton.Cancel)
        free = shutil.disk_usage(self.output_dir).free
        def update_budget():
            needed = frames.value() * frame.data.nbytes
            budget.setText(f'Up to {needed / 1024**3:.2f} GiB; available {free / 1024**3:.1f} GiB.\nRecording stops at the frame or duration limit; preview continues. Writer overflow stops recording and preserves a partial sequence.')
            buttons.button(W.QDialogButtonBox.StandardButton.Ok).setEnabled(needed + 2 * 1024**3 < free)
        frames.valueChanged.connect(update_budget)
        form.addRow('Maximum frames', frames)
        form.addRow('Maximum duration (s)', seconds)
        form.addRow(budget)
        form.addRow(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        update_budget()
        if dialog.exec() == W.QDialog.DialogCode.Accepted:
            directory = self.output_dir / ('sequence_' + stamp())
            self.session.start_recording(directory, frames.value(), duration_s=seconds.value())

    def tick(self):
        try:
            while True:
                callback, result, error = self.results.get_nowait()
                self.task_busy = False
                if error:
                    self.notify(f'{type(error).__name__}: {error}')
                else:
                    try:
                        callback(result)
                    except Exception as callback_error:
                        self.notify(f'{type(callback_error).__name__}: {callback_error}')
        except queue.Empty:
            pass
        if self.session:
            for event in self.session.poll_events():
                if event.get('path'):
                    if event.get('kind') == 'snapshot' and event.get('succeeded'):
                        self.add_recent(Path(event['path']))
                    elif event.get('kind') == 'recording' and event.get('done') and event.get('save_reopen_verified'):
                        self.add_recent(Path(event['path']), partial=event.get('partial', True))
                if event.get('kind') == 'error' or event.get('error'):
                    self.notify(str(event.get('error') or event))
                if event.get('kind') == 'state':
                    self.notify(f"Device state: {event.get('state', self.session.state)}")
            self.last_status = self.session.status()
            frame = self.session.latest_frame()
            if frame is not None and self.session.state in ('streaming', 'recording'):
                age = max(0.0, (time.monotonic_ns() - frame.metadata['host_monotonic_ns']) / 1e9)
                self.display_mode = 'FROZEN' if self.freeze.isChecked() else 'STALE' if age > 2 else 'LIVE'
                if not self.freeze.isChecked() and frame.identity != self.last_frame_identity:
                    self.displayed_frame = frame
                    self.last_frame_identity = frame.identity
                    meta = dict(frame.metadata, data_level='raw_frame', data_source='LIVE', acquisition_source='LIVE')
                    if frame.data.ndim == 3:
                        meta['channel_labels'] = list(str(meta.get('pixel_format', 'RGB8'))[:3])
                    self.set_cube(Cube(frame.data if frame.data.ndim == 3 else frame.data[..., None], meta), live=True)
                    self.session.mark_displayed(frame)
            elif self.displayed_frame is not None and self.display_mode in ('LIVE', 'FROZEN', 'STALE'):
                self.display_mode = 'REPLAY'
            self.update_controls()
            now = time.monotonic()
            if now - self.last_log >= 1:
                self.last_log = now
                self.update_status()
                if self.benchmark_log:
                    payload = dict(self.last_status, host_utc=datetime.now(timezone.utc).isoformat(),
                                   host_monotonic=now, display_mode=self.display_mode,
                                   rss_bytes=psutil.Process().memory_info().rss,
                                   ui_task_busy=self.task_busy, ui_result_queue=self.results.qsize())
                    self.background_log(payload)
            if self.closing and self.last_status.get('closed'):
                self.close()
        self.update_source_label()
        if self.closing and not self.task_busy and (not self.session or self.session.status().get('closed')):
            self.close()

    def background_log(self, payload):
        # One small telemetry record per second; the separate executor owns disk I/O.
        path = self.benchmark_log
        def write():
            with path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(payload, default=str) + '\n')
        if not self.task_busy:
            self.executor.submit(write)

    def update_status(self):
        status = self.last_status
        metrics = status.get('metrics', status)
        recording = status.get('recording') or {}
        def metric(name):
            value = metrics.get(name)
            return f'{value:.1f}' if isinstance(value, (int, float)) else '—'
        age = metrics.get('frame_age_s')
        age_text = f'{age * 1000:.0f}' if age is not None else '—'
        self.metrics_label.setText(f"Capture {metric('capture_fps')} fps  |  Display {metric('display_fps')} fps  |  Writer {recording.get('writer_fps', 0):.1f} fps  |  age {age_text} ms  |  preview drop {metrics.get('preview_dropped', '—')}  |  device gaps {metrics.get('device_frame_gaps', '—')}  |  writer queue {recording.get('queue_length', 0)}")
        frame_meta = status.get('frame_metadata') or {}
        connection = status.get('connection_metadata') or {}
        readback = frame_meta.get('readback_settings') or connection.get('readback_settings') or connection.get('current_settings') or {}
        self.readback_label.setText(f"Frame/session readback: {readback.get('PixelFormat', '—')} · {readback.get('ExposureTime', '—')} µs · gain {readback.get('Gain', '—')}\nPer-frame settings require chunk evidence.")
        if self.diagnostics.isVisible():
            self.detail_text.setPlainText(json_text({'profile': self.profile, 'session': status}))
        if status.get('state') == 'ready':
            for name, control, multiplier in (('ExposureTime', self.exposure, .001), ('Gain', self.gain, 1)):
                node = status.get('capabilities', {}).get(name, {})
                if isinstance(node.get('min'), (int, float)) and isinstance(node.get('max'), (int, float)):
                    control.setRange(node['min'] * multiplier, node['max'] * multiplier)
                    if isinstance(node.get('inc'), (int, float)) and node['inc'] > 0:
                        control.setSingleStep(node['inc'] * multiplier)
                    control.setToolTip(f"Device range {node['min']}–{node['max']} {node.get('unit', '')}; access {node.get('access')}")

    def update_controls(self):
        state = self.session.state if self.session else 'disconnected'
        self.connect_button.setEnabled(state in ('disconnected', 'error') and not self.task_busy)
        self.disconnect_button.setEnabled(state in ('ready', 'streaming', 'recording', 'error'))
        self.preview_button.setEnabled(state == 'ready')
        self.stop_button.setEnabled(state in ('streaming', 'recording'))
        self.record_button.setEnabled(state in ('streaming', 'recording'))
        self.record_button.setText('Stop recording' if state == 'recording' else 'Record…')
        self.save_button.setEnabled(self.cube is not None)
        for item in (self.format, self.exposure, self.gain, self.session_mode, self.apply_button):
            item.setEnabled(state in ('disconnected', 'ready'))

    def update_source_label(self):
        acquisition = self.cube.metadata.get('acquisition_source', self.cube.metadata.get('data_source', 'unknown')) if self.cube else 'unknown'
        level = self.cube.metadata.get('data_level') if self.cube else '—'
        frame_text = f' · #{self.displayed_frame.metadata.get("sequence")}' if self.displayed_frame is not None else ''
        self.mode_label.setText(f'{self.display_mode}{frame_text} · {level} · source {acquisition}')

    def set_cube(self, cube, *, live=False, reset_axis=True):
        old_shape = self.cube.shape if self.cube is not None else None
        self.cube = cube
        if not live:
            self.display_mode = 'SYNTHETIC' if cube.metadata.get('data_source') == 'SYNTHETIC' else 'REPLAY'
            self.displayed_frame = None
            self.product = None
            self.product_source = None
            self.derived_graphics.hide()
            self.roi_results = []
            if reset_axis:
                self.temporal_plot.clear()
        self.band.blockSignals(True)
        self.band.setRange(0, (self.sequence.frame_count - 1) if self.sequence else cube.shape[2] - 1)
        if not live and reset_axis:
            self.band.setValue(0)
        self.band.blockSignals(False)
        if old_shape != cube.shape:
            for control in (self.pair_a, self.pair_b):
                control.setMaximum(cube.shape[2] - 1)
            self.pair_b.setValue(min(1, cube.shape[2] - 1))
            self.reset_rois(force=True)
        self.render_current()
        if not live or old_shape != cube.shape:
            self.update_capabilities()
        if old_shape != cube.shape:
            self.fit()
        self.update_controls()
        self.update_source_label()

    def render_current(self):
        if self.cube is None:
            return
        raw = self.cube.data
        is_color = bool(self.cube.metadata.get('channel_labels'))
        band = min(self.band.value(), raw.shape[2] - 1)
        shown = raw if is_color else raw[..., band]
        if is_color and self.cube.metadata.get('channel_labels') == ['B', 'G', 'R']:
            shown = shown[..., ::-1]
        if self.view_mode.currentIndex() == 1 and not is_color:
            try:
                shown = bayer_cell_rgb(shown, self.cube.metadata)
            except ValueError as error:
                self.notify(str(error))
        if self.auto_levels.isChecked():
            self.levels = display_levels(shown)
        else:
            self.levels = (self.low.value(), max(self.low.value() + 1e-12, self.high.value()))
        self.image.setImage(shown, autoLevels=False, levels=self.levels)
        h, w = raw.shape[:2]
        self.image.setRect(QtCore.QRectF(0, 0, w, h))
        if self.overlay.isChecked():
            bits = self.cube.metadata.get('pfnc_sample_bits', self.cube.metadata.get('effective_bits'))
            limit = self.cube.metadata.get('saturation_value')
            if limit is None and bits:
                limit = 2 ** int(bits) - 1
            if limit is not None:
                saturated = np.any(raw >= limit, axis=2)
                rgba = np.zeros((h, w, 4), dtype=np.uint8)
                rgba[saturated] = [255, 50, 35, 125]
                self.saturation_overlay.setImage(rgba, autoLevels=False)
                self.saturation_overlay.show()
            else:
                self.saturation_overlay.hide()
        else:
            self.saturation_overlay.hide()
        if self.sequence:
            self.axis_label.setText(f'Time frame T={self.band.value()} / {self.sequence.frame_count - 1} · time axis, not spectral')
        elif is_color:
            self.axis_label.setText('R / G / B channels · not spectral')
        elif self.cube.wavelengths is not None:
            self.axis_label.setText(f"λ[{band}] = {self.cube.wavelengths[band]:g} {self.cube.metadata.get('wavelength_units') or 'unknown unit'} · {self.cube.metadata.get('wavelength_evidence', 'declared')}")
        else:
            self.axis_label.setText(f'Fixed optical state · DN' if raw.shape[2] == 1 else f'Scan state index {band} · not nm')
        if time.monotonic() - self.last_quality > 0.5:
            self.last_quality = time.monotonic()
            self.update_chart(shown)

    def fit(self):
        if self.cube is not None:
            h, w = self.cube.shape[:2]
            self.plot.setRange(xRange=(0, w), yRange=(0, h), padding=0.025)

    def one_to_one(self):
        box = self.plot.getViewBox()
        (x0, x1), (y0, y1) = box.viewRange()
        width, height = box.width(), box.height()
        box.setRange(xRange=((x0+x1-width)/2, (x0+x1+width)/2),
                     yRange=((y0+y1-height)/2, (y0+y1+height)/2), padding=0)

    def reset_rois(self, force=False):
        if self.cube is None or (self.rois and not force):
            return
        for roi in self.rois:
            self.plot.removeItem(roi)
        h, w = self.cube.shape[:2]
        self.rois = []
        for index, color in enumerate(('#ed9b3d', '#45a6ff')):
            roi = pg.RectROI([w * (0.18 + index * 0.42), h * 0.32], [max(1, w * 0.2), max(1, h * 0.25)],
                             pen=pg.mkPen(color, width=2), movable=True, rotatable=False,
                             maxBounds=QtCore.QRectF(0, 0, w, h))
            self.plot.addItem(roi)
            self.rois.append(roi)

    def rectangles(self):
        return [roi_rect(roi.pos(), roi.size(), self.cube.shape) for roi in self.rois]

    def pixel_hover(self, scene_position):
        if self.cube is None or not self.plot.sceneBoundingRect().contains(scene_position):
            return
        point = self.image.mapFromScene(scene_position)
        # ImageItem may display a half-resolution CFA image; scale back to raw coordinates.
        sx = self.cube.shape[1] / self.image.image.shape[1]
        sy = self.cube.shape[0] / self.image.image.shape[0]
        x, y = int(np.floor(point.x() * sx)), int(np.floor(point.y() * sy))
        if 0 <= x < self.cube.shape[1] and 0 <= y < self.cube.shape[0]:
            values = self.cube.data[y, x]
            finite = bool(np.all(np.isfinite(values)))
            if self.cube.valid_mask is not None:
                finite &= bool(np.all(self.cube.valid_mask[y, x]))
            self.pixel_label.setText(f'Raw pixel x={x}, y={y} · {np.array2string(values, precision=7, threshold=8)} · finite/mask={finite}')

    def update_chart(self, shown):
        if self.plot_mode.currentIndex() != 2:
            self.chart.getAxis('bottom').setTicks(None)
        from hyperlab.analysis.core import _quality
        cube = self.cube
        policy = self.policy.currentData()
        h, w, k = cube.shape
        band = min(self.band.value(), k - 1)
        channels = slice(None) if cube.metadata.get('channel_labels') else slice(band, band + 1)
        selection = (slice(None, None, max(1, h // 180)), slice(None, None, max(1, w // 240)), channels)
        raw_sample = cube.data[selection]
        good, quality, threshold = _quality(cube, raw_sample, selection, policy)
        eligible = raw_sample.size - np.count_nonzero(quality['invalid']) - np.count_nonzero(quality['ignored'])
        saturated = np.count_nonzero(quality['saturated'])
        sat = f'{100*saturated/eligible:.2f}% ({saturated}/{eligible} eligible)' if threshold is not None and eligible else 'unknown'
        raw_values = raw_sample[good].astype(np.float64)
        mean = f'{raw_values.mean():.2f}' if raw_values.size else 'unavailable'
        sample = np.asarray(shown)[::max(1, shown.shape[0] // 180), ::max(1, shown.shape[1] // 240)]
        values = sample[np.isfinite(sample)].astype(np.float64)
        grey = np.mean(sample, axis=2) if sample.ndim == 3 else sample
        gradients = np.diff(grey.astype(np.float64), axis=0)**2
        finite_gradients = gradients[np.isfinite(gradients)]
        focus = f'{finite_gradients.mean():.2f}' if finite_gradients.size else 'unavailable'
        self.quality_label.setText(f'Raw sample saturation {sat}\n{policy} mean {mean} · display focus {focus} (gradient heuristic)')
        self.quality_label.setToolTip('Saturation uses sampled raw sensor values, not CFA/RGB display derivatives. Eligible excludes nonfinite, masked and ignored samples; the mean follows the selected quality policy.')
        if values.size:
            if self.plot_mode.currentIndex() == 0:
                counts, edges = np.histogram(values, bins=128)
                self.curves[0].setData((edges[:-1] + edges[1:]) * 0.5, counts)
                self.curves[1].setData([], [])
                self.chart.setLabel('bottom', 'Displayed channel values · sampled histogram')
                self.chart.setLabel('left', 'Sample count')
            elif self.plot_mode.currentIndex() == 1:
                rects = self.rectangles()
                means = []
                for x0, y0, x1, y1 in rects:
                    roi_selection = (slice(y0, y1), slice(x0, x1), channels)
                    data = cube.data[roi_selection]
                    valid, _, _ = _quality(cube, data, roi_selection, policy)
                    means.append(float(np.mean(data[valid], dtype=np.float64)) if np.any(valid) else np.nan)
                self.temporal_plot.append((time.monotonic(), *means))
                history = np.asarray(self.temporal_plot)
                for index, curve in enumerate(self.curves):
                    curve.setData(history[:, 0] - history[0, 0], history[:, index + 1])
                self.chart.setLabel('bottom', 'Host elapsed time', units='s')
                self.chart.setLabel('left', f'ROI mean · {policy}', units=cube.metadata.get('units'))
        elif self.plot_mode.currentIndex() == 0:
            for curve in self.curves:
                curve.setData([], [])

    def update_capabilities(self):
        from hyperlab.analysis import capabilities
        cap = capabilities(self.cube)
        for op, button in self.analysis_buttons.items():
            button.setEnabled(cap['operations'].get(op, False))
            button.setToolTip(cap.get('reasons', {}).get(op, ''))
        self.capability_label.setText(f"{cap['axis_label']} · {cap['effective_dimensions']} enabled features\n" +
                                     '\n'.join(dict.fromkeys(cap.get('reasons', {}).values())))

    def analyze_rois(self):
        if self.cube is None:
            return
        from hyperlab.analysis import roi_statistics
        cube, rects, policy = self.cube, self.rectangles(), self.policy.currentData()
        self.background(lambda: [roi_statistics(cube, rect, policy=policy) for rect in rects],
                        self.show_rois, 'Computing ROI statistics in raw pixel coordinates…')

    def show_rois(self, results):
        self.roi_results = results
        self.plot_mode.setCurrentIndex(2)
        labels = results[0].get('channel_labels')
        self.chart.getAxis('bottom').setTicks([list(enumerate(labels))] if labels else None)
        common = np.all(np.isfinite([stats['mean'] for stats in results]), axis=0)
        shape_valid = True
        for index, stats in enumerate(results):
            means = stats['mean'].copy()
            if self.shape_normalize.isChecked():
                means[~common] = np.nan
                norm = np.linalg.norm(means[common])
                if np.any(common) and np.isfinite(norm) and norm > 0:
                    means /= norm
                else:
                    means[:] = np.nan
                    shape_valid = False
            x = stats.get('wavelengths')
            x = np.arange(len(means)) if x is None else x
            self.curves[index].setData(x, means)
        self.chart.setLabel('bottom', results[0].get('axis_label', 'index'), units=results[0].get('wavelength_units'))
        self.chart.setLabel('left', 'L2 normalized shape' if self.shape_normalize.isChecked() else results[0].get('units', 'unknown'))
        self.notify('ROI means updated. Shape normalization uses common finite features; CSV retains raw amplitudes.'
                    if shape_valid else 'Shape comparison unavailable: no common finite features or a zero ROI norm.')

    def export_rois(self):
        if self.cube is None:
            return
        from hyperlab.analysis import roi_statistics, export_roi_csv
        cube, rects, policy = self.cube, self.rectangles(), self.policy.currentData()
        names = [edit.text() for edit in self.roi_names]
        shape_branch = self.shape_normalize.isChecked()
        directory = self.output_dir / ('roi_' + stamp())
        def run():
            directory.mkdir()
            results = [roi_statistics(cube, rect, policy=policy) for rect in rects]
            branch = None
            if shape_branch:
                common = np.all(np.isfinite([stats['mean'] for stats in results]), axis=0)
                branch = {'operation': 'L2 normalization on common finite ROI features',
                          'feature_indices': np.flatnonzero(common).tolist(),
                          'excluded_indices': np.flatnonzero(~common).tolist(),
                          'excluded_reason': 'At least one ROI lacks a valid mean; original indices are retained',
                          'normalized_means': [], 'norms': [], 'valid': []}
                for stats in results:
                    norm = float(np.linalg.norm(stats['mean'][common]))
                    valid = bool(np.any(common) and np.isfinite(norm) and norm > 0)
                    values = np.full(stats['mean'].shape, np.nan)
                    if valid:
                        values[common] = stats['mean'][common] / norm
                    branch['normalized_means'].append([float(value) if np.isfinite(value) else None for value in values])
                    branch['norms'].append(norm if np.isfinite(norm) else None)
                    branch['valid'].append(valid)
            for index, stats in enumerate(results):
                stats.setdefault('metadata', {}).update(roi_name=names[index], source=cube.metadata)
                if branch is not None:
                    stats['metadata']['shape_comparison'] = {'operation': branch['operation'],
                        'feature_indices': branch['feature_indices'], 'excluded_indices': branch['excluded_indices'],
                        'norm': branch['norms'][index], 'valid': branch['valid'][index]}
                export_roi_csv(stats, directory / f'roi_{index + 1}.csv')
            (directory / 'comparison.json').write_text(json_text({'source': cube.metadata, 'rectangles': rects,
                'names': names, 'policy': policy, 'shape_branch': branch}), encoding='utf-8')
            return directory
        self.background(run, lambda path: self.notify(f'ROI CSV saved: {path}'), 'Exporting ROI values and provenance…')

    def analyze(self, operation):
        if self.cube is None:
            return
        from hyperlab.analysis import capabilities, pca, spectral_angle, difference, ratio, roi_statistics
        cap = capabilities(self.cube)
        if not cap['operations'].get(operation):
            self.notify(cap['reasons'].get(operation, 'This data does not support the operation'))
            return
        cube, rect, policy = self.cube, self.rectangles()[0], self.policy.currentData()
        reference_name = self.roi_names[0].text()
        a, b = self.pair_a.value(), self.pair_b.value()
        def run():
            if operation == 'pca':
                return pca(cube, min(3, cap['effective_dimensions']), policy=policy)
            if operation == 'spectral_angle':
                result = spectral_angle(cube, roi_statistics(cube, rect, policy=policy)['mean'], policy=policy)
                result['metadata']['reference_roi'] = {'name': reference_name, 'rect': list(rect),
                    'coordinates': 'raw pixels; half-open x0,y0,x1,y1 rectangle'}
                return result
            return (difference if operation == 'difference' else ratio)(cube, a, b, policy=policy)
        self.background(run, lambda result: self.show_product(result, cube), f'Computing {operation}…')

    def show_product(self, result, source_cube=None):
        self.product = result
        self.product_source = source_cube or self.cube
        shown = result.get('data', result.get('image'))
        if shown.ndim == 3:
            shown = shown[..., 0]
        self.derived_image.setImage(shown, autoLevels=False, levels=display_levels(shown))
        self.colorbar.setLevels(display_levels(shown))
        self.derived_graphics.show()
        self.images.setSizes([self.images.width() // 2] * 2)
        self.set_view_link(self.link_views.isChecked())
        self.notify('Derived values displayed; invalid pixels use NaN/mask. Raw data is unchanged.')

    def set_view_link(self, enabled):
        # Two aspect constraints with different viewport sizes feed range changes
        # back into each other. The raw view owns aspect; the linked map owns none.
        self.derived_plot.setAspectLocked(not enabled)
        self.derived_plot.setXLink(self.plot if enabled else None)
        self.derived_plot.setYLink(self.plot if enabled else None)

    def export_derived(self):
        if self.product is None:
            self.notify('Compute a derived result first.')
            return
        from hyperlab.analysis import export_product
        name, _ = W.QFileDialog.getSaveFileName(self, 'Export numeric values and mask', str(self.output_dir / ('derived_' + stamp() + '.npy')), 'NPY (*.npy);;ENVI (*.hdr)')
        if name:
            product, cube = self.product, self.product_source
            self.background(lambda: export_product(product, name, source_cube=cube),
                            lambda _: self.notify(f'Numeric values and mask exported: {name}'), 'Exporting derived arrays…')

    def export_display(self):
        if self.cube is None:
            return
        name, _ = W.QFileDialog.getSaveFileName(self, 'Display image (not raw data)', str(self.output_dir / ('display_' + stamp() + '.png')), 'PNG (*.png)')
        if not name:
            return
        from PIL import Image
        data, levels = self.image.image.copy(), tuple(self.levels)
        source = dict(self.cube.metadata)
        def run():
            path = Path(name)
            if path.exists():
                raise FileExistsError(path)
            image = np.nan_to_num(np.clip((data.astype(np.float64) - levels[0]) / (levels[1] - levels[0]), 0, 1) * 255).astype(np.uint8)
            Image.fromarray(image).save(path)
            path.with_suffix('.png.json').write_text(json_text({'data_level': 'display_image', 'source': source,
                 'levels': levels, 'note': 'Display stretch; not scientific raw values or calibrated sRGB'}), encoding='utf-8')
        self.background(run, lambda _: self.notify(f'Display image saved: {name}'), 'Saving the display derivative…')

    def open_dialog(self):
        name, _ = W.QFileDialog.getOpenFileName(self, 'Open raw array, ENVI or sequence.npy.json', str(self.output_dir),
                                               'Data (*.npy *.npz *.hdr *.json)')
        if name:
            self.open_path(Path(name))

    def open_path(self, path):
        if self.task_busy:
            self.notify('Wait for the current file operation to finish.')
            return
        if self.session and self.session.state in ('streaming', 'recording', 'stopping'):
            self.notify('Stop acquisition before opening replay data.')
            return
        path = Path(path)
        def read():
            if path.is_dir() or path.name in ('sequence.npy', 'sequence.npy.json'):
                from hyperlab.acquisition.sequence import load_sequence
                sequence = load_sequence(path.with_suffix('') if path.suffix == '.json' else path)
                if sequence.frame_count < 1:
                    sequence.close()
                    raise ValueError('This partial sequence has no persisted frames.')
                return sequence
            try:
                return load_cube(path)
            except ValueError as error:
                raise ValueError(f'{error}; use CLI inspect --axis-order for an NPY file without axis metadata.') from error
        def loaded(value):
            if self.sequence:
                self.sequence.close()
                self.sequence = None
            if self.cube is not None:
                self.cube.close()
            self.temporal_plot.clear()
            if isinstance(value, Cube):
                self.sequence = None
                self.set_cube(value)
            else:
                self.sequence = value
                self.band.blockSignals(True)
                self.band.setRange(0, value.frame_count - 1)
                self.band.setValue(0)
                self.band.blockSignals(False)
                self.band_changed(0)
            self.notify(f'Reopened {path}')
        self.background(read, loaded, 'Reopening local data…')

    def band_changed(self, index):
        if self.sequence:
            frame = self.sequence.frame(index)
            meta = dict(frame.metadata)
            if frame.data.ndim == 3:
                meta['channel_labels'] = list(str(meta.get('pixel_format', 'RGB8'))[:3])
            self.set_cube(Cube(frame.data if frame.data.ndim == 3 else frame.data[..., None],
                               dict(meta, data_level='raw_frame')), reset_axis=False)
        else:
            self.render_current()

    def synthetic(self):
        if self.task_busy:
            self.notify('Wait for the current file operation to finish.')
            return
        if self.session and self.session.state in ('streaming', 'recording', 'stopping'):
            self.notify('Stop acquisition before loading synthetic data.')
            return
        if self.sequence:
            self.sequence.close()
        self.sequence = None
        if self.cube is not None:
            self.cube.close()
        self.set_cube(make_synthetic_cube())

    def add_recent(self, path, *, partial=False):
        path = Path(path)
        if path.is_dir() and (path / 'frame.npy').exists():
            path = path / 'frame.npy'
        self.recent.append(path)
        item = W.QListWidgetItem(path.parent.name if path.name in ('frame.npy', 'manifest.json') else path.name)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, str(path))
        if partial:
            item.setText('PARTIAL · ' + item.text())
        self.recent_list.insertItem(0, item)
        while self.recent_list.count() > 20:
            self.recent_list.takeItem(20)
        self.notify(f'{"Partial sequence preserved" if partial else "Saved"}: {path}')

    def choose_output(self):
        name = W.QFileDialog.getExistingDirectory(self, 'Choose local output folder', str(self.output_dir))
        if name:
            self.output_dir = Path(name)
            self.output_edit.setText(name)

    def export_evidence(self):
        path = self.output_dir / ('session_evidence_' + stamp() + '.json')
        payload = {'profile': self.profile, 'status': self.last_status, 'display_mode': self.display_mode}
        self.background(lambda: path.write_text(json_text(payload), encoding='utf-8'),
                        lambda _: self.notify(f'Local evidence: {path}'), 'Saving evidence…')

    def register_reference(self):
        if self.cube is None or not self.cube.metadata.get('source_file'):
            self.notify('Save the current frame, then reopen it from Recent saves. References must point to immutable files.')
            return
        source = self.cube.metadata['source_file']
        record = {'kind': self.reference_kind.currentText(), 'path': source, 'label': self.scene_label.text(),
                  'conditions': self.conditions.toPlainText() or 'unknown', 'registered_at': stamp(),
                  'metadata': self.cube.metadata}
        path = self.output_dir / ('reference_' + stamp() + '.json')
        self.background(lambda: path.write_text(json_text(record), encoding='utf-8'),
                        lambda _: self._reference_added(record), 'Registering the reference file and conditions…')

    def _reference_added(self, record):
        item = W.QListWidgetItem(f"{record['kind']} · {record['label'] or Path(record['path']).parent.name}")
        item.setData(QtCore.Qt.ItemDataRole.UserRole, record)
        self.references.addItem(item)
        self.notify('Reference registration saved. A label does not establish spectral calibration.')

    def check_references(self):
        records = [item.data(QtCore.Qt.ItemDataRole.UserRole) for item in self.references.selectedItems()]
        if len(records) < 2:
            self.notify('Select at least two registered references.')
            return
        from hyperlab.experiments import matching_settings
        result = matching_settings([record['metadata'] for record in records])
        self.notify(json_text(result))

    def sequence_statistics(self):
        if not self.sequence:
            self.notify('Open a saved sequence.npy.json sidecar first.')
            return
        from hyperlab.experiments import summarize_sequence
        sequence = self.sequence
        directory = self.output_dir / ('temporal_' + stamp())
        self.background(lambda: summarize_sequence(sequence, directory),
                        lambda path: self.add_recent(Path(path) / 'mean.npy'), 'Accumulating frame means, temporal SD and drift…')

    def closeEvent(self, event):
        if self.session and not self.session.status().get('closed'):
            event.ignore()
            if not self.closing:
                self.closing = True
                self.notify('Stopping acquisition, persisting the recording checkpoint and releasing the camera before closing…')
                self.session.close(wait=False)
            return
        if self.task_busy:
            event.ignore()
            self.closing = True
            self.notify('Finishing the current file operation before closing.')
            return
        self.timer.stop()
        if self.sequence:
            self.sequence.close()
        if self.cube is not None:
            self.cube.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        event.accept()


    def _analysis_panel(self):
        form = self.panel()
        form.addWidget(W.QLabel('ROI coordinates always use raw pixels'))
        self.roi_names = []
        for index in range(2):
            row = W.QHBoxLayout()
            name = W.QLineEdit(f'ROI {chr(65 + index)}')
            self.roi_names.append(name)
            row.addWidget(name)
            show = W.QCheckBox('Show')
            show.setChecked(True)
            show.toggled.connect(lambda checked, i=index: self.rois[i].setVisible(checked) if len(self.rois) > i else None)
            row.addWidget(show)
            form.addLayout(row)
        form.addWidget(self.button('Reset both ROIs', lambda: self.reset_rois(force=True)))
        self.policy = W.QComboBox()
        self.policy.addItem('Diagnostic · include saturation', 'diagnostic')
        self.policy.addItem('Quantitative · exclude known saturation', 'quantitative')
        form.addWidget(self.policy)
        self.shape_normalize = W.QCheckBox('L2 normalized shape')
        self.shape_normalize.setToolTip('Compare curve shape over common valid features; exports retain raw amplitudes.')
        form.addWidget(self.shape_normalize)
        form.addWidget(self.button('Compare ROIs', self.analyze_rois, 'roi_compare'))
        form.addWidget(self.button('Export ROI CSV + provenance', self.export_rois, 'roi_export'))
        self.analysis_buttons = {}
        for label, op in [('PCA · mean centered', 'pca'), ('Angle from ROI A', 'spectral_angle')]:
            button = self.button(label, lambda checked=False, operation=op: self.analyze(operation), op)
            self.analysis_buttons[op] = button
            form.addWidget(button)
        pair = W.QHBoxLayout()
        self.pair_a, self.pair_b = W.QSpinBox(), W.QSpinBox()
        pair.addWidget(self.pair_a)
        pair.addWidget(self.pair_b)
        form.addLayout(pair)
        for label, op in [('Index A − B', 'difference'), ('Index A / B', 'ratio')]:
            button = self.button(label, lambda checked=False, operation=op: self.analyze(operation), op)
            self.analysis_buttons[op] = button
            form.addWidget(button)
        self.link_views = W.QCheckBox('Link raw / derived views')
        self.link_views.setChecked(True)
        self.link_views.toggled.connect(self.set_view_link)
        form.addWidget(self.link_views)
        form.addWidget(self.button('Export derived values + mask…', self.export_derived))
        form.addWidget(self.button('Export display image…', self.export_display))
        self.capability_label = W.QLabel('Load data to see available analysis')
        self.capability_label.setWordWrap(True)
        form.addWidget(self.capability_label)
        form.addWidget(self.button('Load synthetic example', self.synthetic, 'synthetic'))
        form.addStretch()

    def _calibration_panel(self):
        form = self.panel()
        form.addWidget(W.QLabel('1 · Sensor dark and repeatability'))
        self.scene_label = W.QLineEdit()
        self.scene_label.setPlaceholderText('Scene / specimen / region label')
        form.addWidget(self.scene_label)
        self.conditions = W.QPlainTextEdit()
        self.conditions.setPlaceholderText('Known lighting, angle, distance and occlusion; keep missing conditions unknown')
        self.conditions.setMaximumHeight(85)
        form.addWidget(self.conditions)
        self.reference_kind = W.QComboBox()
        self.reference_kind.addItems(['dark', 'reference', 'sample'])
        form.addWidget(self.reference_kind)
        form.addWidget(self.button('Register current file as reference', self.register_reference))
        form.addWidget(self.button('Check selected reference settings', self.check_references))
        self.references = W.QListWidget()
        self.references.setSelectionMode(W.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.references.setMaximumHeight(160)
        form.addWidget(self.references)
        form.addWidget(self.button('Temporal mean / SD / drift', self.sequence_statistics))
        form.addWidget(W.QLabel('2 · FP states and spectral response'))
        label = W.QLabel('Control protocol and state synchronization evidence are required. Wavelength response mapping is not configured.')
        label.setWordWrap(True)
        form.addWidget(label)
        form.addWidget(W.QLabel('3 · Reflectance reference correction'))
        note = W.QLabel('External spectral data can be corrected through the analysis API. Wavelength provenance, linear intensity and matched references are required; an ordinary white target cannot recover the FP response.')
        note.setWordWrap(True)
        form.addWidget(note)
        form.addStretch()


def launch(path=None, *, benchmark_log=None):
    app = W.QApplication.instance() or W.QApplication([])
    app.setApplicationName('HyperLab')
    app.setStyle('Fusion')
    app.setFont(QtGui.QFont('Segoe UI', 10))
    window = Workbench(path, benchmark_log=benchmark_log)
    screen = app.primaryScreen().availableGeometry()
    window.resize(min(1360, int(screen.width() * 0.95)), min(860, int(screen.height() * 0.93)))
    window.show()
    return app.exec()
