"""Discover the evidenced imaging interface; never open a serial or CTI here."""
from pathlib import Path
import json

from hyperlab.probe import load_snapshot, run_inventory


def discover_profile():
    snapshot_path = run_inventory()
    snapshot = load_snapshot(snapshot_path)
    targets = [d for d in snapshot['devices'] if d.get('present', True)
               and d['instance_id'].upper().startswith('USB\\VID_164C&PID_5533&MI_00\\')]
    if len(targets) != 1:
        raise RuntimeError('Exactly one investigated mvBlueFOX3 imaging interface must be connected.')
    device = targets[0]
    if device.get('problem_code') != 0:
        raise RuntimeError(f"Imaging interface has Windows problem code {device.get('problem_code')}.")
    parent = next((d for d in snapshot['devices']
                   if d['instance_id'].casefold() == str(device.get('parent', '')).casefold()), None)
    if parent is None or 'mvBlueFOX3' not in parent.get('bus_reported_description', ''):
        raise RuntimeError('The imaging module parent identity is unconfirmed.')
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                       r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment') as key:
        root = Path(winreg.QueryValueEx(key, 'MVIMPACT_ACQUIRE_DIR')[0])
    cti = root / 'bin/x64/mvGenTLProducer.cti'
    if not cti.is_file():
        raise RuntimeError('The installed Balluff x64 producer is missing.')
    profile = {'schema_version': 1, 'name': parent['bus_reported_description'],
               'instance_id': device['instance_id'], 'serial': parent['instance_id'].rsplit('\\', 1)[-1],
               'cti': str(cti), 'snapshot': str(snapshot_path), 'scanner': 'UNVERIFIED',
               'calibration': 'UNCONFIGURED'}
    path = Path('local/config/device-profile.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2), encoding='utf-8')
    return profile
