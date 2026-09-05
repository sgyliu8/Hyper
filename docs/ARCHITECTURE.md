# Minimal software and data contract

PowerShell inventories Windows; Python orchestrates persistence and analysis;
Tk/Matplotlib is the only GUI. Harvester is a thin optional GenTL frontend for the
identified OEM imaging family, subject to installed-driver and exact-target gates.
There is no HinaLea SDK shim or guessed serial/FP command implementation.

`probe.py` only runs `Probe-Devices.ps1` or parses snapshots. It never imports a
native acquisition module. `adapters/gentl.py` is explicitly acquisition-mode:
installed OEM location, x64 PE and signature check, exact serial/model/U3V selection,
read current nodes, bounded single-frame start/fetch/stop/destroy. Unsupported
trigger/test-pattern/pixel formats fail clearly. Optional RGB8/BGR8/BayerRG12,
exposure and gain are validated against live node availability/ranges, applied
for that session, read back and restored in `finally`. Trigger, UserSet and FP
controller settings are not changed. Producer signature review prefers `pwsh`
and avoids the incompatible inherited module path in Windows PowerShell fallback.

`acquisition/ScanWriter` creates an exclusive directory and preallocated memmapped
`cube.npy` in H,W,state order. Each valid appended frame flushes before an atomic
`cube.npy.json` checkpoint advances `frame_count`. Metadata preserves ordered
per-frame records and `expected_frames`; readers expose only the saved prefix.
Stop, errors and disconnect preserve partial. A real scanner is not implemented;
the software sequence fixture is always labelled SYNTHETIC.

Four levels remain distinct: raw_frame (HW sensor plane or HWC camera-color frame),
raw_scan (HWK states),
spectral_cube (evidenced wavelength/reconstruction axis), reflectance_cube (matched
references and stated relative/reference calibration). Wavelengths, units,
calibration, effective bits and unknown fields remain explicit null/unknown.
No `linspace` creates a real wavelength axis. Original Bayer mosaic stays one
sensor plane, not four spectral channels. RGB/BGR has a named color-channel axis,
not wavelengths. A separately stretched preview never replaces the saved samples.

Single-frame output: `transport_payload.bin`, `frame.npy`, `frame.npy.json`,
`preview.png`. The native bytes preserve PFNC packing; NPY stores its losslessly
expanded samples. Receipt records original pixel format, shape/dtype, frame ID,
device and host times, exposure/gain, firmware/runtime, source, validity, stop,
release, any session-setting restoration and saved-array shape/dtype readback.
The reviewed runtime has delivered RGB8 and BayerRG12 frames on this computer;
private execution receipts are listed in HARDWARE_FINDINGS.md. A separate later
scene-validation receipt records the matched-settings, user-confirmed occlusion
comparison that passed H1. The original frame receipts retain their initial
NOT_TESTED scene field; the later acceptance does not relabel raw records or
establish spectral calibration.

The UI consumes Cube(data H,W,K, metadata, valid_mask). It shows source and
hardware status before operations; unsupported controls are disabled. RGB/BGR
raw-frame display uses its color channels and disables spectral-analysis actions.
The GUI exports ROI CSV; derived maps/masks are available through the analysis
API and do not currently have a GUI array-export action. Background
threads return through a queue polled by Tk. Stop discards background analysis
results; it does not misreport native-call cancellation. No automatic LIVE fallback.

NPY/ENVI stay memory mapped; ROI loops bands, PCA samples at most 10,000 pixels
and transforms chunks, SAM processes chunks. NPZ loads its chosen array into
memory and says so. Missing/ambiguous axes or datasets require explicit selection.
No database, network service, second GUI or model framework is involved.
