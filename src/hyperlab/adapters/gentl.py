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
import time
import numpy as np
from hyperlab.acquisition.session import utc_now


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
        environment = {key: value for key, value in environment.items() if key.casefold() != "psmodulepath"}
    response = subprocess.run([shell, "-NoProfile", "-Command", command],
                              capture_output=True, text=True, encoding="utf-8", timeout=30, check=True, env=environment,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    signature = json.loads(response.stdout)
    if not signature["valid"] or not re.search(r"Balluff|MATRIX VISION", signature["signer"], re.I):
        raise ValueError("Installed producer signature is not valid for the reviewed OEM")
    return signature


FEATURES = (
    "Width", "Height", "OffsetX", "OffsetY", "ReverseX", "ReverseY", "PixelFormat",
    "PixelColorFilter", "mvSensorDigitizationBitDepth", "ExposureTime", "ExposureAuto",
    "ExposureMode", "Gain", "GainSelector", "GainAuto", "BalanceWhiteAuto", "BalanceRatioSelector",
    "BalanceRatio", "BlackLevel", "BlackLevelSelector", "BlackLevelAuto", "Gamma", "GammaEnable", "LUTEnable", "TriggerSelector", "TriggerMode",
    "TriggerSource", "AcquisitionMode", "AcquisitionFrameRate", "AcquisitionFrameRateEnable",
    "DeviceFirmwareVersion", "DeviceVersion", "TestPattern", "TestImageSelector", "ChunkModeActive",
)
AUTOMATIC = ("ExposureAuto", "GainAuto", "BalanceWhiteAuto", "BlackLevelAuto")
ESSENTIAL_FEATURES = ('Width', 'Height', 'PixelFormat', 'ExposureTime', 'Gain',
                      'AcquisitionMode', 'TriggerMode')


def _attribute(obj, name, default=None):
    try:
        return getattr(obj, name)
    except AttributeError:
        return default


def _json_scalar(value):
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value if isinstance(value, (str, bool, int, float, type(None))) else str(value)


class GenTLBackend:
    """One-thread Harvester lifecycle; no native calls outside its owner worker.

    Injection arguments are exclusively for offline contract tests. The normal
    path checks the installed producer once per connection and selects one serial.
    """

    def __init__(self, cti, serial, *, harvester_factory=None, producer_reviewer=None, node_api=None):
        if not serial:
            raise ValueError("An exact device serial is required")
        self.cti = Path(cti).resolve(strict=True)
        if self.cti.name != "mvGenTLProducer.cti":
            raise ValueError("Only the reviewed Balluff mvGenTLProducer.cti is supported")
        self.serial = serial
        self._factory = harvester_factory
        self._reviewer = producer_reviewer or _review_producer
        self._api = node_api
        self.harvester = self.camera = self.nodes = self.dll_dir = None
        self.start_attempted = False
        self.original = {}
        self.cleanup = []
        self.metadata = {}
        self.capabilities = {}
        self.requested = {}
        self.readback = {}
        self.failed_payload = None
        self.failed_frame_metadata = None
        self.owner = None
        self.node_evidence = {}

    def _owner(self):
        import threading
        current = threading.get_ident()
        if self.owner is None:
            self.owner = current
        if self.owner != current:
            raise RuntimeError("GenTL access is restricted to the camera owner thread")

    def open(self):
        self._owner()
        from importlib.metadata import version
        review = self._reviewer(self.cti)
        if self._factory is None:
            from harvesters.core import Harvester
            self._factory = Harvester
        if self._api is None:
            from genicam import genapi
            self._api = genapi
        self.metadata = {"serial": self.serial, "producer": str(self.cti), "producer_signature": review,
                         "runtime": {"harvesters": version("harvesters"), "genicam": version("genicam")}}
        if os.name == "nt":
            self.dll_dir = os.add_dll_directory(str(self.cti.parent))
        self.harvester = self._factory()
        self.harvester.add_file(str(self.cti), check_existence=True, check_validity=True)
        self.harvester.update()
        matches = [item for item in self.harvester.device_info_list if item.serial_number == self.serial]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one exact serial match; found {len(matches)}")
        info = matches[0]
        if "mvBlueFOX3" not in info.model or info.tl_type != "U3V":
            raise RuntimeError("Target is not the investigated mvBlueFOX3 USB3 Vision device")
        self.metadata.update(model=info.model, vendor=info.vendor, tl_type=info.tl_type)
        self.camera = self.harvester.create({"serial_number": self.serial})
        self.nodes = self.camera.remote_device.node_map
        self.capabilities = self.describe_nodes(names=ESSENTIAL_FEATURES)
        self.metadata["current_settings"] = self.read_settings(names=ESSENTIAL_FEATURES)
        return self.metadata

    def probe_node(self, name, *, required=False, describe=False, raise_read_error=False):
        """Unsupported, unavailable and transport/read errors are distinct."""
        stage = 'lookup'
        result = {'supported': False, 'readable': False, 'status': 'unsupported'}
        try:
            node = _attribute(self.nodes, name)
            if node is None:
                if required:
                    raise ValueError(f'Required node {name} is unsupported')
                return result
            stage = 'access'
            readable = bool(self._api.is_readable(node))
            result.update(supported=True, readable=readable,
                          status='value' if readable else 'unavailable')
            if not readable:
                if required:
                    raise ValueError(f'Required node {name} is unavailable')
                return result
            stage = 'value'
            result['value'] = _json_scalar(node.value)
            if describe:
                stage = 'description'
                result.update(self._describe(node))
            return result
        except Exception as exc:
            result.update(status='read_error', exception_type=type(exc).__name__,
                          read_error=str(exc), stage=stage)
            if required or raise_read_error:
                exc.add_note(f'Required GenICam read: {name}; stage={stage}')
                raise
            return result
        finally:
            self.node_evidence[name] = result

    def _describe(self, node):
        result = {"readable": bool(self._api.is_readable(node)), "writable": bool(self._api.is_writable(node))}
        descriptor = _attribute(node, "node", node)
        access_query = _attribute(descriptor, "get_access_mode")
        result["access"] = str(access_query() if access_query else _attribute(descriptor, "access_mode", "unknown"))
        result["node_type"] = type(node).__name__
        if result["readable"]:
            result["value"] = _json_scalar(_attribute(node, "value"))
        for name in ("min", "max", "unit"):
            result[name] = _json_scalar(_attribute(node, name))
        # GenApi 1.6 IFloat.has_inc() distinguishes continuous floats from a
        # fixed increment. GetInc() legitimately throws for continuous floats.
        has_inc = _attribute(node, 'has_inc')
        result['inc'] = None if has_inc is not None and not has_inc() else _json_scalar(_attribute(node, 'inc'))
        entries = _attribute(node, "entries")
        if entries is not None:
            result["entries"] = [str(entry.symbolic) for entry in entries if self._api.is_available(entry)]
        return result

    def describe_nodes(self, *, all_nodes=False, names=FEATURES):
        """Read feature descriptions without commands or selector changes."""
        self._owner()
        # genicam 1.6 NodeMap.nodes returns typed IValue/ICategory/IPort
        # interfaces; their INode name lives on the documented .node property.
        if all_nodes:
            candidates = {}
            for interface in self.nodes.nodes:
                descriptor = _attribute(interface, "node", interface)
                name = _attribute(descriptor, "name")
                if name is not None:
                    candidates[str(name)] = interface
        else:
            return {name: self.probe_node(name, required=name in ESSENTIAL_FEATURES, describe=True)
                    for name in names}
        result = {}
        for name, node in candidates.items():
            if node is None:
                continue
            # Command nodes have no sampled value; never call execute or is_done.
            if _attribute(node, "execute") is not None:
                result[name] = {"node_type": "command", "executed": False}
                continue
            if name not in FEATURES:
                # Arbitrary vendor nodes may read volatile registers or block
                # inside the native library. Enumerate cached type/name only;
                # sample values/access/ranges solely for the reviewed feature set.
                result[name] = {"node_type": type(node).__name__, "value_status": "NOT_READ_UNREVIEWED_NODE"}
                continue
            try:
                result[name] = self.probe_node(name, describe=True)
            except Exception as exc:
                result[name] = {"read_error": str(exc)}
        return result

    def read_settings(self, names=FEATURES):
        values = {}
        for name in names:
            evidence = self.probe_node(name, required=name in ESSENTIAL_FEATURES, raise_read_error=True)
            # Optional absence is safe to leave unknown. A failed communication
            # is never silently converted into an unsupported optional feature.
            values[name] = evidence.get('value')
        self.metadata['node_evidence'] = dict(self.node_evidence)
        return values

    def configure(self, settings, mode="measurement"):
        self._owner()
        if mode not in ("measurement", "preview"):
            raise ValueError("Choose measurement or preview configuration")
        allowed = {"PixelFormat", "ExposureTime", "Gain"}
        if set(settings) - allowed:
            raise ValueError("Only documented pixel format, exposure and gain controls are accepted")
        current = self.read_settings()
        for test_name in ("TestPattern", "TestImageSelector"):
            if current[test_name] not in (None, "Off"):
                raise RuntimeError(f"{test_name} is enabled; cannot label this a real scene")
        requested = {}
        qualification = []
        manual_unavailable = set()
        # Auto controls are disabled before setting manual values, and restored last.
        for name in AUTOMATIC:
            if mode == "measurement" or (name == "ExposureAuto" and "ExposureTime" in settings) or (name == "GainAuto" and "Gain" in settings):
                node = _attribute(self.nodes, name)
                if node is not None and self._api.is_writable(node):
                    requested[name] = "Off"
                elif current[name] not in (None, "Off"):
                    qualification.append(f'{name} remains active and cannot be frozen')
                    if name in ('ExposureAuto', 'GainAuto'):
                        manual_unavailable.add('ExposureTime' if name == 'ExposureAuto' else 'Gain')
                elif current[name] is None:
                    qualification.append(f'{name} state is unknown')
        if mode == "measurement":
            for name in ("GammaEnable", "LUTEnable"):
                node = _attribute(self.nodes, name)
                if node is not None and self._api.is_writable(node):
                    requested[name] = False
        requested.update({"AcquisitionMode": "Continuous", "TriggerMode": "Off"})
        requested.update({name: value for name, value in settings.items()
                          if value is not None and name not in manual_unavailable})
        self.requested = dict(requested)
        for name, value in requested.items():
            node = _attribute(self.nodes, name)
            if node is None:
                if name in ("AcquisitionMode", "TriggerMode") and current[name] in (None, value):
                    continue
                raise ValueError(f"{name} is not available on this device")
            before = _attribute(node, "value")
            if before == value:
                continue
            if not self._api.is_writable(node):
                raise ValueError(f"{name} is not writable in this session")
            description = self._describe(node)
            if "entries" in description and value not in description["entries"]:
                raise ValueError(f"{name} value is not in the available device enumeration")
            if name == "PixelFormat" and value not in ("RGB8", "BGR8", "BayerRG12", "Mono8", "Mono12", "Mono16"):
                raise ValueError("Pixel format lacks a reviewed lossless decoder")
            if name in ("ExposureTime", "Gain"):
                lower, upper, inc = description["min"], description["max"], description["inc"]
                if not np.isfinite(value) or lower is None or upper is None or not lower <= value <= upper:
                    raise ValueError(f"{name} outside current range [{lower}, {upper}]")
                if inc and not np.isclose((value - lower) / inc, round((value - lower) / inc), atol=1e-6):
                    raise ValueError(f"{name} does not match current increment {inc}")
            self.original.setdefault(name, before)
            node.value = value
            readback = _attribute(node, "value")
            if readback != value and not (isinstance(value, (float, int)) and isinstance(readback, (float, int)) and np.isclose(readback, value, rtol=1e-7, atol=1e-6)):
                raise RuntimeError(f"{name} readback differs from requested value")
        self.readback = self.read_settings()
        for name in ('GammaEnable', 'LUTEnable'):
            if self.readback.get(name) is not False:
                qualification.append(f'{name} is active or unknown')
        self.capabilities = self.describe_nodes()
        self.metadata.update(configuration_mode=mode, requested_settings=dict(self.requested),
                             readback_settings=dict(self.readback),
                             quantitative_eligible=not qualification and mode == 'measurement',
                             quantitative_limitations=qualification,
                             node_evidence=dict(self.node_evidence),
                             setting_evidence="session node readback; per-frame chunk evidence is separate")

    def start(self):
        self._owner()
        # GenTL defines zero as an immediate event check. Even a 1 ms Windows
        # native wait can starve UI NumPy work; Python owns the deadline/yield.
        self.camera.timeout_period_on_update_event_data_call = 0
        self.start_attempted = True  # Start can partially acquire resources before raising.
        self.camera.start(run_as_thread=False)

    def _wait_for_buffer(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('No camera buffer within the fetch deadline')
            buffer = self.camera.try_fetch(timeout=min(.001, remaining))
            if buffer is not None:
                return buffer
            # Cooperatively release Python between finite native polls.
            time.sleep(min(.001, max(0, deadline - time.monotonic())))

    def fetch(self, timeout=0.25, *, keep_transport=False):
        self._owner()
        from time import monotonic_ns
        buffer = self._wait_for_buffer(timeout)
        primary = None
        result = None
        try:
            received = monotonic_ns()
            received_utc = utc_now()
            payload = bytes(buffer.module.raw_buffer) if keep_transport else None
            if keep_transport:
                self.failed_payload = payload
            if not buffer.module.is_complete():
                raise RuntimeError("Transport buffer is incomplete")
            if len(buffer.payload.components) != 1:
                raise RuntimeError("Multipart payload requires explicit mapping")
            component = buffer.payload.components[0]
            fmt = str(component.data_format)
            color = fmt in ("RGB8", "BGR8")
            if not color and not re.fullmatch(r"(?:Mono|Bayer(?:RG|GR|GB|BG))(?:8|10|12|14|16)(?:p|Packed)?", fmt):
                raise RuntimeError(f"Unmapped pixel format {fmt}")
            values = component.data.copy()
            shape = (component.height, component.width, 3) if color else (component.height, component.width)
            if values.size != int(np.prod(shape)):
                raise RuntimeError("Payload size cannot map to one sensor frame")
            raw = values.reshape(shape)
            chunk = {}
            if self.readback.get("ChunkModeActive") is True:
                for name in ("ChunkExposureTime", "ChunkGain", "ChunkFrameID", "ChunkTimestamp"):
                    value = _attribute(_attribute(self.nodes, name), "value")
                    if value is not None:
                        chunk[name] = _json_scalar(value)
            metadata = dict(self.metadata, frame_id=_json_scalar(_attribute(buffer, "frame_id")),
                            device_timestamp_ns=_json_scalar(_attribute(buffer, "timestamp_ns")),
                            host_monotonic_ns=received, host_utc=received_utc, host_received_at=received_utc,
                            pixel_format=fmt, transport_pixel_format=fmt,
                            effective_bits=int(re.search(r"\d+", fmt)[0]), container_bits=raw.dtype.itemsize * 8,
                            adc_bits=self.readback.get("mvSensorDigitizationBitDepth"),
                            shape=list(shape), dtype=raw.dtype.str, axis_order="HWC" if color else "HW",
                            axis_names=["y", "x", "color_channel"] if color else ["y", "x"],
                            channel_labels=list(fmt[:3]) if color else None,
                            cfa_pattern={"RG": "RGGB", "GR": "GRBG", "GB": "GBRG", "BG": "BGGR"}.get(fmt[5:7]) if fmt.startswith("Bayer") else None,
                            cfa_pattern_origin="delivered", cfa_offset=[0, 0], flip_x=False, flip_y=False,
                            sensor_roi_offset=[self.readback.get("OffsetX"), self.readback.get("OffsetY")],
                            exposure_us=self.readback.get("ExposureTime"), gain=self.readback.get("Gain"),
                            chunk_settings=chunk, valid=True, buffer_complete=True,
                            acquisition_source="LIVE", data_source="LIVE", display_mode="LIVE", data_level="raw_frame",
                            synthetic=False, wavelengths=None, units="DN", calibration_source=None,
                            processing_steps=[], scene_validation="NOT_TESTED")
            result = (raw, metadata, payload)
        except Exception as exc:
            primary = exc
            # A failed buffer never enters the valid prefix. Retain its transport
            # bytes/identity separately when accessible, after this finite copy.
            if self.failed_payload is None:
                try:
                    self.failed_payload = bytes(buffer.module.raw_buffer)
                except Exception:
                    pass
            self.failed_frame_metadata = {
                "host_monotonic_ns": received, "host_utc": received_utc,
                "valid": False, "error": str(exc), "acquisition_source": "LIVE"}
            for attribute, key in (("frame_id", "frame_id"), ("timestamp_ns", "device_timestamp_ns")):
                try:
                    self.failed_frame_metadata[key] = _json_scalar(_attribute(buffer, attribute))
                except Exception as identity_error:
                    self.failed_frame_metadata[key] = None
                    self.failed_frame_metadata[key + "_read_error"] = f"{type(identity_error).__name__}: {identity_error}"
                    primary.add_note(f"Failed buffer identity read also failed: {identity_error}")
        finally:
            try:
                buffer.queue()
            except Exception as exc:
                if primary is None:
                    primary = exc
                else:
                    primary.add_note(f"Buffer requeue also failed: {exc}")
                self.cleanup.append({"step": "buffer_requeue", "attempted": True, "succeeded": False, "error": str(exc)})
        if primary is not None:
            raise primary
        self.failed_payload = None
        self.failed_frame_metadata = None
        return result

    def _attempt(self, name, operation, *, expected=None):
        event = {"step": name, "attempted": True, "succeeded": False}
        if expected is not None:
            event["expected"] = expected
        try:
            readback = operation()
            if expected is not None:
                event["readback"] = _json_scalar(readback)
                if readback != expected:
                    raise RuntimeError("Restoration readback mismatch")
            event["succeeded"] = True
        except Exception as exc:
            event["error"] = str(exc)
        self.cleanup.append(event)
        return event["succeeded"]

    def stop_restore(self):
        self._owner()
        beginning = len(self.cleanup)
        if self.camera is not None and self.start_attempted:
            if self._attempt("stop", self.camera.stop):
                self.start_attempted = False
        # Selectors are never changed. Restore format before dependent numeric
        # ranges, then manual values, and only then re-enable auto controls.
        order = [name for name in reversed(self.original) if name not in AUTOMATIC]
        if "PixelFormat" in order:
            order.remove("PixelFormat")
            order.insert(0, "PixelFormat")
        order += [name for name in AUTOMATIC if name in self.original]
        for name in order:
            expected = self.original[name]
            def restore(name=name, expected=expected):
                node = getattr(self.nodes, name)
                node.value = expected
                return node.value
            if self._attempt(f"restore:{name}", restore, expected=expected):
                del self.original[name]
        return self.cleanup[beginning:]

    def close(self):
        self._owner()
        beginning = len(self.cleanup)
        self.stop_restore()
        if self.camera is not None:
            self._attempt("destroy", self.camera.destroy)
            self.camera = None
        if self.harvester is not None:
            self._attempt("harvester_reset", self.harvester.reset)
            self.harvester = None
        if self.dll_dir is not None:
            self._attempt("dll_directory_close", self.dll_dir.close)
            self.dll_dir = None
        return self.cleanup[beginning:]


def capture_single(cti, serial, output, *, timeout=5, pixel_format=None, exposure_us=None, gain=None):
    """Legacy single-frame API over the same lifecycle and owned buffer decoder."""
    if not 0 < timeout <= 30:
        raise ValueError("Timeout must be in (0,30] seconds")
    from uuid import uuid4
    from hyperlab.acquisition.frame import Frame, save_frame
    directory = Path(output)
    if directory.exists():
        raise FileExistsError(directory)
    backend = GenTLBackend(cti, serial)
    receipt = {"data_source": "LIVE", "acquisition_source": "LIVE", "data_level": "raw_frame",
               "synthetic": False, "completed": False, "partial": True, "started_at": utc_now()}
    primary = None
    path = None
    try:
        backend.open()
        settings = {name: value for name, value in {"PixelFormat": pixel_format,
                    "ExposureTime": exposure_us, "Gain": gain}.items() if value is not None}
        backend.configure(settings, mode="measurement")
        backend.start()
        raw, metadata, payload = backend.fetch(timeout, keep_transport=True)
        metadata.update(session_id=str(uuid4()), sequence=0, started_at=receipt["started_at"])
        # No borrowed transport buffer survives fetch; disk, PNG and statistics
        # below operate only on an owned Frame.
        frame = Frame(raw, metadata)
        path = save_frame(directory, frame, transport_payload=payload)
        receipt.update(json.loads(path.with_suffix(".npy.json").read_text(encoding="utf-8")))
    except Exception as exc:
        primary = exc
        receipt.update(error=str(exc), primary_error=str(exc), completed=False, partial=True)
    finally:
        backend.close()
        cleanup = backend.cleanup
        failures = [entry for entry in cleanup if not entry["succeeded"]]
        receipt.update(cleanup=cleanup, cleanup_errors=failures, ended_at=utc_now(),
                       stop_returned=any(item["step"] == "stop" and item["succeeded"] for item in cleanup),
                       device_released=any(item["step"] == "destroy" and item["succeeded"] for item in cleanup),
                       settings_restored={item["step"].split(":", 1)[1]: item for item in cleanup if item["step"].startswith("restore:")})
        if failures:
            receipt.update(completed=False, partial=True)
            if primary is None:
                primary = RuntimeError("Acquisition cleanup failed; inspect cleanup_errors")
                receipt["error"] = str(primary)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            if backend.failed_payload is not None:
                (directory / "failed_transport_payload.bin").write_bytes(backend.failed_payload)
            (directory / "frame.npy.json").write_text(json.dumps(receipt, indent=2, allow_nan=False), encoding="utf-8")
        except Exception as write_error:
            if primary is None:
                primary = write_error
            else:
                primary.add_note(f"Final receipt also failed: {write_error}")
    if primary is not None:
        raise primary
    return path
