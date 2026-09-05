"""Build one local Windows onedir ZIP and wheel from a clean, exact Git commit."""
import argparse
import hashlib
from importlib.metadata import distribution, version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64','x86_64'):
        raise RuntimeError('Build this desktop package on Windows x64')
    status = run(['git','status','--porcelain'],cwd=root,capture_output=True,text=True).stdout
    if status.strip():
        raise RuntimeError('Commit the reviewed source before building; worktree must be clean')
    commit = run(['git','rev-parse','HEAD'],cwd=root,capture_output=True,text=True).stdout.strip()
    output = args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    # git archive also proves that no untracked/private source enters the build.
    source_zip = output/'source.zip'
    run(['git','archive','--format=zip','-o',str(source_zip),commit],cwd=root)
    import zipfile
    checkout = output/'source'
    with zipfile.ZipFile(source_zip) as archive:
        archive.extractall(checkout)
    wheel_dir = output/'wheel'
    run([sys.executable,'-m','build','--wheel','--outdir',str(wheel_dir)],cwd=checkout)
    packages = ['numpy','matplotlib','pillow','PySide6','PySide6_Essentials','PySide6_Addons',
                'shiboken6','pyqtgraph','psutil','harvesters','genicam','contourpy','cycler',
                'fonttools','kiwisolver','packaging','pyparsing','python-dateutil','six','typing_extensions']
    # License texts come from the exact installed distributions, not a fabricated umbrella license.
    notices = output/'licenses'
    notices.mkdir()
    from urllib.request import urlopen
    license_root = 'https://raw.githubusercontent.com/qt/qtbase/v6.10.3/LICENSES/'
    for name in ('LGPL-3.0-only.txt','GPL-3.0-only.txt','GPL-2.0-only.txt'):
        url = license_root + name
        with urlopen(url,timeout=30) as response:
            license_text = response.read()
        if b'PUBLIC LICENSE' not in license_text[:100]:
            raise RuntimeError('Expected the version-matched upstream license text')
        (notices/name).write_bytes(license_text)
    dependencies = {}
    for name in packages + ['pyinstaller']:
        dist = distribution(name)
        dependencies[name] = dist.version
        for item in dist.files or []:
            leaf = item.name.casefold()
            if any(token in leaf for token in ('license','copying','copyright','notice')) and not leaf.endswith(('.py','.pyc','.pyd','.dll')):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    target = notices/name/Path(str(item))
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(source,target)
    python_license = Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.exists():
        shutil.copy2(python_license,notices/'PYTHON-LICENSE.txt')
    command = [sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--console',
               '--name','HyperLab','--paths',str(checkout/'src'),
               '--distpath',str(output/'desktop'),'--workpath',str(output/'build'),
               '--specpath',str(output),'--collect-data','hyperlab.resources',
               '--add-data',str(checkout/'THIRD_PARTY_NOTICES.md')+':.',
               '--add-data',str(notices)+':licenses',
               '--hidden-import','hyperlab.offline_smoke','--hidden-import','harvesters.core',
               '--hidden-import','matplotlib.backends.backend_svg',
               '--hidden-import','matplotlib.backends.backend_pdf']
    for name in packages:
        command += ['--copy-metadata',name]
    for name in ('tkinter','PyQt5','PyQt6','PySide2','IPython','pytest','scipy','pandas'):
        command += ['--exclude-module',name]
    command += [str(checkout/'packaging'/'launch.py')]
    # Do not collect an unrelated application's incompatible ICU/OpenSSL from PATH.
    windows = Path(os.environ['SystemRoot'])
    build_env = dict(os.environ, PATH=os.pathsep.join((str(Path(sys.executable).parent),
                       sys.base_prefix,str(windows/'System32'),str(windows))))
    run(command,cwd=checkout,env=build_env)
    import ast
    analysis = ast.literal_eval((output/'build'/'HyperLab'/'Analysis-00.toc').read_text(encoding='utf-8'))
    modules = []
    binaries = []
    def inspect_modules(value):
        if isinstance(value,(tuple,list)):
            if len(value)==3 and isinstance(value[0],str) and value[0].startswith('hyperlab') and value[2]=='PYMODULE':
                modules.append(value)
            elif len(value)==3 and isinstance(value[0],str) and value[2]=='BINARY':
                binaries.append(value)
            else:
                for item in value:
                    inspect_modules(item)
    inspect_modules(analysis)
    if not modules or any(not Path(item[1]).resolve().is_relative_to(checkout/'src') for item in modules):
        raise RuntimeError('Frozen HyperLab modules did not all come from the exact archived source')
    allowed = [Path(sys.prefix).resolve(),Path(sys.base_prefix).resolve(),windows.resolve()]
    if any(not any(Path(item[1]).resolve().is_relative_to(root) for root in allowed) for item in binaries):
        raise RuntimeError('A binary from an unrelated application entered the build')
    desktop = output/'desktop'/'HyperLab'
    forbidden = [p for p in desktop.rglob('*') if p.is_file() and
                 (p.suffix.casefold() in ('.cti','.sys') or p.name.casefold().startswith(('mvimpact','mvgentl','mvbluefox')))]
    if forbidden:
        raise RuntimeError('Vendor runtime/driver unexpectedly entered the package')
    shutil.copy2(checkout/'THIRD_PARTY_NOTICES.md',desktop/'THIRD_PARTY_NOTICES.md')
    (desktop/'Start-HyperLab.cmd').write_text('@echo off\ncd /d "%~dp0"\nstart "" "%~dp0HyperLab.exe" app\n',encoding='utf-8')
    record = {'commit':commit,'python':platform.python_version(),'pyinstaller':version('pyinstaller'),
              'dependencies':dependencies,'hardware':'NOT_TESTED','public_release':'PENDING_LICENSE_AND_REVIEW',
              'archived_source_modules_verified':len(modules),
              'build_machine_scope':'Windows x64 development host; not a clean VM'}
    (desktop/'BUILD.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    archive_path = Path(shutil.make_archive(str(output/f'HyperLab-0.3.0-{commit[:8]}-win-x64'),
                                          'zip',root_dir=output/'desktop',base_dir='HyperLab'))
    artifacts = [archive_path,*wheel_dir.glob('*.whl')]
    record['artifacts'] = []
    for artifact in artifacts:
        with artifact.open('rb') as stream:
            digest = hashlib.file_digest(stream,'sha256').hexdigest()
        record['artifacts'].append({'file':artifact.name,'bytes':artifact.stat().st_size,'sha256':digest})
    (output/'build-receipt.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record,indent=2))


if __name__ == '__main__':
    main()
