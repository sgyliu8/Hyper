"""Synthetic mathematical oracles; no device or physical calibration acceptance."""
from copy import deepcopy
import json
import threading

import numpy as np
import pytest

from hyperlab.io import Cube, load_cube
from hyperlab.spectroscopy.response import (characterize_response, load_response,
    reconstruct_scan, save_response, validate_reconstruction)


def response_fixture(*, normalized=False, A=None, shape=(2, 3), model='multiplexed',
                     region_map=None, alpha=0., waves=(500., 600.), wavelength_units='nm',
                     weights=None, bayer=False):
    A = np.array([[1., .2], [.3, 1.]]) if A is None else np.asarray(A, float)
    if A.ndim == 2:
        A = A[None]
    r, m, k = A.shape
    exposure = np.linspace(.01, .02, m)
    grid = {'grid_id': 'SYNTHETIC-native-grid', 'raw_shape_hw': list(shape),
        'sensor_roi_offset': [1, 0] if bayer else [0, 0], 'flip_x': bayer, 'flip_y': False,
        'cfa_pattern': 'RGGB' if bayer else None, 'cfa_pattern_origin': 'sensor' if bayer else 'not_applicable'}
    meta = {'state_ids': [f'state-{i}' for i in range(m)], 'model': model,
        'wavelength_source': 'SYNTHETIC analytic coordinates', 'wavelength_evidence': 'SYNTHETIC',
        'spatial_grid': grid, 'pixel_format': 'BayerRG12' if bayer else 'Mono12',
        'signal_units': 'DN/s' if normalized else 'DN', 'output_units': 'relative linear signal',
        'discretization': 'H rows are bin-integrated relative input coefficients; no further quadrature factor',
        'response_evidence': {'kind': 'SYNTHETIC', 'source': 'known numerical forward model; no device validation'},
        'applicability': {'instrument_id': 'SYNTHETIC-instrument', 'temperature_condition_id': 'SYNTHETIC-optical-temperature',
            'settings': {'black_level': 0, 'gamma': 'off'}, 'gain': 0., 'gain_units': 'dB', 'optical_configuration': {'fixture': 'fixed'}},
        'correction': {'dark_subtracted': True, 'exposure_normalized': normalized, 'exposure_s': exposure.tolist(),
            'linearity_evidence': {'verified': True, 'source': 'SYNTHETIC linear identity',
                'exposure_range_s': [.005, .1], 'gain': 0.} if normalized else None}}
    if model == 'direct_band':
        meta['fwhm'] = [2. if wavelength_units == 'nm' else .002] * k
    if weights is not None:
        meta['weight_evidence'] = {'source': 'SYNTHETIC known independent state variance', 'units': 'inverse state variance'}
    H = np.full((k, k), .2 / max(1, k - 1)) + np.eye(k) * (.8 - .2 / max(1, k - 1))
    if k == 1:
        H[:] = 1
    Y = np.einsum('rmk,kn->rmn', A, H)
    mapping = np.zeros(shape, int) if region_map is None else np.asarray(region_map, int)
    bundle = characterize_response(Y, H, wavelengths=waves, wavelength_units=wavelength_units,
        metadata=meta, region_map=mapping, alpha=alpha, weights=weights,
        wavelength_validity=np.any(A != 0, axis=1))
    return bundle


def raw_fixture(bundle, spectra=None, *, role='sample', exposure_s=None):
    meta, A = bundle['metadata'], np.asarray(bundle['A'])
    mapping = bundle['region_map']
    h, w = mapping.shape
    k, m = A.shape[2], A.shape[1]
    spectra = np.broadcast_to(np.arange(1, k + 1, dtype=float) * 10, (h, w, k)).copy() if spectra is None else np.asarray(spectra, float)
    exposures = np.asarray(meta['correction']['exposure_s'] if exposure_s is None else exposure_s)
    raw = np.zeros((h, w, m))
    for y, x in np.ndindex((h, w)):
        region = max(0, int(mapping[y, x]))
        raw[y, x] = A[region] @ spectra[y, x]
    if meta['correction']['exposure_normalized']:
        raw *= exposures
    dark = np.full(raw.shape, 3.)
    context = {'instrument_id': meta['applicability']['instrument_id'],
        'temperature_condition_id': meta['applicability']['temperature_condition_id'], 'role': role,
        'evidence_kind': 'declared', 'evidence_source': 'SYNTHETIC fixture',
        'illumination_id': 'SYNTHETIC light', 'geometry_id': 'SYNTHETIC geometry'}
    common = {'data_level': 'raw_scan', 'scan_states': list(meta['state_ids']), 'exposure_s': exposures.tolist(),
        'exposure': exposures.tolist(), 'exposure_units': 's', 'scan_recipe_id': 'SYNTHETIC-recipe',
        'spatial_grid': deepcopy(meta['spatial_grid']), 'pixel_format': meta['pixel_format'],
        'settings': deepcopy(meta['applicability']['settings']), 'gain': 0., 'gain_units': 'dB',
        'optical_configuration': deepcopy(meta['applicability']['optical_configuration']),
        'completed': True, 'partial': False, 'units': 'DN', 'saturation_value': 4095.,
        'data_source': 'SYNTHETIC', 'synthetic': True, 'measurement_context': context}
    dark_meta = deepcopy(common)
    dark_meta['measurement_context'].update(role='dark', light_blocked=True, dark_method='SYNTHETIC blocked light')
    return Cube(raw + dark, common), Cube(dark, dark_meta), spectra


def test_finite_band_fit_and_withheld_are_not_delta_sources():
    A = np.array([[1., .2], [.3, 1.]])
    bundle = response_fixture(A=A)
    np.testing.assert_allclose(bundle['A'][0], A, atol=1e-14)
    assert not np.allclose(bundle['characterization_Y'][0], A)
    H, Y = bundle['characterization_H'], bundle['characterization_Y']
    with pytest.raises(ValueError, match='H rank'):
        characterize_response(Y[..., :1], H[:, :1], wavelengths=[500, 600],
            metadata=bundle['metadata'], region_map=bundle['region_map'])
    checked = characterize_response(Y, H, wavelengths=[500, 600], metadata=bundle['metadata'],
        region_map=bundle['region_map'], validation_H=np.eye(2), validation_Y=A)
    np.testing.assert_allclose(checked['metadata']['characterization']['validation_residuals'], 0, atol=1e-14)
    assert checked['metadata']['characterization']['validation_status'] == 'NUMERIC_RESIDUAL_ONLY'
    repeated_brightness=np.array([[1.,2.,3.],[2.,4.,6.]])
    with pytest.raises(ValueError,match='H rank 1'):
        characterize_response(A @ repeated_brightness,repeated_brightness,wavelengths=[500,600],
            metadata=bundle['metadata'],region_map=bundle['region_map'])


@pytest.mark.parametrize('normalized', [False, True])
def test_full_rank_signed_oracle_correction_once_and_raw_immutability(normalized):
    bundle = response_fixture(normalized=normalized)
    spectra = np.broadcast_to([-1., 4.], (2, 3, 2)).copy()
    sample, dark, expected = raw_fixture(bundle, spectra)
    originals = [c.data.copy() for c in (sample, dark)]
    result = reconstruct_scan(sample, dark, bundle, chunk_pixels=2)
    np.testing.assert_allclose(result.data, expected, atol=1e-12)
    np.testing.assert_allclose(result.reconstruction_residual, 0, atol=1e-12)
    assert result.valid_mask.all() and result.metadata['completed']
    assert result.metadata['units'] == 'relative linear signal'
    assert result.metadata['signal_lineage']['exposure_normalized'] is normalized
    assert result.metadata['signal_lineage']['raw_quality_propagated']
    assert all(key not in result.metadata for key in ('saturation_value', 'pfnc_sample_bits'))
    assert result.metadata['effective_bits'] is None and result.metadata['pixel_format'] == 'unknown'
    assert result.metadata['source_provenance']['scan']['saturation_value'] == 4095
    for cube, before in zip((sample, dark), originals):
        np.testing.assert_array_equal(cube.data, before)


def test_reconstruct_then_ratio_mixed_oracle():
    bundle = response_fixture(A=[[.8, .2], [.3, .7]])
    white_signal = np.broadcast_to([10., 4.], (2, 3, 2))
    truth = np.array([.2, .8])
    sample, ds, _ = raw_fixture(bundle, white_signal * truth)
    white, dw, _ = raw_fixture(bundle, white_signal, role='white')
    s, w = reconstruct_scan(sample, ds, bundle), reconstruct_scan(white, dw, bundle)
    np.testing.assert_allclose(s.data / w.data, np.broadcast_to(truth, s.shape), atol=1e-12)
    wrong = np.linalg.solve(bundle['A'][0], ((sample.data - ds.data) / (white.data - dw.data))[0, 0])
    assert np.max(np.abs(wrong - truth)) > .1


def test_rank_deficient_response_rejected_even_with_regularizer():
    with pytest.raises(ValueError, match='rank deficient'):
        response_fixture(A=[[1, 1], [2, 2]], alpha=1)


def test_unsupported_column_is_masked_never_regularized_into_support():
    bundle = response_fixture(A=[[1, 0, 0], [0, 1, 0]], waves=[500, 600, 700], alpha=1)
    sample, dark, _ = raw_fixture(bundle)
    result = reconstruct_scan(sample, dark, bundle)
    assert result.valid_mask[..., :2].all()
    assert not result.valid_mask[..., 2].any()
    assert np.isnan(result.data[..., 2]).all()
    assert result.metadata['band_validity'] == [True, True, False]


@pytest.mark.parametrize('problem', ['missing', 'duplicate', 'reordered', 'partial', 'grid', 'unknown_saturation', 'already_processed'])
def test_preflight_refuses_semantic_mismatch_before_files(tmp_path, problem):
    bundle = response_fixture()
    sample, dark, _ = raw_fixture(bundle)
    if problem == 'missing':
        sample.metadata['scan_states'] = ['state-0']
    elif problem == 'duplicate':
        sample.metadata['scan_states'] = ['state-0', 'state-0']
    elif problem == 'reordered':
        sample.metadata['scan_states'].reverse()
    elif problem == 'partial':
        sample.metadata['partial'] = True
    elif problem == 'grid':
        sample.metadata['spatial_grid']['sensor_roi_offset'][0] = 1
    elif problem == 'unknown_saturation':
        sample.metadata.pop('saturation_value')
    else:
        sample.metadata['signal_lineage'] = {'domain': 'reconstructed_linear_signal'}
    path = tmp_path / 'derived.npy'
    with pytest.raises(ValueError):
        reconstruct_scan(sample, dark, bundle, output_path=path)
    assert not path.exists()


@pytest.mark.parametrize('bad', [0, -1, False, np.nan])
def test_invalid_exposure_refused(bad):
    bundle = response_fixture()
    sample, dark, _ = raw_fixture(bundle)
    sample.metadata['exposure_s'][0] = bad
    with pytest.raises(ValueError, match='exposure'):
        validate_reconstruction(sample, dark, bundle)


def test_normalization_requires_range_and_gain_evidence_but_fixed_A_needs_exact_exposure():
    fixed = response_fixture()
    sample, dark, _ = raw_fixture(fixed, exposure_s=[.02, .04])
    with pytest.raises(ValueError, match='exact characterized exposure'):
        reconstruct_scan(sample, dark, fixed)
    normalized = response_fixture(normalized=True)
    sample, dark, truth = raw_fixture(normalized, exposure_s=[.02, .04])
    np.testing.assert_allclose(reconstruct_scan(sample, dark, normalized).data, truth, atol=1e-12)
    normalized['metadata']['correction']['linearity_evidence']['verified'] = False
    with pytest.raises(ValueError, match='linearity'):
        reconstruct_scan(sample, dark, normalized)


def test_multiplexed_mask_and_raw_saturation_invalidate_all_required_coefficients():
    bundle = response_fixture()
    sample, dark, _ = raw_fixture(bundle)
    sample.valid_mask = np.ones(sample.shape, bool)
    sample.valid_mask[0, 0, 1] = False
    sample.data[0, 1, 0] = 4095
    result = reconstruct_scan(sample, dark, bundle, chunk_pixels=1)
    assert not result.valid_mask[0, :2].any()
    assert result.valid_mask[1].all()
    assert result.metadata['quality_counts']['scan']['saturated'] == [1, 0]
    assert result.metadata['quality_counts']['scan']['invalid'] == [0, 1]
    assert result.metadata['quality_counts']['output_valid_per_wavelength'] == [4, 4]


def test_measured_direct_band_preserves_independent_per_band_mask():
    bundle = response_fixture(A=np.diag([2., .5]), model='direct_band')
    sample, dark, truth = raw_fixture(bundle)
    sample.valid_mask = np.ones(sample.shape, bool)
    sample.valid_mask[0, 0, 1] = False
    result = reconstruct_scan(sample, dark, bundle)
    assert result.valid_mask[0, 0].tolist() == [True, False]
    np.testing.assert_allclose(result.data[1], truth[1], atol=1e-12)
    assert result.metadata['fwhm'] == [2., 2.]


def test_weighted_irregular_regularizer_is_actual_coordinate_and_reversible_units():
    waves = np.array([500., 503., 511.])
    first = response_fixture(A=np.eye(3), waves=waves, alpha=2, weights=[1, 2, 3])
    original_meta = deepcopy(first['metadata'])
    H, Y = first['characterization_H'], first['characterization_Y']
    reverse = characterize_response(Y, H[::-1], wavelengths=(waves / 1000)[::-1], wavelength_units='um',
        metadata=original_meta, region_map=first['region_map'], alpha=2, weights=[1, 2, 3])
    sample, dark, truth = raw_fixture(first)
    a, b = reconstruct_scan(sample, dark, first), reconstruct_scan(sample, dark, reverse)
    np.testing.assert_allclose(a.data, b.data, atol=1e-12)
    D = np.diff(np.eye(3), axis=0) / np.sqrt(np.diff(waves))[:, None]
    reference = np.linalg.solve(np.diag([1, 2, 3]) + 2 * D.T @ D, np.diag([1, 2, 3]) @ truth[0, 0])
    np.testing.assert_allclose(a.data[0, 0], reference, atol=1e-12)
    assert not np.allclose(a.data[0, 0], truth[0, 0])
    assert a.metadata['reconstruction']['response_diagnostics'][0]['rank'] == 3


def test_explicit_gap_omits_regularizer_connection():
    bundle = response_fixture(A=np.eye(3), waves=[500, 501, 900], alpha=10)
    bundle['metadata']['measurement_gaps_nm'] = [[502, 899]]
    sample, dark, _ = raw_fixture(bundle)
    result = reconstruct_scan(sample, dark, bundle)
    D = result.metadata['reconstruction']['response_diagnostics'][0]['regularizer_rows']
    np.testing.assert_array_equal(D, [[-1, 1, 0]])


def test_native_cfa_region_lookup_and_unsupported_pixels():
    phase = np.array([[1, 0, 1], [3, 2, 3]])  # sensor RGGB, offset x1, flip x on width3
    A = np.array([np.diag([scale, 1.]) for scale in (1., 2., 3., 4.)])
    mapping = phase.copy()
    mapping[1, 2] = -1
    bundle = response_fixture(A=A, shape=(2, 3), model='direct_band', region_map=mapping, bayer=True)
    sample, dark, truth = raw_fixture(bundle)
    result = reconstruct_scan(sample, dark, bundle)
    supported = mapping >= 0
    np.testing.assert_allclose(result.data[supported], truth[supported], atol=1e-12)
    assert not result.valid_mask[1, 2].any()
    assert result.metadata['quality_counts']['unsupported_spatial_pixels'] == 1
    assert result.metadata['signal_lineage']['spatial_grid'] == bundle['metadata']['spatial_grid']


def test_bundle_roundtrip_hash_validation_and_finite_arrays(tmp_path):
    bundle = response_fixture()
    saved = save_response(bundle, tmp_path / 'response')
    loaded = load_response(saved)
    np.testing.assert_array_equal(loaded['A'], bundle['A'])
    sample, dark, _ = raw_fixture(bundle)
    assert validate_reconstruction(sample, dark, loaded)['operator_signature'] == validate_reconstruction(sample, dark, bundle)['operator_signature']
    with pytest.raises(FileExistsError):
        save_response(bundle, saved)
    path = saved / 'A.npy'
    with path.open('r+b') as stream:
        stream.seek(-1, 2)
        stream.write(b'\xff')
    with pytest.raises(ValueError, match='hash'):
        load_response(saved)


def test_cancelled_output_reopens_exact_processed_prefix_and_residual(tmp_path):
    bundle = response_fixture()
    sample, dark, truth = raw_fixture(bundle)
    stop = threading.Event()
    def progress(done, total):
        if done == 2:
            stop.set()
    path = tmp_path / 'result.npy'
    result = reconstruct_scan(sample, dark, bundle, output_path=path, stop=stop, progress=progress, chunk_pixels=1)
    assert result.metadata['partial'] and not result.metadata['completed']
    assert result.metadata['completed_pixels'] == 2
    result.close()
    with load_cube(path) as reopened:
        assert reopened.metadata['completed_pixels'] == 2
        assert reopened.valid_mask.reshape(-1, 2)[:2].all()
        assert not reopened.valid_mask.reshape(-1, 2)[2:].any()
        np.testing.assert_allclose(reopened.data.reshape(-1, 2)[:2], truth.reshape(-1, 2)[:2], atol=1e-12)
        assert np.isnan(reopened.data.reshape(-1, 2)[2:]).all()
        residual = np.load(path.parent / reopened.metadata['reconstruction']['residual_file'])
        np.testing.assert_allclose(residual.reshape(-1, 2)[:2], 0, atol=1e-12)
        assert np.isnan(residual.reshape(-1, 2)[2:]).all()
        asset = reopened.metadata['reconstruction']['residual_asset']
        import hashlib
        assert asset['sha256'] == hashlib.sha256((path.parent / asset['file']).read_bytes()).hexdigest()
        assert asset['completed_pixels'] == 2 and asset['shape'] == [2, 3, 2]
        assert asset['operator_signature'] == reopened.metadata['signal_lineage']['operator_signature']
    with pytest.raises(FileExistsError):
        reconstruct_scan(sample, dark, bundle, output_path=path)


def test_source_mutation_during_run_withholds_complete_product(tmp_path):
    bundle = response_fixture()
    sample, dark, _ = raw_fixture(bundle)
    def mutate(done, total):
        if done == 1:
            sample.data[0, 0, 0] += 1
    path = tmp_path / 'failed.npy'
    with pytest.raises(ValueError, match='Source changed'):
        reconstruct_scan(sample, dark, bundle, output_path=path, progress=mutate, chunk_pixels=1)
    saved = json.loads(path.with_suffix('.npy.json').read_text())
    assert saved['partial'] and not saved['completed']
    assert 'Source changed' in saved['reconstruction']['error']


def test_operator_identity_excludes_source_ids_but_includes_alpha_and_mapping():
    bundle = response_fixture(alpha=1)
    sample, dark, _ = raw_fixture(bundle)
    first = validate_reconstruction(sample, dark, bundle)['operator_signature']
    other = deepcopy(bundle)
    other['bundle_id'] = 'different-provenance-identity'
    other['metadata']['response_evidence']['source'] = 'another retained evidence source'
    assert validate_reconstruction(sample, dark, other)['operator_signature'] == first
    other['metadata']['solver']['alpha'] = 2
    assert validate_reconstruction(sample, dark, other)['operator_signature'] != first


def test_imported_um_bandwidth_preserves_nm_operator_and_result():
    bundle = response_fixture(A=np.diag([1., 2.]), model='direct_band')
    sample, dark, _ = raw_fixture(bundle)
    converted = deepcopy(bundle)
    converted['metadata']['wavelengths'] = [.5, .6]
    converted['metadata']['wavelength_units'] = 'um'
    converted['metadata']['fwhm'] = [.002, .002]
    converted['metadata']['fwhm_units'] = 'um'
    first = reconstruct_scan(sample, dark, bundle)
    second = reconstruct_scan(sample, dark, converted)
    assert second.metadata['fwhm'] == [2., 2.]
    assert second.metadata['wavelengths'] == [500., 600.]
    assert first.metadata['signal_lineage']['operator_signature'] == second.metadata['signal_lineage']['operator_signature']


@pytest.mark.parametrize('change', ['solver', 'gain_units', 'mixed_boolean_exposure'])
def test_unsupported_semantics_not_silently_ignored(change):
    bundle = response_fixture()
    sample, dark, _ = raw_fixture(bundle)
    if change == 'solver':
        bundle['metadata']['solver']['method'] = 'an unimplemented nonlinear solver'
    elif change == 'gain_units':
        sample.metadata['gain_units'] = 'linear multiplier'
    else:
        bundle['metadata']['correction']['exposure_s'] = [.01, True]
    with pytest.raises(ValueError):
        validate_reconstruction(sample, dark, bundle)


@pytest.mark.parametrize('failure_stage', ['observer_then_checkpoint', 'initial_checkpoint', 'allocation'])
def test_persistence_error_retains_primary_failure_and_closes_owned_maps(tmp_path, monkeypatch, failure_stage):
    import hyperlab.spectroscopy.response as module
    bundle = response_fixture()
    sample, dark, _ = raw_fixture(bundle)
    original_atomic, original_mmap = module.atomic_json, np.lib.format.open_memmap
    mappings = []
    def open_mapping(*args, **kwargs):
        if failure_stage == 'allocation' and len(mappings) == 1:
            raise OSError('allocation unavailable')
        mapped = original_mmap(*args, **kwargs)
        mappings.append(mapped)
        return mapped
    def fail_checkpoint(path, metadata):
        if failure_stage == 'initial_checkpoint' or metadata['completed_pixels'] > 0:
            raise OSError('checkpoint unavailable')
        original_atomic(path, metadata)
    def observer(done, total):
        raise RuntimeError('observer failure is primary')
    monkeypatch.setattr(np.lib.format, 'open_memmap', open_mapping)
    monkeypatch.setattr(module, 'atomic_json', fail_checkpoint)
    error_type = RuntimeError if failure_stage == 'observer_then_checkpoint' else OSError
    message = 'observer failure is primary' if error_type is RuntimeError else 'allocation unavailable' if failure_stage == 'allocation' else 'checkpoint unavailable'
    with pytest.raises(error_type, match=message) as caught:
        reconstruct_scan(sample, dark, bundle, output_path=tmp_path / 'partial.npy', progress=observer, chunk_pixels=1)
    assert all(mapped._mmap.closed for mapped in mappings)
    if failure_stage != 'allocation':
        assert 'checkpoint' in ' '.join(getattr(caught.value, '__notes__', []))


@pytest.mark.parametrize('case', ['synthetic_dark', 'synthetic_response', 'conflicting_origin'])
def test_synthetic_correction_cannot_be_relabelled_as_measured(case):
    bundle = response_fixture()
    sample, dark, _ = raw_fixture(bundle)
    sample.metadata.update(synthetic=False, acquisition_source='LIVE', data_source='LIVE')
    if case != 'synthetic_dark':
        dark.metadata.update(synthetic=False, acquisition_source='LIVE', data_source='LIVE')
    if case == 'conflicting_origin':
        sample.metadata['synthetic'] = True
    with pytest.raises(ValueError, match='[Ss]ynthetic'):
        validate_reconstruction(sample, dark, bundle)


@pytest.mark.parametrize('origin', ['LIVE', 'EXTERNAL_MEASURED', 'EXTERNAL_MEASURED_AVERAGE'])
def test_replay_and_external_measurement_declarations_remain_usable(origin):
    # Synthetic numbers exercise metadata acceptance, never an actual measured test.
    bundle = response_fixture()
    bundle['metadata']['response_evidence'] = {'kind': 'documented', 'source': 'TEST declared measured response'}
    sample, dark, truth = raw_fixture(bundle)
    for cube in (sample, dark):
        cube.metadata.update(synthetic=False, acquisition_source=origin, data_source='external_file', display_mode='REPLAY')
    result = reconstruct_scan(sample, dark, bundle)
    np.testing.assert_allclose(result.data, truth, atol=1e-12)
    assert result.metadata['acquisition_source'] == origin and result.metadata['display_mode'] == 'REPLAY'
