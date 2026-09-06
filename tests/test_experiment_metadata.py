import hashlib
import json

import numpy as np
import pytest

from hyperlab.experiment_metadata import (compute_pinned, load_annotation, normalize_annotations,
    save_annotation, source_fingerprint, write_analysis_manifest)
from hyperlab.io import Cube, load_cube, save_cube


def raw_cube():
    return Cube(np.arange(36, dtype=np.uint16).reshape(3, 4, 3),
        {'data_level': 'raw_frame', 'channel_labels': ['R', 'G', 'B'],
         'pixel_format': 'RGB8', 'units': 'DN', 'data_source': 'SYNTHETIC'},
        np.ones((3, 4), dtype=bool))


def file_hashes(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.iterdir() if path.is_file()}


def test_annotations_unknowns_zero_and_temperature_meaning():
    values = normalize_annotations({'specimen_id': '  coupon A  ', 'substrate': 'unknown',
        'temperature_value': '0', 'temperature_unit': 'degC',
        'temperature_meaning': 'setpoint', 'dwell_seconds': 0, 'notes': '   '})
    assert values['specimen_id'] == 'coupon A'
    assert values['temperature_value'] == values['dwell_seconds'] == 0
    assert values['temperature_meaning'] == 'setpoint'
    assert values['substrate'] is None and values['notes'] is None
    assert values['coating_batch'] is None and values['reference_ids'] == []
    measured = normalize_annotations(dict(values, temperature_meaning='independent_measurement',
                                          temperature_reference_id='thermocouple log A'))
    assert measured['temperature_reference_id'] == 'thermocouple log A'


@pytest.mark.parametrize('values', [
    {'temperature_value': True, 'temperature_unit': 'degC', 'temperature_meaning': 'setpoint'},
    {'temperature_value': np.bool_(False), 'temperature_unit': 'K', 'temperature_meaning': 'setpoint'},
    {'dwell_seconds': False}, {'dwell_seconds': 'nan'}, {'dwell_seconds': np.inf},
    {'dwell_seconds': -1}, {'dwell_seconds': np.array(False)},
    {'temperature_value': np.array([20]), 'temperature_unit': 'degC', 'temperature_meaning': 'setpoint'},
    {'temperature_value': float('nan'), 'temperature_unit': 'degC', 'temperature_meaning': 'setpoint'},
    {'temperature_value': 20, 'temperature_unit': 'degC'},
    {'temperature_unit': 'K', 'temperature_meaning': 'owner_label'},
    {'temperature_value': 20, 'temperature_unit': 'degrees', 'temperature_meaning': 'setpoint'},
    {'temperature_value': 20, 'temperature_unit': 'degC', 'temperature_meaning': 'model_estimate'},
    {'temperature_value': 20, 'temperature_unit': 'degC', 'temperature_meaning': 'independent_measurement'},
    {'specimen_id': 12}, {'reference_ids': 'reference A'}, {'reference_ids': [False]},
    {'reference_ids': ['same', 'same']}, {'verified': True},
])
def test_annotations_reject_ambiguous_or_nonfinite_inputs(values):
    with pytest.raises(ValueError):
        normalize_annotations(values)


def test_fingerprint_matches_logical_noncontiguous_bytes_and_mask():
    cube = raw_cube()
    cube.data = cube.data[::-1, ::2, :]
    cube.valid_mask = cube.valid_mask[::-1, ::2]
    fingerprint = source_fingerprint(cube)
    assert fingerprint['array']['sha256'] == hashlib.sha256(cube.data.tobytes(order='C')).hexdigest()
    assert fingerprint['array']['shape'] == [3, 2, 3]
    assert fingerprint['valid_mask']['sha256'] == hashlib.sha256(cube.valid_mask.tobytes()).hexdigest()
    assert fingerprint['origin']['acquisition_source'] == 'SYNTHETIC'
    assert source_fingerprint(cube) == fingerprint
    cube.valid_mask[0, 0] = False
    assert source_fingerprint(cube)['source_id'] != fingerprint['source_id']


def test_fingerprint_array_iteration_obeys_buffer_limit(monkeypatch):
    import hyperlab.experiment_metadata as metadata
    data = np.arange(1200, dtype='>u2').reshape(20, 20, 3).transpose(1, 0, 2)[:, ::2]
    expected = hashlib.sha256(data.tobytes(order='C')).hexdigest()
    original = hashlib.sha256
    lengths = []
    class Digest:
        def __init__(self):
            self.digest = original()
        def update(self, value):
            lengths.append(len(value))
            self.digest.update(value)
        def hexdigest(self):
            return self.digest.hexdigest()
    monkeypatch.setattr(metadata, '_HASH_CHUNK_BYTES', 64)
    monkeypatch.setattr(metadata.hashlib, 'sha256', Digest)
    assert metadata._array_identity(data)['sha256'] == expected
    assert max(lengths) <= 64 and sum(lengths) == data.nbytes


@pytest.mark.parametrize('suffix', ['.npy', '.npz', '.hdr'])
def test_fingerprint_saved_assets_and_annotation_revisions_are_immutable(tmp_path, suffix):
    sources = tmp_path / 'sources'
    path = save_cube(raw_cube(), sources / ('source' + suffix))
    before = file_hashes(sources)
    with load_cube(path) as cube:
        first, first_path = save_annotation(tmp_path / 'annotations', cube, {'specimen_id': 'A'})
        first_bytes = first_path.read_bytes()
        second, second_path = save_annotation(tmp_path / 'annotations', cube,
            {'specimen_id': 'A', 'coating_batch': 'B'}, previous=first)
        assert first['kind'] == 'analyst_annotation'
        assert first['revision'] == 1 and first['supersedes'] is None
        assert second['revision'] == 2 and second['supersedes'] == first['annotation_id']
        assert first_path != second_path and first_path.read_bytes() == first_bytes
        assert load_annotation(first_path, cube) == first
        assert load_annotation(second_path, cube) == second
        roles = {entry['role'] for entry in first['source_fingerprint']['source_files']}
        assert ('header' if suffix == '.hdr' else 'data') in roles
        if suffix == '.hdr':
            assert 'data' in roles
        if suffix != '.npz':
            assert {'sidecar', 'mask'} <= roles
    assert file_hashes(sources) == before


@pytest.mark.parametrize('changed', ['data', 'metadata', 'mask'])
def test_same_path_replaced_source_is_rejected(tmp_path, changed):
    path = save_cube(raw_cube(), tmp_path / 'source.npy')
    with load_cube(path) as cube:
        previous, annotation_path = save_annotation(tmp_path / 'annotations', cube, {})
    if changed == 'data':
        np.save(path, np.zeros((3, 4, 3), dtype=np.uint16), allow_pickle=False)
    elif changed == 'metadata':
        sidecar = path.with_suffix('.npy.json')
        metadata = json.loads(sidecar.read_text(encoding='utf-8'))
        metadata['units'] = 'changed units'
        sidecar.write_text(json.dumps(metadata), encoding='utf-8')
    else:
        np.save(path.with_suffix('.npy.valid.npy'), np.zeros((3, 4), bool), allow_pickle=False)
    with load_cube(path) as replacement:
        with pytest.raises(ValueError, match='source'):
            load_annotation(annotation_path, replacement)
        with pytest.raises(ValueError, match='source'):
            save_annotation(tmp_path / 'annotations', replacement, {}, previous=previous)


def test_sidecar_byte_edit_and_loaded_metadata_edit_change_identity(tmp_path):
    path = save_cube(raw_cube(), tmp_path / 'source.npy')
    with load_cube(path) as cube:
        before = source_fingerprint(cube)
        sidecar = path.with_suffix('.npy.json')
        sidecar.write_text(sidecar.read_text(encoding='utf-8') + '\n', encoding='utf-8')
        assert source_fingerprint(cube)['source_id'] != before['source_id']
        cube.metadata['readback_settings'] = {'Gain': 0}
        current = source_fingerprint(cube)
        cube.metadata['readback_settings']['Gain'] = 1
        assert source_fingerprint(cube)['metadata_sha256'] != current['metadata_sha256']


def test_annotation_does_not_write_into_cube_or_accept_forged_revision(tmp_path):
    cube = raw_cube()
    cube.data.setflags(write=False)
    before = source_fingerprint(cube)
    record, path = save_annotation(tmp_path, cube, {'geometry_id': 'declared geometry'})
    assert source_fingerprint(cube) == before
    assert not cube.data.flags.writeable
    assert 'measurement_context' not in cube.metadata
    changed = dict(record, values=dict(record['values'], specimen_id='edited without revision'))
    path.write_text(json.dumps(changed), encoding='utf-8')
    with pytest.raises(ValueError, match='revision'):
        load_annotation(path, cube)


def test_manifest_hashes_only_direct_outputs_and_pins_annotation(tmp_path):
    cube = raw_cube()
    record, _ = save_annotation(tmp_path / 'annotations', cube, {'specimen_id': 'A'})
    output = tmp_path / 'analysis'
    output.mkdir()
    (output / 'series.csv').write_text('feature,value\nR,1\n', encoding='utf-8')
    (output / 'figure.svg').write_text('<svg/>', encoding='utf-8')
    unrelated = output / 'unrelated'
    unrelated.mkdir()
    (unrelated / 'private.txt').write_text('must not be crawled', encoding='utf-8')
    fingerprint = source_fingerprint(cube)
    recipe = {'operation': 'ROI comparison', 'feature_indices': [0, 1, 2],
              'used_counts': np.array([12, 12, 12]), 'unavailable_metric': np.nan}
    path = write_analysis_manifest(output, fingerprint, recipe, annotation=record)
    manifest = json.loads(path.read_text(encoding='utf-8'))
    assert manifest['status'] == 'COMPLETE'
    assert manifest['annotation'] == record and manifest['source_fingerprint'] == fingerprint
    assert manifest['recipe']['unavailable_metric'] is None
    assert manifest['recipe']['used_counts'] == [12, 12, 12]
    assert {item['path'] for item in manifest['outputs']} == {'series.csv', 'figure.svg'}
    for item in manifest['outputs']:
        assert item['sha256'] == hashlib.sha256((output / item['path']).read_bytes()).hexdigest()
    assert source_fingerprint(cube) == fingerprint
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_analysis_manifest(output, fingerprint, recipe)
    assert path.read_bytes() == before


def test_manifest_rejects_mismatched_annotation_and_empty_outputs(tmp_path):
    cube = raw_cube()
    record, _ = save_annotation(tmp_path / 'annotations', cube, {})
    output = tmp_path / 'analysis'
    output.mkdir()
    with pytest.raises(ValueError, match='output'):
        write_analysis_manifest(output, source_fingerprint(cube), {})
    (output / 'table.csv').write_text('value\n1\n', encoding='utf-8')
    cube.data[0, 0, 0] = 123
    with pytest.raises(ValueError, match='source'):
        write_analysis_manifest(output, source_fingerprint(cube), {}, annotation=record)
    assert not (output / 'analysis_manifest.json').exists()


def test_manifest_read_failure_preserves_outputs_without_success_record(tmp_path, monkeypatch):
    import hyperlab.experiment_metadata as metadata
    fingerprint = source_fingerprint(raw_cube())
    output = tmp_path / 'analysis'
    output.mkdir()
    table = output / 'series.csv'
    table.write_text('value\n1\n', encoding='utf-8')
    original = table.read_bytes()
    def fail_read(path):
        raise OSError('injected output read failure')
    monkeypatch.setattr(metadata, '_file_identity', fail_read)
    with pytest.raises(OSError, match='output read failure'):
        write_analysis_manifest(output, fingerprint, {'operation': 'ROI statistics'})
    assert table.read_bytes() == original
    assert not (output / 'analysis_manifest.json').exists()


def test_nonfinite_source_metadata_is_hashed_without_promotion_to_annotation(tmp_path):
    cube = raw_cube()
    cube.metadata['unknown_readback'] = np.nan
    fingerprint = source_fingerprint(cube)
    json.dumps(fingerprint, allow_nan=False)
    cube.metadata['unknown_readback'] = None
    assert source_fingerprint(cube)['metadata_sha256'] != fingerprint['metadata_sha256']


def test_sequence_frame_hashes_full_container_and_durable_manifest(tmp_path):
    from hyperlab.acquisition.sequence import SequenceWriter, load_sequence
    values = np.arange(12, dtype=np.uint16).reshape(3, 4)
    with SequenceWriter(tmp_path / 'sequence', values.shape, values.dtype, 4,
                        metadata={'data_source': 'SYNTHETIC'}) as writer:
        writer.append(values, {'valid': True, 'sequence': 1})
        writer.append(values + 10, {'valid': True, 'sequence': 2})
    before = file_hashes(writer.directory)
    with load_sequence(writer.path) as sequence:
        frame = sequence.frame(0)
        cube = Cube(frame.data[:, :, None], dict(frame.metadata))
        fingerprint = source_fingerprint(cube)
    assets = {item['role']: item for item in fingerprint['source_files']}
    assert set(assets) == {'sequence_data', 'sequence_manifest'}
    assert assets['sequence_data']['sha256'] == before['sequence.npy']
    assert assets['sequence_manifest']['sha256'] == before['sequence.npy.json']
    assert cube.metadata['sequence_source']['container_provenance']['frame_count'] == 2
    assert cube.metadata['sequence_source']['container_provenance']['expected_frames'] == 4
    assert cube.metadata['sequence_source']['container_provenance']['partial'] is True
    record, annotation_path = save_annotation(tmp_path / 'annotations', cube, {})
    assert record['source_fingerprint'] == fingerprint
    assert file_hashes(writer.directory) == before
    stored = np.load(writer.path, mmap_mode='r+', allow_pickle=False)
    stored[1, 0, 0] += 1
    stored.flush()
    stored._mmap.close()
    # The selected frame is unchanged; another durable frame invalidates the binding.
    changed = source_fingerprint(cube)
    assert changed['array'] == fingerprint['array']
    assert changed['source_id'] != fingerprint['source_id']
    with pytest.raises(ValueError, match='source mismatch'):
        load_annotation(annotation_path, cube)


@pytest.mark.parametrize('changed', ['data', 'metadata', 'mask', 'sidecar'])
def test_compute_pinned_rejects_source_changes_during_computation(tmp_path, changed):
    path = save_cube(raw_cube(), tmp_path / 'source.npy')
    with load_cube(path) as cube:
        def function():
            if changed == 'data':
                cube.data = np.zeros(cube.shape, dtype=cube.data.dtype)
            elif changed == 'metadata':
                cube.metadata['units'] = 'changed'
            elif changed == 'mask':
                cube.valid_mask = ~cube.valid_mask
            else:
                sidecar = path.with_suffix('.npy.json')
                sidecar.write_text(sidecar.read_text(encoding='utf-8') + '\n', encoding='utf-8')
            return {'mean': 123}
        with pytest.raises(ValueError, match='changed during computation'):
            compute_pinned(cube, function)


def test_compute_pinned_returns_exact_result_and_fingerprint_without_raw_mutation():
    cube = raw_cube()
    cube.data.setflags(write=False)
    expected = cube.data.mean(axis=(0, 1))
    result, fingerprint = compute_pinned(cube, lambda: cube.data.mean(axis=(0, 1)))
    np.testing.assert_array_equal(result, expected)
    assert fingerprint == source_fingerprint(cube)
    assert not cube.data.flags.writeable
