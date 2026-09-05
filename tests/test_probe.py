import json

import pytest

from hyperlab.probe import candidates, diff, load_snapshot, select_device, standard_interfaces


def snapshot(*devices, artifacts=None):
    return {"schema_version": 1, "devices": list(devices), "artifacts": artifacts or []}


def device(instance_id="USB\\VID_164C&PID_5533&MI_00\\PRIVATE", **changes):
    result = {"instance_id": instance_id, "vid": "164C", "pid": "5533", "present": True, "friendly_name": "mvBlueFOX3-M2024C", "problem_code": 28, "class": "unknown", "driver": {"service": "unknown"}, "usb_class_descriptors": []}
    result.update(changes)
    return result


def test_bom_snapshot_and_no_devices(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot()), encoding="utf-8-sig")
    parsed = load_snapshot(path)
    assert candidates(parsed) == []
    assert standard_interfaces(parsed) == []
    with pytest.raises(ValueError, match="exactly match"):
        select_device(parsed, "0")


@pytest.mark.parametrize("content", [{"devices": []}, {"schema_version": 1, "devices": {}}, snapshot({"friendly_name": "no id"}), snapshot(device(), device())])
def test_reject_malformed_or_duplicate_snapshots(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(content))
    with pytest.raises(ValueError):
        load_snapshot(path)


def test_select_exact_candidate_never_arbitrary_camera_or_dongle():
    camera = device()
    arbitrary = device("USB\\VID_1234&PID_0000\\LAPTOP", vid="1234", pid="0000", friendly_name="Integrated Camera", **{"class": "Camera"})
    dongle = device("USB\\VID_1234&PID_9999\\DONGLE", friendly_name="UGREEN HinaLea USB Capture", vid="1234", pid="9999")
    data = snapshot(camera, arbitrary, dongle)
    assert len(candidates(data)) == 1
    assert select_device(data, camera["instance_id"].lower()) == camera
    for value in ["0", "mvBlueFOX3-M2024C", arbitrary["instance_id"], dongle["instance_id"]]:
        with pytest.raises(ValueError):
            select_device(data, value)


def test_nxp_remains_separate_unassociated_and_not_opened():
    serial = device("USB\\VID_1FC9&PID_0003\\PRIVATE", vid="1FC9", pid="0003", friendly_name="LPC13xx VCOM (COM4)", problem_code=0, driver={"service": "usbser"}, **{"class": "Ports"})
    data = snapshot(device(), serial)
    assert candidates(data)[1]["role"] == "nxp_serial_control_lead_unassociated"
    interfaces = standard_interfaces(data)
    assert interfaces[1]["interfaces"] == ["serial_present_protocol_unknown"]
    assert all(not item["ready_for_acquisition"] for item in interfaces)


def test_standard_descriptors_and_cti_are_static_leads_only():
    uvc = device("USB\\OTHER", vid="1234", pid="1234", usb_class_descriptors=[{"class": "0E"}], friendly_name="USB Video")
    vision = device(usb_class_descriptors=[{"class": "EF", "subclass": "05", "protocol": "01"}])
    results = standard_interfaces(snapshot(uvc, vision, artifacts=[{"path": "C:/local/vendor.cti", "architecture": "x64"}]))
    assert results[0]["interfaces"] == ["UVC_descriptor_or_driver_evidence"]
    assert results[0]["instrument_lead"] is None
    assert "USB3_Vision_descriptor_lead_not_runtime_validation" in results[1]["interfaces"]
    assert results[2]["interfaces"] == ["GenTL_producer_file_unloaded"]
    assert all(not item["ready_for_acquisition"] for item in results)


def test_absent_devices_are_not_candidates():
    assert candidates(snapshot(device(present=False))) == []
    assert standard_interfaces(snapshot(device(present=False))) == []


def test_usb3_vision_class_and_subclass_must_share_a_descriptor():
    unrelated_classes = device(usb_class_descriptors=[{"class": "EF", "subclass": "01"}, {"class": "03", "subclass": "05"}])
    assert standard_interfaces(snapshot(unrelated_classes))[0]["interfaces"] == ["HID_present_protocol_unknown"]


def test_diff_retains_all_present_usb_changes_without_inventing_association():
    original = device()
    updated = device(problem_code=0, driver={"service": "verified_from_snapshot"})
    unrelated = device("USB\\ROOT_HUB30\\PRIVATE", vid="unknown", pid="unknown", friendly_name="USB Root Hub")
    result = diff(snapshot(original), snapshot(updated, unrelated))
    assert result["added"] == [unrelated]
    assert result["removed"] == []
    assert result["changed"][0]["fields"]["problem_code"] == {"before": 28, "after": 0}
    assert result["physical_identity_confirmed"] is False
    assert diff(snapshot(original), snapshot())["removed"] == [original]
