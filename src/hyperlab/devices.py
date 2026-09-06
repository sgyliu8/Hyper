"""Fast static discovery for the supported OEM imaging family; no native open."""
import os
from pathlib import Path
import struct
from hyperlab.probe import load_snapshot, run_inventory
from hyperlab.paths import load_config, save_config


def runtime_candidates(configured=None):
    roots = [Path(configured)] if configured else []
    for name in ('GENICAM_GENTL64_PATH', 'MVIMPACT_ACQUIRE_DIR'):
        roots.extend(Path(item) for item in os.environ.get(name, '').split(os.pathsep) if item)
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                    r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment') as key:
                roots.append(Path(winreg.QueryValueEx(key, 'MVIMPACT_ACQUIRE_DIR')[0]))
        except OSError:
            pass
        roots.append(Path(os.environ.get('ProgramFiles', r'C:\Program Files'))/'Balluff/ImpactAcquire')
    found = []
    for root in roots:
        paths = [root] if root.suffix.casefold() == '.cti' else [root/'mvGenTLProducer.cti', root/'bin/x64/mvGenTLProducer.cti']
        for path in paths:
            if path.name != 'mvGenTLProducer.cti' or not path.is_file():
                continue
            path = path.resolve()
            if path in found:
                continue
            # Signature/installed-root verification occurs once at connection.
            with path.open('rb') as stream:
                stream.seek(0x3c)
                offset = stream.read(4)
                if len(offset) != 4:
                    continue
                stream.seek(struct.unpack('<I', offset)[0])
                if stream.read(6) != b'PE\0\0\x64\x86':
                    continue
            found.append(path)
    return found


def profiles_from_snapshot(snapshot, runtimes, *, snapshot_path=None):
    profiles, issues = [], []
    targets = [d for d in snapshot['devices'] if d.get('present', True)
               and d['instance_id'].upper().startswith('USB\\VID_164C&PID_5533&MI_00\\')]
    if not targets:
        issues.append({'code':'NO_CAMERA', 'message':'No supported mvBlueFOX3 imaging interface is present. Offline tools remain available.'})
    if not runtimes:
        issues.append({'code':'RUNTIME_MISSING', 'message':'The supported Balluff x64 imaging runtime was not found. See Hardware setup.'})
    for device in targets:
        if device.get('problem_code') != 0:
            issues.append({'code':'DRIVER_MISSING' if device.get('problem_code') == 28 else 'DEVICE_PROBLEM',
                           'message':f"Windows imaging interface problem code {device.get('problem_code')}."})
            continue
        parent = next((d for d in snapshot['devices'] if d['instance_id'].casefold() == str(device.get('parent','')).casefold()), None)
        if parent is None or 'mvBlueFOX3' not in parent.get('bus_reported_description',''):
            issues.append({'code':'IDENTITY_UNCONFIRMED', 'message':'Imaging module parent identity needs confirmation.'})
            continue
        for runtime in runtimes:
            profiles.append({'schema_version':1, 'name':parent['bus_reported_description'],
                'instance_id':device['instance_id'], 'serial':parent['instance_id'].rsplit('\\',1)[-1],
                'cti':str(runtime), 'snapshot':str(snapshot_path) if snapshot_path else None,
                'scanner':'UNVERIFIED', 'calibration':'UNCONFIGURED', 'capabilities':'PENDING_CONNECTION_READBACK'})
    return {'profiles':profiles, 'issues':issues}


def discover_profiles():
    saved = load_config().get('device_profile') or {}
    path = run_inventory()
    return profiles_from_snapshot(load_snapshot(path), runtime_candidates(saved.get('cti')), snapshot_path=path)


def discover_profile():
    report = discover_profiles()
    if len(report['profiles']) != 1:
        raise RuntimeError('; '.join(i['message'] for i in report['issues']) or
                           'Multiple supported candidates found. Select a device in the workbench.')
    return report['profiles'][0]


def remember_profile(profile):
    config = load_config()
    config['device_profile'] = profile
    save_config(config)


def connection_error_kind(error):
    text = str(error).casefold()
    if any(token in text for token in ('gencp', 'timeout', 'accessdenied', 'access denied', 'transport')):
        return 'Communication fault'
    if isinstance(error, ModuleNotFoundError) or 'no module named' in text:
        return 'Python acquisition package missing'
    if any(token in text for token in ('cti', 'producer', 'runtime')):
        return 'Runtime unavailable or unverified'
    return 'Connection failed'
