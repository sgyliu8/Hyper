"""Select immutable reference files and inspect their recorded applicability."""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
from PySide6 import QtWidgets as W

from hyperlab.analysis import reflectance
from hyperlab.analysis.applicability import reference_applicability
from hyperlab.analysis.capabilities import capabilities
from hyperlab.analysis.core import calculation_dtype
from hyperlab.experiment_metadata import source_fingerprint
from hyperlab.io import load_cube, save_cube


_ROLES = {"sample": "Sample", "white": "White reference",
          "dark_sample": "Dark for sample", "dark_white": "Dark for white"}
_MEMORY_LIMIT = 256 * 1024**2


def _inspect(cubes, paths):
    return {"schema_version": 1, "paths": {role: str(path) for role, path in paths.items()},
            "applicability": reference_applicability(*cubes),
            "source_fingerprints": {role: source_fingerprint(cube)
                                    for role, cube in zip(_ROLES, cubes)}}


class ReferenceCorrectionDialog(W.QDialog):
    def __init__(self, workbench, sample=None, workspace=None):
        super().__init__(workbench)
        self.workbench = workbench
        self.workspace = Path(workspace if workspace is not None else workbench.workspace)
        self.receipt = None
        self._checked = False
        self._busy = False
        self.setWindowTitle("Reference correction")
        self.resize(820, 560)
        layout = W.QVBoxLayout(self)
        self.status = W.QLabel("Choose four source files, then check their recorded conditions.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.inputs = W.QWidget()
        form = W.QFormLayout(self.inputs)
        form.setContentsMargins(0, 0, 0, 0)
        self.paths = {}
        self.browse_buttons = {}
        for role, label in _ROLES.items():
            row = W.QHBoxLayout()
            field = W.QLineEdit()
            field.setObjectName(f"reference_{role}_path")
            field.setPlaceholderText("NPY, NPZ or ENVI header")
            button = W.QPushButton("Browse…")
            button.setObjectName(f"reference_{role}_browse")
            button.clicked.connect(lambda checked=False, key=role: self._browse(key))
            field.textChanged.connect(self._invalidate)
            self.paths[role] = field
            self.browse_buttons[role] = button
            row.addWidget(field, 1)
            row.addWidget(button)
            form.addRow(label, row)
        layout.addWidget(self.inputs)
        self.check_button = W.QPushButton("Check references")
        self.check_button.clicked.connect(self.check_references)
        layout.addWidget(self.check_button)
        self.details = W.QTreeWidget()
        self.details.setHeaderLabels(["Reference / field", "Status", "Reason / evidence"])
        self.details.setColumnWidth(0, 180)
        self.details.setColumnWidth(1, 95)
        layout.addWidget(self.details, 1)
        note = W.QLabel("MATCH means compatible recorded conditions; it does not verify or certify a calibration.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.options = W.QWidget()
        options = W.QFormLayout(self.options)
        options.setContentsMargins(0, 0, 0, 0)
        self.relative = W.QCheckBox("Relative ratio (white factor = 1; no white standard supplied)")
        self.relative.setChecked(True)
        self.relative.toggled.connect(self._controls)
        options.addRow(self.relative)
        self.factor = W.QDoubleSpinBox()
        self.factor.setRange(0, 1)
        self.factor.setDecimals(6)
        self.factor.setValue(.99)
        self.factor.setToolTip("One constant value at every wavelength; use only when justified by your reference evidence.")
        options.addRow("Constant white factor", self.factor)
        self.factor_source = W.QLineEdit()
        self.factor_source.setPlaceholderText("Source supporting this constant white factor")
        self.factor_source.textChanged.connect(self._controls)
        options.addRow("Factor source", self.factor_source)
        self.minimum = W.QDoubleSpinBox()
        self.minimum.setDecimals(9)
        self.minimum.setRange(1e-9, 1e12)
        self.minimum.setValue(1)
        options.addRow("Minimum white − dark (input units)", self.minimum)
        layout.addWidget(self.options)
        buttons = W.QHBoxLayout()
        self.save_report_button = W.QPushButton("Save check report…")
        self.save_report_button.clicked.connect(self.save_report)
        self.run_button = W.QPushButton("Correct and open")
        self.run_button.clicked.connect(self.run_correction)
        self.close_button = W.QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.save_report_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.run_button)
        layout.addLayout(buttons)
        sample = sample if sample is not None else workbench.cube
        if sample is not None:
            source = sample.metadata.get("source_file")
            if source and Path(source).is_file():
                self.paths["sample"].setText(str(source))
            gate = capabilities(sample)
            if not gate["operations"]["reflectance"]:
                self.status.setText("Current data cannot be corrected. " + gate["reasons"]["reflectance"]
                                    + " Browse a documented spectral sample to continue.")
        self._controls()

    def _active_acquisition(self):
        session = self.workbench.session
        return session is not None and session.state in ("streaming", "recording", "stopping")

    def _controls(self, *_):
        self.inputs.setEnabled(not self._busy)
        self.options.setEnabled(not self._busy)
        self.factor.setEnabled(not self.relative.isChecked())
        self.factor_source.setEnabled(not self.relative.isChecked())
        self.check_button.setEnabled(not self._busy and all(p.text().strip() for p in self.paths.values()))
        valid_factor = self.relative.isChecked() or bool(self.factor_source.text().strip())
        self.run_button.setEnabled(not self._busy and self._checked and valid_factor and not self._active_acquisition())
        self.run_button.setToolTip("Stop acquisition before opening a corrected cube." if self._active_acquisition() else "")
        self.save_report_button.setEnabled(not self._busy and self.receipt is not None)
        self.close_button.setEnabled(not self._busy)

    def _invalidate(self, *_):
        self.receipt = None
        self._checked = False
        self.details.clear()
        self.status.setText("Source selection changed. Check references before correction.")
        self._controls()

    def _browse(self, role):
        name, _ = W.QFileDialog.getOpenFileName(self, f"Choose {_ROLES[role].lower()}",
            self.paths[role].text() or str(self.workspace), "Cube (*.npy *.npz *.hdr)")
        if name:
            self.paths[role].setText(name)

    def _selected_paths(self):
        return {role: Path(field.text().strip()).resolve() for role, field in self.paths.items()}

    def _start(self, function, callback, label):
        if self._busy or self.workbench.task_busy or self.workbench.closing:
            self.status.setText("Wait for the current background operation to finish.")
            return
        self._busy = True
        self._controls()
        self.status.setText(label)
        def guarded():
            try:
                return {"value": function()}
            except Exception as error:
                return {"error": str(error)}
        def completed(result):
            self._busy = False
            if "error" in result:
                self._checked = False
                self.status.setText(result["error"])
                self.workbench.notify(result["error"])
            else:
                callback(result["value"])
            self._controls()
        self.workbench.background(guarded, completed, label)

    def check_references(self):
        paths = self._selected_paths()
        def inspect():
            with ExitStack() as stack:
                cubes = [stack.enter_context(load_cube(path)) for path in paths.values()]
                return _inspect(cubes, paths)
        def checked(receipt):
            self.receipt = receipt
            report = receipt["applicability"]
            self._checked = report["status"] == "MATCH"
            self.status.setText(f"{report['status']} · " + ("References have compatible recorded conditions."
                if self._checked else "Correction is blocked; review the source evidence below."))
            self.details.clear()
            for role, label in _ROLES.items():
                checks = [item for item in report["checks"] if item["role"] == role]
                failed = [item for item in checks if item["status"] != "MATCH"]
                state = "MISMATCH" if any(item["status"] == "MISMATCH" for item in failed) else "UNKNOWN" if failed else "MATCH"
                evidence = report["evidence"][role]
                row = W.QTreeWidgetItem([label, state, f"{evidence.get('kind') or 'Unknown'} · {evidence.get('source') or 'No evidence source'}"])
                self.details.addTopLevelItem(row)
                for item in failed:
                    row.addChild(W.QTreeWidgetItem([item["field"], item["status"], item["reason"]]))
                row.setExpanded(bool(failed))
            if self._checked and self._active_acquisition():
                self.status.setText("MATCH · Stop acquisition before opening a corrected cube.")
        self._start(inspect, checked, "Checking source files and recorded conditions…")

    def run_correction(self):
        if not self.run_button.isEnabled():
            return
        paths = self._selected_paths()
        expected = self.receipt["source_fingerprints"]
        relative = self.relative.isChecked()
        factor, source, minimum = self.factor.value(), self.factor_source.text().strip(), self.minimum.value()
        def correct():
            with ExitStack() as stack:
                cubes = [stack.enter_context(load_cube(path)) for path in paths.values()]
                receipt = _inspect(cubes, paths)
                if receipt["applicability"]["status"] != "MATCH":
                    raise ValueError("Reference conditions changed. Check the source files again.")
                if any(receipt["source_fingerprints"][role]["source_id"] != expected[role]["source_id"] for role in _ROLES):
                    raise ValueError("A source file or its metadata changed after checking. Check references again.")
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
                destination = self.workspace / "experiments" / f"reflectance_{stamp}" / "reflectance.npy"
                kwargs = {"reference_reflectance": None if relative else np.full(cubes[0].shape[2], factor),
                          "reference_source": None if relative else source, "minimum_denominator": minimum}
                dtype = np.result_type(*[calculation_dtype(cube.data) for cube in cubes])
                needed = cubes[0].data.size * (dtype.itemsize + 1)
                with reflectance(*cubes, output_path=destination if needed > _MEMORY_LIMIT else None,
                                 memory_threshold_bytes=_MEMORY_LIMIT, **kwargs) as corrected:
                    if needed <= _MEMORY_LIMIT:
                        save_cube(corrected, destination)
                receipt["correction"] = {"relative": relative, "constant_white_factor": 1 if relative else factor,
                    "factor_source": None if relative else source, "minimum_denominator": minimum,
                    "output": str(destination)}
                (destination.parent / "reference-check.json").write_text(json.dumps(receipt, indent=2, allow_nan=False), encoding="utf-8")
                return load_cube(destination)
        def corrected(cube):
            if self.workbench.closing or self._active_acquisition():
                path = cube.metadata["source_file"]
                cube.close()
                self.status.setText(f"Saved {path}. Stop acquisition and reopen the result.")
                return
            if self.workbench.sequence is not None:
                self.workbench.sequence.close()
                self.workbench.sequence = None
            if self.workbench.cube is not None:
                self.workbench.cube.close()
            self.workbench.set_cube(cube)
            self.workbench.add_recent(Path(cube.metadata["source_file"]))
            self.workbench.notify(f"Corrected cube saved: {cube.metadata['source_file']}")
            self.accept()
        self._start(correct, corrected, "Correcting into a new local output…")

    def save_report(self):
        if self.receipt is None:
            return
        name, _ = W.QFileDialog.getSaveFileName(self, "Save reference check", str(self.workspace / "reference-check.json"), "JSON (*.json)")
        if name:
            try:
                with Path(name).open("x", encoding="utf-8") as stream:
                    json.dump(self.receipt, stream, indent=2, allow_nan=False)
            except (OSError, ValueError) as error:
                self.status.setText(str(error))

    def reject(self):
        if not self._busy:
            super().reject()
