from copy import deepcopy
from threading import Event

import numpy as np
import pytest

from hyperlab.io import Cube, load_cube
from hyperlab.spectroscopy.diagnostics import diagnostic_map
from hyperlab.spectroscopy.response import reconstruct_scan
from test_response import response_fixture, raw_fixture


def residual_fixture(*, normalized=False, output_path=None):
    matrix = np.array([[1., 0], [0, 1.], [1., 1.]])
    bundle = response_fixture(A=matrix, normalized=normalized)
    raw, dark, _ = raw_fixture(bundle)
    raw.data[..., 2] += 3 * (bundle['metadata']['correction']['exposure_s'][2] if normalized else 1)
    return reconstruct_scan(raw, dark, bundle, output_path=output_path)


@pytest.mark.parametrize('normalized', [False, True])
def test_actual_reconstruction_residual_has_independent_rms_and_state_units(normalized):
    cube = residual_fixture(normalized=normalized)
    # Least squares of [10,20,33] under rows [1,0],[0,1],[1,1]
    # gives [11,21] and residual [1,1,-1]: RMS is exactly 1.
    result = diagnostic_map(cube, 'reconstruction_residual', chunk_pixels=2)
    np.testing.assert_allclose(result['data'], 1, rtol=1e-12, atol=1e-12)
    assert result['valid_mask'].all()
    assert result['metadata']['units'] == ('DN/s' if normalized else 'DN')
    np.testing.assert_array_equal(result['metadata']['used_counts'], 3)
    assert result['metadata']['operation'] == 'reconstruction_residual'
    assert result['metadata']['acquisition_source'] == 'SYNTHETIC'
    assert 'not reflectance' in result['metadata']['interpretation']


def test_support_denominator_is_full_output_grid_and_zero_support_is_masked():
    bundle = response_fixture(A=[[1, 0, 0], [0, 1, 0]], waves=[500, 600, 700])
    raw, dark, _ = raw_fixture(bundle)
    cube = reconstruct_scan(raw, dark, bundle)
    cube.valid_mask[0, 0, 0] = False
    cube.valid_mask[0, 1] = False
    cube.data[1, 2, 1] = np.nan
    result = diagnostic_map(cube, 'spectral_support', chunk_pixels=1)
    expected = np.array([[1/3, np.nan, 2/3], [2/3, 2/3, 1/3]])
    np.testing.assert_allclose(result['data'], expected, equal_nan=True)
    assert result['metadata']['denominator'] == 3
    assert result['metadata']['valid_count'] == 5 and result['metadata']['invalid_processed_count'] == 1
    assert result['metadata']['units'] == 'dimensionless'
    assert 'not independent-band count' in result['metadata']['interpretation']


def test_rms_excludes_nonfinite_residuals_and_avoids_squaring_overflow():
    cube = residual_fixture()
    cube.reconstruction_residual[0, 0] = [3, 4, np.nan]
    cube.reconstruction_residual[0, 1] = [np.nan] * 3
    cube.reconstruction_residual[0, 2] = [1e308, -1e308, 1e308]
    result = diagnostic_map(cube, 'reconstruction_residual')
    assert result['data'][0, 0] == pytest.approx(np.sqrt(12.5))
    assert result['metadata']['used_counts'][0, 0] == 2
    assert np.isnan(result['data'][0, 1]) and not result['valid_mask'][0, 1]
    assert result['data'][0, 2] == pytest.approx(1e308)


def test_unsupported_spatial_region_stays_nan_in_both_maps():
    mapping = np.zeros((2, 3), int)
    mapping[0, 1] = -1
    bundle = response_fixture(region_map=mapping)
    raw, dark, _ = raw_fixture(bundle)
    cube = reconstruct_scan(raw, dark, bundle)
    for kind in ('spectral_support', 'reconstruction_residual'):
        result = diagnostic_map(cube, kind)
        assert np.isnan(result['data'][0, 1]) and not result['valid_mask'][0, 1]


def test_saved_residual_reopens_and_matches_source_operator_hash(tmp_path):
    path = tmp_path / 'signal.npy'
    with residual_fixture(output_path=path):
        pass
    with load_cube(path) as cube:
        result = diagnostic_map(cube, 'reconstruction_residual', chunk_pixels=2)
        np.testing.assert_allclose(result['data'], 1, atol=1e-12)
        assert result['metadata']['residual_association'] == 'matched saved source/operator/hash receipt'
        assert result['metadata']['residual_asset_sha256'] == cube.metadata['reconstruction']['residual_asset']['sha256']
        assert result['metadata']['spatial_grid'] == cube.metadata['spatial_grid']
    path.with_suffix('.npy.residual.npy').rename(tmp_path / 'released-residual.npy')


def test_cancelled_saved_reconstruction_maps_only_its_processed_prefix(tmp_path):
    bundle = response_fixture()
    raw, dark, _ = raw_fixture(bundle)
    stop = Event()
    path = tmp_path / 'partial-signal.npy'
    with reconstruct_scan(raw, dark, bundle, output_path=path, chunk_pixels=2,
                          stop=stop, progress=lambda completed, total: stop.set()) as partial:
        assert partial.metadata['completed_pixels'] == 2 and partial.metadata['partial']
    with load_cube(path) as partial:
        for kind in ('spectral_support', 'reconstruction_residual'):
            result = diagnostic_map(partial, kind, chunk_pixels=1)
            np.testing.assert_array_equal(result['valid_mask'], [[True, True, False], [False, False, False]])
            assert np.isnan(result['data'][~result['valid_mask']]).all()
            assert result['metadata']['source_partial'] is True
            assert result['metadata']['processed_pixels'] == 2 and result['metadata']['unprocessed_count'] == 4


@pytest.mark.parametrize('field,value', [('residual_file', '../other.npy'), ('operator_signature', 'different')])
def test_residual_wrong_source_association_is_rejected(tmp_path, field, value):
    path = tmp_path / 'signal.npy'
    with residual_fixture(output_path=path):
        pass
    with load_cube(path) as cube:
        cube.metadata['reconstruction'][field] = value
        with pytest.raises(ValueError, match='source|operator|adjacent'):
            diagnostic_map(cube, 'reconstruction_residual')


def test_residual_changed_bytes_are_rejected_even_with_same_shape(tmp_path):
    path = tmp_path / 'signal.npy'
    with residual_fixture(output_path=path):
        pass
    residual_path = path.with_suffix('.npy.residual.npy')
    altered = np.load(residual_path, mmap_mode='r+')
    altered[0, 0, 0] += 1
    altered.flush()
    altered._mmap.close()
    with load_cube(path) as cube:
        with pytest.raises(ValueError, match='hash receipt'):
            diagnostic_map(cube, 'reconstruction_residual')


def test_wrong_in_memory_state_count_is_rejected():
    cube = residual_fixture()
    cube.reconstruction_residual = cube.reconstruction_residual[..., :2]
    with pytest.raises(ValueError, match='state count'):
        diagnostic_map(cube, 'reconstruction_residual')


def test_older_adjacent_residual_without_hash_is_explicitly_unbound(tmp_path):
    path = tmp_path / 'signal.npy'
    with residual_fixture(output_path=path):
        pass
    with load_cube(path) as cube:
        cube.metadata['reconstruction'].pop('residual_asset')
        result = diagnostic_map(cube, 'reconstruction_residual')
        assert result['metadata']['residual_association'] == 'declared adjacent asset; no saved hash receipt'


def test_chunked_map_never_reads_a_full_source_cube():
    cube = residual_fixture()
    reads = []
    class Tracked(np.ndarray):
        def __getitem__(self, selection):
            assert isinstance(selection, tuple) and len(selection) == 3
            assert isinstance(selection[0], np.ndarray) and len(selection[0]) <= 2
            reads.append(len(selection[0]))
            return np.asarray(super().__getitem__(selection))
    cube.data = cube.data.view(Tracked)
    result = diagnostic_map(cube, 'spectral_support', chunk_pixels=2)
    assert reads == [2, 2, 2] and result['valid_mask'].all()


def test_same_size_detached_array_cannot_borrow_an_adjacent_residual(tmp_path):
    path = tmp_path / 'signal.npy'
    with residual_fixture(output_path=path):
        pass
    with load_cube(path) as original:
        detached = Cube(original.data.copy(), deepcopy(original.metadata), original.valid_mask.copy())
    with pytest.raises(ValueError, match='actual mapped reconstructed source'):
        diagnostic_map(detached, 'reconstruction_residual')


def test_wrong_saved_state_shape_is_rejected_and_mapping_released(tmp_path):
    path = tmp_path / 'signal.npy'
    with residual_fixture(output_path=path):
        pass
    residual_path = path.with_suffix('.npy.residual.npy')
    np.save(residual_path, np.ones((2, 3, 4)))
    with load_cube(path) as cube:
        cube.metadata['reconstruction'].pop('residual_asset')
        with pytest.raises(ValueError, match='state count'):
            diagnostic_map(cube, 'reconstruction_residual')
    residual_path.rename(tmp_path / 'released-wrong-shape.npy')


def test_saved_receipt_cannot_be_rebound_to_other_input_identities(tmp_path):
    path = tmp_path / 'signal.npy'
    with residual_fixture(output_path=path):
        pass
    with load_cube(path) as cube:
        cube.metadata['signal_lineage']['input_source_ids'] = ['other input']
        with pytest.raises(ValueError, match='source/operator/hash receipt'):
            diagnostic_map(cube, 'reconstruction_residual')


def test_residual_change_during_map_is_rejected(tmp_path, monkeypatch):
    import hyperlab.spectroscopy.diagnostics as module
    path = tmp_path / 'signal.npy'
    with residual_fixture(output_path=path):
        pass
    original_hash, calls = module._sha256, []
    def changing_hash(residual_path):
        if calls:
            with residual_path.open('r+b') as stream:
                stream.seek(-1, 2)
                byte = stream.read(1)
                stream.seek(-1, 2)
                stream.write(bytes([byte[0] ^ 1]))
        calls.append(True)
        return original_hash(residual_path)
    monkeypatch.setattr(module, '_sha256', changing_hash)
    with load_cube(path) as cube:
        with pytest.raises(ValueError, match='changed during'):
            diagnostic_map(cube, 'reconstruction_residual')


def test_corrected_factor_uses_its_preserved_grid_for_support_only():
    from hyperlab.spectroscopy.reflectance import reflectance_corrected
    bundle = response_fixture()
    sample, ds, _ = raw_fixture(bundle)
    white, dw, _ = raw_fixture(bundle, role='white')
    factor = reflectance_corrected(reconstruct_scan(sample, ds, bundle), reconstruct_scan(white, dw, bundle))
    result = diagnostic_map(factor, 'spectral_support')
    np.testing.assert_array_equal(result['data'], 1)
    assert result['metadata']['spatial_grid'] == factor.metadata['spatial_grid']
    with pytest.raises(ValueError, match='reconstructed source'):
        diagnostic_map(factor, 'reconstruction_residual')


@pytest.mark.parametrize('kind', ['spectral_support', 'reconstruction_residual'])
def test_diagnostic_rejects_raw_frames_and_unknown_processed_prefix(kind):
    with pytest.raises(ValueError, match='documented spectral'):
        diagnostic_map(Cube(np.ones((2, 2, 1))), kind)
    cube = residual_fixture()
    cube.metadata.update(completed=False, partial=True, completed_pixels=None)
    with pytest.raises(ValueError, match='processed-pixel prefix'):
        diagnostic_map(cube, kind)
