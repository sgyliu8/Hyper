import json
import threading
import time
import numpy as np
import pytest
from hyperlab.acquisition.frame import Frame, save_frame
from hyperlab.acquisition.sequence import SequenceWriter, SequenceRecorder, load_sequence


def frame(index, color=False):
    values = np.full((3, 4, 3) if color else (3, 4), index, dtype=np.uint16)
    return Frame(values, {"session_id": "fixture", "sequence": index, "frame_id": index,
                          "host_monotonic_ns": time.monotonic_ns(), "host_utc": "fixture",
                          "pixel_format": "BayerRG12", "valid": True,
                          "readback_settings": {"ExposureTime": 50000}, "data_source": "SYNTHETIC",
                          "acquisition_source": "SYNTHETIC", "axis_order": "HW", "wavelengths": None})


def test_frame_pixels_and_nested_evidence_frozen():
    owned = frame(4)
    with pytest.raises(ValueError):
        owned.data[0, 0] = 0
    with pytest.raises(TypeError):
        owned.metadata["readback_settings"]["ExposureTime"] = 999
    source = {"session_id": "fixture", "sequence": 1, "records": [{"exposure": 20}]}
    captured = Frame(np.zeros((2, 2), np.uint16), source)
    source["records"][0]["exposure"] = 500
    assert captured.metadata["records"][0]["exposure"] == 20
    with pytest.raises(TypeError):
        captured.metadata["records"][0]["exposure"] = 999


@pytest.mark.parametrize("color", [False, True])
def test_sequence_time_axes_reopen_contents_and_release(tmp_path, color):
    first = frame(0, color)
    with SequenceWriter(tmp_path / "record", first.data.shape, first.data.dtype, 3,
                        metadata=dict(first.metadata), checkpoint_frames=2) as writer:
        for index in range(3):
            current = frame(index, color)
            writer.append(current.data, dict(current.metadata))
    assert writer.closed
    assert writer.meta["save_reopen_verified"]
    assert writer.meta["axis_order"] == ("THWC" if color else "THW")
    with load_sequence(writer.path) as sequence:
        assert sequence.frame_count == 3
        assert sequence.metadata["data_level"] == "raw_sequence"
        assert sequence.metadata["wavelengths"] is None
        assert np.array_equal(sequence.data[-1], frame(2, color).data)
        retained = sequence.frame(1)
        assert retained.metadata["display_mode"] == "REPLAY"
    assert np.all(retained.data == 1)
    writer.path.rename(writer.path.with_name("moved.npy"))  # no leaked Windows mmap handle


def test_checkpoint_publishes_only_durable_prefix(tmp_path):
    current = frame(1)
    writer = SequenceWriter(tmp_path / "partial", current.data.shape, current.data.dtype, 9, checkpoint_frames=2)
    writer.append(current.data, dict(current.metadata))
    receipt_path = writer.path.with_suffix(".npy.json")
    assert json.loads(receipt_path.read_text())["frame_count"] == 0
    writer.append(current.data, dict(current.metadata))
    assert json.loads(receipt_path.read_text())["frame_count"] == 2
    writer.append(current.data, dict(current.metadata))
    writer.finish(error="disconnect")
    with load_sequence(writer.path) as sequence:
        assert sequence.frame_count == 3
        assert sequence.metadata["partial"] and sequence.metadata["error"] == "disconnect"


def test_bounded_queue_overflow_retains_order_and_partial(tmp_path):
    allow_write = threading.Event()
    writer_entered = threading.Event()
    class SlowWriter(SequenceWriter):
        def append(self, data, record):
            writer_entered.set()
            assert allow_write.wait(5)
            super().append(data, record)
    recorder = SequenceRecorder(tmp_path / "overflow", frame(0), 10, capacity=1, writer_factory=SlowWriter)
    assert recorder.submit(frame(1))
    assert writer_entered.wait(5)
    assert recorder.submit(frame(2))
    assert not recorder.submit(frame(3))
    assert recorder.overflow == 1 and "overflow" in recorder.error
    allow_write.set()
    assert recorder.done.wait(5)
    assert recorder.status()["partial"] and not recorder.status()["completed"]
    assert recorder.status()["save_reopen_verified"]
    with load_sequence(recorder.path) as sequence:
        assert sequence.metadata["partial"]
        assert sequence.metadata["failed_frame"]["sequence"] == 3
        assert sequence.frame_count == 2
        assert list(sequence.data[:, 0, 0]) == [1, 2]


def test_disk_failure_retains_original_error_and_committed_prefix(tmp_path):
    class FailingWriter(SequenceWriter):
        def append(self, data, record):
            if self.count == 1:
                raise OSError("disk fixture full")
            super().append(data, record)
    recorder = SequenceRecorder(tmp_path / "disk", frame(0), 3, writer_factory=FailingWriter)
    for index in range(3):
        recorder.submit(frame(index))
    assert recorder.done.wait(5)
    with load_sequence(recorder.path) as sequence:
        assert sequence.frame_count == 1 and sequence.metadata["partial"]
        assert "disk fixture full" in sequence.metadata["error"]


def test_record_duration_and_exact_snapshot(tmp_path):
    recorder = SequenceRecorder(tmp_path / "duration", frame(0), 20, duration_s=0.04)
    recorder.submit(frame(5))
    assert recorder.done.wait(5)
    with load_sequence(recorder.path) as sequence:
        assert sequence.metadata["completed"]
        displayed = sequence.frame(0)
    saved = save_frame(tmp_path / "snapshot", displayed)
    assert np.array_equal(np.load(saved), displayed.data)
    metadata = json.loads(saved.with_suffix(".npy.json").read_text())
    assert metadata["sequence"] == 5 and metadata["save_reopen_verified"]


def test_sequence_rejects_bad_dtype_and_overwrite(tmp_path):
    current = frame(1)
    with SequenceWriter(tmp_path / "raw", current.data.shape, current.data.dtype, 2) as writer:
        with pytest.raises(ValueError, match="dtype"):
            writer.append(current.data.astype(np.uint8), dict(current.metadata))
    with pytest.raises(FileExistsError):
        SequenceWriter(tmp_path / "raw", current.data.shape, current.data.dtype, 2)


@pytest.mark.parametrize("change", [
    {"dtype": "<f4"}, {"shape": [2, 99, 4]}, {"frame_count": "2"},
    {"frames": []}, {"expected_frames": 90}, {"axis_order": "THWC"},
])
def test_sequence_rejects_inconsistent_manifest_without_mapping_leak(tmp_path, change):
    current = frame(1)
    with SequenceWriter(tmp_path / "invalid", current.data.shape, current.data.dtype, 2) as writer:
        writer.append(current.data, dict(current.metadata))
    metadata = dict(writer.meta, **change)
    writer.path.with_suffix(".npy.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        load_sequence(writer.path)
    writer.path.rename(writer.path.with_name("closed-after-invalid.npy"))


def test_initial_checkpoint_failure_releases_mapping(tmp_path, monkeypatch):
    mappings = []
    original = np.lib.format.open_memmap
    def mapping(*args, **kwargs):
        value = original(*args, **kwargs)
        mappings.append(value)
        return value
    monkeypatch.setattr(np.lib.format, "open_memmap", mapping)
    monkeypatch.setattr("hyperlab.acquisition.sequence.atomic_json",
                        lambda *args: (_ for _ in ()).throw(OSError("initial checkpoint failed")))
    with pytest.raises(OSError, match="checkpoint"):
        SequenceWriter(tmp_path / "initial-fail", (3, 4), np.uint16, 2)
    assert mappings[0]._mmap.closed


def test_budget_rejects_before_directory_or_writer_thread(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("hyperlab.acquisition.sequence.shutil.disk_usage",
                        lambda path: SimpleNamespace(free=10))
    with pytest.raises(OSError, match="space"):
        SequenceRecorder(tmp_path / "no-space", frame(0), 4)
    assert not (tmp_path / "no-space").exists()


def test_finished_writer_rate_is_stable(tmp_path):
    recorder = SequenceRecorder(tmp_path / "rate", frame(0), 1)
    assert not recorder.status()["done"]
    assert not recorder.status()["completed"] and not recorder.status()["save_reopen_verified"]
    recorder.submit(frame(0))
    assert recorder.done.wait(5)
    assert recorder.status()["completed"] and not recorder.status()["partial"]
    assert recorder.status()["save_reopen_verified"]
    rate = recorder.status()["writer_fps"]
    time.sleep(0.02)
    assert recorder.status()["writer_fps"] == rate


@pytest.mark.parametrize("source", ["SYNTHETIC", "REPLAY", None])
def test_recording_missing_acquisition_source_never_becomes_live(tmp_path, source):
    original = frame(1)
    metadata = dict(original.metadata)
    metadata.pop("acquisition_source")
    if source is None:
        metadata.pop("data_source")
    else:
        metadata["data_source"] = source
    supplied = Frame(original.data, metadata)
    recorder = SequenceRecorder(tmp_path / "source", supplied, 1)
    recorder.submit(supplied)
    assert recorder.done.wait(5)
    with load_sequence(recorder.path) as sequence:
        assert sequence.metadata["acquisition_source"] == (source or "UNKNOWN")
        assert sequence.metadata["acquisition_source"] != "LIVE"


def test_new_sequence_does_not_inherit_source_reopen_success(tmp_path):
    with SequenceWriter(tmp_path / "new", (2, 3), np.uint16, 2,
                        metadata={"save_reopen_verified": True}) as writer:
        assert not writer.meta["save_reopen_verified"]
