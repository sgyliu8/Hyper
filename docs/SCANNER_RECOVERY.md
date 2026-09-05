# FP controller investigation — Phase 2

The imaging sensor is usable independently of FP scanning. H2 remains **BLOCKED**:
no verified state command, acknowledgement, settling or frame-state association
has been found. H3 additionally needs a matching response/reconstruction asset.
These are separate missing dependencies, not a reason to block live sensor work.

## Executed local investigation (2026-09-05)

Executable entry point, deliberately separate from lightweight Connect/refresh:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m hyperlab.controller.diagnostics --output local\diagnostics\scanner-investigation-new
```

`--snapshot PATH` reuses a previously captured PnP snapshot; `--asset-root PATH`
adds a specific authorized vendor/backup folder. Whole drives, broad system/user
roots, acquisition trees, symlinks and Windows reparse directories are excluded
from recursive search. The bounded search records examined counts, truncation,
warnings, candidates and exact private roots. It never opens serial, loads CTI,
executes a candidate binary or claims a filename is a supported ABI.

The actual run reused current-session
`local/diagnostics/phase2-baseline-pnp/snapshot.json` (15:50 BST). Its complete
IDs/containers/locations remain local. Three pertinent PnP nodes were present:
the healthy MATRIX VISION composite parent and USB3 Vision MI_00, plus a healthy
NXP LPC13xx VCOM lead currently assigned COM4. They share the host root hub but
use different downstream ports and containers. That supports a topology diagram,
not a physical association or serial protocol. Compatible-ID class evidence is
available; raw endpoint descriptors are not. No port was opened.

The expanded registry run is retained at
`local/diagnostics/scanner-phase2/expanded-registry-scope/scanner_report.json`.
It found three related uninstall records: the imaging driver plus two Impact
Acquire 3.7.2 package registrations. These are not three independent scanner
applications. Top-level filename discovery inspected Program Files (44 entries),
Program Files (x86) (25), ProgramData (29), local AppData (66), roaming AppData
(29) and Downloads (68). No HinaLea/TruTag/TruScope root or matching control/
calibration filename was found there. The related Balluff root contained **506
files examined**, no scan/calibration filename hits, no truncation and no access
warnings. Additional related-name inspection of local AppData/Programs returned
no lead. No university backup or old-disk directory has been supplied.

A second, content-level search of Balluff `.xml/.ini/.json/.h/.hpp/.txt/.cfg`
files for HinaLea, TruScope, TruTag, reconstruction matrix or Fabry returned no
match (`rg` exit 1, not a command failure). Receipt:
`local/diagnostics/scanner-phase2/installed-text-search.json`. The first receipt
remains intact; the expanded run corrected the asset match expression to include
the installed display name containing a space, `Impact Acquire`.

No plausible HinaLea library was found to justify exports/dependency/ABI analysis.
The executable contains bounded static PE architecture and keyword extraction
for future candidate files; it does not execute them. A missing name or string
is not proof that control/calibration data are absent from every binary or disk.
The Balluff runtime itself is established imaging software, not evidence of an FP
protocol. GenICam export is a **separate camera-session action**. The failures and
corrected scope below are evidence from the main acceptance run, not a serial
operation or a fabricated controller capability.

## Camera-node investigation and interruption

The first persistent-session benchmark attempt connected and read the reviewed imaging feature
list, but failed before streaming because a typed `ICategory` exposes its name
through INode, not a direct `.name` property. That receipt confirms zero frames
and successful normal release:
`local/diagnostics/phase2-camera-smoke/receipt.json`.

Its partial known-node evidence includes 1936×1216 geometry, zero offsets,
BayerRG color filter and available BayerRG/RGB formats. ReverseX/ReverseY were
unreadable, so CFA orientation was not assumed. BlackLevelAuto was Continuous;
exposure/gain/white-balance auto were Off. Firmware was 2.28.1323.0. A readable
AcquisitionFrameRate value of 4000 is a configured node value, **not measured
FPS**. These are imaging/processing features, not an FP state protocol. Full
identifiers and node values remain in the private receipt.

The second attempt fixed typed names but tried broad all-node value reads. A
native GenApi read did not return **before acquisition started**. The main run
terminated only its identified benchmark process and preserved
`local/diagnostics/phase2-camera-smoke-v2/interruption.json`. Frames received: 0;
graceful release: **NOT_CONFIRMED**. Read-only requests can still hang a vendor
driver; this interruption must not be described as successful node export.

The corrected exporter enumerates cached node names/types and reads values,
access state and ranges only for the reviewed `FEATURES` list. Unknown entries
are marked `NOT_READ_UNREVIEWED_NODE`; commands are never executed and selectors
are not changed. Offline tests cover typed names and refusal to read unknown
node values/access. This is deliberately a partial node description. XML is
**NOT_EXPORTED**, and actual execution of the corrected export is **PENDING**.

A third attempt could not reopen the imaging camera: AccessDenied / failure to
read GenCP MaxDeviceResponseTime. It received zero frames, retained its error and
did not confirm camera release because opening failed. Receipt:
`local/diagnostics/phase2-camera-smoke-v3/receipt.json`. At this checkpoint the
main run awaits physical reconnection before another normal imaging-session
attempt. No FP serial port, firmware reset or permanent setting was used as a
workaround. See [TEST_PLAN](TEST_PLAN.md) for the separate acceptance denominator.

## Public paths checked and useful new evidence

The finite public check revisited the supplied vendor documentation, official
HinaLea product pages, and a vendor-site query for TruScope/4200/SDK/download.
It did not locate a documented matching legacy FP command package. It does not
establish that such a package does not exist. Research records, dates and limits
are in the [Phase 2 source register](SOURCES.md#phase-2-source-recheck-2026-09-05).

The 2019/2020 patents reinforce separate calibrated reconstruction. The 2024
field-calibration patent uses prior full calibrations and reference measurements;
it is not a recipe for recovering an unknown unit from one white image.
These publications provide neither serial line coding nor HinaLea command bytes,
and do not grant a device-specific calibration or commercial implementation right.

Communication observation remains **NOT_TESTED**, because there is no known
normal controller application to observe. Windows CDC or NXP SDK examples are
not application protocol evidence. No baud sweep, newline/help command, DTR/RTS
toggle, EEPROM access or invented gap/voltage/home/reset command was attempted.

## Smallest assets that permit the next real action

1. **H0 association:** one readable chassis/interface photo, or an owner-known
   cable-to-interface observation captured with before/after PnP. Pure software
   cannot read an unseen physical label. This identifies the correct variant;
   it does not by itself unlock serial commands.
2. **H2 control:** one authorized, matching working TruScope/controller package
   with its headers/sample/API configuration, or a documented command protocol
   including line-control behaviour, state acknowledgement and acquisition
   synchronization. A specific backup folder is enough to restart bounded asset
   inspection. A calibration matrix alone does not establish safe control.
3. **H3 reconstruction:** the matching response/reconstruction matrix or callable
   reconstruction runtime, with state order, wavelength units, geometry/CFA and
   temperature applicability. If unrecoverable, known narrowband illumination,
   power reference and independent spectral standards are needed to recalibrate.

Once item 2 is verified, use the existing single imaging-session owner to switch
from preview to scanner mode. Record command, acknowledgement, stability interval,
buffer-drain/trigger rule and frame identity in order, preserving failed states.
Accept a `raw_scan` with state IDs and null wavelengths without waiting for H3.
If the controller requires a full recipe, preserve it. A generic time sequence
is never relabelled as that raw scan. Full-scan acquisition and independent
reconstruction remain NOT_TESTED until those dependencies exist.
