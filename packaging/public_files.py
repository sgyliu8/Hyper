"""Exact distribution member checks. Failures report counts, not private names."""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import zipfile


def safe_name(name):
    parts = name.rstrip('/').split('/')
    if (not name or '\\' in name or ':' in name or
            any(part in {'', '.', '..'} or part.endswith((' ', '.')) for part in parts)):
        raise ValueError('Unsafe distribution member name')
    return '/'.join(parts)


def read_allowlist(path):
    names = [line.strip() for line in Path(path).read_text(encoding='utf-8').splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    for name in names:
        safe_name(name)
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError('Duplicate or case-colliding allowlist entry')
    return set(names)


def check_names(names, expected):
    names = list(names)
    for name in names:
        safe_name(name)
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError('Duplicate or case-colliding distribution member')
    extra, missing = set(names) - expected, expected - set(names)
    if extra or missing:
        raise ValueError(f'Distribution allowlist mismatch: {len(extra)} unexpected, {len(missing)} missing')
    return {'status': 'PASS', 'members': len(names),
            'member_list_sha256': hashlib.sha256('\n'.join(sorted(names)).encode()).hexdigest()}


def ancestor_directories(names):
    return {'/'.join(name.split('/')[:index]) for name in names
            for index in range(1, len(name.split('/')))}


def check_zip(path, expected, *, prefix=''):
    with zipfile.ZipFile(path) as archive:
        names = []
        directories = ancestor_directories({prefix + name for name in expected})
        for item in archive.infolist():
            safe_name(item.filename)
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('Symlinks are not allowed in distributions')
            if item.is_dir():
                if item.filename.rstrip('/') not in directories:
                    raise ValueError('Unexpected distribution directory')
                continue
            if not item.filename.startswith(prefix):
                raise ValueError('Distribution member outside its expected root')
            names.append(item.filename[len(prefix):])
        return check_names(names, expected)


def check_directory(path, expected):
    path = Path(path)
    names = []
    directories = ancestor_directories(expected)
    for item in path.rglob('*'):
        info = item.lstat()
        if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & 1024:
            raise ValueError('Reparse points are not allowed in distributions')
        if item.is_file():
            names.append(item.relative_to(path).as_posix())
        elif item.relative_to(path).as_posix() not in directories:
            raise ValueError('Unexpected distribution directory')
    return check_names(names, expected)


def wheel_members(source_names, version):
    package = {name.removeprefix('src/') for name in source_names if name.startswith('src/')}
    metadata = {f'hyperlab-{version}.dist-info/{name}' for name in
                ('METADATA', 'WHEEL', 'entry_points.txt', 'top_level.txt', 'RECORD')}
    return package | metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--frozen', type=Path)
    parser.add_argument('--version', default='0.6.0')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    source = read_allowlist(here/'public_files.txt')
    result = {}
    if args.source:
        result['source'] = check_zip(args.source, source)
    if args.wheel:
        result['wheel'] = check_zip(args.wheel, wheel_members(source, args.version))
    if args.frozen:
        result['frozen'] = check_zip(args.frozen, read_allowlist(here/'frozen_members.txt'), prefix='HyperLab/')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
