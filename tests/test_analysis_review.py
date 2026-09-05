import json

import numpy as np
import pytest

from hyperlab.analysis import difference, pca, reflectance, roi_statistics, spectral_angle
from hyperlab.io import Cube


def spectral(values):
    data = np.asarray(values, dtype=np.uint16).reshape(1, 2, 2)
    return Cube(data, {"data_level": "spectral_cube", "wavelengths": [500, 600],
        "wavelength_units": "nm", "wavelength_source": "synthetic test", "units": "DN",
        "linear_intensity": True, "settings": {"fixture": True}, "exposure": 10,
        "gain": 0, "processing_steps": [], "completed": True, "partial": False,
        "effective_bits": 12, "data_ignore_value": 0, "pixel_format": "Mono12",
        "envi_header": {"data ignore value": "0"}})


def test_global_bad_band_uses_common_feature_mapping():
    data = np.arange(24, dtype=float).reshape(2, 4, 3) + 1
    data[:, :, 1] = np.nan
    mask = np.ones(data.shape, bool)
    mask[0, 0, 0] = False
    cube = Cube(data, {"band_validity": [True, False, True]}, mask)
    result = pca(cube, n_components=2, max_samples=8)
    assert result["valid_mask"].sum() == 7
    assert result["components"].shape == (2, 2)
    assert result["metadata"]["feature_indices"] == [0, 2]
    angle = spectral_angle(cube, [1, np.nan, 3])
    assert angle["valid_mask"].sum() == 7
    assert angle["metadata"]["feature_indices"] == [0, 2]
    with pytest.raises(ValueError, match="selected|finite"):
        spectral_angle(cube, [np.nan, 1, 3])


def test_all_bad_and_insufficient_features_rejected():
    cube = Cube(np.ones((2, 2, 3)), {"band_validity": [False] * 3})
    with pytest.raises(ValueError, match="feature|band"):
        pca(cube, n_components=1)
    with pytest.raises(ValueError, match="feature|band"):
        spectral_angle(cube, [1, 1, 1])
    with pytest.raises(ValueError, match="two|dimension|channel"):
        spectral_angle(Cube(np.ones((2, 2, 1))), [1])
    with pytest.raises(ValueError, match="Too few"):
        pca(Cube(np.ones((1, 1, 2))), n_components=1)


def test_reflectance_zero_is_not_raw_ignore_and_sources_survive():
    sample, white, ds, dw = [spectral([v] * 4) for v in [10, 100, 10, 10]]
    corrected = reflectance(sample, white, ds, dw)
    stats = roi_statistics(corrected, (0, 0, 2, 1))
    assert stats["count"].tolist() == [2, 2]
    assert stats["mean"].tolist() == [0, 0]
    assert "data_ignore_value" not in corrected.metadata
    assert "envi_header" not in corrected.metadata
    assert corrected.metadata["pixel_format"] == "unknown"
    assert corrected.metadata["source_provenance"]["sample"]["data_ignore_value"] == 0


@pytest.mark.parametrize("dtype,first,second", [(np.uint32, 2**24 + 1, 2**24),
                                                (np.float64, 1 + 1e-10, 1)])
def test_difference_preserves_high_precision(dtype, first, second):
    cube = Cube(np.array([[[first, second]]], dtype=dtype))
    result = difference(cube, 0, 1)
    assert result["data"][0, 0] == pytest.approx(float(first) - float(second), rel=1e-12, abs=0)


def test_quality_policy_counts_saturation_without_discarding_raw():
    cube = Cube(np.array([[[10], [4095], [0], [30], [np.nan]]]),
                {"effective_bits": 12, "data_ignore_value": 0},
                np.array([[True, True, True, False, True]]))
    diagnostic = roi_statistics(cube, (0, 0, 5, 1), policy="diagnostic")
    quantitative = roi_statistics(cube, (0, 0, 5, 1), policy="quantitative")
    assert diagnostic["count"].tolist() == [2]
    assert quantitative["count"].tolist() == [1]
    assert quantitative["counts"]["total"].tolist() == [5]
    assert quantitative["counts"]["saturated"].tolist() == [1]
    assert quantitative["counts"]["ignored"].tolist() == [1]
    assert quantitative["counts"]["invalid"].tolist() == [2]


def test_reflectance_requires_target_over_budget_and_reopens(tmp_path):
    args = [spectral([v] * 4) for v in [10, 100, 10, 10]]
    with pytest.raises(ValueError, match="output_path"):
        reflectance(*args, memory_threshold_bytes=1)
    path = tmp_path / "reflectance.npy"
    with reflectance(*args, output_path=path, memory_threshold_bytes=1, chunk_pixels=1) as result:
        assert isinstance(result.data, np.memmap)
        assert isinstance(result.valid_mask, np.memmap)
        assert result.metadata["completed"] is True
    receipt = json.loads(path.with_suffix(".npy.json").read_text())
    assert receipt["completed"] is True and receipt["completed_pixels"] == 2
    from hyperlab.io import load_cube
    with load_cube(path) as reopened:
        np.testing.assert_array_equal(reopened.data, 0)
        assert reopened.valid_mask.all()


def test_out_of_core_failure_keeps_durable_prefix_and_closed_files(tmp_path, monkeypatch):
    import hyperlab.analysis.core as core
    blocks = core._blocks

    def fail_after_first(*args, **kwargs):
        yield next(blocks(*args, **kwargs))
        raise RuntimeError("injected computation failure")

    monkeypatch.setattr(core, "_blocks", fail_after_first)
    path = tmp_path / "partial.npy"
    args = [spectral([v] * 4) for v in [10, 100, 10, 10]]
    with pytest.raises(RuntimeError, match="injected"):
        reflectance(*args, output_path=path, chunk_pixels=1)
    from hyperlab.io import load_cube
    with load_cube(path) as partial:
        assert partial.metadata["completed_pixels"] == 1 and partial.metadata["partial"]
        assert partial.valid_mask[0, 0].all() and not partial.valid_mask[0, 1].any()
        assert roi_statistics(partial, (0, 0, 2, 1))["count"].tolist() == [1, 1]
    # Windows refuses replacement if a leaked mmap still owns the target.
    path.rename(tmp_path / "partial-released.npy")


def test_large_integer_range_is_not_silently_rounded():
    cube = Cube(np.array([[[2**63 + 1, 2**63]]], np.uint64))
    with pytest.raises(ValueError, match="exact float64"):
        difference(cube, 0, 1)


def test_shared_quantitative_policy_excludes_saturated_vectors():
    cube = Cube(np.array([[[10, 20], [4095, 30]], [[20, 40], [30, 60]]], np.uint16),
                {"effective_bits": 12})
    assert pca(cube, 1, policy="diagnostic")["valid_mask"].sum() == 4
    assert pca(cube, 1, policy="quantitative")["valid_mask"].sum() == 3
    assert spectral_angle(cube, [10, 20], policy="quantitative")["valid_mask"].sum() == 3
