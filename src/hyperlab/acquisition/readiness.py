"""On-demand measurement facts; this report never gates capture or alters raw data."""
from copy import deepcopy

import numpy as np

from hyperlab.analysis.applicability import _text
from hyperlab.analysis.core import _floating, _quality
from hyperlab.io import Cube


def measurement_readiness(source, *, selected_task='descriptive contrast', policy='quantitative',
                          bands=None, scene_evidence=None, reference_check=None):
    """Inspect a Frame/Cube exactly, off the preview path; None means no observation.

    A supplied scene assessment is task/status/source/reason evidence, not inferred
    from brightness. Caller-supplied evidence/checks must be pinned to this source.
    Reference MATCH retains the existing checker's compatibility meaning and is
    not a physical calibration certificate. Quantiles use every
    policy-valid sample of each selected feature; no spatial sampling is hidden.
    """
    if not _text(selected_task):
        raise ValueError('Selected task must be known nonempty text')
    scene = {'status': 'UNKNOWN', 'task': selected_task, 'source': None,
             'reason': 'Scene illumination and response for the selected task have not been established'}
    if scene_evidence is not None:
        if not isinstance(scene_evidence, dict) or scene_evidence.get('status') not in {'PASS', 'FAIL', 'UNKNOWN'}:
            raise ValueError('Scene evidence needs a PASS, FAIL or UNKNOWN status')
        if scene_evidence['status'] != 'UNKNOWN':
            if not _text(scene_evidence.get('source')) or not _text(scene_evidence.get('reason')):
                raise ValueError('Scene assessment requires its source and reason')
            if scene_evidence.get('task') != selected_task:
                raise ValueError('Scene evidence must match the selected task')
        if scene_evidence.get('task', selected_task) != selected_task:
            raise ValueError('Scene evidence must match the selected task')
        scene.update(deepcopy(scene_evidence))
    reference = {'status': 'UNKNOWN', 'check': deepcopy(reference_check),
                 'interpretation': 'Recorded reference compatibility, not physical verification or a calibration certificate'}
    if reference_check is not None:
        if not isinstance(reference_check, dict) or reference_check.get('status') not in {'MATCH', 'MISMATCH', 'UNKNOWN'}:
            raise ValueError('Reference check must be an existing MATCH, MISMATCH or UNKNOWN applicability result')
        checks = reference_check.get('checks') or []
        if reference_check['status'] == 'MISMATCH' or any(check.get('status') == 'MISMATCH' for check in checks):
            reference['status'] = 'MISMATCH'
        elif (reference_check['status'] == 'MATCH' and checks and
              all(check.get('status') == 'MATCH' for check in checks) and
              reference_check.get('evidence')):
            reference['status'] = 'MATCH'
    report = {'schema_version': 1, 'selected_task': selected_task,
              'frame_received': {'status': 'UNKNOWN', 'reason': 'No frame observation supplied'},
              'scene_usable_for_selected_task': scene, 'reference_qualified': reference, 'signal': None,
              'interpretation': 'Independent observation facts; capture and saving remain available. '
                  'Unknown optical cause is not a dark reference or a defect diagnosis.'}
    if source is None:
        scene.update(status='UNKNOWN', reason='No frame observation supplied for the scene assessment')
        reference['status'] = 'UNKNOWN'
        return report
    meta = source.metadata
    cube = source if isinstance(source, Cube) else Cube(
        source.data[:, :, None] if source.data.ndim == 2 else source.data, dict(meta))
    h, w, k = cube.shape
    selected = list(range(k)) if bands is None else list(bands)
    if (not selected or len(set(selected)) != len(selected) or
            any(isinstance(i, (bool, np.bool_)) or not isinstance(i, (int, np.integer)) or not 0 <= i < k
                for i in selected)):
        raise ValueError('Readiness features must be nonempty unique indices inside the source')
    identity = {key: meta.get(key) for key in ('source_file', 'session_id', 'stream_epoch', 'sequence', 'host_utc')}
    missing = [key for key in ('session_id', 'host_utc', 'pixel_format') if not _text(meta.get(key))]
    sequence = meta.get('sequence')
    if isinstance(sequence, (bool, np.bool_)) or not isinstance(sequence, (int, np.integer)) or sequence < 0:
        missing.append('sequence')
    declared_shape = meta.get('shape')
    shape_matches = None if declared_shape is None else list(declared_shape) == list(source.data.shape)
    if shape_matches is None:
        missing.append('shape')
    complete, declared_valid = meta.get('buffer_complete'), meta.get('valid')
    frame_status = 'UNKNOWN'
    if meta.get('data_level') != 'raw_frame':
        frame_status = 'NOT_APPLICABLE'
    elif complete is False or declared_valid is False or shape_matches is False:
        frame_status = 'FAIL'
    elif complete is True and declared_valid is True and not missing:
        frame_status = 'PASS'
    report['frame_received'] = {'status': frame_status, 'buffer_complete': complete,
        'declared_valid': declared_valid, 'identity': identity, 'missing_identity': missing,
        'shape': list(source.data.shape), 'declared_shape_matches': shape_matches, 'dtype': str(source.data.dtype),
        'pixel_format': meta.get('pixel_format'),
        'origin': 'SYNTHETIC' if meta.get('synthetic') else meta.get('acquisition_source', meta.get('data_source', 'unknown')),
        'scope': 'Recorded raw-frame receipt; not current camera connection or end-to-end latency'}
    per_feature = []
    for index in selected:
        selection = (slice(None), slice(None), slice(index, index+1))
        raw = cube.data[selection]
        good, causes, saturation = _quality(cube, raw, selection, policy)
        values = _floating(raw[good], np.float64)
        counts = {key: int(np.count_nonzero(causes[key])) for key in ('invalid', 'ignored')}
        counts.update(total=h*w, used=int(values.size), zero_used=int(np.count_nonzero(values == 0)),
                      saturated=None if saturation is None else int(np.count_nonzero(causes['saturated'])))
        per_feature.append({'index': int(index), 'counts': counts, 'saturation_value': saturation,
            'quantiles': np.quantile(values, [0, .01, .5, .99, 1], method='linear').tolist() if values.size else [None]*5,
            'mean': float(values.mean()) if values.size else None})
    report['signal'] = {'exact': True, 'policy': policy, 'sample_units': cube.metadata['units'],
        'feature_indices': [int(i) for i in selected], 'source_identity': identity,
        'total_pixels': h*w, 'total_selected_values': h*w*len(selected),
        'quantile_probabilities': [0, .01, .5, .99, 1], 'quantile_method': 'linear',
        'per_feature': per_feature,
        'count_semantics': 'Per-feature source samples: invalid, ignored and saturated causes are disjoint. '
            'Diagnostic used includes saturated; quantitative used excludes it. Unknown saturation count is null. '
            'zero_used and quantiles refer only to policy-valid samples.'}
    if not any(feature['counts']['used'] for feature in per_feature):
        scene.update(status='FAIL', reason='No usable samples under the selected numerical quality policy')
    return report
