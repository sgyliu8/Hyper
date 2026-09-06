# HyperLab workbench — implemented UI contract

The default application is an English-only PySide6/pyqtgraph workbench for live
sensor imaging, saved-data analysis and reference/sequence records. This describes
current behavior and limits. Physical scanning/reconstruction remains unavailable
until supported control and calibration assets exist.

## Layout and navigation

The header shows device identity, source/display state, Connect camera,
Disconnect, Open data and Diagnostics. Acquisition, Analysis and Calibration
tabs switch the settings panel while preserving the image area. The common
action row contains Start preview, Stop acquisition, Save current frame, Record,
Freeze display, Fit, 1:1 and the settings-panel toggle.

The settings column is scrollable and constrained to 240–310 px. The primary
image occupies the expandable pane; a second pane shows derived numeric maps
with a color bar. Views may be linked; the raw view owns the aspect constraint to
avoid conflicting linked-range updates. A resizable chart sits below the images,
followed by the band/time selector, pixel values and metrics. The minimum window
is 960×620; launch size fits available screen geometry. Actual viewport fraction,
DPI behavior and readability need desktop observation, not inference from sizes.

The diagnostics dock exposes the local output directory and session/profile
evidence. Full identifiers stay in ignored local artifacts. Recent saves is a
list of up to 20 entries with reopen and two-file statistical comparison actions,
not a thumbnail gallery or a persistent project database. Comparison retains both
files' provenance, quality policy and MATCH/MISMATCH/UNKNOWN settings. It does not
assume spatial registration or attribute differences to a material cause.

## Acquisition semantics

Connect resolves the exact imaging target and starts one persistent camera
owner. Start preview streams to the latest-frame slot without recording. Stop
acquisition requests a real stop and restoration. Freeze display holds the shown
frame while acquisition may continue; it does not stop hardware. Save current
frame writes the exact owned frame shown, including frozen or retained frames
after stop. It does not silently capture another image.

Exposure is entered in milliseconds and converted to microseconds; gain is in
dB. Live ranges and actual readback appear after connection. Current format
choices are BayerRG12, RGB8 and BGR8, validated by the backend. Unsupported choices
fail visibly. Settings apply at the next start. Session readback does not claim
per-frame chunk evidence when chunks are unavailable.

Record requires a bounded count/duration and displays a disk estimate. Stop
recording preserves the prefix and permits preview to continue. Overflow, frame
gaps and write errors produce explicit partial results. Reopen accepts
`sequence.npy`, `sequence.npy.json` or its directory and shows time indices,
not wavelengths. Window close requests session shutdown and finishes file work
before closing, retaining a responsive Qt event loop while waiting.

Modes are EMPTY, LIVE, FROZEN, STALE, REPLAY and SYNTHETIC. Acquisition source is
shown alongside display mode. A retained live frame after stop is not evidence
of continuing acquisition. Capture, display and writer rates are separate; age
uses host monotonic receive time. Gaps, timeouts, preview replacement and writer
queue state remain separate metrics.

## Image and ROI behavior

Persistent row-major image items use raw pixel coordinates, aspect lock and a
downward image y axis. Pan/zoom/Fit/1:1 do not alter ROI sample coordinates.
Automatic 1–99% levels or locked limits affect display only. Saturation overlay
requires an evidenced threshold. Histogram and focus-gradient views are
descriptive, not optical-resolution or spectral-quality acceptance.

Raw DN and camera RGB are distinct from derived CFA-cell RGB. Bayer conversion
needs known phase/offset/flip evidence and may be unavailable when those nodes
are unreadable. Its reduced-resolution preview neither creates spectral
channels nor replaces the mosaic.

Two rectangular ROIs support move, resize, rename, show/hide and reset. The
secondary Edit ROI bounds action selects A/B and validates four integer half-open
raw-pixel bounds. These are two fixed slots; arbitrary ROI creation/
deletion is not implemented. Statistics/CSV retain amplitude and validity counts;
optional shape-normalized curves are separate. RGB statistics remain available
while spectral operations are disabled when the necessary axis is missing.

Analysis exposes PCA, SAM, difference and ratio through shared capability gates.
Derived maps retain the source used for the operation; a source change invalidates
the old product. Numeric NPY/ENVI export and display PNG are separate actions.
Invalid map values remain masked/transparent. A sequence is browsed frame by frame
and summarized as time data, never as a pseudo-spectrum.

## References and calibration limits

Calibration registers saved immutable dark/reference/sample files with labels
and entered conditions, writes local records, compares known settings and
summarizes a loaded sequence. Unknown illumination/geometry stays unknown.
Registration does not establish reflectance calibration. Reference selection is
held in the running UI; a full persistent catalog/reload workflow is not yet
implemented.

FP control, unit-specific reconstruction, calibrated color difference,
temperature estimation and model training are not implemented UI features.
An independently supplied, evidenced spectral cube may be analysed without
claiming this instrument produced it.

## Evidence status

The earlier baseline is retained under `local/diagnostics/ui-phase2/` as
`before-tk.png`, `before-tk-real.png` and `before-tk-roi-export.png`. Actual English
Qt replay, ROI drag/CSV, raw copy/reopen, numeric export and display PNG workflows
passed on the current 125% desktop. `final-english-roi.png`,
`final-english-derived.png` and `after-english-save-reopen.png` show those workflows.
The advanced ROI edit was actually applied as `(400,389,736,693)`; its dialog and
result are in `final-roi-precision-dialog.png` and `final-roi-precision-applied.png`.
`final-saved-comparison.png` tests the two-file flow using two copies of the same
historical frame. This is a UI control check, not two independent acquisitions.
`final-sample-registration.png` verifies registration of the opened saved copy:
its current path is distinct from retained original-source provenance, its kind
is sample, and unentered physical conditions remain unknown.
The current screen is 2048×1152 logical pixels, device pixel ratio 1.25; other
resolution/scaling combinations are NOT_TESTED. Final paths/results belong in
[HANDOFF](../HANDOFF.md). Offline Qt
checks cover interaction/data semantics, not sustained camera/display timing,
physical stop/close or high-DPI inspection. Hardware failures and outstanding
checks are recorded in [TEST_PLAN](../TEST_PLAN.md).
