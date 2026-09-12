"""Locate and inspect the OEM producer without loading it or opening hardware."""
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess


ENVIRONMENT_KEYS = ('GENICAM_GENTL64_PATH', 'MVIMPACT_ACQUIRE_DIR')


def registry_paths():
    """Read current values even when this process inherited old environment."""
    if os.name != 'nt':
        return []
    import winreg
    values = []
    for hive, key_name in (
        (winreg.HKEY_CURRENT_USER, r'Environment'),
        (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')):
        try:
            with winreg.OpenKey(hive, key_name) as key:
                for name in ENVIRONMENT_KEYS:
                    try:
                        values.append(winreg.QueryValueEx(key, name)[0])
                    except OSError:
                        pass
        except OSError:
            pass
    return values


def producer_architecture(path):
    try:
        with Path(path).open('rb') as stream:
            if stream.read(2) != b'MZ':
                return 'invalid'
            stream.seek(0x3c)
            data = stream.read(4)
            if len(data) != 4:
                return 'invalid'
            offset = struct.unpack('<I', data)[0]
            if not 64 <= offset <= os.fstat(stream.fileno()).st_size - 6:
                return 'invalid'
            stream.seek(offset)
            header = stream.read(6)
            if header[:4] != b'PE\0\0':
                return 'invalid'
            return {0x8664: 'x64', 0x14c: 'x86', 0xaa64: 'arm64'}.get(
                struct.unpack('<H', header[4:])[0], 'unsupported')
    except FileNotFoundError:
        return 'missing'
    except OSError:
        return 'unreadable'


def runtime_search(configured=None, *, snapshot=None):
    values = [configured] if configured else []
    values += [os.environ.get(name, '') for name in ENVIRONMENT_KEYS]
    values += registry_paths()
    for entry in (snapshot or {}).get('software', []):
        if re.search(r'Impact\s*Acquire|mvIMPACT|mvGenTL', entry.get('name', ''), re.I):
            location = entry.get('install_location')
            if location and location != 'unknown':
                values.append(location)
    if os.name == 'nt':
        program = Path(os.environ.get('ProgramW6432', os.environ.get('ProgramFiles', r'C:\Program Files')))
        values += [str(program/'Balluff/ImpactAcquire'), str(program/'MATRIX VISION/mvIMPACT Acquire')]
    result, seen = [], set()
    for value in values:
        for item in str(value).split(os.pathsep):
            item = os.path.expandvars(item.strip().strip('"').strip())
            if not item:
                continue
            root = Path(item).expanduser()
            paths = [root] if root.suffix.casefold() == '.cti' else [
                root/'mvGenTLProducer.cti', root/'bin/x64/mvGenTLProducer.cti']
            for path in paths:
                if path.name.casefold() != 'mvgentlproducer.cti':
                    continue
                path = path.resolve()
                key = str(path).casefold()
                if key in seen:
                    continue
                seen.add(key)
                result.append({'path': str(path), 'architecture': producer_architecture(path)})
    return result


def runtime_candidates(configured=None, *, snapshot=None):
    return [Path(item['path']) for item in runtime_search(configured, snapshot=snapshot)
            if item['architecture'] == 'x64']


def review_producer(cti):
    """Check the actual selected file, independent of install-directory naming."""
    if os.name != 'nt':
        raise RuntimeError('The supported OEM acquisition runtime requires Windows x64')
    cti = Path(cti).resolve()
    if cti.name.casefold() != 'mvgentlproducer.cti':
        raise ValueError('Choose the Balluff mvGenTLProducer.cti file')
    architecture = producer_architecture(cti)
    if architecture != 'x64':
        raise ValueError(f'Producer architecture/file status: {architecture}; Windows x64 is required: {cti}')
    environment = dict(os.environ, HYPERLAB_CTI_REVIEW_PATH=str(cti))
    command = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
               "$s=Get-AuthenticodeSignature -LiteralPath $env:HYPERLAB_CTI_REVIEW_PATH; "
               "@{valid=($s.Status -eq 'Valid'); status=[string]$s.Status; signer=$s.SignerCertificate.Subject} | ConvertTo-Json")
    shell = shutil.which('powershell.exe') or shutil.which('pwsh')
    if not shell:
        raise RuntimeError('PowerShell is required to check the runtime signature')
    if Path(shell).stem.casefold() == 'powershell':
        environment = {key: value for key, value in environment.items() if key.casefold() != 'psmodulepath'}
    response = subprocess.run([shell, '-NoProfile', '-Command', command], capture_output=True,
        text=True, encoding='utf-8', errors='replace', timeout=30, env=environment,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if response.returncode:
        raise RuntimeError(f'Runtime signature check failed: {response.stderr.strip()}')
    signature = json.loads(response.stdout)
    if not signature['valid'] or not re.search(r'Balluff|MATRIX VISION', signature.get('signer') or '', re.I):
        raise ValueError(f"Producer signature is not valid for Balluff/MATRIX VISION ({signature.get('status')})")
    return signature
