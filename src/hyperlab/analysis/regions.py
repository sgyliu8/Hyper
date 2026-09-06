"""Deterministic ROI membership in raw pixel coordinates, independent of display."""
from collections.abc import Mapping
from copy import deepcopy
import hashlib
import io
import math
from pathlib import Path
from uuid import uuid4

import numpy as np


def _shape(shape):
    shape = tuple(shape[:2])
    if len(shape) != 2 or any(isinstance(value, (bool, np.bool_)) or
            not isinstance(value, (int, np.integer)) or value < 1 for value in shape):
        raise ValueError('ROI source shape must be positive raw height and width')
    return tuple(int(value) for value in shape)


def _frame(shape):
    return {'kind': 'raw_pixels', 'shape_hw': list(shape), 'origin': 'top_left',
            'pixel_centres': [.5, .5]}


def _points(values, minimum):
    points = np.asarray(values, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < minimum or not np.all(np.isfinite(points)):
        raise ValueError(f'Geometry requires at least {minimum} finite x,y points')
    return points


def _read_mask(path, shape):
    path = Path(path).resolve()
    payload = path.read_bytes()
    if path.suffix.lower() == '.npy':
        mask = np.load(io.BytesIO(payload), allow_pickle=False)
    else:
        from PIL import Image
        with Image.open(io.BytesIO(payload)) as image:
            mask = np.array(image)
    if mask.shape != shape or mask.dtype.kind not in 'buif':
        raise ValueError('Binary mask must have exactly the known raw HW shape')
    if not (np.all((mask == 0) | (mask == 1)) or np.all((mask == 0) | (mask == 255))):
        raise ValueError('Binary mask must contain only 0/1 or 0/255 values')
    mask = np.asarray(mask != 0, dtype=bool)
    return mask, {'path': str(path), 'sha256': hashlib.sha256(payload).hexdigest(),
        'mask_sha256': hashlib.sha256(mask.tobytes(order='C')).hexdigest(),
        'size_bytes': len(payload), 'shape_hw': list(shape),
        'encoding': 'binary nonzero; 0/1 or 0/255, no inferred rescaling'}


def mask_geometry(path, shape_hw):
    """Inspect one binary asset; later use verifies these exact bytes and samples."""
    _, asset = _read_mask(path, _shape(shape_hw))
    return {'type': 'mask', **asset}


def _geometry(geometry):
    if not isinstance(geometry, Mapping):
        raise ValueError('ROI geometry must be a mapping')
    result = deepcopy(dict(geometry))
    kind = result.get('type')
    if kind == 'rectangle':
        bounds = np.asarray(result.get('bounds'), dtype=float)
        if bounds.shape != (4,) or not np.all(np.isfinite(bounds)) or np.any(bounds[2:] < bounds[:2]):
            raise ValueError('Rectangle bounds must be finite ordered x0,y0,x1,y1')
        result['bounds'] = bounds.tolist()
    elif kind == 'polygon':
        result['vertices'] = _points(result.get('vertices'), 3).tolist()
        result['holes'] = [_points(ring, 3).tolist() for ring in result.get('holes', [])]
    elif kind == 'strip':
        points = _points(result.get('points'), 2)
        width = result.get('width_px')
        if isinstance(width, (bool, np.bool_)) or not isinstance(width, (int, float, np.number)) or not np.isfinite(width) or width <= 0:
            raise ValueError('Strip width_px must be finite and positive')
        if not np.any(np.diff(points, axis=0)):
            raise ValueError('Strip requires at least two distinct points')
        result.update(points=points.tolist(), width_px=float(width))
    elif kind == 'mask':
        if not all(result.get(key) for key in ('path', 'sha256', 'mask_sha256', 'shape_hw')):
            raise ValueError('Mask geometry requires inspected asset and logical-mask hashes and shape')
    else:
        raise ValueError('Geometry type must be rectangle, polygon, mask or strip')
    return result


def make_roi(shape_hw, geometry, *, name='ROI', color='#c47a28', role='target',
             roi_id=None, revision=1, visible=True, included=True):
    """Create an explicit stable definition; callers retain its id across revisions."""
    shape = _shape(shape_hw)
    if role not in ('reference', 'target', 'exclude'):
        raise ValueError('ROI role must be reference, target or exclude')
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError('ROI revision must be a positive integer')
    if not all(isinstance(value, str) and value.strip() for value in (name, color)):
        raise ValueError('ROI name and color must be nonempty text')
    if roi_id is not None and (not isinstance(roi_id, str) or not roi_id.strip()):
        raise ValueError('ROI id must be nonempty text')
    if not isinstance(visible, bool) or not isinstance(included, bool):
        raise ValueError('ROI visible and included flags must be explicit Booleans')
    return {'schema_version': 1, 'roi_id': roi_id or str(uuid4()), 'revision': revision,
        'name': name, 'color': color, 'role': role, 'visible': visible, 'included': included,
        'coordinate_frame': _frame(shape), 'geometry': _geometry(geometry)}


def _definition(shape, roi):
    if not isinstance(roi, Mapping):
        if len(roi) != 4 or any(isinstance(value, (bool, np.bool_)) or
                not isinstance(value, (int, np.integer)) for value in roi):
            raise ValueError('ROI must contain four integer coordinates')
        x0, y0, x1, y1 = map(int, roi)
        h, w = shape
        if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
            raise ValueError('ROI is empty or outside image')
        record = make_roi(shape, {'type': 'rectangle', 'bounds': [x0, y0, x1, y1]}, roi_id='legacy_rectangle')
        record['roi_id'] = None  # Legacy rectangle callers have not declared a stable id.
        return record
    if type(roi.get('schema_version')) is not int or roi['schema_version'] != 1 or roi.get('coordinate_frame') != _frame(shape):
        raise ValueError('ROI schema or raw coordinate frame does not match this source')
    if any(key not in roi for key in ('name', 'color', 'role', 'roi_id', 'revision', 'visible', 'included')):
        raise ValueError('ROI definition is missing identity, role or presentation fields')
    return make_roi(shape, roi.get('geometry'), **{key: roi[key] for key in
        ('name', 'color', 'role', 'roi_id', 'revision', 'visible', 'included')})


def _bounds(shape, bounds):
    h, w = shape
    x0, y0, x1, y1 = bounds
    return (max(0, min(w, math.ceil(x0 - .5))), max(0, min(h, math.ceil(y0 - .5))),
            max(0, min(w, math.ceil(x1 - .5))), max(0, min(h, math.ceil(y1 - .5))))


def _polygon(points, x, y):
    # Even-odd + half-open ray crossing. For axis-aligned rectangles this
    # includes left/top boundaries and excludes right/bottom boundaries.
    inside = np.zeros((y.shape[0], x.shape[1]), dtype=bool)
    for (x0, y0), (x1, y1) in zip(points, np.roll(points, -1, axis=0)):
        if y0 != y1:
            inside ^= ((y0 > y) != (y1 > y)) & (x < (x1-x0) * (y-y0) / (y1-y0) + x0)
    return inside


def _canonical_strip(points):
    points = np.asarray(points, dtype=float)
    reverse = bool(tuple(map(tuple, points[::-1])) < tuple(map(tuple, points)))
    return (points[::-1] if reverse else points), reverse


def _membership(shape, definition):
    geometry = definition['geometry']
    kind = geometry['type']
    if kind == 'mask':
        if geometry['shape_hw'] != list(shape):
            raise ValueError('Mask asset shape does not match the raw coordinate frame')
        mask, asset = _read_mask(geometry['path'], shape)
        if any(asset[key] != geometry[key] for key in ('sha256', 'mask_sha256')):
            raise ValueError('Mask asset changed since its ROI definition was created')
        yy, xx = np.nonzero(mask)
        bbox = (int(xx.min()), int(yy.min()), int(xx.max())+1, int(yy.max())+1) if xx.size else (0, 0, 0, 0)
        x0, y0, x1, y1 = bbox
        return bbox, mask[y0:y1, x0:x1].copy()
    if kind == 'rectangle':
        bbox = _bounds(shape, geometry['bounds'])
    else:
        points = np.asarray(geometry['vertices' if kind == 'polygon' else 'points'])
        margin = geometry['width_px'] / 2 if kind == 'strip' else 0
        low, high = points.min(axis=0) - margin, points.max(axis=0) + margin
        # Include strip centres exactly on the closed round-cap boundary.
        if kind == 'strip':
            high = np.nextafter(high, np.inf)
        bbox = _bounds(shape, [*low, *high])
    x0, y0, x1, y1 = bbox
    yy, xx = np.ogrid[y0:y1, x0:x1]
    x, y = xx + .5, yy + .5
    if kind == 'rectangle':
        membership = np.ones((y1-y0, x1-x0), dtype=bool)
    elif kind == 'polygon':
        membership = _polygon(points, x, y)
        for hole in geometry['holes']:
            membership &= ~_polygon(np.asarray(hole), x, y)
    else:
        membership = np.zeros((y1-y0, x1-x0), dtype=bool)
        points, _ = _canonical_strip(points)
        for start, end in zip(points[:-1], points[1:]):
            delta = end - start
            squared = float(delta @ delta)
            if squared:
                t = np.clip(((x-start[0])*delta[0] + (y-start[1])*delta[1]) / squared, 0, 1)
                distance2 = (x-start[0]-t*delta[0])**2 + (y-start[1]-t*delta[1])**2
                membership |= distance2 <= (geometry['width_px'] / 2)**2
    return bbox, membership


def resolve_roi(shape_hw, roi, *, exclusions=()):
    """Resolve local HW masks; geometry counts precede analyst exclusion.

    Polygon rings use pixel centres and even-odd half-open ray crossings.
    Strips are the union of closed radius width_px/2 capsules around segments,
    including exact distance ties. Width is geometric pixels, not measured mm.
    Visibility never affects membership. Callers choose calculation-included ROIs.
    """
    shape = _shape(shape_hw)
    exclusions = tuple(exclusions)
    if isinstance(roi, Mapping) and roi.get('kind') == 'resolved_roi':
        if exclusions or tuple(roi.get('source_shape_hw', ())) != shape:
            raise ValueError('Resolved ROI must retain its source shape and original exclusions')
        x0, y0, x1, y1 = roi['bbox']
        masks = [roi[key] for key in ('membership', 'excluded', 'selected')]
        if not (0 <= x0 <= x1 <= shape[1] and 0 <= y0 <= y1 <= shape[0]) or any(
                not isinstance(mask, np.ndarray) or mask.dtype != bool or mask.shape != (y1-y0, x1-x0) for mask in masks):
            raise ValueError('Resolved ROI masks do not match their raw bounding box')
        if np.any(masks[1] & ~masks[0]) or not np.array_equal(masks[2], masks[0] & ~masks[1]):
            raise ValueError('Resolved ROI membership and exclusion masks are inconsistent')
        if any(roi.get(key) != int(mask.sum()) for key, mask in zip(
                ('geometry_count', 'excluded_count', 'selected_count'), masks)):
            raise ValueError('Resolved ROI counts do not match membership')
        return roi
    definition = _definition(shape, roi)
    bbox, membership = _membership(shape, definition)
    x0, y0, x1, y1 = bbox
    excluded = np.zeros(membership.shape, dtype=bool)
    definitions = []
    for item in exclusions:
        other = _definition(shape, item)
        if not other['included']:
            continue
        other_bbox, mask = _membership(shape, other)
        ex0, ey0, ex1, ey1 = other_bbox
        ix0, iy0, ix1, iy1 = max(x0, ex0), max(y0, ey0), min(x1, ex1), min(y1, ey1)
        if ix0 < ix1 and iy0 < iy1:
            excluded[iy0-y0:iy1-y0, ix0-x0:ix1-x0] |= mask[iy0-ey0:iy1-ey0, ix0-ex0:ix1-ex0]
        definitions.append(other)
    excluded &= membership
    selected = membership & ~excluded
    for mask in (membership, excluded, selected):
        mask.flags.writeable = False
    return {'kind': 'resolved_roi', 'source_shape_hw': list(shape), 'bbox': bbox,
        'membership': membership, 'excluded': excluded, 'selected': selected,
        **{key: definition[key] for key in ('roi_id', 'revision', 'role', 'name', 'color', 'coordinate_frame', 'included', 'visible')},
        'descriptor': definition, 'exclusion_definitions': definitions,
        'geometry_count': int(membership.sum()), 'excluded_count': int(excluded.sum()),
        'selected_count': int(selected.sum()),
        'membership_rule': 'Raw pixel centres; rectangle/polygon half-open ray rule; strip closed Euclidean capsule; binary mask exact'}


def strip_profile(cube, roi, *, bands=None, policy='diagnostic', exclusions=(), bin_width_px=1.0):
    """Aggregate exact strip pixels by projected path distance, without interpolation.

    Nearest segment and half-open bin ties are resolved in canonical endpoint
    order; reversing the requested path reverses every profile bin exactly.
    Round-cap pixels project to the endpoints. SD describes pixel dispersion.
    """
    from .capabilities import feature_selection
    from .core import _floating, _roi_band
    from hyperlab.io.labels import display_labels

    region = resolve_roi(cube.shape[:2], roi, exclusions=exclusions)
    geometry = region['descriptor']['geometry']
    if geometry['type'] != 'strip':
        raise ValueError('A strip profile requires a strip ROI with a pixel width')
    if isinstance(bin_width_px, (bool, np.bool_)) or not isinstance(bin_width_px, (int, float, np.number)) or not np.isfinite(bin_width_px) or bin_width_px <= 0:
        raise ValueError('Profile bin_width_px must be finite and positive')
    requested = None if bands is None else list(bands)
    if requested is not None and any(isinstance(value, (bool, np.bool_)) for value in requested):
        raise ValueError('Profile feature indices must be integer indices, not Booleans')
    features = feature_selection(cube, requested)
    labels = display_labels(cube.metadata, cube.shape[2])
    points, reversed_output = _canonical_strip(geometry['points'])
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    distance = np.r_[0., np.cumsum(lengths)]
    length = float(distance[-1])
    if not np.isfinite(length) or length <= 0 or length / bin_width_px > 100000:
        raise ValueError('Profile needs a finite positive path and at most 100000 bins; choose a wider bin width')
    bins = max(1, math.ceil(length / bin_width_px))
    edges = np.linspace(0., length, bins + 1)
    local_y, local_x = np.nonzero(region['membership'])
    x0, y0, _, _ = region['bbox']
    x, y = local_x + x0 + .5, local_y + y0 + .5
    nearest = np.full(len(x), np.inf)
    position = np.zeros(len(x))
    for index, (start, end, segment_length) in enumerate(zip(points[:-1], points[1:], lengths)):
        if segment_length == 0:
            continue
        delta = end - start
        t = np.clip(((x-start[0])*delta[0] + (y-start[1])*delta[1]) / (segment_length**2), 0., 1.)
        squared = (x-start[0]-t*delta[0])**2 + (y-start[1]-t*delta[1])**2
        closer = squared < nearest
        nearest[closer] = squared[closer]
        position[closer] = distance[index] + t[closer]*segment_length
    indices = np.clip(np.searchsorted(edges, position, side='right') - 1, 0, bins - 1)
    boundary_arithmetic = 'Multiple segments: float64 projected distances and edges; no snapping tolerance'
    active_segments = np.flatnonzero(lengths)
    if len(active_segments) == 1:
        # For one segment the length root cancels: bin coordinate = dot*bins/S.
        # A float error envelope triggers exact comparison, never edge snapping.
        from fractions import Fraction
        start, end = points[active_segments[0]:active_segments[0]+2]
        delta = end-start
        squared_length = float(delta @ delta)
        along_x, along_y = (x-start[0])*delta[0], (y-start[1])*delta[1]
        scaled = ((along_x+along_y)/squared_length)*bins
        indices = np.floor(np.clip(scaled, 0, bins-1)).astype(np.int64)
        boundary = np.rint(scaled)
        error_bound = 16*np.finfo(float).eps*np.maximum(1., ((abs(along_x)+abs(along_y))/squared_length)*bins)
        ambiguous = np.flatnonzero((boundary > 0) & (boundary < bins) & (abs(scaled-boundary) <= error_bound))
        if ambiguous.size:
            sx, sy = (Fraction(float(value)) for value in start)
            dx, dy = Fraction(float(end[0]))-sx, Fraction(float(end[1]))-sy
            exact_squared = dx*dx+dy*dy
            for sample in ambiguous:
                edge = int(boundary[sample])
                dot = (Fraction(float(x[sample]))-sx)*dx+(Fraction(float(y[sample]))-sy)*dy
                indices[sample] = edge if dot*bins >= exact_squared*edge else edge-1
        boundary_arithmetic = 'Single segment: normalized projection; exact binary-input rational comparisons near bin edges; no snapping tolerance'
    member = region['membership']
    selected, excluded = region['selected'][member], region['excluded'][member]

    def counts(keep):
        return np.bincount(indices[keep], minlength=bins).astype(np.int64)

    def orient(values):
        return values[::-1].copy() if reversed_output else values

    curves = []
    for band in features['feature_indices']:
        raw, good, quality, saturation = _roi_band(cube, region, band, policy)
        policy_good = good[..., 0][member]
        used = policy_good & selected
        bin_index = indices[used]
        values = _floating(raw[..., 0][member][used], dtype=np.float64)
        count = counts(used)
        mean = np.divide(np.bincount(bin_index, weights=values, minlength=bins), count,
                         out=np.full(bins, np.nan), where=count > 0)
        variance = np.divide(np.bincount(bin_index, weights=(values-mean[bin_index])**2, minlength=bins),
                             count, out=np.full(bins, np.nan), where=count > 0)
        curves.append({'feature_index': band, 'label': labels[band], 'mean': orient(mean),
            'std': orient(np.sqrt(variance)), 'count': orient(count),
            'counts': {key: orient(counts(mask[..., 0][member])) for key, mask in quality.items()},
            'geometry_excluded_count': orient(counts(policy_good & excluded))})
    return {'kind': 'strip_profile', 'position_px': (edges[:-1] + edges[1:]) / 2,
        'bin_edges_px': edges, 'geometry_count': orient(counts(np.ones(len(x), dtype=bool))),
        'excluded_count': orient(counts(excluded)), 'selected_count': orient(counts(selected)),
        'curves': curves, 'units': cube.metadata['units'], 'metadata': {
            'roi_definition': deepcopy(region['descriptor']),
            'exclusion_definitions': deepcopy(region['exclusion_definitions']),
            'source_provenance': deepcopy(cube.metadata), 'policy': policy, **features,
            'path_length_px': length, 'requested_bin_width_px': float(bin_width_px),
            'actual_bin_width_px': length / bins, 'width_px': geometry['width_px'],
            'position_units': 'px', 'position_origin': 'first requested path point',
            'canonical_path_points': points.tolist(), 'output_reversed': reversed_output,
            'projection': 'Raw pixel centres to nearest path segment; ties choose first canonical segment; round caps clamp to endpoints',
            'binning': 'Equal canonical half-open distance bins, last endpoint included; reverse bin arrays for the requested path direction',
            'bin_boundary_arithmetic': boundary_arithmetic,
            'aggregation': 'Unweighted per-feature mean of policy-valid selected raw pixels in each cross-strip bin; no signal interpolation',
            'std_ddof': 0, 'std_interpretation': 'spatial SD, not uncertainty of the mean or temporal noise',
            'count_semantics': 'geometry_count is membership before exclusions; excluded_count may overlap source quality reasons; count + geometry_excluded_count = counts.valid',
            'empty_bins': 'count zero and mean/SD NaN', 'saturation_value': saturation}}
