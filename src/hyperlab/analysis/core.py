from __future__ import annotations

import csv
from copy import deepcopy
from pathlib import Path

import numpy as np

from hyperlab.io import Cube
from .capabilities import capabilities, feature_selection, require_capability


def calculation_dtype(data):
    """12/16-bit DN fit float32 exactly; larger integer and float64 inputs do not."""
    dtype = np.dtype(data.dtype)
    return np.float64 if dtype.itemsize > (4 if dtype.kind == "f" else 2) else np.float32


def _floating(data, dtype=None):
    # float64 cannot retain every int64/uint64 integer. Refuse those values
    # explicitly instead of making adjacent raw samples numerically identical.
    if data.dtype.kind in "iu" and data.dtype.itemsize >= 8 and data.size:
        if np.any(data > 2**53) or (data.dtype.kind == "i" and np.any(data < -(2**53))):
            raise ValueError("Integer samples outside the exact float64 range need an explicit rescaling before analysis")
    return np.asarray(data, dtype=dtype or calculation_dtype(data))


def saturation_value(cube):
    if cube.metadata["data_level"] == "reflectance_cube":
        return None
    value = cube.metadata.get("saturation_value")
    bits = cube.metadata.get("pfnc_sample_bits", cube.metadata.get("effective_bits"))
    if value is None and bits is not None:
        value = 2 ** int(bits) - 1
    return None if value is None or not np.isfinite(value) else float(value)


def _quality(cube, data, selection, policy="diagnostic"):
    if policy not in {"diagnostic", "quantitative"}:
        raise ValueError("Policy must be diagnostic or quantitative")
    good = np.isfinite(data)
    if cube.valid_mask is not None:
        if cube.valid_mask.ndim == 2:
            good &= cube.valid_mask[selection[:2]][..., None]
        else:
            good &= cube.valid_mask[selection]
    bands = cube.metadata.get("band_validity")
    if bands is not None:
        good &= np.asarray(bands, dtype=bool)[selection[2]]
    invalid = ~good
    ignore = cube.metadata.get("data_ignore_value")
    ignored = good & (data == ignore) if ignore is not None else np.zeros(data.shape, bool)
    good &= ~ignored
    saturation = saturation_value(cube)
    saturated = good & (data >= saturation) if saturation is not None else np.zeros(data.shape, bool)
    if policy == "quantitative":
        good &= ~saturated
    return good, {"total": np.ones(data.shape, bool), "valid": good, "invalid": invalid,
                  "ignored": ignored, "saturated": saturated}, saturation


def _valid(cube, data, selection, policy="diagnostic"):
    return _quality(cube, data, selection, policy)[0]


def _axis(cube):
    return capabilities(cube)["axis_label"]


def _band(cube, index, policy="diagnostic"):
    if not isinstance(index, (int, np.integer)) or not 0 <= index < cube.shape[2]:
        raise ValueError("Band/state index outside cube")
    selection = (slice(None), slice(None), slice(index, index + 1))
    source = cube.data[selection]
    good = _valid(cube, source, selection, policy)
    data = _floating(source)
    return data[:, :, 0], good[:, :, 0]


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


def roi_statistics(cube, rect, *, policy="diagnostic"):
    """Half-open rectangle (x0,y0,x1,y1); population standard deviation (ddof=0)."""
    if len(rect) != 4 or any(not isinstance(x, (int, np.integer)) for x in rect):
        raise ValueError("ROI must contain four integer coordinates")
    x0, y0, x1, y1 = rect
    h, w, k = cube.shape
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise ValueError("ROI is empty or outside image")
    means, stds, counts = np.full(k, np.nan), np.full(k, np.nan), np.zeros(k, dtype=np.int64)
    quality_counts = {key: np.zeros(k, dtype=np.int64) for key in
                      ("total", "valid", "saturated", "ignored", "invalid")}
    # One band at a time keeps ROI working memory independent of K.
    for band in range(k):
        selection = (slice(y0, y1), slice(x0, x1), slice(band, band + 1))
        data = cube.data[selection]
        good, quality, saturation = _quality(cube, data, selection, policy)
        for key, mask in quality.items():
            quality_counts[key][band] = np.count_nonzero(mask)
        values = _floating(data[good], dtype=np.float64)
        counts[band] = len(values)
        if len(values):
            means[band] = values.mean()
            stds[band] = values.std(ddof=0)
    return {"mean": means, "std": stds, "count": counts, "counts": quality_counts,
            "policy": policy, "saturation_value": saturation, "rect": tuple(rect),
            "wavelengths": cube.wavelengths, "axis_label": _axis(cube),
            "channel_labels": cube.metadata.get("channel_labels"),
            "wavelength_units": cube.metadata["wavelength_units"], "units": cube.metadata["units"],
            "metadata": {"std_ddof": 0, "std_interpretation": "spatial SD; not temporal noise",
                "policy": policy, "saturation_status": "unknown" if saturation is None else "known sample threshold",
                "count_semantics": "invalid/ignored/saturated are disjoint; diagnostic valid includes saturated",
                "source_provenance": deepcopy(cube.metadata)}}


def roi_comparison(cube, rectangles, *, policy="diagnostic"):
    """ROI statistics, plus shared-bin DN distributions for a single plane."""
    results = [roi_statistics(cube, rect, policy=policy) for rect in rectangles]
    if cube.shape[2] != 1:
        return results

    def selected(rect):
        x0,y0,x1,y1 = rect
        selection = (slice(y0,y1),slice(x0,x1),slice(0,1))
        raw = cube.data[selection]
        good = _valid(cube,raw,selection,policy)
        return _floating(raw[good],np.float64)

    bounds = []
    for rect in rectangles:
        values = selected(rect)
        if values.size:
            bounds.append((values.min(),values.max()))
    low,high = (min(b[0] for b in bounds),max(b[1] for b in bounds)) if bounds else (0.,1.)
    if high == low:
        low,high = low-.5,high+.5
    edges = np.linspace(low,high,65)
    for result,rect in zip(results,rectangles):
        counts,_ = np.histogram(selected(rect),bins=edges)
        density = counts/(counts.sum()*np.diff(edges)) if counts.sum() else np.full(64,np.nan)
        result['distribution'] = {'x':(edges[:-1]+edges[1:])/2,'y':density,
                                  'counts':counts,'bin_edges':edges,'sample_count':int(counts.sum())}
    return results


def export_roi_csv(stats, path, wavelengths=None):
    path = Path(path)
    wave = stats.get("wavelengths") if wavelengths is None else wavelengths
    if wave is not None and len(wave) != len(stats["mean"]):
        raise ValueError("Wavelength length does not match ROI")
    path.parent.mkdir(parents=True, exist_ok=True)
    sidecar = path.with_suffix(path.suffix + ".json")
    if path.exists() or sidecar.exists():
        raise FileExistsError("ROI output exists; choose a new path")
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["index", "wavelength", "wavelength_units", "mean", "std_ddof0", "valid_count", "signal_units",
                         "axis_label", "channel_label", "policy", "total_count", "saturated_count", "ignored_count", "invalid_count"])
        for i, (mean, std, count) in enumerate(zip(stats["mean"], stats["std"], stats["count"])):
            labels = stats.get("channel_labels")
            quality = stats.get("counts", {})
            writer.writerow([i, "" if wave is None else wave[i], stats.get("wavelength_units") or "",
                mean, std, int(count), stats.get("units", "unknown"), stats.get("axis_label", "index"),
                labels[i] if labels else "", stats.get("policy", "diagnostic"),
                *[int(quality[key][i]) if key in quality else "" for key in ("total", "saturated", "ignored", "invalid")]])
    from hyperlab.io.cube import _dumps
    sidecar.write_text(_dumps({"schema_version": 1, "rect": stats["rect"],
        "axis_label": stats.get("axis_label"), "metadata": stats.get("metadata", {})}), encoding="utf-8")
    return path


def difference(cube, a, b, *, policy="diagnostic"):
    require_capability(cube, "difference")
    if a == b:
        raise ValueError("Difference requires two distinct indices")
    first, ga = _band(cube, a, policy)
    second, gb = _band(cube, b, policy)
    valid = ga & gb
    data = first - second
    valid &= np.isfinite(data)
    data[~valid] = np.nan
    return {"data": data, "image": data, "valid_mask": valid,
            "metadata": {"operation": "difference", "indices": [a, b],
                         "units": cube.metadata["units"], "axis": _axis(cube), "policy": policy,
                         "calculation_dtype": str(data.dtype)}}


def ratio(cube, a, b, *, minimum_denominator=1e-6, policy="diagnostic"):
    require_capability(cube, "ratio")
    if a == b:
        raise ValueError("Ratio requires two distinct indices")
    if not np.isfinite(minimum_denominator) or minimum_denominator <= 0:
        raise ValueError("minimum_denominator must be finite and positive")
    first, ga = _band(cube, a, policy)
    second, gb = _band(cube, b, policy)
    valid = ga & gb & (np.abs(second) >= minimum_denominator)
    data = np.full(first.shape, np.nan, dtype=first.dtype)
    np.divide(first, second, out=data, where=valid)
    valid &= np.isfinite(data)
    data[~valid] = np.nan
    return {"data": data, "image": data, "valid_mask": valid,
            "metadata": {"operation": "ratio", "indices": [a, b], "units": "dimensionless",
                         "minimum_denominator": minimum_denominator, "axis": _axis(cube),
                         "policy": policy, "calculation_dtype": str(data.dtype)}}


def _blocks(cube, chunk_pixels, policy="diagnostic"):
    if chunk_pixels < 1:
        raise ValueError("chunk_pixels must be positive")
    h, w, k = cube.shape
    dtype = calculation_dtype(cube.data)
    chunk = max(1, min(chunk_pixels, 64 * 1024**2 // (k * np.dtype(dtype).itemsize * 6)))
    for start in range(0, h * w, chunk):
        indices = np.arange(start, min(start + chunk, h * w))
        rows, cols = indices // w, indices % w
        selection = (rows, cols, slice(None))
        source = cube.data[selection]
        yield indices, selection, _floating(source, dtype=dtype), _valid(cube, source, selection, policy)


def pca(cube, n_components=3, *, max_samples=10000, chunk_pixels=65536, standardize=False, seed=0,
        bands=None, policy="diagnostic"):
    """Sample fit + chunked transform. Unscaled mean-centering is the default."""
    h, w, k = cube.shape
    mapping = feature_selection(cube, bands)
    require_capability(cube, "pca")
    features = mapping["feature_indices"]
    dimensions = len(features)
    if dimensions < 2 or not 1 <= n_components <= dimensions or max_samples < 2 or chunk_pixels < 1:
        raise ValueError("Invalid PCA components, max_samples or chunk size")
    sample_count = min(h * w, max_samples, max(2, 64 * 1024**2 // (k * 8)))
    rng = np.random.default_rng(seed)
    indices = rng.choice(h * w, size=sample_count, replace=False)
    selection = (indices // w, indices % w, slice(None))
    source = cube.data[selection]
    valid = np.all(_valid(cube, source, selection, policy)[:, features], axis=1)
    samples = _floating(source[valid][:, features], dtype=np.float64)
    if len(samples) < max(2, n_components):
        raise ValueError("Too few complete valid sampled spectra/state vectors for PCA")
    mean = samples.mean(axis=0)
    samples -= mean
    scale = samples.std(axis=0) if standardize else np.ones(dimensions)
    scale[scale == 0] = 1
    samples /= scale
    _, singular, vt = np.linalg.svd(samples, full_matrices=False)
    variance = singular**2 / (len(samples) - 1)
    total = variance.sum()
    explained = variance[:n_components] / total if total > 0 else np.zeros(n_components)
    components = vt[:n_components]
    scores = np.full((h * w, n_components), np.nan, dtype=calculation_dtype(cube.data))
    valid_pixels = np.zeros(h * w, dtype=bool)
    for ids, _, block, good in _blocks(cube, chunk_pixels, policy):
        rows = np.all(good[:, features], axis=1)
        transformed = ((block[rows][:, features] - mean) / scale) @ components.T
        finite = np.all(np.isfinite(transformed), axis=1)
        target = ids[rows][finite]
        scores[target] = transformed[finite]
        valid_pixels[target] = True
    return {"scores": scores.reshape(h, w, n_components), "image": scores.reshape(h, w, n_components),
            "valid_mask": valid_pixels.reshape(h, w), "components": components,
            "explained_variance_ratio": explained, "mean": mean, "scale": scale,
            "metadata": {**mapping, "fit_sample_count": len(samples), "candidate_sample_count": sample_count,
                         "seed": seed, "preprocessing": "center and unit-std" if standardize else "mean-center only",
                         "transform": "chunked", "axis": _axis(cube), "policy": policy,
                         "units": "dimensionless" if standardize else cube.metadata["units"],
                         "calculation_dtype": str(scores.dtype), "data_source": cube.metadata["data_source"]}}


def spectral_angle(cube, reference, *, chunk_pixels=65536, bands=None, policy="diagnostic"):
    mapping = feature_selection(cube, bands)
    require_capability(cube, "spectral_angle")
    features = mapping["feature_indices"]
    if len(features) < 2:
        raise ValueError("Angle requires at least two selected dimensions")
    reference = np.asarray(reference, dtype=np.float64)
    if reference.shape != (cube.shape[2],) or not np.all(np.isfinite(reference[features])):
        raise ValueError("Reference must be a K-vector finite on every selected feature")
    reference = reference[features]
    norm = np.linalg.norm(reference)
    if norm == 0 or not np.isfinite(norm):
        raise ValueError("SAM reference must have a finite nonzero norm")
    unit = reference / norm
    data = np.full(cube.shape[0] * cube.shape[1], np.nan, dtype=calculation_dtype(cube.data))
    valid = np.zeros(data.shape, dtype=bool)
    for indices, _, block, good in _blocks(cube, chunk_pixels, policy):
        values = block[:, features].astype(np.float64)
        lengths = np.linalg.norm(values, axis=1)
        rows = np.all(good[:, features], axis=1) & (lengths > 0) & np.isfinite(lengths)
        cosine = (values[rows] @ unit) / lengths[rows]
        data[indices[rows]] = np.arccos(np.clip(cosine, -1, 1))
        valid[indices[rows]] = True
    image = data.reshape(cube.shape[:2])
    return {"data": image, "image": image, "valid_mask": valid.reshape(cube.shape[:2]),
            "metadata": {**mapping, "units": "radians", "operation": "Spectral Angle Mapper",
                         "interpretation": "spectral angle difference" if cube.wavelengths is not None
                         else "state vector angle difference", "zero_vectors": "invalid", "policy": policy,
                         "reference_selected": reference.tolist(), "preprocessing": "vector length normalization",
                         "limitations": "Positive-scale invariant; not invariant to additive offsets or response changes"}}


def _saturation(cube):
    value = saturation_value(cube)
    if value is None or not np.isfinite(value):
        raise ValueError("Reflectance requires a known saturation_value or effective_bits for every input")
    return float(value)


def reflectance(sample, white, dark_sample, dark_white, *, reference_reflectance=None,
                reference_source=None, minimum_denominator=1.0, chunk_pixels=65536,
                output_path=None, memory_threshold_bytes=256 * 1024**2):
    """Strict matching, float dark subtraction, no clipping of physically unusual ratios."""
    cubes = [sample, white, dark_sample, dark_white]
    if chunk_pixels < 1 or memory_threshold_bytes < 1:
        raise ValueError("Chunk size and memory threshold must be positive")
    if not np.isfinite(minimum_denominator) or minimum_denominator <= 0:
        raise ValueError("minimum_denominator must be finite and positive")
    required = ("settings", "exposure", "gain", "processing_steps", "units", "wavelength_units")
    for cube in cubes:
        require_capability(cube, "reflectance")
        if cube.shape != sample.shape:
            raise ValueError("Reference cube shape must match sample; no implicit spatial registration")
        if cube.metadata["data_level"] != "spectral_cube" or cube.wavelengths is None:
            raise ValueError("Reflectance requires spectral cubes with actual wavelength vectors")
        if not cube.metadata.get("wavelength_source") or cube.metadata.get("linear_intensity") is not True:
            raise ValueError("Explicit wavelength source and linear_intensity=true are required")
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
        reference = np.asarray(reference_reflectance, dtype=np.float64)
        if reference.shape != (k,) or not np.all(np.isfinite(reference)) or np.any((reference < 0) | (reference > 1)):
            raise ValueError("Known reference reflectance must be a finite K-vector in [0,1]")
        if not reference_source:
            raise ValueError("Known reference reflectance requires reference_source")
        kind = "reference-calibrated"
    shape = sample.shape
    dtype = np.result_type(*[calculation_dtype(cube.data) for cube in cubes])
    needed = int(np.prod(shape)) * (dtype.itemsize + 1)
    if needed > memory_threshold_bytes and output_path is None:
        raise ValueError(f"Reflectance needs {needed} output bytes; supply output_path for out-of-core processing")
    meta = deepcopy(sample.metadata)
    source_provenance = {name: deepcopy(cube.metadata) for name, cube in
                         zip(("sample", "white", "dark_sample", "dark_white"), cubes)}
    for key in ("data_ignore_value", "envi_header", "saturation_value", "effective_bits",
                "pfnc_sample_bits", "adc_precision", "adc_precision_source", "storage_dtype",
                "pixel_format", "valid_mask_file",
                "source_file", "estimated_bytes", "dtype", "linear_intensity"):
        meta.pop(key, None)
    meta.update(data_level="reflectance_cube", units="dimensionless", reflectance_kind=kind,
                calibration_source=reference_source, reference_source=reference_source,
                reference_reflectance=reference.tolist(), source_provenance=source_provenance,
                processing_steps=list(meta["processing_steps"]) + [{"operation": "dark-corrected reference ratio",
                    "kind": kind, "minimum_denominator": minimum_denominator, "clipped": False}],
                validity_note="Output mask: finite unsaturated inputs and positive denominator above threshold",
                quality_policy="quantitative", quality_counts={"negative": 0, "above_one": 0},
                interpretation="Relative/reference-calibrated product; no metrological certification or geometry correction",
                calculation_dtype=str(dtype), schema_version=2, completed=False, partial=True,
                completed_pixels=0, axis_order="HWK", shape=list(shape), dtype=str(dtype))
    checkpoint = None
    if output_path is not None:
        path = Path(output_path)
        if path.suffix.lower() != ".npy":
            raise ValueError("Out-of-core output_path must end in .npy")
        mask_path, checkpoint = path.with_suffix(".npy.valid.npy"), path.with_suffix(".npy.json")
        if any(p.exists() for p in (path, mask_path, checkpoint)):
            raise FileExistsError("Derived target exists; choose a new path")
        path.parent.mkdir(parents=True, exist_ok=True)
        output = np.lib.format.open_memmap(path, mode="w+", dtype=dtype, shape=shape)
        validity = np.lib.format.open_memmap(mask_path, mode="w+", dtype=bool, shape=shape)
        meta.update(valid_mask_file=mask_path.name, storage="out-of-core NPY", source_file=str(path.resolve()))
    else:
        output = np.full(shape, np.nan, dtype=dtype)
        validity = np.zeros(shape, dtype=bool)

    def persist():
        if checkpoint is not None:
            from hyperlab.io.cube import _dumps
            output.flush()
            validity.flush()
            temporary = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
            temporary.write_text(_dumps(meta), encoding="utf-8")
            temporary.replace(checkpoint)

    persist()
    flat_out = output.reshape(-1, k)
    flat_valid = validity.reshape(-1, k)
    try:
        for indices, selection, first, good in _blocks(sample, chunk_pixels):
            values = [first.astype(dtype, copy=False)]
            good &= first < saturations[0]
            for cube, saturation in zip(cubes[1:], saturations[1:]):
                source = cube.data[selection]
                block = _floating(source, dtype=dtype)
                values.append(block)
                good &= _valid(cube, source, selection) & (block < saturation)
            numerator = values[0] - values[2]
            denominator = values[1] - values[3]
            good &= denominator >= minimum_denominator
            corrected = np.full(first.shape, np.nan, dtype=dtype)
            np.divide(numerator, denominator, out=corrected, where=good)
            corrected *= reference
            good &= np.isfinite(corrected)
            corrected[~good] = np.nan
            flat_out[indices] = corrected
            flat_valid[indices] = good
            meta["quality_counts"]["negative"] += int(np.count_nonzero(good & (corrected < 0)))
            meta["quality_counts"]["above_one"] += int(np.count_nonzero(good & (corrected > 1)))
            meta["completed_pixels"] = int(indices[-1]) + 1
            persist()
        meta.update(completed=True, partial=False)
        persist()
    except BaseException:
        if checkpoint is not None:
            Cube(output, meta, validity).close()
        raise
    return Cube(output, meta, validity)
