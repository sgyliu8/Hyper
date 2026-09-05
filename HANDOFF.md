# HyperLab recovery handoff — 2026-09-05

## Current outcome

**Real sensor imaging is recovered; hyperspectral scanning is not recovered.**
The user separately approved the reviewed Balluff USB3 Vision installation. It
finished with exit 0, no reboot, and the imaging interface changed code28 to code0.
No firmware, EEPROM, UserSet, permanent calibration or NXP serial command was written.

| Milestone | Status | Actual evidence |
|---|---|---|
| H0 physical identity/interfaces | PARTIAL | PnP identifies mvBlueFOX3-M2024C; chassis labels unavailable; NXP cable association unknown |
| H1 real image save/reopen and physical response | PASS | RGB8 plus BayerRG12; user scene preparation and full-lens occlusion; normal stop/release and restored settings |
| H2 supported raw spectral scan | BLOCKED | NXP LPC13xx VCOM present but protocol, states and trigger association unknown; NOT_TESTED |
| H3 wavelength/reconstructed cube | BLOCKED | No unit-specific mapping/reconstruction calibration; NOT_TESTED |
| H4 reflectance product/repeatability | BLOCKED | H3 plus matched references absent; NOT_TESTED |

H1 is specifically sensor-image acceptance. It does not identify the full HinaLea
variant or establish narrowband transmission, spectral accuracy or temperature.

## Private evidence on this computer

- Initial valid inventory: `local/diagnostics/20260905T131703438/snapshot.json`.
- Installed-driver inventory: `local/diagnostics/20260905T132950698/snapshot.json`;
  GUI refreshed actual hardware at `local/diagnostics/20260905T134425058/snapshot.json`.
- Installer: `local/diagnostics/install-20260905T132833738.log.json`, exit0/no reboot.
- Static provenance: `local/downloads/driver-review/readiness.json` and
  `local/downloads/cti-review/review.json`; installed CTI equals the signed package payload.
- Capability read-only result: `local/diagnostics/pixel_capabilities_20260905T123613Z.json`.
  BayerRG12 is available; Mono12 is not; test image/pattern are Off. No scanner opened.
- Real RGB: `local/acquisitions/scene-ready-rgb/frame.npy` plus sidecar/payload/preview.
- Real Bayer: `local/acquisitions/scene-ready-bayer12/frame.npy` and
  `local/acquisitions/occluded-bayer12/frame.npy`, with separate complete receipts.
- Optical acceptance: `local/diagnostics/scene-validation.json`.

Both Bayer frames have 1216×1936 uint16 samples, BayerRG12, exposure100000µs,
gain0dB. Mean DN changed **817.567 → 4.599** under user-confirmed occlusion
(ratio0.00562564). Device timestamps differ; each new session starts frame_id0,
so do not claim a global monotonically increasing frame counter. Both stop/release,
saved-array reopen and restoration to RGB8/20000µs passed. The scene frame has
1.686% saturation; it is connectivity/optical evidence, not a calibrated research
measurement. Raw data were retained without clipping. Acquisition-time sidecars
retain the original scene-validation NOT_TESTED field; the later comparison is
the independent H1 acceptance receipt and does not rewrite original evidence.

## Software and verification

Python3.11.9 x64 .venv, NumPy2.4.6, Matplotlib3.11.1, Pillow12.3.0;
Harvester1.4.3 / GenICam1.6.0 over installed Balluff Impact Acquire3.7.2.
MATLAB R2025a Image Acquisition Toolbox exists but had no adaptors.

Implemented and locally verified: read-only Windows probe/comparison; exact-device
gate; explicit single-frame control with optional transient format/exposure/gain;
raw byte/sample/metadata saving and reopen; partial scan persistence (software
fixture only); ENVI BSQ/BIL/BIP, NPY/NPZ; ROI/CSV, composite, PCA, SAM, difference,
ratio and masks; strict reference correction on appropriately evidenced inputs.

**56 offline pytest tests PASS**, latest receipt `local/diagnostics/offline-tests.txt`.
Tk callback/window checks are recorded under `ui_smoke_20260905T1326` (19 checks),
`ui_color_smoke_20260905` (11) and `ui_session_controls_smoke_20260905` (15).
These are separate software checks, not extra hardware passes. Normal desktop
Computer Use observed actual windows and exercised synthetic ROI and PCA, then
opened actual RGB/Bayer saved files. Final GUI capture validation is recorded in
the closing addendum below when completed.

Failures preserved: initial code28 rejection; legacy Windows PowerShell module
autoload failure (fixed using pwsh); initial unsupported RGB8 payload retained
then properly mapped HWC/color channels; strict read-only Harvester session tried
to create a stream and was replaced by lower-level read-only NodeMap access;
pythonw signature-output decoding failure (fixed explicit UTF8 and verified in
pythonw without a console). No failure was relabelled as successful acquisition.

## Run now

```powershell
Set-Location C:\Project\HyperSpectral
.\scripts\Start-HyperLab.ps1
.\.venv\Scripts\python.exe -m hyperlab probe --inventory
.\scripts\Capture-CandidateFrame.ps1 -CtiPath 'C:\Program Files\Balluff\ImpactAcquire\bin\x64\mvGenTLProducer.cti' -PixelFormat BayerRG12 -ExposureUs 50000 -Gain 0
```

The GUI reads the installed CTI path; click Refresh, then select format and optional
exposure/gain, then Single frame. Blank optional values preserve current settings.
Each requested setting is checked against live device capability/range and restored
afterwards. Scanning remains disabled. The saved image is shown as REPLAY, distinct
from a live stream. User scene actions are finished; the lens occluder may be removed.

## Remaining blocker and smallest next asset

The next missing capability is the **HinaLea FP scanner control interface**, not
the OEM sensor driver. A working authorized TruScope/controller copy with its
API/config/calibration, or an explicit protocol plus this instrument's wavelength
mapping/reconstruction data, is needed. Public searches found no usable matching
4200/4200C package; a reported 4250 C++ SDK is a lead, not compatibility proof.
The NXP COM port remains unopened because baud, line signals and commands are
unknown. Do not guess them, and do not use a newer model's recipe or 450/299 counts.

When available, first identify the chassis and map the second data cable using a
known physical procedure, then statically inspect authorized assets. No more
physical action is required to use the restored single-frame imaging path today.

## Git and privacy

Remote was verified public and empty: `https://github.com/sgyliu8/Hyper.git`.
Work branch: `recovery/hinalea-local`. Only reviewed source, redacted docs, tests
and synthetic generators are staged. All raw frames, serials, logs, proprietary
binaries, installer components and .venv remain ignored in local/. Publication
and hosted CI result are recorded in the closing addendum; no merge/force-push.

## Closing addendum

The final normal GUI was restarted with the repaired UTF8 signature-reader path.
Computer Use clicked Connect (read-only) and Single frame on the actual window.
It acquired a new real RGB8 frame and reopened/displayed it successfully:
`local/exports/raw_frame_20260905T135317666950/frame.npy` with complete raw payload,
metadata and preview. Receipt confirms stop/release/reopen, original RGB8/20ms/0dB,
test patterns Off and a new device timestamp. GUI shows R/G/B color channels,
REPLAY of the saved LIVE image, and disabled spectroscopy. The actual screen is
saved privately as `local/diagnostics/gui-real-capture.png`. **GUI real capture PASS**.
The earlier pythonw failure was a text-decoding fault before device access; the
fixed explicit UTF8 path was verified both in pythonw and through this actual click.

Code checkpoint **80d572d** was pushed to `origin/recovery/hinalea-local`.
GitHub offline validation passed at
https://github.com/sgyliu8/Hyper/actions/runs/33967270876 . The following handoff-only
checkpoint records these receipts without changing the tested acquisition code.
This was an empty remote: the first pushed branch became its default; there is no
separate base branch for a Draft PR. No branch was merged and visibility stays public.
Live hardware evidence and binary assets remain local and were not uploaded.
