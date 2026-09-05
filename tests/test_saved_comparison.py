import json
from pathlib import Path
import numpy as np
import pytest
from hyperlab.experiments import compare_saved_frames
from hyperlab.io import Cube, save_cube


def saved(path, data=None, *, level='raw_frame', labels=None, exposure=1000, known=True, mask=None):
    if data is None:
        data = np.full((3, 4, 1), 10, np.uint16)
    metadata = {'data_level': level, 'data_source': 'SYNTHETIC', 'acquisition_source': 'SYNTHETIC',
                'pixel_format': 'RGB8' if labels else 'Mono12', 'effective_bits': 12,
                'units': 'DN', 'model': 'synthetic camera', 'serial': 'synthetic identity',
                'readback_settings': {'PixelFormat': 'RGB8' if labels else 'Mono12',
                    'ExposureTime': exposure, 'Gain': 0, 'ExposureAuto': 'Off', 'GainAuto': 'Off',
                    'BalanceWhiteAuto': 'Off', 'GammaEnable': False, 'Gamma': 1,
                    'LUTEnable': False, 'BlackLevel': 0, 'BlackLevelAuto': 'Off'}}
    if labels:
        metadata['channel_labels'] = labels
    if not known:
        metadata['readback_settings'].pop('ExposureTime')
    save_cube(Cube(data, metadata, mask), path)
    return path


def test_saved_comparison_roi_match_and_source_provenance(tmp_path):
    first = saved(tmp_path / 'first.npy')
    second = saved(tmp_path / 'second.npy', np.full((3, 4, 1), 20, np.uint16))
    report = compare_saved_frames([first, second], rectangle=(1, 1, 4, 3))
    assert report['registration'] == 'NOT_VERIFIED'
    assert report['matching_settings']['status'] == 'MATCH'
    assert report['rectangle'] == [1, 1, 4, 3]
    assert report['files'][0]['summary']['per_channel']['mean'] == [10]
    assert report['files'][1]['summary']['per_channel']['mean'] == [20]
    assert report['files'][0]['summary']['per_channel']['count'] == [6]
    assert report['files'][0]['source_provenance']['serial'] == 'synthetic identity'
    assert report['paths'] == [str(first.resolve()), str(second.resolve())]
    assert all(item['acquisition_source'] == 'SYNTHETIC' for item in report['files'])
    json.dumps(report, allow_nan=False)
    first.rename(tmp_path / 'first-closed.npy')
    second.rename(tmp_path / 'second-closed.npy')


@pytest.mark.parametrize('known,exposure,status', [(True, 2000, 'MISMATCH'), (False, 1000, 'UNKNOWN')])
def test_saved_comparison_settings_not_overclaimed(tmp_path, known, exposure, status):
    first = saved(tmp_path / 'first.npy')
    second = saved(tmp_path / 'second.npy', known=known, exposure=exposure)
    report = compare_saved_frames([first, second])
    assert report['matching_settings']['status'] == status
    assert report['registration'] == 'NOT_VERIFIED'
    assert report['rectangle'] == [0, 0, 4, 3]


def test_saved_comparison_uses_shared_quality_policy_and_strict_json(tmp_path):
    data = np.array([[[0.0], [100.0]], [[4095.0], [np.nan]]])
    first = saved(tmp_path / 'raw.npy', data)
    second = saved(tmp_path / 'derived.npy', data, level='derived_frame')
    diagnostic = compare_saved_frames([first, second])
    quantitative = compare_saved_frames([first, second], policy='quantitative')
    assert diagnostic['files'][0]['summary']['valid'] == 3
    assert quantitative['files'][0]['summary']['valid'] == 2
    assert quantitative['files'][0]['summary']['saturated'] == 1
    masked_first = saved(tmp_path / 'masked-first.npy', data, mask=np.zeros(data.shape, bool))
    masked_second = saved(tmp_path / 'masked-second.npy', data, mask=np.zeros(data.shape, bool))
    empty = compare_saved_frames([masked_first, masked_second])
    assert empty['files'][0]['summary']['per_channel']['mean'] == [None]
    assert empty['files'][0]['summary']['per_channel']['std'] == [None]
    assert 'NaN' not in json.dumps(empty, allow_nan=False)


@pytest.mark.parametrize('problem', ['geometry', 'channels', 'level', 'labels'])
def test_saved_comparison_rejects_incompatible_inputs_and_closes(tmp_path, problem):
    first = saved(tmp_path / 'first.npy')
    if problem == 'geometry':
        second = saved(tmp_path / 'second.npy', np.ones((2, 2, 1), np.uint16))
    elif problem == 'channels':
        second = saved(tmp_path / 'second.npy', np.ones((3, 4, 3), np.uint16), labels=['R', 'G', 'B'])
    elif problem == 'level':
        second = saved(tmp_path / 'second.npy', level='raw_scan')
    else:
        first = saved(tmp_path / 'color-first.npy', np.ones((3, 4, 3), np.uint16), labels=['R', 'G', 'B'])
        second = saved(tmp_path / 'second.npy', np.ones((3, 4, 3), np.uint16), labels=['B', 'G', 'R'])
    with pytest.raises(ValueError):
        compare_saved_frames([first, second])
    first.rename(tmp_path / 'closed-first.npy')
    second.rename(tmp_path / 'closed-second.npy')


def test_saved_comparison_requires_two_distinct_files_and_valid_rectangle(tmp_path):
    first, second = saved(tmp_path / 'one.npy'), saved(tmp_path / 'two.npy')
    with pytest.raises(ValueError, match='exactly two'):
        compare_saved_frames([first])
    with pytest.raises(ValueError, match='distinct'):
        compare_saved_frames([first, first])
    with pytest.raises(ValueError, match='outside'):
        compare_saved_frames([first, second], rectangle=(0, 0, 99, 99))


def test_first_mapping_closed_when_second_load_fails(tmp_path, monkeypatch):
    import hyperlab.io
    first, second = saved(tmp_path / 'one.npy'), saved(tmp_path / 'two.npy')
    original = hyperlab.io.load_cube
    opened = []
    def load(path):
        if Path(path) == second.resolve():
            raise OSError('second file failed')
        cube = original(path)
        opened.append(cube)
        return cube
    monkeypatch.setattr(hyperlab.io, 'load_cube', load)
    with pytest.raises(OSError, match='second file'):
        compare_saved_frames([first, second])
    assert opened[0].data._mmap.closed
