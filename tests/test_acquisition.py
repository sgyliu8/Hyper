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
