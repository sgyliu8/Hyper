from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re

import numpy as np


def wavelength_unit_scale(value):
    """Scale to nm for explicitly recognized length units; unknown stays unknown."""
    text = str(value or "").strip().lower().replace("μ", "u").replace("µ", "u")
    return {"nm": 1.0, "nanometer": 1.0, "nanometers": 1.0, "nanometre": 1.0,
            "nanometres": 1.0, "um": 1000.0, "micrometer": 1000.0, "micrometers": 1000.0,
            "micrometre": 1000.0, "micrometres": 1000.0, "micron": 1000.0,
            "microns": 1000.0}.get(text)


def _normalize_units(meta):
    value = meta.get("wavelength_units")
    scale = wavelength_unit_scale(value)
    if scale is not None:
        meta.setdefault("wavelength_units_original", value)
        meta["wavelength_units"] = "nm" if scale == 1 else "um"


@dataclass
class Cube:
    """Data are H,W,K. K is a state/index unless wavelength evidence is present."""

    data: np.ndarray
    metadata: dict = field(default_factory=dict)
    valid_mask: np.ndarray | None = None

    def __post_init__(self):
        if self.data.ndim != 3 or any(n < 1 for n in self.data.shape):
            raise ValueError("Cube data must have nonempty H,W,K axes")
        if self.data.dtype.kind not in "uif":
            raise ValueError("Cube requires real numeric data; complex/Bayer interpretation is not implicit")
        self.metadata = dict(self.metadata)
        if self.metadata.get("data_level") == "raw_sequence" or self.metadata.get("axis_kind") == "time":
            raise ValueError("A time sequence is not a Cube; use load_sequence and select an individual frame")
        for key, default in {
            "data_level": "raw_scan", "units": "unknown", "pixel_format": "unknown",
            "effective_bits": None, "frame_ids": None, "timestamps": None,
            "scan_states": None, "wavelengths": None, "wavelength_units": None,
            "wavelength_source": None, "exposure": None, "gain": None,
            "processing_steps": [], "calibration_source": None,
            "device": None, "runtime": None, "data_source": "unknown",
            "completed": None, "partial": None,
        }.items():
            self.metadata.setdefault(key, default)
        wave = self.metadata["wavelengths"]
        _normalize_units(self.metadata)
        channels = self.metadata.get("channel_labels")
        if channels is not None:
            if self.metadata["data_level"] not in {"raw_frame", "derived_frame"} or len(channels) != self.data.shape[2] or wave is not None:
                raise ValueError("Color channels must be a raw_frame or derived_frame with matching labels and no wavelength axis")
        if wave is not None:
            wave = np.asarray(wave, dtype=float)
            if wave.shape != (self.data.shape[2],) or not np.all(np.isfinite(wave)):
                raise ValueError("Wavelength vector must be finite and match K")
            self.metadata["wavelengths"] = wave.tolist()
            steps = np.diff(wave)
            self.metadata["wavelength_order"] = ("duplicate" if len(np.unique(wave)) != len(wave)
                else "increasing" if np.all(steps > 0) else "decreasing" if np.all(steps < 0)
                else "nonmonotonic")
            self.metadata.setdefault("wavelength_evidence", "declared")
        for key in ("band_validity", "fwhm"):
            value = self.metadata.get(key)
            if value is not None:
                if np.shape(value) != (self.data.shape[2],):
                    raise ValueError(f"{key} must match K")
                if key == "fwhm" and (not np.isfinite(value).all() or np.any(np.asarray(value) <= 0)):
                    raise ValueError("fwhm must be finite and positive")
        source = self.metadata["data_source"]
        self.metadata.setdefault("acquisition_source", "SYNTHETIC" if self.metadata.get("synthetic")
                                 else source if source in {"LIVE", "SYNTHETIC"} else "unknown")
        if self.valid_mask is not None:
            if self.valid_mask.dtype != np.bool_:
                raise ValueError("valid_mask must be boolean")
            if self.valid_mask.shape not in (self.data.shape, self.data.shape[:2]):
                raise ValueError("valid_mask must have HW or HWK shape")
        plane = self.metadata["data_level"] in {"raw_frame", "derived_frame"} and self.data.shape[2] == 1
        self.metadata.update(shape=list(self.data.shape), axis_order="HWK",
                             axis_names=["y", "x", "color_channel" if channels is not None else "wavelength" if wave is not None
                                         else "sensor_plane" if plane else "state"],
                             dtype=str(self.data.dtype), estimated_bytes=int(self.data.nbytes))

    @property
    def shape(self):
        return self.data.shape

    @property
    def wavelengths(self):
        value = self.metadata["wavelengths"]
        return None if value is None else np.asarray(value, dtype=float)

    def close(self):
        """Release owned mapped-file handles, including transpose views, on Windows."""
        seen = set()
        for array in (self.data, self.valid_mask):
            while array is not None:
                mapped = getattr(array, "_mmap", None)
                if mapped is not None and id(mapped) not in seen:
                    seen.add(id(mapped))
                    if not mapped.closed:
                        mapped.close()
                array = getattr(array, "base", None)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _dumps(value):
    return json.dumps(value, indent=2, default=_json_default, allow_nan=False)


def _transpose(data, order):
    if order is None:
        raise ValueError("Axis order is unknown; supply axis_order='HWK', 'KHW', etc.")
    order = str(order).upper().replace(",", "").replace(" ", "")
    if order == "HW" and data.ndim == 2:
        return data[:, :, None]
    if order == "HWC" and data.ndim == 3:
        return data
    if len(order) != 3 or set(order) != set("HWK") or data.ndim != 3:
        raise ValueError("axis_order must be a permutation of HWK (or HW for a raw frame)")
    return data.transpose(tuple(order.index(axis) for axis in "HWK"))


def _sidecar(path):
    return path.with_suffix(path.suffix + ".json")


def load_cube(path, axis_order=None, *, dataset=None, binary_path=None):
    """Load ENVI, NPY+JSON or NPZ; no axes or wavelength units are guessed."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".hdr":
        return _load_envi(path, binary_path=binary_path)
    meta = {}
    mask = None
    if suffix == ".npy":
        data = np.load(path, mmap_mode="r", allow_pickle=False)
        if _sidecar(path).exists():
            meta = json.loads(_sidecar(path).read_text(encoding="utf-8"))
        if meta.get("valid_mask_file"):
            mask = np.load(path.parent / meta["valid_mask_file"], mmap_mode="r", allow_pickle=False)
    elif suffix == ".npz":
        with np.load(path, allow_pickle=False) as archive:
            if "metadata" in archive:
                meta = json.loads(str(archive["metadata"].item()))
            candidates = [k for k in archive.files if k not in {"metadata", "valid_mask"}]
            if dataset is None:
                if candidates == ["data"]:
                    dataset = "data"
                else:
                    raise ValueError(f"Specify dataset explicitly; available arrays: {candidates}")
            data = archive[dataset]
            if "valid_mask" in archive:
                mask = archive["valid_mask"]
        meta["load_note"] = "NPZ materializes its selected array; use NPY/ENVI for memory mapping"
    else:
        raise ValueError("Supported inputs: ENVI .hdr, .npy with explicit axes, .npz")
    order = axis_order or meta.get("axis_order")
    if meta.get("data_level") == "raw_sequence" or (order and str(order).upper().startswith("T")):
        raise ValueError("A time sequence is not a Cube; use load_sequence")
    if order and str(order).upper() == "HWC":
        if meta.get("wavelengths") is not None:
            raise ValueError("HWC color frame cannot carry a spectral wavelength axis")
        meta.setdefault("data_level", "raw_frame")
        meta.setdefault("channel_labels", [f"channel_{i}" for i in range(data.shape[2])])
    mapped = _transpose(data, order)
    if mask is not None and mask.ndim == 3:
        mask = _transpose(mask, order)
    elif mask is not None and mask.ndim == 2 and order and str(order).upper().index("W") < str(order).upper().index("H"):
        mask = mask.T
    if "frame_count" in meta:
        count = meta["frame_count"]
        if not isinstance(count, int) or not 0 < count <= mapped.shape[2]:
            raise ValueError("No acquired frames or invalid frame_count in partial scan")
        mapped = mapped[:, :, :count]
        if mask is not None and mask.ndim == 3:
            mask = mask[:, :, :count]
        if meta.get("wavelengths") is not None:
            meta["wavelengths"] = meta["wavelengths"][:count]
        for field in ("band_validity", "fwhm", "scan_states", "frame_ids", "timestamps"):
            if isinstance(meta.get(field), list):
                meta[field] = meta[field][:count]
    meta.setdefault("source_file", str(path.resolve()))
    meta["display_mode"] = "REPLAY"
    return Cube(mapped, meta, mask)


ENVI_TYPES = {1: "u1", 2: "i2", 3: "i4", 4: "f4", 5: "f8",
              12: "u2", 13: "u4", 14: "i8", 15: "u8"}


def _parse_header(path):
    text = path.read_text(encoding="utf-8-sig")
    if not text.lstrip().startswith("ENVI"):
        raise ValueError("Header must start with ENVI; an arbitrary DAT is not an ENVI file")
    result = {}
    pending = ""
    for line in text.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        pending += " " + line
        if pending.count("{") != pending.count("}"):
            continue
        if "=" in pending:
            key, value = pending.split("=", 1)
            result[key.strip().lower()] = value.strip().strip("{}").strip()
        pending = ""
    if pending.strip():
        raise ValueError("Unclosed ENVI header field")
    return result


def _load_envi(path, binary_path=None):
    hdr = _parse_header(path)
    try:
        h, w, k = (int(hdr[key]) for key in ("lines", "samples", "bands"))
        byte_order = int(hdr["byte order"])
        dtype = np.dtype(ENVI_TYPES[int(hdr["data type"])])
        offset = int(hdr.get("header offset", 0))
        interleave = hdr["interleave"].lower()
    except (KeyError, ValueError) as exc:
        raise ValueError("Missing/unsupported ENVI dimensions, data type, byte order or interleave") from exc
    if byte_order not in (0, 1) or offset < 0 or min(h, w, k) < 1:
        raise ValueError("Invalid ENVI dimensions, offset or byte order")
    dtype = dtype.newbyteorder("<" if byte_order == 0 else ">")
    layouts = {"bsq": ((k, h, w), (1, 2, 0)), "bil": ((h, k, w), (0, 2, 1)),
               "bip": ((h, w, k), (0, 1, 2))}
    if interleave not in layouts:
        raise ValueError("ENVI interleave must be BSQ, BIL or BIP")
    if binary_path is not None:
        binary = Path(binary_path)
    elif "data file" in hdr:
        binary = path.parent / hdr["data file"]
    else:
        candidates = [p for p in [path.with_suffix(""), path.with_suffix(".dat"),
                                  path.with_suffix(".img"), path.with_suffix(".raw"),
                                  path.with_suffix(".bin")] if p.is_file()]
        if len(candidates) != 1:
            raise ValueError("ENVI binary is missing or ambiguous; supply binary_path")
        binary = candidates[0]
    expected = offset + h * w * k * dtype.itemsize
    if binary.stat().st_size < expected:
        raise ValueError(f"Truncated ENVI binary: need {expected} bytes")
    shape, axes = layouts[interleave]
    wave = None
    if "wavelength" in hdr:
        wave = [float(x) for x in re.split(r"[,\s]+", hdr["wavelength"]) if x]
    meta = {"envi_header": hdr, "source_file": str(path.resolve()), "wavelengths": wave,
            "wavelength_units": hdr.get("wavelength units"),
            "wavelength_source": str(path.resolve()) if wave is not None else None,
            "data_level": "spectral_cube" if wave is not None else "raw_scan",
            "units": hdr.get("data units", "unknown"), "data_source": "external_envi"}
    mask = None
    if _sidecar(path).exists():
        saved = json.loads(_sidecar(path).read_text(encoding="utf-8"))
        # Compare physical axes in a common unit before accepting provenance.
        saved_wave = saved.get("wavelengths")
        header_units, saved_units = hdr.get("wavelength units"), saved.get("wavelength_units")
        hscale, sscale = wavelength_unit_scale(header_units), wavelength_unit_scale(saved_units)
        if wave is not None and saved_wave is not None:
            if hscale is not None and sscale is not None:
                agree = np.shape(wave) == np.shape(saved_wave) and np.allclose(
                    np.asarray(wave) * hscale, np.asarray(saved_wave) * sscale, rtol=1e-12, atol=0)
            else:
                agree = header_units == saved_units and wave == saved_wave
            if not agree:
                raise ValueError("ENVI header and sidecar wavelengths/units disagree; resolve explicitly")
        elif wave != saved_wave:
            raise ValueError("ENVI header and sidecar wavelengths disagree")
        if "data units" in hdr and saved.get("units", hdr["data units"]) != hdr["data units"]:
            raise ValueError("ENVI header and sidecar data units disagree")
        meta.update({key: value for key, value in saved.items() if key not in
                     {"wavelengths", "wavelength_units", "envi_header", "source_file"}})
        meta["envi_sidecar_wavelength_units_original"] = saved_units
        if saved.get("valid_mask_file"):
            mask = np.load(path.parent / saved["valid_mask_file"], mmap_mode="r", allow_pickle=False)
    if "data ignore value" in hdr:
        ignore = float(hdr["data ignore value"])
        if np.isfinite(ignore):
            meta["data_ignore_value"] = ignore
        else:
            meta.pop("data_ignore_value", None)
            meta["envi_invalid_encoding"] = "NaN; excluded by finite validity policy"
    if "bbl" in hdr:
        good = [bool(int(x)) for x in re.split(r"[,\s]+", hdr["bbl"]) if x]
        if len(good) != k:
            raise ValueError("ENVI bbl length must match bands")
        meta["band_validity"] = good
    if "fwhm" in hdr:
        meta["fwhm"] = [float(x) for x in re.split(r"[,\s]+", hdr["fwhm"]) if x]
    meta["display_mode"] = "REPLAY"
    data = np.memmap(binary, mode="r", dtype=dtype, offset=offset, shape=shape).transpose(axes)
    try:
        return Cube(data, meta, mask)
    except BaseException:
        data._mmap.close()
        if mask is not None:
            mask._mmap.close()
        raise


def save_cube(cube, path, *, interleave="bip", byte_order=0):
    """Save a new product; never overwrite an existing artifact or raw sidecar."""
    path = Path(path)
    meta = dict(cube.metadata)
    meta.pop("valid_mask_file", None)
    if path.suffix.lower() not in {".npy", ".npz", ".hdr"}:
        raise ValueError("Output must be .npy, .npz or .hdr")
    mask_path = path.with_suffix(path.suffix + ".valid.npy")
    targets = [path]
    if path.suffix.lower() != ".npz":
        targets.append(_sidecar(path))
        if cube.valid_mask is not None:
            targets.append(mask_path)
            meta["valid_mask_file"] = mask_path.name
    if path.suffix.lower() == ".hdr":
        targets.append(path.with_suffix(".dat"))
    if any(p.exists() for p in targets):
        raise FileExistsError("Output exists; select a new path to preserve original data")
    # Validate serializability before writing data; ENVI may add export encoding below.
    metadata_json = _dumps(meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".npz":
        arrays = {"data": cube.data, "metadata": np.asarray(metadata_json)}
        if cube.valid_mask is not None:
            arrays["valid_mask"] = cube.valid_mask
        np.savez(path, **arrays)
    else:
        if path.suffix.lower() == ".npy":
            np.save(path, cube.data, allow_pickle=False)
        else:
            meta.update(_save_envi(cube, path, interleave.lower(), byte_order))
        if cube.valid_mask is not None:
            np.save(mask_path, cube.valid_mask, allow_pickle=False)
        _sidecar(path).write_text(_dumps(meta), encoding="utf-8")
    return path


def _save_envi(cube, path, interleave, byte_order):
    # An arbitrary pixel mask is not ENVI bbl. Encode masked exported samples as
    # NaN in a floating copy and keep the exact mask sidecar; never mutate source.
    floating_export = cube.valid_mask is not None
    dtype = cube.data.dtype
    if floating_export:
        dtype = np.dtype("f8" if dtype.itemsize > (4 if dtype.kind == "f" else 2) else "f4")
    codes = {np.dtype(value).str[1:]: key for key, value in ENVI_TYPES.items()}
    code = codes.get(dtype.str[1:])
    if code is None or interleave not in {"bsq", "bil", "bip"} or byte_order not in (0, 1):
        raise ValueError("Unsupported ENVI dtype, interleave or byte_order")
    binary = path.with_suffix(".dat")
    dtype = dtype.newbyteorder("<" if byte_order == 0 else ">")
    h, w, k = cube.shape

    def encoded(selection):
        source = cube.data[selection]
        if not floating_export:
            return np.asarray(source, dtype=dtype)
        if source.dtype.kind in "iu" and source.dtype.itemsize >= 8:
            if np.any(source > 2**53) or (source.dtype.kind == "i" and np.any(source < -(2**53))):
                raise ValueError("Masked ENVI float export would lose int64 precision; use lossless NPY plus mask")
        result = np.array(source, dtype=dtype, copy=True)
        mask = cube.valid_mask[selection[:2]] if cube.valid_mask.ndim == 2 else cube.valid_mask[selection]
        if mask.ndim < result.ndim:
            mask = mask[..., None]
        good = np.isfinite(source) & mask
        ignore = cube.metadata.get("data_ignore_value")
        if ignore is not None:
            good &= source != ignore
        result[~good] = np.nan
        return result

    with binary.open("xb") as stream:
        if interleave == "bsq":
            for band in range(k):
                encoded((slice(None), slice(None), band)).tofile(stream)
        else:
            for row in range(h):
                block = encoded((row, slice(None), slice(None)))
                (block if interleave == "bip" else block.T).tofile(stream)
    lines = ["ENVI", f"samples = {w}", f"lines = {h}", f"bands = {k}", "header offset = 0",
             "file type = ENVI Standard", f"data type = {code}", f"interleave = {interleave}",
             f"byte order = {byte_order}", f"data file = {binary.name}"]
    if cube.metadata.get("band_validity") is not None:
        lines.append("bbl = {" + ", ".join(str(int(v)) for v in cube.metadata["band_validity"]) + "}")
    if cube.metadata.get("units"):
        lines.append("data units = " + str(cube.metadata["units"]))
    if floating_export:
        lines.append("data ignore value = NaN")
    elif cube.metadata.get("data_ignore_value") is not None:
        lines.append("data ignore value = " + str(cube.metadata["data_ignore_value"]))
    if cube.wavelengths is not None:
        lines.append("wavelength = {" + ", ".join(repr(x) for x in cube.wavelengths.tolist()) + "}")
        if cube.metadata["wavelength_units"]:
            lines.append("wavelength units = " + cube.metadata["wavelength_units"])
        if cube.metadata.get("fwhm") is not None:
            lines.append("fwhm = {" + ", ".join(str(v) for v in cube.metadata["fwhm"]) + "}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"dtype": str(dtype), "data_ignore_value": None,
            "envi_invalid_encoding": "NaN in floating export; exact validity is in mask sidecar",
            "source_data_ignore_value": cube.metadata.get("data_ignore_value"),
            "source_storage_dtype": str(cube.data.dtype)} if floating_export else {}


def make_synthetic_cube(seed=42):
    """Small deterministic demo with known simulated wavelengths, never hardware evidence."""
    rng = np.random.default_rng(seed)
    h, w, k = 48, 64, 24
    wave = np.linspace(450, 900, k)
    baseline = 500 + 700 * np.exp(-((wave - 670) / 110) ** 2)
    data = np.broadcast_to(baseline, (h, w, k)).copy()
    data[8:24, 8:26] *= 0.6  # Brightness scaling; SAM should mostly reject this nuisance.
    data[25:42, 35:55] += 450 * np.exp(-((wave - 790) / 35) ** 2)
    data += 80 + rng.normal(0, 8, data.shape)  # Known synthetic dark pedestal and noise.
    data = np.round(data).astype(np.uint16)
    data[2:5, 2:5, 4:8] = 4095
    valid = np.ones(data.shape, dtype=bool)
    valid[0, 0, :] = False
    meta = {"synthetic": True, "data_source": "SYNTHETIC", "data_level": "spectral_cube",
            "units": "DN", "linear_intensity": True, "wavelengths": wave.tolist(),
            "wavelength_units": "nm", "wavelength_source": "synthetic analytic design",
            "exposure": 10.0, "gain": 1.0, "settings": {"simulation": "v1"},
            "pixel_format": "Mono12 in uint16", "effective_bits": 12,
            "saturation_value": 4095, "completed": True, "partial": False,
            "processing_steps": [], "synthetic_dark_level": 80,
            "description": "Simulated spectral patch, brightness patch, dark, noise, saturation and invalid pixel"}
    return Cube(data, meta, valid)
