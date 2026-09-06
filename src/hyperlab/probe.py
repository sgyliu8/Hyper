"""Read-only Windows inventory and conservative static interface classification."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any


def load_snapshot(path: str | Path) -> dict[str, Any]:
    """Load a probe snapshot, including the Windows UTF-8 BOM if present."""
    snapshot = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise ValueError("Unsupported device snapshot schema")
    if not isinstance(snapshot.get("devices"), list):
        raise ValueError("Snapshot devices must be a list")
    ids = []
    for device in snapshot["devices"]:
        if not isinstance(device, dict) or not isinstance(device.get("instance_id"), str):
            raise ValueError("Every device needs a string instance_id")
        ids.append(device["instance_id"].casefold())
    if len(ids) != len(set(ids)):
        raise ValueError("Snapshot contains duplicate device instance IDs")
    return snapshot


def run_inventory(output: str | Path | None = None) -> Path:
    """Run only the inventory script; return its private snapshot path."""
    if os.name != "nt":
        raise RuntimeError("Live device inventory requires Windows")
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        raise RuntimeError("PowerShell is unavailable")
    from importlib.resources import as_file, files
    from datetime import datetime, timezone
    from .paths import workspace
    output = Path(output).resolve() if output is not None else workspace()/'diagnostics'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() != "PSMODULEPATH" or Path(shell).stem.lower() == "pwsh"}
    with as_file(files('hyperlab.resources').joinpath('Probe-Devices.ps1')) as script:
        command = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                   '-OutputDirectory', str(output)]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                                env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError(f"Read-only inventory failed: {result.stderr.strip()}")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Read-only inventory returned no snapshot path")
    path = Path(lines[-1])
    load_snapshot(path)
    return path


def _identity_text(device: dict[str, Any]) -> str:
    return " ".join(str(device.get(key, "")) for key in (
        "friendly_name", "manufacturer", "bus_reported_description", "instance_id"
    ))


def candidates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return identity leads, never automatic acquisition targets.

    The observed Matrix Vision VID/PID is an imaging-module lead; the NXP
    serial bridge is a separate unassociated control lead. A USB capture
    dongle or laptop camera is not evidence of a HinaLea camera.
    """
    found = []
    for device in snapshot.get("devices", []):
        text = _identity_text(device)
        if device.get("present", True) is False or re.search(r"UGREEN", text, re.I):
            continue
        role = None
        if re.search(r"HinaLea|TruScope|TruTag", text, re.I):
            role = "vendor_identity_lead"
        elif (str(device.get("vid", "")).upper(), str(device.get("pid", "")).upper()) == ("164C", "5533"):
            role = "matrix_vision_imaging_module_lead"
        elif (str(device.get("vid", "")).upper(), str(device.get("pid", "")).upper()) == ("1FC9", "0003"):
            role = "nxp_serial_control_lead_unassociated"
        if role:
            found.append({"device": device, "role": role, "identity_status": "IDENTITY_UNCONFIRMED", "acquisition_verified": False})
    return found


def select_device(snapshot: dict[str, Any], instance_id: str) -> dict[str, Any]:
    """Require the complete ID of an inventory candidate, without opening it."""
    matches = [entry["device"] for entry in candidates(snapshot) if entry["device"]["instance_id"].casefold() == instance_id.casefold()]
    if len(matches) != 1:
        raise ValueError("Device ID must exactly match one present instrument identity lead; indexes and arbitrary cameras are not accepted")
    return matches[0]


def standard_interfaces(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Classify static evidence only. This does not load a CTI or DLL."""
    result = []
    leads = {entry["device"]["instance_id"]: entry["role"] for entry in candidates(snapshot)}
    for device in snapshot.get("devices", []):
        if device.get("present", True) is False:
            continue
        driver = device.get("driver") or {}
        classes = {str(entry.get("class", "")).upper() for entry in device.get("usb_class_descriptors", [])}
        service = str(driver.get("service", "unknown")).casefold()
        interfaces = []
        if "0E" in classes or service == "usbvideo":
            interfaces.append("UVC_descriptor_or_driver_evidence")
        if device.get("class") == "Ports" or service == "usbser":
            interfaces.append("serial_present_protocol_unknown")
        if "03" in classes or service == "hidusb":
            interfaces.append("HID_present_protocol_unknown")
        if service == "winusb":
            interfaces.append("WinUSB_present_protocol_unknown")
        if any(str(entry.get("class", "")).upper() == "EF" and str(entry.get("subclass", "")).upper() == "05" for entry in device.get("usb_class_descriptors", [])):
            interfaces.append("USB3_Vision_descriptor_lead_not_runtime_validation")
        if device["instance_id"] in leads or interfaces:
            result.append({
                "instance_id": device["instance_id"], "friendly_name": device.get("friendly_name", "unknown"),
                "instrument_lead": leads.get(device["instance_id"]), "interfaces": interfaces or ["unknown"],
                "problem_code": device.get("problem_code", "unknown"),
                "ready_for_acquisition": False, "reason": "Static inventory does not verify physical identity, runtime, or control protocol",
            })
    for artifact in snapshot.get("artifacts", []):
        if str(artifact.get("path", "")).lower().endswith(".cti"):
            result.append({"path": artifact["path"], "interfaces": ["GenTL_producer_file_unloaded"], "architecture": artifact.get("architecture", "unknown"), "ready_for_acquisition": False})
    return result


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Compare device snapshots; added IDs are evidence, not identity proof."""
    before = {device["instance_id"].casefold(): device for device in old.get("devices", [])}
    after = {device["instance_id"].casefold(): device for device in new.get("devices", [])}
    changed = []
    for key in sorted(before.keys() & after.keys()):
        fields = {field: {"before": before[key].get(field), "after": after[key].get(field)} for field in sorted(before[key].keys() | after[key].keys()) if field != "instance_id" and before[key].get(field) != after[key].get(field)}
        if fields:
            changed.append({"instance_id": after[key]["instance_id"], "fields": fields})
    return {
        "added": [after[key] for key in sorted(after.keys() - before.keys())],
        "removed": [before[key] for key in sorted(before.keys() - after.keys())],
        "changed": changed,
        "physical_identity_confirmed": False,
        "note": "Cable-change observations require the user's known physical action and must not assume separate USB devices share an instrument.",
    }
