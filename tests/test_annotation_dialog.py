"""Offline analyst-context UI checks; no camera or native desktop operations."""
import copy

import numpy as np
import pytest
from PySide6 import QtWidgets as W

from hyperlab.experiment_metadata import load_annotation, normalize_annotations, save_annotation
from hyperlab.io import Cube
from hyperlab.ui.annotation_dialog import AnnotationDialog


class FakeWorkbench(W.QWidget):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace
        self.cube = Cube(np.arange(36, dtype=np.uint16).reshape(3, 4, 3),
            {'data_level': 'raw_frame', 'data_source': 'SYNTHETIC',
             'channel_labels': ['R', 'G', 'B'], 'measurement_context': {'verified': False}})
        self.annotation = self.annotation_path = None
        self.task_busy = self.closing = False
        self.analysis_version = 0
        self.messages = []
        self.pending = None

    def notify(self, message):
        self.messages.append(message)

    def roi_changed(self):
        self.analysis_version += 1

    def background(self, function, callback, label):
        assert not self.task_busy
        self.task_busy = True
        self.pending = (function, callback)
        self.notify(label)

    def finish(self):
        function, callback = self.pending
        result = function()
        self.task_busy = False
        self.pending = None
        callback(result)


@pytest.fixture
def window(qtbot, tmp_path):
    workbench = FakeWorkbench(tmp_path)
    qtbot.addWidget(workbench)
    return workbench


def make_dialog(qtbot, workbench):
    dialog = AnnotationDialog(workbench)
    qtbot.addWidget(dialog)
    return dialog


def test_blank_dialog_retains_unknowns_without_default_temperature(window, qtbot):
    dialog = make_dialog(qtbot, window)
    assert dialog.values() == normalize_annotations({})
    assert not dialog.isModal()
    assert dialog.tabs.count() == 2
    assert dialog.sizeHint().height() < 750
    dialog.fields['temperature_value'].setText('0')
    dialog.fields['dwell_seconds'].setText('0')
    dialog.fields['temperature_unit'].setCurrentIndex(1)
    dialog.fields['temperature_meaning'].setCurrentIndex(3)
    values = dialog.values()
    assert values['temperature_value'] == values['dwell_seconds'] == 0
    assert values['temperature_meaning'] == 'owner_label'


def test_save_revisions_updates_context_once_without_acquisition_changes(window, qtbot):
    before = copy.deepcopy(window.cube.metadata)
    samples = window.cube.data.copy()
    dialog = make_dialog(qtbot, window)
    dialog.fields['specimen_id'].setText('  coupon A  ')
    dialog.fields['reference_ids'].setPlainText('source A\n\nsource B')
    dialog.save()
    assert dialog.busy and window.task_busy and not dialog.save_button.isEnabled()
    assert window.annotation is None
    window.finish()
    first, first_path = window.annotation, window.annotation_path
    first_bytes = first_path.read_bytes()
    assert first['values']['specimen_id'] == 'coupon A'
    assert first['values']['reference_ids'] == ['source A', 'source B']
    assert load_annotation(first_path, window.cube) == first
    assert window.analysis_version == 1
    dialog.fields['coating_batch'].setText('batch B')
    dialog.save()
    window.finish()
    assert window.annotation['revision'] == 2
    assert window.annotation['supersedes'] == first['annotation_id']
    assert first_path.read_bytes() == first_bytes
    assert window.annotation_path != first_path
    assert window.analysis_version == 2
    assert window.cube.metadata == before
    np.testing.assert_array_equal(window.cube.data, samples)
    assert dialog.save_button.isEnabled() and not dialog.busy


def test_existing_revision_prefills_fields_and_load_restores_exact_revision(window, qtbot):
    first, path = save_annotation(window.workspace / 'annotations', window.cube,
        {'specimen_id': 'A', 'temperature_value': 20, 'temperature_unit': 'degC',
         'temperature_meaning': 'independent_measurement', 'temperature_reference_id': 'log A',
         'notes': 'Known label only', 'reference_ids': ['log A', 'photo B']})
    window.annotation, window.annotation_path = first, path
    dialog = make_dialog(qtbot, window)
    assert dialog.values() == first['values']
    dialog.fields['specimen_id'].setText('unsaved change')
    dialog.load_revision(path)
    window.finish()
    assert window.annotation == first and window.annotation_path == path
    assert dialog.values() == first['values']
    assert window.analysis_version == 1
    assert len(list(path.parent.glob('*.json'))) == 1
    assert window.cube.metadata['measurement_context'] == {'verified': False}


@pytest.mark.parametrize('value', ['nan', '-1', 'not a number'])
def test_invalid_optional_numbers_are_visible_and_never_scheduled(window, qtbot, value):
    dialog = make_dialog(qtbot, window)
    dialog.fields['dwell_seconds'].setText(value)
    dialog.save()
    assert window.pending is None and not dialog.busy
    assert 'dwell_seconds' in dialog.status_label.text()
    assert window.annotation is None


def test_independent_temperature_requires_explicit_reference(window, qtbot):
    dialog = make_dialog(qtbot, window)
    dialog.fields['temperature_value'].setText('20')
    dialog.fields['temperature_unit'].setCurrentIndex(1)
    dialog.fields['temperature_meaning'].setCurrentIndex(2)
    dialog.save()
    assert window.pending is None
    assert 'requires a reference ID' in dialog.status_label.text()


@pytest.mark.parametrize('operation', ['save', 'load'])
def test_source_change_during_background_job_cannot_apply_revision(window, qtbot, operation):
    cube = window.cube
    dialog = make_dialog(qtbot, window)
    if operation == 'save':
        dialog.save()
    else:
        _, path = save_annotation(window.workspace / 'annotations', cube, {})
        dialog.load_revision(path)
    # Same geometry and samples still do not authorize applying to a new Cube.
    window.cube = Cube(cube.data.copy(), copy.deepcopy(cube.metadata))
    window.finish()
    assert window.annotation is None and window.annotation_path is None
    assert window.analysis_version == 0
    assert 'current data were not updated' in dialog.status_label.text()
    assert len(list((window.workspace / 'annotations').glob('*.json'))) == 1


def test_source_change_before_save_and_busy_workbench_do_not_schedule(window, qtbot):
    dialog = make_dialog(qtbot, window)
    window.task_busy = True
    dialog.save()
    assert window.pending is None
    assert 'Another operation' in dialog.status_label.text()
    window.task_busy = False
    window.cube = None
    dialog.save()
    assert window.pending is None
    assert 'Source changed' in dialog.status_label.text()


def test_wrong_source_revision_reports_error_without_changing_current_context(window, qtbot):
    other = Cube(window.cube.data + 1, copy.deepcopy(window.cube.metadata))
    _, path = save_annotation(window.workspace / 'annotations', other, {'specimen_id': 'other'})
    dialog = make_dialog(qtbot, window)
    dialog.load_revision(path)
    window.finish()
    assert window.annotation is None and window.analysis_version == 0
    assert 'source mismatch' in dialog.status_label.text()
    assert 'source mismatch' in window.messages[-1]
    assert dialog.load_button.isEnabled() and not dialog.busy


def test_background_write_error_keeps_form_available_and_visible(window, qtbot, monkeypatch):
    import hyperlab.ui.annotation_dialog as module
    def failure(*args, **kwargs):
        raise OSError('injected disk error')
    monkeypatch.setattr(module, 'save_annotation', failure)
    dialog = make_dialog(qtbot, window)
    dialog.fields['specimen_id'].setText('A')
    dialog.save()
    window.finish()
    assert 'OSError: injected disk error' in dialog.status_label.text()
    assert window.messages[-1] == dialog.status_label.text()
    assert dialog.fields['specimen_id'].text() == 'A'
    assert dialog.save_button.isEnabled() and dialog.tabs.isEnabled()
    assert window.annotation is None and window.analysis_version == 0


def test_closing_dialog_does_not_cancel_authorized_save_for_same_source(window, qtbot):
    dialog = make_dialog(qtbot, window)
    dialog.save()
    dialog.close()
    window.finish()
    assert window.annotation['revision'] == 1
    assert window.analysis_version == 1
