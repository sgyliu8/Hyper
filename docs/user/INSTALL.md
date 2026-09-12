# Install HyperLab

## Choose an entry point

| Mode | Requirements | Qualification |
|---|---|---|
| Offline / demo | Windows x64, Python 3.11, or the evaluation desktop ZIP | No camera or manufacturer runtime required |
| Image acquisition | Above plus official USB3 Vision driver, Balluff Impact Acquire 3.7.2, Harvester 1.4.3 | Experimental; qualify the selected recording mode and actual setup |
| Spectroscopy | Verified FP control, synchronization and device-matched reconstruction/calibration | Not recovered |

Original-code licensing is undecided. The following are evaluation installation
instructions, not a public-release or redistribution authorization. The release
candidate is `feature/materials-science-v040`; default clone currently
selects the older `recovery/hinalea-local` branch.

## Source installation (ordinary user)

Install Python 3.11 x64 and Git, then in PowerShell:

```powershell
git clone --branch feature/materials-science-v040 --single-branch https://github.com/sgyliu8/Hyper.git
cd Hyper
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m hyperlab doctor
.\Start-HyperLab.cmd
```

This is a normal, non-editable install. Reinstall with `pip install .` after a
source update. For acquisition only, install `.[camera]` into this environment.
Do not copy someone else's virtual environment. No test packages are required.
For a reproducible installation, use the source commit recorded in the supplied
BUILD.json or build receipt. An online branch may be older than a local candidate.

## Wheel installation

A wheel is built from a clean exact commit using `python -m build --wheel`.
Use the actual `.whl` file from the local build evidence, then:

```powershell
py -3.11 -m venv "$env:USERPROFILE\HyperLabEnv"
& "$env:USERPROFILE\HyperLabEnv\Scripts\python.exe" -m pip install C:/path/to/hyperlab-VERSION-py3-none-any.whl
& "$env:USERPROFILE\HyperLabEnv\Scripts\python.exe" -m hyperlab demo
```

The path to the wheel is an explicit placeholder, not an author-specific required
location. Runtime resources are in the installed package. Running from another
working directory does not create an accidental `local/` folder there.

## Windows desktop evaluation ZIP

The desktop ZIP contains the Qt workbench. The optional legacy Tk interface is
available only in a source/Python installation with Tk installed.

Extract the entire HyperLab folder and keep `_internal` beside `HyperLab.exe`.
Run `Start-HyperLab.cmd` or `HyperLab.exe app`. No Python installation is required.
`HyperLab.exe doctor` prints runtime and workspace information. The ZIP contains
Python/Qt libraries and their notices, but no Balluff driver, CTI or private data.
The console build retains startup errors for troubleshooting.

### Move the camera to another Windows computer

1. Extract/copy the **complete** supplied desktop folder. A CMD file alone does
   not contain the application; HyperLab.exe requires its adjacent _internal
   directory. Do not copy a Python virtual environment or old device settings.
2. On the destination PC, install the official **Impact Acquire x64** package
   with **USB3 Vision support**. Version 3.7.2 was used on the development host;
   a different release requires checking on that PC. The runtime, its native
   dependencies and the Windows camera driver are separate from HyperLab.
   Use [Balluff downloads](https://www.balluff.com/en-de/downloads/software).
3. Close/reopen HyperLab after installation. Connect the camera's imaging data
   cable to a suitable USB data port. Port shape alone does not establish USB
   speed or a data-capable cable. Close other applications that own the camera.
4. Run **Check-Camera.cmd**, or **Hardware setup… → Check this computer**.
   Both inspect current Windows devices, x64 CTI architecture and OEM signature
   without loading a producer or opening any camera/serial port.
5. If automatic discovery misses a custom installation, use **Browse CTI…** and
   select its mvGenTLProducer.cti, usually under bin/x64. Check this computer
   saves the choice for this user. Clear the path to restore automatic discovery.
6. When a supported candidate is available, close setup, click **Connect camera**,
   then **Start preview**. This is the explicit native-device test.

The imaging module uses USB3 Vision. The separate NXP COM port is listed as an
unverified control lead; its number may change between computers or USB ports.
It is not used for image acquisition, and does not need to be COM4. Each Connect
reads current PnP identity and uses the camera serial, never a saved USB socket
location or a camera index. Multiple cameras require explicit selection.

For Windows error 28, install the USB3 Vision driver. If another vendor's driver
owns the imaging interface, follow [Balluff's driver-binding instructions](https://assets.balluff.com/documents/DRF_957356_AA_000/Troubleshooting_Windows_USB3VisionDeviceIsNotShownOrCannotBeUsed.html)
for that imaging interface. Do not bind the controller COM port to a camera driver.
The official package supplies the [native runtime and driver components](https://assets.balluff.com/documents/DRF_957353_AA_000/InstallationFromPrivateSetupRoutines_Windows_NonMSI_GEV_U3V_PCIe.html);
copying a CTI file alone is not a complete installation.

Reports contain connection-report.txt, connection-report.json and the underlying
PnP snapshot. Their private location is shown in setup and the console. Failed
connections also save a connection-error JSON alongside session phase evidence
in the data workspace. Keep these files when reporting a failure; nothing is
uploaded automatically. READY_TO_CONNECT is static readiness, not a verified frame.

CLI equivalent: HyperLab.exe hardware-check (exit 0 for a candidate, 2 when setup
needs attention). Add --output NEW_DIRECTORY for an explicit report destination
or --cti PATH for a one-time runtime check.

The local acceptance distinguishes same-machine independent installation from a
new Windows machine. A successful offline installation does not qualify a camera, driver or clean
physical Windows machine. Check the supplied artifact hash and BUILD.json;
there is no authorized public binary release yet.

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
