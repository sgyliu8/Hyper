from copy import deepcopy
import json
from threading import Event

import numpy as np
import pytest

from hyperlab.analysis import reflectance, roi_statistics
from hyperlab.analysis.applicability import reference_applicability
from hyperlab.io import Cube, load_cube
from hyperlab.spectroscopy.reflectance import reflectance_corrected, validate_reflectance_corrected


def signal(values, role, *, normalized=False, exposures=(.01, .01)):
    """Independent synthetic linear signals, never physical calibration evidence."""
    data = np.asarray(values, dtype=np.float64).reshape(1, -1, 2)
    lineage = dict(schema_version=1, domain='reconstructed_linear_signal', dark_subtracted=True,
        exposure_normalized=normalized, exposure_units='s', exposure_s=list(exposures),
        normalization_linearity_evidence=({'verified': True, 'source': 'analytic fixture',
            'exposure_range_s': [.001, 1.0], 'gain': 0} if normalized else None),
        response_bundle_id=f'{role}-response-asset', operator_signature='a' * 64,
        input_source_ids=[f'{role}-source'], state_order=['state-0', 'state-1'],
        raw_quality_propagated=True,
        spatial_grid=dict(grid_id='native-test-grid', raw_shape_hw=list(data.shape[:2]),
            sensor_roi_offset=[0, 0], flip_x=False, flip_y=False, cfa_pattern=None,
            cfa_pattern_origin='not_applicable'))
    context = dict(instrument_id='synthetic instrument', response_calibration_id='fixture',
        temperature_condition_id='instrument thermal condition', illumination_id='fixture lamp',
        geometry_id='fixture geometry', role=role, evidence_kind='declared',
        evidence_source='independent analytic fixture')
    return Cube(data, dict(data_level='spectral_cube', wavelengths=[500, 600], wavelength_units='nm',
        wavelength_source='analytic fixture', linear_intensity=True, units='relative linear signal',
        fwhm=[10, 20], gain=0, gain_units='dB', settings={'ExposureAuto': 'Off', 'GainAuto': 'Off'},
        optical_configuration={'lens': 'analytic fixture lens'},
        completed=True, partial=False, signal_lineage=lineage, measurement_context=context,
        data_source='SYNTHETIC', synthetic=True,
        processing_steps=[{'operation': 'reconstruct', 'source_asset': f'{role}-asset'}],
        reconstruction={'rank': 2, 'resolution_matrix': [[.8, .2], [.2, .8]]}),
        np.ones(data.shape, dtype=bool))


def pair(**kwargs):
    return signal([40, 40, 40, 40], 'sample', **kwargs), signal([100] * 4, 'white', **kwargs)


def raw_inputs():
    result = []
    for role, value in zip(('sample', 'white', 'dark', 'dark'), (30, 100, 10, 10)):
        cube = signal([value] * 4, role)
        cube.metadata.pop('signal_lineage')
        cube.metadata.update(units='DN', exposure=10, effective_bits=12, processing_steps=[])
        if role == 'dark':
            cube.metadata['measurement_context'].update(light_blocked=True, dark_method='analytic dark')
        result.append(cube)
    return result


def test_corrected_signal_is_divided_once_and_preserves_distinct_provenance():
    sample, white = pair()
    before = [deepcopy(c.metadata) for c in (sample, white)]
    result = reflectance_corrected(sample, white)
    np.testing.assert_allclose(result.data, .4)
    assert result.metadata['reflectance_kind'] == 'relative'
    assert result.metadata['units'] == 'dimensionless'
    assert result.metadata['processing_steps'][0]['additional_dark_subtraction'] is False
    assert result.metadata['source_provenance']['sample']['reconstruction']['rank'] == 2
    assert result.metadata['source_provenance']['white']['reconstruction']['resolution_matrix'][0] == [.8, .2]
    assert result.metadata['source_fingerprints']['sample']['source_id'] != result.metadata['source_fingerprints']['white']['source_id']
    assert [c.metadata for c in (sample, white)] == before
    assert 'not monochromatic point truth' in result.metadata['interpretation']


def test_normalized_different_original_exposures_are_not_corrected_again():
    sample, white = pair(normalized=True)
    white.metadata['signal_lineage']['exposure_s'] = [.02, .05]
    result = reflectance_corrected(sample, white)
    np.testing.assert_allclose(result.data, .4)
    assert result.metadata['source_provenance']['white']['signal_lineage']['exposure_s'] == [.02, .05]
    assert result.metadata['processing_steps'][0]['additional_exposure_normalization'] is False


def test_fixed_exposure_mismatch_blocks_before_creating_output(tmp_path):
    sample, white = pair()
    white.metadata['signal_lineage']['exposure_s'][0] = .02
    path = tmp_path / 'not-created' / 'factor.npy'
    assert not validate_reflectance_corrected(sample, white)['allowed']
    with pytest.raises(ValueError, match='fixed_exposure'):
        reflectance_corrected(sample, white, output_path=path)
    assert not path.parent.exists()


@pytest.mark.parametrize('field,value', [('verified', False), ('source', ''),
    ('exposure_range_s', [.02, 1]), ('exposure_range_s', [0, 1]), ('exposure_range_s', [1, .01]),
    ('gain', 1), ('gain', False)])
def test_normalization_evidence_must_cover_each_input(field, value):
    sample, white = pair(normalized=True)
    white.metadata['signal_lineage']['normalization_linearity_evidence'][field] = value
    with pytest.raises(ValueError, match='normalization_linearity'):
        reflectance_corrected(sample, white)


@pytest.mark.parametrize('field,value', [('dark_subtracted', False), ('dark_subtracted', 'true'),
    ('domain', 'reflectance'), ('schema_version', True), ('raw_quality_propagated', False),
    ('exposure_normalized', None), ('exposure_s', [0, .01]), ('exposure_s', [True, .01]),
    ('exposure_s', [float('nan'), .01]), ('state_order', None), ('spatial_grid', None)])
def test_incomplete_or_incompatible_lineage_is_reported_without_allocation(field, value, tmp_path):
    sample, white = pair()
    white.metadata['signal_lineage'][field] = value
    path = tmp_path / 'uncreated' / 'factor.npy'
    report = validate_reflectance_corrected(sample, white, output_path=path)
    assert report['status'] == 'MISMATCH' and not report['allowed']
    json.dumps(report, allow_nan=False)
    with pytest.raises(ValueError):
        reflectance_corrected(sample, white, output_path=path)
    assert not path.parent.exists()


@pytest.mark.parametrize('field', ['signal_lineage', 'measurement_context'])
def test_missing_whole_context_is_a_preflight_result(field):
    sample, white = pair()
    white.metadata[field] = None
    assert not validate_reflectance_corrected(sample, white)['allowed']


@pytest.mark.parametrize('field,value', [('operator_signature', 'b' * 64),
    ('spatial_grid', dict(grid_id='different', raw_shape_hw=[1, 2], sensor_roi_offset=[0, 0],
        flip_x=False, flip_y=False, cfa_pattern=None, cfa_pattern_origin='not_applicable'))])
def test_changed_effective_operator_or_grid_blocks_ratio(field, value):
    sample, white = pair()
    white.metadata['signal_lineage'][field] = value
    with pytest.raises(ValueError, match=field):
        reflectance_corrected(sample, white)


@pytest.mark.parametrize('pattern,origin', [(None, 'sensor'), ('unknown CFA', 'sensor'), ('RGGB', 'not_applicable')])
def test_equal_but_contradictory_cfa_grid_evidence_is_not_match(pattern, origin):
    sample, white = pair()
    for cube in (sample, white):
        cube.metadata['signal_lineage']['spatial_grid'].update(cfa_pattern=pattern, cfa_pattern_origin=origin)
    assert not validate_reflectance_corrected(sample, white)['allowed']


def test_native_grid_coordinates_accept_equivalent_list_and_tuple_representations():
    sample, white = pair()
    white.metadata['signal_lineage']['spatial_grid'].update(raw_shape_hw=(1, 2), sensor_roi_offset=(np.int64(0), 0))
    assert validate_reflectance_corrected(sample, white)['allowed']


@pytest.mark.parametrize('field,value', [('fwhm', [100, 20]), ('band_validity', [True, False]),
    ('units', 'DN'), ('gain', 1), ('gain_units', 'linear'), ('wavelengths', [510, 600]), ('data_level', 'reflectance_cube'),
    ('optical_configuration', {'lens': 'different'}), ('measurement_gaps_nm', [[530, 580]])])
def test_different_spectral_basis_or_signal_domain_blocks_ratio(field, value):
    sample, white = pair()
    white.metadata[field] = value
    with pytest.raises(ValueError):
        reflectance_corrected(sample, white)


def test_numpy_width_and_support_metadata_compare_without_ambiguous_truth():
    sample, white = pair()
    for cube in (sample, white):
        cube.metadata['fwhm'] = np.array([10., 20.])
        cube.metadata['band_validity'] = np.array([True, False])
    result = reflectance_corrected(sample, white)
    assert result.valid_mask[..., 0].all() and not result.valid_mask[..., 1].any()


def test_measurement_gaps_remain_explicit_in_output():
    sample, white = pair()
    for cube in (sample, white):
        cube.metadata['measurement_gaps_nm'] = [[530, 580]]
    result = reflectance_corrected(sample, white)
    assert result.metadata['measurement_gaps_nm'] == [[530, 580]]


def test_preflight_does_not_hash_sources_or_allocate_output(monkeypatch, tmp_path):
    import hyperlab.spectroscopy.reflectance as module
    sample, white = pair()
    def forbidden(*args, **kwargs):
        raise AssertionError('Preflight must not touch source arrays or output files')
    monkeypatch.setattr(module, 'source_fingerprint', forbidden)
    monkeypatch.setattr(module.np.lib.format, 'open_memmap', forbidden)
    path = tmp_path / 'uncreated' / 'factor.npy'
    report = validate_reflectance_corrected(sample, white, output_path=path)
    assert report['allowed'] and report['output_bytes'] == 4 * 9
    assert not path.parent.exists()


def test_corrected_values_are_not_raw_adc_counts_or_raw_ignore_values():
    sample = signal([0, 10000, 10000, 10000], 'sample')
    white = signal([20000] * 4, 'white')
    for cube in (sample, white):
        cube.metadata.update(effective_bits=12, saturation_value=4095, data_ignore_value=0,
                             uncertainty={'standard_uncertainty': 2, 'units': 'DN'})
    sample.valid_mask[0, 1, 0] = False  # Upstream raw invalidity still propagates.
    result = reflectance_corrected(sample, white)
    np.testing.assert_array_equal(result.valid_mask, [[[True, True], [False, True]]])
    np.testing.assert_allclose(result.data[result.valid_mask], [0, .5, .5])
    assert result.metadata['uncertainty']['status'] == 'not_computed'
    assert result.metadata['source_provenance']['sample']['uncertainty']['units'] == 'DN'
    assert result.metadata.get('effective_bits') is None and 'data_ignore_value' not in result.metadata


def test_pixel_ratio_precedes_roi_mean_and_spatial_sd_is_not_uncertainty():
    sample = signal([1, 1, 9, 9], 'sample')
    white = signal([1, 1, 3, 3], 'white')
    result = reflectance_corrected(sample, white)
    statistics = roi_statistics(result, (0, 0, 2, 1))
    np.testing.assert_allclose(statistics['mean'], [2, 2])
    assert not np.allclose(statistics['mean'], sample.data.mean(axis=(0, 1)) / white.data.mean(axis=(0, 1)))
    assert result.metadata['uncertainty']['status'] == 'not_computed'


def test_masks_denominator_counts_and_signed_factors_are_complete():
    sample = signal([-1, 3, 5, 7, np.nan, 4, 8, 2], 'sample')
    white = signal([1, 1, 0, -1, 1, 1, 2, 2], 'white')
    sample.valid_mask[0, 3, 0] = False
    result = reflectance_corrected(sample, white, minimum_denominator=.01, chunk_pixels=1)
    counts = result.metadata['quality_counts']
    assert counts == dict(processed_values=8, input_invalid=2, low_denominator=2,
                          nonfinite_result=0, valid=4, negative=1, above_one=2)
    assert result.metadata['valid_count_by_band'] == [1, 3]
    np.testing.assert_allclose(result.data[result.valid_mask], [-1, 3, 4, 1])
    assert np.isnan(result.data[~result.valid_mask]).all()


def test_finite_inputs_that_overflow_ratio_are_counted_and_masked():
    sample = signal([1e308, 1, 1, 1], 'sample')
    white = signal([1e-308, 1, 1, 1], 'white')
    result = reflectance_corrected(sample, white, minimum_denominator=1e-310)
    assert result.metadata['quality_counts']['nonfinite_result'] == 1
    assert result.metadata['quality_counts']['valid'] == 3
    assert not result.valid_mask[0, 0, 0] and np.isnan(result.data[0, 0, 0])


def test_reference_factor_is_applied_per_band_and_requires_source():
    sample, white = pair()
    with pytest.raises(ValueError, match='source'):
        reflectance_corrected(sample, white, reference_reflectance=[.5, .9])
    result = reflectance_corrected(sample, white, reference_reflectance=[.5, .9], reference_source='analytic reference')
    np.testing.assert_allclose(result.data, [[[.2, .36], [.2, .36]]])
    assert result.metadata['reflectance_kind'] == 'reference-calibrated'
    assert result.metadata['reference_source'] == 'analytic reference'


def test_mapped_result_reopens_with_quality_and_full_source_provenance(tmp_path):
    sample, white = pair()
    path = tmp_path / 'factor.npy'
    with reflectance_corrected(sample, white, output_path=path, memory_threshold_bytes=1, chunk_pixels=1) as result:
        assert isinstance(result.data, np.memmap) and result.metadata['completed'] is True
    with load_cube(path) as reopened:
        np.testing.assert_allclose(reopened.data, .4)
        assert reopened.valid_mask.all()
        assert reopened.metadata['completed_pixels'] == 2
        assert reopened.metadata['quality_counts']['valid'] == 4
        assert reopened.metadata['source_provenance']['white']['signal_lineage']['response_bundle_id'] == 'white-response-asset'
    path.rename(tmp_path / 'released.npy')


def test_pre_cancelled_work_creates_no_output(tmp_path):
    sample, white = pair()
    stop = Event(); stop.set()
    path = tmp_path / 'not-created' / 'factor.npy'
    with pytest.raises(InterruptedError):
        reflectance_corrected(sample, white, stop=stop, output_path=path)
    assert not path.parent.exists()


def test_midway_cancel_keeps_only_completed_prefix_and_releases_maps(tmp_path):
    sample, white = pair()
    stop = Event()
    updates = []
    def progress(update):
        updates.append(update)
        stop.set()
    path = tmp_path / 'partial.npy'
    with pytest.raises(InterruptedError):
        reflectance_corrected(sample, white, stop=stop, progress=progress, chunk_pixels=1, output_path=path)
    assert len(updates) == 1 and updates[0]['completed_pixels'] == 1
    with load_cube(path) as reopened:
        assert reopened.metadata['phase'] == 'cancelled' and reopened.metadata['completed'] is False
        assert reopened.metadata['partial'] is True and reopened.metadata['completed_pixels'] == 1
        np.testing.assert_array_equal(reopened.valid_mask, [[[True, True], [False, False]]])
        assert roi_statistics(reopened, (0, 0, 2, 1))['count'].tolist() == [1, 1]
    path.rename(tmp_path / 'released-partial.npy')


def test_source_change_invalidates_all_saved_values(tmp_path):
    sample, white = pair()
    def progress(update):
        sample.data[0, 0, 0] += 1
    path = tmp_path / 'source-changed.npy'
    with pytest.raises(ValueError, match='Source changed'):
        reflectance_corrected(sample, white, progress=progress, chunk_pixels=1, output_path=path)
    with load_cube(path) as reopened:
        assert not reopened.valid_mask.any() and reopened.metadata['completed'] is False
        assert reopened.metadata['quality_counts']['source_invalidated'] == 4
        assert reopened.metadata['quality_counts']['valid'] == 0
        assert reopened.metadata['valid_count_by_band'] == [0, 0]


def test_memory_budget_and_existing_destination_are_not_silently_overridden(tmp_path):
    sample, white = pair()
    with pytest.raises(ValueError, match='output_path'):
        reflectance_corrected(sample, white, memory_threshold_bytes=1)
    path = tmp_path / 'existing.npy'
    path.write_bytes(b'existing evidence')
    with pytest.raises(ValueError, match='never overwritten'):
        reflectance_corrected(sample, white, output_path=path)
    assert path.read_bytes() == b'existing evidence'


def test_failed_final_checkpoint_never_leaves_completed_metadata(tmp_path, monkeypatch):
    from pathlib import Path
    sample, white = pair()
    path = tmp_path / 'failed-final-checkpoint.npy'
    original_replace = Path.replace
    injected = []
    def replace(temporary, target):
        if str(temporary).endswith('.json.tmp') and json.loads(temporary.read_text())['completed'] and not injected:
            injected.append(True)
            raise OSError('Injected final checkpoint replacement failure')
        return original_replace(temporary, target)
    monkeypatch.setattr(Path, 'replace', replace)
    with pytest.raises(OSError, match='Injected final checkpoint'):
        reflectance_corrected(sample, white, output_path=path, chunk_pixels=1)
    assert injected == [True]
    with load_cube(path) as reopened:
        assert reopened.metadata['completed'] is False and reopened.metadata['partial'] is True
        assert reopened.metadata['phase'] == 'failed' and reopened.metadata['completed_pixels'] == 2
    path.rename(tmp_path / 'released-checkpoint.npy')


def test_mask_allocation_failure_releases_already_created_data_mapping(tmp_path, monkeypatch):
    import hyperlab.spectroscopy.reflectance as module
    sample, white = pair()
    path = tmp_path / 'allocation-failed.npy'
    original_open = module.np.lib.format.open_memmap
    def open_memmap(filename, *args, **kwargs):
        if str(filename).endswith('.valid.npy'):
            raise OSError('Injected mask allocation failure')
        return original_open(filename, *args, **kwargs)
    monkeypatch.setattr(module.np.lib.format, 'open_memmap', open_memmap)
    with pytest.raises(OSError, match='Injected mask allocation'):
        reflectance_corrected(sample, white, output_path=path)
    assert not path.with_suffix('.npy.json').exists()
    path.rename(tmp_path / 'released-allocation.npy')


@pytest.mark.parametrize('exposure', [0, -10, False, float('nan')])
def test_legacy_positive_exposure_gate_matches_preflight(exposure, tmp_path):
    inputs = raw_inputs()
    for cube in inputs:
        cube.metadata['exposure'] = exposure
    assert reference_applicability(*inputs)['status'] != 'MATCH'
    path = tmp_path / 'not-created' / 'raw-factor.npy'
    with pytest.raises(ValueError):
        reflectance(*inputs, output_path=path)
    assert not path.parent.exists()


def test_legacy_typed_double_correction_and_nonphysical_wavelengths_are_blocked():
    inputs = raw_inputs()
    for cube in inputs:
        cube.metadata['signal_lineage'] = {'dark_subtracted': True}
    assert reference_applicability(*inputs)['status'] == 'MISMATCH'
    with pytest.raises(ValueError, match='already applied'):
        reflectance(*inputs)
    inputs = raw_inputs()
    for cube in inputs:
        cube.metadata['wavelengths'] = [-600, -500]
    assert reference_applicability(*inputs)['status'] == 'MISMATCH'
    with pytest.raises(ValueError):
        reflectance(*inputs)


def test_valid_raw_dark_route_keeps_algebra_and_does_not_copy_dn_uncertainty():
    inputs = raw_inputs()
    inputs[0].metadata['uncertainty'] = {'standard_uncertainty': 2, 'units': 'DN'}
    result = reflectance(*inputs)
    np.testing.assert_allclose(result.data, 2 / 9)
    assert result.metadata['uncertainty']['status'] == 'not_computed'
    assert result.metadata['source_provenance']['sample']['uncertainty']['units'] == 'DN'


def test_legacy_declared_bandwidth_mismatch_is_not_same_spectral_basis():
    inputs = raw_inputs()
    inputs[1].metadata['fwhm'] = [100, 20]
    assert reference_applicability(*inputs)['status'] == 'MISMATCH'
    with pytest.raises(ValueError, match='fwhm'):
        reflectance(*inputs)
    inputs[1].metadata.pop('fwhm')
    assert reference_applicability(*inputs)['status'] == 'UNKNOWN'


@pytest.mark.parametrize('normalized', [False, True])
def test_actual_reconstruction_then_ratio_recovers_analytic_spectrum(normalized):
    from hyperlab.spectroscopy.response import characterize_response, reconstruct_scan
    grid = dict(grid_id='native-integration-grid', raw_shape_hw=[1, 1], sensor_roi_offset=[0, 0],
                flip_x=False, flip_y=False, cfa_pattern=None, cfa_pattern_origin='not_applicable')
    settings = {'ExposureAuto': 'Off', 'GainAuto': 'Off'}
    optics = {'lens': 'analytic lens'}
    matrix = np.array([[1., .3], [.2, 1.]]) * (100 if normalized else 1)
    known_sources = np.array([[1., 0, 1], [0, 1, 1]])
    bundle = characterize_response(matrix @ known_sources, known_sources, wavelengths=[500, 600],
        region_map=np.zeros((1, 1), dtype=int), metadata=dict(
            state_ids=['s0', 's1'], wavelength_source='analytic finite-source basis',
            response_evidence={'kind': 'SYNTHETIC', 'source': 'independent analytic fixture'},
            discretization='two synthetic linear spectral coefficients', pixel_format='Mono12',
            signal_units='DN/s' if normalized else 'DN', output_units='relative linear signal',
            spatial_grid=grid, applicability=dict(instrument_id='fixture instrument',
                temperature_condition_id='fixture temperature', settings=settings, gain=0, gain_units='dB',
                optical_configuration=optics),
            correction=dict(dark_subtracted=True, exposure_normalized=normalized, exposure_s=[.01, .01],
                linearity_evidence={'verified': True, 'source': 'analytic fixture',
                    'exposure_range_s': [.001, 1], 'gain': 0} if normalized else None)))
    def raw(values, role, exposure):
        context = dict(role=role, instrument_id='fixture instrument', temperature_condition_id='fixture temperature',
            illumination_id='fixture lamp', geometry_id='fixture geometry', evidence_kind='declared',
            evidence_source='independent analytic fixture')
        if role == 'dark':
            context.update(light_blocked=True, dark_method='analytic blocked-light signal')
        return Cube(np.asarray(values)[None, None, :], dict(data_level='raw_scan', units='DN',
            completed=True, partial=False, scan_states=['s0', 's1'], spatial_grid=grid,
            pixel_format='Mono12', effective_bits=12, exposure_s=[exposure] * 2,
            gain=0, gain_units='dB', settings=settings, optical_configuration=optics, measurement_context=context,
            data_source='SYNTHETIC', synthetic=True))
    sample_signal, white_signal = np.array([2., 16.]), np.array([10., 20.])
    exposures = [.01, .02] if normalized else [.01, .01]
    reconstructed, raw_corrected = [], []
    for value, role, exposure in zip((sample_signal, white_signal), ('sample', 'white'), exposures):
        z = matrix @ value * (exposure if normalized else 1)
        raw_corrected.append(z)
        reconstructed.append(reconstruct_scan(raw(z + 10, role, exposure), raw([10., 10.], 'dark', exposure), bundle))
    assert not np.allclose(raw_corrected[0] / raw_corrected[1], [.2, .8])
    result = reflectance_corrected(*reconstructed)
    np.testing.assert_allclose(result.data[0, 0], [.2, .8], rtol=1e-12)
    assert result.metadata['source_provenance']['sample']['reconstruction']['response_diagnostics'][0]['rank'] == 2
