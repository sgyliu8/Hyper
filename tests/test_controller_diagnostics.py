import json
from pathlib import Path

import pytest

from hyperlab.controller import diagnostics as d


def test_topology_does_not_promote_shared_container_or_com_to_identity():
    imaging = {"instance_id": "USB\\VID_164C&PID_5533\\test", "vid": "164C", "pid": "5533", "container_id": "same", "parent": "USB\\HUB"}
    serial = {"instance_id": "USB\\VID_1FC9&PID_0003\\test", "vid": "1FC9", "pid": "0003", "friendly_name": "COM19", "container_id": "same"}
    result = d.topology({"devices": [imaging, serial, {"instance_id": "USB\\HUB"}]})
    assert result["physical_association"] == "UNKNOWN"
    assert result["controller_protocol"] == "UNKNOWN"
    assert len(result["devices_and_available_ancestors"]) == 3


def test_scoped_search_preserves_leads_and_excludes_acquisition_trees(tmp_path):
    vendor = tmp_path / "TruScope"
    vendor.mkdir()
    (vendor / "response_matrix.cal").write_text("HinaLea calibration candidate")
    raw = vendor / "acquisitions"
    raw.mkdir()
    (raw / "recipe.json").write_text("private raw measurement")
    result = d.search_assets([vendor])
    assert result["files_examined"] == 1
    assert len(result["matches"]) == 1
    assert not result["matches"][0]["abi_verified"]
    assert not result["matches"][0]["executed"]


def test_broad_and_measurement_roots_are_rejected(tmp_path):
    for path in (Path.home(), Path(Path.home().anchor), tmp_path / "acquisitions", tmp_path / "local"):
        with pytest.raises(ValueError):
            d.validate_asset_root(path)


def test_asset_budget_reports_partial_scope(tmp_path):
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    for number in range(3):
        (vendor / f"recipe_{number}.json").write_text("{}")
    result = d.search_assets([vendor], max_files=1)
    assert result["files_examined"] == 1
    assert result["scopes"][0]["truncated"]


def test_snapshot_reuse_never_invokes_device_inventory_and_preserves_receipt(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"schema_version": 1, "devices": []}))
    monkeypatch.setattr(d, "run_inventory", lambda _: pytest.fail("Device inventory must not be invoked"))
    monkeypatch.setattr(d, "installation_records", lambda: [])
    monkeypatch.setattr(d, "discover_asset_roots", lambda _: ([], [], [], []))
    output = tmp_path / "receipt"
    path = d.collect_diagnostics(output, snapshot)
    result = json.loads(path.read_text())
    assert not any(result["actions"].values())
    assert result["protocol_status"] == "NOT_ESTABLISHED"
    with pytest.raises(FileExistsError):
        d.collect_diagnostics(output, snapshot)
