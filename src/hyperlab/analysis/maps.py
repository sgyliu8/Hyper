"""Interpretable material contrast maps with fixed feature support."""
import numpy as np

from .capabilities import feature_selection, require_capability
from .core import _band


def normalized_difference(cube, a, b, *, minimum_denominator=1e-6, policy='diagnostic'):
    require_capability(cube, 'ratio')
    if a == b:
        raise ValueError('Normalized difference requires distinct features')
    if not np.isfinite(minimum_denominator) or minimum_denominator <= 0:
        raise ValueError('minimum_denominator must be finite and positive')
    first, ga = _band(cube, a, policy)
    second, gb = _band(cube, b, policy)
    first, second = first.astype(np.float64), second.astype(np.float64)
    denominator = first + second
    valid = ga & gb & (np.abs(denominator) >= minimum_denominator)
    data = np.full(first.shape, np.nan)
    np.divide(first - second, denominator, out=data, where=valid)
    valid &= np.isfinite(data)
    data[~valid] = np.nan
    return {'data': data, 'valid_mask': valid, 'metadata': {
        'operation': 'normalized_difference', 'indices': [a, b], 'units': 'dimensionless',
        'equation': '(a - b) / (a + b)', 'minimum_denominator': minimum_denominator,
        'denominator_rule': 'abs(a + b) >= minimum_denominator', 'policy': policy,
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
