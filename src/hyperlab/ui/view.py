"""Image-space geometry and explicitly derived display operations."""
import math
from time import perf_counter_ns
import numpy as np


def roi_rect(position, size, shape):
    """Pixel centres in a half-open, axis-aligned ROI, independent of ViewBox zoom."""
    h, w = shape[:2]
    x0, y0 = (int(math.ceil(float(v) - 0.5)) for v in position)
    x1, y1 = (int(math.ceil(float(v) + float(s) - 0.5)) for v, s in zip(position, size))
    return max(0, min(w, x0)), max(0, min(h, y0)), max(0, min(w, x1)), max(0, min(h, y1))


def bayer_cell_rgb(raw, metadata):
    """2x2 CFA-cell display, half resolution; never a reconstructed spectrum."""
    fmt = str(metadata.get('pixel_format', metadata.get('PixelFormat', '')))
    if not fmt.startswith('BayerRG') or raw.ndim != 2:
        raise ValueError('CFA display requires evidenced BayerRG samples.')
    settings = metadata.get('readback_settings') or metadata.get('current_settings') or {}
    for name in ('ReverseX', 'ReverseY'):
        if settings.get(name) not in (False, 0):
            raise ValueError(f'{name} must be read back false for this CFA display.')
    offsets = [settings.get(name) for name in ('OffsetX', 'OffsetY')]
    if any(value is None or int(value) % 2 for value in offsets):
        raise ValueError('CFA display currently requires evidenced even sensor offsets.')
    h, w = (n // 2 * 2 for n in raw.shape)
    image = np.empty((h // 2, w // 2, 3), dtype=np.float32)
    image[..., 0] = raw[:h:2, :w:2]
    image[..., 1] = (raw[:h:2, 1:w:2].astype(np.float32) + raw[1:h:2, :w:2]) * 0.5
    image[..., 2] = raw[1:h:2, 1:w:2]
    return image


def display_levels(data, valid_mask=None):
    sampled = np.asarray(data)[::max(1, data.shape[0] // 180), ::max(1, data.shape[1] // 240)]
    good = np.isfinite(sampled)
    if valid_mask is not None:
        good &= np.asarray(valid_mask)[::max(1, data.shape[0] // 180), ::max(1, data.shape[1] // 240)]
    values = sampled[good]
    if not values.size:
        return 0.0, 1.0
    low, high = np.percentile(values, [1, 99])
    return float(low), float(high if high > low else low + 1)


def display_selection(cube, band=0, *, policy='diagnostic', cfa=False,
                      display_stride=1, diagnostics=True, timings=None):
    """Display-only sampling; default diagnostics retain full raw denominators.

    Fast preview may pass diagnostics=False with an explicit stride. Its counts
    then describe strided raw samples, never full-frame measurement quality.
    """
    from hyperlab.analysis.core import _quality, calculation_dtype
    started = perf_counter_ns()
    stride = (display_stride, display_stride) if isinstance(display_stride, (int, np.integer)) else tuple(display_stride)
    if len(stride) != 2 or any(isinstance(value, (bool, np.bool_)) or
            not isinstance(value, (int, np.integer)) or value < 1 for value in stride):
        raise ValueError('Display stride must contain positive integer raw-pixel steps')
    requested_stride = [int(value) for value in stride]
    color = bool(cube.metadata.get('channel_labels'))
    # CFA cell colour needs all four correctly phased raw photosites. Keep this
    # existing full path until a separate cell-aware sampling policy is reviewed.
    sy, sx = (1, 1) if cfa and not color else requested_stride
    channels = slice(None) if color else slice(band, band + 1)
    selection = (slice(None, None, sy), slice(None, None, sx), channels)
    # A strided RGB view otherwise repeats slow non-contiguous reads through
    # quality, histogram, mean and Qt conversion. This copies display samples only.
    raw = np.ascontiguousarray(cube.data[selection])
    good, masks, threshold = _quality(cube, raw, selection, policy)
    if timings:
        timings.record('display_validity', perf_counter_ns() - started)
    image = raw if color else raw[..., 0]
    valid = good if color else good[..., 0]
    display_extent = [0, 0, cube.shape[1], cube.shape[0]]
    note = 'Raw values; invalid/ignored samples are transparent'
    if color:
        # A colour pixel needs all delivered colour components. Histograms use
        # the identical eligibility, not the surviving components of a bad pixel.
        if np.all(good):
            valid = good
        else:
            pixels = good[..., 0].copy()
            for channel in range(1, good.shape[2]):
                pixels &= good[..., channel]
            valid = np.broadcast_to(pixels[..., None], raw.shape)
        if cube.metadata.get('channel_labels') == ['B', 'G', 'R']:
            image, valid = image[..., ::-1], valid[..., ::-1]
    elif cfa:
        image = bayer_cell_rgb(image, cube.metadata)
        h, w = image.shape[:2]
        display_extent = [0, 0, w * 2, h * 2]
        cells = (valid[:h*2:2, :w*2:2] & valid[1:h*2:2, :w*2:2]
                 & valid[:h*2:2, 1:w*2:2] & valid[1:h*2:2, 1:w*2:2])
        valid = np.broadcast_to(cells[..., None], image.shape)
        note = 'CFA-cell colour display derivative; requires four valid raw photosites'
    if not np.all(valid):
        # float32 represents delivered 8/12/16-bit integers exactly. Larger
        # integers and float64 keep float64; raw scientific values never change.
        image = image.astype(calculation_dtype(image), copy=True)
        image[~valid] = np.nan
    image = np.ascontiguousarray(image)
    levels_started = perf_counter_ns()
    step = (max(1, image.shape[0] // 180), max(1, image.shape[1] // 240))
    sampled = image[::step[0], ::step[1]]
    sampled_valid = valid[::step[0], ::step[1]] & np.isfinite(sampled)
    values = sampled[sampled_valid].astype(np.float64)
    if values.size:
        low, high = np.percentile(values, [1, 99])
        levels = float(low), float(high if high > low else low + 1)
    else:
        levels = 0.0, 1.0
    if timings:
        timings.record('display_levels', perf_counter_ns() - levels_started)
    diagnostic_started = perf_counter_ns()
    stats_raw, stats_good, stats_masks = raw, good, masks
    if diagnostics and (sy != 1 or sx != 1):
        full_selection = (slice(None), slice(None), channels)
        stats_raw = np.asarray(cube.data[full_selection])
        stats_good, stats_masks, _ = _quality(cube, stats_raw, full_selection, policy)
    raw_counts = {key: int(np.count_nonzero(mask)) for key, mask in stats_masks.items()}
    raw_mean = None
    if raw_counts['valid']:
        values_for_mean = stats_raw if raw_counts['valid'] == stats_raw.size else stats_raw[stats_good]
        raw_mean = float(np.mean(values_for_mean, dtype=np.float64))
    saturated = masks['saturated'][..., 0].copy()
    for channel in range(1, masks['saturated'].shape[2]):
        saturated |= masks['saturated'][..., channel]
    full_statistics = diagnostics or (sy == 1 and sx == 1)
    h, w = cube.shape[:2]
    if timings:
        timings.record('display_diagnostics', perf_counter_ns() - diagnostic_started)
        timings.record('display_selection_total', perf_counter_ns() - started)
    return {'image': image, 'valid_mask': valid, 'values': values,
            'levels': levels, 'policy': policy,
            'sample_count': int(values.size), 'sample_total': int(sampled.size),
            'sampling_stride': list(step), 'interpretation': note,
            'raw_counts': raw_counts, 'raw_mean': raw_mean,
            'statistics_scope': 'full raw frame' if full_statistics else 'strided raw samples',
            'statistics_sample_count': int(stats_raw.size),
            'statistics_sample_total': int(h * w * raw.shape[2]),
            'statistics_source': {key: cube.metadata.get(key) for key in
                ('source_file', 'session_id', 'stream_epoch', 'sequence', 'host_monotonic_ns', 'host_utc')},
            'requested_display_stride': requested_stride, 'display_stride': [sy, sx],
            'display_sample_origin_yx': [0, 0], 'raw_extent': [0, 0, w, h],
            'display_extent': display_extent,
            'display_sample_rule': 'Raw sample at y=row*stride_y, x=column*stride_x; sampled overview rescaled to raw extent; inspect raw pixels separately'
                if sy != 1 or sx != 1 else 'Full raw grid; CFA view derives 2x2 cells when selected',
            'image_shape': list(image.shape),
            'saturated_mask': saturated,
            'saturation_value': threshold}
