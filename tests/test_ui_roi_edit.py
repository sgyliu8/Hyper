"""Advanced raw-pixel ROI bounds; offline Qt only."""
import numpy as np
import pytest
from PySide6 import QtWidgets as W

from hyperlab.io import Cube
from hyperlab.ui.workbench import Workbench


@pytest.fixture
def window(qtbot, tmp_path):
    workbench = Workbench()
    workbench.output_dir = tmp_path
    qtbot.addWidget(workbench)
    workbench.set_cube(Cube(np.arange(12 * 16 * 3).reshape(12, 16, 3)))
    return workbench


def test_exact_bounds_preserve_other_roi_zoom_band_and_hidden_state(window):
    other = window.rectangles()[0]
    window.rois[1].hide()
    window.plot.setRange(xRange=(2, 8), yRange=(3, 7), padding=0)
    window.band.setValue(2)
    window.apply_roi_bounds(1, (1, 2, 16, 12))
    assert window.rectangles() == [other, (1, 2, 16, 12)]
    assert not window.rois[1].isVisible()
    assert window.band.value() == 2


@pytest.mark.parametrize('bounds', [(0, 0, 0, 3), (2, 3, 4, 3), (-1, 0, 3, 4),
                                     (0, 0, 17, 12), (0, 0, 3, 13), (0.1, 0, 3, 4)])
def test_invalid_bounds_never_change_roi(window, bounds):
    before = window.rectangles()
    with pytest.raises(ValueError):
        window.apply_roi_bounds(0, bounds)
    assert window.rectangles() == before


def test_edit_dialog_selects_b_and_bounds_four_integer_spinners(window, monkeypatch):
    window.edit_roi_bounds()
    dialog = window._roi_bounds_dialog
    target = dialog.findChild(W.QComboBox, 'roi_bounds_target')
    assert target.count() == 2
    target.setCurrentIndex(1)
    controls = {name: dialog.findChild(W.QSpinBox, 'roi_bound_' + name) for name in ('x0', 'y0', 'x1', 'y1')}
    assert controls['x0'].maximum() == 15 and controls['y0'].maximum() == 11
    assert controls['x1'].maximum() == 16 and controls['y1'].maximum() == 12
    for name, value in zip(controls, (0, 0, 4, 5)):
        controls[name].setValue(value)
    dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.StandardButton.Apply).click()
    assert window.rectangles()[1] == (0, 0, 4, 5)


def test_modeless_dialog_close_without_apply_preserves_rois(window, monkeypatch):
    before = window.rectangles()

    window.edit_roi_bounds()
    dialog = window._roi_bounds_dialog
    dialog.findChild(W.QSpinBox, 'roi_bound_x0').setValue(8)
    dialog.findChild(W.QSpinBox, 'roi_bound_x1').setValue(8)
    dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.StandardButton.Close).click()
    assert window.rectangles() == before
