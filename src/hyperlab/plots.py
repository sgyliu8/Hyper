"""Computed scientific plots shared by Qt and publication export."""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import csv
import json
import numpy as np

COLORS = ('#c47a28', '#2478b5', '#42907b', '#9665aa', '#c95670', '#5c7488', '#8b8339', '#725647')


def plain(value):
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def source_identity(cube):
    meta = cube.metadata
    return {key: plain(meta.get(key)) for key in ('source_file', 'session_id', 'stream_epoch',
        'sequence', 'frame_id', 'host_monotonic_ns', 'host_utc', 'device_timestamp_ns',
        'acquisition_source', 'data_source', 'data_level', 'display_mode', 'readback_settings',
        'quantitative_eligible', 'wavelength_evidence', 'wavelength_source', 'channel_labels')}


def map_limit_key(spec, robust=False):
    """Only share colour limits for the same numerical display definition."""
    meta = spec.metadata
    definition = {key: meta.get(key) for key in ('operation', 'component', 'indices',
        'feature_indices', 'feature_wavelengths', 'wavelength_units', 'units', 'reference', 'interval_nm', 'interval_span_nm')}
    definition.update(source_domain=spec.source.get('data_level'),
        source_units=spec.source.get('units'), feature_labels=spec.source.get('feature_labels'),
        semantic_center=meta.get('semantic_center'), normalization='linear',
        colormap=spec.colormap, robust=bool(robust))
    if spec.title.startswith('PCA'):
        definition['fit_source'] = meta.get('source_fingerprint') or spec.source
    return json.dumps(plain(definition), sort_keys=True, separators=(',', ':'))


def map_display_limits(spec, *, robust=False, locked_limits=None):
    """Set rendering limits only; Qt and Matplotlib use this same linear scale."""
    values = spec.image[spec.valid_mask & np.isfinite(spec.image)]
    center = spec.metadata.get('semantic_center')
    magnitude = spec.metadata.get('operation') == 'reference_rmse' or 'angle' in spec.title.lower()
    if values.size:
        low, high = np.percentile(values, [1, 99]) if robust else (values.min(), values.max())
    else:
        low, high = (center-1., center+1.) if center is not None else (0., 1.)
    if center is not None:
        radius = max(abs(float(low)-center), abs(float(high)-center), 1e-12)
        low, high = center-radius, center+radius
    else:
        if magnitude:
            low = 0.
        if high <= low:
            high = low + max(1., abs(float(low))*1e-6)
    if locked_limits is not None:
        low, high = map(float, locked_limits)
        if (not np.isfinite([low, high]).all() or low >= high or
                (center is not None and not np.isclose(low/2+high/2, center, rtol=0, atol=1e-12)) or
                (magnitude and low < 0)):
            raise ValueError('Shared colour limits must preserve the semantic center and magnitude domain')
    spec.limits = (float(low), float(high))
    clipped = int(np.count_nonzero((values < low) | (values > high)))
    spec.metadata['display_limits'] = {
        'policy':'1–99 percentile radius' if robust and center is not None else '1–99 percentile' if robust else 'full finite range',
        'normalization':'linear', 'semantic_center':center, 'shared_limits':locked_limits is not None,
        'shared_limit_key':map_limit_key(spec, robust), 'limits':list(spec.limits),
        'clipped_count':clipped, 'valid_count':int(values.size),
        'clipped_fraction':clipped/values.size if values.size else None,
        'scope':'Colour mapping only; source/map values, statistics and brush eligibility are unchanged'}
    return spec


@dataclass
class PlotSpec:
    kind: str
    title: str
    xlabel: str
    ylabel: str
    source: dict = field(default_factory=dict)
    series: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    image: np.ndarray | None = None
    valid_mask: np.ndarray | None = None
    colour_label: str = ''
    colormap: str = 'viridis'
    limits: tuple | None = None
    caption: str = ''
    categories: list | None = None
    brushes: list = field(default_factory=list)

    def record(self):
        record = {key: value for key, value in vars(self).items()
                  if key not in ('image', 'valid_mask', 'brushes')}
        if self.brushes:
            record['brushes'] = [brush['metadata'] for brush in self.brushes]
        return plain(record)


def roi_plot(results, names, colors, *, source, normalized=False, spatial_sd=True, summary='mean',
             categorical_style='connected'):
    if summary not in ('mean', 'median'):
        raise ValueError('ROI summary must be mean or median')
    if categorical_style not in ('connected', 'points'):
        raise ValueError('Categorical style must be connected or points')
    first = results[0]
    labels = first.get('channel_labels')
    wave = first.get('wavelengths')
    units = first.get('wavelength_units')
    single_plane = len(first['mean']) == 1
    if single_plane:
        normalized = False
    x = np.arange(len(first['mean'])) if wave is None or not units else np.asarray(wave)
    xlabel = ('Colour channel' if labels else f'Wavelength ({units})' if wave is not None and units
              else 'Scan state index' if len(x) > 1 else 'Sensor DN summary')
    common = np.all(np.isfinite([result[summary] for result in results]), axis=0)
    spec = PlotSpec('lines', 'ROI amplitude and spatial variation', xlabel,
                    f"{summary.title()} ({first.get('units', 'unknown')})", source=source, categories=labels,
                    metadata={'policy': first['policy'], 'spatial_sd': spatial_sd, 'std_ddof': 0,
                              'roi_comparison':True, 'single_sensor_plane':single_plane,
                              'summary':summary, 'support':first.get('support', 'per_band'),
                              'categorical_style':categorical_style if labels else 'connected',
                              'units':first.get('units', 'unknown'),
                              'normalization': 'L2 on common finite features' if normalized else None,
                              'common_feature_indices': np.flatnonzero(common).tolist(),
                              'excluded_indices': np.flatnonzero(~common).tolist()},
                    caption='Mean ± 1 spatial SD when enabled; pixel dispersion, not a confidence interval.')
    if summary == 'median':
        spec.caption = 'Median with Q25–Q75 spatial interval when enabled; pixel dispersion, not a confidence interval.'
    spec.caption += (' Common pixels across enabled features.' if first.get('support') == 'common'
                     else ' Per-feature valid pixels.')
    if single_plane:
        spec.title = f'ROI {summary} and spatial variation'
        spec.xlabel, spec.categories = 'Region of interest', list(names)
        spec.caption += ' Single sensor plane: comparing ROI intensities, not a spectrum; L2 shape is unavailable.'
        if any('distribution' in result for result in results):
            spec.metadata['distribution'] = '64 shared bins; all policy-valid ROI pixels; density integrates to one'
    for i, result in enumerate(results):
        means = np.array(result[summary], copy=True)
        sd = np.array(result['std'], copy=True)
        curve = {'name': names[i], 'color': colors[i], 'style': '-' if i % 2 == 0 else '--',
                 'x': np.array([i]) if single_plane else x.copy(), 'y': means,
                 'sd': sd if spatial_sd and summary == 'mean' else None,
                 'counts': result['counts'], 'used_counts':result['count'],
                 'saturation_value':result.get('saturation_value'),
                 'saturation_units':result.get('units', 'unknown'),
                 'rect': result['rect'], 'feature_indices': list(range(len(x)))}
        curve.update({key: plain(result.get('metadata', {}).get(key)) for key in
            ('roi_definition', 'exclusion_definitions', 'geometry_counts', 'geometry_semantics', 'membership_rule')})
        curve.update({key: np.array(result[key], copy=True) for key in
            ('geometry_excluded_count', 'support_excluded_count', 'selection_excluded_count') if key in result})
        if spatial_sd and summary == 'median':
            curve.update(lower=np.array(result['q25'], copy=True), upper=np.array(result['q75'], copy=True))
        if normalized:
            norm = np.linalg.norm(means[common])
            curve['normalized'] = np.where(common, means / norm, np.nan) if norm > 0 else np.full(means.shape, np.nan)
        if single_plane and 'distribution' in result:
            curve['distribution'] = result['distribution']
        spec.series.append(curve)
    return spec


def strip_profile_plot(result, *, source, source_fingerprint, analysis_context=None):
    """A completed spatial-bin profile with its captured source and denominators."""
    if not isinstance(source_fingerprint, dict) or not source_fingerprint.get('source_id'):
        raise ValueError('A profile plot requires the source fingerprint captured during calculation')
    if result.get('kind') != 'strip_profile':
        raise ValueError('A profile plot requires a completed strip_profile result')
    metadata = deepcopy(result['metadata'])
    metadata.update(operation='strip_profile', units=result['units'],
        summary='mean', support='per_band',
        source_fingerprint=deepcopy(source_fingerprint),
        aggregation_order='spatial_bin_then_summary', sample_axis='spatial bin index',
        bin_edges_px=np.asarray(result['bin_edges_px']).tolist(),
        geometry_count=np.asarray(result['geometry_count']).tolist(),
        excluded_count=np.asarray(result['excluded_count']).tolist(),
        selected_count=np.asarray(result['selected_count']).tolist())
    if analysis_context is not None:
        metadata['analysis_context'] = deepcopy(analysis_context)
    spec = PlotSpec('lines', 'Raw line / strip profile', 'Distance along path (px)',
        f"Mean ({result['units']})", source=deepcopy(source), metadata=metadata,
        caption='Mean ± 1 spatial SD within each cross-strip bin; not a confidence interval. '
                'Raw pixel centres projected onto the path; no interpolation or physical-length calibration.')
    n = len(result['position_px'])
    geometry = {key: np.array(result[value], copy=True) for key, value in
        (('geometry_count', 'geometry_count'), ('excluded_count', 'excluded_count'), ('selected_count', 'selected_count'))}
    for i, item in enumerate(result['curves']):
        spec.series.append({'name':item['label'], 'color':COLORS[i % len(COLORS)], 'style':'-',
            'x':np.array(result['position_px'], copy=True), 'y':np.array(item['mean'], copy=True),
            'sd':np.array(item['std'], copy=True), 'used_counts':np.array(item['count'], copy=True),
            'counts':deepcopy(item['counts']), 'geometry_counts':deepcopy(geometry),
            'geometry_excluded_count':np.array(item['geometry_excluded_count'], copy=True),
            'feature_indices':[int(item['feature_index'])]*n, 'sample_indices':list(range(n)),
            'bin_edges_px':np.array(result['bin_edges_px'], copy=True), 'position_units':'px',
            'roi_definition':deepcopy(metadata['roi_definition']),
            'exclusion_definitions':deepcopy(metadata['exclusion_definitions'])})
    return spec


def profile_bin_text(spec, distance):
    """Describe a full-origin profile bin, including unavailable bins and reasons."""
    edges = np.asarray(spec.metadata['bin_edges_px'])
    if not np.isfinite(distance) or distance < edges[0] or distance > edges[-1]:
        return 'Profile: hover within the recorded path distance.'
    index = min(len(edges)-2, int(np.searchsorted(edges, distance, side='right')-1))
    meta = spec.metadata
    text = (f"Bin {index} · {edges[index]:g}–{edges[index+1]:g} px · geometry {meta['geometry_count'][index]}"
            f" · excluded {meta['excluded_count'][index]} · selected {meta['selected_count'][index]}")
    for curve in spec.series:
        count = int(curve['used_counts'][index])
        reasons = ', '.join(f'{key} {int(values[index])}' for key, values in curve['counts'].items()
                            if key not in ('total', 'valid') and values[index])
        text += f"\n{curve['name']}: used {count} · " + ('unavailable' if not count else f"mean {curve['y'][index]:g}")
        if reasons:
            text += ' · ' + reasons + ' (reasons may overlap exclusions)'
    return text


def roi_transform_plot(amplitude_spec, task, *, reference=None, common=None, reference_roi_id=None):
    """One right-task summary transform; the amplitude plot stays unchanged."""
    if task not in ('shape', 'residual') or not amplitude_spec.series:
        raise ValueError('ROI transform needs amplitude series and a shape or residual task')
    spec = deepcopy(amplitude_spec)
    values = np.asarray([item['y'] for item in spec.series], np.float64)
    if common is None:
        common = np.all(np.isfinite(values), axis=0)
    common = np.asarray(common)
    if common.dtype != np.bool_ or common.shape != values.shape[1:]:
        raise ValueError('Common-feature support must be a matching boolean feature mask')
    common = common & np.all(np.isfinite(values), axis=0)
    if task == 'residual':
        reference = np.asarray(reference, np.float64)
        if reference.shape != values.shape[1:]:
            raise ValueError('Reference must match the original summary feature axis')
    for item in spec.series:
        for key in ('sd', 'lower', 'upper', 'normalized', 'distribution'):
            item.pop(key, None)
        y = np.asarray(item['y'], np.float64)
        if task == 'shape':
            finite_support = common & np.isfinite(y)
            # Scale before the norm so large finite amplitudes do not become a zero shape.
            scale = np.max(np.abs(y[finite_support])) if np.any(finite_support) else 0.
            norm = np.linalg.norm(y[finite_support]/scale) if scale else 0.
            with np.errstate(over='ignore', invalid='ignore'):
                item['y'] = np.where(finite_support, (y/scale)/norm, np.nan) if norm else np.full(y.shape, np.nan)
        else:
            with np.errstate(over='ignore', invalid='ignore'):
                residual = y-reference
            item['y'] = np.where(np.isfinite(y) & np.isfinite(reference) & np.isfinite(residual), residual, np.nan)
    source_units = amplitude_spec.metadata.get('units', 'unknown')
    summary = amplitude_spec.metadata.get('summary', 'mean')
    spec.title = 'L2 normalized shape' if task == 'shape' else 'ROI minus reference summary'
    spec.ylabel = f'Normalized {summary} (dimensionless)' if task == 'shape' else f'{summary.title()} residual ({source_units})'
    spec.caption = f'Transform of ROI {summary}; no propagated spatial SD/IQR, confidence interval or defect truth.'
    spec.brushes = []
    spec.metadata.pop('distribution', None)
    spec.metadata.update(right_task=task, roi_comparison=False, source_units=source_units,
        units='dimensionless' if task == 'shape' else source_units, spatial_sd=False,
        aggregation_order='summary_then_transform',
        normalization='L2 on common finite features' if task == 'shape' else None,
        common_feature_indices=np.flatnonzero(common).tolist(), excluded_indices=np.flatnonzero(~common).tolist(),
        finite_support='all included ROI common features' if task == 'shape' else 'finite target and reference summary pairs',
        reference_roi_id=reference_roi_id if task == 'residual' else None,
        reference_summary=None if task == 'shape' else plain(reference))
    return spec


def map_distribution_plot(result, names=None, colors=COLORS, *, source, mode='ecdf', brushes=()):
    """Exact map distributions; spatial brush arrays stay outside JSON plot records."""
    if mode not in ('ecdf', 'histogram'):
        raise ValueError('Map distribution mode must be ecdf or histogram')
    regions = result['regions']
    names = list(names) if names is not None else [item['roi'].get('name') or f'ROI {i+1}' for i, item in enumerate(regions)]
    if len(names) != len(regions):
        raise ValueError('Map distribution names must match ROI results')
    units = result['metadata']['units']
    title = 'Map value ECDF' if mode == 'ecdf' else 'Map value histogram'
    spec = PlotSpec('lines', title, f'Map value ({units})',
        'Cumulative fraction' if mode == 'ecdf' else 'Pixel count', source=source,
        metadata={**plain(result['metadata']), 'distribution_mode':mode,
                  'roi_results':plain([{key:item[key] for key in ('roi', 'counts', 'statistics', 'reason_counts')}
                                       for item in regions])}, brushes=list(brushes),
        caption='All eligible map pixels; exact spatial distribution. Map transform precedes ROI summary. '
                'Selected contrast pixels are not defect truth or independent experimental replicates.')
    signal_status = result['metadata'].get('map_recipe', {}).get('low_signal_assessment', {}).get('status')
    if signal_status:
        spec.caption += f' Low-signal assessment: {signal_status}.'
    for i, (name, item) in enumerate(zip(names, regions)):
        ecdf, histogram = item['ecdf'], item['histogram']
        spec.series.append({'name':name, 'color':item['roi'].get('color') or colors[i % len(colors)],
            'style':'-' if i % 2 == 0 else '--',
            'x':ecdf['values'] if mode == 'ecdf' else (histogram['bin_edges'][:-1]+histogram['bin_edges'][1:])*.5,
            'y':ecdf['fraction'] if mode == 'ecdf' else histogram['counts'],
            'drawstyle':'steps-post' if mode == 'ecdf' else 'steps-mid',
            'roi':item['roi'], 'sample_count':item['counts']['used'],
            'ecdf':ecdf, 'histogram':histogram})
    return spec


def map_plot(result, source, *, component=0, degrees=False, limits=None):
    meta = result['metadata']
    operation = meta.get('operation', 'PCA' if 'scores' in result else 'Derived map')
    data = np.asarray(result.get('data', result.get('image')))
    if data.ndim == 3:
        data = data[..., component]
    valid = np.asarray(result.get('valid_mask', np.isfinite(data)))
    if valid.ndim == 3:
        valid = valid[..., component]
    valid = valid & np.isfinite(data)
    units = meta.get('units', source.get('units', 'score'))
    center, cmap = None, 'viridis'
    title = operation
    pair = meta.get('indices', ['A', 'B'])
    labels = source.get('channel_labels')
    if labels and operation in ('difference', 'ratio', 'normalized_difference'):
        pair = [labels[index] for index in pair]
    if 'scores' in result:
        title = f'PCA · PC{component + 1} score'
        center, cmap = 0., 'RdBu_r'
    elif operation == 'difference':
        title = f"Difference · {pair[0]} − {pair[1]}"
        center, cmap = 0., 'RdBu_r'
    elif 'Angle' in operation:
        if degrees:
            data = np.rad2deg(data)
        units = 'deg' if degrees else 'rad'
        title = 'Spectral / state-vector angle'
    elif operation == 'ratio':
        title = f"Ratio · {pair[0]} / {pair[1]}"
        center, cmap, units = 1., 'RdBu_r', 'dimensionless'
    elif operation == 'normalized_difference':
        title = f"Normalized difference · {pair[0]}, {pair[1]}"
        center, cmap, units = 0., 'RdBu_r', 'dimensionless'
    elif operation == 'reference_rmse':
        title = 'Reference ROI RMSE'
    spec = PlotSpec('map', title, 'Raw x (pixel)', 'Raw y (pixel)', source=source,
                    metadata={**plain(meta), 'component': component, 'valid_count': int(valid.sum()),
                              'total_count': int(valid.size), 'semantic_center': center, 'units':units,
                              'coordinate_frame':{'origin':'upper left edge', 'extent':[0, data.shape[1], data.shape[0], 0],
                                  'pixel_centers':'x + 0.5, y + 0.5', 'array_indices':'integer (y, x)'}},
                    image=np.where(valid, data, np.nan), valid_mask=valid.copy(),
                    colour_label=f'{title} ({units})', colormap=cmap,
                    caption=(f"({pair[0]} − {pair[1]}) / ({pair[0]} + {pair[1]}). "
                             if operation == 'normalized_difference' else '') +
                    'Invalid / masked values are grey; an angle or score is not a defect probability.')
    return map_display_limits(spec, locked_limits=limits)


def roi_feature_plot(result, names, colors, *, source):
    """Use the computed recipe and feature values for both screen and export."""
    meta = result['metadata']
    titles = {'smooth':'Local polynomial smoothing', 'derivative1':'First wavelength derivative',
              'derivative2':'Second wavelength derivative', 'integral':'Measured interval amplitude',
              'continuum':'Endpoint continuum band depth'}
    spec = PlotSpec('lines', titles[meta['operation']], 'Wavelength (nm)',
        f"{meta['summary'].title()} feature ({meta['units']})", source=source,
        metadata=plain(meta), caption='Feature of the ROI summary; no transformed SD or confidence interval. '
        'Measured coordinates and missing intervals are retained.')
    spec.metadata['feature_results'] = plain([curve['features'] for curve in result['curves']])
    for curve in result['curves']:
        i = curve['roi_index']
        spec.series.append({'name':names[i], 'color':colors[i], 'style':'-' if i % 2 == 0 else '--',
            'x':curve['x_nm'], 'y':curve['y'], 'feature_indices':meta['feature_indices'],
            'rect':curve['rect'], 'used_counts':[curve['used_count']]*len(curve['y']),
            'invalid_reasons':curve['invalid_reasons']})
    return spec


def roi_pair_plot(cube, results, comparison, colors):
    meta = comparison['metadata']
    x = np.arange(cube.shape[2]) if cube.wavelengths is None else cube.wavelengths
    labels = cube.metadata.get('channel_labels')
    xlabel = 'Colour channel' if labels else (f"Wavelength ({cube.metadata['wavelength_units']})"
              if cube.wavelengths is not None else 'Stored feature index')
    spec = PlotSpec('lines', 'ROI residuals · target minus reference', xlabel,
        f"{meta['summary'].title()} difference ({meta['units']})", source=source_identity(cube),
        metadata={**plain(meta), 'pair_results':plain(comparison['pairs'])}, categories=labels,
        caption='One common finite feature set across all compared ROIs. Descriptive metrics; no p-values or defect probability.')
    for i, pair in enumerate(comparison['pairs']):
        residual = np.full(cube.shape[2], np.nan)
        features = meta['feature_indices']
        residual[features] = (np.asarray(results[pair['target_index']][meta['summary']])[features]
                              - np.asarray(results[pair['reference_index']][meta['summary']])[features])
        spec.series.append({'name':f"{pair['target']} − {pair['reference']}", 'color':colors[i % len(colors)],
                            'style':'-' if i % 2 == 0 else '--', 'x':x, 'y':residual})
    return spec


def pca_diagnostics(result, cube):
    meta = result['metadata']
    features = np.asarray(meta['feature_indices'], int)
    wave = cube.wavelengths
    units = cube.metadata.get('wavelength_units')
    x = np.arange(cube.shape[2]) if wave is None or not units else wave
    xlabel = f'Wavelength ({units})' if wave is not None and units else 'Scan state index'
    loads = PlotSpec('lines', 'PCA loadings', xlabel, 'Loading (dimensionless)',
                     source=source_identity(cube), metadata=plain(meta),
                     caption='PC signs are arbitrary. Gaps retain excluded features; no interpolation.')
    for i, vector in enumerate(result['components']):
        y = np.full(cube.shape[2], np.nan)
        y[features] = vector
        loads.series.append({'name': f'PC{i+1}', 'color': COLORS[i], 'style': '-', 'x': np.asarray(x), 'y': y})
    variance = PlotSpec('lines', 'PCA explained variance', 'Principal component', 'Explained variance ratio',
                        source=source_identity(cube), metadata=plain(meta),
                        series=[{'name': 'Explained variance', 'color': COLORS[1], 'style': '-',
                                 'x': np.arange(1, len(result['explained_variance_ratio'])+1),
                                 'y': np.asarray(result['explained_variance_ratio'])}],
                        caption='Variance explained is not classification accuracy.')
    return variance, loads


def sequence_coordinates(records):
    """Only compare host monotonic times in one known session; otherwise index."""
    if records and all(isinstance(r.get('host_monotonic_ns'), (int, float)) for r in records):
        sessions = {r.get('session_id') for r in records}
        values = np.array([r['host_monotonic_ns'] for r in records], np.float64)
        if len(sessions) == 1 and None not in sessions and np.all(np.diff(values) >= 0):
            return (values - values[0]) / 1e9, 'Recorded host receive elapsed time (s)'
    return np.arange(len(records), dtype=float), 'Recorded frame index (clock domain unavailable)'


class TemporalTrace:
    """At most one display sample per frame and definition; no redraw timestamps."""
    def __init__(self, capacity=300):
        self.capacity = capacity
        self.points = OrderedDict()
        self.definition = None
        self.segment = 0
        self.origin_ns = None
        self.xlabel = 'Host receive elapsed time (s)'

    def __len__(self):
        return len(self.points)

    def clear(self):
        self.points.clear()
        self.origin_ns = None
        self.definition = None

    def add(self, metadata, values, definition, *, sequence=None, index=None):
        key = json.dumps(plain(definition), sort_keys=True)
        if sequence is None:
            if metadata.get('display_mode') != 'LIVE' or metadata.get('host_monotonic_ns') is None:
                return False
            identity = (metadata.get('session_id'), metadata.get('stream_epoch', 0), metadata.get('sequence'))
            if identity[0] is None or identity[2] is None:
                return False
        else:
            identity = (str(sequence.path), index)
        if key != self.definition:
            self.clear()
            self.definition = key
            self.segment += 1
        if identity in self.points:
            return False
        if sequence is None:
            received = metadata['host_monotonic_ns']
            if self.origin_ns is None:
                self.origin_ns = received
            x = (received-self.origin_ns) / 1e9
            self.xlabel = 'Host receive elapsed time (s)'
        else:
            coordinates, self.xlabel = sequence_coordinates(sequence.metadata['frames'])
            x = coordinates[index]
        self.points[identity] = (float(x), *values)
        while len(self.points) > self.capacity:
            self.points.popitem(last=False)
        return True

    def plot(self, names, colors, source):
        values = np.asarray(sorted(self.points.values(), key=lambda p: p[0]))
        spec = PlotSpec('lines', f'ROI time trend · segment {self.segment}', self.xlabel, 'ROI mean (DN)',
                        source=source, metadata={'analysis_definition': self.definition, 'segment': self.segment,
                        'sampling': 'unique displayed/visited frames only; at most 300 retained',
                        'frame_identities': [list(key) for key in self.points]},
                        caption='Display-sampled frames; redraw timing is not a measurement clock.')
        if values.size:
            for i, name in enumerate(names):
                spec.series.append({'name': name, 'color': colors[i], 'style': '-', 'x': values[:, 0], 'y': values[:, i+1]})
        return spec


def render_figure(spec, *, width_mm=180, height_mm=115, dpi=300):
    """Render only precomputed PlotSpec numbers. No second analysis pipeline."""
    import matplotlib as mpl
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.patches import Patch
    with mpl.rc_context({'font.family':'DejaVu Sans', 'font.size':9, 'svg.fonttype':'none',
                         'pdf.fonttype':42, 'axes.spines.top':False, 'axes.spines.right':False}):
        distributions = any('distribution' in series for series in spec.series)
        shape_branch = distributions or any('normalized' in series for series in spec.series)
        figure = Figure(figsize=(width_mm/25.4, height_mm/25.4), dpi=dpi, layout='constrained')
        FigureCanvasAgg(figure)
        axes = figure.subplots(1, 2 if shape_branch else 1, squeeze=False)[0]
        ax = axes[0]
        ax.set(title=spec.title, xlabel=spec.xlabel, ylabel=spec.ylabel)
        if spec.image is not None:
            cmap = mpl.colormaps[spec.colormap].with_extremes(bad='#dce1e5')
            image = ax.imshow(np.ma.masked_invalid(spec.image), cmap=cmap,
                              vmin=spec.limits[0], vmax=spec.limits[1], interpolation='nearest', rasterized=True,
                              origin='upper', extent=(0, spec.image.shape[1], spec.image.shape[0], 0))
            figure.colorbar(image, ax=ax, label=spec.colour_label, shrink=.82)
            ax.legend(handles=[Patch(facecolor='#dce1e5', label='Invalid / masked')], loc='lower right', fontsize=7)
        for item in spec.series:
            x, y = np.asarray(item['x']), np.asarray(item['y'])
            categorical_points = bool(spec.categories) and spec.metadata.get('categorical_style') == 'points'
            if spec.metadata.get('distribution_mode') == 'histogram':
                ax.stairs(item['histogram']['counts'], item['histogram']['bin_edges'],
                          color=item['color'], label=item['name'], linestyle=item.get('style', '-'), linewidth=1.3)
            else:
                ax.plot(x, y, linestyle='none' if categorical_points else item.get('style', '-'),
                        drawstyle=item.get('drawstyle', 'default'), color=item['color'], label=item['name'],
                        marker=item.get('marker', 'o' if spec.categories or len(x) < 5 else None),
                        markersize=item.get('markersize',3), linewidth=1.3)
                if spec.metadata.get('distribution_mode') == 'ecdf' and len(x):
                    ax.vlines(x[0], 0., y[0], colors=item['color'], linewidth=1.3)
            if item.get('sd') is not None:
                sd = np.asarray(item['sd'])
                if len(x) == 1 or categorical_points:
                    ax.errorbar(x,y,yerr=sd,fmt='none',ecolor=item['color'],capsize=4,linewidth=1.3)
                else:
                    ax.fill_between(x, y-sd, y+sd, color=item['color'], alpha=.17)
            if item.get('lower') is not None:
                lower, upper = np.asarray(item['lower']), np.asarray(item['upper'])
                if len(x) == 1 or categorical_points:
                    ax.errorbar(x, y, yerr=np.stack((y-lower, upper-y)), fmt='none',
                                ecolor=item['color'], capsize=4, linewidth=1.3)
                else:
                    ax.fill_between(x, lower, upper, color=item['color'], alpha=.17)
            if 'distribution' in item:
                distribution = item['distribution']
                axes[1].plot(distribution['x'],distribution['y'],item.get('style','-'),
                             color=item['color'],label=item['name'],linewidth=1.3)
            if 'normalized' in item:
                axes[1].plot(x, item['normalized'], linestyle='none' if categorical_points else item.get('style', '-'),
                             marker='o' if categorical_points else None, color=item['color'], label=item['name'])
        if spec.metadata.get('distribution_mode') == 'ecdf':
            ax.set_ylim(0, 1.02)
        for brush in spec.brushes:
            ax.axvspan(*brush['metadata']['value_range'], color=brush['metadata']['roi'].get('color') or COLORS[0], alpha=.08)
        if spec.series:
            ax.legend(fontsize=7, frameon=False)
        elif spec.image is None:
            ax.text(.5, .5, 'No valid samples', ha='center', transform=ax.transAxes)
        for a in axes:
            if spec.image is None:
                a.grid(alpha=.16)
            if spec.categories and (a is ax or not distributions):
                a.set_xticks(range(len(spec.categories)), spec.categories)
        if distributions:
            units = spec.metadata.get('units', spec.ylabel.removeprefix('Mean (').removesuffix(')'))
            axes[1].set(title='ROI intensity distribution',xlabel=f'Pixel intensity ({units})',
                        ylabel=f'Probability density (1/{units})')
            axes[1].legend(fontsize=7,frameon=False)
        elif shape_branch:
            axes[1].set(title='L2 normalized shape', xlabel=spec.xlabel,
                        ylabel=f"Normalized {spec.metadata.get('summary', 'mean')} (dimensionless)")
        origin = spec.source.get('acquisition_source') or spec.source.get('data_source') or 'UNKNOWN'
        figure.suptitle(f'HyperLab · {origin} origin', fontsize=10, fontweight='bold')
        # Fixed caption area is part of the saved figure, not a clipped UI label.
        import textwrap
        figure.supxlabel('\n'.join(textwrap.wrap(spec.caption, 110)), fontsize=7)
        figure.canvas.draw()
        return figure


def recorded_roi_plot(sequence, rectangles, names, colors, *, policy='diagnostic', band=0, cancelled=None, exclusions=()):
    from .analysis import roi_statistics
    from .experiments import _setting_values, _unknown, matching_settings
    from .io import Cube
    from .io.labels import display_labels
    if sequence.frame_count < 1:
        raise ValueError('Recorded ROI analysis requires at least one persisted frame')
    x,xlabel = sequence_coordinates(sequence.metadata['frames'][:sequence.frame_count])
    values = np.full((len(rectangles),sequence.frame_count),np.nan)
    valid_counts = np.zeros_like(values,dtype=np.int64)
    channel, settings, settings_sources, records, identities = None, [], [], [], []
    for index in range(sequence.frame_count):
        if cancelled is not None and cancelled.is_set():
            raise InterruptedError('Recorded ROI analysis cancelled; no partial curve presented as complete')
        frame = sequence.frame(index)
        cube = Cube(frame.data if frame.data.ndim==3 else frame.data[...,None],dict(frame.metadata))
        if isinstance(band, (bool, np.bool_)) or not isinstance(band, (int, np.integer)) or not 0 <= band < cube.shape[2]:
            raise ValueError('Trace channel must be a stored feature index in every frame')
        label = display_labels(cube.metadata, cube.shape[2])[band]
        if channel is not None and label != channel:
            raise ValueError('Stored channel identity changed inside the sequence')
        channel = label
        record = dict(frame.metadata)
        records.append(record)
        identities.append(frame.identity if record.get('session_id') is not None and record.get('sequence') is not None else None)
        resolved = _setting_values(record)
        base = 'readback_settings' if record.get('readback_settings') else 'current_settings'
        sources = {key: base for key in resolved}
        for target, chunk in (('ExposureTime', 'ChunkExposureTime'), ('Gain', 'ChunkGain')):
            if not _unknown((record.get('chunk_settings') or {}).get(chunk)):
                sources[target] = 'chunk_settings.'+chunk
        settings.append(plain(resolved))
        settings_sources.append(sources)
        for i,rect in enumerate(rectangles):
            stats = roi_statistics(cube,rect,policy=policy,bands=[band],robust=False,exclusions=exclusions)
            values[i,index] = stats['mean'][band]
            valid_counts[i,index] = stats['count'][band]
    settings_check = matching_settings(records) if len(records) >= 2 else {
        'status': 'UNKNOWN', 'unknown': ['At least two observations required for settings consistency'],
        'mismatches': [], 'compared_fields': [], 'unavailable': [],
        'value_evidence': 'per-frame chunks where available, otherwise session readback'}
    status = settings_check['status']
    return PlotSpec('lines',f'ROI trend · channel {channel} · all recorded frames',xlabel,'ROI mean (DN)',
        source={'source_file':str(sequence.path),'acquisition_source':sequence.metadata.get('acquisition_source','UNKNOWN')},
        series=[{'name':name,'color':colors[i],'style':'-','x':x[:sequence.frame_count],'y':values[i],
                 'rect':rectangles[i],'valid_counts':valid_counts[i], 'sample_indices':list(range(sequence.frame_count)),
                 'feature_indices':[int(band)]*sequence.frame_count, 'frame_identities':identities}
                for i,name in enumerate(names)],
        metadata={'frame_count':sequence.frame_count,'sampling':'all persisted frames','policy':policy,
                  'channel_index':int(band),'channel_label':channel,'frame_settings':settings,
                  'frame_setting_sources':settings_sources, 'settings_check':settings_check,
                  'settings_match':None if status == 'UNKNOWN' else status == 'MATCH',
                  'pooling_qualification':'settings consistent only' if status == 'MATCH' else 'not qualified',
                  'recording':plain({k:v for k,v in sequence.metadata.items() if k != 'frames'})},
        caption='Recorded host clock or explicit frame index; missing samples remain gaps. No playback-clock timing. '
                f'Settings consistency: {status}. Raw observations; illumination and same-setting repeatability are not established.')


def export_figure_bundle(spec, directory, *, width_mm=180, height_mm=115, dpi=300,
                         source_cube=None, annotation=None):
    if not 60 <= width_mm <= 400 or not 50 <= height_mm <= 400 or not 72 <= dpi <= 1200:
        raise ValueError('Figure dimensions or DPI exceed the supported range')
    fingerprint = None
    if source_cube is not None:
        from hyperlab.experiment_metadata import source_fingerprint, write_analysis_manifest
        fingerprint = source_fingerprint(source_cube)
        expected = spec.metadata.get('source_fingerprint')
        if expected is not None and fingerprint != expected:
            raise ValueError('Source changed since this plot was computed; run analysis again before exporting.')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    record = spec.record()
    record.update(schema_version=1, renderer='Matplotlib', dimensions_mm=[width_mm, height_mm], dpi=dpi)
    from hyperlab import __version__
    record['hyperlab_version'] = __version__
    if spec.image is not None:
        np.save(directory/'values.npy', spec.image, allow_pickle=False)
        np.save(directory/'valid.npy', spec.valid_mask, allow_pickle=False)
        record.update(values_file='values.npy', valid_file='valid.npy')
    def sample(value, index):
        return value[index] if isinstance(value, (list, tuple, np.ndarray)) else value
    with (directory/'series.csv').open('x', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['series', 'feature_index', 'x', 'y', 'spatial_sd_ddof0', 'normalized',
                         'spatial_q25', 'spatial_q75', 'used_count', 'sample_index',
                         'channel_index', 'channel_label', 'frame_identity', 'settings_consistency',
                         'roi_id', 'roi_revision', 'geometry_count', 'excluded_geometry_count',
                         'geometry_excluded_count', 'support_excluded_count', 'selection_excluded_count',
                         'bin_left_px', 'bin_right_px', 'position_units', 'policy_valid_count',
                         'source_invalid_count', 'source_ignored_count', 'source_saturated_count', 'value_units',
                         'saturation_assessment', 'saturation_value', 'saturation_units'])
        for item in spec.series:
            indices, sample_indices = item.get('feature_indices'), item.get('sample_indices')
            identities = item.get('frame_identities')
            counts = item.get('used_counts', item.get('valid_counts'))
            sd, lower, upper = item.get('sd'), item.get('lower'), item.get('upper')
            definition, geometry = item.get('roi_definition') or item.get('roi') or {}, item.get('geometry_counts') or {}
            removed = [item.get(key) for key in ('geometry_excluded_count', 'support_excluded_count', 'selection_excluded_count')]
            quality, edges = item.get('counts', {}), item.get('bin_edges_px')
            saturation = item.get('saturation_value', spec.metadata.get('saturation_value'))
            saturation_known = 'saturated' in quality and saturation is not None and np.isfinite(saturation)
            saturation_assessment = ('ASSESSED' if saturation_known else 'UNKNOWN') if 'saturated' in quality else ''
            saturation_units = item.get('saturation_units', spec.metadata.get('source_units', spec.metadata.get('units', 'unknown')))
            for i, (x, y) in enumerate(zip(item['x'], item['y'])):
                writer.writerow([item['name'], indices[i] if indices is not None else '' if spec.metadata.get('distribution_mode') else i,
                                 x, y, sd[i] if sd is not None else '',
                                 item['normalized'][i] if 'normalized' in item else '',
                                 lower[i] if lower is not None else '', upper[i] if upper is not None else '',
                                 counts[i] if counts is not None else item.get('sample_count', ''),
                                 sample_indices[i] if sample_indices is not None else '',
                                 spec.metadata.get('channel_index', ''), spec.metadata.get('channel_label', ''),
                                 identities[i] if identities is not None else '',
                                 spec.metadata.get('settings_check', {}).get('status', ''),
                                 definition.get('roi_id', ''), definition.get('revision', ''),
                                 sample(geometry.get('geometry_count', ''), i), sample(geometry.get('excluded_count', ''), i),
                                 *[values[i] if values is not None else '' for values in removed],
                                 edges[i] if edges is not None else '', edges[i+1] if edges is not None else '',
                                 item.get('position_units', ''),
                                 *[sample(quality.get(key, ''), i) for key in ('valid', 'invalid', 'ignored')],
                                 sample(quality['saturated'], i) if saturation_known else '',
                                 spec.metadata.get('units', ''), saturation_assessment,
                                 saturation if saturation_known else '', saturation_units if saturation_assessment else ''])
    if any('distribution' in item for item in spec.series):
        with (directory/'distributions.csv').open('x',newline='',encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['series','bin_left','bin_right','bin_center','count','density'])
            for item in spec.series:
                d = item['distribution']
                for i,x in enumerate(d['x']):
                    writer.writerow([item['name'],d['bin_edges'][i],d['bin_edges'][i+1],x,d['counts'][i],d['y'][i]])
    if spec.metadata.get('distribution_mode'):
        with (directory/'ecdf.csv').open('x', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['series', 'roi_id', 'map_value', 'count_at_value', 'cumulative_count', 'cumulative_fraction', 'n_used'])
            for item in spec.series:
                ecdf = item['ecdf']
                for value, count, cumulative, fraction in zip(ecdf['values'], ecdf['counts'], ecdf['cumulative_counts'], ecdf['fraction']):
                    writer.writerow([item['name'], item['roi'].get('roi_id'), value, count, cumulative, fraction, item['sample_count']])
        with (directory/'map_histograms.csv').open('x', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['series', 'roi_id', 'bin_left', 'bin_right', 'count', 'density', 'n_used'])
            for item in spec.series:
                histogram = item['histogram']
                for i, count in enumerate(histogram['counts']):
                    writer.writerow([item['name'], item['roi'].get('roi_id'), histogram['bin_edges'][i],
                        histogram['bin_edges'][i+1], count, histogram['density'][i], item['sample_count']])
    for index, brush in enumerate(spec.brushes):
        mask_name, coordinates_name = f'brush_{index+1:02d}_mask.npy', f'brush_{index+1:02d}_coordinates.csv'
        np.save(directory/mask_name, brush['mask'], allow_pickle=False)
        metadata = brush['metadata']
        with (directory/coordinates_name).open('x', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['roi_id', 'roi_revision', 'raw_y_index', 'raw_x_index', 'map_value', 'units'])
            for (y, x), value in zip(brush['coordinates_yx'], brush['values']):
                writer.writerow([metadata['roi'].get('roi_id'), metadata['roi'].get('revision'), y, x, value, metadata['units']])
        record['brushes'][index].update(mask_file=mask_name, coordinates_file=coordinates_name)
    (directory/'plot.json').write_text(json.dumps(record, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    figure = render_figure(spec, width_mm=width_mm, height_mm=height_mm, dpi=dpi)
    import matplotlib as mpl
    with mpl.rc_context({'svg.fonttype':'none', 'pdf.fonttype':42}):
        for extension in ('svg', 'pdf', 'png'):
            figure.savefig(directory/f'figure.{extension}', dpi=dpi)
    if source_cube is not None:
        if source_fingerprint(source_cube) != fingerprint:
            raise ValueError('Source changed during export; partial outputs retained without a COMPLETE manifest.')
        write_analysis_manifest(directory, fingerprint, spec.record(), annotation=annotation)
    return directory
