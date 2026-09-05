"""Fail-closed CLI gates use fictitious inventory and never import a live runtime."""

import builtins
import json

import pytest

from hyperlab.__main__ import main
import hyperlab.probe as probe


IMAGING_ID = r"USB\VID_164C&PID_5533&MI_00\SYNTHETIC_INTERFACE"
PARENT_ID = r"USB\VID_164C&PID_5533\SYNTHETIC_PARENT"
SERIAL_ID = r"USB\VID_1FC9&PID_0003\SYNTHETIC_SERIAL_BRIDGE"


@pytest.fixture
def offline_cli(monkeypatch, tmp_path):
    """No real inventory, registry, serial port, CTI or capture API can be reached."""
    snapshot = {
        "schema_version": 1,
        "devices": [
            {"instance_id": IMAGING_ID, "vid": "164C", "pid": "5533",
             "present": True, "problem_code": 28, "parent": PARENT_ID,
             "friendly_name": "SYNTHETIC mvBlueFOX3 test interface"},
            {"instance_id": PARENT_ID, "vid": "164C", "pid": "5533",
             "present": True, "problem_code": 0,
             "bus_reported_description": "mvBlueFOX3 SYNTHETIC fixture"},
            {"instance_id": SERIAL_ID, "vid": "1FC9", "pid": "0003",
             "present": True, "problem_code": 0, "class": "Ports",
             "friendly_name": "SYNTHETIC serial fixture"},
        ],
    }
    path = tmp_path / "synthetic_snapshot.json"
    state = {"inventory_calls": 0, "forbidden_imports": [], "snapshot": snapshot}

    def fake_inventory(*args, **kwargs):
        state["inventory_calls"] += 1
        path.write_text(json.dumps(snapshot), encoding="utf-8")
        return path

    monkeypatch.setattr(probe, "run_inventory", fake_inventory)
    original_import = builtins.__import__

    def reject_live_import(name, *args, **kwargs):
        if name == "hyperlab.adapters.gentl" or name.split(".")[0] in {
            "harvesters", "genicam", "winreg", "serial"
        }:
            state["forbidden_imports"].append(name)
            raise AssertionError(f"Offline gate test attempted live import: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_live_import)

    def reject_subprocess(*args, **kwargs):
        raise AssertionError("Offline CLI gate test attempted a system subprocess")

    monkeypatch.setattr(probe.subprocess, "run", reject_subprocess)
    return state


@pytest.mark.parametrize("problem_code", [28, 10, None, "0"])
def test_driver_problem_refused_before_live_import(offline_cli, capsys, tmp_path, problem_code):
    offline_cli["snapshot"]["devices"][0]["problem_code"] = problem_code
    result = main(["acquire", "--device", IMAGING_ID, "--single-frame", "--cti",
                   str(tmp_path / "reviewed_runtime" / "mvGenTLProducer.cti")])
    assert result == 2
    assert "Windows problem code" in capsys.readouterr().err
    assert offline_cli["inventory_calls"] == 1
    assert offline_cli["forbidden_imports"] == []


def test_recipe_refused_before_inventory_or_live_import(offline_cli, capsys):
    result = main(["acquire", "--device", IMAGING_ID, "--recipe", "SYNTHETIC_UNVERIFIED_RECIPE"])
    assert result == 2
    assert "scan protocol" in capsys.readouterr().err
    assert offline_cli["inventory_calls"] == 0
    assert offline_cli["forbidden_imports"] == []


@pytest.mark.parametrize("device_id", [SERIAL_ID, PARENT_ID])
def test_serial_or_composite_parent_is_not_imaging_target(offline_cli, capsys, device_id):
    result = main(["acquire", "--device", device_id, "--single-frame"])
    assert result == 2
    assert "not the serial or composite parent" in capsys.readouterr().err
    assert offline_cli["forbidden_imports"] == []


def test_missing_explicit_operation_is_rejected_before_inventory(offline_cli, capsys):
    assert main(["acquire", "--device", IMAGING_ID]) == 2
    assert "Specify --single-frame" in capsys.readouterr().err
    assert offline_cli["inventory_calls"] == 0


def test_arbitrary_index_never_selects_a_camera(offline_cli, capsys):
    assert main(["acquire", "--device", "0", "--single-frame"]) == 2
    assert "exactly match" in capsys.readouterr().err
    assert offline_cli["forbidden_imports"] == []


def test_healthy_interface_still_requires_explicit_reviewed_cti(offline_cli, capsys):
    offline_cli["snapshot"]["devices"][0]["problem_code"] = 0
    assert main(["acquire", "--device", IMAGING_ID, "--single-frame"]) == 2
    assert "Explicit --cti is required" in capsys.readouterr().err
    assert offline_cli["forbidden_imports"] == []


def test_unconfirmed_parent_blocks_live_runtime(offline_cli, capsys, tmp_path):
    offline_cli["snapshot"]["devices"][0]["problem_code"] = 0
    offline_cli["snapshot"]["devices"][1]["bus_reported_description"] = "Unknown SYNTHETIC device"
    result = main(["acquire", "--device", IMAGING_ID, "--single-frame", "--cti",
                   str(tmp_path / "reviewed_runtime" / "mvGenTLProducer.cti")])
    assert result == 2
    assert "parent identity is unconfirmed" in capsys.readouterr().err
    assert offline_cli["forbidden_imports"] == []
