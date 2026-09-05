"""Thin Harvester API path, based on the official tutorial.

Loading a CTI executes native code. This module is acquisition-mode only;
the inventory probe never imports Harvester or opens a device.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import numpy as np
from hyperlab.acquisition.session import utc_now


def _value(obj, name):
    try:
        return getattr(obj, name).value
    except (AttributeError, RuntimeError):
        return None


def _review_producer(cti):
    if os.name != "nt":
        raise RuntimeError("This reviewed OEM path targets Windows x64")
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
        root = Path(winreg.QueryValueEx(key, "MVIMPACT_ACQUIRE_DIR")[0]).resolve()
    if not cti.is_relative_to(root):
        raise ValueError("CTI must remain under the installed OEM MVIMPACT_ACQUIRE_DIR")
    import struct
    with cti.open("rb") as stream:
        stream.seek(0x3c)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        if stream.read(4) != b"PE\0\0" or struct.unpack("<H", stream.read(2))[0] != 0x8664:
            raise ValueError("Producer is not Windows AMD64 PE")
    environment = dict(os.environ, HYPERLAB_CTI_REVIEW_PATH=str(cti))
    command = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
               "$s=Get-AuthenticodeSignature -FilePath $env:HYPERLAB_CTI_REVIEW_PATH; "
               "@{valid=($s.Status -eq 'Valid'); signer=$s.SignerCertificate.Subject} | ConvertTo-Json")
    shell = shutil.which("pwsh") or "powershell.exe"
    if shell == "powershell.exe":
        environment.pop("PSModulePath", None)
    response = subprocess.run([shell, "-NoProfile", "-Command", command],
                              capture_output=True, text=True, encoding="utf-8", timeout=30, check=True, env=environment)
    signature = json.loads(response.stdout)
    if not signature["valid"] or not re.search(r"Balluff|MATRIX VISION", signature["signer"], re.I):
        raise ValueError("Installed producer signature is not valid for the reviewed OEM")
    return signature


def capture_single(cti, serial, output, *, timeout=5, pixel_format=None, exposure_us=None, gain=None):
    """Retain current settings, capture one unprocessed sensor plane, stop.

    CTI must be the reviewed OEM producer in its installed location. Caller
    chooses the exact serial; no device index or virtual fallback is allowed.
    """
    if not serial or not 0 < timeout <= 30:
        raise ValueError("Exact serial and timeout in (0,30] seconds required")
    cti = Path(cti).resolve(strict=True)
    if cti.name != "mvGenTLProducer.cti":
        raise ValueError("Only the reviewed Balluff mvGenTLProducer.cti is supported")
    producer_review = _review_producer(cti)
    from harvesters.core import Harvester
    from importlib.metadata import version
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=False)
    receipt = {"data_source": "LIVE", "data_level": "raw_frame", "synthetic": False,
               "wavelengths": None, "started_at": utc_now(), "serial": serial,
               "producer": str(cti), "runtime": {"harvesters": version("harvesters")},
               "producer_signature": producer_review,
               "completed": False, "partial": True, "scene_validation": "NOT_TESTED",
               "processing_steps": [], "calibration_source": None, "units": "DN"}
    dll_dir = os.add_dll_directory(str(cti.parent)) if os.name == "nt" else None
    try:
        with Harvester() as harvester:
            harvester.add_file(str(cti), check_existence=True, check_validity=True)
            harvester.update()
            matches = [d for d in harvester.device_info_list if d.serial_number == serial]
            if len(matches) != 1:
                raise RuntimeError(f"Expected one exact serial match; found {len(matches)}")
            info = matches[0]
            if "mvBlueFOX3" not in info.model or info.tl_type != "U3V":
                raise RuntimeError("Target is not the investigated mvBlueFOX3 USB3 Vision device")
            receipt.update(model=info.model, vendor=info.vendor, tl_type=info.tl_type)
            with harvester.create({"serial_number": serial}) as camera:
                nodes = camera.remote_device.node_map
                current = {name: _value(nodes, name) for name in (
                    "Width", "Height", "PixelFormat", "ExposureTime", "Gain", "TriggerMode",
                    "AcquisitionMode", "DeviceFirmwareVersion", "DeviceVersion", "TestPattern",
                    "TestImageSelector", "PixelColorFilter", "mvSensorDigitizationBitDepth")}
                receipt["current_settings"] = current
                receipt["exposure_us"] = current["ExposureTime"]
                receipt["gain"] = current["Gain"]
                # Leave trigger, pixel format, exposure, gain and UserSets untouched.
                if current["TriggerMode"] not in (None, "Off"):
                    raise RuntimeError("Current trigger is enabled; verified trigger procedure is required")
                for test_node in ("TestPattern", "TestImageSelector"):
                    if current[test_node] not in (None, "Off"):
                        raise RuntimeError(f"{test_node} is enabled; do not label a test pattern a real scene")
                from genicam import genapi
                requested = {name: value for name, value in {
                    "PixelFormat": pixel_format, "ExposureTime": exposure_us, "Gain": gain
                }.items() if value is not None}
                for name, value in requested.items():
                    node = getattr(nodes, name)
                    if not genapi.is_writable(node):
                        raise ValueError(f"{name} is not writable in this session")
                    if name == "PixelFormat":
                        available = [entry.symbolic for entry in node.entries if genapi.is_available(entry)]
                        if value not in available or value not in ("RGB8", "BGR8", "BayerRG12"):
                            raise ValueError("Pixel format must be a reviewed and currently available device enumeration")
                    elif not np.isfinite(value) or not node.min <= value <= node.max:
                        raise ValueError(f"{name} outside current device range [{node.min}, {node.max}]")
                changed = {}
                started = False
                try:
                    for name, value in requested.items():
                        changed[name] = getattr(nodes, name).value
                        getattr(nodes, name).value = value
                    receipt["session_changes"] = {name: {"before": value, "requested": requested[name],
                        "readback": getattr(nodes, name).value} for name, value in changed.items()}
                    receipt["exposure_us"] = _value(nodes, "ExposureTime")
                    receipt["gain"] = _value(nodes, "Gain")
                    camera.start()
                    started = True
                    with camera.fetch(timeout=timeout) as buffer:
                        if not buffer.module.is_complete():
                            raise RuntimeError("Transport buffer is incomplete")
                        (directory / "transport_payload.bin").write_bytes(bytes(buffer.module.raw_buffer))
                        if len(buffer.payload.components) != 1:
                            raise RuntimeError("Multipart payload requires explicit mapping")
                        component = buffer.payload.components[0]
                        values = component.data.copy()
                        fmt = component.data_format
                        color = fmt in ("RGB8", "BGR8")
                        if not color and not re.fullmatch(r"(?:Mono|Bayer(?:RG|GR|GB|BG))(?:8|10|12|14|16)(?:p|Packed)?", fmt):
                            np.save(directory / "unmapped_payload.npy", values, allow_pickle=False)
                            raise RuntimeError(f"Unmapped pixel format {fmt}; payload retained without invented axes")
                        if values.size != component.height * component.width * (3 if color else 1):
                            np.save(directory / "unmapped_payload.npy", values, allow_pickle=False)
                            raise RuntimeError("Payload size cannot map to one sensor plane")
                        raw_shape = (component.height, component.width, 3) if color else (component.height, component.width)
                        raw = values.reshape(raw_shape)
                        frame_id = buffer.frame_id
                        timestamp_ns = buffer.timestamp_ns
                        receipt.update(frame_id=frame_id, device_timestamp_ns=timestamp_ns,
                                       host_received_at=utc_now(), pixel_format=fmt,
                                       transport_pixel_format=fmt,
                                       stored_pixel_format="camera RGB/BGR output, not spectral channels" if color else "PFNC losslessly expanded single sensor plane; Bayer mosaic retained",
                                       effective_bits=int(re.search(r"\d+", fmt)[0]),
                                       shape=list(raw.shape), dtype=raw.dtype.str, axis_order="HWC" if color else "HW",
                                       axis_names=["y", "x", "color_channel"] if color else ["y", "x"],
                                       channel_labels=list(fmt[:3]) if color else None, valid=True,
                                       buffer_complete=True)
                        np.save(directory / "frame.npy", raw, allow_pickle=False)
                        from PIL import Image
                        if color:
                            display = raw if fmt == "RGB8" else raw[:, :, ::-1]
                        else:
                            low, high = np.percentile(raw, [1, 99])
                            display = np.zeros(raw.shape, dtype=np.uint8) if high <= low else (
                                np.clip((raw.astype(np.float32) - low) / (high - low), 0, 1) * 255).astype(np.uint8)
                        Image.fromarray(display).save(directory / "preview.png")
                        receipt["preview_processing"] = "camera RGB8 output, BGR reordered if needed; not colorimetric calibration" if color else "1-99 percentile stretch; Bayer mosaic left uninterpolated"
                finally:
                    try:
                        if started:
                            camera.stop()
                            receipt["stop_returned"] = True
                    finally:
                        restored = {}
                        for name, value in reversed(list(changed.items())):
                            getattr(nodes, name).value = value
                            restored[name] = {"readback": getattr(nodes, name).value, "expected": value}
                        receipt["settings_restored"] = restored
                        if any(item["readback"] != item["expected"] for item in restored.values()):
                            raise RuntimeError("Session settings restoration readback mismatch")
            receipt["device_released"] = True
        reloaded = np.load(directory / "frame.npy", mmap_mode="r", allow_pickle=False)
        if list(reloaded.shape) != receipt["shape"] or reloaded.dtype.str != receipt["dtype"]:
            raise RuntimeError("Saved frame shape/dtype mismatch")
        receipt.update(completed=True, partial=False, save_reopen_verified=True)
    except Exception as exc:
        receipt["error"] = str(exc)
        raise
    finally:
        if dll_dir:
            dll_dir.close()
        receipt["ended_at"] = utc_now()
        (directory / "frame.npy.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return directory / "frame.npy"
