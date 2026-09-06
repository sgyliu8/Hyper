"""Queued completion notices describe the actual pinned outcome, not a global PASS."""
from threading import Event

import numpy as np
import pytest
from PySide6 import QtWidgets as W

from hyperlab.acquisition.sequence import SequenceWriter
from hyperlab.io import Cube
from hyperlab.ui.workbench import Workbench


def source(sequence=1):
    return Cube(np.arange(144, dtype=np.uint16).reshape(12,12,1)+sequence,
        {'data_level':'raw_frame', 'data_source':'SYNTHETIC', 'acquisition_source':'SYNTHETIC',
         'synthetic':True, 'pixel_format':'BayerRG12', 'effective_bits':12, 'units':'DN',
         'shape':[12,12], 'valid':True, 'buffer_complete':True, 'session_id':'offline-status-fixture',
         'stream_epoch':1, 'sequence':sequence, 'host_utc':'2026-09-06T00:00:00+00:00'})


@pytest.fixture
def window(qtbot):
    result = Workbench(); qtbot.addWidget(result)
    result.set_cube(source()); result.roi_timer.stop()
    return result


def barrier(monkeypatch, module, name):
    entered, release = Event(), Event()
    original = getattr(module, name)
    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, name, paused)
    return entered, release


def idle(window, qtbot):
    qtbot.waitUntil(lambda: not window.task_busy, timeout=10000)
    window.roi_timer.stop()


@pytest.mark.parametrize('change_source', [False,True])
def test_quality_completion_keeps_receipt_scene_and_reference_separate(window, qtbot, monkeypatch, change_source):
    import hyperlab.acquisition.readiness as readiness
    entered, release = barrier(monkeypatch, readiness, 'measurement_readiness')
    window.quality_details(); qtbot.waitUntil(entered.is_set, timeout=3000)
    if change_source:
        window.set_cube(source(2))
    release.set(); idle(window, qtbot)
    report = window.last_readiness
    assert report['frame_received']['status'] == 'PASS'
    assert report['frame_received']['identity']['sequence'] == 1
    assert report['scene_usable_for_selected_task']['status'] == report['reference_qualified']['status'] == 'UNKNOWN'
    assert 'Quality inspection complete' in window.message.text()
    assert 'pinned frame receipt PASS' in window.message.text()
    assert 'scene UNKNOWN' in window.message.text() and 'reference UNKNOWN' in window.message.text()
    assert window.cube.metadata['sequence'] == (2 if change_source else 1)


@pytest.mark.parametrize('change_source', [False,True])
def test_recorded_trace_reports_completion_or_obsolete_source(window, qtbot, tmp_path, monkeypatch, change_source):
    import hyperlab.plots as plots
    directory = tmp_path/'recorded'
    with SequenceWriter(directory, (12,12), np.uint16, 3, metadata={'data_source':'SYNTHETIC'}) as writer:
        for index in range(3):
            writer.append(np.full((12,12), index+1, np.uint16),
                {'valid':True, 'session_id':'offline-sequence', 'stream_epoch':1, 'sequence':index,
                 'host_monotonic_ns':(index+1)*1_000_000_000, 'pixel_format':'Mono12', 'effective_bits':12})
    window.open_path(directory/'sequence.npy'); idle(window, qtbot)
    entered, release = barrier(monkeypatch, plots, 'recorded_roi_plot')
    window.plot_recorded_rois(); qtbot.waitUntil(entered.is_set, timeout=3000)
    if change_source:
        window.set_cube(source(8))
    release.set(); idle(window, qtbot)
    if change_source:
        assert 'obsolete curve discarded' in window.message.text()
        assert window.cube.metadata['sequence'] == 8
    else:
        assert len(window.plot_spec.series[0]['x']) == 3
        assert 'Recorded ROI trace complete' in window.message.text()
        assert '3 persisted frames' in window.message.text()


@pytest.mark.parametrize('change_source', [False,True])
def test_mask_import_reports_actual_source_outcome(window, qtbot, tmp_path, monkeypatch, change_source):
    import hyperlab.analysis.regions as regions
    path = tmp_path/'mask.npy'; np.save(path, np.eye(12, dtype=bool))
    original = path.read_bytes()
    monkeypatch.setattr(W.QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    entered, release = barrier(monkeypatch, regions, 'mask_geometry')
    count = len(window.rois)
    window.import_roi_mask(); qtbot.waitUntil(entered.is_set, timeout=3000)
    if change_source:
        window.set_cube(source(2))
    release.set(); idle(window, qtbot)
    assert path.read_bytes() == original
    assert len(window.rois) == count + (0 if change_source else 1)
    if change_source:
        assert 'Source changed' in window.message.text() and 'mask was not added' in window.message.text()
    else:
        assert window.regions()[-1]['geometry']['type'] == 'mask'
        assert 'Mask ROI imported' in window.message.text()


def test_mask_capacity_rejection_is_not_overwritten_by_success(window, qtbot, tmp_path, monkeypatch):
    while len(window.rois) < 8:
        window.add_roi()
    window.roi_timer.stop()
    path = tmp_path/'mask.npy'; np.save(path, np.eye(12, dtype=bool))
    monkeypatch.setattr(W.QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    window.import_roi_mask(); idle(window, qtbot)
    assert len(window.rois) == 8
    assert 'Up to eight ROI definitions' in window.message.text()


def test_all_hidden_roi_completion_preserves_numeric_results(window, qtbot):
    for checkbox in window.roi_visible:
        checkbox.setChecked(False)
    window.roi_timer.stop(); window.analyze_rois(); idle(window, qtbot)
    assert len(window.roi_results) == len(window.rois)
    assert all(np.all(result['count'] > 0) for result in window.roi_results)
    assert window.plot_spec.title == 'No visible ROI'
    assert 'ROI results ready' in window.message.text() and 'hidden' in window.message.text()


@pytest.mark.parametrize('change_source', [False,True])
def test_restored_annotation_reports_attach_or_source_rejection(window, qtbot, tmp_path, monkeypatch, change_source):
    import hyperlab.experiment_metadata as metadata
    from hyperlab.ui.state import restore_view
    record, path = metadata.save_annotation(tmp_path/'annotations', window.cube, {'specimen_id':'offline coupon'})
    entered, release = barrier(monkeypatch, metadata, 'load_annotation')
    window._pending_state = {'annotation_path':str(path)}
    restore_view(window); qtbot.waitUntil(entered.is_set, timeout=3000)
    if change_source:
        window.set_cube(source(2))
    release.set(); idle(window, qtbot)
    if change_source:
        assert window.annotation is None
        assert 'Source changed' in window.message.text() and 'not attached' in window.message.text()
    else:
        assert window.annotation == record and window.annotation_path == path
        assert 'Saved specimen context restored' in window.message.text()


@pytest.mark.parametrize('mismatch', [False,True])
def test_reference_check_reports_compatibility_without_claiming_calibration(window, qtbot, tmp_path, mismatch):
    import json
    from test_reference_dialog import saved_references, dialog_for, click_check
    paths = saved_references(tmp_path)
    if mismatch:
        path = paths['white'].with_suffix('.npy.json')
        metadata = json.loads(path.read_text())
        metadata['measurement_context']['geometry_id'] = 'different offline geometry'
        path.write_text(json.dumps(metadata), encoding='utf-8')
    dialog = dialog_for(window, qtbot, paths)
    click_check(dialog, qtbot)
    assert dialog.receipt['applicability']['status'] == ('MISMATCH' if mismatch else 'MATCH')
    assert window.message.text() == 'Reference check complete: ' + dialog.status.text()


def test_corrected_saved_output_reports_why_it_was_not_opened(window, qtbot, tmp_path, monkeypatch):
    import hyperlab.ui.reference_dialog as reference
    from test_reference_dialog import saved_references, dialog_for, click_check
    dialog = dialog_for(window, qtbot, saved_references(tmp_path))
    click_check(dialog, qtbot)
    original_cube = window.cube
    entered, release = barrier(monkeypatch, reference, 'reflectance')
    active = [False]
    monkeypatch.setattr(dialog, '_active_acquisition', lambda: active[0])
    dialog.run_correction(); qtbot.waitUntil(entered.is_set, timeout=3000)
    active[0] = True; release.set(); idle(window, qtbot)
    assert window.cube is original_cube
    assert len(list((window.workspace/'experiments').glob('reflectance_*/reflectance.npy'))) == 1
    assert 'Stop acquisition and reopen the result' in dialog.status.text()
    assert window.message.text() == 'Correction complete: ' + dialog.status.text()


def test_cancelled_profile_selection_reports_cancellation_without_connecting(window, qtbot, monkeypatch):
    report = {'profiles':[{'name':'Offline fixture A','serial':'fixture-a','cti':'offline.cti'},
                          {'name':'Offline fixture B','serial':'fixture-b','cti':'offline.cti'}], 'issues':[]}
    monkeypatch.setattr(W.QInputDialog, 'getItem', lambda *args: ('',False))
    monkeypatch.setattr(window, '_connect_profile', lambda *args: pytest.fail('Cancelled selection opened a device'))
    window.discovering = True
    window.background(lambda: report, window.choose_profile, 'Checking the current device and runtime…')
    idle(window, qtbot)
    assert window.session is None and not window.discovering
    assert window.message.text() == 'Device selection cancelled.'


@pytest.fixture
def mapped(window, qtbot):
    window.add_roi(kind='strip'); window.roi_timer.stop()
    window.analyze('reference_rmse'); idle(window, qtbot)
    assert window.map_distributions is not None, window.message.text()
    return window


def test_superseded_profile_reports_the_completed_current_distribution(mapped, qtbot, monkeypatch):
    import hyperlab.analysis.regions as regions
    mapped.inspect_roi.setCurrentIndex(mapped.inspect_roi.findData(mapped.roi_records[-1]['roi_id']))
    entered, release = barrier(monkeypatch, regions, 'strip_profile')
    mapped.right_task.setCurrentIndex(mapped.right_task.findData('profile'))
    qtbot.waitUntil(entered.is_set, timeout=3000)
    mapped.right_task.setCurrentIndex(mapped.right_task.findData('ecdf'))
    release.set(); idle(mapped, qtbot)
    assert mapped.right_task.currentData() == 'ecdf'
    assert mapped.message.text() == f'Right plot ready: {mapped.right_spec.title}'


def test_superseded_brush_reports_distribution_ready_without_reviving_selection(mapped, qtbot, monkeypatch):
    import hyperlab.analysis.distributions as distributions
    entered, release = barrier(monkeypatch, distributions, 'brush_map')
    mapped.brush_low.setValue(0); mapped.brush_high.setValue(1000)
    mapped.apply_map_brush(); qtbot.waitUntil(entered.is_set, timeout=3000)
    mapped.right_task.setCurrentIndex(mapped.right_task.findData('profile'))
    mapped.right_task.setCurrentIndex(mapped.right_task.findData('ecdf'))
    release.set(); idle(mapped, qtbot)
    assert mapped.map_brushes == [] and mapped.right_spec.brushes == []
    assert mapped.message.text() == f'Right plot ready: {mapped.right_spec.title}'


@pytest.mark.parametrize('transition', ['replay','start'])
def test_invalidated_map_clears_its_old_colour_count_caption(mapped, qtbot, tmp_path, transition):
    from hyperlab.io import save_cube
    completed = mapped.map_spec
    counts = dict(completed.metadata['display_limits'])
    assert 'valid pixels clipped' in mapped.map_limits_note.text()
    if transition == 'replay':
        path = save_cube(source(2), tmp_path/'new-source.npy')
        mapped.open_path(path); idle(mapped, qtbot)
    else:
        from test_roi_source_transition import EpochSession
        mapped.session = EpochSession(channels=1)
        mapped.start_preview(); mapped.tick()
    assert mapped.map_spec is None and mapped.product is None
    assert mapped.map_limits_note.text() == 'Colour limits: no map'
    assert completed.metadata['display_limits'] == counts
