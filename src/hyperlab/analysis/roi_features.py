"""Descriptive ROI comparisons and features on documented wavelength coordinates."""
from copy import deepcopy
from math import factorial

import numpy as np

from hyperlab.io.cube import wavelength_unit_scale
from .capabilities import capabilities, require_capability


CORRELATION_TOLERANCE = 1e-12
POLYNOMIAL_RCOND = 1e-12


def _summaries(cube, results, summary):
    if summary not in {"mean", "median"}:
        raise ValueError("Summary must be mean or median")
    if not results:
        raise ValueError("At least one ROI summary is required")
    policies, supports, values, selections = set(), set(), [], []
    for result in results:
        meta = result.get("metadata", {})
        if summary == "median" and meta.get("robust_computed") is False:
            raise ValueError("Median requires computed robust ROI statistics")
        value = np.asarray(result[summary], dtype=np.float64)
        counts = np.asarray(result["count"])
        if value.shape != (cube.shape[2],) or counts.shape != value.shape:
            raise ValueError("ROI summaries must have the source's full feature dimension")
        if result.get("units") != cube.metadata["units"]:
            raise ValueError("ROI signal units mismatch")
        wave = result.get("wavelengths")
        if (wave is None) != (cube.wavelengths is None) or (wave is not None and
                (not np.array_equal(wave, cube.wavelengths) or
                 result.get("wavelength_units") != cube.metadata["wavelength_units"])):
            raise ValueError("ROI wavelength axis mismatch")
        provenance = meta.get("source_provenance", {})
        for key in ("source_file", "session_id", "stream_epoch", "sequence", "host_monotonic_ns", "data_level"):
            if provenance.get(key) != cube.metadata.get(key):
                raise ValueError(f"ROI source identity mismatch: {key}")
        policies.add(result.get("policy", "diagnostic"))
        supports.add(result.get("support", "per_band"))
        selections.append(result.get("feature_indices", list(range(cube.shape[2]))))
        values.append(np.where(counts > 0, value, np.nan))
    if len(policies) != 1 or len(supports) != 1:
        raise ValueError("Compared ROI summaries must use one quality policy and spatial support mode")
    return np.asarray(values), selections, {"summary": summary, "support": supports.pop(),
        "policy": policies.pop(), "source_provenance": deepcopy(cube.metadata),
        "aggregation_order": "summary_then_transform"}


def roi_pairwise(cube, results, names, *, summary="mean"):
    """One feature population for every pair; undefined metrics retain their reason."""
    results, names = list(results), list(names)
    if len(results) < 2 or len(names) != len(results) or any(not str(name).strip() for name in names):
        raise ValueError("Pairwise comparison requires at least two named ROI summaries")
    values, selections, metadata = _summaries(cube, results, summary)
    capability = capabilities(cube)
    chosen = set(capability["feature_indices"]).intersection(*map(set, selections))
    features = [i for i in range(cube.shape[2]) if i in chosen and np.all(np.isfinite(values[:, i]))]
    domain = capability["axis_kind"]
    correlation_label = {"color_channel": "Channel correlation", "state": "State-vector correlation",
                         "wavelength": "Spectral-shape correlation"}.get(domain, "Correlation")
    metadata.update(feature_indices=features, feature_count=len(features),
        excluded_features=[{"index": i, "reason": "not selected or globally invalid" if i not in chosen
                            else "not finite/used in every ROI"}
                           for i in range(cube.shape[2]) if i not in features],
        weighting="equal feature weights", bias_direction="target minus reference",
        units=cube.metadata["units"], angle_units="rad", correlation_label=correlation_label,
        correlation_near_constant_tolerance=CORRELATION_TOLERANCE, names=names,
        metric_domain=domain, support_counts=[np.asarray(result["count"]).tolist() for result in results],
        rectangles=[list(result["rect"]) for result in results],
        interpretation="descriptive ROI comparison; no significance test, material label or defect probability")
    pairs = []
    for target in range(1, len(results)):
        for reference in range(target):
            pair = {"target": names[target], "reference": names[reference], "target_index": target,
                    "reference_index": reference, "bias": None, "rmse": None,
                    "correlation": None, "angle": None, "unavailable": {}, "feature_count": len(features)}
            if not features:
                pair["unavailable"] = {name: "No common finite features across all ROIs"
                                        for name in ("bias", "rmse", "correlation", "angle")}
                pairs.append(pair)
                continue
            x, y = values[target, features], values[reference, features]
            with np.errstate(over="ignore", invalid="ignore"):
                residual = x-y
                scale = np.max(np.abs(residual))
                bias = scale*np.mean(residual/scale) if scale > 0 else 0.
                rmse = scale*np.sqrt(np.mean((residual/scale)**2)) if scale > 0 else 0.
            for name, value in (("bias", bias), ("rmse", rmse)):
                if np.isfinite(value):
                    pair[name] = float(value)
                else:
                    pair["unavailable"][name] = "Amplitude result is not representable as finite float64"
            sx, sy = np.max(np.abs(x)), np.max(np.abs(y))
            nx, ny = (x/sx if sx else x), (y/sy if sy else y)
            cx, cy = nx-nx.mean(), ny-ny.mean()
            if len(features) < 3:
                pair["unavailable"]["correlation"] = "Correlation needs at least three common features"
            elif (np.linalg.norm(cx) <= CORRELATION_TOLERANCE*np.linalg.norm(nx) or
                  np.linalg.norm(cy) <= CORRELATION_TOLERANCE*np.linalg.norm(ny)):
                pair["unavailable"]["correlation"] = "Constant or near-constant summary vector"
            else:
                pair["correlation"] = float(np.clip(np.dot(cx/np.linalg.norm(cx), cy/np.linalg.norm(cy)), -1, 1))
            if not capability["operations"]["spectral_angle"]:
                pair["unavailable"]["angle"] = capability["reasons"]["spectral_angle"]
            elif len(features) < 2:
                pair["unavailable"]["angle"] = "Angle needs at least two common features"
            elif sx == 0 or sy == 0:
                pair["unavailable"]["angle"] = "Zero-norm summary vector"
            else:
                pair["angle"] = float(np.arccos(np.clip(np.dot(nx/np.linalg.norm(nx), ny/np.linalg.norm(ny)), -1, 1)))
            pairs.append(pair)
    return {"pairs": pairs, "metadata": metadata}


def local_polynomial(wavelengths_nm, values, *, derivative=0, window=5, degree=2):
    """Complete centered windows on true increasing coordinates; no edge extension."""
    x, y = np.asarray(wavelengths_nm, np.float64), np.asarray(values, np.float64)
    if (x.ndim != 1 or y.shape != x.shape or not np.all(np.isfinite(x)) or
            np.any(np.diff(x) <= 0)):
        raise ValueError("Local polynomial needs matching 1D values and finite increasing wavelengths")
    if (any(isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, np.integer))
            for v in (window, degree, derivative)) or window < 3 or window % 2 != 1 or
            not 0 <= derivative <= degree < window or len(x) < window):
        raise ValueError("Local polynomial requires an odd complete window, 0 <= derivative <= degree < window")
    output = np.full(y.shape, np.nan)
    reasons = ["Unsupported centered edge window"] * len(x)
    half = window//2
    for center in range(half, len(x)-half):
        selected = slice(center-half, center+half+1)
        signal = y[selected]
        if not np.all(np.isfinite(signal)):
            reasons[center] = "Incomplete finite window"
            continue
        offsets = x[selected]-x[center]
        scale = np.max(np.abs(offsets))
        design = np.vander(offsets/scale, N=degree+1, increasing=True)
        coefficient, _, rank, _ = np.linalg.lstsq(design, signal, rcond=POLYNOMIAL_RCOND)
        if rank != degree+1:
            reasons[center] = "Rank-deficient polynomial window"
            continue
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            value = factorial(derivative)*coefficient[derivative]/scale**derivative
        if not np.isfinite(value):
            reasons[center] = "Nonfinite polynomial result"
            continue
        output[center], reasons[center] = value, None
    return {"y": output, "valid_mask": np.isfinite(output), "invalid_reasons": reasons,
            "metadata": {"method": "Local polynomial", "window": int(window), "degree": int(degree),
                         "derivative_order": int(derivative), "rank_rcond": POLYNOMIAL_RCOND,
                         "offset_scale": "maximum absolute wavelength offset within each centered window",
                         "edge_policy": "invalid without a complete centered window"}}


def _interval_area(x, y):
    with np.errstate(over="ignore", invalid="ignore"):
        value = np.sum((y[:-1]*.5+y[1:]*.5)*np.diff(x))
    return float(value) if np.isfinite(value) else None


def spectral_roi_features(cube, results, operation, *, summary="mean", bands=None, window=5, degree=2):
    """Feature of a common-support ROI summary; never a propagated SD/IQR ribbon."""
    operations = {"smooth": 0, "derivative1": 1, "derivative2": 2, "integral": None, "continuum": None}
    if operation not in operations:
        raise ValueError("Unknown spectral ROI operation")
    require_capability(cube, "continuum" if operation == "continuum" else "spectral_features")
    results = list(results)
    values, selections, metadata = _summaries(cube, results, summary)
    if metadata["support"] != "common":
        raise ValueError("Spectral ROI features require common spatial support over the selected bands")
    selected = list(range(cube.shape[2])) if bands is None else list(bands)
    if (not selected or any(isinstance(i, (bool, np.bool_)) or not isinstance(i, (int, np.integer))
                            or not 0 <= i < cube.shape[2] for i in selected) or len(set(selected)) != len(selected)):
        raise ValueError("Spectral feature indices must be nonempty, unique integers inside the cube")
    if not set(selected).issubset(capabilities(cube)["feature_indices"]):
        raise ValueError("Selected spectral interval contains globally invalid bands")
    if any(set(indices) != set(selected) for indices in selections):
        raise ValueError("ROI common support must match exactly the selected spectral interval")
    with np.errstate(over="ignore", invalid="ignore"):
        all_nm = cube.wavelengths*wavelength_unit_scale(cube.metadata["wavelength_units"])
    if not np.all(np.isfinite(all_nm)):
        raise ValueError("Wavelength conversion to nm must remain finite")
    order = np.argsort(all_nm[selected])
    indices = np.asarray(selected, int)[order]
    x = all_nm[indices]
    if len(indices) < (3 if operation == "continuum" else 2) or np.any(np.abs(np.diff(indices)) != 1):
        raise ValueError("Spectral features need contiguous original bands without gaps and sufficient interval samples")
    derivative = operations[operation]
    source_units = cube.metadata["units"]
    units = "dimensionless" if operation == "continuum" else (
        source_units if derivative in (None, 0) else f"{source_units}/nm" + ("^2" if derivative == 2 else ""))
    metadata.update(operation=operation, feature_indices=indices.tolist(), wavelength_units="nm",
        original_wavelength_units=cube.metadata["wavelength_units"],
        original_wavelengths=cube.wavelengths[indices].tolist(), source_units=source_units, units=units,
        actual_interval_nm=[float(x[0]), float(x[-1])], interval_span_nm=float(x[-1]-x[0]),
        gap_policy="complete contiguous original band interval; no interpolation or extrapolation",
        uncertainty="not supplied; spatial SD/IQR are not propagated through a summary transformation",
        reflectance_kind=cube.metadata.get("reflectance_kind"),
        wavelength_evidence=cube.metadata.get("wavelength_evidence"),
        interpretation=f"Feature of ROI {summary}; not mean of transformed pixel features")
    curves = []
    for number, result in enumerate(results):
        used = np.asarray(result["count"])[indices]
        if np.any(used != used[0]):
            raise ValueError("Common-support ROI denominators must match across selected spectral bands")
        signal = values[number, indices].copy()
        curve = {"roi_index": number, "rect": result["rect"], "x_nm": x.copy(), "y": signal,
                 "valid_mask": np.isfinite(signal), "used_count": int(used[0]), "features": {},
                 "invalid_reasons": [None if valid else "No finite common-support summary" for valid in np.isfinite(signal)]}
        if derivative is not None:
            fitted = local_polynomial(x, signal, derivative=derivative, window=window, degree=degree)
            curve.update({key: fitted[key] for key in ("y", "valid_mask", "invalid_reasons")})
            metadata.update(fitted["metadata"])
        elif not np.all(np.isfinite(signal)):
            curve["features"] = {"status": "unavailable", "reason": "No complete finite common-support interval"}
        elif operation == "integral":
            area = _interval_area(x, signal)
            curve["features"] = {"status": "available" if area is not None else "unavailable",
                                 "integral": area, "integral_units": f"{source_units}*nm",
                                 "interval_mean": None if area is None else area/(x[-1]-x[0]),
                                 "interval_mean_units": source_units}
            if area is None:
                curve["features"]["reason"] = "Integral is not representable as finite float64"
        else:
            fraction = (x-x[0])/(x[-1]-x[0])
            continuum = (1-fraction)*signal[0]+fraction*signal[-1]
            curve["continuum"] = continuum
            if np.any(continuum <= 0) or not np.all(np.isfinite(continuum)):
                curve.update(y=np.full(len(x), np.nan), valid_mask=np.zeros(len(x), bool),
                             invalid_reasons=["Nonpositive or nonfinite endpoint continuum"]*len(x),
                             features={"status": "unavailable", "reason": "Nonpositive or nonfinite endpoint continuum"})
            else:
                with np.errstate(over="ignore", invalid="ignore"):
                    ratio = signal/continuum
                    depth = 1-ratio
                if not np.all(np.isfinite(depth)):
                    curve.update(y=np.where(np.isfinite(depth), depth, np.nan),
                                 continuum_ratio=np.where(np.isfinite(ratio), ratio, np.nan),
                                 valid_mask=np.isfinite(depth),
                                 invalid_reasons=[None if valid else "Nonfinite continuum ratio" for valid in np.isfinite(depth)],
                                 features={"status": "unavailable", "reason": "Incomplete finite continuum ratio"})
                    curves.append(curve)
                    continue
                minimum = int(np.argmin(ratio))
                curve.update(y=depth, continuum_ratio=ratio, valid_mask=np.isfinite(depth))
                area = _interval_area(x, depth)
                curve["features"] = {"status": "available" if area is not None else "partial", "depth_area_nm": area,
                    "maximum_depth": float(depth[minimum]), "sampled_minimum_nm": float(x[minimum]),
                    "sampled_minimum_index": int(indices[minimum]), "sampled_minimum_ratio": float(ratio[minimum]),
                    "minimum_at_boundary": minimum in (0, len(x)-1), "minimum_tie_policy": "first increasing wavelength"}
                if area is None:
                    curve["features"]["reason"] = "Depth area is not representable as finite float64"
        curves.append(curve)
    return {"curves": curves, "metadata": metadata}
