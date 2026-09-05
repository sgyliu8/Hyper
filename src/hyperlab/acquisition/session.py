from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import numpy as np


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class ScanWriter:
    """Append-only valid prefix; an interrupted acquisition stays partial."""

    def __init__(self, directory, shape, dtype, *, source, metadata=None):
        if source not in ("LIVE", "REPLAY", "SYNTHETIC"):
            raise ValueError("Explicit LIVE / REPLAY / SYNTHETIC source required")
        if len(shape) != 3 or min(shape) <= 0:
            raise ValueError("Expected positive H,W,states shape")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.path = self.directory / "cube.npy"
        self.array = np.lib.format.open_memmap(self.path, mode="w+", dtype=dtype, shape=shape)
        self.meta = dict(metadata or {})
        self.meta.update(data_level="raw_scan", data_source=source, synthetic=source == "SYNTHETIC",
                         shape=list(shape), axis_order="HWK", axis_names=["y", "x", "scan_state"],
                         dtype=np.dtype(dtype).str, units="DN", wavelengths=None,
                         expected_frames=shape[2], frame_count=0, frames=[],
                         completed=False, partial=True, status="partial", started_at=utc_now(),
                         processing_steps=[], calibration_source=None)
        self.closed = False
        self._checkpoint()

    def _checkpoint(self):
        target = self.path.with_suffix(".npy.json")
        temp = target.with_suffix(".json.tmp")
        temp.write_text(json.dumps(self.meta, indent=2, allow_nan=False), encoding="utf-8")
        temp.replace(target)

    def append(self, frame, record):
        if self.closed:
            raise RuntimeError("Writer already closed")
        index = self.meta["frame_count"]
        if index >= self.array.shape[2]:
            raise ValueError("More frames than declared")
        frame = np.asarray(frame)
        if frame.shape != self.array.shape[:2] or frame.dtype != self.array.dtype:
            raise ValueError("Frame shape/dtype changed; refusing conversion")
        if record.get("valid") is not True:
            raise ValueError("Only valid frames may enter the valid prefix; record failure separately")
        json.dumps(record, allow_nan=False)
        self.array[:, :, index] = frame
        self.array.flush()
        self.meta["frames"].append(dict(record, index=index))
        self.meta["frame_count"] = index + 1
        self._checkpoint()

    def finish(self, *, error=None, stopped=False):
        if self.closed:
            return self.path
        complete = self.meta["frame_count"] == self.meta["expected_frames"] and not error and not stopped
        self.meta.update(completed=complete, partial=not complete,
                         status="completed" if complete else "partial", error=error,
                         stopped=bool(stopped), ended_at=utc_now())
        self.array.flush()
        self._checkpoint()
        self.closed = True
        return self.path


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
        writer.finish(error=str(exc))
        raise
