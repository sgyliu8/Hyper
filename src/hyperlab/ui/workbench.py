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


class TimedImageItem(pg.ImageItem):
    def __init__(self, timings, **kwargs):
        super().__init__(**kwargs)
        self.timings = timings

    def paint(self, *args):
        with self.timings.measure('qt_image_paint'):
            return super().paint(*args)


class Workbench(W.QMainWindow):
    def __init__(self, path=None, *, session_factory=None, benchmark_log=None, workspace=None):
        super().__init__()
        self.setWindowTitle('HyperLab')
        self.resize(1220, 820)
        self.setMinimumSize(960, 620)
        self.session_factory = session_factory
        self.session = None
        self.discovering = False
        self.connection_issue = None
        self.follow_camera = False
        self.full_resolution_view = False
        from hyperlab.profiling import StageTimings
        self.timings = StageTimings()
        self._last_tick_ns = None
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
        self.recording_receipt = None
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
        self.roi_included = []
        self.roi_records = []
        self.roi_fills = []
        self.roi_source_notice = ''
        self.reference_roi_id = None
        self.right_spec = None
        self.map_distributions = None
        self.map_brushes = []
        self._right_task_pending = False
        self._brush_pending = False
        self._right_request = 0
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
        self.device_label = W.QLabel('Camera: Disconnected')
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
        header.addWidget(self.button('Session details', lambda: self.diagnostics.setVisible(not self.diagnostics.isVisible())))
        layout.addLayout(header)
        self.tabs = W.QTabBar()
        for text in ('Acquisition', 'Analysis', 'Calibration'):
            self.tabs.addTab(text)
        layout.addWidget(self.tabs)
        actions = W.QHBoxLayout()
        self.preview_button = self.button('▶ Start preview', self.start_preview, 'preview')
        self.preview_button.setStyleSheet('QPushButton {background:#147b83; color:white; font-weight:600; padding:9px 18px;} '
            'QPushButton:disabled {background:#dfe7eb; color:#71808b;}')
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
        self.recording_label = W.QLabel()
        self.recording_label.setObjectName('recording_result')
        self.recording_label.setWordWrap(True)
        self.recording_label.hide()
        layout.addWidget(self.recording_label)
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
        self.image = TimedImageItem(self.timings, axisOrder='row-major')
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
        self.brush_overlay = pg.ScatterPlotItem(pen=None, brush=pg.mkBrush(193, 73, 124, 180), size=4)
        self.derived_plot.addItem(self.brush_overlay)
        self.brush_mask_overlay = pg.ImageItem(axisOrder='row-major')
        self.brush_mask_overlay.setLookupTable(np.array([[0,0,0,0],[193,73,124,100]],np.uint8))
        self.derived_plot.addItem(self.brush_mask_overlay)
        self.source_cursor = [pg.InfiniteLine(angle=angle, pen=pg.mkPen('#b04d77', width=1)) for angle in (0, 90)]
        self.map_cursor = [pg.InfiniteLine(angle=angle, pen=pg.mkPen('#b04d77', width=1)) for angle in (0, 90)]
        for plot, lines in ((self.plot, self.source_cursor), (self.derived_plot, self.map_cursor)):
            for line in lines:
                line.hide(); plot.addItem(line, ignoreBounds=True)
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
        self.source_label = W.QLabel('Viewed data: none')
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)
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
        self.derived_graphics.scene().sigMouseMoved.connect(self.map_hover)
        self.message = W.QLabel('Connect opens a real camera session. Preview is not recorded by default.')
        self.message.setWordWrap(True)
        self.statusBar().addWidget(self.message, 1)
        self.diagnostics = W.QDockWidget('Session details · current state and historical telemetry', self)
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
        def measured():
            with self.timings.measure('background_operation'):
                return function()
        future = self.executor.submit(measured)
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
        self.discovering = True
        self.connection_issue = None
        self.background(discover, self.choose_profile, 'Checking the current device and runtime…')

    def choose_profile(self, report):
        self.discovering = False
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
            self.close_source_dialogs()
            if self.sequence:
                self.sequence.close()
                self.sequence = None
            if self.cube is not None:
                self.cube.close()
                self.cube = None
            self.product = self.product_source = None
            self.right_spec = self.map_distributions = None
            self.map_brushes = []
            self.map_tools.hide()
            self.brush_overlay.clear(); self.brush_mask_overlay.clear()
            self.map_spec = self.plot_spec = None
            self.plot_source = self.roi_source = None
            self.roi_result_context = None
            self.science_result = None
            self.plot_annotation = None
            self.roi_results = []
            self.display_mode = 'EMPTY'
            self.image.clear()
            self.chart.clear()
            self.shape_chart.hide()
            self.analysis_label.setText('Analysis source: no computed chart')
            self.derived_graphics.hide()
            self.temporal_plot.clear()
            self.band.blockSignals(True)
            self.band.setValue(0)
            self.band.setRange(0, 0)
            self.band.blockSignals(False)
            self.freeze.setChecked(False)
            self.last_frame_identity = None
            if self.session.state not in ('streaming', 'recording'):
                self.session.set_settings(self.requested_settings(), mode=self.session_mode.currentData())
                self.session.start_preview()
            self.follow_camera = True

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
        tick_ns = time.perf_counter_ns()
        if self._last_tick_ns is not None:
            self.timings.record('qt_timer_lateness', max(0, tick_ns - self._last_tick_ns - 33_000_000))
        self._last_tick_ns = tick_ns
        try:
            while True:
                callback, result, error = self.results.get_nowait()
                self.task_busy = False
                failed = bool(error)
                if error:
                    self.discovering = False
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
        if not self.task_busy and not self.closing:
            if self._right_task_pending:
                self._right_task_pending = False
                self.update_right_task()
            if self._brush_pending and not self.task_busy:
                self._brush_pending = False
                self.apply_map_brush()
        if self.session:
            for event in self.session.poll_events():
                if event.get('kind') == 'recording':
                    self.update_recording_result(event)
                if event.get('path'):
                    if event.get('kind') == 'snapshot' and event.get('succeeded'):
                        self.add_recent(Path(event['path']))
                    elif event.get('kind') == 'recording' and event.get('done') and event.get('save_reopen_verified'):
                        self.add_recent(Path(event['path']), partial=event.get('partial', True))
                if event.get('kind') == 'error' or event.get('error'):
                    if event.get('kind') == 'error' and self.session.state == 'error':
                        from hyperlab.devices import connection_error_kind
                        self.connection_issue = connection_error_kind(event.get('error') or event)
                    self.notify(str(event.get('error') or event))
                if event.get('kind') == 'state':
                    self.notify(f"Device state: {event.get('state', self.session.state)}")
            self.last_status = self.session.status()
            frame = self.session.latest_frame()
            if self.follow_camera and frame is not None and self.session.state in ('streaming', 'recording'):
                age = max(0.0, (time.monotonic_ns() - frame.metadata['host_monotonic_ns']) / 1e9)
                self.display_mode = 'FROZEN' if self.freeze.isChecked() else 'STALE' if self.last_status.get('stale', age > 2) else 'LIVE'
                if not self.freeze.isChecked() and frame.identity != self.last_frame_identity:
                    self.displayed_frame = frame
                    self.last_frame_identity = frame.identity
                    meta = dict(frame.metadata, data_level='raw_frame', data_source='LIVE', acquisition_source='LIVE')
                    with self.timings.measure('ui_frame_update'):
                        self.set_cube(Cube(frame.data if frame.data.ndim == 3 else frame.data[..., None], meta), live=True)
                    self.session.mark_displayed(frame)
            elif self.displayed_frame is not None and self.display_mode in ('LIVE', 'FROZEN', 'STALE'):
                self.display_mode = 'REPLAY'
                self.follow_camera = False
            self.update_controls()
            now = time.monotonic()
            if now - self.last_log >= 1:
                self.last_log = now
                self.update_status()
                queued_ns = time.perf_counter_ns()
                QtCore.QTimer.singleShot(0, lambda started=queued_ns: self.timings.record('qt_queued_callback_delay', time.perf_counter_ns() - started))
                if self.benchmark_log:
                    payload = dict(self.last_status, host_utc=datetime.now(timezone.utc).isoformat(),
                                   host_monotonic=now, display_mode=self.display_mode,
                                   rss_bytes=psutil.Process().memory_info().rss,
                                   ui_task_busy=self.task_busy, ui_result_queue=self.results.qsize())
                    payload['ui_stage_timings'] = self.timings.snapshot()
                    payload['view_recipe'] = {key: value for key, value in getattr(self, 'display_selection', {}).items()
                                             if key in ('display_stride', 'raw_extent', 'statistics_scope', 'statistics_source')}
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

    def update_recording_result(self, recording):
        if not recording or not recording.get('done'):
            return
        receipt = {key:recording.get(key) for key in ('path', 'written_frames', 'max_frames',
            'accepted_frames', 'explicitly_failed_frames', 'rejected_frames', 'overflow',
            'completed', 'partial', 'error', 'save_reopen_verified')}
        if receipt == self.recording_receipt:
            return
        self.recording_receipt = receipt
        complete = receipt['completed'] is True and receipt['partial'] is False
        outcome = 'COMPLETE' if complete else 'PARTIAL' if receipt['partial'] is True else 'UNKNOWN'
        written, maximum = (receipt[key] if receipt[key] is not None else '—'
                            for key in ('written_frames', 'max_frames'))
        text = f'Last recording: {outcome} · {written} / {maximum} frames written'
        if not complete:
            text += ' · ' + (receipt['error'] or 'Reason not recorded')
        text += ' · reopen verified' if receipt['save_reopen_verified'] else ' · reopen not verified'
        self.recording_label.setText(text)
        self.recording_label.setToolTip('Latest terminal recording receipt; independent of camera state. '
            'The frame limit is an upper bound; a duration-limited recording may complete earlier.\n' + json_text(receipt))
        self.recording_label.setStyleSheet('padding:5px 8px; border-radius:4px; ' +
            ('background:#e6f1eb; color:#256348;' if complete else 'background:#fff0da; color:#775120;'))
        self.recording_label.show()

    def update_status(self):
        status = self.last_status
        metrics = status.get('metrics', status)
        recording = status.get('recording') or {}
        self.update_recording_result(recording)
        def metric(name):
            value = metrics.get(name)
            return f'{value:.1f}' if isinstance(value, (int, float)) else '—'
        age = metrics.get('frame_age_s')
        age_text = f'{age * 1000:.0f}' if age is not None else '—'
        screen_age = '—'
        if self.displayed_frame is not None and self.display_mode in ('LIVE','FROZEN','STALE'):
            screen_age = f"{max(0,time.monotonic_ns()-self.displayed_frame.metadata.get('host_monotonic_ns',time.monotonic_ns()))/1e6:.0f}"
        live_view = self.display_mode in ('LIVE', 'FROZEN', 'STALE') and status.get('state') in ('streaming', 'recording')
        if live_view:
            text = f"Capture {metric('capture_fps')} fps  |  Display {metric('display_fps')} fps  |  Latest capture age {age_text} ms  |  Displayed frame age {screen_age} ms"
            if status.get('state') == 'recording':
                writer_fps = recording.get('writer_fps')
                rate = f'{writer_fps:.1f}' if isinstance(writer_fps, (int, float)) else '—'
                text += f"  |  Writer {rate} fps · queue {recording.get('queue_length', '—')}"
            self.metrics_label.setText(text)
        else:
            self.metrics_label.clear()
        self.metrics_label.setVisible(live_view)
        frame_meta = status.get('frame_metadata') or {}
        connection = status.get('connection_metadata') or {}
        readback = frame_meta.get('readback_settings') or connection.get('readback_settings') or connection.get('current_settings') or {}
        self.readback_label.setText(f"Frame/session readback: {readback.get('PixelFormat', '—')} · {readback.get('ExposureTime', '—')} µs · gain {readback.get('Gain', '—')}\nPer-frame settings require chunk evidence.")
        if self.diagnostics.isVisible():
            self.detail_text.setPlainText(json_text({'profile': self.profile, 'session': status,
                'viewing_mode': self.display_mode, 'ui_stage_timings': self.timings.snapshot()}))
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
        from hyperlab.ui.presentation import camera_label
        self.device_label.setText(camera_label(state, discovering=self.discovering))
        if state == 'error' and self.connection_issue:
            self.device_label.setText('Camera: ' + self.connection_issue)
        self.device_label.setToolTip((self.profile or {}).get('name', 'No verified camera selected'))
        self.connect_button.setEnabled(state in ('disconnected', 'error') and not self.task_busy)
        self.disconnect_button.setEnabled(state in ('ready', 'streaming', 'recording', 'error'))
        returning = state in ('streaming', 'recording') and not self.follow_camera
        self.preview_button.setEnabled(state == 'ready' or returning)
        self.preview_button.setText('Return to live' if returning else '▶ Start preview')
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
        self.metrics_label.setVisible(state in ('streaming', 'recording') and self.display_mode in ('LIVE', 'FROZEN', 'STALE'))
        if hasattr(self, 'run_button'):
            self.method_changed()
        for item in (self.format, self.exposure, self.gain, self.session_mode, self.apply_button):
            item.setEnabled(state in ('disconnected', 'ready'))

    def update_source_label(self):
        from hyperlab.ui.presentation import observation_label, viewing_label
        self.mode_label.setText('Viewing: ' + viewing_label(self.display_mode))
        meta = self.cube.metadata if self.cube else {}
        self.source_label.setText('Viewed data: ' + observation_label(meta) if self.cube else 'Viewed data: none')
        self.source_label.setToolTip(json_text(source_identity(self.cube)) if self.cube else '')

    def set_cube(self, cube, *, live=False, reset_axis=True):
        old_shape = self.cube.shape if self.cube is not None else None
        self.roi_source_notice = ''
        if self.annotation is not None and self.cube is not cube:
            self.annotation = None
            self.annotation_path = None
        if not live and self.cube is not cube:
            self.close_source_dialogs()
        self.cube = cube
        self.pixel_label.setText('Pixel: —')
        self.pixel_label.setToolTip('')
        if not live:
            self.follow_camera = False
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
            self.right_spec = None
            self.map_distributions = None
            self.map_brushes = []
            self.map_tools.hide()
            self.derived_graphics.hide()
            self.roi_results = []
            if reset_axis:
                self.temporal_plot.clear()
                self.plot_spec = None
                self.plot_mode.blockSignals(True)
                self.plot_mode.setCurrentIndex(0)
                self.plot_mode.blockSignals(False)
                self.last_quality = 0.0
        if old_shape != cube.shape:
            matching_coordinates = bool(self.rois) and all(
                record and record['coordinate_frame']['shape_hw'] == list(cube.shape[:2])
                for record in self.roi_records)
            if not matching_coordinates:
                new_coordinates = bool(self.rois)
                self.reset_rois(force=True, new_coordinates=new_coordinates)
                if new_coordinates:
                    self.roi_source_notice = ('Raw image dimensions changed; new default ROIs created. '
                                              'Review placement and choose the reference.')
            elif live and old_shape is None:
                self.roi_source_notice = ('ROI coordinates retained for matching raw dimensions; '
                                          'verify placement in the current scene.')
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
        from hyperlab.io.labels import display_labels
        labels = display_labels(cube.metadata, cube.shape[2])
        if labels != [self.trace_channel.itemText(i) for i in range(self.trace_channel.count())]:
            channel = max(0, self.trace_channel.currentIndex())
            self.trace_channel.blockSignals(True)
            self.trace_channel.clear()
            self.trace_channel.addItems(labels)
            self.trace_channel.setCurrentIndex(min(channel, len(labels)-1))
            self.trace_channel.blockSignals(False)
        self.render_current()
        if not live or old_shape != cube.shape:
            self.update_capabilities()
        if old_shape != cube.shape:
            self.fit()
        from hyperlab.ui.state import restore_view
        restore_view(self)
        if not live:
            self.update_controls()
            self.update_source_label()
        if self.roi_source_notice:
            self.notify(self.roi_source_notice)

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
        fast = self.display_mode in ('LIVE', 'STALE') and not self.full_resolution_view
        stride = (max(1, int(np.ceil(raw.shape[0] / 640))), max(1, int(np.ceil(raw.shape[1] / 960)))) if fast else (1, 1)
        try:
            selected = display_selection(self.cube, band, policy=self.policy.currentData(),
                                         cfa=self.view_mode.currentIndex() == 1 and not is_color,
                                         display_stride=stride, diagnostics=not fast, timings=self.timings)
        except ValueError as error:
            self.notify(str(error))
            selected = display_selection(self.cube, band, policy=self.policy.currentData(),
                                         display_stride=stride, diagnostics=not fast, timings=self.timings)
        self.display_selection = selected
        shown = selected['image']
        if self.auto_levels.isChecked():
            self.levels = selected['levels']
        else:
            self.levels = (self.low.value(), max(self.low.value() + 1e-12, self.high.value()))
        with self.timings.measure('image_item_enqueue'):
            self.image.setImage(shown, autoLevels=False, levels=self.levels)
        h, w = raw.shape[:2]
        extent = tuple(selected.get('display_extent', [0, 0, w, h]))
        image_geometry = (shown.shape[:2], extent)
        if image_geometry != getattr(self, '_image_geometry', None):
            self.image.setRect(QtCore.QRectF(*extent))
            self._image_geometry = image_geometry
        if self.overlay.isChecked():
            limit = selected['saturation_value']
            if limit is not None:
                saturated = selected['saturated_mask']
                rgba = np.zeros(saturated.shape + (4,), dtype=np.uint8)
                rgba[saturated] = [255, 50, 35, 125]
                self.saturation_overlay.setImage(rgba, autoLevels=False)
                self.saturation_overlay.setRect(QtCore.QRectF(0, 0, w, h))
                self.saturation_overlay.show()
            else:
                self.saturation_overlay.hide()
        else:
            self.saturation_overlay.hide()
        if self.sequence:
            self.axis_label.setText(f'Time frame T={self.band.value()} / {self.sequence.frame_count - 1} · time axis, not spectral')
        elif is_color:
            self.axis_label.setText(' / '.join(self.cube.metadata['channel_labels']) + ' channels · not spectral')
        elif self.cube.wavelengths is not None:
            self.axis_label.setText(f"λ[{band}] = {self.cube.wavelengths[band]:g} {self.cube.metadata.get('wavelength_units') or 'unknown unit'} · {self.cube.metadata.get('wavelength_evidence', 'declared')}")
        else:
            self.axis_label.setText(f'Fixed optical state · DN' if raw.shape[2] == 1 else f'Scan state index {band} · not nm')
        if selected['display_stride'] != [1, 1]:
            sy, sx = selected['display_stride']
            self.axis_label.setText(self.axis_label.text() + f' · Overview samples {sx}×{sy}; 1:1 for full detail')
        if time.monotonic() - self.last_quality > 0.5:
            self.last_quality = time.monotonic()
            with self.timings.measure('chart_update'):
                self.update_chart(shown, selected=selected)

    def fit(self):
        self.full_resolution_view = False
        if self.cube is not None:
            h, w = self.cube.shape[:2]
            self.plot.setRange(xRange=(0, w), yRange=(0, h), padding=0.025)

    def one_to_one(self):
        self.full_resolution_view = True
        self.render_current()
        box = self.plot.getViewBox()
        (x0, x1), (y0, y1) = box.viewRange()
        width, height = box.width(), box.height()
        box.setRange(xRange=((x0+x1-width)/2, (x0+x1+width)/2),
                     yRange=((y0+y1-height)/2, (y0+y1+height)/2), padding=0)

    def _roi_row(self, name, color, record=None):
        row = W.QWidget()
        layout = W.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = W.QLineEdit(name)
        edit.setStyleSheet(f'border-left: 4px solid {color};')
        layout.addWidget(edit, 1)
        show = W.QCheckBox('Show')
        show.setChecked(True)
        layout.addWidget(show)
        use = W.QCheckBox('Use'); use.setChecked(True)
        use.setToolTip('Include in calculations; independent of visibility')
        layout.addWidget(use)
        remove = self.button('×', lambda: self.remove_roi(self.roi_rows.index(row)))
        remove.setToolTip('Remove this ROI from the analysis definition')
        remove.setMaximumWidth(28)
        layout.addWidget(remove)
        self.roi_form.addWidget(row)
        self.roi_names.append(edit)
        self.roi_colors.append(color)
        self.roi_rows.append(row)
        self.roi_visible.append(show)
        self.roi_included.append(use)
        self.roi_records.append(record)
        edit.textChanged.connect(self.roi_changed)
        use.toggled.connect(self.roi_changed)
        show.toggled.connect(lambda visible: self.set_roi_visible(self.roi_rows.index(row), visible))

    def set_roi_visible(self, index, visible):
        if index < len(self.rois):
            self.rois[index].setVisible(visible)
        self.roi_changed()

    def add_roi(self, name=None, rect=None, color=None, *, record=None, kind='rectangle'):
        if len(self.roi_names) >= 8:
            self.notify('Up to eight ROI definitions are supported.')
            return
        index = len(self.roi_names)
        self._roi_row(name or f'ROI {chr(65+index)}', color or COLORS[index], record)
        if self.cube is not None:
            self._create_roi(index, rect, kind=kind)
        if record:
            self.roi_visible[-1].setChecked(record['visible'])
            self.roi_included[-1].setChecked(record['included'])
        self.roi_changed()

    def _create_roi(self, index, rect=None, *, kind='rectangle'):
        from hyperlab.analysis.regions import make_roi, resolve_roi
        h, w = self.cube.shape[:2]
        if rect is None:
            x, y = w * (.12 + .26 * (index % 3)), h * (.22 + .28 * (index // 3))
            width, height = max(1, w * .2), max(1, h * .22)
        else:
            x, y, x1, y1 = rect
            width, height = x1-x, y1-y
        record = self.roi_records[index]
        if record is None:
            geometry = {'type':'rectangle', 'bounds':[x, y, x+width, y+height]}
            if kind == 'polygon':
                geometry = {'type':'polygon', 'vertices':[[x,y],[x+width,y],[x+width,y+height],[x,y+height]], 'holes':[]}
            elif kind == 'strip':
                geometry = {'type':'strip', 'points':[[x,y],[x+width,y+height]], 'width_px':10.0}
            record = make_roi((h,w), geometry, name=self.roi_names[index].text(), color=self.roi_colors[index],
                              role='reference' if index == 0 else 'target')
            self.roi_records[index] = record
            if self.reference_roi_id is None and index == 0:
                self.reference_roi_id = record['roi_id']
        geometry = record['geometry']; kind = geometry['type']
        pen = pg.mkPen(self.roi_colors[index], width=2)
        if kind == 'rectangle':
            x, y, x1, y1 = geometry['bounds']
            roi = pg.RectROI([x,y], [x1-x,y1-y], pen=pen, movable=True, rotatable=False,
                             maxBounds=QtCore.QRectF(0,0,w,h))
        elif kind in ('polygon', 'strip'):
            roi = pg.PolyLineROI(geometry.get('vertices', geometry.get('points')), closed=kind == 'polygon', pen=pen)
        else:
            roi = pg.ImageItem(axisOrder='row-major')
        self.plot.addItem(roi)
        self.rois.append(roi)
        fill = pg.ImageItem(axisOrder='row-major'); fill.setZValue(-.1)
        self.plot.addItem(fill); self.roi_fills.append(fill)
        roi.setVisible(self.roi_visible[index].isChecked())
        label = pg.TextItem(self.roi_names[index].text(), color=self.roi_colors[index], anchor=(0,1))
        self.plot.addItem(label)
        self.roi_labels.append(label)
        if hasattr(roi, 'sigRegionChanged'):
            roi.sigRegionChanged.connect(self.roi_changed)
        self._update_roi_fill(index)
        self._update_roi_labels()

    def _update_roi_fill(self, index):
        from hyperlab.analysis.regions import resolve_roi
        record = self.roi_records[index]
        target = self.rois[index] if record['geometry']['type'] == 'mask' else self.roi_fills[index]
        if record['geometry']['type'] == 'rectangle':
            target.hide(); return
        selection = resolve_roi(self.cube.shape, record)
        x0,y0,x1,y1 = selection['bbox']
        if x0 == x1 or y0 == y1:
            target.hide(); return
        color = pg.mkColor(record['color'])
        rgba = np.zeros(selection['selected'].shape + (4,), np.uint8)
        rgba[selection['selected']] = [color.red(), color.green(), color.blue(), 50]
        target.setImage(rgba, autoLevels=False)
        target.setRect(QtCore.QRectF(x0,y0,x1-x0,y1-y0))
        target.setVisible(self.roi_visible[index].isChecked())

    def regions(self):
        """Return copied stable definitions; geometry stays in the raw coordinate frame."""
        from copy import deepcopy
        for i, roi in enumerate(self.rois):
            old = self.roi_records[i]
            record = deepcopy(old)
            kind = record['geometry']['type']
            if kind == 'rectangle':
                record['geometry']['bounds'] = list(roi_rect(roi.pos(), roi.size(), self.cube.shape))
            elif kind in ('polygon', 'strip'):
                points = [roi.mapToParent(point) for _, point in roi.getLocalHandlePositions()]
                record['geometry']['vertices' if kind == 'polygon' else 'points'] = [[p.x(),p.y()] for p in points]
            record.update(name=self.roi_names[i].text().strip() or f'ROI {i+1}',
                          visible=self.roi_visible[i].isChecked(), included=self.roi_included[i].isChecked())
            if record != old:
                record['revision'] += 1
                self.roi_records[i] = record
        return deepcopy(self.roi_records[:len(self.rois)])

    def refresh_reference_selector(self):
        if not hasattr(self, 'reference_roi'):
            return
        self.reference_roi.blockSignals(True)
        self.reference_roi.clear()
        self.reference_roi.addItem('Select reference ROI', None)
        for record in self.roi_records:
            if record and record['included'] and record['role'] != 'exclude':
                self.reference_roi.addItem(record['name'], record['roi_id'])
        self.reference_roi.setCurrentIndex(max(0, self.reference_roi.findData(self.reference_roi_id)))
        self.reference_roi.blockSignals(False)

    def choose_reference_roi(self):
        self.set_reference_roi(self.reference_roi.currentData())

    def set_reference_roi(self, roi_id):
        self.reference_roi_id = roi_id
        for record in self.roi_records:
            if record and record['role'] != 'exclude':
                role = 'reference' if record['roi_id'] == self.reference_roi_id else 'target'
                if record['role'] != role:
                    record['role'] = role; record['revision'] += 1
        self.refresh_reference_selector()
        self.roi_changed()

    def _update_roi_labels(self):
        for i, roi in enumerate(self.rois):
            self.roi_labels[i].setVisible(roi.isVisible())
            self.roi_labels[i].setText(self.roi_names[i].text(), color=self.roi_colors[i])
            if self.roi_records[i]['geometry']['type'] == 'mask':
                from hyperlab.analysis.regions import resolve_roi
                self.roi_labels[i].setPos(*resolve_roi(self.cube.shape, self.roi_records[i])['bbox'][:2])
            elif isinstance(roi, pg.PolyLineROI):
                point = roi.mapToParent(roi.getLocalHandlePositions()[0][1])
                self.roi_labels[i].setPos(point)
            else:
                self.roi_labels[i].setPos(roi.pos())

    def roi_changed(self, *args):
        self.analysis_version += 1
        if self.cube is not None:
            self.regions()
            for index in range(len(self.rois)):
                self._update_roi_fill(index)
        self.refresh_reference_selector()
        self._update_roi_labels()
        if self.cube is not None and self.plot_mode.currentIndex() == 2:
            self.roi_timer.start(160)

    def remove_roi(self, index):
        if not 0 <= index < len(self.roi_names):
            return
        if len(self.roi_names) <= 1:
            self.notify('Keep at least one ROI; clear Use to exclude it from calculations.')
            return
        row = self.roi_rows.pop(index)
        row.setParent(None)
        row.deleteLater()
        self.roi_names.pop(index)
        self.roi_visible.pop(index)
        self.roi_included.pop(index)
        self.roi_records.pop(index)
        self.roi_colors.pop(index)
        if index < len(self.rois):
            self.plot.removeItem(self.rois.pop(index))
            self.plot.removeItem(self.roi_labels.pop(index))
            self.plot.removeItem(self.roi_fills.pop(index))
        self.roi_changed()

    def reset_rois(self, force=False, *, new_coordinates=False):
        if self.cube is None or (self.rois and not force):
            return
        for item in [*self.rois, *self.roi_labels, *self.roi_fills]:
            self.plot.removeItem(item)
        self.rois, self.roi_labels, self.roi_fills = [], [], []
        self.roi_records = [None] * len(self.roi_names)
        self.reference_roi_id = None
        for index in range(len(self.roi_names)):
            if new_coordinates:
                name, show, use = self.roi_names[index], self.roi_visible[index], self.roi_included[index]
                for control in (name, show, use):
                    control.blockSignals(True)
                name.setText(f'ROI {chr(65+index)}')
                show.setChecked(True); use.setChecked(True)
                for control in (name, show, use):
                    control.blockSignals(False)
            self._create_roi(index)
        self.roi_changed()

    def rectangles(self):
        from hyperlab.analysis.regions import resolve_roi
        return [resolve_roi(self.cube.shape, record)['bbox'] for record in self.regions()]

    def pixel_hover(self, scene_position):
        if self.cube is None or not self.plot.sceneBoundingRect().contains(scene_position):
            return
        point = self.plot.getViewBox().mapSceneToView(scene_position)
        # Inspection uses raw axes even when an overview displays sampled pixels.
        x, y = int(np.floor(point.x())), int(np.floor(point.y()))
        self.move_cursors(x, y)
        if 0 <= x < self.cube.shape[1] and 0 <= y < self.cube.shape[0]:
            values = self.cube.data[y, x]
            from hyperlab.analysis.core import _quality
            selection = (slice(y,y+1),slice(x,x+1),slice(None))
            valid, counts, _ = _quality(self.cube,self.cube.data[selection],selection,self.policy.currentData())
            self.pixel_label.setText(f'Raw pixel x={x}, y={y} · {np.array2string(values, precision=7, threshold=8)} · {self.policy.currentData()} valid channels {np.count_nonzero(valid)}/{valid.size}')
            self.pixel_label.setToolTip(json_text({name: int(mask.sum()) for name,mask in counts.items()}))

    def move_cursors(self, x, y):
        for lines in (self.source_cursor, self.map_cursor):
            for line, value in zip(lines, (y+.5, x+.5)):
                line.setValue(value); line.setVisible(self.link_views.isChecked())

    def map_hover(self, scene_position):
        if self.map_spec is None or not self.derived_plot.sceneBoundingRect().contains(scene_position):
            return
        point = self.derived_plot.getViewBox().mapSceneToView(scene_position)
        x,y = int(np.floor(point.x())),int(np.floor(point.y()))
        if 0 <= y < self.map_spec.image.shape[0] and 0 <= x < self.map_spec.image.shape[1]:
            self.move_cursors(x,y)
            value = self.map_spec.image[y,x]
            validity = 'valid' if self.map_spec.valid_mask[y,x] else 'invalid / masked'
            from hyperlab.ui.presentation import observation_label
            self.pixel_label.setText(f'Map pixel ({x}, {y}): {value:g} · {validity} · {self.map_spec.colour_label}')
            self.pixel_label.setToolTip('Pinned map source: ' + observation_label(self.map_spec.source))

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
        scope = selected.get('statistics_scope', 'full raw frame')
        self.quality_label.setText(f"{scope.capitalize()} · {policy} mean {mean} · saturation {saturation}\n"
            f"Display histogram: {selected['sample_count']}/{selected['sample_total']} selected samples\n"
            'Invalid and ignored samples do not affect contrast.')
        self.quality_label.setToolTip(json_text({'raw_counts': counts, **{k:v for k,v in selected.items()
            if k not in ('image','valid_mask','values','saturated_mask')}}))
        # Pending controls do not replace the completed chart's source or recipe.
        if self.task_busy and self.plot_spec is not None:
            return
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
            context = self.analysis_context()
            indices = [i for i,flag in enumerate(context['included']) if flag]
            rects = [context['regions'][i] for i in indices]
            band = max(0, self.trace_channel.currentIndex())
            with self.timings.measure('roi_trend_statistics'):
                stats = [roi_statistics(cube, rect, policy=policy, bands=[band], robust=False,
                                        exclusions=context['exclusions']) for rect in rects]
            means = [float(r['mean'][band]) for r in stats]
            definition = {'regions':rects, 'exclusions':context['exclusions'], 'names':[context['names'][i] for i in indices],
                          'policy':policy, 'band':band,
                          'source_file':cube.metadata.get('source_file'),
                          'session_id':cube.metadata.get('session_id'),
                          'stream_epoch':cube.metadata.get('stream_epoch'),
                          'settings':cube.metadata.get('readback_settings') or cube.metadata.get('current_settings')}
            # File replay uses recorded times, never UI playback cadence.
            meta = dict(cube.metadata, display_mode=self.display_mode)
            self.temporal_plot.add(meta, means, definition, sequence=self.sequence,
                                   index=self.band.value() if self.sequence else None)
            spec = self.temporal_plot.plot(definition['names'], [context['colors'][i] for i in indices], source)
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
        previous = self.plot_spec
        was_comparison = bool(self.plot_spec and self.plot_spec.metadata.get('roi_comparison'))
        self.plot_spec = spec
        self.completed_plot_mode = self.plot_mode.currentIndex()
        self.plot_source = getattr(self, '_completed_source', None) or self.cube
        self.plot_annotation = spec.metadata.get('analysis_context', {}).get('annotation', self.annotation)
        from hyperlab.ui.presentation import observation_label
        revision = spec.metadata.get('analysis_version')
        suffix = f' · ROI revision {revision}' if revision is not None else ''
        self.analysis_label.setText(f'Chart: {spec.title} · {observation_label(spec.source)}{suffix}')
        self.analysis_label.setToolTip(json_text({'source': spec.source, 'recipe': spec.metadata, 'caption': spec.caption}))
        same_histogram = (previous is not None and previous.title == spec.title == 'Sampled histogram'
            and previous.xlabel == spec.xlabel and len(previous.series) == len(spec.series) == 1
            and previous.series[0]['name'] == spec.series[0]['name'] and self.curves
            and len(spec.series[0]['x']) > 1)
        if same_histogram:
            item = spec.series[0]
            self.curves[0].setData(item['x'], item['y'], connect='finite')
            self.chart.setToolTip(spec.caption)
            if not np.array_equal(previous.series[0]['x'],item['x']):
                self.chart.setXRange(float(np.min(item['x'])),float(np.max(item['x'])),padding=.03)
            return
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
            categorical_points = bool(spec.categories and spec.metadata.get('categorical_style') == 'points')
            curve = self.chart.plot(item['x'], item['y'], pen=None if categorical_points else pen, name=item['name'], connect='finite',
                                    symbol='o' if spec.categories or len(item['x'])<5 else None,
                                    symbolSize=8,symbolBrush=item['color'],symbolPen='w',antialias=True)
            curve.setZValue(2)
            self.curves.append(curve)
            if item.get('sd') is not None:
                if len(item['x']) == 1 or categorical_points:
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
                if len(item['x']) == 1 or categorical_points:
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
        self.install_interval_selector()

    def install_interval_selector(self):
        if not hasattr(self,'chart'):
            return
        if getattr(self,'interval_region',None) is not None:
            self.chart.removeItem(self.interval_region); self.interval_region=None
        if (self.cube is None or self.cube.wavelengths is None or self.plot_source is not self.cube
                or self.plot_spec is None or not self.plot_spec.metadata.get('roi_comparison')
                or self.analysis_method.currentData() not in ('interval_map','interval_mean_map')):
            return
        wave=self.cube.wavelengths
        first,last=self.feature_first.value(),self.feature_last.value()
        self.interval_region=pg.LinearRegionItem(sorted([float(wave[first]),float(wave[last])]),
                                                brush=pg.mkBrush(58,144,124,30))
        self.chart.addItem(self.interval_region)
        def selected():
            lower,upper=self.interval_region.getRegion()
            indices=np.flatnonzero((wave >= lower) & (wave <= upper))
            if indices.size < 2:
                self.notify('Select at least two measured wavelengths for an interval map.'); return
            self.feature_first.setValue(int(indices.min())); self.feature_last.setValue(int(indices.max()))
            self.roi_timer.stop()
            if not self.task_busy:
                self.analyze(self.analysis_method.currentData())
        self.interval_region.sigRegionChangeFinished.connect(selected)

    def update_capabilities(self):
        from hyperlab.analysis import capabilities
        cap = capabilities(self.cube)
        self.shape_normalize.setVisible(self.cube is None or self.cube.shape[2]>1)
        for op, button in self.analysis_buttons.items():
            button.setEnabled(cap['operations'].get(op, False))
            button.setToolTip(cap.get('reasons', {}).get(op, ''))
        self.method_changed()

    def analysis_context(self):
        records = self.regions()
        return {'version':self.analysis_version, 'source':source_identity(self.cube),
                'rectangles':self.rectangles(), 'names':[name.text() for name in self.roi_names],
                'regions':records, 'included':[item['included'] and item['role'] != 'exclude' for item in records],
                'exclusions':[item for item in records if item['included'] and item['role'] == 'exclude'],
                'reference_roi_id':self.reference_roi_id,
                'colors':list(self.roi_colors), 'visible':[item.isChecked() for item in self.roi_visible],
                'policy':self.policy.currentData(), 'normalized':self.shape_normalize.isChecked(),
                'spatial_sd':self.spatial_sd.isChecked(), 'summary':self.roi_summary.currentData(),
                'categorical_style':self.categorical_style.currentData(),
                'support':self.roi_support.currentData(), 'annotation':self.annotation,
                'method':self.analysis_method.currentData(), 'trace_channel':self.trace_channel.currentIndex(),
                'feature_interval':[self.feature_first.value(), self.feature_last.value()],
                'window':self.local_window.value(), 'degree':self.local_degree.value(),
                'max_gap_nm':self.max_gap_nm.value() or None}

    def analyze_rois(self):
        if self.cube is None or self.closing:
            return
        if self.task_busy:
            self.roi_timer.start(180)
            return
        from hyperlab.analysis import roi_comparison
        from hyperlab.experiment_metadata import compute_pinned
        cube, context = self.cube, self.analysis_context()
        included = [i for i, flag in enumerate(context['included']) if flag]
        if not included:
            self.notify('Select Use for at least one target or reference ROI.'); return
        context['analyzed_roi_indices'] = included
        def completed(payload):
            results, context['source_fingerprint'] = payload
            if context['version'] != self.analysis_version:
                self.notify('ROI definition changed; obsolete result discarded.')
                self.roi_timer.start(180)
                return
            self.roi_source = cube
            self.show_rois(results, context)
        self.background(lambda: compute_pinned(cube, lambda: roi_comparison(cube,[context['regions'][i] for i in included],
                        policy=context['policy'],support=context['support'],exclusions=context['exclusions'])),
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
        included = list(context.get('analyzed_roi_indices', range(len(results))))
        enabled = [i for i, original in enumerate(included) if context['visible'][original]]
        if not enabled:
            self.draw_plot(PlotSpec('lines','No visible ROI','Index','Mean'))
            return
        spec = roi_plot(results, [context['names'][i] for i in included],
                        [context['colors'][i] for i in included], source=context['source'],
                        normalized=context['normalized'], spatial_sd=context['spatial_sd'], summary=context['summary'],
                        categorical_style=context.get('categorical_style','connected'))
        spec.series = [spec.series[i] for i in enabled]
        if self.roi_source.shape[2] == 1:
            spec.categories = [context['names'][included[i]] for i in enabled]
            for position,item in enumerate(spec.series):
                item['x'] = np.array([position])
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
                    shape = roi_plot(results, names,
                        COLORS, source=context['source'], normalized=True, summary=context['summary'])
                    branch = {'operation':shape.metadata['normalization'], 'summary':context['summary'],
                        'feature_indices':shape.metadata['common_feature_indices'], 'roi_indices':visible,
                        'normalized_summaries':plain([shape.series[i]['normalized'] for i in visible])}
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
        gate = {'reference_rmse':'roi', 'normalized_difference':'ratio',
                'interval_map':'spectral_features','interval_mean_map':'spectral_features'}.get(operation, operation)
        if not cap['operations'].get(gate):
            self.notify(cap['reasons'].get(gate, 'This data does not support the operation'))
            return
        cube, policy = self.cube, self.policy.currentData()
        context = self.analysis_context()
        reference = next((record for record in context['regions'] if record['roi_id'] == context['reference_roi_id']
                          and record['included'] and record['role'] != 'exclude'), None)
        if operation in ('spectral_angle', 'reference_rmse') and reference is None:
            self.notify('Select an included reference ROI. The previous reference is missing or excluded.'); return
        a, b = self.pair_a.value(), self.pair_b.value()
        minimum_denominator = self.minimum_denominator.value()
        context.update(pair_indices=[a, b], minimum_denominator=minimum_denominator)
        low_signal = self.low_signal_threshold.value() if self.low_signal_enabled.isChecked() else None
        low_signal_source = self.low_signal_source.text().strip() if low_signal is not None else None
        context.update(low_signal_threshold=low_signal, low_signal_source=low_signal_source)
        if operation in ('spectral_angle', 'reference_rmse'):
            context['support'] = 'common'
        def run():
            if operation in ('interval_map','interval_mean_map'):
                from hyperlab.analysis.distributions import spectral_interval_map
                first,last=context['feature_interval']
                return spectral_interval_map(cube,bands=list(range(first,last+1)), policy=policy,
                    statistic='integral' if operation == 'interval_map' else 'mean', max_gap_nm=context['max_gap_nm'])
            if operation == 'pca':
                return pca(cube, min(3, cap['effective_dimensions']), policy=policy)
            if operation in ('spectral_angle', 'reference_rmse'):
                from hyperlab.analysis.maps import reference_rmse
                stats = roi_statistics(cube, reference, policy=policy, support='common', exclusions=context['exclusions'])
                vector = stats[context['summary']]
                result = (spectral_angle if operation == 'spectral_angle' else reference_rmse)(cube, vector, policy=policy)
                result['metadata']['reference_roi'] = {**reference, 'rect':list(stats['rect']),
                    'coordinates': 'raw pixel centres; declared ROI geometry',
                    'used_counts':stats['count'].tolist(), 'quality_counts':{k:v.tolist() for k,v in stats['counts'].items()}}
                result['metadata'].update(summary=context['summary'], reference_support='common')
                return result
            if operation == 'difference':
                return difference(cube, a, b, policy=policy)
            from hyperlab.analysis.maps import normalized_difference
            if operation == 'normalized_difference':
                return normalized_difference(cube, a, b, policy=policy, minimum_denominator=minimum_denominator,
                    low_signal_threshold=low_signal, low_signal_source=low_signal_source)
            return ratio(cube, a, b, policy=policy, minimum_denominator=minimum_denominator)
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
        visible = [i for i, flag in enumerate(context['included']) if flag]
        if not visible:
            self.notify('Select Use for at least one target or reference ROI.')
            return
        rects = [context['regions'][i] for i in visible]
        names = [context['names'][i] for i in visible]
        colors = [context['colors'][i] for i in visible]
        first, last = context['feature_interval']
        bands = list(range(first, last+1)) if operation != 'pairs' else None
        support = 'common' if operation != 'pairs' else context['support']
        context.update(support=support, feature_indices=bands, analyzed_roi_indices=visible)
        self.roi_timer.stop()
        def run():
            results = roi_comparison(cube, rects, policy=context['policy'], bands=bands, support=support, exclusions=context['exclusions'])
            if operation == 'pairs':
                result = roi_pairwise(cube, results, names, summary=context['summary'])
                spec = roi_pair_plot(cube, results, result, colors)
            else:
                result = spectral_roi_features(cube, results, operation, summary=context['summary'], bands=bands,
                    window=context['window'], degree=context['degree'], max_gap_nm=context['max_gap_nm'])
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
        signal = result.get('metadata', {}).get('low_signal_assessment')
        if signal:
            self.low_signal_note.setText('Completed map signal policy: ' + str(signal['status']))
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
        robust = self.robust_map_limits.isChecked()
        values = spec.image[spec.valid_mask]
        if robust and values.size:
            lower,upper = np.percentile(values,[1,99])
            if lower < upper:
                spec.limits = (float(lower),float(upper))
        key = (spec.title, spec.colour_label, robust)
        if self.lock_map_limits.isChecked() and key in self._map_limits:
            spec.limits = self._map_limits[key]
        self._map_limits[key] = spec.limits
        clipped = int(np.count_nonzero((values < spec.limits[0]) | (values > spec.limits[1]))) if values.size else 0
        spec.metadata['display_limits'] = {'policy':'1–99 percentile' if robust else 'full finite range',
            'shared_limits':self.lock_map_limits.isChecked(), 'limits':list(spec.limits), 'clipped_count':clipped,
            'valid_count':int(values.size),'clipped_fraction':clipped/len(values) if values.size else None,
            'scope':'Colour mapping only; source/map values, statistics and brush eligibility are unchanged'}
        self.map_limits_note.setText(f'Colour limits: {clipped} / {len(values)} valid pixels clipped')
        self.map_spec = spec
        self.map_distributions = None
        self.map_brushes = []
        self.brush_overlay.clear()
        self.brush_mask_overlay.clear()
        self.derived_image.setImage(spec.image, autoLevels=False, levels=spec.limits)
        self.derived_invalid.setImage((~spec.valid_mask).astype(np.uint8),autoLevels=False,levels=(0,1))
        cmap = pg.colormap.get(spec.colormap, source='matplotlib')
        self.colorbar.setColorMap(cmap)
        self.colorbar.setLevels(spec.limits)
        label_style = {'color':'#26313d','font-size':'11pt','siPrefixEnableRanges':()}
        self.colorbar.axis.setLabel(spec.colour_label,**label_style)
        from html import escape
        identity = spec.source.get('sequence')
        map_source = f'frame {identity}' if identity is not None else Path(spec.source.get('source_file') or 'current data').name
        self.derived_plot.setTitle(escape(f'{spec.title} · {map_source}'),color='#17212b',size='12pt')
        from hyperlab.ui.presentation import observation_label
        self.derived_graphics.setToolTip(f'{observation_label(spec.source)}\n{spec.caption}\n{json_text(spec.metadata)}')
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
        self.prepare_map_panels()

    def prepare_map_panels(self):
        if self.task_busy or self.map_spec is None:
            return
        from hyperlab.analysis import roi_comparison
        from hyperlab.analysis.distributions import map_roi_distributions
        from hyperlab.experiment_metadata import compute_pinned
        cube, spec = self.product_source, self.map_spec
        context = spec.metadata.get('analysis_context') or self.analysis_context()
        indices = [i for i, record in enumerate(context['regions']) if record['included'] and record['role'] != 'exclude']
        regions = [context['regions'][i] for i in indices]
        if not regions:
            self.notify('Select Use for an ROI to inspect the map distribution.'); return
        product = {'data':spec.image, 'valid_mask':spec.valid_mask,
                   'metadata':dict(spec.metadata, units=spec.metadata.get('units',cube.metadata['units']), displayed_component=spec.title),
                   'reason_masks':self.product.get('reason_masks',{})}
        # Complete map values are independent of colour limits and viewport sampling.
        def run():
            stats = roi_comparison(cube, regions, policy=context['policy'], support=context['support'], exclusions=context['exclusions'])
            distributions = map_roi_distributions(product, regions, exclusions=context['exclusions'])
            return stats, distributions
        def completed(payload):
            if self.map_spec is not spec:
                return
            (stats, distributions), fingerprint = payload
            context.update(source_fingerprint=fingerprint, analyzed_roi_indices=indices)
            self.roi_source = cube
            self.show_rois(stats, context)
            self.map_distributions, self.map_distribution_product = distributions, product
            self.map_distribution_context = context
            selected = self.inspect_roi.currentData()
            self.inspect_roi.blockSignals(True); self.inspect_roi.clear()
            for record in regions:
                self.inspect_roi.addItem(record['name'],record['roi_id'])
            self.inspect_roi.setCurrentIndex(max(0,self.inspect_roi.findData(selected))); self.inspect_roi.blockSignals(False)
            self.map_tools.show(); self.update_right_task()
        self.background(lambda:compute_pinned(cube,run),completed,'Computing exact map ROI distributions and linked amplitude…')

    def draw_right_plot(self, spec, *, brush=False):
        self.right_spec = spec
        chart = self.shape_chart; chart.clear(); chart.plotItem.legend.clear(); chart.show()
        chart.setTitle(spec.title,color='#17212b',size='12pt'); chart.setToolTip(spec.caption)
        chart.setLabel('bottom',spec.xlabel,**{'color':'#26313d','siPrefixEnableRanges':()})
        chart.setLabel('left',spec.ylabel,**{'color':'#26313d','siPrefixEnableRanges':()})
        chart.getAxis('bottom').setTicks([list(enumerate(spec.categories))] if spec.categories else None)
        for item in spec.series:
            x,y = np.asarray(item['x']),np.asarray(item['y'])
            if item.get('drawstyle') == 'steps-post' and x.size:
                x,y = np.repeat(x,2),np.r_[0,np.repeat(y,2)[:-1]]
            elif item.get('drawstyle') == 'steps-mid' and item.get('histogram'):
                x = np.repeat(item['histogram']['bin_edges'],2)[1:-1]
                y = np.repeat(item['histogram']['counts'],2)
            if item.get('sd') is not None:
                sd = np.asarray(item['sd'])
                lower = chart.plot(x,y-sd,pen=None,connect='finite')
                upper = chart.plot(x,y+sd,pen=None,connect='finite')
                shade = pg.mkColor(item['color']); shade.setAlpha(43)
                chart.addItem(pg.FillBetweenItem(lower,upper,brush=shade))
            points_only = spec.categories and spec.metadata.get('categorical_style') == 'points'
            chart.plot(x,y,pen=None if points_only else pg.mkPen(item['color'],width=2.5,
                style=QtCore.Qt.PenStyle.DashLine if item.get('style') == '--' else QtCore.Qt.PenStyle.SolidLine),
                name=item['name'],connect='finite',symbol='o' if spec.categories else None,symbolSize=7,
                symbolBrush=item['color'],symbolPen='w')
        if brush and spec.series:
            values = np.concatenate([np.asarray(item.get('ecdf',{}).get('values',item['x'])) for item in spec.series])
            values = values[np.isfinite(values)]
            if values.size:
                if getattr(self, '_right_brush_product', None) is self.map_distribution_product:
                    low,high = self.brush_low.value(),self.brush_high.value()
                else:
                    low,high = float(values.min()),float(values.max())
                self._right_brush_product = self.map_distribution_product
                self.brush_low.setValue(low); self.brush_high.setValue(high)
                self.brush_region = pg.LinearRegionItem((low,high),brush=pg.mkBrush(190,73,124,28))
                chart.addItem(self.brush_region)
                def changed():
                    low,high=self.brush_region.getRegion()
                    self.brush_low.setValue(low); self.brush_high.setValue(high); self.apply_map_brush()
                self.brush_region.sigRegionChangeFinished.connect(changed)
        chart.enableAutoRange(); self.chart_row.setSizes([1,1]); self.vertical.setSizes([440,300])

    def update_right_task(self):
        self._right_request += 1
        task = self.right_task.currentData()
        distribution_task = task in ('ecdf','histogram')
        self.brush_controls.setVisible(distribution_task)
        self.brush_controls.setEnabled(distribution_task)
        if not distribution_task:
            self._brush_pending = False
            self.map_brushes = []
            self.brush_overlay.clear(); self.brush_mask_overlay.clear()
            self.brush_note.setText('No selected map range.')
        if self.map_brushes and self.map_brushes[0]['metadata']['roi']['roi_id'] != self.inspect_roi.currentData():
            self.map_brushes = []
            self.brush_overlay.clear(); self.brush_mask_overlay.clear()
            self.brush_note.setText('No selection for the current ROI')
        if self.map_distributions is None:
            return
        if self.task_busy:
            self._right_task_pending = True
            self.right_spec = None
            self.shape_chart.clear(); self.shape_chart.setTitle('Computing selected ROI…')
            return
        from hyperlab.plots import map_distribution_plot, strip_profile_plot, roi_transform_plot
        from hyperlab.analysis.regions import strip_profile
        from hyperlab.experiment_metadata import compute_pinned
        context = self.map_distribution_context
        if task in ('ecdf','histogram'):
            spec = map_distribution_plot(self.map_distributions, source=source_identity(self.product_source),
                                         mode=task, brushes=self.map_brushes)
            spec.metadata['analysis_context'] = context
            spec.metadata['source_fingerprint'] = context.get('source_fingerprint')
            self.draw_right_plot(spec,brush=True); return
        record = next((item for item in context['regions'] if item['roi_id'] == self.inspect_roi.currentData()),None)
        if record is None:
            return
        if task == 'profile':
            if record['geometry']['type'] != 'strip':
                self.right_spec = None
                self.shape_chart.clear(); self.shape_chart.setTitle('Select a line / strip ROI')
                self.brush_note.setText('No selected map range. Select a line / strip ROI for a profile.'); return
            cube, product, request = self.product_source, self.map_distribution_product, self._right_request
            def completed(payload):
                if (self.product_source is not cube or self.map_distribution_product is not product or
                        self._right_request != request or self.inspect_roi.currentData() != record['roi_id']):
                    return
                result, fingerprint = payload
                if fingerprint != context.get('source_fingerprint'):
                    raise ValueError('Source changed since the map was computed; recompute the map before its profile.')
                spec = strip_profile_plot(result, source=source_identity(cube), source_fingerprint=fingerprint,
                                          analysis_context=context)
                self.draw_right_plot(spec)
                self.notify(f"Profile complete: {record['name']} · raw pixel positions and full-resolution counts.")
            self.background(lambda:compute_pinned(cube, lambda:strip_profile(cube,record,policy=context['policy'],exclusions=context['exclusions'])),
                            completed,'Computing exact cross-strip profile…'); return
        if not self.plot_spec or not self.plot_spec.metadata.get('roi_comparison'):
            return
        reference_id = context['reference_roi_id']
        indices = context.get('analyzed_roi_indices',range(len(self.roi_results)))
        ref = next((self.roi_results[i][context['summary']] for i,original in enumerate(indices)
                    if context['regions'][original]['roi_id'] == reference_id),None)
        if task == 'residual' and ref is None:
            self.brush_note.setText('Select an included reference ROI and recompute this map.'); return
        common = np.all(np.isfinite([item[context['summary']] for item in self.roi_results]),axis=0)
        spec = roi_transform_plot(self.plot_spec, task, reference=ref, common=common, reference_roi_id=reference_id)
        self.draw_right_plot(spec)

    def apply_map_brush(self):
        if self.map_distributions is None or self.right_task.currentData() not in ('ecdf','histogram'):
            return
        if self.task_busy:
            self._brush_pending = True
            self.brush_note.setText('Computing the latest selected ROI and range…')
            return
        from hyperlab.analysis.distributions import brush_map
        context=self.map_distribution_context
        record=next((item for item in context['regions'] if item['roi_id'] == self.inspect_roi.currentData()),None)
        if record is None:
            return
        product=self.map_distribution_product; bounds=[self.brush_low.value(),self.brush_high.value()]
        task, request = self.right_task.currentData(), self._right_request
        def completed(result):
            if self.map_distributions is None or self.map_distribution_product is not product:
                return
            if self.right_task.currentData() != task:
                return
            if (self.inspect_roi.currentData() != record['roi_id'] or
                    [self.brush_low.value(),self.brush_high.value()] != bounds):
                self._brush_pending = True
                return
            if self._right_request != request:
                return
            self.map_brushes=[result]
            self.brush_low.setValue(result['metadata']['value_range'][0])
            self.brush_high.setValue(result['metadata']['value_range'][1])
            if hasattr(self,'brush_region'):
                self.brush_region.blockSignals(True)
                self.brush_region.setRegion(result['metadata']['value_range'])
                self.brush_region.blockSignals(False)
            coordinates=result['coordinates_yx']
            if len(coordinates) <= 20000:
                self.brush_mask_overlay.clear()
                self.brush_overlay.setData(x=coordinates[:,1]+.5,y=coordinates[:,0]+.5)
                result['metadata']['display_selection']={'method':'exact raw-coordinate points'}
            else:
                self.brush_overlay.clear()
                mask=result['mask']; h,w=mask.shape
                sy,sx=max(1,int(np.ceil(h/600))),max(1,int(np.ceil(w/900)))
                overview=np.logical_or.reduceat(np.logical_or.reduceat(mask,np.arange(0,h,sy),axis=0),
                                                np.arange(0,w,sx),axis=1)
                self.brush_mask_overlay.setImage(overview.astype(np.uint8),autoLevels=False,levels=(0,1))
                self.brush_mask_overlay.setRect(QtCore.QRectF(0,0,w,h))
                result['metadata']['display_selection']={'method':'any-selected overview cells', 'stride_yx':[sy,sx],
                    'scope':'Display only; exact full mask and every raw coordinate retained in export'}
            counts=result['metadata']['counts']
            self.brush_note.setText(f"Selected contrast pixels: {counts['selected']} / {counts['used']} valid / {counts['geometry']} in ROI. No defect truth.")
            if self.right_spec:
                self.right_spec.brushes=[result]
            self.notify(f"Map range selection complete: {counts['selected']} / {counts['used']} valid pixels in {record['name']}.")
        self.background(lambda:brush_map(product,record,bounds,exclusions=context['exclusions']),completed,
                        'Selecting the inclusive map range at exact raw pixel coordinates…')

    def refresh_product(self):
        if self.product is not None:
            self.show_product(self.product, self.product_source)

    def close_source_dialogs(self):
        for dialog in self.findChildren(W.QDialog):
            if dialog.property('source_bound') or dialog in [getattr(self, name, None) for name in
                    ('_reference_dialog', '_annotation_dialog', '_roi_bounds_dialog')]:
                dialog.setProperty('source_invalidated', True)
                dialog.reject()
        self._right_task_pending = self._brush_pending = False
        self._right_request += 1

    def figure_export(self):
        choices = {'Current chart': self.plot_spec}
        sources = {'Current chart': (self.plot_source, self.plot_annotation)}
        if self.right_spec is not None:
            choices['Right task plot + selections'] = self.right_spec
            sources['Right task plot + selections'] = (self.product_source,
                self.right_spec.metadata.get('analysis_context',{}).get('annotation'))
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
        dialog.setProperty('source_bound', True)
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
            if dialog.property('source_invalidated'):
                self.notify('The source was replaced. Open Figure export for the current result.'); return
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
        if self.session and self.session.state == 'stopping':
            self.notify('Wait for acquisition to finish stopping before opening data.')
            return
        # Opening a file is an explicit viewing choice; the camera keeps its owner.
        self.follow_camera = False
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
            self.close_source_dialogs()
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
            self.notify(f'Reopened {path}' + (f' · {self.roi_source_notice}' if self.roi_source_notice else ''))
        self.background(read, loaded, 'Reopening local data…')

    def band_changed(self, index, *, reset_axis=False):
        if self.sequence:
            frame = self.sequence.frame(index)
            meta = dict(frame.metadata)
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
        self.close_source_dialogs()
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
                from hyperlab.io.labels import display_labels
                labels = display_labels(item['source_provenance'], len(stats['mean']))
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
        indices = [i for i,flag in enumerate(context['included']) if flag]
        if not indices:
            self.notify('Select Use for at least one target or reference ROI.'); return
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
        self.background(lambda:compute_pinned(cube, lambda:recorded_roi_plot(sequence,[context['regions'][i] for i in indices],
                        [context['names'][i] for i in indices],[context['colors'][i] for i in indices],
                        policy=context['policy'], band=context['trace_channel'],exclusions=context['exclusions'])),
                        completed,'Computing all recorded ROI samples…')

    def quality_details(self):
        if self.cube is None or self.task_busy:
            self.notify('Open data and finish the current operation before inspecting quality.')
            return
        from hyperlab.acquisition.readiness import measurement_readiness
        from hyperlab.experiment_metadata import compute_pinned
        cube, policy = self.cube, self.policy.currentData()
        dialog = W.QDialog(self); dialog.setWindowTitle('Full-resolution quality · pinned observation')
        dialog.resize(700,520); layout = W.QVBoxLayout(dialog)
        text = W.QPlainTextEdit('Computing exact counts and quantiles from the pinned raw frame…')
        text.setReadOnly(True); layout.addWidget(text)
        layout.addWidget(self.button('Close',dialog.accept))
        self._quality_dialog = dialog
        dialog.show()
        def complete(payload):
            report, fingerprint = payload
            self.last_readiness = dict(report, source_fingerprint=fingerprint)
            text.setPlainText(json_text(self.last_readiness))
        self.background(lambda: compute_pinned(cube, lambda: measurement_readiness(cube, policy=policy)),
                        complete, 'Inspecting full-resolution quality of the pinned observation…')

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
        self.close_source_dialogs()
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
        if self.roi_records[index]['geometry']['type'] != 'rectangle':
            raise ValueError('Bounds editing requires a rectangle; use Edit for vertices, strip width or mask role.')
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
        from hyperlab.ui.roi_dialog import edit_regions
        edit_regions(self)

    def rebuild_roi_graphics(self):
        for item in [*self.rois, *self.roi_labels, *self.roi_fills]:
            self.plot.removeItem(item)
        self.rois, self.roi_labels, self.roi_fills = [], [], []
        for index in range(len(self.roi_names)):
            self._create_roi(index)

    def reorder_roi(self, index, other):
        self.regions()
        for items in (self.roi_names, self.roi_colors, self.roi_rows, self.roi_visible,
                      self.roi_included, self.roi_records):
            items.insert(other, items.pop(index))
        for row in self.roi_rows:
            self.roi_form.removeWidget(row)
            self.roi_form.addWidget(row)
        self.rebuild_roi_graphics()
        self.roi_changed()

    def import_roi_mask(self):
        if self.cube is None:
            return
        path, _ = W.QFileDialog.getOpenFileName(self, 'Import binary mask in raw coordinates', '', 'Binary mask (*.npy *.png *.tif *.tiff)')
        if not path:
            return
        from hyperlab.analysis.regions import mask_geometry, make_roi
        cube = self.cube
        def completed(geometry):
            if self.cube is cube:
                index = len(self.rois)
                color = COLORS[index % len(COLORS)]
                record = make_roi(cube.shape[:2], geometry, name='Mask ROI', color=color)
                self.add_roi(record['name'], color=color, record=record)
        self.background(lambda: mask_geometry(path, cube.shape[:2]), completed, 'Verifying binary mask bytes and raw shape…')

    def study_dialog(self):
        from hyperlab.ui.study_dialog import StudyDialog
        self._study_dialog = StudyDialog(self)
        self._study_dialog.show()

    def _analysis_panel(self):
        form = self.panel()
        self.roi_names = []
        self.roi_form = W.QVBoxLayout()
        form.addLayout(self.roi_form)
        self._roi_row('ROI A', COLORS[0])
        self._roi_row('ROI B', COLORS[1])
        row = W.QHBoxLayout()
        add = W.QToolButton(); add.setText('Add ROI'); add.setObjectName('add_roi')
        add.setPopupMode(W.QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        add.clicked.connect(lambda: self.add_roi())
        menu = W.QMenu(add)
        for label,kind in [('Rectangle','rectangle'),('Polygon','polygon'),('Line / strip','strip')]:
            menu.addAction(label, lambda checked=False, geometry=kind: self.add_roi(kind=geometry))
        menu.addAction('Import binary mask…', self.import_roi_mask); add.setMenu(menu)
        row.addWidget(add)
        row.addWidget(self.button('Edit…', self.edit_roi_bounds, 'roi_edit_bounds'))
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
                   ('Wavelength interval integral map','interval_map'), ('Wavelength interval mean map','interval_mean_map'),
                   ('Endpoint continuum / band depth', 'continuum'), ('PCA', 'pca'),
                   ('Spectral / state-vector angle', 'spectral_angle'), ('Recorded ROI trace', 'recorded')]
        for label, operation in methods:
            self.analysis_method.addItem(label, operation)
            action = QtGui.QAction(label, self)
            action.triggered.connect(lambda checked=False, op=operation: self.analyze(op))
            self.analysis_buttons[operation] = action
        self.analysis_method.currentIndexChanged.connect(self.method_changed)
        form.addWidget(self.analysis_method)
        self.reference_roi = W.QComboBox(); self.reference_roi.setObjectName('reference_roi')
        self.reference_roi.setToolTip('Reference is selected by stable ROI ID. Rename and reorder retain the selection.')
        self.reference_roi.currentIndexChanged.connect(self.choose_reference_roi)
        form.addWidget(self.reference_roi)
        self.pair_controls = W.QWidget()
        pair = W.QFormLayout(self.pair_controls); pair.setContentsMargins(0, 0, 0, 0)
        self.pair_a, self.pair_b = W.QSpinBox(), W.QSpinBox()
        pair.addRow('Feature A', self.pair_a); pair.addRow('Feature B', self.pair_b)
        self.minimum_denominator = W.QDoubleSpinBox()
        self.minimum_denominator.setDecimals(8); self.minimum_denominator.setRange(1e-8, 1e12)
        self.minimum_denominator.setValue(1e-6)
        pair.addRow('Min. |denominator|', self.minimum_denominator)
        self.minimum_denominator.setToolTip('Numerical denominator validity only; this is not a measured noise threshold.')
        self.low_signal_controls = W.QWidget()
        signal = W.QFormLayout(self.low_signal_controls); signal.setContentsMargins(0, 0, 0, 0)
        self.low_signal_enabled = W.QCheckBox('Analyst signal threshold')
        self.low_signal_enabled.setToolTip('Optional diagnostic exclusion using |A| + |B| in source units; no SNR estimate.')
        self.low_signal_threshold = W.QDoubleSpinBox()
        self.low_signal_threshold.setDecimals(6); self.low_signal_threshold.setRange(1e-6, 1e12)
        self.low_signal_threshold.setValue(1)
        self.low_signal_source = W.QLineEdit(); self.low_signal_source.setPlaceholderText('Reason / evidence source required')
        for item in (self.low_signal_threshold, self.low_signal_source):
            item.setEnabled(False)
            self.low_signal_enabled.toggled.connect(item.setEnabled)
        signal.addRow(self.low_signal_enabled); signal.addRow('Min. |A| + |B|', self.low_signal_threshold)
        signal.addRow(self.low_signal_source)
        self.low_signal_note = W.QLabel('Low-signal qualification: UNKNOWN')
        signal.addRow(self.low_signal_note)
        self.low_signal_enabled.toggled.connect(self.roi_changed)
        self.low_signal_threshold.valueChanged.connect(self.roi_changed)
        self.low_signal_source.textChanged.connect(self.roi_changed)
        pair.addRow(self.low_signal_controls)
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
        self.max_gap_nm = W.QDoubleSpinBox(); self.max_gap_nm.setDecimals(3); self.max_gap_nm.setRange(0, 1e9)
        self.max_gap_nm.setSpecialValueText('Unspecified')
        self.max_gap_nm.setToolTip('Optional explicit maximum adjacent wavelength gap. Unspecified imposes no invented physical cutoff.')
        self.max_gap_nm.valueChanged.connect(self.roi_changed)
        spectral.addRow('Max. adjacent gap (nm)', self.max_gap_nm)
        form.addWidget(self.spectral_controls)
        self.trace_channel = W.QComboBox(); self.trace_channel.addItem('0')
        self.trace_channel.setToolTip('Stored channel for time traces; channels are never averaged together.')
        self.trace_channel.currentIndexChanged.connect(self.roi_changed)
        for control in (self.pair_a, self.pair_b, self.minimum_denominator, self.feature_first,
                        self.feature_last, self.local_window, self.local_degree):
            control.valueChanged.connect(self.roi_changed)
        form.addWidget(self.trace_channel)
        self.run_button = self.button('Run analysis', self.run_analysis, 'roi_compare')
        self.run_button.setStyleSheet('QPushButton {background:#147b83; color:white; padding:8px; font-weight:600;} '
            'QPushButton:disabled {background:#dfe7eb; color:#71808b;}')
        form.addWidget(self.run_button)
        self.map_tools = W.QWidget(); map_form = W.QFormLayout(self.map_tools); map_form.setContentsMargins(0,0,0,0)
        self.right_task = W.QComboBox()
        for label,key in [('Map ECDF / brush','ecdf'),('Map histogram / brush','histogram'),
                          ('Line / strip profile','profile'),('Reference residual','residual'),('L2 shape','shape')]:
            self.right_task.addItem(label,key)
        self.right_task.currentIndexChanged.connect(self.update_right_task)
        map_form.addRow('Right plot',self.right_task)
        self.inspect_roi = W.QComboBox(); self.inspect_roi.currentIndexChanged.connect(self.update_right_task)
        map_form.addRow('Inspect ROI',self.inspect_roi)
        self.brush_low, self.brush_high = W.QDoubleSpinBox(), W.QDoubleSpinBox()
        for spin in (self.brush_low,self.brush_high):
            spin.setDecimals(8); spin.setRange(-1e100,1e100)
        brush_row = W.QHBoxLayout(); brush_row.addWidget(self.brush_low); brush_row.addWidget(self.brush_high)
        self.brush_controls = W.QWidget()
        brush_form = W.QFormLayout(self.brush_controls); brush_form.setContentsMargins(0,0,0,0)
        brush_form.addRow('Inclusive range',brush_row)
        brush_form.addRow(self.button('Select map range',self.apply_map_brush,'map_brush'))
        map_form.addRow(self.brush_controls)
        self.brush_note = W.QLabel('No selected contrast range'); self.brush_note.setWordWrap(True)
        map_form.addRow(self.brush_note)
        form.addWidget(self.map_tools); self.map_tools.hide()
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
        form.addWidget(self.button('Study…', self.study_dialog, 'study'))
        details = W.QToolButton(); details.setText('Plot and view options ▸'); details.setCheckable(True)
        form.addWidget(details)
        options = W.QWidget(); options_form = W.QVBoxLayout(options); options_form.setContentsMargins(0, 0, 0, 0)
        details.toggled.connect(options.setVisible)
        options_form.addWidget(self.plot_mode)
        self.shape_normalize = W.QCheckBox('L2 normalized shape')
        self.shape_normalize.setToolTip('Amplitude is retained. Normalization uses common finite features.')
        self.spatial_sd = W.QCheckBox('Show spatial spread (SD / IQR)'); self.spatial_sd.setChecked(True)
        self.categorical_style = W.QComboBox(); self.categorical_style.addItem('Channel points with connecting lines','connected')
        self.categorical_style.addItem('Channel points with whiskers','points')
        self.categorical_style.currentIndexChanged.connect(self.roi_changed); options_form.addWidget(self.categorical_style)
        for control in (self.shape_normalize, self.spatial_sd):
            options_form.addWidget(control); control.toggled.connect(self.roi_changed)
        self.pc_component = W.QComboBox(); self.pc_component.addItem('PC1 score'); self.pc_component.setEnabled(False)
        self.pc_component.currentIndexChanged.connect(self.refresh_product); options_form.addWidget(self.pc_component)
        self.angle_degrees = W.QCheckBox('Angle in degrees'); self.angle_degrees.toggled.connect(self.refresh_product)
        self.lock_map_limits = W.QCheckBox('Share map limits'); self.lock_map_limits.setChecked(True)
        self.robust_map_limits = W.QCheckBox('Robust map colour limits · 1–99%')
        self.robust_map_limits.setToolTip('Display only. Tails remain in values, distributions, brushes and exports.')
        self.robust_map_limits.toggled.connect(self.refresh_product)
        self.map_limits_note = W.QLabel('Colour limits: no map'); self.map_limits_note.setWordWrap(True)
        self.link_views = W.QCheckBox('Link image views'); self.link_views.setChecked(True)
        self.link_views.toggled.connect(self.set_view_link)
        for control in (self.angle_degrees, self.lock_map_limits, self.robust_map_limits, self.map_limits_note, self.link_views):
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
        self.reference_roi.setVisible(operation in ('reference_rmse', 'spectral_angle'))
        spectral = operation in ('smooth', 'derivative1', 'derivative2', 'integral', 'continuum','interval_map','interval_mean_map')
        self.pair_controls.setVisible(operation in ('difference', 'ratio', 'normalized_difference'))
        self.low_signal_controls.setVisible(operation == 'normalized_difference')
        self.spectral_controls.setVisible(spectral)
        self.local_window.setEnabled(operation in ('smooth', 'derivative1', 'derivative2'))
        self.local_degree.setEnabled(self.local_window.isEnabled())
        self.trace_channel.setVisible(operation == 'recorded' or self.plot_mode.currentIndex() == 1)
        if self.cube is None:
            self.run_button.setEnabled(False)
            return
        cap = capabilities(self.cube)
        self.low_signal_threshold.setSuffix(' ' + self.cube.metadata['units'])
        gate = {'pairs':'roi', 'reference_rmse':'roi', 'normalized_difference':'ratio',
                'smooth':'spectral_features', 'derivative1':'spectral_features',
                'derivative2':'spectral_features', 'integral':'spectral_features',
                'interval_map':'spectral_features','interval_mean_map':'spectral_features'}.get(operation, operation)
        allowed = bool(self.sequence) if operation == 'recorded' else cap['operations'].get(gate, False)
        self.run_button.setEnabled(allowed and not self.task_busy)
        if spectral:
            note = 'Common pixel support; measured wavelengths only.'
        elif operation in ('reference_rmse', 'spectral_angle'):
            note = 'Selected reference ROI; all enabled features must be valid.'
        else:
            note = 'ROI bounds use raw pixels.'
        if not allowed:
            note = 'Open a recorded sequence.' if operation == 'recorded' else cap['reasons'].get(gate, 'Unavailable for these data.')
        self.capability_label.setText(f"{cap['axis_kind']} · {cap['effective_dimensions']} features · {self.cube.metadata['units']}\n{note}")
        if not self.session or self.session.state not in ('streaming','recording'):
            self.install_interval_selector()

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
