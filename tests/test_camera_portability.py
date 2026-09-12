"""Cross-computer connection regressions; no native device opens."""
import json
from pathlib import Path
import struct

import pytest

from hyperlab import devices


def pe(path, machine=0x8664):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = bytearray(256)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 128)
    data[128:132] = b'PE\0\0'
    struct.pack_into('<H', data, 132, machine)
    path.write_bytes(data)
    return path


def snapshot(*, port='COM17', parent_description='unknown', problem=0):
    parent = r'USB\VID_164C&PID_5533\EXAMPLE_SERIAL'
    return {'schema_version': 1, 'devices': [
        {'instance_id': parent, 'friendly_name': 'mvBlueFOX3-M2024C',
         'bus_reported_description': parent_description, 'present': True, 'problem_code': 0},
        {'instance_id': r'USB\VID_164C&PID_5533&MI_00\NEW_PC_PORT', 'parent': parent,
         'present': True, 'problem_code': problem, 'driver': {'service': 'libusbK'}},
        {'instance_id': r'USB\VID_1FC9&PID_0003\EXAMPLE_CONTROLLER',
         'friendly_name': f'USB Serial Device ({port})', 'class': 'Ports',
         'present': True, 'problem_code': 0}], 'software': []}


def test_parent_windows_name_fallback_and_new_port():
    report = devices.profiles_from_snapshot(snapshot(), [Path('runtime/mvGenTLProducer.cti')])
    assert len(report['profiles']) == 1
    assert report['profiles'][0]['serial'] == 'EXAMPLE_SERIAL'
    assert report['profiles'][0]['instance_id'].endswith('NEW_PC_PORT')


def test_missing_driver_is_actionable_even_without_interface_child():
    data = snapshot()
    data['devices'] = data['devices'][:1]
    data['devices'][0]['problem_code'] = 28
    report = devices.profiles_from_snapshot(data, [])
    assert 'DRIVER_MISSING' in {i['code'] for i in report['issues']}
    assert not report['profiles']


def test_configured_genicam_directory_whitespace_and_quotes(tmp_path, monkeypatch):
    producer = pe(tmp_path/'runtime with spaces'/'mvGenTLProducer.cti')
    monkeypatch.setenv('GENICAM_GENTL64_PATH', f'  "{producer.parent}"  ')
    assert producer in devices.runtime_candidates()


def test_short_or_non_pe_file_is_rejected(tmp_path):
    invalid = tmp_path/'mvGenTLProducer.cti'
    invalid.write_bytes(b'bad')
    assert invalid not in devices.runtime_candidates(str(invalid))
    invalid.write_bytes(bytes(128) + b'PE\0\0\x64\x86')
    assert invalid not in devices.runtime_candidates(str(invalid))


def test_installer_location_without_environment_variable(tmp_path, monkeypatch):
    producer = pe(tmp_path/'custom install'/'bin'/'x64'/'mvGenTLProducer.cti')
    data = snapshot()
    data['software'] = [{'name': 'Balluff Impact Acquire', 'install_location': str(tmp_path/'custom install')}]
    monkeypatch.delenv('MVIMPACT_ACQUIRE_DIR', raising=False)
    assert producer in devices.runtime_candidates(snapshot=data)


def test_multiple_runtime_versions_do_not_duplicate_camera():
    report = devices.profiles_from_snapshot(snapshot(parent_description='mvBlueFOX3-M2024C'),
        [Path('preferred/mvGenTLProducer.cti'), Path('older/mvGenTLProducer.cti')])
    assert len(report['profiles']) == 1
    assert report['profiles'][0]['cti'].startswith('preferred')


def test_alternate_driver_has_specific_diagnosis():
    data = snapshot(parent_description='mvBlueFOX3-M2024C')
    data['devices'][1]['driver']['service'] = 'WinUSB'
    report = devices.profiles_from_snapshot(data, [Path('runtime/mvGenTLProducer.cti')])
    assert 'DRIVER_BINDING' in {i['code'] for i in report['issues']}
    assert not report['profiles']


def test_saved_old_com_is_not_required_for_imaging():
    data = snapshot(parent_description='mvBlueFOX3-M2024C')
    data['devices'] = data['devices'][:2]
    assert len(devices.profiles_from_snapshot(data, [Path('mvGenTLProducer.cti')])['profiles']) == 1


def fake_inventory(tmp_path, monkeypatch, data=None):
    from hyperlab import connection_diagnostics as diagnostics
    path = tmp_path/'snapshot.json'
    path.write_text(json.dumps(data if data is not None else snapshot()), encoding='utf-8')
    monkeypatch.setattr(diagnostics, 'run_inventory', lambda output: path)
    monkeypatch.setattr(diagnostics, 'review_producer', lambda path: {'valid': True, 'signer': 'Balluff'})
    monkeypatch.setattr(diagnostics, 'version', lambda name: 'example-installed-version')
    return diagnostics


def test_report_separates_control_port_and_saves_failure_evidence(tmp_path, monkeypatch):
    diagnostics = fake_inventory(tmp_path, monkeypatch)
    monkeypatch.setattr(diagnostics, 'runtime_search', lambda *a, **k: [])
    report = diagnostics.hardware_check(output=tmp_path/'report')
    assert report['status'] == 'SETUP_REQUIRED'
    assert report['controllers'][0]['port'] == 'COM17'
    assert not report['controllers'][0]['required_for_imaging']
    assert not any(report[key] for key in ('camera_opened', 'serial_opened', 'producer_loaded'))
    assert json.loads(Path(report['report_path']).read_text())['status'] == 'SETUP_REQUIRED'
    assert 'RUNTIME_MISSING' in Path(report['text_path']).read_text()


def test_bad_explicit_cti_is_not_silently_replaced(tmp_path, monkeypatch):
    diagnostics = fake_inventory(tmp_path, monkeypatch)
    path = pe(tmp_path/'valid'/'mvGenTLProducer.cti')
    monkeypatch.setattr(diagnostics, 'runtime_search', lambda *a, **k: [{'path':str(path), 'architecture':'x64'}])
    report = diagnostics.hardware_check(cti=tmp_path/'missing.cti', output=tmp_path/'report')
    assert not report['profiles']
    assert 'CONFIGURED_RUNTIME_INVALID' in [i['code'] for i in report['issues']]


def test_stale_saved_profile_uses_current_inventory(tmp_path, monkeypatch):
    from hyperlab.paths import save_config
    diagnostics = fake_inventory(tmp_path, monkeypatch)
    save_config({'device_profile': {'serial':'OLD_CAMERA', 'cti':'missing/mvGenTLProducer.cti', 'port':'COM4'}})
    path = pe(tmp_path/'installed'/'mvGenTLProducer.cti')
    monkeypatch.setattr(diagnostics, 'runtime_search', lambda *a, **k: [{'path':str(path), 'architecture':'x64'}])
    report = diagnostics.hardware_check(output=tmp_path/'report')
    assert report['profiles'][0]['serial'] == 'EXAMPLE_SERIAL'
    assert report['profiles'][0]['cti'] == str(path)
    assert report['controllers'][0]['port'] == 'COM17'


@pytest.mark.parametrize('missing', ['harvesters', 'genicam'])
def test_missing_camera_package_prevents_ready_status(tmp_path, monkeypatch, missing):
    diagnostics = fake_inventory(tmp_path, monkeypatch)
    path = pe(tmp_path/'installed'/'mvGenTLProducer.cti')
    monkeypatch.setattr(diagnostics, 'runtime_search', lambda *a, **k: [{'path':str(path), 'architecture':'x64'}])
    def installed_version(name):
        if name == missing:
            raise diagnostics.PackageNotFoundError(name)
        return 'example-installed-version'
    monkeypatch.setattr(diagnostics, 'version', installed_version)
    report = diagnostics.hardware_check(output=tmp_path/'report')
    assert report['status'] == 'SETUP_REQUIRED'
    assert not report['profiles']
    assert report['dependencies'][missing] == 'NOT_INSTALLED'
    assert 'ACQUISITION_PACKAGE_MISSING' in [i['code'] for i in report['issues']]


def test_inventory_failure_is_retained_in_readable_report(tmp_path, monkeypatch):
    diagnostics = fake_inventory(tmp_path, monkeypatch)
    def fail(output):
        raise RuntimeError('Windows PnP unavailable')
    monkeypatch.setattr(diagnostics, 'run_inventory', fail)
    monkeypatch.setattr(diagnostics, 'runtime_search', lambda *a, **k: [])
    report = diagnostics.hardware_check(output=tmp_path/'report')
    assert 'Windows PnP unavailable' in Path(report['text_path']).read_text()


def test_generated_usb_location_is_not_promoted_to_serial():
    data = snapshot()
    data['devices'][0]['instance_id'] = r'USB\VID_164C&PID_5533\7&ABC&0&5'
    data['devices'][1]['parent'] = data['devices'][0]['instance_id']
    report = devices.profiles_from_snapshot(data, [Path('runtime/mvGenTLProducer.cti')])
    assert not report['profiles']
    assert 'SERIAL_UNCONFIRMED' in [i['code'] for i in report['issues']]


@pytest.mark.parametrize('machine,expected', [(0x14c,'x86'), (0xaa64,'arm64'), (0x8664,'x64')])
def test_architecture_before_native_load(tmp_path, machine, expected):
    from hyperlab.camera_runtime import producer_architecture
    assert producer_architecture(pe(tmp_path/'mvGenTLProducer.cti', machine)) == expected


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows signature API')
def test_signed_custom_install_does_not_require_registry_root(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from hyperlab import camera_runtime as runtime
    path = pe(tmp_path/'another install'/'mvGenTLProducer.cti')
    monkeypatch.setattr(runtime, 'registry_paths', lambda: [])
    calls = []
    def signature(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout=json.dumps({'valid':True, 'signer':'CN=Balluff MV GmbH'}))
    monkeypatch.setattr(runtime.subprocess, 'run', signature)
    monkeypatch.setattr(runtime.shutil, 'which', lambda name: 'powershell.exe')
    assert runtime.review_producer(path)['valid']
    assert calls[0]['env']['HYPERLAB_CTI_REVIEW_PATH'] == str(path)


def test_setup_dialog_is_offline_until_explicit_check(qtbot, tmp_path, monkeypatch):
    from hyperlab.ui import hardware_dialog as ui
    calls = []
    def report(**kwargs):
        calls.append(kwargs)
        return {'summary':'SETUP_REQUIRED: example runtime missing', 'report_path':str(tmp_path/'report.json')}
    monkeypatch.setattr(ui, 'hardware_check', report)
    dialog = ui.HardwareSetupDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    assert calls == []
    dialog.check.click()
    qtbot.waitUntil(lambda: dialog.future is None)
    assert len(calls) == 1 and 'SETUP_REQUIRED' in dialog.text.toPlainText()
    assert dialog.open_report.isEnabled()
    dialog.reject()


def test_setup_dialog_surfaces_failed_worker_and_allows_close(qtbot, monkeypatch):
    from hyperlab.ui import hardware_dialog as ui
    def fail(**kwargs):
        raise OSError('Example unwritable folder')
    monkeypatch.setattr(ui, 'hardware_check', fail)
    dialog = ui.HardwareSetupDialog()
    qtbot.addWidget(dialog)
    dialog.run_check()
    qtbot.waitUntil(lambda: dialog.future is None)
    assert 'Example unwritable folder' in dialog.text.toPlainText()
    assert dialog.close_button.isEnabled()
    dialog.reject()
