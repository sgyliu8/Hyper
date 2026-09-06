"""Measurement semantics: numerical ratios are separate from evidence quality."""
from copy import deepcopy
import json

import numpy as np
import pytest

from hyperlab.acquisition.frame import Frame
from hyperlab.analysis.maps import normalized_difference
from hyperlab.io import Cube, load_cube


def contrast_cube(values, **metadata):
    return Cube(np.asarray(values, np.float64).reshape(1, -1, 2),
                {'data_level': 'raw_scan', 'units': 'DN', 'synthetic': True, **metadata})


def test_nd_unknown_low_signal_preserves_weak_bright_and_signed_values():
    cube = contrast_cube([[1, 1], [2, 1], [100, 100], [101, 100], [2, -1], [0, 0]])
    original = cube.data.copy()
    result = normalized_difference(cube, 0, 1)
    np.testing.assert_allclose(result['data'][0, :5], [0, 1/3, 0, 1/201, 3])
    assert np.isnan(result['data'][0, 5])
    assert result['metadata']['low_signal_assessment']['status'] == 'UNKNOWN'
    assert result['metadata']['reason_counts']['low_signal'] is None
    assert 'low_signal' not in result['reason_masks']
    assert result['metadata']['saturation_assessment'] == 'UNKNOWN'
    assert result['metadata']['reason_counts']['source_saturated'] is None
    assert 'source_saturated' not in result['reason_masks']
    np.testing.assert_equal(result['numerical_denominator_valid_mask'], [[True]*5 + [False]])
    np.testing.assert_equal(original, cube.data)
    json.dumps(result['metadata'], allow_nan=False)


def test_nd_explicit_amplitude_policy_is_not_denominator_cancellation():
    cube = contrast_cube([[1, 1], [2, 1], [100, 100], [101, 100], [2, -1], [100, -100]])
    result = normalized_difference(cube, 0, 1, low_signal_threshold=3,
                                   low_signal_source='Analyst diagnostic fixture')
    np.testing.assert_equal(result['valid_mask'], [[False, True, True, True, True, False]])
    assert result['data'][0, 4] == 3
    assessment = result['metadata']['low_signal_assessment']
    assert assessment['status'] == 'DIAGNOSTIC_THRESHOLD'
    assert assessment['units'] == 'DN' and assessment['feature_indices'] == [0, 1]
    assert assessment['expression'] == 'abs(a) + abs(b)'
    assert assessment['exclusion_rule'] == 'abs(a) + abs(b) < threshold'
    assert assessment['source'] == 'Analyst diagnostic fixture'
    assert result['metadata']['reason_counts']['low_signal'] == 1
    assert result['metadata']['reason_counts']['low_denominator'] == 1
    assert result['metadata']['reason_counts']['used'] == 4


@pytest.mark.parametrize('threshold,source,units', [
    (0, 'Analyst', 'DN'), (-1, 'Analyst', 'DN'), (np.inf, 'Analyst', 'DN'),
    (True, 'Analyst', 'DN'), (3, None, 'DN'), (3, 'unknown', 'DN'), (3, 'Analyst', 'unknown')])
def test_nd_threshold_requires_explicit_known_diagnostic_evidence(threshold, source, units):
    cube = contrast_cube([[1, 2]], units=units)
    with pytest.raises(ValueError):
        normalized_difference(cube, 0, 1, low_signal_threshold=threshold, low_signal_source=source)


def test_nd_reason_partition_and_overlapping_source_causes():
    cube = contrast_cube([[np.nan, 2], [-99, 2], [255, 1], [0, 0], [1, 1], [10, 10]],
                         saturation_value=255, data_ignore_value=-99)
    result = normalized_difference(cube, 0, 1, policy='quantitative',
                                   low_signal_threshold=3, low_signal_source='Analyst diagnostic fixture')
    counts = result['metadata']['reason_counts']
    assert {key: counts[key] for key in ('source_invalid', 'source_ignored', 'source_saturated')} == {
        'source_invalid': 1, 'source_ignored': 1, 'source_saturated': 1}
    assert counts['total'] == 6 and counts['source_excluded'] == 3
    assert counts['total'] == sum(counts[key] for key in
        ('source_excluded', 'low_denominator', 'nonfinite_calculation', 'low_signal', 'used'))
    assert result['reason_masks']['low_signal'][0, 4]
    assert result['valid_mask'][0, 5] and np.count_nonzero(result['valid_mask']) == 1


def test_nd_numerical_overflow_is_invalid_not_zero_contrast():
    result = normalized_difference(contrast_cube([[1e308, 1e308], [1e308, -1e308 + 1e292]]), 0, 1)
    assert not np.any(result['valid_mask'])
    assert np.all(np.isnan(result['data']))
    assert result['metadata']['reason_counts']['nonfinite_calculation'] == 2


def test_nd_export_keeps_exact_policy_mask_and_signed_values(tmp_path):
    from hyperlab.analysis.products import export_product
    cube = contrast_cube([[1, 1], [2, -1], [0, 0]])
    result = normalized_difference(cube, 0, 1, low_signal_threshold=3,
                                   low_signal_source='Analyst diagnostic fixture')
    path = export_product(result, tmp_path/'contrast.npy', source_cube=cube)
    reopened = load_cube(path)
    try:
        np.testing.assert_equal(reopened.data[:, :, 0], result['data'])
        np.testing.assert_equal(reopened.valid_mask, result['valid_mask'])
        assert reopened.metadata['low_signal_assessment'] == result['metadata']['low_signal_assessment']
        assert reopened.metadata['reason_counts'] == result['metadata']['reason_counts']
    finally:
        reopened.close()


def raw_frame(values=None, **metadata):
    data = np.array([[0, 4], [8, 4095]], np.uint16) if values is None else np.asarray(values, np.uint16)
    return Frame(data, {'data_level': 'raw_frame', 'units': 'DN', 'pixel_format': 'BayerRG12',
        'effective_bits': 12, 'buffer_complete': True, 'valid': True,
        'session_id': 'synthetic readiness fixture', 'stream_epoch': 1, 'sequence': 2,
        'host_utc': '2026-09-06T00:00:00+00:00', 'shape': list(data.shape),
        'synthetic': True, 'acquisition_source': 'SYNTHETIC', **metadata})


def test_readiness_has_exact_counts_without_physical_cause_or_reference():
    from hyperlab.acquisition.readiness import measurement_readiness
    frame = raw_frame()
    metadata_before = deepcopy(dict(frame.metadata))
    result = measurement_readiness(frame)
    assert result['frame_received']['status'] == 'PASS'
    assert result['frame_received']['origin'] == 'SYNTHETIC'
    assert result['scene_usable_for_selected_task']['status'] == 'UNKNOWN'
    assert result['reference_qualified']['status'] == 'UNKNOWN'
    feature = result['signal']['per_feature'][0]
    assert feature['counts'] == {'total': 4, 'used': 3, 'invalid': 0, 'ignored': 0,
                                 'saturated': 1, 'zero_used': 1}
    np.testing.assert_allclose(feature['quantiles'], [0, .08, 4, 7.92, 8])
    assert feature['mean'] == 4 and result['signal']['exact'] is True
    assert dict(frame.metadata) == metadata_before and not frame.data.flags.writeable
    assert result['signal']['sample_units'] == 'DN'
    json.dumps(result, allow_nan=False)


def test_readiness_black_is_unknown_and_remains_saveable(tmp_path):
    from hyperlab.acquisition.frame import save_frame
    from hyperlab.acquisition.readiness import measurement_readiness
    frame = raw_frame(np.zeros((2, 2), np.uint16))
    result = measurement_readiness(frame)
    assert result['frame_received']['status'] == 'PASS'
    assert result['scene_usable_for_selected_task']['status'] == 'UNKNOWN'
    assert result['signal']['per_feature'][0]['quantiles'] == [0.]*5
    assert result['signal']['per_feature'][0]['counts']['zero_used'] == 4
    assert 'light_blocked' not in frame.metadata and 'measurement_context' not in frame.metadata
    assert save_frame(tmp_path/'black', frame).is_file()


def test_readiness_explicit_scene_is_task_bound_and_not_calibration():
    from hyperlab.acquisition.readiness import measurement_readiness
    evidence = {'status': 'PASS', 'task': 'coating contrast',
                'source': 'Analyst synthetic review', 'reason': 'Known fixture response'}
    result = measurement_readiness(raw_frame(), selected_task='coating contrast', scene_evidence=evidence)
    assert result['scene_usable_for_selected_task']['status'] == 'PASS'
    assert result['reference_qualified']['status'] == 'UNKNOWN'
    with pytest.raises(ValueError, match='task'):
        measurement_readiness(raw_frame(), selected_task='temperature inference', scene_evidence=evidence)
    with pytest.raises(ValueError, match='task'):
        measurement_readiness(raw_frame(), scene_evidence={key: value for key, value in evidence.items() if key != 'task'})
    with pytest.raises(ValueError, match='source'):
        measurement_readiness(raw_frame(), scene_evidence={'status': 'PASS'})
    with pytest.raises(ValueError, match='task'):
        measurement_readiness(raw_frame(), scene_evidence={'status': 'UNKNOWN', 'task': 'unrelated task'})
    assert measurement_readiness(None, selected_task='coating contrast', scene_evidence=evidence)[
        'scene_usable_for_selected_task']['status'] == 'UNKNOWN'


def test_readiness_no_source_missing_receipt_all_invalid_and_unknown_saturation():
    from hyperlab.acquisition.readiness import measurement_readiness
    absent = measurement_readiness(None)
    assert absent['frame_received']['status'] == 'UNKNOWN' and absent['signal'] is None
    incomplete = measurement_readiness(raw_frame(buffer_complete=False))
    assert incomplete['frame_received']['status'] == 'FAIL'
    cube = Cube(np.full((1, 2, 1), np.nan), {'data_level': 'raw_frame', 'units': 'DN'})
    result = measurement_readiness(cube)
    assert result['frame_received']['status'] == 'UNKNOWN'
    assert result['scene_usable_for_selected_task']['status'] == 'FAIL'
    assert result['signal']['per_feature'][0]['counts']['saturated'] is None
    assert result['signal']['per_feature'][0]['quantiles'] == [None]*5
    json.dumps(result, allow_nan=False)


def test_readiness_does_not_pass_incomplete_identity_or_inconsistent_geometry():
    from hyperlab.acquisition.readiness import measurement_readiness
    for values in ({'session_id': 'unknown'}, {'host_utc': ''}, {'sequence': None}, {'pixel_format': 'unknown'}):
        assert measurement_readiness(raw_frame(**values))['frame_received']['status'] == 'UNKNOWN'
    result = measurement_readiness(raw_frame(shape=[99, 99]))
    assert result['frame_received']['status'] == 'FAIL'
    assert result['frame_received']['declared_shape_matches'] is False


def test_readiness_reference_uses_detailed_existing_checker_and_retains_evidence():
    from hyperlab.acquisition.readiness import measurement_readiness
    from hyperlab.analysis.applicability import reference_applicability
    inputs = []
    for role in ('sample', 'white', 'dark', 'dark'):
        context = {'instrument_id': 'synthetic', 'response_calibration_id': 'synthetic',
            'temperature_condition_id': 'synthetic', 'role': role,
            'evidence_kind': 'declared', 'evidence_source': 'synthetic readiness fixture'}
        context.update({'dark_method': 'synthetic blocked input', 'light_blocked': True} if role == 'dark'
                       else {'illumination_id': 'synthetic light', 'geometry_id': 'synthetic geometry'})
        inputs.append(Cube(np.ones((1, 1, 2)), {'data_level': 'spectral_cube', 'units': 'DN',
            'wavelengths': [500, 600], 'wavelength_units': 'nm', 'wavelength_source': 'synthetic',
            'exposure': 1000, 'gain': 0, 'settings': {'GainAuto': 'Off'},
            'linear_intensity': True, 'completed': True, 'partial': False, 'measurement_context': context}))
    check = reference_applicability(*inputs)
    assert check['status'] == 'MATCH'
    result = measurement_readiness(inputs[0], reference_check=check)
    assert result['frame_received']['status'] == 'NOT_APPLICABLE'
    assert result['reference_qualified']['status'] == 'MATCH'
    assert result['reference_qualified']['check'] == check
    assert 'not physical' in result['reference_qualified']['interpretation']
    assert measurement_readiness(raw_frame(), reference_check={'status': 'MATCH'})[
        'reference_qualified']['status'] == 'UNKNOWN'
    inputs[1].metadata['measurement_context']['instrument_id'] = 'different synthetic unit'
    mismatched = reference_applicability(*inputs)
    assert measurement_readiness(inputs[0], reference_check=mismatched)['reference_qualified']['status'] == 'MISMATCH'
