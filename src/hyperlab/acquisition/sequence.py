"""Frame-contiguous, bounded raw time recording with a durable valid prefix."""
from collections import OrderedDict
import json
import os
from pathlib import Path
import queue
import shutil
import threading
import time
import numpy as np
from .session import utc_now


def atomic_json(path, metadata):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(metadata, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class SequenceWriter:
    """Store THW/THWC frames; metadata completion advances after data flush."""

    def __init__(self, directory, frame_shape, dtype, max_frames, *, metadata=None, checkpoint_frames=8):
        if len(frame_shape) not in (2, 3) or min(frame_shape) <= 0 or max_frames <= 0:
            raise ValueError("Positive frame shape and finite frame count required")
        if checkpoint_frames < 1:
            raise ValueError("Positive checkpoint frame count required")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.path = self.directory / "sequence.npy"
        self.array = np.lib.format.open_memmap(self.path, mode="w+", dtype=dtype,
                                               shape=(int(max_frames), *frame_shape))
        self.meta = dict(metadata or {})
        self.meta.update(schema_version=2, data_level="raw_sequence", axis_kind="time",
                         axis_order="THWC" if len(frame_shape) == 3 else "THW",
                         axis_names=["time", "y", "x"] + (["color_channel"] if len(frame_shape) == 3 else []),
                         shape=list(self.array.shape), dtype=self.array.dtype.str, units="DN", wavelengths=None,
                         expected_frames=int(max_frames), frame_count=0, frames=[], completed=False,
                         partial=True, status="partial", save_reopen_verified=False,
                         started_at=utc_now(), time_units="s",
                         time_origin="first acquired frame host_monotonic_ns; device clock is separate",
                         calibration_source=None, processing_steps=[])
        self.count = 0
        self.checkpoint_frames = checkpoint_frames
        self.closed = False
        self._samples = OrderedDict()
        try:
            atomic_json(self.path.with_suffix(".npy.json"), self.meta)
        except Exception:
            self.array._mmap.close()
            self.closed = True
            raise

    def append(self, frame, record):
        if self.closed:
            raise RuntimeError("Writer already closed")
        if self.count >= self.array.shape[0]:
            raise ValueError("More frames than declared")
        if frame.shape != self.array.shape[1:] or frame.dtype != self.array.dtype:
            raise ValueError("Frame shape/dtype changed; refusing conversion")
        if record.get("valid") is not True:
            raise ValueError("Only valid acquired frames can enter the prefix")
        json.dumps(record, allow_nan=False)
        index = self.count
        self.array[index] = frame
        self.meta["frames"].append(dict(record, index=index))
        self.count += 1
        # Keep only first/middle/latest samples, not another copy of the recording.
        if index in (0, self.array.shape[0] // 2):
            self._samples[index] = np.array(frame, copy=True)
        if -1 in self._samples:
            del self._samples[-1]
        self._samples[-1] = np.array(frame, copy=True)
        if self.count % self.checkpoint_frames == 0:
            self.checkpoint()

    def checkpoint(self):
        if self.closed:
            return
        self.array.flush()
        # fsync the file as well as the mapped pages before publishing completion.
        with self.path.open("r+b") as stream:
            os.fsync(stream.fileno())
        self.meta["frame_count"] = self.count
        atomic_json(self.path.with_suffix(".npy.json"), self.meta)

    def finish(self, *, error=None, stopped=False, duration_complete=False):
        if self.closed:
            return self.path
        primary = None
        try:
            self.checkpoint()
            check = np.load(self.path, mmap_mode="r", allow_pickle=False)
            try:
                verified = []
                for index, samples in self._samples.items():
                    index = self.count - 1 if index == -1 else index
                    if not np.array_equal(check[index], samples, equal_nan=True):
                        raise RuntimeError(f"Sequence reopen content mismatch at frame {index}")
                    verified.append(index)
                self.meta["reopen_verified_indices"] = sorted(set(verified))
            finally:
                check._mmap.close()
            complete = (self.count == self.meta["expected_frames"] or duration_complete) and self.count > 0 and not error and not stopped
            self.meta.update(completed=bool(complete), partial=not complete,
                             status="completed" if complete else "partial", error=error,
                             stopped=bool(stopped), ended_at=utc_now(), save_reopen_verified=True)
            atomic_json(self.path.with_suffix(".npy.json"), self.meta)
        except Exception as exc:
            primary = exc
            self.meta.update(completed=False, partial=True, error=error or str(exc),
                             finalization_error=str(exc), ended_at=utc_now())
            try:
                atomic_json(self.path.with_suffix(".npy.json"), self.meta)
            except Exception as receipt_error:
                exc.add_note(f"Final receipt also failed: {receipt_error}")
        finally:
            try:
                self.array._mmap.close()
            except Exception as close_error:
                if primary is None:
                    primary = close_error
                else:
                    primary.add_note(f"Mapping close also failed: {close_error}")
            self.closed = True
            self._samples.clear()
        if primary is not None:
            raise primary
        return self.path

    close = finish

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        try:
            self.finish(error=str(error) if error else None)
        except Exception as cleanup_error:
            if error is None:
                raise
            error.add_note(f"Sequence finalization also failed: {cleanup_error}")


class Sequence:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_dir():
            self.path /= "sequence.npy"
        self.metadata = json.loads(self.path.with_suffix(".npy.json").read_text(encoding="utf-8"))
        if self.metadata.get("data_level") != "raw_sequence" or self.metadata.get("axis_order") not in ("THW", "THWC"):
            raise ValueError("Expected a raw time sequence, not a spectral cube")
        count = self.metadata.get("frame_count")
        records = self.metadata.get("frames")
        if type(count) is not int or count < 0 or not isinstance(records, list) or len(records) < count:
            raise ValueError("Invalid durable sequence prefix or frame-record denominator")
        if any(not isinstance(record, dict) or record.get("valid") is not True for record in records[:count]):
            raise ValueError("Sequence valid prefix contains an invalid frame record")
        self._mapping = np.load(self.path, mmap_mode="r", allow_pickle=False)
        try:
            expected_ndim = 4 if self.metadata["axis_order"] == "THWC" else 3
            if self._mapping.ndim != expected_ndim or count > self._mapping.shape[0]:
                raise ValueError("Invalid sequence dimensions or durable prefix")
            if list(self._mapping.shape) != self.metadata.get("shape") or self._mapping.dtype.str != self.metadata.get("dtype"):
                raise ValueError("Sequence manifest shape/dtype differs from the NPY header")
            if self.metadata.get("expected_frames") != self._mapping.shape[0]:
                raise ValueError("Sequence expected-frame denominator differs from storage")
            self.array = self._mapping[:count]
        except Exception:
            self._mapping._mmap.close()
            raise
        self.data = self.array

    @property
    def frame_count(self):
        return len(self.array)

    def frame(self, index):
        from .frame import Frame
        if not -self.frame_count <= index < self.frame_count:
            raise IndexError(index)
        index %= self.frame_count
        record = self.metadata["frames"][index]
        metadata = dict(self.metadata)
        metadata.update(record)
        container_fields = ("frames", "frame_count", "expected_frames", "completed", "partial", "status",
                            "started_at", "ended_at", "error", "stopped", "time_units", "time_origin",
                            "save_reopen_verified", "reopen_verified_indices", "writer_error", "writer_overflow",
                            "writer_capacity", "accepted_frames", "acquired_frames", "recording_budget_bytes",
                            "free_bytes_at_start", "duration_limit_s", "failed_frame", "failed_transport_payload",
                            "failed_payload_write_error", "finalization_error", "index")
        for key in container_fields:
            metadata.pop(key, None)
        provenance = dict(self.metadata)
        records = provenance.pop("frames")
        # The immutable manifest retains the complete record list. Repeating it
        # in every selected Frame would make a T-frame summary retain O(T²)
        # metadata, although only one frame's pixels are accumulated at a time.
        source = {"path": str(self.path), "manifest_path": str(self.path.with_suffix(".npy.json")),
                  "time_index": index, "axis_kind": "time", "frame_records_count": len(records),
                  "container_provenance": provenance}
        metadata.update(data_level="raw_frame", display_mode="REPLAY",
                        axis_order="HWC" if self.array.ndim == 4 else "HW",
                        axis_kind="color_channel" if self.array.ndim == 4 else "sensor_plane",
                        axis_names=["y", "x"] + (["color_channel"] if self.array.ndim == 4 else []),
                        sequence_source=source,
                        shape=list(self.array.shape[1:]))
        # Independent ownership: the Frame stays valid after this file is closed.
        return Frame(np.array(self.array[index], copy=True), metadata)

    def close(self):
        self._mapping._mmap.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def load_sequence(path):
    return Sequence(path)


class SequenceRecorder:
    """Independent bounded writer; overflow is an explicit partial recording."""

    def __init__(self, directory, frame, max_frames, *, duration_s=None, capacity=8, writer_factory=SequenceWriter):
        if int(max_frames) != max_frames or max_frames < 1:
            raise ValueError("Positive integer max_frames required")
        if duration_s is not None and (not np.isfinite(duration_s) or duration_s <= 0):
            raise ValueError("Recording duration must be positive and finite")
        if capacity < 1:
            raise ValueError("Positive bounded writer capacity required")
        self.directory = Path(directory)
        if self.directory.exists():
            raise FileExistsError(self.directory)
        ancestor = self.directory.parent
        while not ancestor.exists():
            ancestor = ancestor.parent
        self.expected_bytes = int(frame.data.nbytes * max_frames)
        self.free_bytes = shutil.disk_usage(ancestor).free
        if self.expected_bytes + 256 * 1024**2 > self.free_bytes:
            raise OSError("Recording budget exceeds available space with 256 MiB reserve")
        self.queue = queue.Queue(maxsize=capacity)
        self.max_frames = int(max_frames)
        self.duration_s = duration_s
        self.started = time.monotonic()
        self.ended = None
        self.stop_event = threading.Event()
        self.done = threading.Event()
        self.error = None
        self.stopped = False
        self.duration_complete = False
        self.accepted = 0
        self.written = 0
        self.overflow = 0
        self.failed_frame = None
        self.failed_payload = None
        self.path = self.directory / "sequence.npy"
        self.metadata = None
        self._frame = frame
        self._writer_factory = writer_factory
        self.thread = threading.Thread(target=self._run, name="HyperLabWriter", daemon=True)
        self.thread.start()

    def submit(self, frame):
        if self.stop_event.is_set():
            return False
        if self.duration_s is not None and time.monotonic() - self.started >= self.duration_s:
            self.duration_complete = True
            self.stop_event.set()
            return False
        try:
            self.queue.put_nowait(frame)
        except queue.Full:
            self.overflow += 1
            self.failed_frame = dict(frame.metadata)
            self.error = "Writer queue overflow: recording stopped; no silent frame drop"
            self.stop_event.set()
            return False
        self.accepted += 1
        if self.accepted >= self.max_frames:
            self.stop_event.set()
        return True

    def stop(self, *, error=None):
        self.stopped = self.accepted < self.max_frames and not self.duration_complete
        self.error = self.error or error
        self.stop_event.set()

    def _run(self):
        writer = None
        try:
            metadata = dict(self._frame.metadata)
            # Per-frame identity is kept under frames; no single-frame identity applies to T.
            for key in ("sequence", "frame_id", "device_timestamp_ns", "host_monotonic_ns", "host_utc", "host_received_at"):
                metadata.pop(key, None)
            metadata.update(recording_budget_bytes=self.expected_bytes, free_bytes_at_start=self.free_bytes,
                            writer_capacity=self.queue.maxsize, duration_limit_s=self.duration_s,
                            acquisition_source=metadata.get("acquisition_source") or metadata.get("data_source") or "UNKNOWN",
                            display_mode="REPLAY")
            writer = self._writer_factory(self.directory, self._frame.data.shape, self._frame.data.dtype,
                                          self.max_frames, metadata=metadata)
            self._frame = None
            while not self.stop_event.is_set() or not self.queue.empty():
                try:
                    frame = self.queue.get(timeout=0.05)
                except queue.Empty:
                    if self.duration_s is not None and time.monotonic() - self.started >= self.duration_s:
                        self.duration_complete = True
                        self.stop_event.set()
                    continue
                writer.append(frame.data, dict(frame.metadata))
                self.written += 1
                self.queue.task_done()
        except Exception as exc:
            self.error = self.error or str(exc)
            self.stop_event.set()
        finally:
            if writer is not None:
                writer.meta.update(writer_overflow=self.overflow, accepted_frames=self.accepted,
                                   failed_frame=self.failed_frame, writer_error=self.error)
                if self.failed_payload is not None:
                    try:
                        failed_path = self.directory / "failed_transport_payload.bin"
                        with failed_path.open("xb") as stream:
                            stream.write(self.failed_payload)
                        writer.meta["failed_transport_payload"] = failed_path.name
                    except Exception as exc:
                        writer.meta["failed_payload_write_error"] = str(exc)
                        self.error = self.error or str(exc)
                try:
                    writer.finish(error=self.error, stopped=self.stopped, duration_complete=self.duration_complete)
                except Exception as exc:
                    self.error = self.error or str(exc)
                self.metadata = dict(writer.meta)
            # Release any unsaved arrays after a disk failure; their absence is explicit.
            while not self.queue.empty():
                self.queue.get_nowait()
            self._frame = None
            self.failed_payload = None
            self.ended = time.monotonic()
            self.done.set()

    def status(self):
        metadata = self.metadata or {}
        return {"path": str(self.path), "accepted_frames": self.accepted, "written_frames": self.written,
                "max_frames": self.max_frames, "queue_length": self.queue.qsize(), "queue_capacity": self.queue.maxsize,
                "overflow": self.overflow, "error": self.error, "done": self.done.is_set(),
                "completed": metadata.get("completed", False), "partial": metadata.get("partial", True),
                "save_reopen_verified": metadata.get("save_reopen_verified", False),
                "writer_fps": self.written / max((self.ended or time.monotonic()) - self.started, 0.001),
                "expected_bytes": self.expected_bytes, "free_bytes_at_start": self.free_bytes}
