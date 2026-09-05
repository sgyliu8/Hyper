# Read-only device inventory

`python -m hyperlab probe --inventory` runs `scripts/Probe-Devices.ps1` and saves
`snapshot.json` plus a readable `inventory.txt` under a fresh
`local/diagnostics/<timestamp>/` directory. These private files can contain full
device identifiers. Do not commit them.

The snapshot includes every present USB/USBSTOR device and every present
Camera, Image, or Ports device. Hardware and compatible IDs, parent/container,
location, problem code, driver information, and associated service image paths
are recorded when Windows exposes them. USB class/subclass/protocol values are
parsed from Windows compatible IDs; they are not raw endpoint descriptors.
Unavailable serial numbers and endpoints remain `unknown`.

Software discovery reads related Uninstall registry entries, explicitly related
Program Files subdirectories, configured GenTL directories, and project `local`.
It does not use `Win32_Product` or scan unrelated personal folders. PE architecture
checks read file headers without loading libraries. The probe does not open a
camera or serial port, change DTR/RTS, load CTI/DLL code, or alter drivers.

Python API:

```python
from hyperlab.probe import run_inventory, load_snapshot, candidates, select_device, standard_interfaces, diff

path = run_inventory()                  # Windows only; returns snapshot.json
current = load_snapshot(path)
leads = candidates(current)             # identity leads, not verified hardware
interfaces = standard_interfaces(current)  # static classification only
# select_device(current, exact_instance_id) never accepts camera index 0
# changes = diff(load_snapshot(old_path), current)
```

For a cable comparison, retain a snapshot before and after the user's identified
physical action using the device's known connection procedure. `diff` reports
added, removed, and changed devices, including unrelated USB devices; it does
not invent physical association between the imaging module and a serial bridge.
Do not disconnect power or reset the device to produce a snapshot.

The verified 2026-09-05 inventory found the Matrix Vision composite device and
its USB3 Vision imaging interface, with code 28 and no interface driver, plus a
working Windows NXP serial bridge. The full HinaLea model and the serial bridge's
physical association remain unconfirmed. Static USB3 Vision evidence alone does
not establish a working runtime, a scanning API, or spectral calibration.

Validation: parser/selection/static-classification/diff tests pass; the Python
wrapper and PowerShell inventory ran on this Windows computer. An early probe
revision returned missing properties when querying an unavailable Windows key;
the corrected probe enumerates available keys and retains unavailable values as
`unknown`. Use the later verified snapshot identified in `HARDWARE_FINDINGS.md`.
