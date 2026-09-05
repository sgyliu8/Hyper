# Install HyperLab

## Choose an entry point

| Mode | Requirements | Qualification |
|---|---|---|
| Offline / demo | Windows x64, Python 3.11, or the evaluation desktop ZIP | No camera or manufacturer runtime required |
| Image acquisition | Above plus official USB3 Vision driver, Balluff Impact Acquire 3.7.2, Harvester 1.4.3 | Experimental; current sustained hardware revalidation deferred |
| Spectroscopy | Verified FP control, synchronization and device-matched reconstruction/calibration | Not recovered |

Original-code licensing is undecided. The following are evaluation installation
instructions, not a public-release or redistribution authorization. The release
candidate is `feature/scientific-workbench-portable-v3`; default clone currently
selects the older `recovery/hinalea-local` branch.

## Source installation (ordinary user)

Install Python 3.11 x64 and Git, then in PowerShell:

```powershell
git clone --branch feature/scientific-workbench-portable-v3 --single-branch https://github.com/sgyliu8/Hyper.git
cd Hyper
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m hyperlab doctor
.\Start-HyperLab.cmd
```

This is a normal, non-editable install. Reinstall with `pip install .` after a
source update. For acquisition only, install `.[camera]` into this environment.
Do not copy someone else's virtual environment. No test packages are required.
Use the exact commit recorded in [release evidence](../dev/RELEASE_PLAN.md) for a
reproducible candidate, with `git checkout COMMIT` after cloning.

## Wheel installation

A wheel is built from a clean exact commit using `python -m build --wheel`.
Use the actual `.whl` file from the local build evidence, then:

```powershell
py -3.11 -m venv "$env:USERPROFILE\HyperLabEnv"
& "$env:USERPROFILE\HyperLabEnv\Scripts\python.exe" -m pip install C:/path/to/hyperlab-0.3.0-py3-none-any.whl
& "$env:USERPROFILE\HyperLabEnv\Scripts\python.exe" -m hyperlab demo
```

The path to the wheel is an explicit placeholder, not an author-specific required
location. Runtime resources are in the installed package. Running from another
working directory does not create an accidental `local/` folder there.

## Windows desktop evaluation ZIP

Extract the entire HyperLab folder and keep `_internal` beside `HyperLab.exe`.
Run `Start-HyperLab.cmd` or `HyperLab.exe app`. No Python installation is required.
`HyperLab.exe doctor` prints runtime and workspace information. The ZIP contains
Python/Qt libraries and their notices, but no Balluff driver, CTI or private data.
The console build retains startup errors for troubleshooting.

The local acceptance distinguishes same-machine independent installation from a
new Windows machine. No clean physical PC/VM or driver installation was validated
this phase. Artifact paths, SHA and actual smoke results are in the release plan;
there is no published GitHub Release yet.

## Workspace and configuration

**Workspace…** selects writable experiment storage. CLI equivalent (before the
subcommand):

```powershell
.\.venv\Scripts\python.exe -m hyperlab --workspace "$env:USERPROFILE\Documents\MyHyperLabData" app
```

Priority: explicit workspace, `HYPERLAB_WORKSPACE`, saved workspace, then
Documents/HyperLabData. Small settings use Qt GenericConfigLocation/HyperLab;
`doctor` reports the actual path. `HYPERLAB_CONFIG_DIR` is an optional explicit
configuration override for tests or independent profiles. The application never
writes measurements into the installation directory. Choose the previous project
`local` folder once if you want to continue using its data; no automatic migration
or hardware connection occurs.

If PowerShell blocks a source launcher, double-click the CMD file or use this
process-scoped invocation:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-HyperLab.ps1
```

Do not change the machine execution policy. The environment path is `.\.venv`,
not `..venv`. See [troubleshooting](TROUBLESHOOTING.md).
