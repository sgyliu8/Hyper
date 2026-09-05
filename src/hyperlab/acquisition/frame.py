"""Owned raw sensor frames; display transforms never modify these samples."""
from dataclasses import dataclass
import json
from pathlib import Path
import numpy as np


class FrozenDict(dict):
    def _immutable(self, *args, **kwargs):
        raise TypeError("Frame evidence is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable
    __ior__ = _immutable


def _freeze(value):
    if isinstance(value, dict):
        return FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class Frame:
    data: np.ndarray
    metadata: dict

    def __post_init__(self):
        if self.data.ndim not in (2, 3):
            raise ValueError("A frame must be HW or HWC")
        # The adapter transfers its owned copy. No second full-frame copy here.
        self.data.flags.writeable = False
        metadata = json.loads(json.dumps(dict(self.metadata), allow_nan=False))
        object.__setattr__(self, "metadata", _freeze(metadata))

    @property
    def identity(self):
        return f"{self.metadata['session_id']}:{self.metadata.get('stream_epoch', 0)}:{self.metadata['sequence']}"


def save_frame(directory, frame, *, transport_payload=None):
    """Save the exact supplied raw frame and verify all reopened samples."""
    from PIL import Image
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "frame.npy"
    metadata = dict(frame.metadata, completed=False, partial=True, display_mode="REPLAY",
                    snapshot_source_display_mode=frame.metadata.get("display_mode"))
    primary = None
    try:
        np.save(path, frame.data, allow_pickle=False)
        if transport_payload is not None:
            (directory / "transport_payload.bin").write_bytes(transport_payload)
        check = np.load(path, mmap_mode="r", allow_pickle=False)
        try:
            if not np.array_equal(check, frame.data, equal_nan=True):
                raise RuntimeError("Saved raw frame content differs from acquired samples")
        finally:
            check._mmap.close()
        metadata["save_reopen_verified"] = True
        if frame.data.ndim == 3:
            display = frame.data[:, :, ::-1] if metadata["pixel_format"] == "BGR8" else frame.data
            metadata["preview_processing"] = "camera colour output; not colorimetrically calibrated"
        else:
            low, high = np.percentile(frame.data, [1, 99])
            display = np.zeros(frame.data.shape, np.uint8) if high <= low else (
                np.clip((frame.data.astype(np.float32) - low) / (high - low), 0, 1) * 255).astype(np.uint8)
            metadata["preview_processing"] = "1-99 percentile display stretch; Bayer mosaic uninterpolated"
        Image.fromarray(display).save(directory / "preview.png")
        metadata.update(completed=True, partial=False)
    except Exception as exc:
        primary = exc
        metadata["error"] = str(exc)
    finally:
        try:
            path.with_suffix(".npy.json").write_text(json.dumps(metadata, indent=2, allow_nan=False), encoding="utf-8")
        except Exception as write_error:
            if primary is None:
                raise
            primary.add_note(f"Writing frame receipt also failed: {write_error}")
    if primary is not None:
        raise primary
    return path
