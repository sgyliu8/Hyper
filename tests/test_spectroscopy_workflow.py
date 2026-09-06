"""File-based SYNTHETIC workflow checks; no hardware or physical acceptance."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import threading

import numpy as np
import pytest

from hyperlab.io import Cube, load_cube, save_cube
from hyperlab.spectroscopy.example import generate_example
from hyperlab.spectroscopy.response import load_response
from hyperlab.spectroscopy.workflow import process_spectroscopy


@pytest.fixture(scope='module')
def example(tmp_path_factory):
    return generate_example(tmp_path_factory.mktemp('spectroscopy')/'example')


def process(example, directory, **kwargs):
    return process_spectroscopy(example['raw']['sample'], example['raw']['white'], directory,
        response_path=example['response'], dark_sample_path=example['raw']['dark-sample'],
        dark_white_path=example['raw']['dark-white'], reference_csv=example['reference_csv'], **kwargs)


def test_saved_scan_response_ratio_and_roi_recover_known_synthetic_factor(example):
    assert example['origin'] == 'SYNTHETIC' and example['hardware_validation'] == 'NOT_TESTED'
    for role, path in example['raw'].items():
        assert example['scans'][role] == dict(completed=True, accepted=16, durable=16, unpersisted=0)
        with load_cube(path) as raw:
            assert raw.shape == (32, 48, 16) and raw.wavelengths is None
            assert raw.metadata['acquisition_source'] == 'SYNTHETIC'
            assert raw.metadata['data_level'] == 'raw_scan' and raw.metadata['units'] == 'DN'
            if role.startswith('dark'):
                assert raw.metadata['measurement_context']['light_blocked'] is True
    with load_cube(example['product']) as result, load_cube(example['expected_factor']) as truth:
        assert truth.metadata['data_level'] == 'reflectance_cube'
        np.testing.assert_allclose(result.data, truth.data, rtol=1e-12, atol=1e-14)
        assert result.valid_mask.all() and result.metadata['completed'] is True
        assert result.metadata['acquisition_source'] == 'SYNTHETIC'
        assert result.metadata['reflectance_kind'] == 'reference-calibrated'
        assert result.metadata['uncertainty']['status'] == 'not_computed'
        for item in example['numerical']['roi']:
            x0, y0, x1, y1 = item['rect']
            values = truth.data[y0:y1, x0:x1]
            np.testing.assert_allclose(item['mean'], values.mean(axis=(0, 1)), atol=1e-14)
            np.testing.assert_allclose(item['spatial_sd'], values.std(axis=(0, 1)), atol=1e-14)
            assert item['used_count'] == [(x1-x0)*(y1-y0)] * 12
    assert [item['color'] for item in example['numerical']['roi']] == ['#c47a28', '#2478b5', '#42907b']
    assert len(example['numerical']['integral']) == 3
    assert all(item['integral_units'] == 'dimensionless*nm' for item in example['numerical']['integral'])
    full_integral = json.loads(Path(example['roi_integral']).read_text())
    assert full_integral['metadata']['source_provenance']['acquisition_source'] == 'SYNTHETIC'


def test_finite_source_characterization_and_noise_match_independent_linear_oracle(example):
    bundle = load_response(example['response'])
    A, H = bundle['A'][0], bundle['characterization_H']
    assert np.linalg.matrix_rank(A) == 12 and np.linalg.matrix_rank(H) == 12
    assert np.count_nonzero(H > .05) > H.shape[0]
    assert not np.allclose(H, np.eye(12))
    with load_cube(example['raw']['sample']) as sample, load_cube(example['raw']['sample-noisy']) as noisy:
        perturbation = (noisy.data - sample.data).reshape(-1, 16)
    # Independent normal-equation oracle; production uses augmented least squares.
    delta = np.linalg.solve(A.T @ A, A.T @ perturbation.T).T.reshape(32, 48, 12)
    with load_cube(example['product']) as clean, load_cube(example['noisy_product']) as noisy:
        with load_cube(Path(example['directory'])/'clean'/'white-signal.npy') as white:
            reference = np.loadtxt(example['reference_csv'], delimiter=',', skiprows=1)[:, 1]
            np.testing.assert_allclose(noisy.data-clean.data, delta*reference/white.data, atol=1e-13)
    assert 0 < example['numerical']['noisy_rmse'] < .02


def test_file_workflow_callbacks_reach_complete_and_leave_originals_unchanged(example, tmp_path):
    paths = [Path(value) for value in example['raw'].values()]
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    events = []
    report = process(example, tmp_path/'complete', progress=events.append)
    assert report['completed'] and report['phase'] == 'COMPLETE'
    for name in ('RECONSTRUCT_SAMPLE', 'RECONSTRUCT_WHITE'):
        ticks = [event for event in events if event['phase'] == name and 'completed_pixels' in event]
        assert ticks[-1]['completed_pixels'] == ticks[-1]['total_pixels'] == 1536
    assert events[-1]['phase'] == 'COMPLETE'
    assert before == [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]


@pytest.mark.parametrize('phase,partial_name', [('RECONSTRUCT_SAMPLE', 'sample-signal.npy'),
                                             ('RECONSTRUCT_WHITE', 'white-signal.npy')])
def test_callback_cancellation_preserves_exact_completed_prefix(example, tmp_path, monkeypatch, phase, partial_name):
    import hyperlab.spectroscopy.response as module
    original = module.reconstruct_scan
    monkeypatch.setattr(module, 'reconstruct_scan', lambda *args, **kwargs:
                        original(*args, **kwargs, chunk_pixels=100))
    stop = threading.Event()
    def progress(event):
        if event['phase'] == phase and event.get('completed_pixels') == 100:
            stop.set()
    directory = tmp_path/'cancelled'
    with pytest.raises(InterruptedError, match='cancelled'):
        process(example, directory, stop=stop, progress=progress)
    report = json.loads((directory/'processing.json').read_text())
    assert report['phase'] == 'CANCELLED' and report['partial'] and not report['completed']
    assert not (directory/'reflectance.npy').exists()
    with load_cube(directory/partial_name) as partial:
        assert partial.metadata['completed_pixels'] == 100
        assert partial.metadata['partial'] and not partial.metadata['completed']
        assert partial.valid_mask.reshape(-1, 12)[:100].all()
        assert not partial.valid_mask.reshape(-1, 12)[100:].any()
        assert np.isnan(partial.data.reshape(-1, 12)[100:]).all()
    if phase == 'RECONSTRUCT_WHITE':
        with load_cube(directory/'sample-signal.npy') as sample:
            assert sample.metadata['completed'] and sample.valid_mask.all()


def test_callback_failure_retains_failed_prefix_instead_of_completed_product(example, tmp_path, monkeypatch):
    import hyperlab.spectroscopy.response as module
    original = module.reconstruct_scan
    monkeypatch.setattr(module, 'reconstruct_scan', lambda *args, **kwargs:
                        original(*args, **kwargs, chunk_pixels=100))
    def progress(event):
        if event.get('completed_pixels') == 100:
            raise OSError('SYNTHETIC progress sink failure')
    directory = tmp_path/'failed'
    with pytest.raises(OSError, match='progress sink'):
        process(example, directory, progress=progress)
    report = json.loads((directory/'processing.json').read_text())
    assert report['phase'] == 'FAILED' and report['partial'] and not report['completed']
    with load_cube(directory/'sample-signal.npy') as partial:
        assert partial.metadata['completed_pixels'] == 100 and partial.metadata['partial']
        assert 'progress sink' in partial.metadata['reconstruction']['error']
    assert not (directory/'reflectance.npy').exists()


def test_wrong_state_negative_receipt_and_reference_context_mismatch_are_preserved(example, tmp_path):
    rejection = example['wrong_state']
    report = json.loads(Path(rejection['receipt']).read_text())
    assert rejection['rejected'] and 'state identity/order mismatch' in report['error']
    assert report['phase'] == 'FAILED' and not report['completed']
    with load_cube(example['raw']['white']) as white:
        meta = deepcopy(white.metadata)
        meta['measurement_context']['illumination_id'] = 'SYNTHETIC changed lamp'
        wrong_white = save_cube(Cube(np.array(white.data), meta), tmp_path/'wrong-white.npy')
    directory = tmp_path/'mismatch'
    with pytest.raises(ValueError, match='illumination_id'):
        process_spectroscopy(example['raw']['sample'], wrong_white, directory,
            response_path=example['response'], dark_sample_path=example['raw']['dark-sample'],
            dark_white_path=example['raw']['dark-white'])
    assert not (directory/'reflectance.npy').exists()
    for name in ('sample-signal.npy', 'white-signal.npy'):
        with load_cube(directory/name) as intermediate:
            assert intermediate.metadata['completed']
    assert json.loads((directory/'processing.json').read_text())['phase'] == 'FAILED'


def test_existing_example_is_preserved(example):
    receipt = Path(example['directory'])/'example.json'
    before = receipt.read_bytes()
    with pytest.raises(FileExistsError):
        generate_example(example['directory'])
    assert receipt.read_bytes() == before


def test_actual_cli_roi_keeps_units_wavelengths_spatial_sd_and_counts(example, tmp_path, capsys):
    from hyperlab.__main__ import main
    output = tmp_path/'roi.csv'
    code = main(['spectroscopy', 'roi', example['product'], '--roi', '4', '4', '16', '16',
                 '--support', 'common', '--output', str(output)])
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and output.is_file()
    assert result['units'] == 'dimensionless'
    assert result['count'] == [144] * 12
    np.testing.assert_allclose(result['mean'], example['numerical']['roi'][0]['mean'], atol=1e-14)
    np.testing.assert_allclose(result['spatial_sd'], example['numerical']['roi'][0]['spatial_sd'], atol=1e-14)
    np.testing.assert_allclose(result['wavelengths'], np.linspace(450., 900., 12))
