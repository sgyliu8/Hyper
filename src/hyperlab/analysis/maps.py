"""Interpretable material contrast maps with fixed feature support."""
import numpy as np

from .applicability import _text
from .capabilities import feature_selection, require_capability
from .core import _band, _floating, _quality


def normalized_difference(cube, a, b, *, minimum_denominator=1e-6, policy='diagnostic',
                          low_signal_threshold=None, low_signal_source=None):
    """Numerical contrast plus optional analyst amplitude selection; no noise estimate."""
    require_capability(cube, 'ratio')
    if a == b:
        raise ValueError('Normalized difference requires distinct features')
    if not np.isfinite(minimum_denominator) or minimum_denominator <= 0:
        raise ValueError('minimum_denominator must be finite and positive')
    assessment = {'status': 'UNKNOWN', 'threshold': None, 'units': cube.metadata['units'],
                  'feature_indices': [int(a), int(b)], 'source': None,
                  'interpretation': 'No matched noise evidence or analyst amplitude threshold; not an SNR estimate'}
    if low_signal_threshold is not None:
        if (isinstance(low_signal_threshold, (bool, np.bool_)) or
                not isinstance(low_signal_threshold, (int, float, np.integer, np.floating)) or
                not np.isfinite(low_signal_threshold) or low_signal_threshold <= 0):
            raise ValueError('Low-signal threshold must be finite and positive')
        if not _text(low_signal_source) or not _text(cube.metadata['units']):
            raise ValueError('Low-signal threshold requires a known analyst source and source signal units')
        assessment.update(status='DIAGNOSTIC_THRESHOLD', threshold=float(low_signal_threshold),
            source=low_signal_source.strip(), expression='abs(a) + abs(b)',
            exclusion_rule='abs(a) + abs(b) < threshold',
            scope='numerically valid pixels of the selected feature pair',
            interpretation='Analyst diagnostic amplitude selection; not a measured noise floor or SNR')
    planes, goods, quality = [], [], []
    for index in (a, b):
        if not isinstance(index, (int, np.integer)) or not 0 <= index < cube.shape[2]:
            raise ValueError('Band/state index outside cube')
        selection = (slice(None), slice(None), slice(index, index+1))
        raw = cube.data[selection]
        good, causes, saturation = _quality(cube, raw, selection, policy)
        planes.append(_floating(raw, np.float64)[:, :, 0])
        goods.append(good[:, :, 0])
        quality.append(causes)
    first, second = planes
    joint = goods[0] & goods[1]
    with np.errstate(over='ignore', invalid='ignore'):
        denominator = first + second
    finite_denominator = np.isfinite(denominator)
    numerical_denominator_valid = joint & finite_denominator & (np.abs(denominator) >= minimum_denominator)
    data = np.full(first.shape, np.nan)
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        np.divide(first - second, denominator, out=data, where=numerical_denominator_valid)
    valid = numerical_denominator_valid & np.isfinite(data)
    reasons = {f'source_{key}': quality[0][key][:, :, 0] | quality[1][key][:, :, 0]
               for key in ('invalid', 'ignored', 'saturated')}
    if saturation is None:
        reasons.pop('source_saturated')
    reasons.update(source_excluded=~joint,
        low_denominator=joint & finite_denominator & (np.abs(denominator) < minimum_denominator),
        nonfinite_calculation=joint & (~finite_denominator | (numerical_denominator_valid & ~np.isfinite(data))))
    if low_signal_threshold is not None:
        with np.errstate(over='ignore', invalid='ignore'):
            reasons['low_signal'] = valid & ((np.abs(first) + np.abs(second)) < low_signal_threshold)
        valid &= ~reasons['low_signal']
    data[~valid] = np.nan
    counts = {key: int(np.count_nonzero(mask)) for key, mask in reasons.items()}
    counts.update(total=int(data.size), used=int(np.count_nonzero(valid)),
                  numerical_denominator_valid=int(np.count_nonzero(numerical_denominator_valid)))
    counts.setdefault('low_signal', None)
    counts.setdefault('source_saturated', None)
    return {'data': data, 'valid_mask': valid, 'reason_masks': reasons,
            'numerical_denominator_valid_mask': numerical_denominator_valid, 'metadata': {
        'operation': 'normalized_difference', 'indices': [a, b], 'units': 'dimensionless',
        'equation': '(a - b) / (a + b)', 'minimum_denominator': minimum_denominator,
        'denominator_rule': 'finite(a + b) and abs(a + b) >= minimum_denominator',
        'denominator_units': cube.metadata['units'], 'policy': policy,
        'low_signal_assessment': assessment, 'reason_counts': counts,
        'saturation_value': saturation,
        'saturation_assessment': 'UNKNOWN' if saturation is None else 'known source sample threshold',
        'count_semantics': 'HW pixels; source causes overlap across features and source_excluded. '
            'total = source_excluded + low_denominator + nonfinite_calculation + enabled low_signal + used; '
            'unknown low_signal is not a mask. Saturation is retained under diagnostic policy.',
        'calculation_dtype': 'float64', 'interpretation': 'descriptive contrast; no defect threshold'}}


def reference_rmse(cube, reference, *, bands=None, policy='diagnostic'):
    """Equal-feature RMSE from one fixed ROI vector; require every selected feature."""
    mapping = feature_selection(cube, bands)
    features = mapping['feature_indices']
    reference = np.asarray(reference, dtype=np.float64)
    if reference.shape != (cube.shape[2],) or not np.all(np.isfinite(reference[features])):
        raise ValueError('Reference must have one value per stored feature and be finite on all selected features')
    data = np.zeros(cube.shape[:2], dtype=np.float64)
    valid = np.ones(data.shape, dtype=bool)
    # Band-wise accumulation bounds working memory independently of cube depth.
    for index in features:
        plane, good = _band(cube, index, policy)
        delta = plane.astype(np.float64) - reference[index]
        with np.errstate(over='ignore', invalid='ignore'):
            data += np.square(np.where(good, delta, 0.))
        valid &= good
    np.sqrt(data / len(features), out=data)
    valid &= np.isfinite(data)
    data[~valid] = np.nan
    return {'data': data, 'valid_mask': valid, 'metadata': {
        **mapping, 'operation': 'reference_rmse', 'units': cube.metadata['units'],
        'reference': [float(value) if np.isfinite(value) else None for value in reference],
        'policy': policy, 'calculation_dtype': 'float64',
        'support': 'all selected features at each pixel', 'feature_weighting': 'equal',
        'equation': 'sqrt(mean((pixel - reference)**2))',
        'interpretation': 'descriptive reference contrast; no defect probability'}}
