"""Computed scientific plots shared by Qt and publication export."""
from collections import OrderedDict
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

    def record(self):
        return plain({key: value for key, value in vars(self).items()
                      if key not in ('image', 'valid_mask')})


def roi_plot(results, names, colors, *, source, normalized=False, spatial_sd=True):
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
    common = np.all(np.isfinite([result['mean'] for result in results]), axis=0)
    spec = PlotSpec('lines', 'ROI amplitude and spatial variation', xlabel,
                    f"Mean ({first.get('units', 'unknown')})", source=source, categories=labels,
                    metadata={'policy': first['policy'], 'spatial_sd': spatial_sd, 'std_ddof': 0,
                              'roi_comparison':True, 'single_sensor_plane':single_plane,
                              'normalization': 'L2 on common finite features' if normalized else None,
                              'common_feature_indices': np.flatnonzero(common).tolist(),
                              'excluded_indices': np.flatnonzero(~common).tolist()},
                    caption='Mean ± 1 spatial SD when enabled; pixel dispersion, not a confidence interval.')
    if single_plane:
        spec.title = 'ROI mean and spatial variation'
        spec.xlabel, spec.categories = 'Region of interest', list(names)
        spec.caption += ' Single sensor plane: comparing ROI intensities, not a spectrum; L2 shape is unavailable.'
        if any('distribution' in result for result in results):
            spec.metadata['distribution'] = '64 shared bins; all policy-valid ROI pixels; density integrates to one'
    for i, result in enumerate(results):
        means = np.array(result['mean'], copy=True)
        sd = np.array(result['std'], copy=True)
        curve = {'name': names[i], 'color': colors[i], 'style': '-' if i % 2 == 0 else '--',
                 'x': np.array([i]) if single_plane else x.copy(), 'y': means, 'sd': sd if spatial_sd else None,
                 'counts': result['counts'], 'rect': result['rect'], 'feature_indices': list(range(len(x)))}
        if normalized:
            norm = np.linalg.norm(means[common])
            curve['normalized'] = np.where(common, means / norm, np.nan) if norm > 0 else np.full(means.shape, np.nan)
        if single_plane and 'distribution' in result:
            curve['distribution'] = result['distribution']
        spec.series.append(curve)
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
    if labels and operation in ('difference', 'ratio'):
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
    values = data[valid]
    if limits is None:
        low, high = (float(values.min()), float(values.max())) if values.size else (0., 1.)
        if center is not None:
            radius = max(abs(low-center), abs(high-center), 1e-12)
            low, high = center-radius, center+radius
        elif high <= low:
            high = low + 1
        limits = (low, high)
    return PlotSpec('map', title, 'Raw x (pixel)', 'Raw y (pixel)', source=source,
                    metadata={**plain(meta), 'component': component, 'valid_count': int(valid.sum()),
                              'total_count': int(valid.size), 'semantic_center': center},
                    image=np.where(valid, data, np.nan), valid_mask=valid.copy(),
                    colour_label=f'{title} ({units})', colormap=cmap, limits=tuple(limits),
                    caption='Invalid / masked values are grey; an angle or score is not a defect probability.')


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
                              vmin=spec.limits[0], vmax=spec.limits[1], interpolation='nearest', rasterized=True)
            figure.colorbar(image, ax=ax, label=spec.colour_label, shrink=.82)
            ax.legend(handles=[Patch(facecolor='#dce1e5', label='Invalid / masked')], loc='lower right', fontsize=7)
        for item in spec.series:
            x, y = np.asarray(item['x']), np.asarray(item['y'])
            ax.plot(x, y, item.get('style', '-'), color=item['color'], label=item['name'],
                    marker='o' if spec.categories or len(x) < 5 else None, markersize=3, linewidth=1.3)
            if item.get('sd') is not None:
                sd = np.asarray(item['sd'])
                if len(x) == 1:
                    ax.errorbar(x,y,yerr=sd,fmt='none',ecolor=item['color'],capsize=4,linewidth=1.3)
                else:
                    ax.fill_between(x, y-sd, y+sd, color=item['color'], alpha=.17)
            if 'distribution' in item:
                distribution = item['distribution']
                axes[1].plot(distribution['x'],distribution['y'],item.get('style','-'),
                             color=item['color'],label=item['name'],linewidth=1.3)
            if 'normalized' in item:
                axes[1].plot(x, item['normalized'], item.get('style', '-'), color=item['color'], label=item['name'])
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
            units = spec.ylabel.removeprefix('Mean (').removesuffix(')')
            axes[1].set(title='ROI intensity distribution',xlabel=f'Pixel intensity ({units})',
                        ylabel=f'Probability density (1/{units})')
            axes[1].legend(fontsize=7,frameon=False)
        elif shape_branch:
            axes[1].set(title='L2 normalized shape', xlabel=spec.xlabel, ylabel='Normalized mean (dimensionless)')
        origin = spec.source.get('acquisition_source') or spec.source.get('data_source') or 'UNKNOWN'
        figure.suptitle(f'HyperLab · {origin} origin', fontsize=10, fontweight='bold')
        # Fixed caption area is part of the saved figure, not a clipped UI label.
        import textwrap
        figure.supxlabel('\n'.join(textwrap.wrap(spec.caption, 110)), fontsize=7)
        figure.canvas.draw()
        return figure


def recorded_roi_plot(sequence, rectangles, names, colors, *, policy='diagnostic', cancelled=None):
    from .analysis import roi_statistics
    from .io import Cube
    x,xlabel = sequence_coordinates(sequence.metadata['frames'])
    values = np.full((len(rectangles),sequence.frame_count),np.nan)
    valid_counts = np.zeros_like(values,dtype=np.int64)
    for index in range(sequence.frame_count):
        if cancelled is not None and cancelled.is_set():
            raise InterruptedError('Recorded ROI analysis cancelled; no partial curve presented as complete')
        frame = sequence.frame(index)
        cube = Cube(frame.data if frame.data.ndim==3 else frame.data[...,None],dict(frame.metadata))
        for i,rect in enumerate(rectangles):
            stats = roi_statistics(cube,rect,policy=policy)
            finite = np.isfinite(stats['mean'])
            values[i,index] = np.mean(stats['mean'][finite]) if np.any(finite) else np.nan
            valid_counts[i,index] = stats['count'].sum()
    return PlotSpec('lines','ROI trend · all recorded frames',xlabel,'ROI mean (DN)',
        source={'source_file':str(sequence.path),'acquisition_source':sequence.metadata.get('acquisition_source','UNKNOWN')},
        series=[{'name':name,'color':colors[i],'style':'-','x':x[:sequence.frame_count],'y':values[i],
                 'rect':rectangles[i],'valid_counts':valid_counts[i]} for i,name in enumerate(names)],
        metadata={'frame_count':sequence.frame_count,'sampling':'all persisted frames','policy':policy,
                  'color_policy':'arithmetic mean of valid channel means when colour is present'},
        caption='Recorded host clock or explicit frame index; missing samples remain gaps. No playback-clock timing.')


def export_figure_bundle(spec, directory, *, width_mm=180, height_mm=115, dpi=300):
    if not 60 <= width_mm <= 400 or not 50 <= height_mm <= 400 or not 72 <= dpi <= 1200:
        raise ValueError('Figure dimensions or DPI exceed the supported range')
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
    with (directory/'series.csv').open('x', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['series', 'feature_index', 'x', 'y', 'spatial_sd_ddof0', 'normalized'])
        for item in spec.series:
            for i, (x, y) in enumerate(zip(item['x'], item['y'])):
                sd = item.get('sd')
                writer.writerow([item['name'], i, x, y, sd[i] if sd is not None else '',
                                 item['normalized'][i] if 'normalized' in item else ''])
    if any('distribution' in item for item in spec.series):
        with (directory/'distributions.csv').open('x',newline='',encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['series','bin_left','bin_right','bin_center','count','density'])
            for item in spec.series:
                d = item['distribution']
                for i,x in enumerate(d['x']):
                    writer.writerow([item['name'],d['bin_edges'][i],d['bin_edges'][i+1],x,d['counts'][i],d['y'][i]])
    (directory/'plot.json').write_text(json.dumps(record, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    figure = render_figure(spec, width_mm=width_mm, height_mm=height_mm, dpi=dpi)
    import matplotlib as mpl
    with mpl.rc_context({'svg.fonttype':'none', 'pdf.fonttype':42}):
        for extension in ('svg', 'pdf', 'png'):
            figure.savefig(directory/f'figure.{extension}', dpi=dpi)
    return directory
