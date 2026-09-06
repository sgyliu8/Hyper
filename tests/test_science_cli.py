"""Offline CLI reaches the same frozen ROI mathematics without native runtimes."""
import builtins
import csv
import json

import numpy as np
import pytest

from hyperlab.__main__ import main
from hyperlab.io import Cube, load_cube, save_cube


@pytest.fixture(autouse=True)
def no_camera_imports(monkeypatch):
    original_import = builtins.__import__

    def reject_live_import(name, *args, **kwargs):
        if name == 'hyperlab.adapters.gentl' or name.split('.')[0] in {'harvesters', 'genicam', 'serial', 'winreg'}:
            raise AssertionError(f'Offline analysis attempted native import: {name}')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', reject_live_import)


def spectral_file(tmp_path, values, wavelengths, *, level='spectral_cube', units='nm'):
    data = np.asarray(values, dtype=np.float64)
    if data.ndim == 1:
        data = data[None, None, :]
    cube = Cube(data, {'data_level': level, 'wavelengths': wavelengths, 'wavelength_units': units,
        'wavelength_source': 'Analytical CLI fixture, not camera calibration',
        'data_source': 'SYNTHETIC', 'synthetic': True,
        'units': 'dimensionless' if level == 'reflectance_cube' else 'DN'})
    path = tmp_path/'spectrum.npy'
    save_cube(cube, path)
    return path


def strict_payload(capsys):
    captured = capsys.readouterr()
    assert not captured.err

    def reject_constant(value):
        raise AssertionError(f'Non-JSON number in CLI output: {value}')

    return json.loads(captured.out, parse_constant=reject_constant)


def test_roi_cli_selected_common_support_csv_and_strict_nulls(tmp_path, capsys):
    path = tmp_path/'source.npy'
    save_cube(Cube(np.array([[[1., 10, 100], [np.nan, 20, 200]]])), path)
    output = tmp_path/'roi.csv'
    assert main(['analyze', str(path), 'roi', '--bands', '0', '1', '--support', 'common',
                 '--output', str(output)]) == 0
    result = strict_payload(capsys)
    assert result['mean'] == result['median'] == [1, 10, None]
    assert result['count'] == [1, 1, 0] and result['counts']['valid'] == [1, 2, 2]
    assert result['support_excluded_count'] == [0, 1, 0]
    with output.open(encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    assert rows[1]['valid_count'] == '1' and rows[1]['policy_valid_count'] == '2'
    assert rows[2]['selection_excluded_count'] == '2'


def test_pair_cli_rgb_direction_and_explicit_unavailable_angle(tmp_path, capsys):
    path, output = tmp_path/'rgb.npy', tmp_path/'pairs.json'
    save_cube(Cube(np.array([[[1, 2, 4], [3, 5, 9]]], np.uint8),
        {'data_level': 'raw_frame', 'channel_labels': ['R', 'G', 'B'], 'pixel_format': 'RGB8'}), path)
    args = ['analyze', str(path), 'pairs', '--roi', '1', '0', '2', '1',
            '--reference-roi', '0', '0', '1', '1', '--output', str(output)]
    assert main(args) == 0
    result = strict_payload(capsys)
    pair = result['pairs'][0]
    assert pair['target'] == 'Target ROI' and pair['reference'] == 'Reference ROI'
    assert pair['bias'] == pytest.approx(10/3) and pair['rmse'] == pytest.approx(np.sqrt(38/3))
    assert pair['correlation'] == pytest.approx(1) and pair['angle'] is None
    assert 'not a spectral' in pair['unavailable']['angle']
    assert result['metadata']['correlation_label'] == 'Channel correlation'
    assert json.loads(output.read_text()) == result
    original = output.read_bytes()
    assert main(args) == 2
    assert capsys.readouterr().err and output.read_bytes() == original


def test_pair_cli_requires_both_rectangles_and_rejects_non_json_output(tmp_path, capsys):
    path = spectral_file(tmp_path, [1, 2, 3], [500, 510, 520])
    assert main(['analyze', str(path), 'pairs']) == 2
    assert '--reference-roi' in capsys.readouterr().err
    assert main(['analyze', str(path), 'pairs', '--output', str(tmp_path/'bad.npy')]) == 2
    assert '.json' in capsys.readouterr().err
    assert not (tmp_path/'bad.npy').exists()


@pytest.mark.parametrize('operation,expected,units', [
    ('smooth', .04, 'DN'), ('derivative1', .04, 'DN/nm'), ('derivative2', .02, 'DN/nm^2')])
def test_cli_local_polynomial_real_coordinates_and_invalid_edges(tmp_path, capsys, operation, expected, units):
    wavelengths = np.array([500, 501, 502, 510, 511])
    path = spectral_file(tmp_path, ((wavelengths-500)/10)**2, wavelengths)
    output = tmp_path/f'{operation}.json'
    assert main(['analyze', str(path), operation, '--support', 'common', '--summary', 'median',
                 '--window', '5', '--degree', '2', '--output', str(output)]) == 0
    result = strict_payload(capsys)
    assert result['curves'][0]['y'] == [None, None, pytest.approx(expected), None, None]
    assert result['curves'][0]['valid_mask'] == [False, False, True, False, False]
    assert result['metadata']['units'] == units and result['metadata']['summary'] == 'median'
    assert result['metadata']['aggregation_order'] == 'summary_then_transform'
    assert result['metadata']['method'] == 'Local polynomial'
    assert json.loads(output.read_text()) == result


def test_cli_integral_descending_um_selected_interval(tmp_path, capsys):
    path = spectral_file(tmp_path, [.9, .6, .3, .2], [.6, .54, .51, .5], units='um')
    assert main(['analyze', str(path), 'integral', '--support', 'common', '--bands', '1', '2', '3']) == 0
    result = strict_payload(capsys)
    assert result['metadata']['feature_indices'] == [3, 2, 1]
    assert result['metadata']['actual_interval_nm'] == [500, 540]
    assert result['metadata']['original_wavelength_units'] == 'um'
    features = result['curves'][0]['features']
    assert features['integral'] == pytest.approx(16) and features['integral_units'] == 'DN*nm'
    assert features['interval_mean'] == pytest.approx(.4)


def test_cli_continuum_exposes_physical_interval_and_sampled_minimum(tmp_path, capsys):
    path = spectral_file(tmp_path, [.8, .736, 1.2], [500, 560, 700], level='reflectance_cube')
    assert main(['analyze', str(path), 'continuum', '--support', 'common']) == 0
    curve = strict_payload(capsys)['curves'][0]
    assert curve['y'] == pytest.approx([0, .2, 0])
    assert curve['features']['depth_area_nm'] == pytest.approx(20)
    assert curve['features']['sampled_minimum_nm'] == 560
    assert curve['features']['sampled_minimum_index'] == 1


def test_cli_spectral_common_support_and_gap_contract(tmp_path, capsys):
    path = spectral_file(tmp_path, [1, 2, 3, 4, 5], [500, 510, 520, 530, 540])
    assert main(['analyze', str(path), 'integral']) == 2
    assert '--support common' in capsys.readouterr().err
    assert main(['analyze', str(path), 'integral', '--support', 'common', '--bands', '0', '2', '3']) == 2
    assert 'contiguous' in capsys.readouterr().err
    assert main(['analyze', str(path), 'smooth', '--support', 'common', '--window', '4']) == 2
    assert 'odd' in capsys.readouterr().err
    assert main(['analyze', str(path), 'continuum', '--support', 'common']) == 2
    assert 'reflectance' in capsys.readouterr().err


def test_cli_rgb_cannot_become_wavelength_signal(tmp_path, capsys):
    path = tmp_path/'rgb.npy'
    save_cube(Cube(np.ones((1, 1, 3), np.uint8),
        {'data_level': 'raw_frame', 'channel_labels': ['R', 'G', 'B']}), path)
    assert main(['analyze', str(path), 'integral', '--support', 'common']) == 2
    assert 'wavelengths' in capsys.readouterr().err


def test_cli_normalized_difference_threshold_and_saved_mask(tmp_path, capsys):
    path, output = tmp_path/'source.npy', tmp_path/'contrast.npy'
    save_cube(Cube(np.array([[[3., 1], [1, -1], [1, 0]]]), {'units': 'DN'}), path)
    assert main(['analyze', str(path), 'normalized-difference', '--bands', '0', '1',
                 '--minimum-denominator', '2', '--output', str(output)]) == 0
    result = strict_payload(capsys)
    assert result['metadata']['minimum_denominator'] == 2
    with load_cube(output) as product:
        assert product.data[0, 0, 0] == pytest.approx(.5)
        assert np.isnan(product.data[0, 1:, 0]).all()
        assert product.valid_mask.tolist() == [[True, False, False]]
        assert product.metadata['data_level'] == 'derived_map'


def test_cli_reference_rmse_median_subset_exports_complete_reference_provenance(tmp_path, capsys):
    path, output = tmp_path/'source.npy', tmp_path/'reference.npy'
    save_cube(Cube(np.array([[[1., 3, 99], [3, 5, 99], [10, 12, 99], [5, 7, 99]]]), {'units': 'DN'}), path)
    args = ['analyze', str(path), 'reference-rmse', '--reference-roi', '0', '0', '3', '1',
            '--summary', 'median', '--bands', '0', '1', '--output', str(output)]
    assert main(args) == 2
    assert '--support common' in capsys.readouterr().err
    assert main([*args, '--support', 'common']) == 0
    result = strict_payload(capsys)
    assert result['metadata']['reference_rect'] == [0, 0, 3, 1]
    assert result['metadata']['reference_counts'] == [3, 3, 0]
    assert result['metadata']['reference_summary'] == 'median'
    assert result['metadata']['reference_support'] == 'common'
    with load_cube(output) as product:
        assert product.data[0, :, 0].tolist() == pytest.approx([2, 0, 7, 2])
        assert product.valid_mask.all()
        assert product.metadata['feature_indices'] == [0, 1]


def test_cli_reference_rejects_empty_common_support(tmp_path, capsys):
    path = tmp_path/'source.npy'
    save_cube(Cube(np.array([[[1., np.nan], [np.nan, 2]]])), path)
    target = tmp_path/'empty.npy'
    assert main(['analyze', str(path), 'reference-rmse', '--support', 'common', '--output', str(target)]) == 2
    assert 'finite' in capsys.readouterr().err and not target.exists()
