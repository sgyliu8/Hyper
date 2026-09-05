from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import numpy as np


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class ScanWriter:
    """Append-only valid prefix; an interrupted acquisition stays partial."""

    def __init__(self, directory, shape, dtype, *, source, metadata=None, checkpoint_frames=8):
        if source not in ("LIVE", "REPLAY", "SYNTHETIC"):
            raise ValueError("Explicit LIVE / REPLAY / SYNTHETIC source required")
        if len(shape) != 3 or min(shape) <= 0:
            raise ValueError("Expected positive H,W,states shape")
        if checkpoint_frames < 1:
            raise ValueError("Positive checkpoint frame count required")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.path = self.directory / "cube.npy"
        physical_shape = (shape[2], shape[0], shape[1])
        self.array = np.lib.format.open_memmap(self.path, mode="w+", dtype=dtype, shape=physical_shape)
        self.meta = dict(metadata or {})
        self.meta.update(data_level="raw_scan", data_source=source, synthetic=source == "SYNTHETIC",
                         shape=list(physical_shape), axis_order="KHW", axis_names=["scan_state", "y", "x"],
                         logical_axis_order="HWK", logical_shape=list(shape), schema_version=2,
                         acquisition_source=source, display_mode="REPLAY", axis_kind="scan_state",
                         dtype=np.dtype(dtype).str, units="DN", wavelengths=None,
                         expected_frames=shape[2], frame_count=0, frames=[],
                         completed=False, partial=True, status="partial", started_at=utc_now(),
                         processing_steps=[], calibration_source=None)
        self.closed = False
        self.checkpoint_frames = checkpoint_frames
        self._sample_first = self._sample_last = None
        self._durable_count = 0
        try:
            self._checkpoint()
        except Exception:
            self.array._mmap.close()
            self.closed = True
            raise

    def _checkpoint(self):
        from .sequence import atomic_json
        import os
        self.array.flush()
        with self.path.open("r+b") as stream:
            os.fsync(stream.fileno())
        self._durable_count = self.meta["frame_count"]
        atomic_json(self.path.with_suffix(".npy.json"), self.meta)

    def append(self, frame, record):
        if self.closed:
            raise RuntimeError("Writer already closed")
        index = self.meta["frame_count"]
        if index >= self.array.shape[0]:
            raise ValueError("More frames than declared")
        frame = np.asarray(frame)
        if frame.shape != self.array.shape[1:] or frame.dtype != self.array.dtype:
            raise ValueError("Frame shape/dtype changed; refusing conversion")
        if record.get("valid") is not True:
            raise ValueError("Only valid frames may enter the valid prefix; record failure separately")
        json.dumps(record, allow_nan=False)
        self.array[index] = frame
        if index == 0:
            self._sample_first = frame.copy()
        self._sample_last = frame.copy()
        self.meta["frames"].append(dict(record, index=index))
        self.meta["frame_count"] = index + 1
        if (index + 1) % self.checkpoint_frames == 0:
            self._checkpoint()

    def finish(self, *, error=None, stopped=False):
        if self.closed:
            return self.path
        complete = self.meta["frame_count"] == self.meta["expected_frames"] and not error and not stopped
        self.meta.update(completed=complete, partial=not complete,
                         status="completed" if complete else "partial", error=error,
                         stopped=bool(stopped), ended_at=utc_now())
        primary = None
        try:
            self.array.flush()
            check = np.load(self.path, mmap_mode="r", allow_pickle=False)
            try:
                indices = []
                if self.meta["frame_count"]:
                    last = self.meta["frame_count"] - 1
                    for index, sample in ((0, self._sample_first), (last, self._sample_last)):
                        if not np.array_equal(check[index], sample, equal_nan=True):
                            raise RuntimeError(f"Scan reopen content differs at frame {index}")
                        indices.append(index)
                self.meta["reopen_verified_indices"] = sorted(set(indices))
                self.meta["save_reopen_verified"] = True
            finally:
                check._mmap.close()
            self._checkpoint()
        except Exception as exc:
            primary = exc
            self.meta.update(completed=False, partial=True, status="partial",
                             error=error or str(exc), finalization_error=str(exc))
            self.meta["acquired_frames"] = self.meta["frame_count"]
            self.meta["frame_count"] = self._durable_count
            try:
                from .sequence import atomic_json
                atomic_json(self.path.with_suffix(".npy.json"), self.meta)
            except Exception as receipt_error:
                exc.add_note(f"Scan failure receipt also failed: {receipt_error}")
        finally:
            try:
                self.array._mmap.close()
            except Exception as close_error:
                if primary is None:
                    primary = close_error
                else:
                    primary.add_note(f"Mapping close also failed: {close_error}")
            self.closed = True
            self._sample_first = self._sample_last = None
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
            error.add_note(f"Scan finalization also failed: {cleanup_error}")


def synthetic_scan(directory, *, stop=None, progress=None, frames=12, disconnect_at=None):
    """Software-only scan-state fixture; no wavelength or device commands."""
    stop = stop or threading.Event()
    writer = ScanWriter(directory, (48, 64, frames), np.uint16, source="SYNTHETIC",
                        metadata={"pixel_format": "Mono16", "effective_bits": 12})
    try:
        y, x = np.indices((48, 64))
        for index in range(frames):
            if stop.is_set():
                break
            if index == disconnect_at:
                raise ConnectionError("SYNTHETIC disconnect injection")
            image = ((x + y + index * 11) % 4095).astype(np.uint16)
            writer.append(image, {"target_state": index, "returned_state": index,
                                  "frame_id": index, "timestamp": utc_now(), "valid": True,
                                  "exposure_us": None, "gain": None, "error": None})
            if progress:
                progress(index + 1, frames)
        return writer.finish(stopped=stop.is_set())
    except Exception as exc:
        try:
            writer.finish(error=str(exc))
        except Exception as cleanup_error:
            exc.add_note(f"Scan finalization also failed: {cleanup_error}")
        raise
