# Verification and acceptance — Phase 2

Offline tests, real desktop interaction and physical camera acceptance are
separate evidence streams. Phase 2 source **`e80079a` passed 189 offline tests on
Windows in 9.77 s** and **189 tests in Linux CI** ([run 33978247352](https://github.com/sgyliu8/Hyper/actions/runs/33978247352)).
The English Qt workflows recorded in [HANDOFF](../HANDOFF.md) passed on the current
Windows desktop at **125% display scaling only**; other display configurations
remain NOT_TESTED. Complete desktop/hardware acceptance remains PARTIAL, and
**persistent real-camera acceptance is BLOCKED awaiting physical USB reconnect**.
The earlier 56-test/Tk checkpoint and its CI are historical evidence, distinct
from these Phase 2 results. Unexecuted hardware and XML gates remain explicit below.

## Offline verification

Run in the project `.venv`:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

Tests use synthetic arrays, temporary files, fake GenTL objects and Qt widgets.
They do not load a producer, open serial, install drivers, fetch real frames or
download datasets. CI runs this suite on Python 3.11 with Qt offscreen; a
workflow file is not evidence of a successful hosted run. Clear the process
variable before real desktop launch if reusing that PowerShell process.

| Coverage | Failure or invariant checked |
|---|---|
| Probe/controller diagnostics | Exact identity/health, invalid snapshots, shared hub not physical association, bounded roots, truncation, acquisition-tree exclusion |
| I/O and axes | NPY/ENVI layout/endian/offset/masks, standard BBL/ignore/units, conflicts, independent Spectral Python reader, time sequence rejected as spectral cube |
| Analysis/quality | Common features, all-invalid/insufficient data, zero vectors, selected-band completeness, saturation policy/counts, precision, reference provenance and real zero values |
| Out-of-core products | Output budget, reopen content, partial failure, released Windows handles, numeric products/provenance |
| Frame/sequence | Owned immutable pixels/metadata, THW/THWC content, durable checkpoints, no overwrite, overflow/disk failure/frame gap, duration, exact displayed-frame snapshot |
| Native lifecycle | Injected start/fetch/incomplete/decode/size/stop/restore/destroy faults, single requeue, no borrowed-buffer use after return, primary error retained, independent restoration |
| Camera API | Fake persistent start/stop/restart, latest replacement, snapshot/recording, cooperative close, ready-only configuration |
| Node diagnostics | Typed names use INode; unreviewed nodes never read values/access; commands never execute |
| Qt | ROI raw coordinates under zoom/pan/band change, capability gates, product source, stopped snapshot, actual-readback/status schema, sequence replay, busy-reader guard, release before close |
| Experiments | Settings MATCH/MISMATCH/UNKNOWN; temporal results compared with independent stacked calculations |
| Replay identity | Selected mono/RGB time frames save/reopen without inherited T counts; opened NPY/NPZ/ENVI copies register their actual path while preserving earlier declarations |
| Saved comparison / precision | Equal geometry/channel contract, masks/quality/settings/handle release; half-open numeric ROI edits preserve view, other ROI and hidden state |

Fake-producer success does not validate particular firmware, USB health, native
timeouts or achievable FPS. Qt tests verify callbacks/state; desktop geometry,
DPI, mouse/keyboard interaction and sustained responsiveness require observation.

## Desktop acceptance

Actual earlier Tk baseline screenshots are retained locally:

- `local/diagnostics/ui-phase2/before-tk.png`
- `local/diagnostics/ui-phase2/before-tk-real.png`
- `local/diagnostics/ui-phase2/before-tk-roi-export.png`

The English Qt workbench replaces that baseline. Actual replay, ROI dragging,
CSV, raw copy/reopen, difference export and display PNG workflows passed on the
current Windows desktop at 125% scaling. The numeric copy and difference were
compared against source pixels; both ROI means were independently recomputed.
Private evidence: `ui-phase2/export-verification.json`, `final-english-roi.png`,
`final-english-derived.png`, `after-english-save-reopen.png` and
`display-environment.json`. Other resolution/scaling combinations are NOT_TESTED.
Final paths/results belong in HANDOFF. Native sample registration also passed,
including the opened-copy identity and retained original-source provenance.
Remaining checks include other display configurations, sustained time-sequence
interaction and live transitions among LIVE/FROZEN/STALE. Offline files stay
labelled as REPLAY or SYNTHETIC, with acquisition source retained separately.

Hardware-connected GUI acceptance additionally checks preview, freeze, exact
current-frame save, bounded recording/reopen, stop and window close. Measure
display FPS, frame age and UI delay from actual events. Headless polling is not
displayed FPS; a 33 ms timer does not establish a 30 FPS camera.

## Explicit hardware acceptance

`hyperlab.benchmark` is opt-in, with no acquisition on import. Use a new output
directory for every run. A short invocation is:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m hyperlab.benchmark --hardware --output local\diagnostics\camera-new-run --seconds 10 --cycles 1 --record-frames 5
```

Only extend the run after confirming connection, frames, snapshot persistence,
recording content and release. Extended checks include sustained preview/memory,
bounded recording, ten start/stop cycles, age/gaps, responsive stop and close
while recording. Requested durations/cycles are not completed results. Preserve
exceptions and incomplete denominators; process interruption is not graceful stop.

The current-turn legacy Tk baseline saved/reopened one real RGB8 frame. The
three subsequent persistent CameraSession benchmark attempts produced **zero
real frames** and no valid sustained-performance measurement. Their scopes stay
separate:

| Receipt under `local/diagnostics/` | Observed result |
|---|---|
| Baseline frame outside that diagnostics root: `local/exports/raw_frame_20260905T155322198944/frame.npy` | Single-frame PASS in legacy Tk: RGB8, 1216×1936×3 uint8; sidecar confirms save/reopen, stop and release; not a persistent-preview result |
| `phase2-camera-smoke/receipt.json` | FAIL before stream: typed category lacked direct `.name`; reviewed feature reads and normal release succeeded |
| `phase2-camera-smoke-v2/interruption.json` | INTERRUPTED before start during broad node-value export; native read did not return; graceful release NOT_CONFIRMED |
| `phase2-camera-smoke-v3/receipt.json` | FAIL opening camera: AccessDenied / GenCP MaxDeviceResponseTime register read; no session/frames; physical reconnect pending |

The exporter now uses cached names/types plus reviewed `FEATURES` values;
unknown node access/value reads are omitted. **Corrected real node export is
PENDING; XML is NOT_EXPORTED.** Offline regression coverage exists. Live acceptance
awaits successful communication after physical reconnection. Prior H1 sensor-image
evidence remains historical evidence, not proof of current link health.

## Physical gates and closeout

| Gate | Evidence required | Current scope/status |
|---|---|---|
| H0 | Chassis model/ports and physical interface association | PARTIAL; unseen labels/control-lead association unknown |
| H1 | Exact real frame, raw samples/metadata, reopen, scene response and normal release | Earlier PASS retained; Phase 2 persistent-session acceptance BLOCKED awaiting USB reconnect |
| H2 | Supported recipe, acknowledgement/settling, fresh frame-state association and full/partial/stop | BLOCKED; real scan NOT_TESTED |
| H3 | Matching reconstruction and evidenced wavelength axis with stated external validation | BLOCKED; real reconstruction NOT_TESTED |
| H4 | Matched references/settings, masks, repeatability and appropriate accuracy evidence | BLOCKED; physical reflectance validation NOT_TESTED |

Closeout records exact revision, suite count/output, dependencies, real desktop
artifacts, completed hardware duration/counts, cleanup, preserved failures and
hosted CI status. Offline PASS does not upgrade H0–H4, and OEM Bayer/RGB frames
do not establish spectroscopy. [SCANNER_RECOVERY](../SCANNER_RECOVERY.md) identifies
the smallest missing control/calibration assets.
