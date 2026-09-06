"""Optional analyst context; acquisition and calibration metadata stay read-only."""
from pathlib import Path

from PySide6 import QtWidgets as W

from hyperlab.experiment_metadata import load_annotation, normalize_annotations, save_annotation


class AnnotationDialog(W.QDialog):
    """Edit source-bound revisions using the workbench background queue."""

    def __init__(self, workbench):
        super().__init__(workbench)
        self.workbench = workbench
        self.cube = workbench.cube
        if self.cube is None:
            raise ValueError('Open source data before adding specimen context')
        self.record = workbench.annotation
        self.busy = False
        self.setWindowTitle('Specimen and thermal context')
        self.resize(600, 570)
        layout = W.QVBoxLayout(self)
        note = W.QLabel('Optional analyst declarations. Blank fields stay unknown. '
                        'Acquisition metadata and calibration evidence are read-only.')
        note.setWordWrap(True)
        layout.addWidget(note)
        source = self.cube.metadata.get('source_file')
        self.source_label = W.QLabel('Source: ' + (Path(source).name if source else
            f"{self.cube.metadata['data_level']} · frame {self.cube.metadata.get('sequence', 'unknown')}"))
        self.source_label.setWordWrap(True)
        if source:
            self.source_label.setToolTip(str(source))
        layout.addWidget(self.source_label)
        self.tabs = W.QTabWidget()
        layout.addWidget(self.tabs)
        specimen, notes = W.QWidget(), W.QWidget()
        self.tabs.addTab(specimen, 'Specimen and thermal history')
        self.tabs.addTab(notes, 'Acquisition notes')
        specimen_form, notes_form = W.QFormLayout(specimen), W.QFormLayout(notes)
        self.fields = {}
        for key, label in (('specimen_id', 'Specimen ID'), ('material', 'Material / coating'),
                ('coating_batch', 'Coating batch'), ('substrate', 'Substrate'),
                ('session_label', 'Session label'), ('replicate_id', 'Replicate ID')):
            self._line(specimen_form, key, label)
        self._line(specimen_form, 'temperature_value', 'Temperature value')
        self._combo(specimen_form, 'temperature_unit', 'Temperature unit',
                    [('Degrees Celsius (°C)', 'degC'), ('Kelvin (K)', 'K')])
        self._combo(specimen_form, 'temperature_meaning', 'Temperature meaning',
                    [('Setpoint', 'setpoint'), ('Independent measurement', 'independent_measurement'),
                     ('Owner label', 'owner_label')])
        self._line(specimen_form, 'temperature_reference_id', 'Temperature reference ID')
        self._line(specimen_form, 'dwell_seconds', 'Dwell time (s)')
        for key, label in (('illumination_id', 'Illumination ID'), ('geometry_id', 'Geometry ID')):
            self._line(notes_form, key, label)
        for key, label, height in (('reference_ids', 'Reference IDs (one per line)', 90),
                                   ('notes', 'Notes', 150)):
            field = W.QPlainTextEdit()
            field.setPlaceholderText('Unknown' if key == 'notes' else 'No references declared')
            field.setMaximumHeight(height)
            self.fields[key] = field
            notes_form.addRow(label, field)
        self.status_label = W.QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        row = W.QHBoxLayout()
        self.load_button = W.QPushButton('Load prior revision…')
        self.load_button.clicked.connect(self.choose_revision)
        row.addWidget(self.load_button)
        row.addStretch()
        self.save_button = W.QPushButton('Save new revision')
        self.save_button.clicked.connect(self.save)
        self.save_button.setDefault(True)
        row.addWidget(self.save_button)
        close = W.QPushButton('Close')
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)
        self._fill(self.record['values'] if self.record else normalize_annotations({}))
        self._status(f"Revision {self.record['revision']} loaded." if self.record else
                     'No annotation revision saved for this source.')

    def _line(self, form, key, label):
        field = W.QLineEdit()
        field.setPlaceholderText('Unknown')
        self.fields[key] = field
        form.addRow(label, field)

    def _combo(self, form, key, label, choices):
        field = W.QComboBox()
        field.addItem('Unknown', None)
        for text, value in choices:
            field.addItem(text, value)
        self.fields[key] = field
        form.addRow(label, field)

    def _fill(self, values):
        for key, field in self.fields.items():
            value = values.get(key)
            if isinstance(field, W.QComboBox):
                field.setCurrentIndex(max(0, field.findData(value)))
            elif isinstance(field, W.QPlainTextEdit):
                field.setPlainText('\n'.join(value or []) if key == 'reference_ids' else value or '')
            else:
                field.setText('' if value is None else str(value))

    def values(self):
        values = {}
        for key, field in self.fields.items():
            if isinstance(field, W.QComboBox):
                value = field.currentData()
            elif isinstance(field, W.QPlainTextEdit):
                value = field.toPlainText()
                if key == 'reference_ids':
                    value = value.splitlines()
            else:
                value = field.text()
            values[key] = value
        return normalize_annotations(values)

    def _status(self, text, *, error=False):
        self.status_label.setText(text)
        self.status_label.setStyleSheet('color: #a52a2a;' if error else '')

    def _ready(self):
        if self.cube is not self.workbench.cube:
            self._status('Source changed. Reopen this dialog for the current data.', error=True)
            return False
        if self.busy or self.workbench.task_busy or self.workbench.closing:
            self._status('Another operation is still running. Try again when it finishes.', error=True)
            return False
        return True

    def _dispatch(self, function, action):
        if not self._ready():
            return
        self.busy = True
        for widget in (self.tabs, self.save_button, self.load_button):
            widget.setEnabled(False)
        self._status(f'{action} source-bound annotation…')

        def run():
            # Deliver failures to this dialog as well as the workbench status.
            try:
                return function(), None
            except Exception as error:
                return None, error

        def completed(outcome):
            self.busy = False
            for widget in (self.tabs, self.save_button, self.load_button):
                widget.setEnabled(True)
            result, error = outcome
            if error is not None:
                text = f'{type(error).__name__}: {error}'
                self._status(text, error=True)
                self.workbench.notify(text)
                return
            record, path = result
            if self.cube is not self.workbench.cube or self.workbench.closing:
                text = f'Source changed. Revision retained at {path}; current data were not updated.'
                self._status(text, error=True)
                self.workbench.notify(text)
                return
            self.record = record
            self.workbench.annotation = record
            self.workbench.annotation_path = Path(path)
            self.workbench.roi_changed()
            self._fill(record['values'])
            text = f"{action} complete: annotation revision {record['revision']}."
            self._status(text)
            self.workbench.notify(text)

        self.workbench.background(run, completed, f'{action} source-bound annotation…')

    def save(self):
        if not self._ready():
            return
        try:
            values = self.values()
        except ValueError as error:
            self._status(str(error), error=True)
            return
        cube, previous = self.cube, self.record
        directory = self.workbench.workspace / 'annotations'
        self._dispatch(lambda: save_annotation(directory, cube, values, previous=previous), 'Save')

    def choose_revision(self):
        if not self._ready():
            return
        path, _ = W.QFileDialog.getOpenFileName(self, 'Load annotation revision',
            str(self.workbench.workspace / 'annotations'), 'Annotation JSON (*.json)')
        if path:
            self.load_revision(path)

    def load_revision(self, path):
        cube, path = self.cube, Path(path)
        self._dispatch(lambda: (load_annotation(path, cube), path), 'Load')
