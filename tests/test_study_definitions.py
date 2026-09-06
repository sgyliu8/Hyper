"""Completed Study estimators keep their actual support and original operands."""
from copy import deepcopy
import csv
import json

import numpy as np
import pytest

from hyperlab.acquisition.sequence import SequenceWriter, load_sequence
from hyperlab.analysis import roi_statistics
from hyperlab.analysis.regions import make_roi
from hyperlab.experiment_metadata import _digest, normalize_annotations, source_fingerprint
from hyperlab.io import Cube, load_cube, save_cube
from hyperlab.study import (add_observation, new_study, observation_from_cube,
                            measurement_comparison, study_summary, verify_study)
from hyperlab.ui.study_dialog import StudyDialog, export_study_points, study_point_plot
from test_technical_study import WorkbenchStub


def observation(tmp_path, sequence=1, *, data=None, bands=(0, 1), support='common',
                policy='diagnostic', metric='mean', metadata=None, rois=None,
                reference='reference', links=None, purpose=None, bands_by_roi=None):
    data = np.array([[[10, 1, 1], [100, 1, np.nan]]], dtype=float) if data is None else data
    shape = data.shape[:2]
    meta = {'data_level': 'raw_frame', 'units': 'DN', 'data_source': 'SYNTHETIC',
        'channel_labels': ['R', 'G', 'B'], 'session_id': 'fixture', 'stream_epoch': 1,
        'sequence': sequence, 'processing_steps': []}
    meta.update(metadata or {})
    path = save_cube(Cube(data, meta), tmp_path / f'source-{sequence}.npy')
    if rois is None:
        rois = [make_roi(shape, {'type': 'rectangle', 'bounds': [0, 0, shape[1], shape[0]]},
                        name='Region', roi_id='target', role='target')]
    with load_cube(path) as cube:
        results = [roi_statistics(cube, roi, bands=bands if bands_by_roi is None else bands_by_roi[i],
                    support=support, policy=policy) for i, roi in enumerate(rois)]
        context = {'source_fingerprint': source_fingerprint(cube), 'names': [roi['name'] for roi in rois],
            'summary': metric, 'roi_definitions': rois, 'reference_roi_id': reference}
        return observation_from_cube(cube, roi_results=results, roi_context=context,
                                     links=links, comparison_purpose=purpose)


def study_of(*observations):
    study = new_study('SYNTHETIC completed definition checks')
    for item in observations:
        study = add_observation(study, item)
    return study


def feature_columns(summary, feature=0):
    return [(i, col) for i, col in enumerate(summary['feature_columns']) if col['feature_index'] == feature]


def test_common_rg_vs_rgb_separates_55_from_10_with_visible_population(tmp_path):
    a = observation(tmp_path, bands=[0, 1])
    b = observation(tmp_path, 2, bands=[0, 1, 2])
    study = study_of(a, b)
    before = deepcopy(study)
    summary = study_summary(study)
    columns = feature_columns(summary)
    assert len(columns) == 2
    assert [col['support_label'] for _, col in columns] == ['common: 0 R, 1 G', 'common: 0 R, 1 G, 2 B']
    assert summary['feature_rows'][0]['cells'][columns[0][0]] == {'value': 55, 'used': 2, 'total': 2}
    assert summary['feature_rows'][1]['cells'][columns[1][0]] == {'value': 10, 'used': 1, 'total': 2}
    for column, _ in columns:
        spec = study_point_plot(study, column)
        assert spec.metadata['counts']['plotted_points'] == 1
        assert spec.metadata['counts']['omitted_by_reason'] == {'feature_unavailable': 1}
    assert study == before  # Deriving compatibility never upgrades old evidence in place.


@pytest.mark.parametrize('support,expected', [('common', 2), ('per_band', 1)])
def test_non_output_wavelength_changes_only_common_population(tmp_path, support, expected):
    items = [observation(tmp_path, i+1, support=support,
        metadata={'data_level': 'spectral_cube', 'channel_labels': None,
                  'wavelengths': wave, 'wavelength_units': 'nm'})
        for i, wave in enumerate(([500, 600, 700], [500, 610, 700]))]
    summary = study_summary(study_of(*items))
    assert len(feature_columns(summary)) == expected
    label = feature_columns(summary)[0][1]['support_label']
    assert '0 500 nm' in label
    assert ('1 600 nm' in label) == (support == 'common')


def test_canonical_actual_enabled_features_and_per_band_do_not_over_key(tmp_path):
    variants = [([0, 1], {}), ([1, 0], {}), ([0, 1, 2], {'band_validity': [True, True, False]})]
    summary = study_summary(study_of(*[observation(tmp_path, i+1, bands=bands, metadata=meta)
                                      for i, (bands, meta) in enumerate(variants)]))
    assert len(feature_columns(summary)) == 1
    per_band = study_summary(study_of(observation(tmp_path / 'per-band', bands=[0, 1], support='per_band'),
        observation(tmp_path / 'per-band', 2, bands=[0, 1, 2], support='per_band')))
    assert len(feature_columns(per_band)) == 1
    assert feature_columns(per_band)[0][1]['support_label'] == 'per_band: 0 R'


@pytest.mark.parametrize('policy,expected', [('quantitative', 2), ('diagnostic', 1)])
def test_saturation_threshold_definition_tracks_applied_policy(tmp_path, policy, expected):
    summary = study_summary(study_of(*[observation(tmp_path, i+1, policy=policy,
        metadata={'saturation_value': threshold}) for i, threshold in enumerate([50, 200])]))
    columns = feature_columns(summary)
    assert len(columns) == expected
    definitions = [summary['definition_contexts'][col['definition_id']] for _, col in columns]
    assert definitions[0]['quality']['saturation_value'] == (50 if policy == 'quantitative' else None)


@pytest.mark.parametrize('field,a,b', [
    ('data_ignore_value', -1, -2),
    ('processing_steps', [{'operation': 'subtract', 'value': 1}], [{'operation': 'subtract', 'value': 2}]),
    ('reference_source', 'reference-a', 'reference-b'),
    ('response_matrix_id', 'response-a', 'response-b'),
    ('low_signal_assessment', {'minimum': 2, 'units': 'DN'}, {'minimum': 3, 'units': 'DN'}),
])
def test_applied_estimator_rules_and_response_contexts_are_not_collapsed(tmp_path, field, a, b):
    summary = study_summary(study_of(observation(tmp_path, metadata={field: a}),
                                   observation(tmp_path, 2, metadata={field: b})))
    assert len(feature_columns(summary)) == 2


def test_raw_display_reference_and_roi_identity_do_not_split_amplitude_math(tmp_path):
    a = observation(tmp_path, reference='display-reference-a')
    roi = make_roi((1, 2), {'type': 'rectangle', 'bounds': [0, 0, 1, 1]},
                   name='Different position', roi_id='another-roi', revision=4)
    b = observation(tmp_path, 2, rois=[roi], reference='display-reference-b')
    summary = study_summary(study_of(a, b))
    assert len(feature_columns(summary)) == 1
    assert summary['feature_rows'][0]['cells'][0]['value'] == 55
    assert summary['feature_rows'][1]['cells'][0]['value'] == 10
    assert summary['feature_rows'][1]['roi']['revision'] == 4


def test_legacy_missing_common_population_remains_unknown_without_rewriting(tmp_path):
    legacy = observation(tmp_path)
    legacy.pop('comparison_purpose')  # Valid old schema content, with no new declaration inferred.
    run = legacy['analysis_run']
    run['roi_evidence'][0].pop('feature_indices')
    run['analysis_run_id'] = _digest({k: v for k, v in run.items() if k != 'analysis_run_id'})
    legacy['content_sha256'] = _digest({k: v for k, v in legacy.items()
        if k not in ('content_sha256', 'asset_locations', 'relocations')})
    study = study_of(legacy, observation(tmp_path, 2))
    before = deepcopy(study)
    summary = study_summary(study)
    assert len(feature_columns(summary)) == 2
    assert feature_columns(summary)[0][1]['definition_status'] == 'UNKNOWN'
    assert 'UNKNOWN feature population' in feature_columns(summary)[0][1]['support_label']
    assert study_point_plot(study, 0).metadata['counts']['plotted_points'] == 1
    assert study == before


def contrast_observation(tmp_path, sequence=1, *, metric='mean', reference='reference',
                         bands_by_roi=None, links=None, purpose=None):
    data = np.repeat(np.array([[[-5], [-1], [2], [4], [20]]], float), 3, axis=2)
    rois = [make_roi((1, 5), {'type': 'rectangle', 'bounds': bounds}, name=name,
                    roi_id=role, revision=2, role=role)
            for bounds, name, role in [([0, 0, 2, 1], 'Reference', 'reference'),
                                      ([2, 0, 5, 1], 'Target', 'target')]]
    return observation(tmp_path, sequence, data=data, metric=metric, rois=rois,
        reference=reference, bands_by_roi=bands_by_roi, links=links, purpose=purpose)


@pytest.mark.parametrize('metric,target,difference', [('mean', 26/3, 35/3), ('median', 4, 7)])
def test_signed_contrast_is_difference_of_summaries_with_exact_operands(tmp_path, metric, target, difference):
    study = study_of(contrast_observation(tmp_path, metric=metric))
    spec = study_point_plot(study, 0, view='contrast')
    reference, point = spec.metadata['points']
    assert reference['omitted_reason'] == 'reference_operand'
    assert reference['y'] is None and reference['original_y'] == -3
    assert point['original_y'] == pytest.approx(target)
    assert point['reference_value'] == -3 and point['y'] == pytest.approx(difference)
    assert (point['used'], point['total'], point['reference_used'], point['reference_total']) == (3, 3, 2, 2)
    assert point['roi_revision'] == point['reference_roi_revision'] == 2
    assert spec.metadata['aggregation'] == 'within_observation_summary_then_difference'
    assert spec.metadata['independent_replicate_count'] is None
    assert spec.metadata['definition']['quantile_method'] == ('linear' if metric == 'median' else None)
    assert all(series['style'] == 'none' and 'std' not in series for series in spec.series)
    assert 'no pixel pairing' in spec.caption


@pytest.mark.parametrize('reference,bands,reason', [
    (None, None, 'reference_missing_or_ambiguous'),
    ('reference', [[0, 1], [0, 1, 2]], 'reference_definition_or_value_unavailable'),
])
def test_unavailable_or_incompatible_reference_retains_original_points(tmp_path, reference, bands, reason):
    study = study_of(contrast_observation(tmp_path, reference=reference, bands_by_roi=bands))
    summary = study_summary(study)
    target_column = max(index for index, _ in feature_columns(summary))
    spec = study_point_plot(study, target_column, view='contrast')
    assert spec.metadata['points'][1]['omitted_reason'] == reason
    assert spec.metadata['points'][1]['y'] is None
    assert spec.metadata['counts']['plotted_points'] == 0
    originals = study_point_plot(study, target_column)
    assert originals.metadata['points'][1]['included']


def test_unknown_specimens_and_explicit_purpose_do_not_invent_replication(tmp_path):
    study = study_of(contrast_observation(tmp_path, purpose='nuisance-control'),
                     contrast_observation(tmp_path, 2, purpose='target-change'))
    spec = study_point_plot(study, 0, view='contrast', group_by='specimen')
    assert len(spec.series) == 2
    assert spec.series[0]['name'].startswith('Unknown specimen · Obs 1')
    assert spec.series[1]['name'].startswith('Unknown specimen · Obs 2')
    assert spec.metadata['declared_specimen_count'] == 0
    assert spec.metadata['unknown_specimen_observations'] == 2
    assert spec.metadata['independent_replicate_count'] is None
    assert [s['points'][0]['comparison_purpose'] for s in spec.series] == ['nuisance-control', 'target-change']
    assert spec.metadata['comparison_evidence']['status'] == 'UNKNOWN'
    assert all(s['name'].endswith(' · UNKNOWN') and s['comparison_evidence']['observation_count'] == 1
               for s in spec.series)
    assert 'No cross-observation' in spec.metadata['pairing']


def test_source_settings_mismatch_stays_visible_with_original_definition(tmp_path):
    metadata = {'readback_settings': {'ExposureTime': 20000}}
    a = observation(tmp_path, metadata=metadata)
    b = observation(tmp_path, 2, metadata={'readback_settings': {'ExposureTime': 40000}})
    summary = study_summary(study_of(a, b))
    assert len(feature_columns(summary)) == 1
    assert summary['comparison_evidence']['status'] == 'MISMATCH'
    assert 'acquisition_settings' in summary['comparison_evidence']['mismatches']
    spec = study_point_plot(study_of(a, b), 0)
    assert spec.metadata['counts']['plotted_points'] == 2
    assert 'measurement compatibility MISMATCH' in spec.caption
    assert spec.series[0]['name'].endswith(' · MISMATCH')
    assert all(point['measurement_compatibility'] == 'MISMATCH' for point in spec.metadata['points'])
    separate = study_point_plot(study_of(a, b), 0, group_by='specimen')
    assert all(s['comparison_evidence']['status'] == 'UNKNOWN' for s in separate.series)
    assert separate.metadata['comparison_evidence']['status'] == 'MISMATCH'


@pytest.mark.parametrize('calibrations,status,unknown,mismatch', [
    (['response-A', 'response-B'], 'MISMATCH', False, True),
    (['response-A', 'response-A'], 'MATCH', False, False),
    (['UNKNOWN', 'UNKNOWN'], 'UNKNOWN', True, False),
    ([' Unavailable ', 'not_tested'], 'UNKNOWN', True, False),
    ([None, 'response-A'], 'UNKNOWN', True, False),
    (['UNKNOWN', 'response-A', 'response-B'], 'MISMATCH', True, True),
])
def test_declared_response_identity_and_unknown_are_not_truthiness(calibrations, status, unknown, mismatch):
    observations = [{'source_metadata': {'shape': [1, 2, 3], 'model': 'fixture', 'serial': 'fixture',
        'pixel_format': 'RGB8', 'calibration_source': calibration, 'readback_settings': {
            'PixelFormat': 'RGB8', 'ExposureTime': 20000, 'Gain': 0, 'ExposureAuto': 'Off',
            'GainAuto': 'Off', 'BalanceWhiteAuto': 'Off', 'GammaEnable': False, 'Gamma': 1,
            'LUTEnable': False, 'BlackLevel': 0, 'BlackLevelAuto': 'Off'}},
        'annotation': {'values': normalize_annotations({'illumination_id': 'fixture-light',
                                                      'geometry_id': 'fixture-geometry'})}}
        for calibration in calibrations]
    before = deepcopy(observations)
    result = measurement_comparison(observations)
    assert result['status'] == status
    assert ('response_calibration' in result['unknown']) == unknown
    assert ('response_calibration' in result['mismatches']) == mismatch
    assert result['settings']['status'] == 'MATCH'
    assert result['physical_qualification'] == 'NOT_ASSESSED'
    assert observations == before


def test_nonfinite_contrast_is_unavailable_and_finite_operands_remain_exact(tmp_path):
    data = np.repeat(np.array([[[-1e308], [1e308]]]), 3, axis=2)
    rois = [make_roi((1, 2), {'type': 'rectangle', 'bounds': [i, 0, i+1, 1]},
                    name=role, roi_id=role, role=role) for i, role in enumerate(['reference', 'target'])]
    study = study_of(observation(tmp_path, data=data, rois=rois, metric='median'))
    spec = study_point_plot(study, 0, view='contrast')
    target = spec.metadata['points'][1]
    assert target['omitted_reason'] == 'nonfinite_contrast' and target['y'] is None
    assert target['original_y'] == 1e308 and target['reference_value'] == -1e308
    assert spec.metadata['counts']['plotted_points'] == 0
    json.dumps(spec.metadata, allow_nan=False)


def test_later_sequence_prefix_growth_invalidates_existing_snapshot_and_not_counts(tmp_path):
    writer = SequenceWriter(tmp_path / 'partial', (1, 2, 3), np.float64, 2, checkpoint_frames=1)
    record = {'valid': True, 'session_id': 'temporal-fixture', 'stream_epoch': 1,
        'sequence': 1, 'frame_id': 1, 'acquisition_source': 'SYNTHETIC', 'data_source': 'SYNTHETIC',
        'channel_labels': ['R', 'G', 'B'], 'host_monotonic_ns': 1000}
    try:
        writer.append(np.ones((1, 2, 3)), record)
        with load_sequence(writer.path) as sequence:
            assert sequence.frame_count == 1
            frame = sequence.frame(0)
        cube = Cube(frame.data, dict(frame.metadata, source_file=str(writer.path)))
        result = roi_statistics(cube, (0, 0, 2, 1), bands=[0, 1], support='common')
        context = {'source_fingerprint': source_fingerprint(cube), 'summary': 'mean'}
        study = study_of(observation_from_cube(cube, roi_results=[result], roi_context=context))
        before = deepcopy(study_summary(study)['feature_rows'])
        spec = study_point_plot(study, 0)
        assert verify_study(study)['status'] == 'MATCH'
        writer.append(np.full((1, 2, 3), 9.0), dict(record, sequence=2, frame_id=2, host_monotonic_ns=2000))
        writer.finish()
        assert verify_study(study)['status'] == 'MISMATCH'
        assert study_summary(study)['feature_rows'] == before
        assert before[0]['cells'][0] == {'value': 1, 'used': 2, 'total': 2}
        with pytest.raises(ValueError, match='every declared'):
            export_study_points(study, spec, tmp_path / 'refused', dpi=72)
        assert not (tmp_path / 'refused').exists()
    finally:
        if not writer.closed:
            writer.finish(stopped=True)


def test_contrast_ui_and_export_preserve_definition_originals_and_denominators(tmp_path, qapp):
    study = study_of(contrast_observation(tmp_path, metric='median'))
    parent = WorkbenchStub(tmp_path)
    dialog = StudyDialog(parent)
    try:
        dialog.study = study
        dialog.refresh()
        assert 'common: 0 R, 1 G' in dialog.point_feature.itemText(0)
        dialog.point_view.setCurrentIndex(dialog.point_view.findData('contrast'))
        dialog.point_group.setCurrentIndex(dialog.point_group.findData('specimen'))
        assert dialog.points_spec.metadata['counts']['plotted_points'] == 1
        assert dialog.points_spec.series[0]['y'] == [7]
        assert 'Unknown specimen · Obs 1' in dialog.points_spec.series[0]['name']
        output = export_study_points(study, dialog.points_spec, tmp_path / 'contrast', dpi=72)
        rows = list(csv.DictReader((output / 'points.csv').open(encoding='utf-8')))
        assert len(rows) == 2 and rows[0]['included'] == 'False'
        point = rows[1]
        assert float(point['y']) == 7 and float(point['original_y']) == 4 and float(point['reference_value']) == -3
        assert (point['used'], point['reference_used'], point['total'], point['reference_total']) == ('3', '2', '3', '2')
        assert point['definition_status'] == 'KNOWN' and point['definition_id']
        plot = json.loads((output / 'plot.json').read_text(encoding='utf-8'))
        assert plot['metadata']['definition']['support_features'][1]['label'] == 'G'
        assert plot['metadata']['study'] == study
        assert verify_study(study)['status'] == 'MATCH'
    finally:
        dialog.close()
        parent.close()
