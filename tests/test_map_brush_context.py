"""Range brushing belongs to distributions; prior export receipts stay immutable."""
from copy import deepcopy
from threading import Event

import numpy as np
import pytest
from PySide6 import QtWidgets as W

from hyperlab.analysis.regions import make_roi
from hyperlab.io import Cube
from hyperlab.ui.workbench import Workbench


@pytest.fixture
def mapped(qtbot):
    window = Workbench(); qtbot.addWidget(window)
    window.set_cube(Cube(np.arange(432, dtype=float).reshape(12,12,3),
        {'data_level':'raw_frame', 'data_source':'SYNTHETIC', 'units':'DN', 'channel_labels':['R','G','B']}))
    window.roi_records[1] = make_roi((12,12),
        {'type':'strip', 'points':[[.5,10.5],[10.5,10.5]], 'width_px':.5}, name='Profile')
    window.rebuild_roi_graphics(); window.roi_changed(); window.roi_timer.stop()
    window.analyze('reference_rmse')
    qtbot.waitUntil(lambda: not window.task_busy, timeout=10000)
    assert window.map_distributions is not None, window.message.text()
    return window


@pytest.mark.parametrize('task,roi_index', [('profile',0),('profile',1),('residual',0),('shape',0)])
def test_non_distribution_task_hides_range_and_keeps_completed_receipt(mapped, qtbot, monkeypatch, task, roi_index):
    mapped.inspect_roi.setCurrentIndex(roi_index)
    mapped.brush_low.setValue(0); mapped.brush_high.setValue(1000)
    mapped.apply_map_brush()
    qtbot.waitUntil(lambda: not mapped.task_busy, timeout=10000)
    previous_spec = mapped.right_spec
    previous_brush = previous_spec.brushes[0]
    receipt = deepcopy(previous_brush['metadata'])
    mask = previous_brush['mask'].copy()
    assert 'Map range selection complete' in mapped.message.text()
    assert mapped.brush_low.isVisibleTo(mapped.map_tools)

    mapped.right_task.setCurrentIndex(mapped.right_task.findData(task))
    qtbot.waitUntil(lambda: not mapped.task_busy, timeout=10000)
    assert not mapped.brush_low.isVisibleTo(mapped.map_tools)
    assert not mapped.findChild(W.QPushButton, 'map_brush').isEnabled()
    assert mapped.map_brushes == []
    assert len(mapped.brush_overlay.points()) == 0
    assert 'No selected map range' in mapped.brush_note.text()
    assert previous_spec.brushes[0]['metadata'] == receipt
    np.testing.assert_array_equal(previous_spec.brushes[0]['mask'], mask)
    if task == 'profile' and roi_index == 1:
        assert 'Profile complete' in mapped.message.text()

    def unexpected(*args, **kwargs):
        pytest.fail('A non-distribution task started a range-brush computation')
    monkeypatch.setattr('hyperlab.analysis.distributions.brush_map', unexpected)
    mapped.apply_map_brush()
    assert not mapped.task_busy and mapped.map_brushes == []

    mapped.right_task.setCurrentIndex(mapped.right_task.findData('ecdf'))
    assert mapped.brush_low.isVisibleTo(mapped.map_tools)
    assert mapped.findChild(W.QPushButton, 'map_brush').isEnabled()
    assert mapped.right_spec.brushes == []


def test_old_brush_cannot_return_after_leaving_and_reentering_distribution(mapped, qtbot, monkeypatch):
    import hyperlab.analysis.distributions as distributions
    entered, release = Event(), Event()
    original = distributions.brush_map
    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(distributions, 'brush_map', paused)
    mapped.brush_low.setValue(0); mapped.brush_high.setValue(1000)
    mapped.apply_map_brush()
    qtbot.waitUntil(entered.is_set, timeout=3000)
    mapped.right_task.setCurrentIndex(mapped.right_task.findData('profile'))
    mapped.right_task.setCurrentIndex(mapped.right_task.findData('ecdf'))
    release.set()
    qtbot.waitUntil(lambda: not mapped.task_busy, timeout=10000)
    assert mapped.map_brushes == []
    assert len(mapped.brush_overlay.points()) == 0
    assert mapped.right_spec.brushes == []
    assert 'No selected map range' in mapped.brush_note.text()


def test_brushed_rectangle_profile_instruction_clears_axes_and_valid_plots_restore_them(mapped, qtbot):
    mapped.analyze('normalized_difference')
    qtbot.waitUntil(lambda: not mapped.task_busy, timeout=10000)
    mapped.inspect_roi.setCurrentIndex(0)
    mapped.brush_low.setValue(-1); mapped.brush_high.setValue(1)
    mapped.apply_map_brush()
    qtbot.waitUntil(lambda: not mapped.task_busy, timeout=10000)
    completed = mapped.right_spec
    labels = (completed.xlabel, completed.ylabel, completed.caption)
    selection = deepcopy(completed.brushes[0])
    assert selection['metadata']['counts']['selected'] > 0
    assert 'Map range selection complete' in mapped.message.text()
    assert mapped.shape_chart.getAxis('left').labelText == completed.ylabel

    def invalid_profile():
        mapped.inspect_roi.setCurrentIndex(0)
        mapped.right_task.setCurrentIndex(mapped.right_task.findData('profile'))
        assert mapped.right_spec is None and mapped.map_brushes == []
        assert mapped.message.text() == 'Select a line / strip ROI for a profile.'
        assert len(mapped.shape_chart.listDataItems()) == 0
        assert len(mapped.shape_chart.plotItem.legend.items) == 0
        for name in ('left','bottom'):
            assert mapped.shape_chart.getAxis(name).labelText == ''
            assert not mapped.shape_chart.getAxis(name).isVisible()
        assert mapped.shape_chart.toolTip() == 'Select a line / strip ROI for a profile.'

    invalid_profile()
    mapped.inspect_roi.setCurrentIndex(1)
    qtbot.waitUntil(lambda: not mapped.task_busy, timeout=10000)
    assert 'Profile complete' in mapped.message.text()
    for name, label in (('bottom',mapped.right_spec.xlabel),('left',mapped.right_spec.ylabel)):
        assert mapped.shape_chart.getAxis(name).isVisible()
        assert mapped.shape_chart.getAxis(name).labelText == label

    mapped.right_task.setCurrentIndex(mapped.right_task.findData('ecdf'))
    assert mapped.shape_chart.getAxis('left').labelText == mapped.right_spec.ylabel
    invalid_profile()
    mapped.shape_normalize.setChecked(True)
    mapped.roi_timer.stop(); mapped.analyze_rois()
    qtbot.waitUntil(lambda: not mapped.task_busy, timeout=10000)
    for name in ('left','bottom'):
        assert mapped.shape_chart.getAxis(name).isVisible()
        assert mapped.shape_chart.getAxis(name).labelText
    assert (completed.xlabel, completed.ylabel, completed.caption) == labels
    assert completed.brushes[0]['metadata'] == selection['metadata']
    np.testing.assert_array_equal(completed.brushes[0]['mask'], selection['mask'])
