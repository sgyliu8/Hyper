import json
import numpy as np
import pytest
from hyperlab.io import load_cube
from hyperlab.analysis import roi_statistics


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
