"""Private reference exchange; importing a package never applies calibration."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile
from .plots import plain


def file_digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def applicability(metadata):
    keys = ('serial','model','calibration_source','wavelengths','wavelength_units','wavelength_evidence',
            'scan_states','shape','axis_order','pixel_format','cfa_pattern','sensor_roi_offset',
            'temperature_range','readback_settings')
    return {key:plain(metadata.get(key)) for key in keys}


def mask_name(metadata):
    name = metadata.get('valid_mask_file')
    if name and (Path(name).name != name or '/' in name or '\\' in name or ':' in name or not name.endswith('.npy')):
        raise ValueError('Reference validity mask must be an adjacent NPY asset')
    return name


def export_references(records, path):
    """NPY/NPZ references + sidecars. Vendor binaries are never packaged."""
    path = Path(path)
    entries = []
    if not records:
        raise ValueError('Select at least one registered reference')
    files = []
    total = 0
    for i, record in enumerate(records):
        source = Path(record['path'])
        if source.suffix.lower() not in ('.npy','.npz'):
            raise ValueError('Private reference exchange currently accepts NPY/NPZ arrays; convert ENVI with explicit metadata first')
        paths = [source]
        sidecar = source.with_suffix(source.suffix+'.json')
        if sidecar.exists():
            paths.append(sidecar)
            mask = mask_name(json.loads(sidecar.read_text(encoding='utf-8')))
            if mask:
                paths.append(source.parent/mask)
        assets = []
        for item in paths:
            total += item.stat().st_size
            if total > 2*1024**3:
                raise ValueError('Private reference bundle exceeds the 2 GiB local budget')
            name = f'assets/{i}/{item.name}'
            assets.append({'name':name,'sha256':file_digest(item),'bytes':item.stat().st_size})
            files.append((item,name))
        entries.append({'record':plain(record),'assets':assets,'array':assets[0]['name'],
                        'applicability':applicability(record['metadata'])})
    manifest = {'schema_version':1,'kind':'private_reference_bundle','records':entries,
                'notice':'Private data; no vendor driver, calibration validity or cross-device compatibility is granted.'}
    with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',json.dumps(manifest,allow_nan=False,indent=2))
        for item,name in files:
            archive.write(item,name)
    return path


def import_references(path, directory, *, device_serial=None):
    directory = Path(directory).resolve()
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if sum(info.file_size for info in infos) > 2*1024**3:
            raise ValueError('Reference bundle exceeds the 2 GiB extraction budget')
        names = [info.filename for info in infos]
        if len(names)!=len(set(names)):
            raise ValueError('Duplicate archive entries are not accepted')
        for info in infos:
            name = PurePosixPath(info.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in info.filename or ':' in info.filename or ((info.external_attr>>16)&0o170000)==0o120000:
                raise ValueError('Unsafe reference archive path')
        if archive.getinfo('manifest.json').file_size > 4*1024**2:
            raise ValueError('Reference manifest is too large')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('schema_version')!=1 or manifest.get('kind')!='private_reference_bundle':
            raise ValueError('Unsupported reference bundle')
        expected = {'manifest.json'} | {a['name'] for e in manifest['records'] for a in e['assets']}
        if expected != set(names):
            raise ValueError('Archive contains undeclared assets')
        # Validate hashes before writing anything outside the new destination.
        for entry in manifest['records']:
            if entry['array'] not in {a['name'] for a in entry['assets']}:
                raise ValueError('Reference array is not a declared asset')
            if PurePosixPath(entry['array']).suffix.lower() not in ('.npy','.npz'):
                raise ValueError('Reference array must be NPY/NPZ')
            for asset in entry['assets']:
                if PurePosixPath(asset['name']).suffix.lower() not in ('.npy','.npz','.json'):
                    raise ValueError('Only array and JSON reference assets are accepted')
                with archive.open(asset['name']) as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=asset['sha256']:
                        raise ValueError('Reference asset digest mismatch')
                if asset['name'].endswith('.json'):
                    if archive.getinfo(asset['name']).file_size > 4*1024**2:
                        raise ValueError('Reference sidecar is too large')
                    mask = mask_name(json.loads(archive.read(asset['name'])))
                    if mask and str(PurePosixPath(asset['name']).parent/mask) not in {a['name'] for a in entry['assets']}:
                        raise ValueError('Reference validity mask is not a declared asset')
        directory.mkdir(parents=True,exist_ok=False)
        for info in infos:
            target = directory/Path(*PurePosixPath(info.filename).parts)
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(info) as source, target.open('xb') as dest:
                import shutil
                shutil.copyfileobj(source,dest)
    records = []
    for entry in manifest['records']:
        record = entry['record']
        previous = record['path']
        record.update(path=str(directory/entry['array']), imported_from=previous,
                      applicability=entry['applicability'],
                      sha256=next(a['sha256'] for a in entry['assets'] if a['name']==entry['array']))
        record['metadata'] = dict(record['metadata'], source_file=record['path'], imported_source_file=previous)
        serial = entry['applicability'].get('serial')
        record['device_compatibility'] = ('MATCH' if device_serial and serial==device_serial else
                                          'MISMATCH' if device_serial and serial else 'UNKNOWN')
        record['calibration_applied'] = False
        records.append(record)
    return records


def locate_reference(record, path):
    from .io import load_cube
    path = Path(path).resolve()
    digest = file_digest(path)
    if record.get('sha256') and digest != record['sha256']:
        raise ValueError('Selected file differs from the registered reference digest; register it as a new reference')
    with load_cube(path) as cube:
        metadata = dict(cube.metadata)
    return dict(record,path=str(path),metadata=metadata,sha256=digest,
                previous_path=record['path'],previous_metadata=record['metadata'],
                relocation_evidence='BYTE_MATCH' if record.get('sha256') else 'USER_SELECTED_UNVERIFIED')
