import json

import numpy as np
import pytest

from hyperlab.io import Cube, load_cube, make_synthetic_cube, save_cube


@pytest.mark.parametrize("suffix", [".npy", ".npz", ".hdr"])
def test_round_trip_preserves_truth_and_mask(tmp_path, suffix):
    original = make_synthetic_cube()
    path = tmp_path / ("synthetic" + suffix)
    save_cube(original, path)
    loaded = load_cube(path)
    np.testing.assert_array_equal(loaded.data, original.data)
    np.testing.assert_array_equal(loaded.valid_mask, original.valid_mask)
    assert loaded.metadata["synthetic"] is True
    assert loaded.metadata["data_source"] == "SYNTHETIC"
    np.testing.assert_array_equal(loaded.wavelengths, original.wavelengths)
    assert loaded.metadata["units"] == "DN"
    with pytest.raises(FileExistsError):
        save_cube(original, path)


@pytest.mark.parametrize("interleave", ["bsq", "bil", "bip"])
@pytest.mark.parametrize("byte_order", [0, 1])
def test_envi_interleaves_offsets_and_endian(tmp_path, interleave, byte_order):
    # Build fixtures independently of the writer, with distinguishable H/W/K.
    original = np.arange(2 * 3 * 4, dtype=np.uint16).reshape(2, 3, 4)
    axes = {"bsq": (2, 0, 1), "bil": (0, 2, 1), "bip": (0, 1, 2)}[interleave]
    binary = tmp_path / "fixture.dat"
    dtype = np.dtype(">u2" if byte_order else "<u2")
    binary.write_bytes(b"1234567" + original.transpose(axes).astype(dtype).tobytes())
    header = tmp_path / "fixture.hdr"
    header.write_text(f"ENVI\nsamples = 3\nlines = 2\nbands = 4\nheader offset = 7\n"
                      f"data type = 12\ninterleave = {interleave}\nbyte order = {byte_order}\n"
                      "wavelength = {410,\n 520, 630, 740}\nwavelength units = Nanometers\n")
    result = load_cube(header)
    np.testing.assert_array_equal(result.data, original)
    assert isinstance(result.data, np.memmap)
    assert result.metadata["wavelength_units"] == "Nanometers"


def test_missing_wavelength_is_not_invented(tmp_path):
    cube = Cube(np.zeros((2, 3, 4), dtype=np.uint16), {"data_level": "raw_scan"})
    save_cube(cube, tmp_path / "states.hdr")
    loaded = load_cube(tmp_path / "states.hdr")
    assert loaded.wavelengths is None
    assert loaded.metadata["axis_names"] == ["y", "x", "state"]


def test_explicit_axis_mapping_and_npz_dataset(tmp_path):
    data = np.arange(24).reshape(4, 2, 3)
    path = tmp_path / "external.npy"
    np.save(path, data)
    with pytest.raises(ValueError, match="Axis order is unknown"):
        load_cube(path)
    np.testing.assert_array_equal(load_cube(path, axis_order="KHW").data, data.transpose(1, 2, 0))
    archive = tmp_path / "ambiguous.npz"
    np.savez(archive, a=data, b=data + 1)
    with pytest.raises(ValueError, match="dataset"):
        load_cube(archive, axis_order="KHW")
    np.testing.assert_array_equal(load_cube(archive, axis_order="KHW", dataset="b").data,
                                  (data + 1).transpose(1, 2, 0))


def test_partial_scan_hides_unacquired_preallocated_frames(tmp_path):
    path = tmp_path / "cube.npy"
    np.save(path, np.arange(24).reshape(2, 3, 4))
    sidecar = tmp_path / "cube.npy.json"
    meta = {"axis_order": "HWK", "frame_count": 2, "completed": False,
            "partial": True, "data_level": "raw_scan", "data_source": "LIVE"}
    sidecar.write_text(json.dumps(meta))
    cube = load_cube(path)
    assert cube.shape == (2, 3, 2)
    assert cube.metadata["partial"] is True
    assert cube.wavelengths is None
    meta["frame_count"] = 0
    sidecar.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="No acquired frames"):
        load_cube(path)


def test_raw_frame_hw_and_bad_wave(tmp_path):
    path = tmp_path / "frame.npy"
    np.save(path, np.ones((2, 3), dtype=np.uint16))
    assert load_cube(path, axis_order="HW").shape == (2, 3, 1)
    with pytest.raises(ValueError, match="Wavelength"):
        Cube(np.zeros((2, 3, 4)), {"wavelengths": [400, 500]})


def test_envi_truncation_rejected(tmp_path):
    cube = Cube(np.arange(24, dtype=np.uint16).reshape(2, 3, 4))
    path = tmp_path / "test.hdr"
    save_cube(cube, path)
    path.with_suffix(".dat").write_bytes(b"short")
    with pytest.raises(ValueError, match="Truncated"):
        load_cube(path)
