"""Fast static discovery for the supported OEM imaging family; no native open."""
import re
from hyperlab.paths import load_config, save_config
from hyperlab.camera_runtime import runtime_candidates


def profiles_from_snapshot(snapshot, runtimes, *, snapshot_path=None):
    profiles, issues = [], []
    imaging = [d for d in snapshot['devices'] if d.get('present', True)
               and re.match(r'USB\\VID_164C&PID_5533(?:&|\\)', d['instance_id'], re.I)]
    targets = [d for d in imaging if re.match(r'USB\\VID_164C&PID_5533&MI_00\\', d['instance_id'], re.I)]
    if not imaging:
        issues.append({'code':'NO_CAMERA', 'message':'Windows does not see the supported imaging module. Check camera power and the USB imaging data cable; a COM port alone is not the image connection.'})
    for device in imaging:
        if device.get('problem_code') != 0:
            code = device.get('problem_code')
            issues.append({'code':'DRIVER_MISSING' if str(code) == '28' else 'DEVICE_PROBLEM',
                'message':f'Windows imaging device problem code {code}. Check the official Balluff USB3 Vision driver on this computer.'})
    if imaging and not targets and not issues:
        issues.append({'code':'INTERFACE_MISSING', 'message':'The camera USB parent is present, but the image interface is absent. Check the official USB3 Vision driver and imaging data cable.'})
    if not runtimes:
        issues.append({'code':'RUNTIME_MISSING', 'message':'The Balluff x64 runtime was not found. Install Impact Acquire with USB3 Vision support on this computer, or choose its mvGenTLProducer.cti in Hardware setup.'})
    for device in targets:
        if device.get('problem_code') != 0:
            continue
        service = (device.get('driver') or {}).get('service', 'unknown')
        if service.casefold() not in ('libusbk', 'unknown'):
            issues.append({'code':'DRIVER_BINDING', 'message':f'The imaging interface uses {service}. The supported Balluff USB3 Vision path uses libusbK; check its driver binding in Device Manager.'})
            continue
        parent = next((d for d in imaging if d['instance_id'].casefold() == str(device.get('parent','')).casefold()), None)
        names = [] if parent is None else [parent.get('bus_reported_description', ''), parent.get('friendly_name', '')]
        name = next((n for n in names if 'mvbluefox3' in str(n).casefold()), None)
        if parent is None or name is None or parent.get('problem_code', 0) != 0:
            issues.append({'code':'IDENTITY_UNCONFIRMED', 'message':'PnP parent identity is unconfirmed. The current USB parent must identify an mvBlueFOX3 imaging module. Run Hardware setup to save its device properties.'})
            continue
        serial = parent.get('serial')
        if not serial or serial == 'unknown':
            serial = parent['instance_id'].rsplit('\\', 1)[-1]
        if not serial or '&' in serial:
            issues.append({'code':'SERIAL_UNCONFIRMED', 'message':'Windows supplied a location-based ID rather than a camera serial. Check the camera parent properties; no device index was selected.'})
            continue
        if runtimes:
            # Runtime preference is independent of camera count.
            profiles.append({'schema_version':1, 'name':name,
                'instance_id':device['instance_id'], 'serial':serial,
                'cti':str(runtimes[0]), 'snapshot':str(snapshot_path) if snapshot_path else None,
                'scanner':'UNVERIFIED', 'calibration':'UNCONFIGURED', 'capabilities':'PENDING_CONNECTION_READBACK'})
    return {'profiles':profiles, 'issues':issues}


def discover_profiles():
    from hyperlab.connection_diagnostics import hardware_check
    return hardware_check()


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
    if any(token in text for token in ('cti', 'producer', 'runtime', 'dll load', 'winerror 126', 'winerror 193')):
        return 'Runtime unavailable or unverified'
    return 'Connection failed'
