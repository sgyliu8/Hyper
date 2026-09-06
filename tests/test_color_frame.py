import json
import numpy as np
import pytest
from hyperlab.io import Cube, load_cube, save_cube
from hyperlab.analysis import capabilities, roi_statistics


def test_camera_rgb_remains_color_not_wavelength(tmp_path):
    path = tmp_path / "frame.npy"
    data = np.arange(36, dtype=np.uint8).reshape(3, 4, 3)
    np.save(path, data)
    path.with_suffix(".npy.json").write_text(json.dumps({
        "axis_order": "HWC", "data_source": "SYNTHETIC", "data_level": "raw_frame",
        "channel_labels": ["R", "G", "B"], "wavelengths": None}))
    frame = load_cube(path)
    np.testing.assert_array_equal(frame.data, data)
    assert frame.metadata["axis_names"][-1] == "color_channel"
    assert frame.metadata["data_level"] == "raw_frame" and frame.wavelengths is None
    assert roi_statistics(frame, (0, 0, 2, 2))["axis_label"] == "color_channel_index"


def test_rgb_cannot_be_relabelled_spectral(tmp_path):
    path = tmp_path / "bad.npy"
    np.save(path, np.zeros((2, 3, 3), np.uint8))
    path.with_suffix(".npy.json").write_text(json.dumps({
        "axis_order": "HWC", "wavelengths": [450, 550, 650]}))
    with pytest.raises(ValueError, match="cannot carry"):
        load_cube(path)


@pytest.mark.parametrize("suffix", [".npy", ".npz", ".hdr"])
def test_derived_color_preserves_level_channels_and_capabilities(tmp_path, suffix):
    cube = Cube(np.ones((2, 3, 3)), {"data_level": "derived_frame", "channel_labels": ["B", "G", "R"],
                "units": "DN", "processing_steps": [{"operation": "temporal mean"}]})
    path = save_cube(cube, tmp_path / ("mean" + suffix))
    with load_cube(path) as loaded:
        assert loaded.metadata["data_level"] == "derived_frame"
        assert loaded.metadata["channel_labels"] == ["B", "G", "R"]
        assert loaded.wavelengths is None
        caps = capabilities(loaded)
        assert caps["operations"]["roi"] and not caps["operations"]["pca"]
        assert not caps["operations"]["spectral_angle"]


def test_explicit_hwc_derived_sidecar_is_not_downgraded_to_raw(tmp_path):
    path = tmp_path / "mean.npy"
    np.save(path, np.ones((2, 3, 3)))
    path.with_suffix(".npy.json").write_text(json.dumps({"data_level": "derived_frame", "axis_order": "HWC",
        "channel_labels": ["R", "G", "B"], "processing_steps": [{"operation": "temporal mean"}]}))
    with load_cube(path) as loaded:
        assert loaded.metadata["data_level"] == "derived_frame"


def test_derived_sensor_plane_has_no_state_axis():
    cube = Cube(np.ones((2, 3, 1)), {"data_level": "derived_frame"})
    assert cube.metadata["axis_names"] == ["y", "x", "sensor_plane"]
