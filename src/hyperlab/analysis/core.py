from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from hyperlab.io import Cube


def _valid(cube, data, selection):
    good = np.isfinite(data)
    if cube.valid_mask is not None:
        if cube.valid_mask.ndim == 2:
            good &= cube.valid_mask[selection[:2]][..., None]
        else:
            good &= cube.valid_mask[selection]
    ignore = cube.metadata.get("data_ignore_value")
    if ignore is not None:
        good &= data != ignore
    bands = cube.metadata.get("band_validity")
    if bands is not None:
        good &= np.asarray(bands, dtype=bool)[selection[2]]
    return good


def _axis(cube):
    return "color_channel_index" if cube.metadata.get("channel_labels") else "wavelength" if cube.wavelengths is not None else "state_index"


def _band(cube, index):
    if not isinstance(index, (int, np.integer)) or not 0 <= index < cube.shape[2]:
        raise ValueError("Band/state index outside cube")
    selection = (slice(None), slice(None), slice(index, index + 1))
    data = np.asarray(cube.data[selection], dtype=np.float32)
    return data[:, :, 0], _valid(cube, data, selection)[:, :, 0]


def composite(cube, bands=(0, 1, 2)):
    """Per-channel 2-98% display stretch; this is not a colorimetric RGB image."""
    if len(bands) != 3:
        raise ValueError("Composite needs three band/state indices")
    image = np.zeros(cube.shape[:2] + (3,), dtype=np.float32)
    valid = np.ones(cube.shape[:2], dtype=bool)
    limits = []
    for channel, band in enumerate(bands):
        data, good = _band(cube, band)
        valid &= good
        if np.any(good):
            values = data[good]
            # Only a bounded set is needed to choose display limits.
            values = values[::max(1, len(values) // 100000)]
            low, high = np.percentile(values, [2, 98])
            if high > low:
                image[:, :, channel] = np.clip((data - low) / (high - low), 0, 1)
            limits.append([float(low), float(high)])
        else:
            limits.append([None, None])
    image[~valid] = 0
    wave = cube.wavelengths
    return {"image": image, "valid_mask": valid, "bands": list(bands),
            "wavelengths": None if wave is None else wave[list(bands)].tolist(),
            "metadata": {"interpretation": "display composite; not colorimetrically calibrated",
                         "stretch": "per-channel 2-98 percentile", "limits": limits,
                         "wavelength_units": cube.metadata["wavelength_units"]}}


def roi_statistics(cube, rect):
    """Half-open rectangle (x0,y0,x1,y1); population standard deviation (ddof=0)."""
    if len(rect) != 4 or any(not isinstance(x, (int, np.integer)) for x in rect):
        raise ValueError("ROI must contain four integer coordinates")
    x0, y0, x1, y1 = rect
    h, w, k = cube.shape
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise ValueError("ROI is empty or outside image")
    means, stds, counts = np.full(k, np.nan), np.full(k, np.nan), np.zeros(k, dtype=np.int64)
    # One band at a time keeps ROI working memory independent of K.
    for band in range(k):
        selection = (slice(y0, y1), slice(x0, x1), slice(band, band + 1))
        data = cube.data[selection]
        values = np.asarray(data[_valid(cube, data, selection)], dtype=np.float64)
        counts[band] = len(values)
        if len(values):
            means[band] = values.mean()
            stds[band] = values.std(ddof=0)
    return {"mean": means, "std": stds, "count": counts, "rect": tuple(rect),
            "wavelengths": cube.wavelengths, "axis_label": _axis(cube),
            "wavelength_units": cube.metadata["wavelength_units"], "units": cube.metadata["units"],
            "metadata": {"std_ddof": 0, "validity": "finite and declared valid pixels"}}


def export_roi_csv(stats, path, wavelengths=None):
    path = Path(path)
    wave = stats.get("wavelengths") if wavelengths is None else wavelengths
    if wave is not None and len(wave) != len(stats["mean"]):
        raise ValueError("Wavelength length does not match ROI")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["index", "wavelength", "wavelength_units", "mean", "std_ddof0", "valid_count", "signal_units"])
        for i, (mean, std, count) in enumerate(zip(stats["mean"], stats["std"], stats["count"])):
            writer.writerow([i, "" if wave is None else wave[i], stats.get("wavelength_units") or "",
                             mean, std, int(count), stats.get("units", "unknown")])
    return path


def difference(cube, a, b):
    first, ga = _band(cube, a)
    second, gb = _band(cube, b)
    valid = ga & gb
    data = first - second
    valid &= np.isfinite(data)
    data[~valid] = np.nan
    return {"data": data, "image": data, "valid_mask": valid,
            "metadata": {"operation": "difference", "indices": [a, b],
                         "units": cube.metadata["units"], "axis": _axis(cube)}}


def ratio(cube, a, b, *, minimum_denominator=1e-6):
    if not np.isfinite(minimum_denominator) or minimum_denominator <= 0:
        raise ValueError("minimum_denominator must be finite and positive")
    first, ga = _band(cube, a)
    second, gb = _band(cube, b)
    valid = ga & gb & (np.abs(second) >= minimum_denominator)
    data = np.full(first.shape, np.nan, dtype=np.float32)
    np.divide(first, second, out=data, where=valid)
    valid &= np.isfinite(data)
    data[~valid] = np.nan
    return {"data": data, "image": data, "valid_mask": valid,
            "metadata": {"operation": "ratio", "indices": [a, b], "units": "dimensionless",
                         "minimum_denominator": minimum_denominator, "axis": _axis(cube)}}


def _blocks(cube, chunk_pixels):
    if chunk_pixels < 1:
        raise ValueError("chunk_pixels must be positive")
    h, w, k = cube.shape
    chunk = max(1, min(chunk_pixels, 64 * 1024**2 // (k * 4 * 6)))
    for start in range(0, h * w, chunk):
        indices = np.arange(start, min(start + chunk, h * w))
        rows, cols = indices // w, indices % w
        selection = (rows, cols, slice(None))
        data = np.asarray(cube.data[selection], dtype=np.float32)
        yield indices, selection, data, _valid(cube, data, selection)


def pca(cube, n_components=3, *, max_samples=10000, chunk_pixels=65536, standardize=False, seed=0):
    """Sample fit + chunked transform. Unscaled mean-centering is the default."""
    h, w, k = cube.shape
    if not 1 <= n_components <= k or max_samples < 2 or chunk_pixels < 1:
        raise ValueError("Invalid PCA components, max_samples or chunk size")
    sample_count = min(h * w, max_samples, max(2, 64 * 1024**2 // (k * 8)))
    rng = np.random.default_rng(seed)
    indices = rng.choice(h * w, size=sample_count, replace=False)
    selection = (indices // w, indices % w, slice(None))
    source = cube.data[selection]
    valid = np.all(_valid(cube, source, selection), axis=1)
    samples = np.asarray(source[valid], dtype=np.float64)
    if len(samples) < max(2, n_components):
        raise ValueError("Too few complete valid sampled spectra/state vectors for PCA")
    mean = samples.mean(axis=0)
    samples -= mean
    scale = samples.std(axis=0) if standardize else np.ones(k)
    scale[scale == 0] = 1
    samples /= scale
    _, singular, vt = np.linalg.svd(samples, full_matrices=False)
    variance = singular**2 / (len(samples) - 1)
    total = variance.sum()
    explained = variance[:n_components] / total if total > 0 else np.zeros(n_components)
    components = vt[:n_components]
    scores = np.full((h * w, n_components), np.nan, dtype=np.float32)
    valid_pixels = np.zeros(h * w, dtype=bool)
    for ids, _, block, good in _blocks(cube, chunk_pixels):
        rows = np.all(good, axis=1)
        transformed = ((block[rows] - mean) / scale) @ components.T
        finite = np.all(np.isfinite(transformed), axis=1)
        target = ids[rows][finite]
        scores[target] = transformed[finite]
        valid_pixels[target] = True
    return {"scores": scores.reshape(h, w, n_components), "image": scores.reshape(h, w, n_components),
            "valid_mask": valid_pixels.reshape(h, w), "components": components,
            "explained_variance_ratio": explained, "mean": mean, "scale": scale,
            "metadata": {"fit_sample_count": len(samples), "candidate_sample_count": sample_count,
                         "seed": seed, "preprocessing": "center and unit-std" if standardize else "mean-center only",
                         "transform": "chunked", "axis": _axis(cube), "data_source": cube.metadata["data_source"]}}


def spectral_angle(cube, reference, *, chunk_pixels=65536):
    reference = np.asarray(reference, dtype=np.float64)
    if reference.shape != (cube.shape[2],) or not np.all(np.isfinite(reference)):
        raise ValueError("Reference must be a finite K-vector")
    norm = np.linalg.norm(reference)
    if norm == 0 or not np.isfinite(norm):
        raise ValueError("SAM reference must have a finite nonzero norm")
    unit = reference / norm
    data = np.full(cube.shape[0] * cube.shape[1], np.nan, dtype=np.float32)
    valid = np.zeros(data.shape, dtype=bool)
    for indices, _, block, good in _blocks(cube, chunk_pixels):
        values = block.astype(np.float64)
        lengths = np.linalg.norm(values, axis=1)
        rows = np.all(good, axis=1) & (lengths > 0) & np.isfinite(lengths)
        cosine = (values[rows] @ unit) / lengths[rows]
        data[indices[rows]] = np.arccos(np.clip(cosine, -1, 1))
        valid[indices[rows]] = True
    image = data.reshape(cube.shape[:2])
    return {"data": image, "image": image, "valid_mask": valid.reshape(cube.shape[:2]),
            "metadata": {"units": "radians", "operation": "Spectral Angle Mapper",
                         "interpretation": "spectral angle difference" if cube.wavelengths is not None
                         else "state vector angle difference", "zero_vectors": "invalid"}}


def _saturation(cube):
    value = cube.metadata.get("saturation_value")
    if value is None and cube.metadata.get("effective_bits") is not None:
        value = 2 ** int(cube.metadata["effective_bits"]) - 1
    if value is None or not np.isfinite(value):
        raise ValueError("Reflectance requires a known saturation_value or effective_bits for every input")
    return float(value)


def reflectance(sample, white, dark_sample, dark_white, *, reference_reflectance=None,
                reference_source=None, minimum_denominator=1.0, chunk_pixels=65536):
    """Strict matching, float dark subtraction, no clipping of physically unusual ratios."""
    cubes = [sample, white, dark_sample, dark_white]
    if not np.isfinite(minimum_denominator) or minimum_denominator <= 0:
        raise ValueError("minimum_denominator must be finite and positive")
    required = ("settings", "exposure", "gain", "processing_steps", "units", "wavelength_units")
    for cube in cubes:
        if cube.shape != sample.shape:
            raise ValueError("Reference cube shape must match sample; no implicit spatial registration")
        if cube.metadata["data_level"] != "spectral_cube" or cube.wavelengths is None:
            raise ValueError("Reflectance requires spectral cubes with actual wavelength vectors")
        if not cube.metadata.get("wavelength_source") or cube.metadata.get("linear_intensity") is not True:
            raise ValueError("Verified wavelength source and explicit linear_intensity=true are required")
        if not np.array_equal(cube.wavelengths, sample.wavelengths):
            raise ValueError("Wavelength vectors differ; no implicit interpolation")
        for key in required:
            if cube.metadata.get(key) is None or cube.metadata.get(key) == "unknown":
                raise ValueError(f"Reflectance requires known {key}")
            if cube.metadata[key] != sample.metadata[key]:
                raise ValueError(f"Reflectance input {key} mismatch")
        if cube.metadata.get("partial") is True or cube.metadata.get("completed") is not True:
            raise ValueError("Reflectance requires completed, non-partial inputs")
    saturations = [_saturation(cube) for cube in cubes]
    k = sample.shape[2]
    if reference_reflectance is None:
        reference = np.ones(k, dtype=np.float32)
        kind = "relative"
    else:
        reference = np.asarray(reference_reflectance, dtype=np.float32)
        if reference.shape != (k,) or not np.all(np.isfinite(reference)) or np.any((reference < 0) | (reference > 1)):
            raise ValueError("Known reference reflectance must be a finite K-vector in [0,1]")
        if not reference_source:
            raise ValueError("Known reference reflectance requires reference_source")
        kind = "reference-calibrated"
    shape = sample.shape
    output = np.full(shape, np.nan, dtype=np.float32)
    validity = np.zeros(shape, dtype=bool)
    flat_out = output.reshape(-1, k)
    flat_valid = validity.reshape(-1, k)
    for indices, selection, first, good in _blocks(sample, chunk_pixels):
        values = [first]
        good &= first < saturations[0]
        for cube, saturation in zip(cubes[1:], saturations[1:]):
            block = np.asarray(cube.data[selection], dtype=np.float32)
            values.append(block)
            good &= _valid(cube, block, selection) & (block < saturation)
        numerator = values[0] - values[2]
        denominator = values[1] - values[3]
        good &= denominator >= minimum_denominator
        corrected = np.full(first.shape, np.nan, dtype=np.float32)
        np.divide(numerator, denominator, out=corrected, where=good)
        corrected *= reference
        good &= np.isfinite(corrected)
        corrected[~good] = np.nan
        flat_out[indices] = corrected
        flat_valid[indices] = good
    meta = dict(sample.metadata)
    meta.update(data_level="reflectance_cube", units="dimensionless", reflectance_kind=kind,
                calibration_source=reference_source, reference_source=reference_source,
                processing_steps=list(meta["processing_steps"]) + [{"operation": "dark-corrected reference ratio",
                    "kind": kind, "minimum_denominator": minimum_denominator, "clipped": False}],
                validity_note="finite, unsaturated inputs and positive denominator above threshold",
                interpretation="Relative/reference-calibrated product; no metrological certification or geometry correction")
    meta.pop("saturation_value", None)
    meta["effective_bits"] = None
    return Cube(output, meta, validity)
