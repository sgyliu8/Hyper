# HyperLab: HinaLea instrument recovery

The imaging interface is restored: the approved Balluff Impact Acquire 3.7.2
installation completed without a reboot, Windows reports code 0, and the
mvBlueFOX3-M2024C module delivered real 1936×1216 RGB8 and BayerRG12 frames.
Transport bytes, NPY samples, metadata and previews were saved locally; stop,
release and saved-array readback succeeded. Session settings were restored.

**H1 sensor-image acquisition passes**, including the user-confirmed full-lens
occlusion comparison at matched settings. **Full hyperspectral recovery remains
incomplete.** H0 identity is PARTIAL because chassis labels and the second cable
association remain incomplete. H2–H4 are BLOCKED by the unknown
HinaLea scanner interface and this instrument's wavelength/reconstruction
calibration. The separate NXP LPC13xx VCOM interface remains unassociated and
unopened. An RGB image or Bayer sensor plane is not a hyperspectral cube.

See [HANDOFF](HANDOFF.md), [hardware findings](docs/HARDWARE_FINDINGS.md),
[sources](docs/SOURCES.md) and [acceptance plan](docs/TEST_PLAN.md).

## Start on this computer

PowerShell, working directory `C:\Project\HyperSpectral`:

```powershell
Set-Location C:\Project\HyperSpectral
.\.venv\Scripts\python.exe -X utf8 -m hyperlab doctor
.\.venv\Scripts\python.exe -X utf8 -m hyperlab probe --inventory
.\.venv\Scripts\python.exe -X utf8 -m hyperlab probe --standard-interfaces
.\Start-HyperLab.cmd
.\.venv\Scripts\python.exe -X utf8 -m hyperlab demo
```

`Start-HyperLab.cmd` can also be double-clicked. It opens the GUI and returns the
terminal immediately, without changing PowerShell execution policy. The Python
path is `.\.venv\Scripts\python.exe` (not `..venv\Scripts\python.exe`).
To run the GUI directly in the current terminal, use
`.\.venv\Scripts\python.exe -X utf8 -m hyperlab app`.
If using the PowerShell launcher, invoke it with
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-HyperLab.ps1`;
this policy applies only to that child process. Do not copy terminal prompts such
as `PS C:\...>` or `>>` into commands.

`demo` explicitly generates SYNTHETIC data. `app` starts without opening a camera.
All new private diagnostics and outputs go under `local/` and stay out of Git.
The exact executed environment uses Python 3.11.9 x64, NumPy 2.4.6, Matplotlib
3.11.1 and Pillow 12.3.0. Harvester 1.4.3 / GenICam 1.6.0 are installed in .venv;
their presence does not supply a Windows USB3 Vision driver.

For a fresh checkout:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test,camera]'
.\.venv\Scripts\python.exe -m pytest -q
```

MATLAB R2025a and Image Acquisition Toolbox are present, but actual `imaqhwinfo`
returned `InstalledAdaptors: {}`. Python/Tk is the one maintained GUI; switching
languages would not supply the missing FP protocol or spectral calibration.

## Capture on this computer

The installed and signature-verified x64 producer is
`C:\Program Files\Balluff\ImpactAcquire\bin\x64\mvGenTLProducer.cti`.
Run from an ordinary PowerShell in the project directory; each command creates a
new timestamped private output directory:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Capture-CandidateFrame.ps1 -CtiPath 'C:\Program Files\Balluff\ImpactAcquire\bin\x64\mvGenTLProducer.cti'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Capture-CandidateFrame.ps1 -CtiPath 'C:\Program Files\Balluff\ImpactAcquire\bin\x64\mvGenTLProducer.cti' -PixelFormat BayerRG12 -ExposureUs 100000 -Gain 0
```

The first command preserves current format/exposure/gain. The second requests one
BayerRG12 sensor plane at 100 ms and gain 0, validates the camera's available
format and parameter ranges, reads back the session settings, and restores their
previous values after acquisition. The live test restored RGB8 / 20 ms / gain 0.
No UserSet is saved and no FP controller is commanded. Current enabled trigger
or test-pattern settings stop acquisition with an explanation.

The wrapper selects the one observed VID/PID/MI imaging interface; the CLI
re-probes, requires code 0, derives its parent serial privately and opens exactly
that USB3 Vision mvBlueFOX3. Fetch timeout is five seconds. A session saves
`transport_payload.bin`, `frame.npy`, `frame.npy.json` and `preview.png`, then
stops/releases and checks the reopened NPY shape/dtype. Bayer samples remain a
single HW mosaic; RGB/BGR samples use HWC color channels with no wavelength axis.

The equivalent CLI is `python -m hyperlab acquire --device <exact-local-PnP-ID>
--single-frame --cti <installed-producer-path>`. Optional session arguments are
`--pixel-format BayerRG12 --exposure-us 100000 --gain 0`; the wrapper above avoids
copying full device IDs into commands. `--recipe` is rejected before device access
because no HinaLea scan recipe is verified. H1 physical acceptance was verified
with user-confirmed full-lens occlusion: at matched BayerRG12/100 ms/gain 0, mean
intensity changed from 817.57 to 4.60 DN. This verifies sensor imagery and the
optical path, not FP scanning or spectral measurements.

The guarded `scripts/Install-ReviewedRuntime.ps1` has already run with recorded
approval and exit code 0; its private receipt is
`local/diagnostics/install-20260905T132833738.log.json`. Reinstallation is not the
next recovery step. Original failure receipts are retained in the hardware report.

## Offline use

```powershell
.\.venv\Scripts\python.exe -m hyperlab inspect local\synthetic\initial\demo.npy
.\.venv\Scripts\python.exe -m hyperlab app local\synthetic\initial\demo.npy
.\.venv\Scripts\python.exe -m hyperlab app local\acquisitions\scene-ready-rgb\frame.npy
.\.venv\Scripts\python.exe -m hyperlab inspect your-array.npy --axis-order KHW
.\.venv\Scripts\python.exe examples\generate_synthetic.py
```

The desktop app opens ENVI HDR+binary (BSQ/BIL/BIP), NPY+JSON and NPZ. Unmapped arrays
require an explicit axis order; ambiguous NPZ requires its dataset name. Use the
band/state slider, three composite indices, and two half-open rectangle ROIs
`x0,y0,x1,y1`. ROI curves/CSV contain mean, population standard deviation and valid
count. Buttons provide difference, ratio/invalid mask, sampled PCA and angle to ROI1.
Angles are radians; without wavelength evidence the comparison is a state-vector
difference. Scores are descriptive, not defect diagnoses. Composite is display RGB,
not a colorimetric calibration. The GUI exports ROI CSV files. Derived maps/masks
are available through the analysis API; GUI export of those arrays is not implemented.

The GUI distinguishes LIVE / REPLAY / SYNTHETIC explicitly. Single-frame access
is gated by the reviewed producer and exact device; unsupported scan and GUI
exposure/gain controls remain disabled. Session exposure/gain are supported by
the CLI and wrapper above. RGB/BGR frames display as color data, with spectral
analysis controls disabled. Background analysis keeps the UI responsive; Stop discards a pending background result, it does not
pretend to interrupt a native device call. Single-frame calls have a bounded timeout.

Large NPY/ENVI arrays use memmap and analysis uses bands/chunks/sampled PCA. NPZ must
materialize the selected array; convert large data to NPY/ENVI first. No automatic
HDF5/MAT/TIFF or proprietary DAT interpretation is claimed. See
[examples and API contracts](examples/README.md) and [architecture](docs/ARCHITECTURE.md).

Reflectance processing is available as a Python analysis function only for data with
an evidenced wavelength axis, linear intensity and matching acquisition/reference
conditions. It subtracts dark values in floating point, masks saturation/low
denominators and does not silently clamp output. It cannot recover missing FP mapping.

## Privacy and Git

The remote `sgyliu8/Hyper` was verified public and empty before initialization.
Only source, redacted documentation, lightweight tests and synthetic generators
are eligible for publication. `local/`, .venv, raw images, calibration, installers,
full serials, licenses and diagnostic logs are ignored. No public real dataset is
downloaded. No model training, PatchCore, cloud service or database is included.
