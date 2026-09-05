import json

import numpy as np
import pytest

from hyperlab.io import Cube, load_cube, save_cube


def test_envi_independent_reader_sees_quality_units_and_precise_values(tmp_path):
    from spectral.io import envi
    data = np.arange(24, dtype=np.uint32).reshape(2, 4, 3) + 2**24
    valid = np.ones(data.shape, bool)
    valid[0, 0, 0] = False
    cube = Cube(data, {"wavelengths": [500, 600, 700], "wavelength_units": "Nanometers",
        "wavelength_source": "synthetic", "units": "DN", "band_validity": [True, False, True],
        "fwhm": [10, 11, 12], "data_ignore_value": 0}, valid)
    path = tmp_path / "external.hdr"
    save_cube(cube, path)
    reader = envi.open(str(path))
    # open_memmap preserves uint32/float64 precision; SPy's load() converts to float32.
    actual = reader.open_memmap()
    assert reader.metadata["bbl"] == [1, 0, 1]
    assert reader.metadata["data units"] == "DN"
    assert reader.metadata["wavelength units"] == "nm"
    assert reader.bands.bandwidths == [10, 11, 12]
    np.testing.assert_array_equal(actual[valid], data[valid])
    assert np.isnan(actual[0, 0, 0])
    assert reader.metadata["data ignore value"].lower() == "nan"
    assert cube.data[0, 0, 0] == 2**24  # Source untouched.
    actual._mmap.close()


def test_envi_sidecar_unit_equivalence_and_conflict(tmp_path):
    cube = Cube(np.ones((2, 2, 2)), {"wavelengths": [500, 600], "wavelength_units": "nm"})
    path = tmp_path / "units.hdr"
    save_cube(cube, path)
    sidecar = path.with_suffix(".hdr.json")
    meta = json.loads(sidecar.read_text())
    meta.update(wavelengths=[.5, .6], wavelength_units="micrometers")
    sidecar.write_text(json.dumps(meta))
    with load_cube(path) as loaded:
        assert loaded.wavelengths.tolist() == [500, 600]
        assert loaded.metadata["wavelength_units"] == "nm"
        assert loaded.metadata["envi_sidecar_wavelength_units_original"] == "micrometers"
    meta["wavelengths"] = [500, 600]
    sidecar.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="units|wavelength"):
        load_cube(path)


def test_envi_exports_ignore_without_pixel_mask(tmp_path):
    cube = Cube(np.ones((2, 2, 2), np.int16), {"data_ignore_value": -9999, "units": "radiance"})
    path = tmp_path / "ignore.hdr"
    save_cube(cube, path)
    text = path.read_text()
    assert "data ignore value = -9999" in text
    assert "data units = radiance" in text


def test_time_axis_is_not_spectral_and_khw_prefix_remains_mapped(tmp_path):
    path = tmp_path / "sequence.npy"
    np.save(path, np.arange(24).reshape(4, 2, 3))
    path.with_suffix(".npy.json").write_text(json.dumps({"data_level": "raw_sequence", "axis_order": "THW"}))
    with pytest.raises(ValueError, match="time sequence"):
        load_cube(path)
    path.with_suffix(".npy.json").write_text(json.dumps({"data_level": "raw_scan", "axis_order": "KHW",
        "frame_count": 2, "band_validity": [True] * 4, "scan_states": [0, 1, 2, 3]}))
    with load_cube(path) as cube:
        assert cube.shape == (2, 3, 2) and isinstance(cube.data, np.memmap)
        assert cube.metadata["scan_states"] == [0, 1]
