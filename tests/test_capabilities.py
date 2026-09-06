import json

import numpy as np
import pytest

from hyperlab.analysis import (TemporalStatistics, capabilities, cfa_statistics, export_product,
                               export_roi_csv, pca, quality_summary, roi_statistics, spectral_angle)
from hyperlab.io import Cube, load_cube


def test_color_statistics_export_allowed_but_not_spectral(tmp_path):
    cube = Cube(np.arange(24, dtype=np.uint8).reshape(2, 4, 3),
        {"data_level": "raw_frame", "pixel_format": "RGB8", "channel_labels": ["R", "G", "B"], "units": "DN"})
    caps = capabilities(cube)
    assert caps["operations"]["roi"] and caps["operations"]["export"]
    assert not caps["operations"]["spectral_angle"] and not caps["operations"]["pca"]
    with pytest.raises(ValueError, match="RGB"):
        spectral_angle(cube, [1, 2, 3])
    stats = roi_statistics(cube, (0, 0, 2, 2))
    path = export_roi_csv(stats, tmp_path / "rgb.csv")
    assert "color_channel_index,R,diagnostic" in path.read_text()
    provenance = json.loads(path.with_suffix(".csv.json").read_text())
    assert provenance["rect"] == [0, 0, 2, 2]


def test_bayer_is_single_plane_and_cfa_respects_roi_crop_flip():
    # Pixel value encodes its physical sensor phase. Crop origin (1,1).
    sensor = np.tile([[10, 20], [30, 40]], (3, 4))
    data = sensor[1:5, 1:7][:, ::-1]
    cube = Cube(data[:, :, None], {"data_level": "raw_frame", "pixel_format": "BayerRG12",
        "cfa_pattern": "RGGB", "cfa_offset": [1, 1], "flip_x": True, "effective_bits": 12})
    caps = capabilities(cube)
    assert caps["operations"]["cfa"] and not caps["operations"]["spectral_angle"]
    result = cfa_statistics(cube, (1, 1, 5, 4))
    assert {name: values["mean"] for name, values in result["phases"].items()} == {"R": 10, "G1": 20, "G2": 30, "B": 40}


def test_external_spectral_axis_evidence_and_order():
    meta = {"data_level": "spectral_cube", "wavelengths": [500, 600, 700],
            "wavelength_units": "nanometres", "wavelength_source": "external header declaration"}
    cube = Cube(np.ones((2, 2, 3)), meta)
    assert capabilities(cube)["operations"]["pca"]
    assert capabilities(cube)["wavelength_evidence"] == "declared"
    bad = Cube(cube.data, {**meta, "wavelengths": [500, 700, 600]})
    assert not capabilities(bad)["operations"]["pca"]
    assert bad.wavelengths.tolist() == [500, 700, 600]  # No silent reorder.
    unknown = Cube(cube.data, {**meta, "wavelength_units": "unknown"})
    assert not capabilities(unknown)["operations"]["spectral_angle"]


def test_temporal_online_matches_independent_stack_with_invalid_and_saturation():
    stack = np.array([[[1., 2], [3, 4]], [[3., 4], [5, 6]], [[5., np.nan], [7, 8]]])
    stats = TemporalStatistics((2, 2), saturation_value=7)
    for frame in stack:
        stats.update(frame)
    result = stats.result()
    np.testing.assert_allclose(result["mean"], np.nanmean(stack, axis=0))
    np.testing.assert_allclose(result["std"], np.nanstd(stack, axis=0))
    assert result["saturated_count"].sum() == 2
    assert result["metadata"]["axis_kind"] == "time" and result["metadata"]["wavelengths"] is None


def test_product_retains_feature_mapping_and_numerical_components(tmp_path):
    cube = Cube(np.arange(24, dtype=float).reshape(2, 4, 3), {"band_validity": [True, False, True]})
    result = pca(cube, n_components=2, max_samples=8)
    path = export_product(result, tmp_path / "pca.npy", cube)
    with load_cube(path) as reopened:
        np.testing.assert_allclose(reopened.data, result["scores"])
        assert reopened.metadata["feature_indices"] == [0, 2]
        np.testing.assert_allclose(reopened.metadata["components"], result["components"])
        assert reopened.wavelengths is None


def test_unknown_saturation_is_not_dtype_maximum():
    cube = Cube(np.array([[[65535]]], np.uint16), {"data_level": "raw_frame"})
    assert quality_summary(cube, policy="quantitative")["saturation_fraction"] is None
