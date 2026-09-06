"""Local studies link saved observations without changing their evidence identity."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from .experiment_metadata import (_check_annotation, _check_fingerprint, _digest,
    _file_identity, normalize_annotations, source_fingerprint)
from .experiments import _unknown, matching_settings
from .io.labels import display_labels
from .plots import plain


COMPARISON_LEVELS = ('within-session', 'reposition', 'between-specimen', 'between-session')
COMPARISON_PURPOSES = ('nuisance-control', 'target-change')
_LINKS = ('specimen_id', 'treatment_id', 'session_id', 'technical_repeat_id')


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def new_study(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('A study name is required')
    return {'schema_version': 1, 'kind': 'study', 'study_id': str(uuid4()),
            'name': name.strip(), 'created_utc': _now(), 'observations': []}


def _content(observation):
    return {key: value for key, value in observation.items()
            if key not in ('content_sha256', 'asset_locations', 'relocations')}


def _assets(observation):
    return observation['source_fingerprint']['source_files'] + observation['associated_assets']


def _acquisition_key(observation):
    origin = observation['source_fingerprint']['origin']
    values = [origin.get(key) for key in ('acquisition_source', 'session_id', 'stream_epoch', 'sequence')]
    return values if all(value is not None for value in values) else None


def _check_observation(observation):
    if observation.get('content_sha256') != _digest(_content(observation)):
        raise ValueError('Observation content changed')
    fingerprint = observation['source_fingerprint']
    _check_fingerprint(fingerprint)
    if observation['comparison_level'] not in (None, *COMPARISON_LEVELS):
        raise ValueError('Unknown comparison level')
    if observation.get('comparison_purpose') not in (None, *COMPARISON_PURPOSES):
        raise ValueError('Unknown comparison purpose')
    if set(observation['links']) != set(_LINKS):
        raise ValueError('Observation hierarchy links are incomplete')
    if observation['annotation'] is not None:
        _check_annotation(observation['annotation'])
        if observation['annotation']['source_fingerprint'] != fingerprint:
            raise ValueError('Annotation belongs to a different observation')
    analysis = observation['analysis_run']
    if analysis is not None:
        if (analysis.get('analysis_run_id') != _digest({key: value for key, value in analysis.items()
                if key != 'analysis_run_id'}) or analysis['source_id'] != fingerprint['source_id']):
            raise ValueError('Analysis run identity or source changed')
    expected = [asset['path'] for asset in _assets(observation)]
    if len(expected) != len(set(expected)) or set(observation['asset_locations']) != set(expected):
        raise ValueError('All recorded source and associated assets need exactly one declared location')


def _check_study(study):
    if study.get('kind') != 'study' or study.get('schema_version') != 1:
        raise ValueError('Unsupported Study manifest')
    ids, sources, acquisition_keys = [], [], []
    for observation in study['observations']:
        _check_observation(observation)
        ids.append(observation['observation_id'])
        source = observation['source_fingerprint']['source_id']
        key = _acquisition_key(observation)
        if source in sources or key is not None and key in acquisition_keys:
            raise ValueError('Duplicate source or acquisition in Study manifest')
        sources.append(source)
        if key is not None:
            acquisition_keys.append(key)
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate observation IDs in Study manifest')


def _roi_analysis(cube, fingerprint, results, context, feature_result):
    if not results and context is None and feature_result is None:
        return None
    if not results or not context or context.get('source_fingerprint') != fingerprint:
        raise ValueError('Completed ROI results require the unchanged original source fingerprint')
    if context.get('annotation') is not None:
        _check_annotation(context['annotation'])
        if context['annotation']['source_fingerprint'] != fingerprint:
            raise ValueError('Completed analysis annotation belongs to a different source')
    selected = list(context.get('analyzed_roi_indices', range(len(results))))
    if len(selected) != len(results):
        raise ValueError('Completed ROI result and definition counts differ')
    metric = context.get('summary', 'mean')
    if metric not in ('mean', 'median'):
        raise ValueError('Study amplitude features require a mean or median summary')
    labels = display_labels(cube.metadata, cube.shape[2])
    features, rois, evidence = [], [], []
    for position, result in zip(selected, results):
        names = context.get('names', [])
        name = names[position] if position < len(names) else f'ROI {position + 1}'
        definitions = context.get('roi_definitions', [])
        roi = (definitions[position] if position < len(definitions) else None) or result.get('roi') or result.get('metadata', {}).get('roi_definition')
        roi = plain(roi) if roi else {'roi_id': None, 'revision': None, 'name': name,
            'geometry': {'type': 'rectangle', 'bounds': plain(result['rect'])},
            'coordinate_frame': 'source raw pixels', 'legacy_context_version': context.get('version')}
        rois.append(roi)
        evidence.append(plain({key: value for key, value in result.get('metadata', {}).items()
                               if key != 'source_provenance'}))
        for band in result.get('feature_indices', range(cube.shape[2])):
            feature = {'roi_index': len(rois)-1, 'roi_name': name,
                'roi_id': roi.get('roi_id'), 'roi_revision': roi.get('revision'),
                'feature_index': int(band), 'feature_label': labels[band],
                'axis_kind': 'wavelength' if cube.wavelengths is not None else
                    'category' if cube.metadata.get('channel_labels') else 'index',
                'coordinate': None if cube.wavelengths is None else plain(cube.wavelengths[band]),
                'coordinate_units': cube.metadata.get('wavelength_units'),
                'data_level': cube.metadata['data_level'], 'units': result['units'],
                'metric': metric, 'value': plain(result[metric][band]),
                'used': int(result['count'][band]), 'total': int(result['counts']['total'][band]),
                'policy': result['policy'], 'support': result.get('support', 'per_band'),
                'aggregation_order': 'source_pixel_summary'}
            features.append(feature)
    run = {'kind': 'study_roi_analysis', 'status': 'COMPLETE',
        'source_id': fingerprint['source_id'], 'recipe': plain(context), 'rois': rois, 'roi_evidence': evidence,
        'features': features, 'additional_completed_features': plain(feature_result),
        'interpretation': 'Completed source ROI summaries; spatial samples are not independent observations.'}
    return dict(run, analysis_run_id=_digest(run))


def _roi_assets(analysis):
    assets = {}
    if analysis is None:
        return []
    definitions = list(analysis['rois'])
    for evidence in analysis['roi_evidence']:
        definitions.extend(evidence.get('exclusion_definitions', []))
    for definition in definitions:
        geometry = definition.get('geometry', {})
        if geometry.get('type') != 'mask':
            continue
        path = str(Path(geometry['path']).resolve())
        expected = {'role': 'roi_mask', 'path': path, 'status': 'PRESENT',
                    'sha256': geometry['sha256'], 'size_bytes': geometry['size_bytes']}
        actual = _file_identity(path)
        if any(actual[key] != expected[key] for key in ('status', 'sha256', 'size_bytes')):
            raise ValueError('A completed ROI mask asset is missing or changed')
        if path in assets and assets[path] != expected:
            raise ValueError('Completed ROI definitions disagree about an external mask asset')
        assets[path] = expected
    return list(assets.values())


def observation_from_cube(cube, *, annotation=None, annotation_path=None, roi_results=None,
                          roi_context=None, feature_result=None, links=None, comparison_level=None,
                          comparison_purpose=None):
    """Snapshot a saved source and a completed result; never run implicit analysis."""
    fingerprint = source_fingerprint(cube)
    source = cube.metadata.get('source_file')
    if not source or not any(asset['path'] == str(Path(source).resolve()) and
            asset['status'] == 'PRESENT' for asset in fingerprint['source_files']):
        raise ValueError('Save the source frame or cube before adding it to a Study')
    if any(asset['status'] != 'PRESENT' and asset['role'] != 'sidecar'
           for asset in fingerprint['source_files']):
        raise ValueError('A declared source asset is missing')
    if comparison_level not in (None, *COMPARISON_LEVELS):
        raise ValueError('Unknown comparison level')
    if comparison_purpose not in (None, *COMPARISON_PURPOSES):
        raise ValueError('Unknown comparison purpose')
    if annotation is not None:
        _check_annotation(annotation)
        if annotation['source_fingerprint'] != fingerprint:
            raise ValueError('Annotation belongs to a different saved source')
    values = normalize_annotations({}) if annotation is None else annotation['values']
    supplied = links or {}
    if set(supplied) - set(_LINKS):
        raise ValueError('Unsupported Study hierarchy link')
    hierarchy = {'specimen_id': values['specimen_id'], 'treatment_id': None,
                 'session_id': cube.metadata.get('session_id'),
                 'technical_repeat_id': values['replicate_id']}
    for key, value in supplied.items():
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f'{key} must be a declared text ID or unknown')
        if key in ('specimen_id', 'technical_repeat_id', 'session_id') and hierarchy[key] and value != hierarchy[key]:
            raise ValueError(f'{key} conflicts with the saved annotation')
        hierarchy[key] = value.strip() if value is not None else None
    associated = []
    if annotation_path is not None:
        path = Path(annotation_path).resolve()
        payload = path.read_bytes()
        if annotation is None or json.loads(payload) != annotation:
            raise ValueError('Annotation file does not match the declared revision')
        associated.append({'role': 'annotation', 'path': str(path), 'status': 'PRESENT',
                           'size_bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()})
    analysis = _roi_analysis(cube, fingerprint, roi_results, roi_context, feature_result)
    source_paths = {asset['path']: asset for asset in fingerprint['source_files']}
    for asset in _roi_assets(analysis):
        if asset['path'] in source_paths:
            if any(asset[key] != source_paths[asset['path']][key] for key in ('size_bytes', 'sha256', 'status')):
                raise ValueError('Source and ROI definitions disagree about a shared asset')
        else:
            associated.append(asset)
    observation = {'observation_id': str(uuid4()), 'added_utc': _now(),
        'source_fingerprint': fingerprint, 'source_metadata': plain(dict(cube.metadata, shape=list(cube.shape))),
        'source_name': Path(source).name, 'links': hierarchy, 'comparison_level': comparison_level,
        'comparison_purpose': comparison_purpose,
        'annotation': deepcopy(annotation), 'analysis_run': analysis, 'associated_assets': associated,
        'asset_locations': {asset['path']: asset['path'] for asset in fingerprint['source_files'] + associated},
        'relocations': []}
    if source_fingerprint(cube) != fingerprint:
        raise ValueError('Source changed while creating the observation')
    observation['content_sha256'] = _digest(_content(observation))
    _check_observation(observation)
    return observation


def add_observation(study, observation):
    """Return a new study. Re-importing one acquisition does not create a replicate."""
    _check_study(study)
    _check_observation(observation)
    fingerprint = observation['source_fingerprint']
    key = _acquisition_key(observation)
    for previous in study['observations']:
        if (previous['source_fingerprint']['source_id'] == fingerprint['source_id'] or
                key is not None and key == _acquisition_key(previous)):
            raise ValueError('This source or acquisition is already an observation; use its existing row')
    result = deepcopy(study)
    result['observations'].append(deepcopy(observation))
    return result


def verify_study(study):
    """Hash every declared file location. Never search or substitute another file."""
    _check_study(study)
    checks = []
    for observation in study['observations']:
        files = []
        for expected in _assets(observation):
            location = observation['asset_locations'][expected['path']]
            actual = _file_identity(location)
            if expected['status'] == 'MISSING':
                status = 'EXPECTED_ABSENT' if actual['status'] == 'MISSING' else 'MISMATCH'
            elif actual['status'] == 'MISSING':
                status = 'MISSING'
            else:
                status = 'MATCH' if all(actual[key] == expected[key]
                    for key in ('size_bytes', 'sha256')) else 'MISMATCH'
            files.append({'role': expected['role'], 'original_path': expected['path'],
                          'location': actual['path'], 'status': status})
        checks.append({'observation_id': observation['observation_id'], 'assets': files,
            'status': 'MATCH' if all(item['status'] in ('MATCH', 'EXPECTED_ABSENT') for item in files)
                      else 'MISMATCH' if any(item['status'] == 'MISMATCH' for item in files) else 'MISSING'})
    return {'checked_utc': _now(), 'status': 'MATCH' if checks and all(item['status'] == 'MATCH'
            for item in checks) else 'EMPTY' if not checks else 'MISMATCH' if any(
            item['status'] == 'MISMATCH' for item in checks) else 'MISSING', 'observations': checks,
            'interpretation': 'Byte integrity at declared locations; physical readiness and registration are separate.'}


def relocate_observation(study, observation_id, locations):
    """Associate explicitly chosen locations only after ALL source assets match."""
    _check_study(study)
    result = deepcopy(study)
    observation = next((item for item in result['observations'] if item['observation_id'] == observation_id), None)
    if observation is None:
        raise ValueError('Observation not found')
    if set(locations) != set(observation['asset_locations']):
        raise ValueError('Relocation must explicitly cover every recorded asset, including absent sidecars')
    previous = observation['asset_locations']
    observation['asset_locations'] = {key: str(Path(value).resolve()) for key, value in locations.items()}
    check = verify_study(dict(result, observations=[observation]))
    if check['status'] != 'MATCH':
        raise ValueError('Relocation rejected: one or more source/annotation assets are missing or changed')
    observation['relocations'].append({'checked_utc': check['checked_utc'],
        'previous_locations': previous, 'locations': deepcopy(observation['asset_locations']),
        'status': 'ALL_ASSETS_MATCH'})
    return result


def save_study(study, path):
    """Write a portable manifest; raw files and original fingerprints stay intact."""
    _check_study(study)
    path = Path(path).resolve()
    if any(path == Path(location).resolve() for observation in study['observations']
           for location in (*observation['asset_locations'], *observation['asset_locations'].values())):
        raise ValueError('A Study manifest cannot overwrite a source or annotation asset')
    if path.exists():
        existing = json.loads(path.read_text(encoding='utf-8'))
        if existing.get('kind') != 'study' or existing.get('study_id') != study['study_id']:
            raise ValueError('Choose a new filename; an unrelated file or Study already exists')
    payload = deepcopy(study)
    for observation in payload['observations']:
        for key, value in observation['asset_locations'].items():
            try:
                observation['asset_locations'][key] = os.path.relpath(Path(value).resolve(), path.parent)
            except ValueError:  # A different Windows drive cannot have a relative locator.
                observation['asset_locations'][key] = str(Path(value).resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def load_study(path):
    path = Path(path).resolve()
    study = json.loads(path.read_text(encoding='utf-8'))
    _check_study(study)
    for observation in study['observations']:
        observation['asset_locations'] = {key: str((path.parent / value).resolve())
            for key, value in observation['asset_locations'].items()}
    return study


def _analysis_definition(metadata, evidence, feature):
    """Define the estimator from retained evidence, without rewriting observations.

    Geometry membership and particular missing samples remain source evidence;
    their content hashes do not define compatibility between different ROIs.
    """
    from types import SimpleNamespace
    from .analysis.core import saturation_value

    common = feature['support'] == 'common'
    selected = evidence.get('feature_indices') if common else [feature['feature_index']]
    shape = metadata.get('shape', [])
    size = shape[2] if len(shape) == 3 else len(metadata.get('wavelengths') or metadata.get('channel_labels') or [])
    labels = display_labels(metadata, size) if size else []
    wave = metadata.get('wavelengths')
    mappings = None
    if selected and feature['feature_index'] in selected and all(type(index) is int and 0 <= index < size for index in selected):
        mappings = [{'feature_index': index, 'label': labels[index],
            'coordinate': wave[index] if wave is not None else None,
            'coordinate_units': metadata.get('wavelength_units') if wave is not None else None}
            for index in sorted(set(selected))]
    threshold = saturation_value(SimpleNamespace(metadata=metadata))
    quality = {'policy': feature['policy'], 'invalid_rule': 'finite and supplied source validity; enabled features only',
        'data_ignore_value': metadata.get('data_ignore_value'),
        'saturation_rule': 'exclude values >= threshold when known' if feature['policy'] == 'quantitative' else 'retained',
        'saturation_value': threshold if feature['policy'] == 'quantitative' else None,
        'saturation_units': feature['units'] if feature['policy'] == 'quantitative' and threshold is not None else None,
        'low_signal_assessment': deepcopy(metadata.get('low_signal_assessment'))}
    applied = {key: deepcopy(metadata.get(key)) for key in ('processing_steps', 'calibration_source',
        'reference_source', 'reference_reflectance', 'reflectance_kind', 'reference_applicability',
        'response_id', 'response_matrix_id', 'spectral_response_id', 'spatial_calibration')}
    quantile = evidence.get('quantile_method') if feature['metric'] == 'median' else None
    unknown = (['support_features'] if mappings is None else []) + (
        ['quantile_method'] if feature['metric'] == 'median' and quantile is None else [])
    definition = {'schema_version': 1, 'status': 'UNKNOWN' if unknown else 'KNOWN', 'unknown_fields': unknown,
        'evidence_source': 'retained completed ROI feature selection' if common else 'output feature per-band support',
        'data_level': feature['data_level'], 'units': feature['units'], 'summary': feature['metric'],
        'aggregation_order': feature['aggregation_order'], 'support': feature['support'],
        'quantile_method': quantile,
        'support_features': mappings, 'quality': quality, 'applied_context': applied}
    return plain(definition)


def support_label(definition):
    """Readable support, with hashes reserved for the provenance details."""
    mappings = definition['support_features']
    if mappings is None:
        return definition['support'] + ': UNKNOWN feature population'
    labels = [f"{item['feature_index']} {item['coordinate']:g} {item['coordinate_units']}"
              if item['coordinate'] is not None else f"{item['feature_index']} {item['label']}" for item in mappings]
    return definition['support'] + ': ' + ', '.join(labels)


def measurement_comparison(observations):
    """Declared conditions for these observations, independent of estimator identity."""
    settings = matching_settings([item['source_metadata'] for item in observations]) if len(observations) >= 2 else {
        'status': 'UNKNOWN', 'note': 'At least two observations are required for a settings comparison.'}
    mismatches, unknown = [], []
    for field in ('illumination_id', 'geometry_id'):
        values = [normalize_annotations({})[field] if item['annotation'] is None
                  else item['annotation']['values'].get(field) for item in observations]
        if any(value is None for value in values) or not values:
            unknown.append(field)
        if len({value for value in values if value is not None}) > 1:
            mismatches.append(field)
    if settings['status'] == 'MISMATCH':
        mismatches.append('acquisition_settings')
    elif settings['status'] != 'MATCH':
        unknown.append('acquisition_settings')
    calibration = [item['source_metadata'].get('calibration_source') for item in observations]
    known_calibration = [value for value in calibration if not _unknown(value)]
    if len(known_calibration) != len(calibration) or not calibration:
        unknown.append('response_calibration')
    if known_calibration and any(value != known_calibration[0] for value in known_calibration[1:]):
        mismatches.append('response_calibration')
    return {'status': 'MISMATCH' if mismatches else 'UNKNOWN' if unknown or len(observations) < 2 else 'MATCH',
        'mismatches': mismatches, 'unknown': unknown, 'settings': settings,
        'observation_count': len(observations), 'physical_qualification': 'NOT_ASSESSED',
        'scope': 'All supplied observations: declared acquisition/illumination/geometry evidence; not material equivalence, registration or independent replication.'}


def study_summary(study):
    """Unpooled observation rows and compatible feature columns; no inferred n."""
    _check_study(study)
    rows, feature_rows, columns, definitions = [], [], [], {}
    signatures = {}
    seen_arrays = {}
    for index, observation in enumerate(study['observations']):
        values = normalize_annotations({}) if observation['annotation'] is None else observation['annotation']['values']
        origin = observation['source_fingerprint']['origin']
        array_key = _digest(observation['source_fingerprint']['array'])
        byte_peers = list(seen_arrays.get(array_key, []))
        seen_arrays.setdefault(array_key, []).append(observation['observation_id'])
        run = observation['analysis_run']
        rows.append({'observation_id': observation['observation_id'], 'number': index+1,
            'source_name': observation['source_name'], 'origin': origin.get('acquisition_source'),
            'sequence': origin.get('sequence'), **observation['links'], **{key: values[key] for key in
                ('material', 'coating_batch', 'dwell_seconds', 'temperature_value', 'temperature_unit',
                 'temperature_meaning', 'temperature_reference_id', 'illumination_id', 'geometry_id')},
            'comparison_level': observation['comparison_level'], 'comparison_purpose': observation.get('comparison_purpose'),
            'analysis_status': 'NOT_RUN' if run is None else run['status'],
            'same_array_observations': byte_peers})
        if run is None:
            continue
        for roi_index, roi in enumerate(run['rois']):
            cells = {}
            evidence = run.get('roi_evidence', [])
            evidence = evidence[roi_index] if roi_index < len(evidence) else {}
            common_definition = None
            for feature in (item for item in run['features'] if item['roi_index'] == roi_index):
                descriptor = {key: feature[key] for key in ('feature_index', 'feature_label', 'axis_kind',
                    'coordinate', 'coordinate_units', 'data_level', 'units', 'metric', 'policy', 'support', 'aggregation_order')}
                definition = common_definition or _analysis_definition(observation['source_metadata'], evidence, feature)
                if feature['support'] == 'common':
                    common_definition = definition
                definition_id = _digest(definition)
                definitions.setdefault(definition_id, definition)
                descriptor.update(definition_id=definition_id, definition_status=definition['status'],
                                  support_label=support_label(definition))
                signature = _digest(descriptor)
                if signature not in signatures:
                    signatures[signature] = len(columns)
                    columns.append(descriptor)
                cells[signatures[signature]] = {key: feature[key] for key in ('value', 'used', 'total')}
            feature_rows.append({'observation_id': observation['observation_id'], 'number': index+1,
                                 'roi': roi, 'cells': cells})
    comparison = measurement_comparison(study['observations'])
    return {'observations': rows, 'feature_rows': feature_rows, 'feature_columns': columns,
        'definition_contexts': definitions, 'comparison_evidence': comparison,
        'settings_check': comparison['settings'], 'observation_count': len(rows),
        'declared_specimen_ids': sorted({row['specimen_id'] for row in rows if row['specimen_id']}),
        'unknown_specimen_observations': sum(row['specimen_id'] is None for row in rows),
        'independent_replicate_count': None, 'registration': 'NOT_VERIFIED',
        'interpretation': 'Each row is an original observation or its ROI. No pooling, registration, temperature prediction or independent-replicate count is inferred.'}
