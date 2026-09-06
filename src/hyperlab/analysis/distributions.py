"""Exact ROI distributions and spatial selections of already computed maps."""
from copy import deepcopy
import hashlib

import numpy as np

from hyperlab.io import Cube
from .core import _floating, _quality, roi_statistics


def _map_arrays(product):
    data, valid = np.asarray(product['data']), np.asarray(product['valid_mask'])
    if data.ndim != 2 or data.dtype.kind not in 'uif' or valid.shape != data.shape or valid.dtype != np.bool_:
        raise ValueError('Map distributions require one numeric HW map and its boolean HW validity mask')
    metadata = product.get('metadata', {})
    if metadata.get('preview_only') or metadata.get('sampled') or metadata.get('sampling') not in (None, 'exact'):
        raise ValueError('Preview or sampled maps cannot enter exact ROI distributions')
    return data, valid


def _selection(product, roi, exclusions):
    from .regions import resolve_roi
    data, valid = _map_arrays(product)
    region = resolve_roi(data.shape, roi, exclusions=exclusions)
    x0, y0, x1, y1 = region['bbox']
    selected = region['selected']
    plane = data[y0:y1, x0:x1]
    good = valid[y0:y1, x0:x1] & np.isfinite(plane)
    used = selected & good
    counts = {'geometry': int(np.count_nonzero(region['membership'])),
              'excluded': int(np.count_nonzero(region['excluded'])),
              'after_exclusion': int(np.count_nonzero(selected)),
              'invalid_after_exclusion': int(np.count_nonzero(selected & ~good)),
              'used': int(np.count_nonzero(used))}
    reasons = {}
    for name, mask in product.get('reason_masks', {}).items():
        mask = np.asarray(mask)
        if mask.shape != data.shape or mask.dtype != np.bool_:
            raise ValueError('Map reason masks must be boolean with the original HW shape')
        reasons[name] = int(np.count_nonzero(selected & mask[y0:y1, x0:x1]))
    identity = {key: deepcopy(region.get(key)) for key in
                ('roi_id', 'revision', 'role', 'name', 'color', 'coordinate_frame', 'descriptor',
                 'exclusion_definitions', 'membership_rule')}
    identity.update(bbox=list(region['bbox']), source_shape_hw=list(data.shape),
        membership_sha256=hashlib.sha256(region['membership'].tobytes()).hexdigest(),
        excluded_sha256=hashlib.sha256(region['excluded'].tobytes()).hexdigest())
    return region, plane, used, counts, reasons, identity


def map_roi_distributions(product, rois, *, exclusions=(), bins=64):
    """All selected finite map values; unique/count ECDF compression is exact."""
    if isinstance(bins, (bool, np.bool_)) or not isinstance(bins, (int, np.integer)) or not 1 <= bins <= 4096:
        raise ValueError('Histogram bins must be an integer from 1 to 4096')
    data, valid = _map_arrays(product)
    rois = list(rois)
    if not rois:
        raise ValueError('At least one ROI is required for map distributions')
    exclusions = tuple(exclusions)
    units = product.get('metadata', {}).get('units', 'unknown')
    # The existing statistics kernel supplies the same quantile/MAD/quality semantics.
    map_cube = Cube(data[..., None], {'data_level': 'derived_map', 'units': units}, valid)
    results = []
    for roi in rois:
        resolved, plane, used, counts, reasons, identity = _selection(product, roi, exclusions)
        stats = roi_statistics(map_cube, resolved)
        values = _floating(plane[used], np.float64)
        unique, frequency = np.unique(values, return_counts=True)
        cumulative = np.cumsum(frequency, dtype=np.int64)
        results.append({'roi': identity, 'counts': counts, 'reason_counts': reasons,
            'statistics': {key: float(stats[key][0]) if np.isfinite(stats[key][0]) else None for key in
                           ('mean', 'std', 'median', 'q25', 'q75', 'iqr', 'mad', 'min', 'max')},
            'ecdf': {'values': unique, 'counts': frequency, 'cumulative_counts': cumulative,
                     'fraction': cumulative/len(values) if len(values) else np.empty(0),
                     'sample_count': int(len(values))}})
    present = [result['ecdf']['values'] for result in results if result['counts']['used']]
    low, high = (min(values[0] for values in present), max(values[-1] for values in present)) if present else (0., 1.)
    if high == low:
        low, high = low-.5, high+.5
    edges = np.linspace(low, high, int(bins)+1)
    if not np.all(np.isfinite(edges)) or np.any(np.diff(edges) <= 0):
        raise ValueError('Shared histogram bounds are not representable as finite increasing float64 edges')
    for result in results:
        ecdf = result['ecdf']
        histogram, _ = np.histogram(ecdf['values'], bins=edges, weights=ecdf['counts'])
        count = result['counts']['used']
        result['histogram'] = {'bin_edges': edges.copy(), 'counts': histogram,
            'density': histogram/(count*np.diff(edges)) if count else np.full(int(bins), np.nan)}
    return {'regions': results, 'metadata': {'operation': 'map_roi_distribution', 'units': units,
        'aggregation_order': 'pixel_transform_then_summary', 'sampling': 'exact',
        'source_shape_hw': list(data.shape), 'map_recipe': deepcopy(product.get('metadata', {})),
        'ecdf_definition': 'F(v) = count(selected finite valid map values <= v) / n_used; unique/count compression is exact',
        'histogram_bins': int(bins), 'histogram_scope': 'shared edges over all selected ROIs; every valid map value used',
        'statistics': {'std_ddof': 0, 'quantile_method': 'linear', 'mad_scale': 'unscaled'},
        'count_semantics': 'geometry = excluded + invalid_after_exclusion + used; after_exclusion = invalid_after_exclusion + used',
        'reason_count_scope': 'map reason masks within the ROI after analyst exclusions; reasons may overlap',
        'interpretation': 'Spatial contrast distribution; pixels are not independent experimental observations or defect truth'}}


def brush_map(product, roi, value_range, *, exclusions=()):
    """Inclusive numeric range selects actual raw-coordinate pixels, never a probability."""
    bounds = np.asarray(value_range, np.float64)
    if bounds.shape != (2,) or not np.all(np.isfinite(bounds)) or bounds[0] > bounds[1]:
        raise ValueError('Brush range must contain finite increasing or equal lower/upper values')
    data, _ = _map_arrays(product)
    region, plane, used, counts, reasons, identity = _selection(product, roi, tuple(exclusions))
    selected = used & (plane >= bounds[0]) & (plane <= bounds[1])
    mask = np.zeros(data.shape, bool)
    x0, y0, x1, y1 = region['bbox']
    mask[y0:y1, x0:x1] = selected
    coordinates = np.argwhere(selected)
    coordinates += np.array([y0, x0], np.int64)
    selected_count = int(len(coordinates))
    return {'mask': mask, 'coordinates_yx': coordinates, 'values': _floating(plane[selected], np.float64),
        'metadata': {'operation': 'map_range_selection', 'label': 'Selected contrast pixels',
            'roi': identity, 'value_range': bounds.tolist(), 'range_rule': 'lower <= value <= upper',
            'units': product.get('metadata', {}).get('units', 'unknown'),
            'sampling': 'exact', 'aggregation_order': 'pixel_transform_then_summary',
            'counts': {**counts, 'selected': selected_count}, 'reason_counts': reasons,
            'selected_fraction_of_used': selected_count/counts['used'] if counts['used'] else None,
            'selected_fraction_of_geometry': selected_count/counts['geometry'] if counts['geometry'] else None,
            'coordinate_order': 'y, x; raw integer pixel indices',
            'pixel_centres': 'x+0.5, y+0.5 in raw raster geometry',
            'map_recipe': deepcopy(product.get('metadata', {})),
            'mask_sha256': hashlib.sha256(mask.tobytes()).hexdigest(),
            'interpretation': 'Analyst-selected contrast range; no defect probability, truth or calibrated physical area'}}


def spectral_interval_map(cube, *, bands=None, statistic='integral', policy='diagnostic',
                          max_gap_nm=None, measurement_gaps_nm=None):
    """Trapezoidal pixel feature on actual wavelengths with complete band support."""
    from hyperlab.io.cube import wavelength_unit_scale
    from .capabilities import feature_selection, require_capability
    from .roi_features import _gap_constraints, _physical_support
    require_capability(cube, 'spectral_features')
    if (cube.metadata.get('preview_only') or cube.metadata.get('sampled') or
            cube.metadata.get('sampling') not in (None, 'exact')):
        raise ValueError('Preview or sampled cubes cannot enter exact wavelength interval maps')
    if statistic not in {'integral', 'mean'}:
        raise ValueError('Interval statistic must be integral or mean')
    if policy not in {'diagnostic', 'quantitative'}:
        raise ValueError('Policy must be diagnostic or quantitative')
    selected = list(range(cube.shape[2])) if bands is None else list(bands)
    if any(isinstance(index, (bool, np.bool_)) for index in selected):
        raise ValueError('Interval bands must be original integer feature indices')
    mapping = feature_selection(cube, selected)
    if set(mapping['feature_indices']) != set(selected):
        raise ValueError('Selected spectral interval contains globally invalid bands')
    with np.errstate(over='ignore', invalid='ignore'):
        all_nm = cube.wavelengths*wavelength_unit_scale(cube.metadata['wavelength_units'])
    if not np.all(np.isfinite(all_nm)):
        raise ValueError('Wavelength conversion to nm must remain finite')
    indices = np.asarray(selected, int)[np.argsort(all_nm[selected])]
    x = all_nm[indices]
    if len(indices) < 2 or np.any(np.abs(np.diff(indices)) != 1):
        raise ValueError('Interval maps need at least two contiguous original bands without gaps')
    max_gap_nm, declared = _gap_constraints(max_gap_nm, cube.metadata.get('measurement_gaps_nm'))
    _, added = _gap_constraints(None, measurement_gaps_nm)
    _, gaps = _gap_constraints(None, declared+added)
    support = _physical_support(x, indices, max_gap_nm, gaps)
    span = x[-1]-x[0]
    # Positive normalized trapezoid weights avoid a spurious integral overflow
    # when a finite interval mean is requested; no resampling changes the axis.
    segment = np.diff(x)/span
    weights = np.zeros(len(x), np.float64)
    weights[:-1] += segment*.5
    weights[1:] += segment*.5
    data, joint = np.full(cube.shape[:2], np.nan), np.zeros(cube.shape[:2], bool)
    reasons = {name: np.zeros(cube.shape[:2], bool) for name in
               ('source_invalid', 'source_ignored', 'source_saturated')}
    saturation = None
    # Fixed spatial blocks plus one original band keep scratch memory independent of K.
    for y0 in range(0, cube.shape[0], 128):
        y1 = min(y0+128, cube.shape[0])
        mean = np.zeros((y1-y0, cube.shape[1]), np.float64)
        common = np.ones(mean.shape, bool)
        for position, index in enumerate(indices):
            selection = (slice(y0, y1), slice(None), slice(index, index+1))
            raw = cube.data[selection]
            good, quality, saturation = _quality(cube, raw, selection, policy)
            values = _floating(raw, np.float64)[:, :, 0]
            good = good[:, :, 0]
            common &= good
            for cause in ('invalid', 'ignored', 'saturated'):
                reasons['source_'+cause][y0:y1] |= quality[cause][:, :, 0]
            with np.errstate(over='ignore', invalid='ignore'):
                mean += np.where(good, values, 0.)*weights[position]
        joint[y0:y1] = common
        with np.errstate(over='ignore', invalid='ignore'):
            data[y0:y1] = mean*span if statistic == 'integral' else mean
    if saturation is None:
        reasons.pop('source_saturated')
    reasons.update(source_excluded=~joint,
        physical_gap_unsupported=joint & (not support['allowed']),
        nonfinite_calculation=joint & support['allowed'] & ~np.isfinite(data))
    valid = joint & support['allowed'] & np.isfinite(data)
    data[~valid] = np.nan
    counts = {name: int(mask.sum()) for name, mask in reasons.items()}
    counts.update(total=int(data.size), used=int(valid.sum()))
    counts.setdefault('source_saturated', None)
    source_units = cube.metadata['units']
    fwhm = cube.metadata.get('fwhm')
    fwhm_units = cube.metadata.get('fwhm_units', cube.metadata['wavelength_units'])
    fwhm_original = None if fwhm is None else np.asarray(fwhm, np.float64)[indices].tolist()
    scale = wavelength_unit_scale(fwhm_units)
    with np.errstate(over='ignore', invalid='ignore'):
        fwhm_nm = None if fwhm_original is None or scale is None else np.asarray(fwhm_original)*scale
    bandpass = {'fwhm_original': fwhm_original, 'fwhm_units': fwhm_units,
        'fwhm_nm': None if fwhm_nm is None or not np.all(np.isfinite(fwhm_nm)) else fwhm_nm.tolist(),
        'fwhm_unit_source': 'fwhm_units' if 'fwhm_units' in cube.metadata else 'wavelength_units (Cube/ENVI convention)',
        'response_evidence': deepcopy(cube.metadata.get('response_evidence')),
        'response_source': deepcopy(cube.metadata.get('response_source')),
        'response_calibration_id': (cube.metadata.get('measurement_context') or {}).get('response_calibration_id'),
        'note': 'Supplied bandwidth/response evidence, not a validation of spectral resolution.'}
    return {'data': data, 'valid_mask': valid, 'reason_masks': reasons, 'metadata': {
        'operation': 'spectral_interval_'+statistic, 'statistic': statistic,
        'units': f'{source_units}*nm' if statistic == 'integral' else source_units,
        'source_units': source_units, 'feature_indices': indices.tolist(),
        'wavelengths_nm': x.tolist(), 'wavelength_units': 'nm',
        'original_wavelengths': cube.wavelengths[indices].tolist(),
        'original_wavelength_units': cube.metadata['wavelength_units'],
        'actual_interval_nm': support['interval_nm'], 'interval_span_nm': float(span),
        'interval_support': support, 'max_gap_nm': max_gap_nm, 'measurement_gaps_nm': gaps,
        'gap_policy': 'contiguous original bands plus explicit physical gap constraints; no interpolation or extrapolation',
        'measurement_gap_rule': 'support interior must not intersect an explicitly excluded open interval',
        'bandpass_evidence': bandpass, 'wavelength_evidence': cube.metadata.get('wavelength_evidence'),
        'equation': 'sum((s[i]+s[i+1])/2 * (lambda[i+1]-lambda[i]))' + (' / wavelength span' if statistic == 'mean' else ''),
        'normalized_trapezoid_weights': weights.tolist(), 'policy': policy,
        'support': 'common over every selected original band', 'sampling': 'exact',
        'aggregation_order': 'pixel_transform_then_summary', 'calculation_dtype': 'float64',
        'saturation_value': saturation, 'reason_counts': counts,
        'count_semantics': 'total = source_excluded + physical_gap_unsupported + nonfinite_calculation + used; source causes may overlap',
        'source_provenance': deepcopy(cube.metadata),
        'interpretation': 'Pixel wavelength-interval feature; downstream ROI statistics summarize this completed map'}}
