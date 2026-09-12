"""Private, read-only connection reports usable without a camera or SDK."""
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import re
import sys

from hyperlab.camera_runtime import runtime_search, review_producer
from hyperlab.devices import profiles_from_snapshot
from hyperlab.paths import config_directory, load_config
from hyperlab.probe import load_snapshot, run_inventory


def hardware_check(*, cti=None, output=None):
    from hyperlab import __version__
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory = Path(output) if output is not None else config_directory()/'diagnostics'/stamp
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    report = {'schema_version': 1, 'created_at': stamp, 'version': __version__,
        'mode': 'READ_ONLY_STATIC', 'hardware_validation': 'NOT_RUN',
        'camera_opened': False, 'serial_opened': False, 'producer_loaded': False,
        'profiles': [], 'issues': [], 'runtimes': [], 'controllers': [],
        'report_path': str(directory/'connection-report.json'),
        'text_path': str(directory/'connection-report.txt'),
        'environment': {'platform': platform.platform(), 'python': sys.version,
                        'executable': sys.executable, 'process_bits': 64 if sys.maxsize > 2**32 else 32}}
    config = load_config()
    explicit = cti is not None or bool(config.get('camera_cti'))
    if cti is None:
        cti = config.get('camera_cti', (config.get('device_profile') or {}).get('cti'))
    report['configured_cti'] = str(cti) if cti else None
    try:
        path = run_inventory(directory/'inventory')
        snapshot = load_snapshot(path)
        report['snapshot'] = str(path)
        report['inventory_warnings'] = snapshot.get('warnings', [])
    except Exception as error:
        snapshot = {'devices': []}
        report['issues'].append({'code': 'INVENTORY_FAILED', 'message': f'{type(error).__name__}: {error}'})
    available = []
    for item in runtime_search(cti, snapshot=snapshot):
        if item['architecture'] == 'x64':
            try:
                item['signature'] = review_producer(Path(item['path']))
                available.append(Path(item['path']))
            except Exception as error:
                item['error'] = f'{type(error).__name__}: {error}'
        report['runtimes'].append(item)
    if explicit and cti:
        requested = Path(str(cti).strip().strip('"')).expanduser().resolve()
        available = [p for p in available if p == requested]
        if not available:
            report['issues'].append({'code': 'CONFIGURED_RUNTIME_INVALID',
                'message': 'The selected CTI is missing, not x64 or has an invalid/unverifiable OEM signature. Choose the installed mvGenTLProducer.cti, or clear the path to use automatic discovery.'})
    dependencies = {}
    for name in ('harvesters', 'genicam'):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = 'NOT_INSTALLED'
            report['issues'].append({'code': 'ACQUISITION_PACKAGE_MISSING',
                'message': f'{name} is missing. Use the complete desktop package, or install HyperLab with its camera extra in this Python environment.'})
    report['dependencies'] = dependencies
    found = profiles_from_snapshot(snapshot, available, snapshot_path=report.get('snapshot'))
    report['issues'].extend(found['issues'])
    if all(value != 'NOT_INSTALLED' for value in dependencies.values()):
        report['profiles'] = found['profiles']
    report['imaging_devices'] = [d for d in snapshot['devices'] if d.get('present', True)
        and re.match(r'USB\\VID_164C&PID_5533(?:&|\\)', d['instance_id'], re.I)]
    for device in snapshot['devices']:
        if device.get('present', True) and re.match(r'USB\\VID_1FC9&PID_0003\\', device['instance_id'], re.I):
            match = re.search(r'\bCOM\d+\b', device.get('friendly_name', ''), re.I)
            report['controllers'].append({'port': match[0].upper() if match else None,
                'instance_id': device['instance_id'], 'problem_code': device.get('problem_code'),
                'protocol': 'UNVERIFIED', 'required_for_imaging': False})
    report['status'] = 'READY_TO_CONNECT' if report['profiles'] else 'SETUP_REQUIRED'
    report['summary'] = format_report(report)
    Path(report['report_path']).write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding='utf-8')
    Path(report['text_path']).write_text(report['summary'], encoding='utf-8')
    return report


def format_report(report):
    lines = [f"HyperLab camera setup: {report['status']}",
        'Read-only check: no camera, serial port or producer opened.',
        f"Imaging candidates: {len(report['profiles'])}",
        'Control ports: ' + (', '.join(c['port'] or 'unknown port' for c in report['controllers']) or 'not present'),
        'Control ports are separate, unverified leads; COM numbering does not control image acquisition.', '',
        'Runtime files:']
    present = [r for r in report['runtimes'] if r['architecture'] != 'missing']
    for item in present:
        state = 'OEM signature valid' if item.get('signature', {}).get('valid') else item.get('error', item['architecture'])
        lines.append(f"  {item['path']}\n    {item['architecture']} / {state}")
    if not present:
        lines.append('  No supported CTI found. Install Balluff Impact Acquire x64 with USB3 Vision support.')
    for profile in report['profiles']:
        lines.append(f"\nImage device: {profile['name']} / {profile['serial']}\nSelected runtime: {profile['cti']}")
    if report['issues']:
        lines.append('\nChecks to resolve:')
        lines += [f"  {item['code']}: {item['message']}" for item in report['issues']]
    else:
        lines.append('\nNext: close other camera applications, then use Connect camera and Start preview.')
    lines += ['', 'Static readiness does not verify native loading or a real frame.',
        'Copy the complete application folder; Windows camera drivers must be installed on each computer.',
        f"Local report: {report['report_path']}", 'Nothing was uploaded.']
    return '\n'.join(lines)
