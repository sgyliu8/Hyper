"""Bounded, read-only controller asset and topology investigation.

Run explicitly, separately from normal device refresh. No native library imports,
serial ports, device writes, command execution or calibration inference occur.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import struct
from typing import Any

from hyperlab.probe import candidates, load_snapshot, run_inventory

VENDOR = re.compile(r"HinaLea|TruTag|TruScope|Balluff|MATRIX.?VISION|mvIMPACT|Impact.?Acquire", re.I)
ASSET = re.compile(r"HinaLea|TruTag|TruScope|4200|4250|calibrat|response.?matrix|reconstruct|recipe|(?:^|[_ .-])gap(?:[_ .-]|$)", re.I)
SKIP = {"acquisitions", "diagnostics", ".venv", "node_modules", ".git", "__pycache__"}
STATIC_EXT = {".dll", ".exe", ".cti", ".h", ".hpp", ".xml", ".ini", ".json", ".cal", ".cfg", ".lut", ".txt", ".pdf"}


def _linked(path: Path) -> bool:
    # Path.is_junction is unavailable on the supported Python 3.11.
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def topology(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Preserve leads and parent evidence without promoting association to fact."""
    leads = candidates(snapshot)
    wanted = {entry["device"]["instance_id"].casefold() for entry in leads}
    by_id = {d["instance_id"].casefold(): d for d in snapshot["devices"]}
    pending = list(wanted)
    while pending:
        parent = str(by_id.get(pending.pop(), {}).get("parent", "")).casefold()
        if parent in by_id and parent not in wanted:
            wanted.add(parent)
            pending.append(parent)
    return {"snapshot_captured_at": snapshot.get("captured_at"), "leads": leads,
            "devices_and_available_ancestors": [by_id[k] for k in sorted(wanted)],
            "physical_association": "UNKNOWN", "controller_protocol": "UNKNOWN",
            "descriptor_scope": "Windows PnP properties and compatible IDs; not raw endpoint reads",
            "note": "Shared or different host paths/containers do not prove chassis or cable identity. COM numbering is transient."}


def installation_records() -> list[dict[str, Any]]:
    """Read uninstall registry records; never use Win32_Product repair queries."""
    if os.name != "nt":
        return []
    import winreg
    records = []
    for hive, hive_name in ((winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU")):
        for prefix in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
            try:
                with winreg.OpenKey(hive, prefix) as root:
                    for i in range(winreg.QueryInfoKey(root)[0]):
                        name = winreg.EnumKey(root, i)
                        try:
                            with winreg.OpenKey(root, name) as item:
                                fields = {}
                                for field in ("DisplayName", "DisplayVersion", "Publisher", "InstallLocation", "DisplayIcon"):
                                    try:
                                        fields[field] = winreg.QueryValueEx(item, field)[0]
                                    except OSError:
                                        pass
                                if VENDOR.search(str(fields.get("DisplayName", ""))):
                                    records.append({"registry_key": f"{hive_name}\\{prefix}\\{name}", **fields})
                        except OSError:
                            continue
            except OSError:
                continue
    return records


def _broad_roots() -> set[Path]:
    paths = {Path.home(), Path.home() / "Downloads"}
    paths.update(Path(os.environ[key]) for key in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData", "LOCALAPPDATA", "APPDATA", "WINDIR") if os.environ.get(key))
    return {p.resolve() for p in paths}


def validate_asset_root(path: str | Path) -> Path:
    original = Path(path)
    if original.exists() and _linked(original):
        raise ValueError("Linked/reparse asset roots are excluded")
    root = Path(path).resolve()
    if str(root).startswith("\\\\") or root == Path(root.anchor) or root in _broad_roots():
        raise ValueError("Asset root must be a specific local vendor/backup folder, not a broad system/user root")
    if any(part.casefold() in SKIP for part in root.parts) or root.name.casefold() == "local":
        raise ValueError("Acquisition, diagnostics, environment and broad project local folders are excluded")
    return root


def discover_asset_roots(records: list[dict[str, Any]]) -> tuple[list[Path], list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    roots: set[Path] = set()
    hits, warnings, listings = [], [], []
    for base in sorted(_broad_roots() - {Path.home().resolve(), Path(os.environ.get("WINDIR", "__absent__")).resolve()}):
        listing = {"root": str(base), "exists": base.is_dir(), "depth": 1, "entries_examined": 0}
        listings.append(listing)
        if not base.is_dir():
            continue
        try:
            for entry in base.iterdir():
                listing["entries_examined"] += 1
                if _linked(entry):
                    continue
                if entry.is_dir() and VENDOR.search(entry.name):
                    roots.add(entry.resolve())
                elif entry.is_file() and ASSET.search(entry.name):
                    hits.append({"path": str(entry), "bytes": entry.stat().st_size, "reason": "top_level_filename_lead", "executed": False})
        except OSError as exc:
            warnings.append(f"Top-level listing unavailable: {base}: {exc}")
    for entry in records:
        location = entry.get("InstallLocation")
        if location:
            try:
                roots.add(validate_asset_root(location))
            except ValueError as exc:
                warnings.append(f"Rejected registry root: {exc}")
    return sorted(roots), hits, warnings, listings


def static_metadata(path: Path) -> dict[str, Any]:
    """Read bounded bytes only, never load binary or infer an ABI from names."""
    result: dict[str, Any] = {"path": str(path), "bytes": path.stat().st_size, "executed": False}
    with path.open("rb") as stream:
        content = stream.read(2 * 1024 * 1024)
    result["bytes_examined"] = len(content)
    result["static_read_truncated"] = result["bytes"] > len(content)
    if content.startswith(b"MZ") and len(content) >= 64:
        offset = struct.unpack_from("<I", content, 60)[0]
        if offset + 6 <= len(content) and content[offset:offset + 4] == b"PE\0\0":
            machine = struct.unpack_from("<H", content, offset + 4)[0]
            result["architecture"] = {0x8664: "x64", 0x14c: "x86", 0xaa64: "arm64"}.get(machine, "unknown")
    strings = re.findall(rb"[\x20-\x7e]{6,256}", content)
    result["keyword_strings"] = [s.decode("ascii") for s in strings if ASSET.search(s.decode("ascii"))][:30]
    result["abi_verified"] = False
    return result


def search_assets(roots: list[Path], *, max_files: int = 20000, max_depth: int = 8) -> dict[str, Any]:
    matches, scopes, warnings = [], [], []
    examined = 0
    for requested in roots:
        root = validate_asset_root(requested)
        scope = {"root": str(root), "exists": root.is_dir(), "files_examined": 0, "truncated": False}
        scopes.append(scope)
        if not root.is_dir():
            continue
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=lambda e: warnings.append(str(e))):
            here = Path(directory)
            dirs[:] = [d for d in dirs if d.casefold() not in SKIP and not _linked(here / d)]
            if len(here.relative_to(root).parts) >= max_depth:
                if dirs:
                    scope["truncated"] = True
                dirs[:] = []
            for name in files:
                if examined >= max_files:
                    scope["truncated"] = True
                    break
                examined += 1
                scope["files_examined"] += 1
                path = here / name
                if _linked(path) or not ASSET.search(name):
                    continue
                try:
                    info = static_metadata(path) if path.suffix.lower() in STATIC_EXT else {"path": str(path), "bytes": path.stat().st_size, "executed": False}
                    matches.append({**info, "reason": "scoped_filename_lead", "root": str(root)})
                except OSError as exc:
                    warnings.append(f"Static read unavailable: {path}: {exc}")
            if examined >= max_files:
                break
    return {"scopes": scopes, "matches": matches, "files_examined": examined, "max_files": max_files,
            "max_depth": max_depth, "warnings": warnings}


def collect_diagnostics(output: str | Path, snapshot_path: str | Path | None = None,
                        asset_roots: tuple[str | Path, ...] = ()) -> Path:
    destination = Path(output).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    result_path = destination / "scanner_report.json"
    if result_path.exists():
        raise FileExistsError("Diagnostics already exist; choose a fresh output directory")
    snapshot_path = Path(snapshot_path) if snapshot_path else run_inventory(destination / "pnp")
    snapshot = load_snapshot(snapshot_path)
    records = installation_records()
    roots, named_hits, warnings, listings = discover_asset_roots(records)
    roots = sorted(set(roots) | {validate_asset_root(p) for p in asset_roots})
    report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "mode": "controller_diagnostics_read_only", "snapshot": str(snapshot_path.resolve()),
              "topology": topology(snapshot), "installed_software": records,
              "top_level_search_scope": listings, "top_level_filename_leads": named_hits,
              "assets": search_assets(roots), "warnings": warnings,
              "genicam_node_dump": {"status": "NOT_TESTED", "reason": "Separate authorized camera session must supply read-only nodes; this entry point does not load CTI"},
              "protocol_status": "NOT_ESTABLISHED", "calibration_status": "NOT_ESTABLISHED",
              "actions": {"serial_ports_opened": False, "cti_loaded": False, "device_writes": False,
                          "binaries_executed": False, "full_disk_search": False},
              "limitations": ["Filename matches are leads, not protocol or calibration verification", "No supplied university/old-disk backup path", "No DTR/RTS/serial probe", "No absence claim outside recorded search scopes"]}
    with result_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
    return result_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Fresh private local diagnostics directory")
    parser.add_argument("--snapshot", help="Reuse a PnP snapshot instead of querying Windows")
    parser.add_argument("--asset-root", action="append", default=[], help="Specific authorized vendor/backup folder; never a whole drive")
    args = parser.parse_args()
    print(collect_diagnostics(args.output, args.snapshot, tuple(args.asset_root)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
