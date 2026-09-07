"""One modeless setup/processing flow, sharing scientific APIs with the CLI."""
from pathlib import Path
import json
import queue
import threading

from PySide6 import QtCore, QtWidgets as W

from hyperlab.io import load_cube
from hyperlab.ui.workbench import stamp


class SpectroscopyDialog(W.QDialog):
    def __init__(self, workbench):
        super().__init__(workbench)
        self.workbench = workbench
        self.setWindowTitle('Reflectance spectroscopy')
        self.resize(800, 630)
        self.setModal(False)
        self._busy = False
        self._external_summary = 'Not checked'
        self._progress = queue.Queue(maxsize=1)
        self.fields = {}
        layout = W.QVBoxLayout(self)
        self.capabilities = W.QLabel()
        self.capabilities.setWordWrap(True)
        self.capabilities.setStyleSheet('background:#e6edf2; padding:10px; color:#123e52;')
        layout.addWidget(self.capabilities)
        self.input_kind = W.QComboBox()
        self.input_kind.addItem('Raw optical states → reconstructed signal → reference ratio', 'raw')
        self.input_kind.addItem('Already reconstructed linear signals → reference ratio', 'signal')
        self.input_kind.addItem('External illumination bands → finite-band reference ratio', 'external')
        self.input_kind.currentIndexChanged.connect(self._mode)
        layout.addWidget(self.input_kind)
        self.form = W.QFormLayout()
        layout.addLayout(self.form)
        for key, label in [('response', 'Response bundle'), ('sample', 'Sample scan / signal'),
                           ('dark_sample', 'Sample dark scan'), ('white', 'White scan / signal'),
                           ('dark_white', 'White dark scan'), ('reference', 'Reference factors CSV'),
                           ('recipe', 'Acquisition recipe'), ('external', 'Band measurement manifest')]:
            row = W.QWidget()
            box = W.QHBoxLayout(row); box.setContentsMargins(0,0,0,0)
            field = W.QLineEdit(); field.setObjectName('spectroscopy_' + key)
            field.setPlaceholderText('Optional; otherwise an uncharacterized-reference ratio' if key == 'reference' else 'Choose a local file')
            button = W.QPushButton('Browse…')
            button.clicked.connect(lambda checked=False, name=key: self._browse(name))
            box.addWidget(field, 1); box.addWidget(button)
            self.fields[key] = field
            self.form.addRow(label, row)
        self.fields['response'].textChanged.connect(self._response_changed)
        self.minimum = W.QDoubleSpinBox()
        self.minimum.setDecimals(12); self.minimum.setRange(1e-12, 1e12); self.minimum.setValue(1e-12)
        self.minimum.setToolTip('Positive white-signal threshold in reconstructed signal units. This numerical floor is not a measured noise limit.')
        self.form.addRow('Minimum white signal', self.minimum)
        self.note = W.QLabel('References must share the calibrated response and spatial grid. A physically blocked dark is required for raw states. '
            'Reference CSV columns: wavelength_nm, reflectance; values must match the actual bands. '
            'Spatial SD describes pixel variation; it is not measurement uncertainty.')
        self.note.setWordWrap(True); layout.addWidget(self.note)
        controls = W.QHBoxLayout()
        self.inspect_button = W.QPushButton('Check inputs')
        self.inspect_button.clicked.connect(self.check_inputs)
        self.run_button = W.QPushButton('Process saved scans')
        self.run_button.setObjectName('spectroscopy_process')
        self.run_button.clicked.connect(self.process_saved)
        self.acquire_button = W.QPushButton('Acquire reflectance cube')
        self.acquire_button.setObjectName('spectroscopy_acquire')
        self.acquire_button.clicked.connect(self.acquire)
        self.stop_button = W.QPushButton('Stop')
        self.stop_button.clicked.connect(workbench.spectral_stop.set)
        for button in (self.inspect_button, self.run_button, self.acquire_button, self.stop_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.status = W.QLabel('Choose measured inputs. Processing preserves raw data and saves new products.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.details = W.QPlainTextEdit(); self.details.setReadOnly(True)
        self.details.setMaximumHeight(145); self.details.setPlaceholderText('Input checks and processing details')
        layout.addWidget(self.details)
        self.band_table = W.QTableWidget(0,6)
        self.band_table.setHorizontalHeaderLabels(['Step','Source peak (nm)','Support (nm)','White mean (DN)','Invalid ratio','ROI mean'])
        self.band_table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        self.band_table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.band_table.setMaximumHeight(165); self.band_table.hide(); layout.addWidget(self.band_table)
        for field in self.fields.values():
            field.textChanged.connect(self._inputs_changed)
        self.minimum.valueChanged.connect(self._inputs_changed)
        self.timer = QtCore.QTimer(self); self.timer.timeout.connect(self._poll); self.timer.start(150)
        if workbench.cube is not None:
            source = workbench.cube.metadata.get('source_file')
            if source:
                self.fields['sample'].setText(source)
            if workbench.cube.metadata['data_level'] == 'spectral_cube':
                self.input_kind.setCurrentIndex(1)
        if workbench.response_path:
            self.fields['response'].setText(str(workbench.response_path))
        setup = workbench.config.get('ui', {}).get('spectroscopy_setup', {})
        for key in ('response', 'dark_sample', 'white', 'dark_white', 'reference', 'recipe', 'external'):
            if setup.get(key):
                self.fields[key].setText(setup[key])
        index = self.input_kind.findData(setup.get('mode'))
        if index >= 0:
            self.input_kind.setCurrentIndex(index)
        if setup.get('minimum_denominator') is not None:
            self.minimum.setValue(setup['minimum_denominator'])
        self._mode()

    def setup_values(self):
        return {**{key: self.fields[key].text().strip() for key in
                   ('response', 'dark_sample', 'white', 'dark_white', 'reference', 'recipe', 'external')},
                'mode': self.input_kind.currentData(), 'minimum_denominator': self.minimum.value()}

    def _response_changed(self):
        value = self.fields['response'].text().strip()
        self.workbench.response_path = Path(value) if value else None
        self.workbench.response_summary = None

    def _browse(self, key):
        filters = 'Measurement / response JSON (*.json)' if key in ('response', 'recipe', 'external') else (
            'Reference CSV (*.csv)' if key == 'reference' else 'Cube files (*.npy *.npz *.hdr)')
        name, _ = W.QFileDialog.getOpenFileName(self, 'Select ' + key.replace('_', ' '), str(self.workbench.workspace), filters)
        if name:
            self.fields[key].setText(name)

    def _mode(self):
        raw = self.input_kind.currentData() == 'raw'
        external = self.input_kind.currentData() == 'external'
        for key in self.fields:
            visible = external if key == 'external' else (raw if key in ('response','dark_sample','dark_white','recipe') else not external)
            self.form.setRowVisible(self.fields[key].parentWidget(), visible)
        self.form.setRowVisible(self.minimum,not external)
        self.acquire_button.setVisible(raw)
        self.note.setText('Use the saved band manifest with matched sample, white and background observations. '
            'Its minimum white DN, measured source profiles and reference weighting are checked. Manual placement stays labelled manual.' if external else
            'Use matching spatial grids, instrument conditions and reference factors. Raw optical states require a response and matched blocked-light dark scans. '
            'Spatial SD describes pixel variation, not measurement uncertainty.')
        self._inputs_changed()
        self._poll()

    def _inputs_changed(self):
        self._external_summary = 'Not checked'
        self.band_table.hide()
        self.details.clear()
        self.status.setText('Choose inputs, then check or process. Results are saved as new products.')

    def _poll(self):
        wb = self.workbench
        sensor = wb.session.state if wb.session else 'disconnected'
        selector = 'Configured adapter; check its current preflight' if wb.spectral_adapter is not None else 'Not configured'
        response = wb.response_summary or 'Not checked'
        self.capabilities.setText(f'Sensor: {sensor}   |   Acquisition: saved external-band observations\nSource bands / reference: {self._external_summary}'
            if self.input_kind.currentData() == 'external' else f'Sensor: {sensor}   |   Spectral selector: {selector}\nResponse: {response}')
        if wb.spectral_adapter is None:
            self.acquire_button.setToolTip('Identify and characterize a physical selector, or use measured external illumination bands. Sensor connection alone does not establish spectral control.')
        ready = not self._busy and not wb.task_busy and not wb.closing
        self.inspect_button.setEnabled(ready); self.run_button.setEnabled(ready)
        self.acquire_button.setEnabled(ready and wb.spectral_adapter is not None)
        self.stop_button.setEnabled(self._busy)
        self.input_kind.setEnabled(ready)
        self.minimum.setEnabled(ready)
        for field in self.fields.values():
            field.setEnabled(ready)
            for button in field.parentWidget().findChildren(W.QPushButton):
                button.setEnabled(ready)
        try:
            report = self._progress.get_nowait()
        except queue.Empty:
            return
        self.status.setText(str(report.get('phase', report.get('status', 'Processing'))) +
                            (f" · {report['durable']} states saved" if 'durable' in report else
                             f" · {report['completed_pixels']} pixels processed" if 'completed_pixels' in report else ''))

    def _values(self, *, acquiring=False):
        values = {key: field.text().strip() or None for key, field in self.fields.items()}
        if self.input_kind.currentData() == 'external':
            if not values['external']:
                raise ValueError('Choose the external-band measurement manifest')
            return {'external':values['external']}
        if (not acquiring and not values['sample']) or not values['white']:
            raise ValueError('Choose sample and white files')
        if self.input_kind.currentData() == 'raw' and any(not values[key] for key in ('response', 'dark_sample', 'dark_white')):
            raise ValueError('Choose the response bundle and both matched dark scans')
        if self.input_kind.currentData() == 'signal':
            for key in ('response', 'dark_sample', 'dark_white'):
                values[key] = None
        return values

    def _run(self, function, complete, text):
        wb = self.workbench
        if self._busy or wb.task_busy or wb.closing:
            return
        self._busy = True; wb.spectral_stop.clear(); wb.spectral_busy = True
        self.status.setText(text)
        def guarded():
            try:
                return {'result': function()}
            except Exception as error:
                return {'error': str(error)}
        def finished(payload):
            self._busy = False; wb.spectral_busy = False
            while not self._progress.empty():
                self._progress.get_nowait()
            if 'error' in payload:
                self.status.setText(payload['error']); wb.notify(payload['error'])
            else:
                complete(payload['result'])
            self._poll(); wb.update_controls()
        wb.background(guarded, finished, text)

    def _notify_progress(self, report):
        try:
            self._progress.get_nowait()
        except queue.Empty:
            pass
        try:
            self._progress.put_nowait(report)
        except queue.Full:
            pass

    def check_inputs(self):
        try:
            values = self._values()
        except ValueError as error:
            self.status.setText(str(error)); return
        minimum = self.minimum.value()
        def inspect():
            if values.get('external') and len(values)==1:
                from hyperlab.spectroscopy.external_bands import process_external_bands
                return process_external_bands(values['external'], self.workbench.workspace, inspect_only=True)
            from contextlib import ExitStack
            from hyperlab.spectroscopy.response import load_response, validate_reconstruction
            from hyperlab.spectroscopy.reflectance import validate_reflectance_corrected
            with ExitStack() as stack:
                sample = stack.enter_context(load_cube(values['sample']))
                white = stack.enter_context(load_cube(values['white']))
                if values['response']:
                    bundle = load_response(values['response'])
                    ds = stack.enter_context(load_cube(values['dark_sample']))
                    dw = stack.enter_context(load_cube(values['dark_white']))
                    result = {'sample': validate_reconstruction(sample, ds, bundle),
                              'white': validate_reconstruction(white, dw, bundle),
                              'response': bundle['metadata']['wavelengths'],
                              'note': 'Reference-ratio compatibility is checked again on the reconstructed products.'}
                    if values['reference']:
                        from hyperlab.spectroscopy.workflow import read_reference_factors
                        read_reference_factors(values['reference'], bundle['metadata']['wavelengths'])
                else:
                    from hyperlab.spectroscopy.workflow import read_reference_factors
                    from hyperlab.io.cube import wavelength_unit_scale
                    factors = None
                    if values['reference']:
                        if sample.wavelengths is None or wavelength_unit_scale(sample.metadata['wavelength_units']) is None:
                            raise ValueError('Reference factors need actual wavelengths with known length units')
                        factors = read_reference_factors(values['reference'], sample.wavelengths * wavelength_unit_scale(sample.metadata['wavelength_units']))
                    result = validate_reflectance_corrected(sample, white, minimum_denominator=minimum,
                        reference_reflectance=factors, reference_source=values['reference'])
                return result
        def checked(result):
            if values.get('external') and len(values)==1:
                self._external_summary = f"{len(result['source_bands'])} observations · recorded compatibility checked"
            self.details.setPlainText(json.dumps(result, indent=2, default=str))
            self.status.setText('Inputs are incompatible; see the mismatched fields below.' if result.get('allowed') is False
                                else 'Raw reconstruction checks passed. Reference compatibility is checked after reconstruction.' if 'response' in result
                                else 'Recorded input compatibility passed. Independent physical accuracy remains unverified.')
            if 'response' in result:
                wavelengths = result['response']
                self.workbench.response_summary = f'{len(wavelengths)} declared wavelengths · {min(wavelengths):g}–{max(wavelengths):g} nm; see checks'
        self._run(inspect, checked, 'Checking input correction history and response applicability…')

    def process_saved(self):
        try:
            values = self._values()
        except ValueError as error:
            self.status.setText(str(error)); return
        directory = self.workbench.workspace/'experiments'/('spectroscopy_' + stamp())
        minimum = self.minimum.value()
        def process():
            if values.get('external') and len(values)==1:
                from hyperlab.spectroscopy.external_bands import process_external_bands
                return process_external_bands(values['external'],directory,stop=self.workbench.spectral_stop,progress=self._notify_progress)
            from hyperlab.spectroscopy.workflow import process_spectroscopy
            return process_spectroscopy(values['sample'], values['white'], directory,
                response_path=values['response'], dark_sample_path=values['dark_sample'], dark_white_path=values['dark_white'],
                reference_csv=values['reference'], minimum_denominator=minimum,
                stop=self.workbench.spectral_stop, progress=self._notify_progress)
        self._run(process, self._completed, 'Calculating finite-band pixelwise reference ratios…' if values.get('external') and len(values)==1 else
                  'Reconstructing and calculating pixelwise reference ratios…')

    def _completed(self, result):
        diagnostics = result.get('diagnostics')
        self.band_table.setVisible(bool(diagnostics))
        if diagnostics:
            self._external_summary = f"{len(diagnostics['bands'])} observations · product saved; see diagnostics"
            self.band_table.setRowCount(len(diagnostics['bands']))
            roi = diagnostics.get('roi',{}).get('mean',[])
            for i,band in enumerate(diagnostics['bands']):
                values = [band['step_id'],band['source_peak_nm'],str(band['source_support_nm']),band['white_mean_dn'],
                          f"{100*band['invalid_ratio_fraction']:.1f}%",roi[i] if i<len(roi) else 'Select ROI']
                for j,value in enumerate(values):
                    self.band_table.setItem(i,j,W.QTableWidgetItem(f'{value:.5g}' if isinstance(value,float) else str(value)))
            self.details.setPlainText(json.dumps({k:v for k,v in diagnostics.items() if k!='bands'},indent=2,default=str))
        else:
            self.details.setPlainText(json.dumps(result, indent=2, default=str))
        wb = self.workbench
        if result.get('completed') and result.get('product') and not wb.closing:
            wb.follow_camera = False
            cube = load_cube(result['product'])
            wb.close_source_dialogs()
            if wb.sequence:
                wb.sequence.close()
                wb.sequence = None
            if wb.cube is not None:
                wb.cube.close()
            wb.set_cube(cube)
            wb.add_recent(Path(result['product']))
            wb.tabs.setCurrentIndex(1)
            origin = 'SYNTHETIC' if cube.metadata.get('synthetic') else cube.metadata['acquisition_source']
            self.status.setText(f'Product saved ({origin}). Select pixels or ROIs in Analysis to read the finite-band response.' if diagnostics else
                f'Product saved ({origin}). Select pixels or ROIs in Analysis to read the wavelength spectrum.')
        else:
            self.status.setText('Partial acquisition retained. The previous complete result remains available.')

    def acquire(self):
        wb = self.workbench
        if wb.spectral_adapter is None:
            self.status.setText('No verified spectral selector adapter is installed.'); return
        try:
            values = self._values(acquiring=True)
            if not values['recipe']:
                raise ValueError('Choose the verified acquisition recipe')
            recipe = json.loads(Path(values['recipe']).read_text(encoding='utf8'))
        except (OSError, ValueError) as error:
            self.status.setText(str(error)); return
        directory = wb.workspace/'experiments'/('acquisition_' + stamp())
        minimum = self.minimum.value()
        def acquire_and_process():
            from hyperlab.spectroscopy.scan import stationary_scan
            from hyperlab.spectroscopy.workflow import process_spectroscopy
            if wb.session and not wb.session.close(wait=True):
                raise RuntimeError('Previous sensor owner did not release its resources')
            scan = stationary_scan(wb.spectral_adapter, recipe, directory/'raw', stop=wb.spectral_stop, progress=self._notify_progress)
            if not scan['completed']:
                return scan
            if any(item['status'] != 'PASS' for item in scan['cleanup']):
                raise RuntimeError('Raw scan saved but controller cleanup failed; resolve the owner before continuing')
            return process_spectroscopy(scan['raw_path'], values['white'], directory/'products',
                response_path=values['response'], dark_sample_path=values['dark_sample'], dark_white_path=values['dark_white'],
                reference_csv=values['reference'], minimum_denominator=minimum, stop=wb.spectral_stop, progress=self._notify_progress)
        self._run(acquire_and_process, self._completed, 'Acquiring a stationary optical recipe…')

    def reject(self):
        if self._busy:
            self.workbench.spectral_stop.set()
            self.status.setText('Stopping and preserving partial output…')
            return
        super().reject()
