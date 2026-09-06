"""Offline clicks against explicit synthetic reference evidence; no device sessions."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtCore, QtWidgets as W

from hyperlab.io import Cube, load_cube, save_cube
from hyperlab.ui.reference_dialog import ReferenceCorrectionDialog
from hyperlab.ui.workbench import Workbench
from test_reference_applicability import reference_inputs


@pytest.fixture
def window(qtbot, tmp_path):
    workbench = Workbench(workspace=tmp_path / "workspace")
    qtbot.addWidget(workbench)
    return workbench


def saved_references(tmp_path):
    paths = {}
    for role, cube in zip(("sample", "white", "dark_sample", "dark_white"), reference_inputs()):
        paths[role] = save_cube(cube, tmp_path / f"{role}.npy")
    return paths


def dialog_for(window, qtbot, paths):
    dialog = ReferenceCorrectionDialog(window)
    qtbot.addWidget(dialog)
    for role, path in paths.items():
        dialog.paths[role].setText(str(path))
    dialog.show()
    return dialog


def click_check(dialog, qtbot):
    assert dialog.check_button.isEnabled()
    qtbot.mouseClick(dialog.check_button, QtCore.Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not dialog._busy, timeout=10000)


def test_rgb_is_blocked_but_sample_browser_is_available(window, tmp_path, qtbot, monkeypatch):
    cube = Cube(np.ones((4, 4, 3), np.uint8), {"data_level": "raw_frame",
        "channel_labels": ["R", "G", "B"], "pixel_format": "RGB8", "data_source": "LIVE"})
    window.set_cube(cube)
    source = save_cube(cube, tmp_path / "rgb.npy")
    dialog = ReferenceCorrectionDialog(window)
    qtbot.addWidget(dialog)
    dialog.show()
    assert "Current data cannot be corrected" in dialog.status.text()
    assert not dialog.run_button.isEnabled()
    monkeypatch.setattr(W.QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    for role in dialog.paths:
        qtbot.mouseClick(dialog.browse_buttons[role], QtCore.Qt.MouseButton.LeftButton)
    click_check(dialog, qtbot)
    assert dialog.receipt["applicability"]["status"] != "MATCH"
    assert not dialog.run_button.isEnabled()
    assert dialog.details.topLevelItemCount() == 4


@pytest.mark.parametrize("relative, expected", [(True, 2 / 9), (False, .2)])
def test_clicked_correction_preserves_sources_and_opens_new_cube(window, tmp_path, qtbot, relative, expected):
    paths = saved_references(tmp_path)
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.glob("*.npy*")}
    dialog = dialog_for(window, qtbot, paths)
    click_check(dialog, qtbot)
    assert dialog.receipt["applicability"]["status"] == "MATCH"
    assert dialog.run_button.isEnabled()
    if not relative:
        qtbot.mouseClick(dialog.relative, QtCore.Qt.MouseButton.LeftButton)
        assert not dialog.run_button.isEnabled()
        dialog.factor.setValue(.9)
        dialog.factor_source.setText("Declared constant factor in analytic synthetic test")
    qtbot.mouseClick(dialog.run_button, QtCore.Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not dialog._busy, timeout=10000)
    assert dialog.result() == W.QDialog.DialogCode.Accepted
    assert window.cube.metadata["data_level"] == "reflectance_cube"
    assert window.cube.metadata["reflectance_kind"] == ("relative" if relative else "reference-calibrated")
    assert window.cube.metadata["data_source"] == "SYNTHETIC"
    assert window.cube.metadata["reference_applicability"]["status"] == "MATCH"
    assert window.cube.metadata["completed"] is True and window.cube.metadata["partial"] is False
    np.testing.assert_allclose(window.cube.data, expected)
    destination = Path(window.cube.metadata["source_file"])
    receipt = json.loads((destination.parent / "reference-check.json").read_text())
    assert receipt["correction"]["relative"] is relative
    assert set(receipt["source_fingerprints"]) == set(paths)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in hashes.items())


def test_mismatched_white_is_blocked_and_report_can_be_saved(window, tmp_path, qtbot, monkeypatch):
    paths = saved_references(tmp_path)
    metadata_path = paths["white"].with_suffix(".npy.json")
    metadata = json.loads(metadata_path.read_text())
    metadata["measurement_context"]["geometry_id"] = "Different synthetic geometry"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    dialog = dialog_for(window, qtbot, paths)
    click_check(dialog, qtbot)
    assert not dialog.run_button.isEnabled()
    assert dialog.details.topLevelItem(1).text(1) == "MISMATCH"
    assert any(item["field"] == "geometry_id" for item in dialog.receipt["applicability"]["checks"])
    destination = tmp_path / "blocked-check.json"
    monkeypatch.setattr(W.QFileDialog, "getSaveFileName", lambda *args: (str(destination), ""))
    qtbot.mouseClick(dialog.save_report_button, QtCore.Qt.MouseButton.LeftButton)
    assert json.loads(destination.read_text())["applicability"]["status"] == "MISMATCH"
    assert not list((window.workspace / "experiments").glob("reflectance_*"))


def test_edited_source_after_check_is_rejected_before_output(window, tmp_path, qtbot):
    paths = saved_references(tmp_path)
    dialog = dialog_for(window, qtbot, paths)
    click_check(dialog, qtbot)
    values = np.load(paths["sample"])
    values[0, 0, 0] += 1
    np.save(paths["sample"], values)
    qtbot.mouseClick(dialog.run_button, QtCore.Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not dialog._busy, timeout=10000)
    assert "changed after checking" in dialog.status.text()
    assert not dialog.run_button.isEnabled()
    assert window.cube is None
    assert not list((window.workspace / "experiments").glob("reflectance_*"))


def test_selection_edit_invalidates_check_and_load_failure_recovers(window, tmp_path, qtbot):
    paths = saved_references(tmp_path)
    dialog = dialog_for(window, qtbot, paths)
    click_check(dialog, qtbot)
    dialog.paths["white"].setText(str(tmp_path / "missing.npy"))
    assert not dialog.run_button.isEnabled()
    assert dialog.receipt is None
    click_check(dialog, qtbot)
    assert "missing.npy" in dialog.status.text()
    assert dialog.check_button.isEnabled()
    assert dialog.close_button.isEnabled()
    assert not dialog.run_button.isEnabled()


def test_streamed_correction_uses_existing_out_of_core_contract(window, tmp_path, qtbot, monkeypatch):
    paths = saved_references(tmp_path)
    dialog = dialog_for(window, qtbot, paths)
    click_check(dialog, qtbot)
    monkeypatch.setattr("hyperlab.ui.reference_dialog._MEMORY_LIMIT", 1)
    qtbot.mouseClick(dialog.run_button, QtCore.Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not dialog._busy, timeout=10000)
    assert dialog.result() == W.QDialog.DialogCode.Accepted
    destination = Path(window.cube.metadata["source_file"])
    assert destination.with_suffix(".npy.valid.npy").is_file()
    with load_cube(destination) as cube:
        np.testing.assert_allclose(cube.data, 2 / 9)
        assert cube.valid_mask.all() and cube.metadata["completed"] is True


def test_matching_references_do_not_replace_active_acquisition(window, tmp_path, qtbot, monkeypatch):
    dialog = dialog_for(window, qtbot, saved_references(tmp_path))
    monkeypatch.setattr(dialog, "_active_acquisition", lambda: True)
    click_check(dialog, qtbot)
    assert dialog.receipt["applicability"]["status"] == "MATCH"
    assert "Stop acquisition" in dialog.status.text()
    assert not dialog.run_button.isEnabled()
