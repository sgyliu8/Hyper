"""Original frame receipt dimensions survive HWK analysis and saved products."""
from copy import deepcopy

import numpy as np
import pytest

from hyperlab.acquisition.frame import Frame
from hyperlab.acquisition.readiness import measurement_readiness
from hyperlab.experiment_metadata import source_fingerprint
from hyperlab.io import Cube, load_cube, save_cube


def frame(declared_shape, *, color=False):
    data = np.zeros((3, 4, 3) if color else (3, 4), np.uint16)
    metadata = {'data_level': 'raw_frame', 'units': 'DN',
        'pixel_format': 'RGB12' if color else 'BayerRG12', 'effective_bits': 12,
        'axis_order': 'HWC' if color else 'HW',
        'buffer_complete': True, 'valid': True, 'session_id': 'synthetic-receipt-geometry',
        'stream_epoch': 1, 'sequence': 2, 'host_utc': '2026-09-06T00:00:00+00:00',
        'synthetic': True, 'acquisition_source': 'SYNTHETIC'}
    if declared_shape is not None:
        metadata['shape'] = declared_shape
    return Frame(data, metadata)


@pytest.mark.parametrize('declared_shape,color,status', [
    ([3, 4], False, 'PASS'), ([3, 4, 3], True, 'PASS'),
    ([99, 99], False, 'FAIL'), ([3, 4], True, 'FAIL'),
    (None, False, 'UNKNOWN'), (None, True, 'UNKNOWN'),
    ([True, 4], False, 'FAIL'), ('3,4', False, 'FAIL')])
def test_frame_and_wrapper_use_original_shape_evidence(declared_shape, color, status):
    original = frame(declared_shape, color=color)
    metadata = deepcopy(dict(original.metadata))
    cube = Cube(original.data if color else original.data[..., None], dict(original.metadata))
    before = deepcopy(cube.metadata)
    for source in (original, cube):
        facts = measurement_readiness(source)
        assert facts['frame_received']['status'] == status
        assert facts['frame_received']['declared_frame_shape'] == original.metadata.get('shape')
        assert facts['frame_received']['declared_shape_matches'] is (
            None if status == 'UNKNOWN' else status == 'PASS')
        assert facts['scene_usable_for_selected_task']['status'] == 'UNKNOWN'
        assert facts['reference_qualified']['status'] == 'UNKNOWN'
    assert dict(original.metadata) == metadata
    assert cube.metadata == before and 'recorded_frame_shape' not in cube.metadata
    assert cube.metadata['shape'] == list(cube.data.shape)
    assert not original.data.flags.writeable


@pytest.mark.parametrize('suffix', ['.npy', '.npz', '.hdr'])
@pytest.mark.parametrize('declared_shape,status', [([3, 4], 'PASS'), ([99, 99], 'FAIL'), (None, 'UNKNOWN')])
def test_new_cube_artifact_keeps_receipt_geometry_without_mutating_source(tmp_path, suffix, declared_shape, status):
    original = frame(declared_shape)
    cube = Cube(original.data[..., None], dict(original.metadata))
    before = source_fingerprint(cube)
    path = save_cube(cube, tmp_path / ('saved' + suffix))
    assert source_fingerprint(cube) == before
    with load_cube(path) as replay:
        facts = measurement_readiness(replay)
        assert facts['frame_received']['status'] == status
        assert facts['frame_received']['declared_frame_shape'] == declared_shape
        assert replay.metadata['recorded_frame_shape'] == declared_shape
        np.testing.assert_array_equal(replay.data, cube.data)


def test_explicit_unknown_receipt_is_not_replaced_by_normalized_shape():
    original = frame([3, 4])
    metadata = dict(original.metadata, shape=[3, 4, 1], recorded_frame_shape=None)
    cube = Cube(original.data[..., None], metadata)
    assert measurement_readiness(cube)['frame_received']['status'] == 'UNKNOWN'


def test_legacy_raw_file_shape_is_kept_outside_metadata_hash(tmp_path):
    import json
    original = frame([99, 99])
    path = tmp_path / 'existing.npy'
    np.save(path, original.data, allow_pickle=False)
    sidecar = path.with_suffix('.npy.json')
    sidecar.write_text(json.dumps(dict(original.metadata)), encoding='utf-8')
    before = path.read_bytes(), sidecar.read_bytes()
    with load_cube(path) as cube:
        fingerprint = source_fingerprint(cube)
        metadata = deepcopy(cube.metadata)
        assert measurement_readiness(cube)['frame_received']['status'] == 'FAIL'
        assert cube.metadata == metadata and 'recorded_frame_shape' not in cube.metadata
        assert source_fingerprint(cube) == fingerprint
    assert (path.read_bytes(), sidecar.read_bytes()) == before
