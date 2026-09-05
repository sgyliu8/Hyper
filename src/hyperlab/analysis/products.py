from copy import deepcopy
import numpy as np

from hyperlab.io import Cube, save_cube


def export_product(result, path, source_cube=None):
    """Persist numerical results and masks; never substitute a stretched PNG."""
    data = result.get("data", result.get("scores"))
    if data is None:
        raise ValueError("Product needs numeric data or PCA scores")
    data = np.asarray(data)
    if data.ndim == 2:
        data = data[:, :, None]
    if data.ndim != 3:
        raise ValueError("Numeric product must be HW or HWK")
    meta = deepcopy(result.get("metadata", {}))
    meta.update(data_level="derived_map", wavelengths=None, wavelength_units=None,
                wavelength_source=None, completed=True, partial=False,
                processing_steps=[deepcopy(result.get("metadata", {}))])
    if source_cube is not None:
        meta["source_provenance"] = deepcopy(source_cube.metadata)
        meta["data_source"] = source_cube.metadata["data_source"]
        meta["acquisition_source"] = source_cube.metadata["acquisition_source"]
    for key in ("components", "mean", "scale", "explained_variance_ratio"):
        if key in result:
            meta[key] = np.asarray(result[key]).tolist()
    return save_cube(Cube(data, meta, result.get("valid_mask")), path)
