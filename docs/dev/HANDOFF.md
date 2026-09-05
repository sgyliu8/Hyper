# Current handoff — ROI/display follow-up; historical Phase 3 below

The owner subsequently authorized a real imaging/UI follow-up for the Compare
ROIs error and chart styling. See [0.3.1 live ROI follow-up](ROI_LIVE_FIX.md) for
its separate results. The Phase 3 evidence below remains a historical closeout;
its no-new-session scope does not cancel the newer explicit authorization.

The follow-up fixes immutable live-frame ROI metadata copying and single-plane
plots, verifies real saved-frame/figure numbers and 20-frame recording, and
improves native event polling/display. Its source/package/test results and all
normal camera releases are tracked in ROI_LIVE_FIX.md and ignored local evidence.
H1 has new bounded imaging evidence; long-duration/recovery qualification and
H2–H4 are still outstanding. The historical gate table below is not current H1.
The final 0.3.1 package (source e809135) passed 229 offline tests and its own
1,803-frame native imaging check, 20/20 recording, real ROI/figure export and normal
settings restoration/release. The delivered window shows actual frame 1261 with
ROI plots in REPLAY. The earlier e06345b 2,512-frame run remains separate evidence.

Baseline: `feature/live-workbench-v2@2d9083533a2e367e6543748f97753da02b1a0713`.
Working branch: `feature/scientific-workbench-portable-v3`.
The owner deferred original-code licensing. Keep public release pending.

Software implementation and the bounded offline delivery are complete; hardware
qualification and public release remain separate, as recorded below.
See [review matrix](REVIEW_PHASE3.md), [user entry](../../README.md),
[release evidence](RELEASE_PLAN.md) and [scientific contract](PHYSICS_AND_DATA.md).
This document supersedes the [Phase 2 handoff](archive/PHASE2_HANDOFF.md).
Do not execute archived requests to replug hardware during Phase 3.

## Evidence timeline (UTC, 2026-09-05)

All required prior files were checked for existence; none was missing. The original
receipts were not rewritten. Local `phase3/prior-evidence-inventory.json` records
the paths, sizes and keys; the historical RGB NPY was opened read-only and retains
1216×1936×3 uint8 with save/reopen verification.

| Time / event | Observed result and cleanup |
|---|---|
| 14:53:27–14:53:30, pre-v2 single RGB frame | PASS historical; normal stop and device release true; no sustained-performance claim |
| 15:15:21, persistent attempt 1 | ICategory direct .name failed before streaming; zero frames; session closed, release true |
| 15:23:28, attempt 2 interruption record | Native all-node read before camera.start did not return; specified process 15220 terminated in Phase 2; zero frames, graceful release NOT_CONFIRMED |
| 15:24:02–15:24:31, attempt 3 | AccessDenied / GenCP MaxDeviceResponseTime during Open; zero frames; release false/not confirmed |
| 16:43:54, v2 desktop acceptance | English REPLAY workflows at 125%; no new persistent physical pass |
| 16:46:29, v2 final receipt | 189 Windows tests and exact-head Linux CI passed; physical status separately blocked |
| Later owner report and Phase 3 entry screenshot | Owner had already power-cycled/replugged and reported LIVE. Existing v2 screenshot shows LIVE #5895, BayerRG12/50 ms/gain 0; instantaneous UI-reported rates are not a benchmark |
| Subsequent window inventory | The previously observed app window was no longer present. No close/stop/kill/input action was performed by Phase 3 before its disappearance; cause unconfirmed |
| 20:17:40–20:17:46, unplanned Connect during desktop QA | Phase log confirms native Open failed while ExposureTime.GetInc() queried a continuous float; no start/fetch phase or frames. error_cleanup returned; the old phase log does not independently prove every release step. Trigger is unconfirmed. The test app was normally closed; no retry was made |

Historical receipt roots under local/diagnostics: phase2-final-delivery.json,
phase2-camera-smoke/receipt.json, phase2-camera-smoke-v2/interruption.json,
phase2-camera-smoke-v3/receipt.json and ui-phase2/acceptance.json. The historical
frame is under local/exports/raw_frame_20260905T155322198944/.
Before screenshot: local/diagnostics/ui-phase3/before-live.png. UIA text was stale;
the actual screenshot and owner report are the point-observation evidence. No
cable cause is diagnosed from this chronology.

## Hardware boundary

| Gate | State |
|---|---|
| H0 enclosure/interface identity | PARTIAL; OEM module known, body label/second lead association unknown |
| H1 sensor imaging | Historical single-frame/occlusion PASS; recovered LIVE point observation; persistent/record/Stop/stability revalidation DEFERRED |
| H2 raw controlled FP scan | BLOCKED: no verified protocol, state acknowledgement/settling/frame association |
| H3 spectral reconstruction | BLOCKED: no matching response matrix/runtime and independent wavelength check |
| H4 physical reflectance | BLOCKED: H3 and matched references/conditions/independent validation absent |

Phase 3 performed no hardware acquisition, reset, replug, power cycle, device
restart, disable/enable, driver reinstall, unknown serial open or permanent write.
New application windows were launched only for offline synthetic UI verification.
One unplanned native Open occurred as recorded above, so this phase must not be
described as having zero device-open attempts. This was not a hardware acceptance
run. The error was reproduced offline and fixed using GenApi 1.6 IFloat.has_inc(),
verified against the installed wrapper; a support-query timeout still propagates.
Final phase receipts also persist cleanup outcomes and release uncertainty.

## Next physical acceptance, not executed and not requested now

After a separately authorized hardware phase: one unique-target normal connection,
minimum readback and a fresh frame; bounded preview with increasing epoch/identity;
one displayed-frame save/reopen; a short bounded recording with full accounting;
normal Stop/close and settings readback; then format/exposure restart and a longer
stability test if preceding steps pass. Log every failure and release uncertainty.
Do not make all-node export a first-frame prerequisite. No retry/reset is implied.
H2/H3/H4 remain separate from imaging and require actual matching assets.

## Build and verification closeout

The final source suite passed 219 tests (18.17 s, offscreen Qt). A preceding native-Qt
test run passed 215 tests while emitting 0x8001010d; the cause is unconfirmed and
its log is retained. Native 125% desktop actions exercised synthetic loading,
three ROIs, rename, amplitude/L2 comparison, PC2/loadings, figure export, save,
reopen and reference registration. A normal close saved these items in config.
Automated restore regression passed. After native restart the desktop helper
repeatedly reported "foreground window did not report a process id". Resetting only
the JavaScript helper session restored capture: restored-reference-native.jpg
shows the same three named ROIs and registered sample. No PC/device reset was
used. Do not relabel the separate Qt offscreen render as a desktop screenshot.

Simulated 100/125/150/200% Qt layouts were exercised separately. At 200%, stacked
plots were too short; parallel amplitude/shape panels corrected the height issue.
Image ROI labels can overlap when zoomed far out; zoom/pan and named ROI controls
remain available. Public README now uses a native Windows synthetic screenshot
from the independently installed final wheel (2048x1104 returned logical pixels,
125% display scale). The earlier offscreen Qt render is separately linked.
The final desktop check used an environment without Harvester or GenICam, loaded
the synthetic example, compared amplitude/L2 curves and normally saved/closed.
No session-phase log was created by that final offline check.
All six example/native-export PDFs yielded selectable text; SVG text nodes and
numerical CSV/NPY/PlotSpec regressions passed. No physical precision is inferred.

Final exact source SHA, tests, Windows installation scope, screenshots and hosted
CI are recorded in RELEASE_PLAN.md and the ignored phase3 final-delivery receipt.
A true second clean Windows computer/VM and physical driver installation remain
NOT_TESTED. The staged public scope is source, tests, English docs and synthetic
examples only; no calibration, raw frames, identifiers or build binaries.
