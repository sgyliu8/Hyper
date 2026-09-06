import json
from pathlib import Path
import shutil

import numpy as np
import pytest
from PySide6 import QtWidgets as W

from hyperlab.analysis import roi_statistics
from hyperlab.experiment_metadata import save_annotation, source_fingerprint
from hyperlab.io import Cube, load_cube, save_cube
from hyperlab.study import (add_observation, load_study, new_study, observation_from_cube,
    relocate_observation, save_study, study_summary, verify_study)
from hyperlab.ui.study_dialog import StudyDialog


def saved(tmp_path, name='source.npy', sequence=1, exposure=20000, black=False, mask=True):
    settings = {'PixelFormat': 'RGB8', 'ExposureTime': exposure, 'Gain': 0,
        'ExposureAuto': 'Off', 'GainAuto': 'Off', 'BalanceWhiteAuto': 'Off',
        'GammaEnable': False, 'Gamma': 1, 'LUTEnable': False, 'BlackLevel': 0, 'BlackLevelAuto': 'Off'}
    data = np.zeros((3, 4, 3), np.uint8) if black else np.arange(36, dtype=np.uint8).reshape(3, 4, 3)
    cube = Cube(data, {'data_level': 'raw_frame', 'units': 'DN', 'data_source': 'SYNTHETIC',
        'pixel_format': 'RGB8', 'channel_labels': ['R', 'G', 'B'], 'model': 'test-model',
        'serial': 'test-serial', 'session_id': 'test-session', 'stream_epoch': 2,
        'sequence': sequence, 'readback_settings': settings}, np.ones((3, 4), bool) if mask else None)
    return save_cube(cube, tmp_path / name)


def with_analysis(cube, **kwargs):
    result = roi_statistics(cube, (0, 0, 2, 3), policy='diagnostic')
    context = {'source_fingerprint': source_fingerprint(cube), 'names': ['Region A'],
        'summary': 'median', 'version': 4, 'annotation': kwargs.get('annotation')}
    return observation_from_cube(cube, roi_results=[result], roi_context=context, **kwargs)


@pytest.mark.parametrize('suffix', ['.npy', '.npz', '.hdr'])
def test_study_portable_bundle_all_assets_and_strict_original_identity(tmp_path, suffix):
    original = tmp_path / 'Original bundle'
    path = saved(original / 'sources', 'source' + suffix)
    with load_cube(path) as cube:
        annotation, annotation_path = save_annotation(original / 'annotations', cube,
            {'specimen_id': 'coupon A', 'temperature_value': 500, 'temperature_unit': 'degC',
             'temperature_meaning': 'owner_label', 'dwell_seconds': 60})
        observation = with_analysis(cube, annotation=annotation, annotation_path=annotation_path,
            links={'treatment_id': 'treatment A'}, comparison_level='within-session')
        study = add_observation(new_study('Local pilot'), observation)
    manifest = save_study(study, original / 'study.json')
    assert verify_study(study)['status'] == 'MATCH'
    serialized = json.loads(manifest.read_text(encoding='utf-8'))
    assert all(not Path(location).is_absolute() for location in serialized['observations'][0]['asset_locations'].values())
    moved = tmp_path / 'Moved 工作区 with spaces'
    shutil.copytree(original, moved)
    restored = load_study(moved / 'study.json')
    assert verify_study(restored)['status'] == 'MATCH'
    record = restored['observations'][0]
    assert record['source_fingerprint'] == observation['source_fingerprint']
    assert record['annotation']['annotation_id'] == annotation['annotation_id']
    assert all(Path(location).is_relative_to(moved) for location in record['asset_locations'].values())
    with load_cube(moved / 'sources' / path.name) as relocated_cube:
        assert source_fingerprint(relocated_cube) != record['source_fingerprint']
    summary = study_summary(restored)
    assert summary['observations'][0]['temperature_meaning'] == 'owner_label'
    assert summary['observations'][0]['dwell_seconds'] == 60
    assert summary['feature_columns'][0]['axis_kind'] == 'category'
    assert summary['feature_rows'][0]['cells'][0]['value'] == 13.5
    assert summary['independent_replicate_count'] is None


@pytest.mark.parametrize('role', ['data', 'sidecar', 'mask', 'annotation'])
def test_missing_or_modified_any_asset_never_falls_back(tmp_path, role):
    original = tmp_path / 'source bundle'
    path = saved(original)
    with load_cube(path) as cube:
        annotation, annotation_path = save_annotation(original / 'annotations', cube, {})
        observation = with_analysis(cube, annotation=annotation, annotation_path=annotation_path)
    study = add_observation(new_study('Integrity'), observation)
    save_study(study, original / 'study.json')
    moved = tmp_path / 'moved'
    shutil.copytree(original, moved)
    restored = load_study(moved / 'study.json')
    asset = next(item for item in observation['source_fingerprint']['source_files'] + observation['associated_assets']
                 if item['role'] == role)
    location = Path(restored['observations'][0]['asset_locations'][asset['path']])
    before = location.read_bytes()
    location.write_bytes(before + b'changed')
    assert verify_study(restored)['status'] == 'MISMATCH'
    location.unlink()
    assert verify_study(restored)['status'] == 'MISSING'
    assert Path(asset['path']).exists()  # The old copy is deliberately not a fallback.


def test_explicit_relocation_requires_every_asset_and_preserves_original_fingerprint(tmp_path):
    path = saved(tmp_path / 'original')
    with load_cube(path) as cube:
        observation = with_analysis(cube)
    study = add_observation(new_study('Relocate'), observation)
    moved = tmp_path / 'new 路径'
    shutil.copytree(path.parent, moved)
    locations = {original: str(moved / Path(original).name) for original in observation['asset_locations']}
    with pytest.raises(ValueError, match='every recorded asset'):
        relocate_observation(study, observation['observation_id'], dict(list(locations.items())[:1]))
    relocated = relocate_observation(study, observation['observation_id'], locations)
    assert verify_study(relocated)['status'] == 'MATCH'
    assert relocated['observations'][0]['content_sha256'] == observation['content_sha256']
    assert relocated['observations'][0]['relocations'][0]['status'] == 'ALL_ASSETS_MATCH'
    assert study['observations'][0]['relocations'] == []
    (moved / path.name).write_bytes(b'incorrect')
    with pytest.raises(ValueError, match='Relocation rejected'):
        relocate_observation(study, observation['observation_id'], locations)


def test_expected_absent_sidecar_is_not_optional_new_metadata(tmp_path):
    path = tmp_path / 'no sidecar.npy'
    np.save(path, np.ones((2, 3, 1)), allow_pickle=False)
    with load_cube(path, axis_order='HWK') as cube:
        observation = observation_from_cube(cube)
    study = add_observation(new_study('Absent sidecar'), observation)
    assert verify_study(study)['status'] == 'MATCH'
    path.with_suffix('.npy.json').write_text('{}', encoding='utf-8')
    assert verify_study(study)['status'] == 'MISMATCH'


def test_copied_capture_is_duplicate_but_two_identical_black_frames_are_observations(tmp_path):
    first = saved(tmp_path / 'first', black=True)
    second = saved(tmp_path / 'second', sequence=2, black=True)
    copy_dir = tmp_path / 'copied'
    shutil.copytree(first.parent, copy_dir)
    with load_cube(first) as cube:
        a = observation_from_cube(cube)
    study = add_observation(new_study('Duplicates'), a)
    with pytest.raises(ValueError, match='already an observation'):
        add_observation(study, a)
    with load_cube(copy_dir / first.name) as cube:
        copied = observation_from_cube(cube)
    assert copied['source_fingerprint']['source_id'] != a['source_fingerprint']['source_id']
    with pytest.raises(ValueError, match='already an observation'):
        add_observation(study, copied)
    with load_cube(second) as cube:
        b = observation_from_cube(cube)
    study = add_observation(study, b)
    summary = study_summary(study)
    assert summary['observation_count'] == 2
    assert summary['unknown_specimen_observations'] == 2
    assert summary['observations'][1]['same_array_observations'] == [a['observation_id']]
    assert summary['settings_check']['status'] == 'MATCH'
    assert summary['independent_replicate_count'] is None


def test_settings_mismatch_keeps_original_rows_without_pooling(tmp_path):
    paths = [saved(tmp_path, 'a.npy'), saved(tmp_path, 'b.npy', sequence=2, exposure=10000)]
    study = new_study('Mismatched settings')
    for path in paths:
        with load_cube(path) as cube:
            study = add_observation(study, with_analysis(cube))
    summary = study_summary(study)
    assert summary['settings_check']['status'] == 'MISMATCH'
    assert 'ExposureTime' in summary['settings_check']['mismatches']
    assert len(summary['feature_rows']) == 2
    assert summary['registration'] == 'NOT_VERIFIED'


def test_unpinned_stale_analysis_and_conflicting_annotations_rejected(tmp_path):
    path = saved(tmp_path)
    with load_cube(path) as cube:
        result = roi_statistics(cube, (0, 0, 2, 2))
        context = {'names': ['A'], 'summary': 'mean'}
        with pytest.raises(ValueError, match='unchanged original source'):
            observation_from_cube(cube, roi_results=[result], roi_context=context)
        context['source_fingerprint'] = source_fingerprint(cube)
        cube.metadata['notes'] = 'edited since the completed result'
        with pytest.raises(ValueError, match='unchanged original source'):
            observation_from_cube(cube, roi_results=[result], roi_context=context)
        annotation, _ = save_annotation(tmp_path / 'annotations', cube, {'specimen_id': 'one coupon'})
        with pytest.raises(ValueError, match='conflicts'):
            observation_from_cube(cube, annotation=annotation, links={'specimen_id': 'two coupons'})
    unsaved = Cube(np.ones((2, 3, 1)), {'data_level': 'raw_frame', 'units': 'DN'})
    with pytest.raises(ValueError, match='Save the source'):
        observation_from_cube(unsaved)


def test_study_save_cannot_overwrite_any_raw_or_unrelated_asset(tmp_path):
    path = saved(tmp_path)
    with load_cube(path) as cube:
        observation = observation_from_cube(cube)
    study = add_observation(new_study('Safe save'), observation)
    for asset in observation['asset_locations']:
        with pytest.raises(ValueError, match='cannot overwrite'):
            save_study(study, asset)
    other = tmp_path / 'other.json'
    other.write_text('{"important": "unrelated"}', encoding='utf-8')
    with pytest.raises(ValueError, match='unrelated'):
        save_study(study, other)
    manifest = save_study(study, tmp_path / 'study.json')
    save_study(study, manifest)
    altered = load_study(manifest)
    altered['observations'][0]['links']['specimen_id'] = 'invented specimen'
    with pytest.raises(ValueError, match='Observation content changed'):
        save_study(altered, manifest)


def test_stable_roi_revision_external_mask_and_exclusion_assets_are_bound(tmp_path):
    from hyperlab.analysis.regions import make_roi, mask_geometry
    path = saved(tmp_path)
    mask_path = tmp_path / 'selection mask.npy'
    exclusion_path = tmp_path / 'exclude mask.npy'
    np.save(mask_path, np.ones((3, 4), bool), allow_pickle=False)
    mask = np.zeros((3, 4), bool)
    mask[0, 0] = True
    np.save(exclusion_path, mask, allow_pickle=False)
    roi = make_roi((3, 4), mask_geometry(mask_path, (3, 4)), name='Coating', roi_id='roi-A', revision=3)
    exclude = make_roi((3, 4), mask_geometry(exclusion_path, (3, 4)), role='exclude', roi_id='exclude-A')
    with load_cube(path) as cube:
        result = roi_statistics(cube, roi, exclusions=[exclude])
        context = {'source_fingerprint': source_fingerprint(cube), 'names': ['Coating'], 'summary': 'mean'}
        observation = observation_from_cube(cube, roi_results=[result], roi_context=context)
        run = observation['analysis_run']
        assert run['rois'][0]['roi_id'] == 'roi-A'
        assert run['rois'][0]['revision'] == 3
        assert len([asset for asset in observation['associated_assets'] if asset['role'] == 'roi_mask']) == 2
        assert run['features'][0]['used'] == 11
        np.save(exclusion_path, np.zeros((3, 4), bool), allow_pickle=False)
        assert source_fingerprint(cube) == context['source_fingerprint']
        with pytest.raises(ValueError, match='ROI mask asset'):
            observation_from_cube(cube, roi_results=[result], roi_context=context)
    study = add_observation(new_study('Geometry assets'), observation)
    assert verify_study(study)['status'] == 'MISMATCH'


class WorkbenchStub(W.QWidget):
    def __init__(self, tmp_path):
        super().__init__()
        self.workspace, self.task_busy, self.closing = tmp_path, False, False
        self.cube = self.annotation = self.annotation_path = None
        self.roi_source = self.roi_result_context = self.science_result = None
        self.roi_results = []
        self.jobs = 0
    def background(self, function, callback, label):
        self.jobs += 1
        callback(function())


def test_study_dialog_import_save_open_duplicates_and_unknown_analysis(qtbot, tmp_path):
    paths = [saved(tmp_path, 'a.npy'), saved(tmp_path, 'b.npy', sequence=2)]
    workbench = WorkbenchStub(tmp_path)
    qtbot.addWidget(workbench)
    dialog = StudyDialog(workbench)
    qtbot.addWidget(dialog)
    dialog.add_paths([str(path) for path in paths] + [str(paths[0])])
    assert dialog.table.rowCount() == 2
    assert 'Added 2/3' in dialog.status.text()
    assert all(observation['analysis_run'] is None for observation in dialog.study['observations'])
    manifest = tmp_path / 'Study 中文.json'
    dialog.save_path(manifest)
    assert manifest.exists() and not dialog.dirty
    dialog.new()
    dialog.open_path(manifest)
    assert dialog.table.rowCount() == 2
    assert dialog.receipt['status'] == 'MATCH'
    assert workbench.jobs == 3
    assert dialog.heatmap.rowCount() == 0
    assert 'Independent replicate count unknown' in dialog.facts.text()


def test_study_dialog_current_uses_completed_result_and_never_hidden_link_fields(qtbot, tmp_path):
    path = saved(tmp_path)
    workbench = WorkbenchStub(tmp_path)
    qtbot.addWidget(workbench)
    with load_cube(path) as cube:
        workbench.cube = workbench.roi_source = cube
        workbench.roi_results = [roi_statistics(cube, (0, 0, 2, 3))]
        workbench.roi_result_context = {'source_fingerprint': source_fingerprint(cube),
                                      'names': ['A'], 'summary': 'mean', 'version': 7}
        dialog = StudyDialog(workbench)
        qtbot.addWidget(dialog)
        dialog.treatment.setText('Hidden stale field')
        dialog.add_current()
        assert dialog.table.rowCount() == dialog.heatmap.rowCount() == 1
        assert dialog.heatmap.columnCount() == 3
        observation = dialog.study['observations'][0]
        assert observation['links']['treatment_id'] is None
        assert observation['analysis_run']['status'] == 'COMPLETE'
        assert observation['analysis_run']['recipe']['version'] == 7
        assert observation['analysis_run']['rois'][0]['roi_id'] is None
        dialog.table.selectRow(0)
        assert 'source_fingerprint' in dialog.details.toPlainText()
