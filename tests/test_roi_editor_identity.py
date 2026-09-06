"""Modeless ROI edits retain stable targets across independent row changes."""
from copy import deepcopy
import numpy as np
import pytest
from PySide6 import QtWidgets as W

from hyperlab.io import Cube
from hyperlab.ui.workbench import Workbench


@pytest.fixture
def editor(qtbot):
    window = Workbench(); qtbot.addWidget(window)
    window.set_cube(Cube(np.arange(144.).reshape(12,12,1),
        {'data_level':'raw_frame','data_source':'SYNTHETIC'}))
    window.apply_roi_bounds(0,(0,0,2,2)); window.apply_roi_bounds(1,(3,3,6,6))
    window.add_roi('ROI C',(8,8,11,11)); window.roi_timer.stop()
    window.edit_roi_bounds()
    dialog = window._roi_bounds_dialog
    target = dialog.findChild(W.QComboBox,'roi_bounds_target'); target.setCurrentIndex(1)
    return window, dialog, target


def apply_bounds(dialog, bounds):
    for name,value in zip(('x0','y0','x1','y1'), bounds):
        dialog.findChild(W.QSpinBox,'roi_bound_'+name).setValue(value)
    dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.StandardButton.Apply).click()


def test_removing_preceding_row_applies_draft_to_original_id_and_preserves_other_roi(editor):
    window, dialog, target = editor
    records = window.regions()
    chosen = records[1]['roi_id']; other = deepcopy(records[2])
    assert target.currentData() == chosen
    window.remove_roi(0)
    apply_bounds(dialog,(2,3,7,8))
    actual = {record['roi_id']:record for record in window.regions()}
    assert actual[chosen]['geometry']['bounds'] == [2.,3.,7.,8.]
    assert actual[other['roi_id']] == other
    assert target.currentData() == chosen and target.currentIndex() == 0
    assert target.currentText() == actual[chosen]['name']


def test_removed_target_rejects_apply_and_move_without_touching_surviving_rois(editor):
    window, dialog, target = editor
    chosen = target.currentData()
    window.remove_roi(1)
    before = deepcopy(window.regions())
    apply_bounds(dialog,(2,3,7,8))
    message = dialog.findChild(W.QLabel,'roi_bounds_message')
    assert 'selected ROI no longer exists' in message.text()
    assert window.regions() == before and chosen not in [item['roi_id'] for item in before]
    next(button for button in dialog.findChildren(W.QPushButton) if button.text() == 'Move up').click()
    assert 'selected ROI no longer exists' in message.text()
    assert window.regions() == before


def test_editor_move_follows_selected_id_after_external_reorder(editor):
    window, dialog, target = editor
    chosen = target.currentData()
    window.reorder_roi(1,2)
    next(button for button in dialog.findChildren(W.QPushButton) if button.text() == 'Move up').click()
    assert window.regions()[1]['roi_id'] == chosen
    assert target.currentData() == chosen and target.currentIndex() == 1


def test_source_shape_change_rejects_old_editor_coordinates(editor):
    window, dialog, _ = editor
    window.set_cube(Cube(np.ones((4,5,1)),{'data_level':'raw_frame','data_source':'SYNTHETIC'}))
    before = deepcopy(window.regions())
    apply_bounds(dialog,(0,0,2,2))
    assert 'Source dimensions changed' in dialog.findChild(W.QLabel,'roi_bounds_message').text()
    assert window.regions() == before
