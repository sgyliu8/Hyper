"""Local Qt instrument workbench. Camera and disk work never run on the GUI thread."""
from __future__ import annotations

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
from hyperlab.ui.view import display_selection, display_levels, roi_rect
from hyperlab.plots import (COLORS, PlotSpec, TemporalTrace, source_identity,
                           roi_plot, map_plot, pca_diagnostics, export_figure_bundle)


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2,
                      default=lambda v: v.tolist() if isinstance(v, np.ndarray) else str(v))


class Workbench(W.QMainWindow):
    def __init__(self, path=None, *, session_factory=None, benchmark_log=None, workspace=None):
        super().__init__()
        self.setWindowTitle('HyperLab — Live workbench')
        self.resize(1220, 820)
        self.setMinimumSize(960, 620)
        self.session_factory = session_factory
        self.session = None
        from hyperlab.paths import load_config, workspace as resolve_workspace
        self.config = load_config()
        self.profile = self.config.get('device_profile')
        self.workspace = resolve_workspace(workspace)
        self._pending_state = self.config.get('ui', {})
        self.cube = None
        self.sequence = None
        self.displayed_frame = None
        self.display_mode = 'EMPTY'
        self.product = None
        self.product_source = None
        self.roi_results = []
        self.roi_result_context = None
        self.roi_source = None
        self.science_result = None
        self.annotation = None
        self.annotation_path = None
        self.plot_source = None
        self.plot_annotation = None
        self.completed_plot_mode = 0
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
        self.temporal_plot = TemporalTrace()
        self.plot_spec = None
        self.map_spec = None
        self.analysis_version = 0
        self.roi_colors = []
        self.roi_rows = []
        self.roi_labels = []
        self.roi_visible = []
        self._map_limits = {}
        self.roi_timer = QtCore.QTimer(self)
        self.roi_timer.setSingleShot(True)
        self.roi_timer.timeout.connect(self.analyze_rois)
        self.output_dir = self.workspace/'experiments'
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.benchmark_log = Path(benchmark_log) if benchmark_log else None
        if self.benchmark_log:
            self.benchmark_log.parent.mkdir(parents=True, exist_ok=True)
        self._build()
        from hyperlab.ui.state import restore_controls
        restore_controls(self, self._pending_state)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        if path:
            QtCore.QTimer.singleShot(0, lambda: self.open_path(Path(path)))
        elif self._pending_state.get('last_path'):
            saved = Path(self._pending_state['last_path'])
            if saved.exists():
                QtCore.QTimer.singleShot(0, lambda: self.open_path(saved))
            else:
                self.notify('Previous data file is missing. Select it in Recent files and use Locate.')
        elif self._pending_state.get('synthetic'):
            QtCore.QTimer.singleShot(0,self.synthetic)

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
        header.addWidget(self.button('Workspace…', self.choose_output, 'workspace'))
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
        self.tabs.currentChanged.connect(self.update_controls)
        self.vertical = W.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.images = W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setBackground('#1c2634')
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
        self.derived_graphics.setBackground('w')
        self.derived_plot = self.derived_graphics.addPlot(title='Derived values · invalid pixels are grey')
        self.derived_plot.setAspectLocked(True)
        self.derived_plot.invertY(True)
        self.derived_image = pg.ImageItem(axisOrder='row-major')
        self.derived_plot.addItem(self.derived_image)
        self.derived_invalid = pg.ImageItem(axisOrder='row-major')
        self.derived_invalid.setLookupTable(np.array([[0,0,0,0],[220,225,229,255]],dtype=np.uint8))
        self.derived_plot.addItem(self.derived_invalid)
        invalid_legend = self.derived_plot.addLegend(offset=(-12,-12),labelTextColor='#26313d',
            labelTextSize='10pt',brush=pg.mkBrush(255,255,255,230),pen='#c5cbd0')
        invalid_legend.addItem(pg.ScatterPlotItem(pen=None,symbol='s',size=10,
            brush='#dce1e5'),'Invalid / masked')
        self.colorbar = pg.ColorBarItem(values=(0, 1), colorMap=pg.colormap.get('viridis'), interactive=False)
        self.colorbar.axis.setWidth(85)
        self.colorbar.axis.enableAutoSIPrefix(False)
        self.colorbar.setImageItem(self.derived_image, insert_in=self.derived_plot)
        for axis in (self.derived_plot.getAxis('left'),self.derived_plot.getAxis('bottom'),self.colorbar.axis):
            axis.setPen(pg.mkPen('#26313d',width=1))
            axis.setTextPen('#26313d')
            axis.setTickFont(QtGui.QFont('Segoe UI',10))
            axis.enableAutoSIPrefix(False)
        self.images.addWidget(self.derived_graphics)
        self.derived_graphics.hide()
        self.vertical.addWidget(self.images)
        self.chart_row = W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.chart_row.setMinimumHeight(180)
        self.chart = pg.PlotWidget(background='w')
        self.chart.setLabel('left', 'DN / descriptive value')
        self.chart.showGrid(x=True, y=True, alpha=0.15)
        self.curves = [self.chart.plot(pen=pg.mkPen(c, width=2)) for c in ('#d47e22', '#247dc4')]
        self.chart_row.addWidget(self.chart)
        self.shape_chart = pg.PlotWidget(background='w')
        for chart in (self.chart,self.shape_chart):
            self._style_scientific_chart(chart)
        self.shape_chart.hide()
        self.chart_row.addWidget(self.shape_chart)
        self.vertical.addWidget(self.chart_row)
        self.vertical.setSizes([570, 140])
        split.addWidget(self.vertical)
        split.addWidget(self.side_scroll)
        split.setStretchFactor(0, 1)
        split.setSizes([920, 275])
        layout.addWidget(split, 1)
        axis = W.QHBoxLayout()
        self.axis_label = W.QLabel('Fixed optical state · no data loaded')
        self.band = W.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.band.setRange(0, 0)
        self.band.valueChanged.connect(self.band_changed)
        axis.addWidget(self.axis_label)
        axis.addWidget(self.band, 1)
        layout.addLayout(axis)
        self.analysis_label = W.QLabel('Analysis source: no computed chart')
        self.analysis_label.setWordWrap(True)
        layout.addWidget(self.analysis_label)
        self.pixel_label = W.QLabel('Pixel: —')
        self.pixel_label.setWordWrap(True)
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
        dl.addWidget(self.button('Preview redacted support report…', self.support_report))
        dl.addWidget(self.button('Hardware setup / About…', self.hardware_help))
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
        self.plot_mode.addItems(['PCA explained variance', 'PCA loadings'])
        self.plot_mode.addItem('Computed feature / recorded trace')
        self.plot_mode.currentIndexChanged.connect(self.chart_selected)
        self.quality_label = W.QLabel('Quality: —')
        self.quality_label.setWordWrap(True)
        form.addWidget(self.quality_label)
        form.addWidget(self.button('View quality / ROI counts…', self.quality_details))
        form.addWidget(W.QLabel('Recent saves · double-click to reopen'))
        self.recent_list = W.QListWidget()
        self.recent_list.setSelectionMode(W.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.recent_list.setMaximumHeight(130)
        self.recent_list.itemDoubleClicked.connect(lambda item: self.open_path(Path(item.data(QtCore.Qt.ItemDataRole.UserRole))))
        form.addWidget(self.recent_list)
        form.addWidget(self.button('Locate selected file…', self.locate_recent))
        form.addWidget(self.button('Compare two saved frames', self.compare_recent))
        form.addWidget(self.button('Open output folder', lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.output_dir)))))
        form.addStretch()

    def notify(self, text):
        self.message.setText(str(text))

    def background(self, function, callback, label):
        if self.closing or self.task_busy:
            self.notify('A background operation is still running.')
            return
        self.task_busy = True
        self.update_controls()
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
        from hyperlab.devices import discover_profiles
        previous = self.session
        if previous:
            previous.close(wait=False)
        def discover():
            if previous and not previous.close(wait=True):
                raise RuntimeError('Previous camera session has not released its resources.')
            return discover_profiles()
        self.background(discover, self.choose_profile, 'Checking the current device and runtime…')

    def choose_profile(self, report):
        profiles = report['profiles']
        if not profiles:
            self.device_label.setText(report['issues'][0]['code'].replace('_',' ').title() if report['issues'] else 'No camera')
            self.notify('\n'.join(item['message'] for item in report['issues']))
            return
        if len(profiles) == 1:
            selected = profiles[0]
        else:
            labels = [f"{i+1}. {p['name']} · identifier ending {p['serial'][-4:]} · runtime {Path(p['cti']).parent.name}"
                      for i,p in enumerate(profiles)]
            name,ok = W.QInputDialog.getItem(self,'Select imaging device','Discovered supported cameras',labels,0,False)
            if not ok:
                return
            selected = profiles[labels.index(name)]
        if self.profile and any(self.profile.get(key)!=selected.get(key) for key in ('serial','name','cti')):
            self.notify('Saved profile changed; selected device will be validated again on connection.')
        self._connect_profile(selected)

    def _connect_profile(self, profile):
        if self.closing:
            return
        from hyperlab.acquisition.camera import CameraSession
        self.profile = profile
        from hyperlab.devices import remember_profile
        remember_profile(profile)
        factory = self.session_factory or CameraSession
        options = {} if self.session_factory else {'phase_log': self.output_dir/('session-phases_'+stamp()+'.json')}
        self.session = factory(profile['cti'], profile['serial'], settings=self.requested_settings(),
                               mode=self.session_mode.currentData(), **options)
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
            self.map_spec = self.plot_spec = None
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
                failed = bool(error)
                if error:
                    self.notify(f'{type(error).__name__}: {error}')
                else:
                    try:
                        callback(result)
                    except Exception as callback_error:
                        failed = True
                        self.notify(f'{type(callback_error).__name__}: {callback_error}')
                if failed:
                    self.plot_mode.blockSignals(True)
                    self.plot_mode.setCurrentIndex(self.completed_plot_mode)
                    self.plot_mode.blockSignals(False)
                self.update_controls()
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
                    if event.get('kind') == 'error' and self.session.state == 'error':
                        from hyperlab.devices import connection_error_kind
                        self.device_label.setText(connection_error_kind(event.get('error') or event))
                    self.notify(str(event.get('error') or event))
                if event.get('kind') == 'state':
                    self.notify(f"Device state: {event.get('state', self.session.state)}")
            self.last_status = self.session.status()
            frame = self.session.latest_frame()
            if frame is not None and self.session.state in ('streaming', 'recording'):
                age = max(0.0, (time.monotonic_ns() - frame.metadata['host_monotonic_ns']) / 1e9)
                self.display_mode = 'FROZEN' if self.freeze.isChecked() else 'STALE' if self.last_status.get('stale', age > 2) else 'LIVE'
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
        screen_age = '—'
        if self.displayed_frame is not None and self.display_mode in ('LIVE','FROZEN','STALE'):
            screen_age = f"{max(0,time.monotonic_ns()-self.displayed_frame.metadata.get('host_monotonic_ns',time.monotonic_ns()))/1e6:.0f}"
        self.metrics_label.setText(f"Capture {metric('capture_fps')} fps  |  Display {metric('display_fps')} fps  |  Writer {recording.get('writer_fps', 0):.1f} fps  |  receive age {age_text} ms / screen age {screen_age} ms  |  preview drop {metrics.get('preview_dropped', '—')}  |  device gaps {metrics.get('device_frame_gaps', '—')}  |  writer queue {recording.get('queue_length', 0)}")
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
        self.record_button.setEnabled(state == 'recording' or (state == 'streaming' and
            self.last_status.get('has_current_frame', self.displayed_frame is not None)))
        self.record_button.setText('Stop recording' if state == 'recording' else 'Record…')
        self.save_button.setEnabled(self.cube is not None)
        active = state in ('streaming', 'recording')
        acquisition = self.tabs.currentIndex() == 0
        for item in (self.preview_button, self.save_button, self.record_button, self.freeze):
            item.setVisible(acquisition or active)
        self.stop_button.setVisible(acquisition or active)
        self.metrics_label.setVisible(self.session is not None)
        if hasattr(self, 'run_button'):
            self.method_changed()
        for item in (self.format, self.exposure, self.gain, self.session_mode, self.apply_button):
            item.setEnabled(state in ('disconnected', 'ready'))

    def update_source_label(self):
        acquisition = self.cube.metadata.get('acquisition_source', self.cube.metadata.get('data_source', 'unknown')) if self.cube else 'unknown'
        level = self.cube.metadata.get('data_level') if self.cube else '—'
        frame_text = f' · #{self.displayed_frame.metadata.get("sequence")}' if self.displayed_frame is not None else ''
        self.mode_label.setText(f'{self.display_mode}{frame_text} · {level} · source {acquisition}')

    def set_cube(self, cube, *, live=False, reset_axis=True):
        old_shape = self.cube.shape if self.cube is not None else None
        if self.annotation is not None and self.cube is not cube:
            self.annotation = None
            self.annotation_path = None
        self.cube = cube
        self.pixel_label.setText('Pixel: —')
        self.pixel_label.setToolTip('')
        if not live:
            if reset_axis:
                self.analysis_version += 1
                self.annotation = None
                self.annotation_path = None
                self.science_result = None
                self.roi_result_context = None
                self.roi_source = None
                self.plot_source = None
                self.plot_annotation = None
            self.display_mode = 'SYNTHETIC' if cube.metadata.get('data_source') == 'SYNTHETIC' else 'REPLAY'
            self.displayed_frame = None
            self.product = None
            self.product_source = None
            self.map_spec = None
            self.derived_graphics.hide()
            self.roi_results = []
            if reset_axis:
                self.temporal_plot.clear()
                self.plot_spec = None
                self.plot_mode.blockSignals(True)
                self.plot_mode.setCurrentIndex(0)
                self.plot_mode.blockSignals(False)
                self.last_quality = 0.0
        self.band.blockSignals(True)
        self.band.setRange(0, (self.sequence.frame_count - 1) if self.sequence else cube.shape[2] - 1)
        if not live and reset_axis:
            self.band.setValue(0)
        self.band.blockSignals(False)
        if old_shape != cube.shape:
            for control in (self.pair_a, self.pair_b, self.feature_first, self.feature_last):
                control.setMaximum(cube.shape[2] - 1)
            self.pair_b.setValue(min(1, cube.shape[2] - 1))
            self.feature_last.setValue(cube.shape[2] - 1)
        labels = cube.metadata.get('channel_labels') or [str(i) for i in range(cube.shape[2])]
        if labels != [self.trace_channel.itemText(i) for i in range(self.trace_channel.count())]:
            channel = max(0, self.trace_channel.currentIndex())
            self.trace_channel.blockSignals(True)
            self.trace_channel.clear()
            self.trace_channel.addItems(labels)
            self.trace_channel.setCurrentIndex(min(channel, len(labels)-1))
            self.trace_channel.blockSignals(False)
        if old_shape != cube.shape:
            self.reset_rois(force=True)
        self.render_current()
        if not live or old_shape != cube.shape:
            self.update_capabilities()
        if old_shape != cube.shape:
            self.fit()
        from hyperlab.ui.state import restore_view
        restore_view(self)
        self.update_controls()
        self.update_source_label()

    def chart_selected(self):
        if self.cube is None:
            return
        mode = self.plot_mode.currentIndex()
        unavailable = ((mode in (3, 4) and (self.product is None or 'scores' not in self.product))
                       or (mode == 5 and self.completed_plot_mode != 5))
        if unavailable:
            self.plot_mode.blockSignals(True)
            self.plot_mode.setCurrentIndex(self.completed_plot_mode)
            self.plot_mode.blockSignals(False)
            self.notify('Run the corresponding analysis before choosing this chart.')
            return
        if mode == 2:
            self.analyze_rois()
        else:
            self.update_chart(self.image.image)

    def render_current(self):
        if self.cube is None:
            return
        raw = self.cube.data
        is_color = bool(self.cube.metadata.get('channel_labels'))
        band = min(self.band.value(), raw.shape[2] - 1)
        try:
            selected = display_selection(self.cube, band, policy=self.policy.currentData(),
                                         cfa=self.view_mode.currentIndex() == 1 and not is_color)
        except ValueError as error:
            self.notify(str(error))
            selected = display_selection(self.cube, band, policy=self.policy.currentData())
        self.display_selection = selected
        shown = selected['image']
        if self.auto_levels.isChecked():
            self.levels = selected['levels']
        else:
            self.levels = (self.low.value(), max(self.low.value() + 1e-12, self.high.value()))
        self.image.setImage(shown, autoLevels=False, levels=self.levels)
        h, w = raw.shape[:2]
        self.image.setRect(QtCore.QRectF(0, 0, w, h))
        if self.overlay.isChecked():
            limit = selected['saturation_value']
            if limit is not None:
                saturated = selected['saturated_mask']
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
            self.update_chart(shown, selected=selected)

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

    def _roi_row(self, name, color):
        row = W.QWidget()
        layout = W.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = W.QLineEdit(name)
        edit.setStyleSheet(f'border-left: 4px solid {color};')
        layout.addWidget(edit, 1)
        show = W.QCheckBox('Show')
        show.setChecked(True)
        layout.addWidget(show)
        remove = self.button('×', lambda: self.remove_roi(self.roi_rows.index(row)))
        remove.setToolTip('Remove this ROI from the analysis definition')
        remove.setMaximumWidth(28)
        layout.addWidget(remove)
        self.roi_form.addWidget(row)
        self.roi_names.append(edit)
        self.roi_colors.append(color)
        self.roi_rows.append(row)
        self.roi_visible.append(show)
        edit.textChanged.connect(self.roi_changed)
        show.toggled.connect(lambda visible: self.set_roi_visible(self.roi_rows.index(row), visible))

    def set_roi_visible(self, index, visible):
        if index < len(self.rois):
            self.rois[index].setVisible(visible)
        self.roi_changed()

    def add_roi(self, name=None, rect=None, color=None):
        if len(self.roi_names) >= 8:
            self.notify('Up to eight rectangular ROIs are supported.')
            return
        index = len(self.roi_names)
        self._roi_row(name or f'ROI {chr(65+index)}', color or COLORS[index])
        if self.cube is not None:
            self._create_roi(index, rect)
        self.roi_changed()

    def _create_roi(self, index, rect=None):
        h, w = self.cube.shape[:2]
        if rect is None:
            x, y = w * (.12 + .26 * (index % 3)), h * (.22 + .28 * (index // 3))
            width, height = max(1, w * .2), max(1, h * .22)
        else:
            x, y, x1, y1 = rect
            width, height = x1-x, y1-y
        roi = pg.RectROI([x, y], [width, height], pen=pg.mkPen(self.roi_colors[index], width=2),
                         movable=True, rotatable=False, maxBounds=QtCore.QRectF(0,0,w,h))
        self.plot.addItem(roi)
        self.rois.append(roi)
        roi.setVisible(self.roi_visible[index].isChecked())
        label = pg.TextItem(self.roi_names[index].text(), color=self.roi_colors[index], anchor=(0,1))
        self.plot.addItem(label)
        self.roi_labels.append(label)
        roi.sigRegionChanged.connect(self.roi_changed)
        self._update_roi_labels()

    def _update_roi_labels(self):
        for i, roi in enumerate(self.rois):
            self.roi_labels[i].setVisible(roi.isVisible())
            self.roi_labels[i].setText(self.roi_names[i].text(), color=self.roi_colors[i])
            self.roi_labels[i].setPos(roi.pos())

    def roi_changed(self, *args):
        self.analysis_version += 1
        self._update_roi_labels()
        if self.cube is not None and self.plot_mode.currentIndex() == 2:
            self.roi_timer.start(160)

    def remove_roi(self, index):
        if not 0 <= index < len(self.roi_names):
            return
        if len(self.roi_names) <= 1:
            self.notify('Keep at least one ROI; use Show to hide its curve.')
            return
        row = self.roi_rows.pop(index)
        row.setParent(None)
        row.deleteLater()
        self.roi_names.pop(index)
        self.roi_visible.pop(index)
        self.roi_colors.pop(index)
        if index < len(self.rois):
            self.plot.removeItem(self.rois.pop(index))
            self.plot.removeItem(self.roi_labels.pop(index))
        self.roi_changed()

    def reset_rois(self, force=False):
        if self.cube is None or (self.rois and not force):
            return
        for item in [*self.rois, *self.roi_labels]:
            self.plot.removeItem(item)
        self.rois, self.roi_labels = [], []
        for index in range(len(self.roi_names)):
            self._create_roi(index)
        self.roi_changed()

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
            from hyperlab.analysis.core import _quality
            selection = (slice(y,y+1),slice(x,x+1),slice(None))
            valid, counts, _ = _quality(self.cube,self.cube.data[selection],selection,self.policy.currentData())
            self.pixel_label.setText(f'Raw pixel x={x}, y={y} · {np.array2string(values, precision=7, threshold=8)} · {self.policy.currentData()} valid channels {np.count_nonzero(valid)}/{valid.size}')
            self.pixel_label.setToolTip(json_text({name: int(mask.sum()) for name,mask in counts.items()}))

    def update_chart(self, shown, *, selected=None):
        if self.cube is None:
            return
        from hyperlab.analysis import roi_statistics
        cube, policy = self.cube, self.policy.currentData()
        band = min(self.band.value(), cube.shape[2]-1)
        if selected is None:
            try:
                selected = display_selection(cube, band, policy=policy,
                                            cfa=self.view_mode.currentIndex() == 1 and not cube.metadata.get('channel_labels'))
            except ValueError:
                selected = display_selection(cube, band, policy=policy)
        values = selected['values']
        counts = selected['raw_counts']
        eligible = counts['total'] - counts['invalid'] - counts['ignored']
        saturation = (f"{100*counts['saturated']/eligible:.2f}% ({counts['saturated']}/{eligible} eligible)"
                      if selected['saturation_value'] is not None and eligible else 'unknown')
        mean = f"{selected['raw_mean']:.2f}" if selected['raw_mean'] is not None else 'unavailable'
        self.quality_label.setText(f"{policy} mean {mean} · raw saturation {saturation}\n"
            f"Display histogram: {selected['sample_count']}/{selected['sample_total']} selected samples\n"
            'Invalid and ignored samples do not affect contrast.')
        self.quality_label.setToolTip(json_text({'raw_counts': counts, **{k:v for k,v in selected.items()
            if k not in ('image','valid_mask','values','saturated_mask')}}))
        mode = self.plot_mode.currentIndex()
        source = source_identity(cube)
        if mode == 0:
            y, edges = np.histogram(values, bins=128) if values.size else (np.array([]), np.array([0.]))
            spec = PlotSpec('lines', 'Sampled histogram', f"Value ({cube.metadata['units']})", 'Sample count',
                source=source, series=[{'name':policy, 'color':COLORS[0], 'style':'-',
                'x':(edges[:-1]+edges[1:])/2, 'y':y}] if values.size else [], metadata={k:v for k,v in selected.items()
                if k not in ('image','valid_mask','values','saturated_mask')}, caption=selected['interpretation'])
            self.draw_plot(spec)
        elif mode == 1:
            rects = self.rectangles()
            band = max(0, self.trace_channel.currentIndex())
            stats = [roi_statistics(cube, rect, policy=policy, bands=[band], robust=False) for rect in rects]
            means = [float(r['mean'][band]) for r in stats]
            definition = {'rectangles':rects, 'names':[edit.text() for edit in self.roi_names],
                          'policy':policy, 'band':band,
                          'source_file':cube.metadata.get('source_file'),
                          'session_id':cube.metadata.get('session_id'),
                          'stream_epoch':cube.metadata.get('stream_epoch'),
                          'settings':cube.metadata.get('readback_settings') or cube.metadata.get('current_settings')}
            # File replay uses recorded times, never UI playback cadence.
            meta = dict(cube.metadata, display_mode=self.display_mode)
            self.temporal_plot.add(meta, means, definition, sequence=self.sequence,
                                   index=self.band.value() if self.sequence else None)
            spec = self.temporal_plot.plot(definition['names'], self.roi_colors, source)
            spec.title += f' · channel {self.trace_channel.currentText()}'
            if not len(self.temporal_plot):
                spec.caption = 'A static frame has no temporal samples. Open a recorded sequence for time analysis.'
            self.draw_plot(spec)
        elif mode in (3,4) and self.product is not None and 'scores' in self.product:
            self._completed_source = self.product_source
            self.draw_plot(pca_diagnostics(self.product, self.product_source)[mode-3])
            self._completed_source = None

    @staticmethod
    def _style_scientific_chart(chart):
        chart.showGrid(x=True,y=True,alpha=.12)
        chart.plotItem.layout.setContentsMargins(8,8,12,8)
        for name in ('left','bottom'):
            axis = chart.getAxis(name)
            axis.setPen(pg.mkPen('#26313d',width=1))
            axis.setTextPen('#26313d')
            axis.setTickFont(QtGui.QFont('Segoe UI',10))
            axis.enableAutoSIPrefix(False)
        chart.getAxis('left').setWidth(82)
        chart.addLegend(offset=(-12,12),labelTextColor='#26313d',labelTextSize='10pt',
                        brush=pg.mkBrush(255,255,255,225),pen=None)

    def draw_plot(self, spec):
        was_comparison = bool(self.plot_spec and self.plot_spec.metadata.get('roi_comparison'))
        self.plot_spec = spec
        self.completed_plot_mode = self.plot_mode.currentIndex()
        self.plot_source = getattr(self, '_completed_source', None) or self.cube
        self.plot_annotation = spec.metadata.get('analysis_context', {}).get('annotation', self.annotation)
        origin = spec.source.get('acquisition_source') or spec.source.get('data_source') or 'UNKNOWN'
        frame = spec.source.get('sequence')
        source = (f"frame {frame} / stream {spec.source.get('stream_epoch')}" if frame is not None
                  else Path(spec.source.get('source_file') or 'in-memory example').name)
        self.analysis_label.setText(f'{source} · {origin} · {spec.ylabel}')
        self.analysis_label.setToolTip(spec.caption)
        self.chart.clear()
        legend = self.chart.plotItem.legend
        legend.clear()
        legend.setColumnCount(1 if len(spec.series)<=4 else 2)
        self.curves = []
        self.error_bars = []
        self.chart.setTitle(spec.title if any(np.any(np.isfinite(item['y'])) for item in spec.series) else spec.title+' · No valid samples',
                            color='#17212b',size='12pt')
        self.chart.setToolTip(spec.caption)
        # 0.14 can rescale ticks when disabling SI prefixes; empty ranges also
        # survive each setLabel call, keeping density/L2 ticks in printed units.
        label_style = {'color':'#26313d','font-size':'11pt','siPrefixEnableRanges':()}
        self.chart.setLabel('bottom', spec.xlabel,**label_style)
        self.chart.setLabel('left', spec.ylabel,**label_style)
        self.chart.getAxis('left').enableAutoSIPrefix(False)
        self.chart.getAxis('bottom').setTicks([list(enumerate(spec.categories))] if spec.categories else None)
        for item in spec.series:
            pen = pg.mkPen(item['color'], width=2.5,
                           style=QtCore.Qt.PenStyle.SolidLine if item.get('style','-') == '-' else QtCore.Qt.PenStyle.DashLine)
            curve = self.chart.plot(item['x'], item['y'], pen=pen, name=item['name'], connect='finite',
                                    symbol='o' if spec.categories or len(item['x'])<5 else None,
                                    symbolSize=8,symbolBrush=item['color'],symbolPen='w',antialias=True)
            curve.setZValue(2)
            self.curves.append(curve)
            if item.get('sd') is not None:
                if len(item['x']) == 1:
                    error = pg.ErrorBarItem(x=np.asarray(item['x']),y=np.asarray(item['y']),
                        height=2*np.asarray(item['sd']),beam=.12,pen=pg.mkPen(item['color'],width=2))
                    self.chart.addItem(error); self.error_bars.append(error)
                else:
                    low = pg.PlotCurveItem(item['x'], np.asarray(item['y'])-item['sd'], pen=None, connect='finite')
                    high = pg.PlotCurveItem(item['x'], np.asarray(item['y'])+item['sd'], pen=None, connect='finite')
                    self.chart.addItem(low); self.chart.addItem(high)
                    color = pg.mkColor(item['color']); color.setAlpha(44)
                    ribbon = pg.FillBetweenItem(low,high,brush=color)
                    ribbon.setZValue(-1); self.chart.addItem(ribbon)
            if item.get('lower') is not None:
                y = np.asarray(item['y'])
                if len(item['x']) == 1:
                    error = pg.ErrorBarItem(x=np.asarray(item['x']), y=y,
                        bottom=y-item['lower'], top=item['upper']-y, beam=.12,
                        pen=pg.mkPen(item['color'], width=2))
                    self.chart.addItem(error); self.error_bars.append(error)
                else:
                    low = pg.PlotCurveItem(item['x'], item['lower'], pen=None, connect='finite')
                    high = pg.PlotCurveItem(item['x'], item['upper'], pen=None, connect='finite')
                    self.chart.addItem(low); self.chart.addItem(high)
                    color = pg.mkColor(item['color']); color.setAlpha(44)
                    ribbon = pg.FillBetweenItem(low, high, brush=color)
                    ribbon.setZValue(-1); self.chart.addItem(ribbon)
        # Preserve the two default curve handles for existing integrations.
        while len(self.curves) < 2:
            self.curves.append(self.chart.plot([],[],pen=None))
        xs = np.concatenate([np.asarray(item['x']) for item in spec.series]) if spec.series else np.array([])
        xs = xs[np.isfinite(xs)]
        if spec.categories:
            self.chart.setXRange(-.5,len(spec.categories)-.5,padding=0)
        elif xs.size and xs.max()>xs.min():
            self.chart.setXRange(float(xs.min()),float(xs.max()),padding=.03)
        self.shape_chart.clear()
        self.shape_chart.plotItem.legend.clear()
        self.shape_chart.plotItem.legend.setColumnCount(1 if len(spec.series)<=4 else 2)
        self.shape_curves = []
        normalized = [item for item in spec.series if 'normalized' in item]
        distributions = [item for item in spec.series if 'distribution' in item]
        self.shape_chart.setVisible(bool(normalized or distributions))
        if normalized or distributions:
            units = spec.metadata.get('units', spec.ylabel.removeprefix('Mean (').removesuffix(')'))
            self.shape_chart.setTitle('ROI intensity distribution' if distributions else 'L2 normalized shape',
                                      color='#17212b',size='12pt')
            self.shape_chart.setLabel('bottom',f'Pixel intensity ({units})' if distributions else spec.xlabel,**label_style)
            self.shape_chart.setLabel('left',f'Density (1/{units})' if distributions else
                                      f"Normalized {spec.metadata.get('summary', 'mean')}",**label_style)
            self.shape_chart.getAxis('left').enableAutoSIPrefix(False)
            self.shape_chart.getAxis('bottom').setTicks([list(enumerate(spec.categories))] if spec.categories and not distributions else None)
            for item in distributions or normalized:
                x = item['distribution']['x'] if distributions else item['x']
                y = item['distribution']['y'] if distributions else item['normalized']
                pen = pg.mkPen(item['color'],width=2.5,
                    style=QtCore.Qt.PenStyle.SolidLine if item.get('style','-')=='-' else QtCore.Qt.PenStyle.DashLine)
                self.shape_curves.append(self.shape_chart.plot(x,y,pen=pen,name=item['name'],connect='finite',
                    antialias=True,symbol='o' if len(x)<5 else None,symbolSize=7,symbolBrush=item['color']))
            self.shape_chart.enableAutoRange()
        if spec.metadata.get('roi_comparison') and not was_comparison:
            self.chart_row.setSizes([1,1])
            self.vertical.setSizes([400,280])

    def update_capabilities(self):
        from hyperlab.analysis import capabilities
        cap = capabilities(self.cube)
        self.shape_normalize.setVisible(self.cube is None or self.cube.shape[2]>1)
        for op, button in self.analysis_buttons.items():
            button.setEnabled(cap['operations'].get(op, False))
            button.setToolTip(cap.get('reasons', {}).get(op, ''))
        self.method_changed()

    def analysis_context(self):
        return {'version':self.analysis_version, 'source':source_identity(self.cube),
                'rectangles':self.rectangles(), 'names':[name.text() for name in self.roi_names],
                'colors':list(self.roi_colors), 'visible':[item.isChecked() for item in self.roi_visible],
                'policy':self.policy.currentData(), 'normalized':self.shape_normalize.isChecked(),
                'spatial_sd':self.spatial_sd.isChecked(), 'summary':self.roi_summary.currentData(),
                'support':self.roi_support.currentData(), 'annotation':self.annotation,
                'method':self.analysis_method.currentData(), 'trace_channel':self.trace_channel.currentIndex(),
                'feature_interval':[self.feature_first.value(), self.feature_last.value()],
                'window':self.local_window.value(), 'degree':self.local_degree.value()}

    def analyze_rois(self):
        if self.cube is None or self.closing:
            return
        if self.task_busy:
            self.roi_timer.start(180)
            return
        from hyperlab.analysis import roi_comparison
        from hyperlab.experiment_metadata import compute_pinned
        cube, context = self.cube, self.analysis_context()
        def completed(payload):
            results, context['source_fingerprint'] = payload
            if context['version'] != self.analysis_version:
                self.notify('ROI definition changed; obsolete result discarded.')
                self.roi_timer.start(180)
                return
            self.roi_source = cube
            self.show_rois(results, context)
        self.background(lambda: compute_pinned(cube, lambda: roi_comparison(cube,context['rectangles'],
                        policy=context['policy'],support=context['support'])),
                        completed, 'Computing pinned ROI statistics…')

    def show_rois(self, results, context=None):
        context = context or self.analysis_context()
        self.roi_results = results
        self.roi_result_context = context
        self.roi_source = self.roi_source or self.cube
        self.science_result = None
        self.plot_mode.blockSignals(True)
        self.plot_mode.setCurrentIndex(2)
        self.plot_mode.blockSignals(False)
        enabled = [i for i,v in enumerate(context['visible']) if v]
        if not enabled:
            self.draw_plot(PlotSpec('lines','No visible ROI','Index','Mean'))
            return
        spec = roi_plot([results[i] for i in enabled], [context['names'][i] for i in enabled],
                        [context['colors'][i] for i in enabled], source=context['source'],
                        normalized=context['normalized'], spatial_sd=context['spatial_sd'], summary=context['summary'])
        spec.metadata['analysis_version'] = context['version']
        spec.metadata['analysis_context'] = context
        spec.metadata['source_fingerprint'] = context.get('source_fingerprint')
        self._completed_source = self.roi_source
        self.draw_plot(spec)
        self._completed_source = None
        self.notify('Shape comparison unavailable for a zero norm or missing common features; raw amplitude is retained.'
                    if any('normalized' in item and not np.any(np.isfinite(item['normalized'])) for item in spec.series)
                    else 'ROI results ready. Summary, spatial spread and sample counts are available in Results and Export.')

    def export_rois(self):
        if not self.roi_results or self.roi_result_context is None:
            self.notify('Run ROI analysis before exporting its completed results.')
            return
        from copy import deepcopy
        from hyperlab.analysis import export_roi_csv
        from hyperlab.plots import plain
        from hyperlab.experiment_metadata import source_fingerprint, write_analysis_manifest
        cube, results = self.roi_source, deepcopy(self.roi_results)
        context, feature_result = deepcopy(self.roi_result_context), deepcopy(self.science_result)
        selected = context.get('analyzed_roi_indices', range(len(results)))
        names = [context['names'][i] for i in selected]
        directory = self.output_dir / ('roi_' + stamp())
        def run():
            fingerprint = source_fingerprint(cube)
            if context.get('source_fingerprint') and fingerprint != context['source_fingerprint']:
                raise ValueError('Source changed since this ROI result was computed; run analysis again before exporting.')
            directory.mkdir()
            branch = None
            if context['normalized'] and cube.shape[2] > 1:
                visible = [i for i, original in enumerate(selected) if context['visible'][original]]
                if visible:
                    shape = roi_plot([results[i] for i in visible], [names[i] for i in visible],
                        COLORS, source=context['source'], normalized=True, summary=context['summary'])
                    branch = {'operation':shape.metadata['normalization'], 'summary':context['summary'],
                        'feature_indices':shape.metadata['common_feature_indices'], 'roi_indices':visible,
                        'normalized_summaries':plain([item['normalized'] for item in shape.series])}
                    if context['summary'] == 'mean':
                        branch['normalized_means'] = branch['normalized_summaries']
            for index, stats in enumerate(results):
                stats.setdefault('metadata', {}).update(roi_name=names[index], analysis_context=context)
                if branch is not None and index in branch['roi_indices']:
                    stats['metadata']['shape_comparison'] = branch
                export_roi_csv(stats, directory / f'roi_{index + 1}.csv')
            payload = {'source':cube.metadata, 'analysis_context':context, 'feature_result':feature_result,
                       'shape_branch':branch}
            (directory / 'comparison.json').write_text(json.dumps(plain(payload), indent=2, allow_nan=False), encoding='utf-8')
            if feature_result:
                import csv
                with (directory / 'features.csv').open('x', newline='', encoding='utf-8') as stream:
                    writer = csv.writer(stream)
                    if 'pairs' in feature_result:
                        keys = ['target','reference','bias','rmse','correlation','angle','feature_count','unavailable']
                        writer.writerow(keys)
                        for pair in feature_result['pairs']:
                            writer.writerow([json.dumps(plain(pair[key])) if key == 'unavailable' else pair[key] for key in keys])
                    else:
                        writer.writerow(['roi','feature','value'])
                        for curve in feature_result['curves']:
                            for key,value in curve['features'].items():
                                writer.writerow([names[curve['roi_index']], key, value])
            write_analysis_manifest(directory, fingerprint, payload, annotation=context['annotation'])
            return directory
        self.background(run, lambda path: self.notify(f'Completed ROI tables and manifest saved: {path}'),
                        'Exporting completed ROI results and source hashes…')

    def analyze(self, operation):
        if self.cube is None:
            return
        from hyperlab.analysis import capabilities, pca, spectral_angle, difference, ratio, roi_statistics
        cap = capabilities(self.cube)
        gate = {'reference_rmse':'roi', 'normalized_difference':'ratio'}.get(operation, operation)
        if not cap['operations'].get(gate):
            self.notify(cap['reasons'].get(gate, 'This data does not support the operation'))
            return
        cube, rect, policy = self.cube, self.rectangles()[0], self.policy.currentData()
        reference_name = self.roi_names[0].text()
        context = self.analysis_context()
        a, b = self.pair_a.value(), self.pair_b.value()
        minimum_denominator = self.minimum_denominator.value()
        context.update(pair_indices=[a, b], minimum_denominator=minimum_denominator)
        if operation in ('spectral_angle', 'reference_rmse'):
            context['support'] = 'common'
        def run():
            if operation == 'pca':
                return pca(cube, min(3, cap['effective_dimensions']), policy=policy)
            if operation in ('spectral_angle', 'reference_rmse'):
                from hyperlab.analysis.maps import reference_rmse
                stats = roi_statistics(cube, rect, policy=policy, support='common')
                reference = stats[context['summary']]
                result = (spectral_angle if operation == 'spectral_angle' else reference_rmse)(cube, reference, policy=policy)
                result['metadata']['reference_roi'] = {'name': reference_name, 'rect': list(rect),
                    'coordinates': 'raw pixels; half-open x0,y0,x1,y1 rectangle',
                    'used_counts':stats['count'].tolist(), 'quality_counts':{k:v.tolist() for k,v in stats['counts'].items()}}
                result['metadata'].update(summary=context['summary'], reference_support='common')
                return result
            if operation == 'difference':
                return difference(cube, a, b, policy=policy)
            from hyperlab.analysis.maps import normalized_difference
            return (normalized_difference if operation == 'normalized_difference' else ratio)(
                cube, a, b, policy=policy, minimum_denominator=minimum_denominator)
        def completed(result):
            result, context['source_fingerprint'] = result
            result['metadata']['analysis_context'] = context
            result['metadata']['source_fingerprint'] = context['source_fingerprint']
            if context['version'] != self.analysis_version:
                self.notify('Analysis definition changed; obsolete result discarded. Compute again with the new ROI.')
                return
            self.show_product(result, cube)
        from hyperlab.experiment_metadata import compute_pinned
        self.roi_timer.stop()
        self.background(lambda:compute_pinned(cube, run), completed, f'Computing pinned {operation}…')

    def analyze_roi_features(self, operation):
        if self.cube is None:
            return
        from hyperlab.analysis import roi_comparison
        from hyperlab.analysis.roi_features import roi_pairwise, spectral_roi_features
        from hyperlab.plots import roi_feature_plot, roi_pair_plot
        cube, context = self.cube, self.analysis_context()
        visible = [i for i, flag in enumerate(context['visible']) if flag]
        if not visible:
            self.notify('Show at least one ROI before analysis.')
            return
        rects = [context['rectangles'][i] for i in visible]
        names = [context['names'][i] for i in visible]
        colors = [context['colors'][i] for i in visible]
        first, last = context['feature_interval']
        bands = list(range(first, last+1)) if operation != 'pairs' else None
        support = 'common' if operation != 'pairs' else context['support']
        context.update(support=support, feature_indices=bands, analyzed_roi_indices=visible)
        self.roi_timer.stop()
        def run():
            results = roi_comparison(cube, rects, policy=context['policy'], bands=bands, support=support)
            if operation == 'pairs':
                result = roi_pairwise(cube, results, names, summary=context['summary'])
                spec = roi_pair_plot(cube, results, result, colors)
            else:
                result = spectral_roi_features(cube, results, operation, summary=context['summary'], bands=bands,
                    window=context['window'], degree=context['degree'])
                spec = roi_feature_plot(result, names, colors, source=context['source'])
            spec.metadata['analysis_context'] = context
            return result, spec, results
        def completed(payload):
            payload, context['source_fingerprint'] = payload
            if context['version'] != self.analysis_version:
                self.notify('Analysis definition changed; obsolete result discarded.')
                return
            self.science_result, spec, self.roi_results = payload
            spec.metadata['source_fingerprint'] = context['source_fingerprint']
            self.roi_source, self.roi_result_context = cube, context
            self.plot_mode.blockSignals(True); self.plot_mode.setCurrentIndex(5); self.plot_mode.blockSignals(False)
            self._completed_source = cube
            self.draw_plot(spec)
            self._completed_source = None
            self.notify('Analysis complete. Results includes numeric features, support counts and unavailable-metric reasons.')
        from hyperlab.experiment_metadata import compute_pinned
        self.background(lambda:compute_pinned(cube, run), completed, f'Computing {operation} on pinned ROI summaries…')

    def science_results_dialog(self):
        if not self.roi_results:
            self.notify('Run an ROI analysis before opening Results.')
            return
        dialog = W.QDialog(self); dialog.setWindowTitle('ROI results · descriptive statistics')
        dialog.resize(960, 570); layout = W.QVBoxLayout(dialog); tabs = W.QTabWidget(); layout.addWidget(tabs)
        context = self.roi_result_context or self.analysis_context()
        selected = context.get('analyzed_roi_indices', range(len(self.roi_results)))
        names = [context['names'][i] for i in selected]
        columns = ['ROI', 'Feature', 'Mean', 'SD', 'Median', 'Q25', 'Q75', 'IQR', 'MAD', 'Min', 'Max',
                   'Used', 'Policy valid', 'Total', 'Saturated', 'Used fraction']
        rows = []
        for name, result in zip(names, self.roi_results):
            for i in range(len(result['mean'])):
                labels = result.get('channel_labels')
                label = labels[i] if labels else (f"{result['wavelengths'][i]:g} {result['wavelength_units']}"
                    if result.get('wavelengths') is not None else str(i))
                rows.append([name, label, *[result.get(key, np.full(len(result['mean']), np.nan))[i]
                    for key in ('mean','std','median','q25','q75','iqr','mad','min','max')], result['count'][i],
                    *[result['counts'][key][i] for key in ('valid','total','saturated')], result.get('used_fraction', [np.nan]*len(result['mean']))[i]])
        def table(label, headers, values):
            widget = W.QTableWidget(len(values), len(headers)); widget.setHorizontalHeaderLabels(headers)
            widget.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
            for row, values in enumerate(values):
                for col, value in enumerate(values):
                    text = 'Unavailable' if value is None or isinstance(value, (float,np.floating)) and not np.isfinite(value) else (
                        f'{value:.7g}' if isinstance(value, (float,np.floating)) else str(value))
                    widget.setItem(row, col, W.QTableWidgetItem(text))
            widget.resizeColumnsToContents(); tabs.addTab(widget, label)
        table('ROI summary', columns, rows)
        if self.science_result and 'pairs' in self.science_result:
            table('Pair metrics', ['Target','Reference','Bias','RMSE','Correlation','Angle (rad)','Features','Unavailable reasons'],
                [[p['target'],p['reference'],p['bias'],p['rmse'],p['correlation'],p['angle'],p['feature_count'],
                  '; '.join(f'{k}: {v}' for k,v in p['unavailable'].items())] for p in self.science_result['pairs']])
        if self.science_result and 'curves' in self.science_result:
            table('Spectral features', ['ROI','Feature','Value'],
                [[names[curve['roi_index']], key, value] for curve in self.science_result['curves']
                 for key,value in curve['features'].items()])
        text = W.QPlainTextEdit(json_text({'context':context, 'result':self.science_result,
            'denominators':'Used counts apply to all displayed summary statistics; spatial spread is not a confidence interval.'}))
        text.setReadOnly(True); tabs.addTab(text, 'Recipe and provenance')
        layout.addWidget(self.button('Close', dialog.accept))
        self._science_results_dialog = dialog
        dialog.show()

    def annotation_dialog(self):
        if self.cube is None:
            self.notify('Open source data before adding specimen context.')
            return
        from hyperlab.ui.annotation_dialog import AnnotationDialog
        self._annotation_dialog = AnnotationDialog(self)
        self._annotation_dialog.show()

    def reference_correction_dialog(self):
        from hyperlab.ui.reference_dialog import ReferenceCorrectionDialog
        self._reference_dialog = ReferenceCorrectionDialog(self, sample=self.cube, workspace=self.workspace)
        self._reference_dialog.show()

    def show_product(self, result, source_cube=None):
        self.product = result
        self.product_source = source_cube or self.cube
        count = result['scores'].shape[2] if 'scores' in result else 1
        self.pc_component.blockSignals(True)
        selected = min(self.pc_component.currentIndex(), count-1)
        self.pc_component.clear()
        self.pc_component.addItems([f'PC{i+1} score' for i in range(count)])
        self.pc_component.setCurrentIndex(max(0, selected))
        self.pc_component.setEnabled(count > 1)
        self.pc_component.blockSignals(False)
        source = source_identity(self.product_source)
        source['units'] = self.product_source.metadata.get('units')
        spec = map_plot(result, source, component=max(0, selected), degrees=self.angle_degrees.isChecked())
        key = (spec.title, spec.colour_label)
        if self.lock_map_limits.isChecked() and key in self._map_limits:
            spec.limits = self._map_limits[key]
        self._map_limits[key] = spec.limits
        self.map_spec = spec
        self.derived_image.setImage(spec.image, autoLevels=False, levels=spec.limits)
        self.derived_invalid.setImage((~spec.valid_mask).astype(np.uint8),autoLevels=False,levels=(0,1))
        cmap = pg.colormap.get(spec.colormap, source='matplotlib')
        self.colorbar.setColorMap(cmap)
        self.colorbar.setLevels(spec.limits)
        label_style = {'color':'#26313d','font-size':'11pt','siPrefixEnableRanges':()}
        self.colorbar.axis.setLabel(spec.colour_label,**label_style)
        self.derived_plot.setTitle(spec.title,color='#17212b',size='12pt')
        self.derived_graphics.setToolTip(spec.caption)
        self.derived_plot.setLabel('bottom', spec.xlabel,**label_style)
        self.derived_plot.setLabel('left', spec.ylabel,**label_style)
        self.derived_graphics.show()
        self.images.setSizes([self.images.width() // 2] * 2)
        self.set_view_link(self.link_views.isChecked())
        identity = source.get('sequence')
        label = f'frame {identity}' if identity is not None else Path(source.get('source_file') or 'current data').name
        self.notify(f'Pinned result from {label}; units and invalid mask retained. Raw data is unchanged.')
        if 'scores' in result:
            self.plot_mode.setCurrentIndex(3)
            self._completed_source = self.product_source
            self.draw_plot(pca_diagnostics(result, self.product_source)[0])
            self._completed_source = None

    def refresh_product(self):
        if self.product is not None:
            self.show_product(self.product, self.product_source)

    def figure_export(self):
        choices = {'Current chart': self.plot_spec}
        sources = {'Current chart': (self.plot_source, self.plot_annotation)}
        if self.map_spec:
            choices['Derived map'] = self.map_spec
            sources['Derived map'] = (self.product_source,
                self.map_spec.metadata.get('analysis_context', {}).get('annotation'))
        choices = {name:spec for name,spec in choices.items() if spec is not None}
        if not choices:
            self.notify('Display a chart or compute a map before Figure export.')
            return
        dialog = W.QDialog(self)
        dialog.setWindowTitle('Figure export · SVG / PDF / PNG and source data')
        form = W.QFormLayout(dialog)
        selected = W.QComboBox(); selected.addItems(list(choices))
        form.addRow('Figure', selected)
        title = W.QLineEdit(next(iter(choices.values())).title)
        form.addRow('Title', title)
        selected.currentTextChanged.connect(lambda name: title.setText(choices[name].title))
        width, height, dpi = W.QSpinBox(), W.QSpinBox(), W.QSpinBox()
        for control, minimum, maximum, value, label in ((width,60,400,180,'Width (mm)'),
                (height,50,400,115,'Height (mm)'), (dpi,72,1200,300,'PNG DPI')):
            control.setRange(minimum, maximum); control.setValue(value); form.addRow(label,control)
        form.addRow(W.QLabel('Editable vector text; map pixels rasterized. CSV / NPY / PlotSpec accompany the figures.'))
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Save | W.QDialogButtonBox.StandardButton.Cancel)
        form.addRow(buttons)
        def save():
            if self.task_busy:
                self.notify('Wait for the current background operation before exporting.'); return
            from dataclasses import replace
            spec = replace(choices[selected.currentText()], title=title.text())
            directory = self.output_dir / ('figure_' + stamp())
            width_mm, height_mm, output_dpi = width.value(), height.value(), dpi.value()
            source_cube, annotation = sources[selected.currentText()]
            dialog.accept()
            self.background(lambda: export_figure_bundle(spec, directory, width_mm=width_mm,
                            height_mm=height_mm, dpi=output_dpi, source_cube=source_cube, annotation=annotation),
                            lambda path: self.notify(f'Figure and source-data bundle saved: {path}'), 'Rendering publication figure…')
        buttons.accepted.connect(save); buttons.rejected.connect(dialog.reject)
        self._figure_dialog = dialog
        dialog.show()

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
                self.band_changed(0, reset_axis=True)
            self.notify(f'Reopened {path}')
        self.background(read, loaded, 'Reopening local data…')

    def band_changed(self, index, *, reset_axis=False):
        if self.sequence:
            frame = self.sequence.frame(index)
            meta = dict(frame.metadata)
            if frame.data.ndim == 3:
                meta.setdefault('channel_labels', list(str(meta.get('pixel_format', 'RGB8'))[:3]))
            self.set_cube(Cube(frame.data if frame.data.ndim == 3 else frame.data[..., None],
                               dict(meta, data_level='raw_frame')), reset_axis=reset_axis)
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
        if not path.exists():
            item.setText('MISSING · ' + item.text())
        if partial:
            item.setText('PARTIAL · ' + item.text())
        self.recent_list.insertItem(0, item)
        while self.recent_list.count() > 20:
            self.recent_list.takeItem(20)
        self.notify(f'{"Partial sequence preserved" if partial else "Saved"}: {path}')

    def choose_output(self):
        name = W.QFileDialog.getExistingDirectory(self, 'Choose data workspace', str(self.workspace))
        if name:
            from hyperlab.paths import select_workspace
            try:
                self.workspace = select_workspace(name)
                self.output_dir = self.workspace/'experiments'
                self.output_dir.mkdir(parents=True,exist_ok=True)
                self.output_edit.setText(str(self.output_dir))
                self.notify(f'Workspace saved: {self.workspace}')
            except (ValueError,OSError) as error:
                self.notify(str(error))

    def locate_recent(self):
        item = self.recent_list.currentItem()
        if item is None:
            self.notify('Select a recent file first.')
            return
        old = item.data(QtCore.Qt.ItemDataRole.UserRole)
        name,_ = W.QFileDialog.getOpenFileName(self,'Locate the moved data file',str(self.workspace),
                                              'Data (*.npy *.npz *.hdr *.json)')
        if name:
            item.setData(QtCore.Qt.ItemDataRole.UserRole,name)
            item.setData(QtCore.Qt.ItemDataRole.UserRole+1,{'previous_path':old,'association':'user-selected; not byte-verified'})
            item.setText(Path(name).name)
            self.open_path(Path(name))

    def compare_recent(self):
        paths = [item.data(QtCore.Qt.ItemDataRole.UserRole) for item in self.recent_list.selectedItems()]
        if len(paths) != 2:
            self.notify('Ctrl-click two saved frames in Recent saves. Sequence comparison uses temporal statistics.')
            return
        from hyperlab.experiments import compare_saved_frames
        path = self.output_dir / ('saved_comparison_' + stamp() + '.json')
        policy = self.policy.currentData()
        def run():
            report = compare_saved_frames(paths, policy=policy)
            path.write_text(json_text(report), encoding='utf-8')
            return report
        def completed(report):
            self.notify(f'Saved-frame comparison: {path}')
            self.detail_text.setPlainText(json_text(report))
            lines = [f"Whole-frame statistics · {policy}",
                     f"Acquisition settings: {report['matching_settings']['status']}"]
            for index, item in enumerate(report['files']):
                stats = item['summary']['per_channel']
                labels = stats.get('channel_labels') or [str(i) for i in range(len(stats['mean']))]
                means = ', '.join(f'{label}: {value:.6g}' if value is not None else f'{label}: unavailable'
                                  for label, value in zip(labels, stats['mean']))
                lines.append(f"\n{chr(65 + index)} · {Path(item['path']).name}\nMean ({item['summary']['units']}): {means}\nSpatial SD: {stats['std']}\nValid samples: {stats['count']}")
            lines.append('\nFrames are not registered. These are descriptive field statistics, not pixelwise change or a material diagnosis.')
            self.comparison_dialog = W.QMessageBox(W.QMessageBox.Icon.Information, 'Saved-frame comparison',
                                                   '\n'.join(lines), W.QMessageBox.StandardButton.Ok, self)
            self.comparison_dialog.open()
        self.background(run, completed, 'Comparing whole-frame statistics of two saved files…')

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
        def register():
            from hyperlab.calibration import file_digest, applicability
            record.update(sha256=file_digest(source), applicability=applicability(record['metadata']))
            path.write_text(json_text(record),encoding='utf-8')
        self.background(register,
                        lambda _: self._reference_added(record), 'Registering the reference file and conditions…')

    def _reference_added(self, record):
        item = W.QListWidgetItem(f"{record['kind']} · {record['label'] or Path(record['path']).parent.name}")
        item.setData(QtCore.Qt.ItemDataRole.UserRole, record)
        self.references.addItem(item)
        if not Path(record['path']).exists():
            item.setText('MISSING · '+item.text())
        self.notify('Reference registration saved. A label does not establish spectral calibration.')

    def check_references(self):
        records = [item.data(QtCore.Qt.ItemDataRole.UserRole) for item in self.references.selectedItems()]
        if len(records) < 2:
            self.notify('Select at least two registered references.')
            return
        from hyperlab.experiments import matching_settings
        if any(record.get('device_compatibility')=='MISMATCH' or not Path(record['path']).exists() for record in records):
            self.notify('Reference device mismatch or missing file. Locate and check applicability before use.')
            return
        result = matching_settings([record['metadata'] for record in records])
        self.notify(json_text(result))

    def locate_reference(self):
        item = self.references.currentItem()
        if item is None:
            self.notify('Select a registered reference first.')
            return
        record = item.data(QtCore.Qt.ItemDataRole.UserRole)
        name,_ = W.QFileDialog.getOpenFileName(self,'Locate reference array',str(self.workspace),'Arrays (*.npy *.npz *.hdr)')
        if not name:
            return
        from hyperlab.calibration import locate_reference
        def complete(updated):
            item.setData(QtCore.Qt.ItemDataRole.UserRole,updated)
            item.setText(f"{updated['kind']} · {updated['label'] or Path(name).name}")
            self.notify(f"Reference relocated: {updated['relocation_evidence']}; previous provenance retained.")
        self.background(lambda: locate_reference(record,name),complete,'Checking relocated reference…')

    def export_reference_bundle(self):
        records = [item.data(QtCore.Qt.ItemDataRole.UserRole) for item in self.references.selectedItems()]
        if not records:
            self.notify('Select the references to export. This package contains private data.')
            return
        from hyperlab.calibration import export_references
        path = self.output_dir/('private_references_'+stamp()+'.zip')
        self.background(lambda:export_references(records,path),lambda p:self.notify(f'Private reference package: {p}'),
                        'Packaging selected private references…')

    def import_reference_bundle(self):
        name,_ = W.QFileDialog.getOpenFileName(self,'Import private reference package',str(self.workspace),'Reference package (*.zip)')
        if not name:
            return
        from hyperlab.calibration import import_references
        directory = self.workspace/'references'/stamp()
        serial = (self.profile or {}).get('serial')
        def complete(records):
            for record in records:
                self._reference_added(record)
            self.notify('References imported. Device applicability recorded; no calibration applied.')
        self.background(lambda:import_references(name,directory,device_serial=serial),complete,'Checking reference package…')

    def support_report(self):
        from hyperlab.support import redacted_report
        payload = redacted_report(self.last_status)
        dialog = W.QDialog(self); dialog.setWindowTitle('Preview redacted support report')
        dialog.resize(650,520)
        layout = W.QVBoxLayout(dialog)
        text = W.QPlainTextEdit(json_text(payload)); text.setReadOnly(True); layout.addWidget(text)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Save | W.QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        if dialog.exec()==W.QDialog.DialogCode.Accepted:
            path = self.output_dir/('support_redacted_'+stamp()+'.json')
            path.write_text(json_text(payload),encoding='utf-8')
            self.notify(f'Redacted report saved locally: {path}. Nothing was transmitted.')

    def hardware_help(self):
        from hyperlab import __version__
        dialog = W.QDialog(self); dialog.setWindowTitle('HyperLab setup and support scope')
        dialog.resize(680,540); layout = W.QVBoxLayout(dialog)
        text = W.QTextBrowser(); text.setOpenExternalLinks(True)
        text.setHtml(f'<h2>HyperLab {__version__}</h2><p>Research preview. Original-code license and public release are pending.</p>'
            '<h3>1. Offline</h3><p>Open data or Load synthetic example. No camera or vendor runtime is needed.</p>'
            '<h3>2. Image acquisition</h3><p>Windows x64, supported mvBlueFOX3 module, official USB3 Vision driver, '
            'Balluff Impact Acquire 3.7.2 and Harvester 1.4.3. Install the vendor runtime from its official source; '
            'an administrator approves driver installation. HyperLab does not bundle or silently install drivers.</p>'
            '<p>Connect discovers candidates; choose the intended device when more than one is present. '
            'A missing Python package, runtime, OS driver or device is distinct from a communication fault.</p>'
            '<h3>3. Spectroscopy</h3><p>Requires verified FP state control and device-specific calibration. '
            'USB-A / USB-C are connector shapes, not proof of image/control roles.</p>'
            '<p><a href="https://assets.balluff.com/documents/DRF_957356_AA_000/Troubleshooting_Windows_USB3VisionDeviceIsNotShownOrCannotBeUsed.html">Official Balluff USB3 Vision setup guidance</a></p>')
        layout.addWidget(text); button=self.button('Close',dialog.accept); layout.addWidget(button); dialog.exec()

    def plot_recorded_rois(self):
        if not self.sequence:
            self.notify('Open a recorded sequence first; a static image has no time trend.')
            return
        from hyperlab.plots import recorded_roi_plot
        context,sequence = self.analysis_context(),self.sequence
        cube = self.cube
        def completed(spec):
            spec, context['source_fingerprint'] = spec
            if context['version'] != self.analysis_version or sequence is not self.sequence:
                self.notify('Recorded ROI definition changed; obsolete curve discarded.')
                return
            spec.metadata['analysis_context'] = context
            spec.metadata['source_fingerprint'] = context['source_fingerprint']
            self.plot_mode.blockSignals(True); self.plot_mode.setCurrentIndex(5); self.plot_mode.blockSignals(False)
            self._completed_source = cube
            self.draw_plot(spec)
            self._completed_source = None
        from hyperlab.experiment_metadata import compute_pinned
        self.roi_timer.stop()
        self.background(lambda:compute_pinned(cube, lambda:recorded_roi_plot(sequence,context['rectangles'],
                        context['names'],context['colors'], policy=context['policy'], band=context['trace_channel'])),
                        completed,'Computing all recorded ROI samples…')

    def quality_details(self):
        payload = {'display': self.quality_label.toolTip(),
                   'rois': self.plot_spec.record() if self.plot_spec else None}
        dialog = W.QDialog(self); dialog.setWindowTitle('Validity and pinned ROI statistics')
        dialog.resize(700,520); layout = W.QVBoxLayout(dialog)
        text = W.QPlainTextEdit(json_text(payload)); text.setReadOnly(True); layout.addWidget(text)
        layout.addWidget(self.button('Close',dialog.accept)); dialog.exec()

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
        self.roi_timer.stop()
        from hyperlab.ui.state import save_state
        try:
            save_state(self)
        except (OSError,ValueError) as error:
            self.notify(f'Could not save workspace settings: {error}')
        if self.sequence:
            self.sequence.close()
        if self.cube is not None:
            self.cube.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        event.accept()


    def apply_roi_bounds(self, index, bounds):
        if self.cube is None or not 0 <= index < len(self.rois) or index >= len(self.rois):
            raise ValueError('Load an image and select an existing ROI first.')
        if len(bounds) != 4 or any(not isinstance(value, (int, np.integer)) for value in bounds):
            raise ValueError('ROI bounds must be four integer raw-pixel coordinates.')
        x0, y0, x1, y1 = (int(value) for value in bounds)
        h, w = self.cube.shape[:2]
        if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
            raise ValueError('ROI must be nonempty: 0 ≤ x0 < x1 ≤ width and 0 ≤ y0 < y1 ≤ height.')
        roi = self.rois[index]
        roi.setPos((x0, y0), update=False)
        roi.setSize((x1 - x0, y1 - y0))
        self.notify(f'{self.roi_names[index].text()}: raw bounds ({x0}, {y0}, {x1}, {y1}).')
        return x0, y0, x1, y1

    def edit_roi_bounds(self):
        if self.cube is None or not self.rois:
            self.notify('Load an image before editing ROI bounds.')
            return
        dialog = W.QDialog(self)
        dialog.setWindowTitle('Edit ROI bounds · raw pixels')
        dialog.setObjectName('roi_bounds_dialog')
        form = W.QFormLayout(dialog)
        target = W.QComboBox()
        target.setObjectName('roi_bounds_target')
        target.addItems([f'{chr(65 + index)} · {name.text()}' for index, name in enumerate(self.roi_names)])
        form.addRow('ROI', target)
        h, w = self.cube.shape[:2]
        controls = []
        for name, minimum, maximum in (('x0', 0, w - 1), ('y0', 0, h - 1), ('x1', 1, w), ('y1', 1, h)):
            control = W.QSpinBox()
            control.setObjectName('roi_bound_' + name)
            control.setRange(minimum, maximum)
            controls.append(control)
            form.addRow(name, control)
        note = W.QLabel('Half-open raw pixels: x0 ≤ x < x1 and y0 ≤ y < y1.')
        note.setWordWrap(True)
        form.addRow(note)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok | W.QDialogButtonBox.StandardButton.Cancel)
        form.addRow(buttons)

        def validate():
            x0, y0, x1, y1 = (control.value() for control in controls)
            valid = x0 < x1 and y0 < y1
            buttons.button(W.QDialogButtonBox.StandardButton.Ok).setEnabled(valid)
            note.setText('Half-open raw pixels: x0 ≤ x < x1 and y0 ≤ y < y1.' if valid
                         else 'Choose nonempty bounds: x0 < x1 and y0 < y1.')

        def load_bounds(index):
            for control, value in zip(controls, self.rectangles()[index]):
                control.setValue(value)
            validate()

        def accept():
            try:
                self.apply_roi_bounds(target.currentIndex(), tuple(control.value() for control in controls))
            except ValueError as error:
                note.setText(str(error))
            else:
                dialog.accept()

        for control in controls:
            control.valueChanged.connect(validate)
        target.currentIndexChanged.connect(load_bounds)
        buttons.accepted.connect(accept)
        buttons.rejected.connect(dialog.reject)
        load_bounds(0)
        dialog.exec()

    def _analysis_panel(self):
        form = self.panel()
        self.roi_names = []
        self.roi_form = W.QVBoxLayout()
        form.addLayout(self.roi_form)
        self._roi_row('ROI A', COLORS[0])
        self._roi_row('ROI B', COLORS[1])
        row = W.QHBoxLayout()
        row.addWidget(self.button('Add ROI', lambda: self.add_roi(), 'add_roi'))
        row.addWidget(self.button('Bounds…', self.edit_roi_bounds, 'roi_edit_bounds'))
        form.addLayout(row)
        self.policy = W.QComboBox()
        self.policy.addItem('Include saturation', 'diagnostic')
        self.policy.addItem('Exclude known saturation', 'quantitative')
        self.policy.setToolTip('Pixel inclusion policy; excluding saturation does not establish radiometric calibration.')
        self.roi_summary = W.QComboBox()
        self.roi_summary.addItem('Mean / spatial SD', 'mean')
        self.roi_summary.addItem('Median / Q25–Q75', 'median')
        self.roi_support = W.QComboBox()
        self.roi_support.addItem('Per-feature valid pixels', 'per_band')
        self.roi_support.addItem('Common pixels across features', 'common')
        for control in (self.policy, self.roi_summary, self.roi_support):
            form.addWidget(control)
            control.currentIndexChanged.connect(self.roi_changed)
        self.policy.currentIndexChanged.connect(lambda: self.render_current())
        self.analysis_method = W.QComboBox()
        self.analysis_buttons = {}
        methods = [('ROI summary', 'roi'), ('ROI pair comparison', 'pairs'),
                   ('Reference ROI RMSE map', 'reference_rmse'), ('Normalized difference map', 'normalized_difference'),
                   ('Difference map', 'difference'), ('Ratio map', 'ratio'),
                   ('Local polynomial smoothing', 'smooth'), ('First derivative', 'derivative1'),
                   ('Second derivative', 'derivative2'), ('Interval integral / mean', 'integral'),
                   ('Endpoint continuum / band depth', 'continuum'), ('PCA', 'pca'),
                   ('Spectral / state-vector angle', 'spectral_angle'), ('Recorded ROI trace', 'recorded')]
        for label, operation in methods:
            self.analysis_method.addItem(label, operation)
            action = QtGui.QAction(label, self)
            action.triggered.connect(lambda checked=False, op=operation: self.analyze(op))
            self.analysis_buttons[operation] = action
        self.analysis_method.currentIndexChanged.connect(self.method_changed)
        form.addWidget(self.analysis_method)
        self.pair_controls = W.QWidget()
        pair = W.QFormLayout(self.pair_controls); pair.setContentsMargins(0, 0, 0, 0)
        self.pair_a, self.pair_b = W.QSpinBox(), W.QSpinBox()
        pair.addRow('Feature A', self.pair_a); pair.addRow('Feature B', self.pair_b)
        self.minimum_denominator = W.QDoubleSpinBox()
        self.minimum_denominator.setDecimals(8); self.minimum_denominator.setRange(1e-8, 1e12)
        self.minimum_denominator.setValue(1e-6)
        pair.addRow('Min. |denominator|', self.minimum_denominator)
        form.addWidget(self.pair_controls)
        self.spectral_controls = W.QWidget()
        spectral = W.QFormLayout(self.spectral_controls); spectral.setContentsMargins(0, 0, 0, 0)
        self.feature_first, self.feature_last = W.QSpinBox(), W.QSpinBox()
        spectral.addRow('First stored feature', self.feature_first)
        spectral.addRow('Last stored feature', self.feature_last)
        self.local_window, self.local_degree = W.QSpinBox(), W.QSpinBox()
        self.local_window.setRange(3, 101); self.local_window.setSingleStep(2); self.local_window.setValue(5)
        self.local_degree.setRange(1, 6); self.local_degree.setValue(2)
        spectral.addRow('Window (odd)', self.local_window); spectral.addRow('Polynomial degree', self.local_degree)
        form.addWidget(self.spectral_controls)
        self.trace_channel = W.QComboBox(); self.trace_channel.addItem('0')
        self.trace_channel.setToolTip('Stored channel for time traces; channels are never averaged together.')
        self.trace_channel.currentIndexChanged.connect(self.roi_changed)
        for control in (self.pair_a, self.pair_b, self.minimum_denominator, self.feature_first,
                        self.feature_last, self.local_window, self.local_degree):
            control.valueChanged.connect(self.roi_changed)
        form.addWidget(self.trace_channel)
        self.run_button = self.button('Run analysis', self.run_analysis, 'roi_compare')
        self.run_button.setStyleSheet('background:#147b83; color:white; padding:8px; font-weight:600')
        form.addWidget(self.run_button)
        row = W.QHBoxLayout()
        row.addWidget(self.button('Results…', self.science_results_dialog, 'science_results'))
        export = W.QToolButton(); export.setText('Export…')
        export.setPopupMode(W.QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = W.QMenu(export)
        for label, callback in [('Publication figure + data', self.figure_export), ('ROI tables + recipe', self.export_rois),
                                ('Derived array + mask', self.export_derived), ('Display image', self.export_display)]:
            menu.addAction(label, callback)
        export.setMenu(menu); row.addWidget(export); form.addLayout(row)
        form.addWidget(self.button('Specimen / thermal context…', self.annotation_dialog, 'annotation'))
        details = W.QToolButton(); details.setText('Plot and view options ▸'); details.setCheckable(True)
        form.addWidget(details)
        options = W.QWidget(); options_form = W.QVBoxLayout(options); options_form.setContentsMargins(0, 0, 0, 0)
        details.toggled.connect(options.setVisible)
        options_form.addWidget(self.plot_mode)
        self.shape_normalize = W.QCheckBox('L2 normalized shape')
        self.shape_normalize.setToolTip('Amplitude is retained. Normalization uses common finite features.')
        self.spatial_sd = W.QCheckBox('Show spatial spread (SD / IQR)'); self.spatial_sd.setChecked(True)
        for control in (self.shape_normalize, self.spatial_sd):
            options_form.addWidget(control); control.toggled.connect(self.roi_changed)
        self.pc_component = W.QComboBox(); self.pc_component.addItem('PC1 score'); self.pc_component.setEnabled(False)
        self.pc_component.currentIndexChanged.connect(self.refresh_product); options_form.addWidget(self.pc_component)
        self.angle_degrees = W.QCheckBox('Angle in degrees'); self.angle_degrees.toggled.connect(self.refresh_product)
        self.lock_map_limits = W.QCheckBox('Share map limits'); self.lock_map_limits.setChecked(True)
        self.link_views = W.QCheckBox('Link image views'); self.link_views.setChecked(True)
        self.link_views.toggled.connect(self.set_view_link)
        for control in (self.angle_degrees, self.lock_map_limits, self.link_views):
            options_form.addWidget(control)
        options_form.addWidget(self.button('Reset ROI geometry', lambda: self.reset_rois(force=True)))
        options_form.addWidget(self.button('Load synthetic example', self.synthetic, 'synthetic'))
        form.addWidget(options); options.hide()
        self.capability_label = W.QLabel('Open data to analyze')
        self.capability_label.setWordWrap(True); form.addWidget(self.capability_label)
        form.addStretch()

    def method_changed(self):
        if not hasattr(self, 'run_button'):
            return
        from hyperlab.analysis import capabilities
        operation = self.analysis_method.currentData()
        spectral = operation in ('smooth', 'derivative1', 'derivative2', 'integral', 'continuum')
        self.pair_controls.setVisible(operation in ('difference', 'ratio', 'normalized_difference'))
        self.spectral_controls.setVisible(spectral)
        self.local_window.setEnabled(operation in ('smooth', 'derivative1', 'derivative2'))
        self.local_degree.setEnabled(self.local_window.isEnabled())
        self.trace_channel.setVisible(operation == 'recorded' or self.plot_mode.currentIndex() == 1)
        if self.cube is None:
            self.run_button.setEnabled(False)
            return
        cap = capabilities(self.cube)
        gate = {'pairs':'roi', 'reference_rmse':'roi', 'normalized_difference':'ratio',
                'smooth':'spectral_features', 'derivative1':'spectral_features',
                'derivative2':'spectral_features', 'integral':'spectral_features'}.get(operation, operation)
        allowed = bool(self.sequence) if operation == 'recorded' else cap['operations'].get(gate, False)
        self.run_button.setEnabled(allowed and not self.task_busy)
        if spectral:
            note = 'Common pixel support; measured wavelengths only.'
        elif operation in ('reference_rmse', 'spectral_angle'):
            note = 'First ROI is the reference; all enabled features must be valid.'
        else:
            note = 'ROI bounds use raw pixels.'
        if not allowed:
            note = 'Open a recorded sequence.' if operation == 'recorded' else cap['reasons'].get(gate, 'Unavailable for these data.')
        self.capability_label.setText(f"{cap['axis_kind']} · {cap['effective_dimensions']} features · {self.cube.metadata['units']}\n{note}")

    def run_analysis(self):
        operation = self.analysis_method.currentData()
        if operation == 'roi':
            self.analyze_rois()
        elif operation == 'recorded':
            self.plot_recorded_rois()
        elif operation in ('pairs', 'smooth', 'derivative1', 'derivative2', 'integral', 'continuum'):
            self.analyze_roi_features(operation)
        else:
            self.analyze(operation)

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
        form.addWidget(self.button('Locate selected reference…',self.locate_reference))
        form.addWidget(self.button('Export selected private references',self.export_reference_bundle))
        form.addWidget(self.button('Import private reference package…',self.import_reference_bundle))
        form.addWidget(self.button('Temporal mean / SD / drift', self.sequence_statistics))
        form.addWidget(self.button('Plot all recorded ROI samples',self.plot_recorded_rois))
        form.addWidget(W.QLabel('2 · FP states and spectral response'))
        label = W.QLabel('Control protocol and state synchronization evidence are required. Wavelength response mapping is not configured.')
        label.setWordWrap(True)
        form.addWidget(label)
        form.addWidget(W.QLabel('3 · Reflectance reference correction'))
        form.addWidget(self.button('Reflectance correction…', self.reference_correction_dialog, 'reflectance_correction'))
        note = W.QLabel('Requires documented wavelengths, linear intensity and applicable sample / white / dark references.')
        note.setWordWrap(True)
        form.addWidget(note)
        form.addStretch()


def launch(path=None, *, benchmark_log=None):
    app = W.QApplication.instance() or W.QApplication([])
    app.setApplicationName('HyperLab')
    app.setStyle('Fusion')
    app.setFont(QtGui.QFont('Segoe UI', 10))
    try:
        window = Workbench(path, benchmark_log=benchmark_log)
    except ValueError as error:
        if 'workspace' not in str(error).lower():
            raise
        W.QMessageBox.warning(None,'Choose a writable workspace',str(error))
        directory = W.QFileDialog.getExistingDirectory(None,'Choose a writable data workspace')
        if not directory:
            return 2
        from hyperlab.paths import select_workspace
        select_workspace(directory)
        window = Workbench(path, benchmark_log=benchmark_log, workspace=directory)
    screen = app.primaryScreen().availableGeometry()
    if not window.config.get('ui',{}).get('geometry'):
        window.resize(min(1360, int(screen.width() * 0.95)), min(860, int(screen.height() * 0.93)))
    window.show()
    return app.exec()
