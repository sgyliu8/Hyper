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


def display_levels(data):
    sampled = np.asarray(data)[::max(1, data.shape[0] // 180), ::max(1, data.shape[1] // 240)]
    values = sampled[np.isfinite(sampled)]
    if not values.size:
        return 0.0, 1.0
    low, high = np.percentile(values, [1, 99])
    return float(low), float(high if high > low else low + 1)
