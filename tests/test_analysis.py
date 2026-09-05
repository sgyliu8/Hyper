import numpy as np
import pytest

from hyperlab.analysis import (composite, difference, export_roi_csv, pca, ratio,
                               reflectance, roi_statistics, spectral_angle)
from hyperlab.io import Cube, make_synthetic_cube


def test_roi_two_rectangles_and_csv(tmp_path):
    data = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
    valid = np.ones(data.shape, dtype=bool)
    valid[0, 0, 0] = False
    cube = Cube(data, valid_mask=valid)
    first = roi_statistics(cube, (0, 0, 2, 2))
    second = roi_statistics(cube, (2, 0, 3, 2))
    assert first["count"].tolist() == [3, 4, 4, 4]
    assert first["mean"][0] == np.mean([4, 12, 16])
    np.testing.assert_allclose(second["mean"], data[:, 2, :].mean(axis=0))
    assert first["axis_label"] == "state_index"
    export_roi_csv(first, tmp_path / "roi.csv")
    text = (tmp_path / "roi.csv").read_text()
    assert "valid_count" in text and "nm" not in text
    with pytest.raises(ValueError):
        roi_statistics(cube, (0, 0, 0, 2))


def test_difference_ratio_and_invalid_masks():
    data = np.array([[[1, 2], [10, 0]], [[3, np.nan], [4, 2]]], dtype=np.float32)
    cube = Cube(data)
    diff = difference(cube, 0, 1)
    assert diff["data"][0, 0] == -1
    assert not diff["valid_mask"][1, 0]
    result = ratio(cube, 0, 1)
    assert result["data"][0, 0] == 0.5
    assert np.isnan(result["data"][0, 1])
    assert result["valid_mask"].sum() == 2


def test_composite_preserves_source_and_labels():
    cube = make_synthetic_cube()
    before = cube.data.copy()
    result = composite(cube, (18, 12, 4))
    assert result["image"].shape == (48, 64, 3)
    assert np.all(np.isfinite(result["image"]))
    assert result["image"].min() >= 0 and result["image"].max() <= 1
    assert result["wavelengths"] == cube.wavelengths[[18, 12, 4]].tolist()
    np.testing.assert_array_equal(cube.data, before)


def test_pca_known_rank_and_invalid_pixel():
    base = np.arange(60, dtype=np.float32).reshape(10, 6)
    data = base[:, :, None] * np.array([1, 2, 3, 4])[None, None, :]
    data[0, 0] = np.nan
    cube = Cube(data)
    result = pca(cube, max_samples=60, chunk_pixels=7)
    assert result["scores"].shape == (10, 6, 3)
    assert result["explained_variance_ratio"][0] == pytest.approx(1.0)
    assert result["metadata"]["fit_sample_count"] == 59
    assert result["metadata"]["preprocessing"] == "mean-center only"
    assert not result["valid_mask"][0, 0]
    assert np.isnan(result["scores"][0, 0]).all()


def test_sam_brightness_invariance_zero_protection_and_units():
    cube = Cube(np.array([[[1., 2., 3.], [2., 4., 6.]], [[0., 0., 0.], [3., 2., 1.]]]))
    result = spectral_angle(cube, [1, 2, 3], chunk_pixels=1)
    np.testing.assert_allclose(result["data"][0], 0, atol=2e-8)
    assert result["data"][1, 1] > 0
    assert not result["valid_mask"][1, 0]
    assert result["metadata"]["units"] == "radians"
    assert result["metadata"]["interpretation"] == "state vector angle difference"
    with pytest.raises(ValueError, match="nonzero"):
        spectral_angle(cube, [0, 0, 0])


def calibrated(data):
    return Cube(np.asarray(data, dtype=np.uint16).reshape(1, 2, 2), {
        "data_level": "spectral_cube", "wavelengths": [500, 600], "wavelength_units": "nm",
        "wavelength_source": "test fixture only", "linear_intensity": True, "units": "DN",
        "settings": {"recipe": "fixture"}, "exposure": 10, "gain": 1,
        "processing_steps": [], "completed": True, "partial": False, "effective_bits": 12,
        "data_source": "SYNTHETIC", "synthetic": True})


def test_reflectance_float_dark_saturation_low_denominator_no_clip():
    sample = calibrated([5, 4095, 200, 30])
    white = calibrated([100, 100, 10, 20])
    dark_s = calibrated([10, 10, 10, 10])
    dark_w = calibrated([10, 10, 10, 10])
    result = reflectance(sample, white, dark_s, dark_w, chunk_pixels=1)
    assert result.data[0, 0, 0] == pytest.approx(-5 / 90)  # No uint16 underflow.
    assert not result.valid_mask[0, 0, 1]  # Saturated sample.
    assert not result.valid_mask[0, 1, 0]  # White-dark = zero.
    assert result.data[0, 1, 1] == 2  # Not silently clipped to one.
    assert result.metadata["reflectance_kind"] == "relative"


@pytest.mark.parametrize("key,value", [("exposure", 11), ("gain", 2), ("settings", {"recipe": "other"}),
                                        ("processing_steps", ["unverified"]), ("wavelength_units", "um"),
                                        ("units", "radiance")])
def test_reflectance_setting_mismatch_rejected(key, value):
    cubes = [calibrated([20, 30, 40, 50]) for _ in range(4)]
    cubes[1].metadata[key] = value
    with pytest.raises(ValueError, match="mismatch"):
        reflectance(*cubes)


def test_reflectance_wave_unknown_partial_and_reference_provenance():
    sample, white, ds, dw = [calibrated(data) for data in ([30]*4, [100]*4, [10]*4, [10]*4)]
    white.metadata["wavelengths"] = [501, 600]
    with pytest.raises(ValueError, match="Wavelength"):
        reflectance(sample, white, ds, dw)
    white.metadata["wavelengths"] = [500, 600]
    ds.metadata["linear_intensity"] = False
    with pytest.raises(ValueError, match="linear_intensity"):
        reflectance(sample, white, ds, dw)
    ds.metadata["linear_intensity"] = True
    ds.metadata["partial"] = True
    with pytest.raises(ValueError, match="partial"):
        reflectance(sample, white, ds, dw)
    ds.metadata["partial"] = False
    with pytest.raises(ValueError, match="reference_source"):
        reflectance(sample, white, ds, dw, reference_reflectance=[.9, .8])
    result = reflectance(sample, white, ds, dw, reference_reflectance=[.9, .8], reference_source="synthetic board")
    assert result.metadata["reflectance_kind"] == "reference-calibrated"
    np.testing.assert_allclose(result.data[0, 0], [0.2, 20 / 90 * .8])


def test_envi_ignore_and_bad_band_propagate():
    cube = Cube(np.array([[[1., 2.], [-9999, 4.]]]), {"data_ignore_value": -9999, "band_validity": [True, False]})
    stats = roi_statistics(cube, (0, 0, 2, 1))
    assert stats["count"].tolist() == [1, 0]
    assert np.isnan(stats["mean"][1])
