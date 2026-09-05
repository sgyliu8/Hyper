"""Image-space geometry and explicitly derived display operations."""
import math
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


def display_selection(cube, band=0, *, policy='diagnostic', cfa=False):
    """One validity selection for image, histogram and contrast; raw is unchanged."""
    from hyperlab.analysis.core import _quality
    color = bool(cube.metadata.get('channel_labels'))
    channels = slice(None) if color else slice(band, band + 1)
    selection = (slice(None), slice(None), channels)
    raw = cube.data[selection]
    good, masks, threshold = _quality(cube, raw, selection, policy)
    image = raw if color else raw[..., 0]
    valid = good if color else good[..., 0]
    note = 'Raw values; invalid/ignored samples are transparent'
    if color:
        # A colour pixel needs all delivered colour components. Histograms use
        # the identical eligibility, not the surviving components of a bad pixel.
        valid = np.broadcast_to(np.all(good, axis=2)[..., None], raw.shape)
        if cube.metadata.get('channel_labels') == ['B', 'G', 'R']:
            image, valid = image[..., ::-1], valid[..., ::-1]
    elif cfa:
        image = bayer_cell_rgb(image, cube.metadata)
        h, w = image.shape[:2]
        cells = (valid[:h*2:2, :w*2:2] & valid[1:h*2:2, :w*2:2]
                 & valid[:h*2:2, 1:w*2:2] & valid[1:h*2:2, 1:w*2:2])
        valid = np.broadcast_to(cells[..., None], image.shape)
        note = 'CFA-cell colour display derivative; requires four valid raw photosites'
    if not np.all(valid):
        image = np.where(valid, image, np.nan)
    step = (max(1, image.shape[0] // 180), max(1, image.shape[1] // 240))
    sampled = image[::step[0], ::step[1]]
    sampled_valid = valid[::step[0], ::step[1]] & np.isfinite(sampled)
    values = sampled[sampled_valid].astype(np.float64)
    return {'image': image, 'valid_mask': valid, 'values': values,
            'levels': display_levels(image, valid), 'policy': policy,
            'sample_count': int(values.size), 'sample_total': int(sampled.size),
            'sampling_stride': list(step), 'interpretation': note,
            'raw_counts': {key: int(np.count_nonzero(mask)) for key, mask in masks.items()},
            'raw_mean': float(np.mean(raw[good], dtype=np.float64)) if np.any(good) else None,
            'saturated_mask': np.any(masks['saturated'], axis=2),
            'saturation_value': threshold}
