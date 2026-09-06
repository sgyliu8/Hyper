import json
import threading
import numpy as np
import pytest
from hyperlab.acquisition import ScanWriter, synthetic_scan


def test_stop_is_partial_and_preserves_order(tmp_path):
    stop = threading.Event()
    path = synthetic_scan(tmp_path / "stopped", stop=stop,
                          progress=lambda done, total: stop.set() if done == 3 else None)
    meta = json.loads(path.with_suffix(".npy.json").read_text())
    assert meta["frame_count"] == 3 and meta["expected_frames"] == 12
    assert meta["partial"] and not meta["completed"]
    assert [r["frame_id"] for r in meta["frames"]] == [0, 1, 2]
    assert meta["wavelengths"] is None and meta["data_source"] == "SYNTHETIC"


def test_disconnect_preserves_prefix(tmp_path):
    with pytest.raises(ConnectionError):
        synthetic_scan(tmp_path / "disconnect", disconnect_at=2)
    meta = json.loads((tmp_path / "disconnect/cube.npy.json").read_text())
    assert meta["frame_count"] == 2 and meta["partial"] and meta["error"]


def test_scan_completion_and_no_overwrite(tmp_path):
    path = synthetic_scan(tmp_path / "done", frames=3)
    meta = json.loads(path.with_suffix(".npy.json").read_text())
    assert meta["completed"] and not meta["partial"]
    with pytest.raises(FileExistsError):
        synthetic_scan(tmp_path / "done")


def test_reject_dtype_change_and_invalid_frame(tmp_path):
    writer = ScanWriter(tmp_path / "raw", (2, 3, 4), np.uint16, source="SYNTHETIC")
    with pytest.raises(ValueError, match="dtype"):
        writer.append(np.ones((2, 3), np.uint8), {"valid": True})
    with pytest.raises(ValueError, match="valid"):
        writer.append(np.ones((2, 3), np.uint16), {"valid": False})
    writer.finish(error="fixture")
    assert writer.meta["frame_count"] == 0


def test_scan_frames_contiguous_close_and_reopen_contents(tmp_path):
    from hyperlab.io import load_cube
    with ScanWriter(tmp_path / "layout", (2, 3, 4), np.uint16, source="SYNTHETIC") as writer:
        for index in range(4):
            writer.append(np.full((2, 3), index, np.uint16), {"valid": True, "returned_state": index})
        assert writer.array.shape == (4, 2, 3)
        assert writer.array[0].flags.c_contiguous
    assert writer.meta["axis_order"] == "KHW"
    assert writer.meta["save_reopen_verified"]
    cube = load_cube(writer.path)
    assert cube.data.shape == (2, 3, 4)
    assert list(cube.data[0, 0]) == [0, 1, 2, 3]
    cube.close()
    writer.path.rename(writer.path.with_name("closed.npy"))


def test_scan_reopen_failure_is_partial_and_releases_mapping(tmp_path, monkeypatch):
    writer = ScanWriter(tmp_path / "failed-close", (2, 3, 1), np.uint16, source="SYNTHETIC")
    writer.append(np.ones((2, 3), np.uint16), {"valid": True})
    monkeypatch.setattr("hyperlab.acquisition.session.np.load",
                        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("reopen failed")))
    with pytest.raises(OSError, match="reopen failed"):
        writer.finish()
    metadata = json.loads(writer.path.with_suffix(".npy.json").read_text())
    assert metadata["partial"] and not metadata["completed"]
    assert metadata["frame_count"] == 0 and metadata["acquired_frames"] == 1
    assert writer.array._mmap.closed


def test_synthetic_disconnect_primary_survives_finish_failure(tmp_path, monkeypatch):
    original = ScanWriter.finish
    def fail_finish(self, **kwargs):
        original(self, **kwargs)
        raise OSError("finish secondary")
    monkeypatch.setattr(ScanWriter, "finish", fail_finish)
    with pytest.raises(ConnectionError, match="disconnect") as failure:
        synthetic_scan(tmp_path / "primary", disconnect_at=1)
    assert any("finish secondary" in note for note in failure.value.__notes__)
