"""Private analyst annotations and source-bound analysis export records.

Annotations never amend acquisition metadata or satisfy calibration admission.
Fingerprinting is explicit save/export work, not a live-preview operation.
"""
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
from numbers import Real
from pathlib import Path

import numpy as np

from .io.cube import _json_default


_TEXT_FIELDS = ('specimen_id', 'material', 'coating_batch', 'substrate',
    'session_label', 'replicate_id', 'temperature_unit', 'temperature_meaning',
    'temperature_reference_id', 'illumination_id', 'geometry_id', 'notes')
_NUMBER_FIELDS = ('temperature_value', 'dwell_seconds')
_UNKNOWN = {'', 'unknown', 'unavailable', 'n/a'}
_HASH_CHUNK_BYTES = 1024 * 1024


def _text(value, field):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f'{field} must be text or unknown')
    value = value.strip()
    return None if value.lower() in _UNKNOWN else value


def normalize_annotations(values):
    """Return fixed nullable fields; retain entered meaning, never infer it."""
    if not isinstance(values, Mapping):
        raise ValueError('Experiment annotations must be a mapping')
    extra = set(values) - {*_TEXT_FIELDS, *_NUMBER_FIELDS, 'reference_ids'}
    if extra:
        raise ValueError('Unknown annotation fields: ' + ', '.join(map(str, extra)))
    result = {key: _text(values.get(key), key) for key in _TEXT_FIELDS}
    for key in _NUMBER_FIELDS:
        value = values.get(key)
        if isinstance(value, str):
            value = _text(value, key)
        if value is not None:
            if isinstance(value, (bool, np.bool_)):
                raise ValueError(f'{key} must be a number, not a Boolean')
            if not isinstance(value, (str, Real)):
                raise ValueError(f'{key} must be a scalar number or unknown')
            try:
                value = float(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f'{key} must be a finite number or unknown') from error
            if not np.isfinite(value):
                raise ValueError(f'{key} must be finite')
        result[key] = value
    if result['dwell_seconds'] is not None and result['dwell_seconds'] < 0:
        raise ValueError('dwell_seconds must be nonnegative')
    temperature, unit, meaning = (result[key] for key in
        ('temperature_value', 'temperature_unit', 'temperature_meaning'))
    if temperature is None:
        if unit is not None or meaning is not None:
            raise ValueError('Temperature unit and meaning require a value')
    elif unit not in ('degC', 'K') or meaning not in (
            'setpoint', 'independent_measurement', 'owner_label'):
        raise ValueError('Temperature requires unit degC/K and an explicit input meaning')
    if meaning == 'independent_measurement' and result['temperature_reference_id'] is None:
        raise ValueError('An independent temperature declaration requires a reference ID')
    references = values.get('reference_ids')
    if references is None:
        references = []
    if not isinstance(references, (list, tuple)):
        raise ValueError('reference_ids must be a list of IDs')
    result['reference_ids'] = [item for value in references
                              if (item := _text(value, 'reference_ids')) is not None]
    if len(set(result['reference_ids'])) != len(result['reference_ids']):
        raise ValueError('reference_ids must be unique')
    return result


def _json_bytes(value, *, allow_nan=False):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=allow_nan, default=_json_default).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _array_identity(array):
    view = array
    while view is not None:
        mapped = getattr(view, '_mmap', None)
        if mapped is not None and mapped.closed:
            raise ValueError('Source mapping is closed; reopen the source and run analysis again before exporting')
        view = getattr(view, 'base', None)
    digest = hashlib.sha256()
    # Buffered C-order iteration also handles transposed ENVI and sliced masks.
    with np.nditer(array, flags=['external_loop', 'buffered', 'zerosize_ok'],
                   op_flags=['readonly'], order='C',
                   buffersize=max(1, _HASH_CHUNK_BYTES // array.dtype.itemsize)) as blocks:
        for block in blocks:
            digest.update(block.tobytes(order='C'))
    return {'shape': list(array.shape), 'dtype': str(array.dtype), 'sha256': digest.hexdigest()}


def _file_identity(path):
    path = Path(path).resolve()
    if not path.exists():
        return {'path': str(path), 'status': 'MISSING', 'size_bytes': None, 'sha256': None}
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'status': 'PRESENT', 'size_bytes': path.stat().st_size,
            'sha256': digest}


def _mapped_path(array):
    while array is not None:
        filename = getattr(array, 'filename', None)
        if filename is not None:
            return Path(filename)
        array = getattr(array, 'base', None)
    return None


def source_fingerprint(cube):
    """Hash logical samples, metadata and only the explicitly related source assets."""
    from .plots import plain
    paths = []
    source = cube.metadata.get('source_file')
    if source:
        source = Path(source)
        paths.append(('header' if source.suffix.lower() == '.hdr' else 'data', source))
        if source.suffix.lower() in ('.npy', '.hdr'):
            paths.append(('sidecar', source.with_suffix(source.suffix + '.json')))
        if cube.metadata.get('valid_mask_file'):
            paths.append(('mask', source.parent / cube.metadata['valid_mask_file']))
    sequence = cube.metadata.get('sequence_source')
    if isinstance(sequence, Mapping):
        for key, role in (('path', 'sequence_data'), ('manifest_path', 'sequence_manifest')):
            if sequence.get(key):
                paths.append((role, Path(sequence[key])))
    for array, role in ((cube.data, 'data'), (cube.valid_mask, 'mask')):
        mapped = _mapped_path(array)
        if mapped is not None:
            paths.append((role, mapped))
    assets, seen = [], set()
    for role, path in paths:
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        assets.append({'role': role, **_file_identity(path)})
    result = {'schema_version': 1, 'array': _array_identity(cube.data),
        'valid_mask': None if cube.valid_mask is None else _array_identity(cube.valid_mask),
        # Metadata NaN and null hash differently; nonfinite values are not copied
        # into the strict-JSON fingerprint record or turned into annotations.
        'metadata_sha256': hashlib.sha256(_json_bytes(cube.metadata, allow_nan=True)).hexdigest(),
        'source_files': sorted(assets, key=lambda item: (item['role'], item['path'])),
        'origin': plain({key: cube.metadata.get(key) for key in ('data_level', 'data_source',
            'acquisition_source', 'display_mode', 'session_id', 'stream_epoch', 'sequence',
            'frame_id', 'completed', 'partial')})}
    return dict(result, source_id=_digest(result))


def _check_fingerprint(fingerprint):
    if (not isinstance(fingerprint, dict) or type(fingerprint.get('schema_version')) is not int
            or fingerprint['schema_version'] != 1 or fingerprint.get('source_id') !=
            _digest({key: value for key, value in fingerprint.items() if key != 'source_id'})):
        raise ValueError('Invalid source fingerprint')


def compute_pinned(cube, function):
    """Bind an explicit analysis to unchanged source bytes, metadata and masks."""
    fingerprint = source_fingerprint(cube)
    result = function()
    if source_fingerprint(cube) != fingerprint:
        raise ValueError('Analysis source changed during computation; result was not accepted')
    return result, fingerprint


def _check_annotation(record):
    if (not isinstance(record, dict) or record.get('kind') != 'analyst_annotation'
            or type(record.get('schema_version')) is not int or record['schema_version'] != 1
            or type(record.get('revision')) is not int or record['revision'] < 1
            or record.get('annotation_id') !=
            _digest({key: value for key, value in record.items() if key != 'annotation_id'})):
        raise ValueError('Invalid or changed annotation revision')
    _check_fingerprint(record.get('source_fingerprint'))
    if normalize_annotations(record.get('values')) != record['values']:
        raise ValueError('Annotation revision fields are not normalized')


def save_annotation(directory, cube, values, previous=None):
    """Create a new source-bound revision; return (record, path) without raw edits."""
    values = normalize_annotations(values)
    fingerprint = source_fingerprint(cube)
    if previous is not None:
        _check_annotation(previous)
        if previous['source_fingerprint']['source_id'] != fingerprint['source_id']:
            raise ValueError('Previous annotation belongs to a different source')
    payload = {'schema_version': 1, 'kind': 'analyst_annotation',
        'revision': 1 if previous is None else previous['revision'] + 1,
        'supersedes': None if previous is None else previous['annotation_id'],
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='microseconds'),
        'source_fingerprint': fingerprint, 'values': values}
    record = dict(payload, annotation_id=_digest(payload))
    path = Path(directory) / ('annotation_' + record['annotation_id'] + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return record, path


def load_annotation(path, cube):
    """Restore an exact saved revision only while its source identity still matches."""
    record = json.loads(Path(path).read_text(encoding='utf-8'))
    _check_annotation(record)
    if record['source_fingerprint']['source_id'] != source_fingerprint(cube)['source_id']:
        raise ValueError('Annotation source mismatch; source bytes or metadata changed')
    return record


def write_analysis_manifest(directory, fingerprint, recipe, annotation=None):
    """Hash direct files in a dedicated completed output directory, then record it.

    No recursion or raw copying. Failure propagates before a success record is
    returned; existing outputs are preserved and an existing manifest is refused.
    """
    from . import __version__
    from .plots import plain
    path = Path(directory) / 'analysis_manifest.json'
    if path.exists():
        raise FileExistsError('Analysis manifest already exists; choose a new output directory')
    _check_fingerprint(fingerprint)
    if not isinstance(recipe, Mapping):
        raise ValueError('Analysis recipe must be a mapping')
    if annotation is not None:
        _check_annotation(annotation)
        if annotation['source_fingerprint']['source_id'] != fingerprint['source_id']:
            raise ValueError('Annotation belongs to a different analysis source')
    outputs = []
    for item in sorted(path.parent.iterdir()):
        if item.is_symlink():
            raise ValueError('Analysis outputs must be local regular files, not links')
        if item.is_file():
            identity = _file_identity(item)
            outputs.append({'path': item.name, 'size_bytes': identity['size_bytes'],
                            'sha256': identity['sha256']})
    if not outputs:
        raise ValueError('Analysis manifest requires existing output files')
    record = {'schema_version': 1, 'kind': 'analysis_manifest', 'status': 'COMPLETE',
        'status_meaning': 'Listed analysis outputs were hashed; not acquisition or physical acceptance',
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='microseconds'),
        'hyperlab_version': __version__, 'source_fingerprint': fingerprint,
        'recipe': plain(recipe), 'annotation': annotation, 'outputs': outputs}
    content = json.dumps(record, indent=2, allow_nan=False) + '\n'
    with path.open('x', encoding='utf-8') as stream:
        stream.write(content)
    return path
