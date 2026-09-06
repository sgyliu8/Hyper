"""Sensor quality and time-repeatability helpers; no spectral interpretation."""
import numpy as np

from .core import _floating, _quality, roi_statistics


def quality_summary(cube, rect=None, *, policy="diagnostic"):
    h, w, _ = cube.shape
    stats = roi_statistics(cube, rect or (0, 0, w, h), policy=policy, robust=False)
    counts = {key: int(values.sum()) for key, values in stats["counts"].items()}
    return {**counts, "policy": policy, "saturation_value": stats["saturation_value"],
            "saturation_fraction": None if stats["saturation_value"] is None else
                counts["saturated"] / counts["total"],
            "per_channel": stats, "units": cube.metadata["units"]}


def cfa_statistics(cube, rect=None, *, policy="diagnostic"):
    """CFA phases use sensor-origin pattern, ROI/crop offsets and explicit flips."""
    from .capabilities import require_capability
    require_capability(cube, "cfa")
    meta = cube.metadata
    pattern = meta.get("cfa_pattern")
    pattern_origin = meta.get("cfa_pattern_origin", "sensor" if pattern is not None else "delivered")
    if pattern_origin not in {"sensor", "delivered"}:
        raise ValueError("cfa_pattern_origin must be sensor or delivered")
    if pattern is None:
        for name, full in {"BayerRG": "RGGB", "BayerGR": "GRBG", "BayerGB": "GBRG", "BayerBG": "BGGR"}.items():
            if str(meta["pixel_format"]).startswith(name):
                pattern = full
                break
    tiles = {"RGGB": [["R", "G1"], ["G2", "B"]], "GRBG": [["G1", "R"], ["B", "G2"]],
             "GBRG": [["G2", "B"], ["R", "G1"]], "BGGR": [["B", "G2"], ["G1", "R"]]}
    if pattern not in tiles:
        raise ValueError("CFA phase statistics require a documented Bayer pattern")
    h, w, _ = cube.shape
    rect = rect or (0, 0, w, h)
    roi_statistics(cube, rect, policy=policy, robust=False)  # Reuse coordinate validation.
    x0, y0, x1, y1 = rect
    offset = meta.get("cfa_offset", [meta.get("offset_x", 0), meta.get("offset_y", 0)])
    flip_x, flip_y = bool(meta.get("flip_x", False)), bool(meta.get("flip_y", False))
    if pattern_origin == "delivered":
        offset, flip_x, flip_y = [0, 0], False, False
    ys, xs = np.arange(y0, y1), np.arange(x0, x1)
    sx = int(offset[0]) + (w - 1 - xs if flip_x else xs)
    sy = int(offset[1]) + (h - 1 - ys if flip_y else ys)
    labels = np.asarray(tiles[pattern])[sy[:, None] % 2, sx[None, :] % 2]
    selection = (slice(y0, y1), slice(x0, x1), slice(0, 1))
    raw = cube.data[selection]
    good, masks, threshold = _quality(cube, raw, selection, policy)
    phases = {}
    for name in ("R", "G1", "G2", "B"):
        phase = labels == name
        values = _floating(raw[:, :, 0][phase & good[:, :, 0]], np.float64)
        phases[name] = {"mean": float(values.mean()) if len(values) else None,
            "std": float(values.std()) if len(values) else None,
            **{key: int(np.count_nonzero(mask[:, :, 0] & phase)) for key, mask in masks.items()}}
    return {"phases": phases, "rect": list(rect), "pattern": pattern, "pattern_origin": pattern_origin,
            "cfa_offset": list(offset),
            "flip_x": flip_x, "flip_y": flip_y, "policy": policy, "saturation_value": threshold,
            "units": meta["units"], "interpretation": "CFA phase DN; not four wavelength bands"}


class TemporalStatistics:
    """Welford accumulation of owned matching frames; memory is independent of T."""

    def __init__(self, shape, saturation_value=None):
        self.shape = tuple(shape)
        self.mean = np.zeros(self.shape, np.float64)
        self.m2 = np.zeros(self.shape, np.float64)
        self.count = np.zeros(self.shape, np.uint64)
        self.saturated = np.zeros(self.shape, np.uint64)
        self.saturation_value = saturation_value
        self.frame_count = 0
        self.first_mean = self.last_mean = None

    def update(self, frame, valid_mask=None):
        data = np.asarray(frame)
        if data.shape != self.shape:
            raise ValueError("Temporal frames must share shape; time is not a new spectral dimension")
        good = np.isfinite(data)
        if valid_mask is not None:
            if np.shape(valid_mask) != self.shape:
                raise ValueError("Temporal validity mask must match frame shape")
            good &= valid_mask
        values = _floating(data[good], np.float64)
        self.count[good] += 1
        delta = values - self.mean[good]
        self.mean[good] += delta / self.count[good]
        self.m2[good] += delta * (values - self.mean[good])
        if self.saturation_value is not None:
            self.saturated += good & (data >= self.saturation_value)
        self.frame_count += 1
        signal = float(values.mean()) if len(values) else None
        if self.frame_count == 1:
            self.first_mean = signal
        self.last_mean = signal

    def result(self):
        variance = np.full(self.shape, np.nan)
        np.divide(self.m2, self.count, out=variance, where=self.count > 0)
        mean = np.where(self.count > 0, self.mean, np.nan)
        return {"mean": mean, "variance": variance, "std": np.sqrt(np.maximum(variance, 0)),
            "count": self.count.copy(), "saturated_count": self.saturated.copy(),
            "frame_count": self.frame_count, "first_frame_mean": self.first_mean,
            "last_frame_mean": self.last_mean, "mean_drift": None if self.first_mean is None or self.last_mean is None
                else self.last_mean - self.first_mean,
            "metadata": {"operation": "temporal Welford mean and variance", "std_ddof": 0,
                "axis_kind": "time", "data_level": "derived_frame", "wavelengths": None,
                "policy": "finite and declared valid; saturated samples counted and retained",
                "saturation_value": self.saturation_value,
                "drift_note": "last minus first frame spatial mean; not material attribution"}}
