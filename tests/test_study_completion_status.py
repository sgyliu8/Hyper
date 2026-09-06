"""Real queued Study operations report terminal state in both UI surfaces."""
import numpy as np
import pytest

from hyperlab.io import Cube, save_cube
from hyperlab.ui.study_dialog import StudyDialog
from hyperlab.ui.workbench import Workbench


@pytest.fixture
def current(qtbot, tmp_path):
    path = save_cube(Cube(np.arange(432, dtype=np.uint16).reshape(12,12,3),
        {'data_level':'raw_frame', 'data_source':'SYNTHETIC', 'units':'DN',
         'channel_labels':['R','G','B']}), tmp_path/'source.npy')
    window = Workbench(path=path); qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.cube is not None and not window.task_busy, timeout=5000)
    window.roi_timer.stop(); window.analyze_rois()
    qtbot.waitUntil(lambda: not window.task_busy, timeout=5000)
    assert window.roi_source is window.cube and window.roi_results
    dialog = StudyDialog(window); qtbot.addWidget(dialog)
    return window, dialog


def added(current, qtbot):
    window, dialog = current
    dialog.add_current()
    assert window.task_busy and dialog.busy
    qtbot.waitUntil(lambda: not window.task_busy, timeout=5000)
    assert len(dialog.study['observations']) == 1
    return window, dialog


def test_add_current_replaces_pinning_with_actual_completed_observation(current, qtbot):
    window, dialog = added(current, qtbot)
    assert dialog.study['observations'][0]['analysis_run']['status'] == 'COMPLETE'
    assert not dialog.busy
    assert 'Added original observation' in dialog.status.text()
    assert window.message.text() == 'Study · ' + dialog.status.text()


def test_saved_study_reports_actual_integrity_in_main_window(current, qtbot, tmp_path):
    window, dialog = added(current, qtbot)
    path = tmp_path/'completed-study.json'
    dialog.save_path(path)
    assert window.message.text().startswith('Saving Study')
    qtbot.waitUntil(lambda: not window.task_busy, timeout=5000)
    assert path.exists() and not dialog.dirty and dialog.receipt['status'] == 'MATCH'
    assert 'Saved completed-study.json' in dialog.status.text()
    assert window.message.text() == 'Study · ' + dialog.status.text()


def test_failed_duplicate_replaces_pinning_without_claiming_another_observation(current, qtbot):
    window, dialog = added(current, qtbot)
    dialog.add_current()
    qtbot.waitUntil(lambda: not window.task_busy, timeout=5000)
    assert len(dialog.study['observations']) == 1 and not dialog.busy
    assert dialog.status.text().startswith('ValueError:')
    assert window.message.text() == 'Study · ' + dialog.status.text()


def test_failed_save_preserves_existing_file_and_reports_failure(current, qtbot, tmp_path):
    window, dialog = added(current, qtbot)
    path = tmp_path/'unrelated.json'; original = b'{"unrelated": true}'
    path.write_bytes(original)
    dialog.save_path(path)
    qtbot.waitUntil(lambda: not window.task_busy, timeout=5000)
    assert path.read_bytes() == original and dialog.dirty and not dialog.busy
    assert dialog.status.text().startswith('ValueError:')
    assert window.message.text() == 'Study · ' + dialog.status.text()
