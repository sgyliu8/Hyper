"""One semantic gate shared by interactive and command-line analysis."""
import numpy as np

from hyperlab.io.cube import wavelength_unit_scale


def capabilities(cube):
    meta = cube.metadata
    level = meta["data_level"]
    k = cube.shape[2]
    indices = np.flatnonzero(np.asarray(meta.get("band_validity", [True] * k), bool)).tolist()
    color = bool(meta.get("channel_labels"))
    bayer = "bayer" in str(meta.get("pixel_format", "")).lower()
    spectral = (level in {"spectral_cube", "reflectance_cube"} and cube.wavelengths is not None
                and wavelength_unit_scale(meta.get("wavelength_units")) is not None
                and bool(meta.get("wavelength_source"))
                and meta.get("wavelength_order") not in {"nonmonotonic", "duplicate"})
    state = level == "raw_scan" and cube.wavelengths is None and not color
    axis = "color_channel" if color else "wavelength" if cube.wavelengths is not None else "state" if state else "sensor_plane"
    vector = (state or spectral) and not (bayer and k == 1) and len(indices) >= 2
    wavelength_features = spectral and len(indices) >= 2 and bool(np.all(cube.wavelengths > 0))
    operations = {"roi": True, "histogram": True, "export": True,
                  "cfa": bayer and k == 1, "temporal": level == "raw_frame",
                  "pca": vector, "spectral_angle": vector,
                  "difference": len(indices) >= 2 and not (bayer and k == 1),
                  "ratio": len(indices) >= 2 and not (bayer and k == 1),
                  "spectral_features": wavelength_features,
                  "continuum": wavelength_features and level == "reflectance_cube" and len(indices) >= 3,
                  "reflectance": spectral and level == "spectral_cube"
                    and meta.get("linear_intensity") is True}
    reasons = {}
    for operation, enabled in operations.items():
        if enabled:
            continue
        if operation == "cfa":
            reasons[operation] = "CFA statistics require one raw Bayer mosaic."
        elif operation == "temporal":
            reasons[operation] = "Temporal statistics require a sequence of matching frames."
        elif operation == "reflectance":
            reasons[operation] = "Requires a documented wavelength axis, linear_intensity=true and matched references."
        elif operation == "spectral_features":
            reasons[operation] = "Requires at least two documented, positive, ordered wavelengths with known units."
        elif operation == "continuum":
            reasons[operation] = "Requires a reflectance cube and at least three documented, positive, ordered wavelengths."
        elif len(indices) < 2:
            reasons[operation] = "Requires at least two enabled dimensions; one sensor channel is not a spectrum."
        elif color:
            reasons[operation] = "RGB permits channel statistics; color channels are not a spectral or state vector."
        else:
            reasons[operation] = "Requires scan states or an ordered wavelength axis with known units and source."
    return {"axis_kind": axis, "axis_label": {"color_channel": "color_channel_index",
                "state": "state_index", "wavelength": "wavelength", "sensor_plane": "sensor_plane"}[axis],
            "feature_indices": indices, "effective_dimensions": len(indices),
            "operations": operations, "reasons": reasons,
            "wavelength_evidence": meta.get("wavelength_evidence", "declared" if cube.wavelengths is not None else None)}


def require_capability(cube, operation):
    result = capabilities(cube)
    if not result["operations"].get(operation, False):
        raise ValueError(result["reasons"].get(operation, f"Unsupported operation: {operation}"))
    return result


def feature_selection(cube, bands=None):
    k = cube.shape[2]
    requested = list(range(k)) if bands is None else list(bands)
    if (any(not isinstance(i, (int, np.integer)) or not 0 <= i < k for i in requested)
            or len(set(requested)) != len(requested)):
        raise ValueError("Feature indices must be unique integer indices inside the cube")
    enabled = np.asarray(cube.metadata.get("band_validity", [True] * k), bool)
    chosen = [int(i) for i in requested if enabled[i]]
    if not chosen:
        raise ValueError("No enabled features remain after band selection")
    excluded = [{"index": i, "reason": "globally invalid band" if not enabled[i] else "not selected"}
                for i in range(k) if i not in chosen]
    return {"feature_indices": chosen, "excluded_features": excluded, "original_dimensions": k,
            "input_dimensions": len(chosen), "feature_wavelengths": None if cube.wavelengths is None
                else cube.wavelengths[chosen].tolist(), "wavelength_units": cube.metadata["wavelength_units"],
            "feature_wavelength_units": cube.metadata["wavelength_units"]}
