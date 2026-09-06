"""Independent numeric examples for the frozen ROI scientific feature contract."""
import csv
from copy import deepcopy
import json

import numpy as np
import pytest

from hyperlab.analysis.core import export_roi_csv, roi_comparison, roi_statistics
from hyperlab.analysis.quality import cfa_statistics, quality_summary
from hyperlab.analysis.roi_features import local_polynomial, roi_pairwise, spectral_roi_features
from hyperlab.io import Cube


def spectrum(values, wavelengths=None, *, level="spectral_cube", units="nm", **metadata):
    data = np.asarray(values, dtype=np.float64)
    if data.ndim == 1:
        data = data[None, None, :]
    elif data.ndim == 2:
        data = data[None, :, :]
    waves = np.arange(data.shape[2])*10+500 if wavelengths is None else wavelengths
    return Cube(data, {"data_level": level, "wavelengths": waves, "wavelength_units": units,
        "wavelength_source": "analytic test fixture, not instrument calibration",
        "data_source": "SYNTHETIC", "synthetic": True,
        "units": "dimensionless" if level == "reflectance_cube" else "DN", **metadata})


def pixel_rois(cube, **kwargs):
    return [roi_statistics(cube, (i, 0, i+1, 1), **kwargs) for i in range(cube.shape[1])]


def test_robust_quantiles_mad_and_immutable_full_k_output(tmp_path):
    cube = Cube(np.array([1, 2, 3, 100], np.uint16).reshape(1, 4, 1))
    cube.data.setflags(write=False)
    before, metadata = cube.data.tobytes(), deepcopy(cube.metadata)
    result = roi_comparison(cube, [(0, 0, 4, 1)])[0]
    expected = {"median": 2.5, "q25": 1.75, "q75": 27.25, "iqr": 25.5,
                "mad": 1, "min": 1, "max": 100, "mean": 26.5}
    for key, value in expected.items():
        np.testing.assert_allclose(result[key], [value])
    assert result["metadata"]["quantile_method"] == "linear"
    assert result["metadata"]["mad_scale"] == "unscaled"
    assert result["distribution"]["counts"].sum() == 4
    assert result["count"].tolist() == result["counts"]["valid"].tolist() == [4]
    path = export_roi_csv(result, tmp_path/"robust.csv")
    row = next(csv.DictReader(path.open(encoding="utf-8")))
    assert float(row["q25"]) == 1.75 and float(row["mad_unscaled"]) == 1
    assert int(row["valid_count"]) == int(row["policy_valid_count"]) == 4
    record = json.loads(path.with_suffix(".csv.json").read_text())
    assert record["schema_version"] == 2
    assert "actual samples" in record["count_columns"]["valid_count"]
    assert cube.data.tobytes() == before and cube.metadata == metadata


def test_common_support_preserves_original_quality_and_used_denominators(tmp_path):
    cube = Cube(np.array([[[1, 10, 100], [np.nan, 20, 200], [3, 30, 300],
                          [4095, 40, 400], [0, 50, 500]]]),
                {"effective_bits": 12, "data_ignore_value": 0})
    result = roi_statistics(cube, (0, 0, 5, 1), policy="quantitative", bands=[0, 1], support="common")
    assert result["counts"]["valid"].tolist() == [2, 5, 5]
    assert result["count"].tolist() == [2, 2, 0]
    assert result["support_excluded_count"].tolist() == [0, 3, 0]
    assert result["selection_excluded_count"].tolist() == [0, 0, 5]
    np.testing.assert_array_equal(result["count"]+result["support_excluded_count"]+
                                  result["selection_excluded_count"], result["counts"]["valid"])
    np.testing.assert_allclose(result["mean"], [2, 20, np.nan], equal_nan=True)
    np.testing.assert_allclose(result["valid_fraction"], [.4, 1, 1])
    np.testing.assert_allclose(result["used_fraction"], [.4, .4, 0])
    assert result["common_count"] == 2
    path = export_roi_csv(result, tmp_path/"support.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows[1]["valid_count"] == "2" and rows[1]["policy_valid_count"] == "5"
    assert rows[1]["support_excluded_count"] == "3" and rows[1]["support"] == "common"


def test_complementary_masks_do_not_manufacture_a_complete_spectrum():
    cube = spectrum([[1, np.nan], [np.nan, 9]])
    independent = roi_statistics(cube, (0, 0, 2, 1))
    common = roi_statistics(cube, (0, 0, 2, 1), support="common")
    np.testing.assert_array_equal(independent["mean"], [1, 9])
    assert common["count"].tolist() == [0, 0] and common["common_count"] == 0
    assert np.isnan(common["mean"]).all() and np.isnan(common["mad"]).all()
    assert common["counts"]["valid"].tolist() == [1, 1]
    assert common["support_excluded_count"].tolist() == [1, 1]
    feature = spectral_roi_features(cube, [common], "integral")["curves"][0]
    assert feature["features"]["status"] == "unavailable"


def test_globally_bad_band_does_not_enter_unrelated_common_support():
    cube = spectrum([[1, np.nan, 3], [2, np.nan, 4]], band_validity=[True, False, True])
    result = roi_statistics(cube, (0, 0, 2, 1), support="common")
    assert result["feature_indices"] == [0, 2]
    assert result["count"].tolist() == [2, 0, 2] and result["common_count"] == 2
    np.testing.assert_allclose(result["median"], [1.5, np.nan, 3.5], equal_nan=True)
    empty = spectrum([1, 2, 3], band_validity=[False, False, False])
    result = roi_statistics(empty, (0, 0, 1, 1), support="common")
    assert result["common_count"] == 0 and result["count"].sum() == 0


@pytest.mark.parametrize("bands", [[], [0, 0], [-1], [3], [True], [0.5]])
def test_roi_selected_indices_reject_ambiguous_or_empty_selection(bands):
    with pytest.raises(ValueError, match="indices"):
        roi_statistics(spectrum([1, 2, 3]), (0, 0, 1, 1), bands=bands)


def test_singleton_and_diagnostic_fast_path_do_not_claim_precision(monkeypatch):
    cube = spectrum([10, 20, 30])
    result = roi_statistics(cube, (0, 0, 1, 1))
    np.testing.assert_array_equal(result["std"], [0, 0, 0])
    np.testing.assert_array_equal(result["mad"], [0, 0, 0])
    assert "spatial SD" in result["metadata"]["std_interpretation"]
    monkeypatch.setattr(np, "quantile", lambda *args, **kwargs: pytest.fail("Quantiles in diagnostic hot path"))
    quality = quality_summary(cube)
    assert quality["valid"] == 3 and quality["per_channel"]["metadata"]["robust_computed"] is False
    mosaic = Cube(np.arange(4).reshape(2, 2, 1), {"data_level": "raw_frame", "pixel_format": "BayerRG12"})
    cfa = cfa_statistics(mosaic)
    assert cfa["phases"]["R"]["mean"] == 0 and cfa["phases"]["B"]["mean"] == 3


def test_roi_robust_precision_and_high_integer_rejection():
    base = 2**32
    cube = Cube(np.array([base+1, base+2, base+3], dtype=np.uint64).reshape(1, 3, 1))
    result = roi_statistics(cube, (0, 0, 3, 1))
    assert result["median"][0] == base+2 and result["mad"][0] == 1
    cube = Cube(np.array([2**53+1], dtype=np.uint64).reshape(1, 1, 1))
    with pytest.raises(ValueError, match="exact float64"):
        roi_statistics(cube, (0, 0, 1, 1))


def test_pairwise_positive_scale_offset_and_signed_amplitude():
    cube = spectrum([[1, 2, 4], [2, 4, 8], [6, 7, 9]])
    result = roi_pairwise(cube, pixel_rois(cube), ["Reference", "Scaled", "Offset"])
    scaled, offset = result["pairs"][:2]
    assert scaled["target"] == "Scaled" and scaled["reference"] == "Reference"
    assert scaled["bias"] == pytest.approx(7/3) and scaled["rmse"] == pytest.approx(np.sqrt(7))
    assert scaled["angle"] == pytest.approx(0, abs=2e-8) and scaled["correlation"] == pytest.approx(1)
    assert offset["bias"] == 5 and offset["rmse"] == 5 and offset["angle"] > 0
    assert offset["correlation"] == pytest.approx(1)
    assert result["metadata"]["feature_indices"] == [0, 1, 2]
    assert result["metadata"]["bias_direction"] == "target minus reference"
    assert result["metadata"]["angle_units"] == "rad"


def test_pairwise_uses_one_common_population_for_all_pairs_and_keeps_nulls():
    cube = spectrum([[1, 2, 3, 4], [2, 4, np.nan, 8], [3, 6, 9, np.nan]])
    result = roi_pairwise(cube, pixel_rois(cube), ["A", "B", "C"])
    assert result["metadata"]["feature_indices"] == [0, 1]
    assert len(result["pairs"]) == 3
    for pair in result["pairs"]:
        assert pair["rmse"] is not None and pair["correlation"] is None
        assert "three" in pair["unavailable"]["correlation"]
    no_common = roi_pairwise(cube, pixel_rois(cube, support="common"), ["A", "B", "C"])
    assert no_common["metadata"]["feature_indices"] == []
    assert len(no_common["pairs"]) == 3
    assert all(len(pair["unavailable"]) == 4 for pair in no_common["pairs"])


@pytest.mark.parametrize("scale", [1., 1e-9])
def test_constant_near_constant_and_zero_vectors_retain_defined_metrics(scale):
    cube = spectrum(np.array([[0, 0, 0], [1, 1, 1], [1, 1+1e-14, 1-1e-14]])*scale)
    result = roi_pairwise(cube, pixel_rois(cube), ["Zero", "Constant", "Near constant"])
    assert result["pairs"][0]["angle"] is None
    assert "Zero" in result["pairs"][0]["unavailable"]["angle"]
    assert result["pairs"][0]["rmse"] == pytest.approx(scale)
    assert all(pair["correlation"] is None for pair in result["pairs"])


def test_rgb_and_single_plane_metrics_keep_their_domains():
    rgb = Cube(np.array([[[1., 2., 3.], [2., 4., 6.]]]),
               {"data_level": "raw_frame", "channel_labels": ["R", "G", "B"], "units": "DN"})
    result = roi_pairwise(rgb, pixel_rois(rgb), ["A", "B"])
    assert result["metadata"]["correlation_label"] == "Channel correlation"
    assert result["pairs"][0]["correlation"] == pytest.approx(1)
    assert result["pairs"][0]["angle"] is None
    assert "RGB" in result["pairs"][0]["unavailable"]["angle"]
    plane = Cube(np.array([[[3.], [7.]]]), {"data_level": "raw_frame", "pixel_format": "BayerRG12"})
    pair = roi_pairwise(plane, pixel_rois(plane), ["A", "B"])["pairs"][0]
    assert pair["bias"] == pair["rmse"] == 4 and pair["correlation"] is None and pair["angle"] is None


def test_pairwise_rejects_mixed_support_units_or_source_and_uncomputed_median():
    cube = spectrum([[1, 2, 3], [3, 2, 1]], source_file="fixture-A.npy")
    results = pixel_rois(cube)
    results[1]["support"] = "common"
    with pytest.raises(ValueError, match="support"):
        roi_pairwise(cube, results, ["A", "B"])
    results = pixel_rois(cube)
    results[1]["units"] = "radiance"
    with pytest.raises(ValueError, match="units mismatch"):
        roi_pairwise(cube, results, ["A", "B"])
    results = pixel_rois(cube)
    results[1]["metadata"]["source_provenance"]["source_file"] = "fixture-B.npy"
    with pytest.raises(ValueError, match="identity mismatch"):
        roi_pairwise(cube, results, ["A", "B"])
    with pytest.raises(ValueError, match="robust"):
        roi_pairwise(cube, pixel_rois(cube, robust=False), ["A", "B"], summary="median")


@pytest.mark.parametrize("operation,expected", [("smooth", .04), ("derivative1", .04), ("derivative2", .02)])
@pytest.mark.parametrize("reverse,units", [(False, "nm"), (True, "nm"), (False, "um"), (True, "um")])
def test_actual_irregular_coordinates_polynomial_and_unit_orientation(operation, expected, reverse, units):
    wavelengths = np.array([500., 501., 502., 510., 511.])
    signal = ((wavelengths-500)/10)**2
    if reverse:
        wavelengths, signal = wavelengths[::-1], signal[::-1]
    cube = spectrum(signal, wavelengths/(1000 if units == "um" else 1), units=units)
    before, meta = cube.data.tobytes(), deepcopy(cube.metadata)
    result = spectral_roi_features(cube, pixel_rois(cube, support="common"), operation)
    curve = result["curves"][0]
    assert curve["valid_mask"].tolist() == [False, False, True, False, False]
    assert curve["y"][2] == pytest.approx(expected, abs=1e-12)
    assert result["metadata"]["feature_indices"] == ([4, 3, 2, 1, 0] if reverse else list(range(5)))
    assert result["metadata"]["wavelength_units"] == "nm"
    assert "sd" not in curve and result["metadata"]["aggregation_order"] == "summary_then_transform"
    assert cube.data.tobytes() == before and cube.metadata == meta


@pytest.mark.parametrize("derivative,weights", [(0, np.array([-3, 12, 17, 12, -3])/35),
    (1, np.array([-2, -1, 0, 1, 2])/10), (2, np.array([2, -1, -2, -1, 2])/7)])
def test_uniform_interior_agrees_with_independent_five_point_polynomial_coefficients(derivative, weights):
    x = np.arange(11)*10+500
    y = np.array([1., 5, 2, 3, 7, -4, 9, 2, 1, 6, 4])
    expected = np.array([np.dot(weights, y[i-2:i+3])/10**derivative for i in range(2, 9)])
    result = local_polynomial(x, y, derivative=derivative)
    np.testing.assert_allclose(result["y"][2:-2], expected, atol=1e-12)
    assert not result["valid_mask"][:2].any() and not result["valid_mask"][-2:].any()


@pytest.mark.parametrize("options", [{"window": 4}, {"window": 1}, {"window": 7}, {"degree": 5},
                                      {"degree": -1}, {"derivative": 3}, {"window": True}])
def test_invalid_polynomial_parameters_rejected(options):
    with pytest.raises(ValueError, match="window"):
        local_polynomial(np.arange(5)+500, np.ones(5), **options)


def test_polynomial_missing_values_and_rank_deficiency_stay_unavailable():
    result = local_polynomial(np.arange(5)+500, [1, 2, np.nan, 4, 5])
    assert not result["valid_mask"].any() and result["invalid_reasons"][2] == "Incomplete finite window"
    eps = np.finfo(float).eps
    result = local_polynomial([1, 1+eps, 1+2*eps, 1+3*eps, 1e10], [1, 2, 3, 4, 5])
    assert not result["valid_mask"].any() and "Rank-deficient" in result["invalid_reasons"][2]


@pytest.mark.parametrize("reverse", [False, True])
def test_wavelength_integral_is_not_an_unweighted_band_mean(reverse):
    wave, signal = np.array([500, 510, 540]), np.array([.2, .3, .6])
    cube = spectrum(signal[::-1] if reverse else signal, wave[::-1] if reverse else wave, level="reflectance_cube")
    result = spectral_roi_features(cube, pixel_rois(cube, support="common"), "integral")
    feature = result["curves"][0]["features"]
    assert feature["integral"] == pytest.approx(16) and feature["interval_mean"] == pytest.approx(.4)
    assert feature["integral_units"] == "dimensionless*nm"
    assert feature["interval_mean"] != pytest.approx(np.mean(signal))


def test_spectral_interval_requires_exact_common_support_and_no_original_index_gap():
    cube = spectrum(np.arange(6)+1)
    selected = [0, 1, 3, 4, 5]
    with pytest.raises(ValueError, match="gaps"):
        spectral_roi_features(cube, pixel_rois(cube, bands=selected, support="common"), "smooth", bands=selected)
    with pytest.raises(ValueError, match="common spatial"):
        spectral_roi_features(cube, pixel_rois(cube), "integral")
    with pytest.raises(ValueError, match="exactly"):
        spectral_roi_features(cube, pixel_rois(cube, support="common"), "integral", bands=[1, 2, 3])
    cube.metadata["band_validity"] = [True, True, False, True, True, True]
    with pytest.raises(ValueError, match="globally invalid"):
        spectral_roi_features(cube, pixel_rois(cube, support="common"), "integral")
    subset = [3, 4, 5]
    allowed = spectral_roi_features(cube, pixel_rois(cube, support="common", bands=subset), "integral", bands=subset)
    assert allowed["curves"][0]["features"]["integral"] == pytest.approx(100)


def test_continuum_uses_actual_asymmetric_shoulders_and_retains_source_kind():
    cube = spectrum([.8, .736, 1.2], [500, 560, 700], level="reflectance_cube", reflectance_kind="relative")
    result = spectral_roi_features(cube, pixel_rois(cube, support="common"), "continuum")
    curve = result["curves"][0]
    assert curve["continuum"][1] == pytest.approx(.92) and curve["y"][1] == pytest.approx(.2)
    assert curve["features"]["depth_area_nm"] == pytest.approx(20)
    assert curve["features"]["sampled_minimum_nm"] == 560
    assert curve["features"]["sampled_minimum_index"] == 1
    assert curve["features"]["minimum_at_boundary"] is False
    assert result["metadata"]["reflectance_kind"] == "relative"


def test_continuum_is_feature_of_summary_and_does_not_clip_negative_depth():
    cube = spectrum([[1, 1, 1], [3, 9, 3]], [500, 600, 700], level="reflectance_cube")
    stats = [roi_statistics(cube, (0, 0, 2, 1), support="common")]
    result = spectral_roi_features(cube, stats, "continuum")
    curve = result["curves"][0]
    assert curve["continuum_ratio"][1] == 2.5 and curve["y"][1] == -1.5
    assert curve["y"][1] != np.mean([0, -2])
    assert curve["features"]["depth_area_nm"] == -150
    assert result["metadata"]["aggregation_order"] == "summary_then_transform"
    assert "sd" not in curve and "q25" not in curve
    flat = spectrum([.8, 1., 1.2], [500, 600, 700], level="reflectance_cube")
    result = spectral_roi_features(flat, pixel_rois(flat, support="common"), "continuum")
    np.testing.assert_allclose(result["curves"][0]["y"], 0, atol=1e-15)


def test_zero_continuum_unavailable_and_raw_dn_depth_gate():
    cube = spectrum([0, 1, 0], level="reflectance_cube")
    result = spectral_roi_features(cube, pixel_rois(cube, support="common"), "continuum")["curves"][0]
    assert not result["valid_mask"].any() and result["features"]["status"] == "unavailable"
    raw = spectrum([1, .5, 1])
    with pytest.raises(ValueError, match="reflectance"):
        spectral_roi_features(raw, pixel_rois(raw, support="common"), "continuum")


def test_unrepresentable_derived_values_are_unavailable_not_successful_infinities():
    cube = spectrum([1e-308, 1e308, 1e-308], level="reflectance_cube")
    result = spectral_roi_features(cube, pixel_rois(cube, support="common"), "continuum")["curves"][0]
    assert result["features"]["status"] == "unavailable"
    assert result["valid_mask"].tolist() == [True, False, True]
    assert np.isnan(result["y"][1]) and np.isnan(result["continuum_ratio"][1])
    huge = spectrum([1e308, 1e308, 1e308])
    result = spectral_roi_features(huge, pixel_rois(huge, support="common"), "integral")["curves"][0]
    assert result["features"]["status"] == "unavailable" and result["features"]["integral"] is None


@pytest.mark.parametrize("waves", [[500, 500, 600], [500, 700, 600], [-1, 500, 600]])
def test_invalid_physical_wavelength_axis_is_not_analyzed(waves):
    cube = spectrum([1, 2, 3], waves)
    with pytest.raises(ValueError, match="wavelength"):
        spectral_roi_features(cube, pixel_rois(cube, support="common"), "integral")


def test_color_and_state_inputs_do_not_gain_wavelength_operations():
    rgb = Cube(np.ones((1, 1, 3)), {"data_level": "raw_frame", "channel_labels": ["R", "G", "B"]})
    state = Cube(np.ones((1, 1, 5)))
    for cube in (rgb, state):
        with pytest.raises(ValueError, match="wavelength"):
            spectral_roi_features(cube, pixel_rois(cube, support="common"), "integral")


def test_median_branch_uses_robust_summary_not_mean():
    cube = spectrum([[1, 2, 3], [2, 4, 6], [100, 300, 900]])
    stats = [roi_statistics(cube, (0, 0, 3, 1), support="common")]
    result = spectral_roi_features(cube, stats, "integral", summary="median")
    np.testing.assert_array_equal(result["curves"][0]["y"], [2, 4, 6])
    assert result["metadata"]["summary"] == "median"
    assert result["curves"][0]["features"]["integral"] == 80
