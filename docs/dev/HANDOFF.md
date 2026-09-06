# Current handoff — technical-first 0.5.0 local delivery

The technical-first increment is implemented on `feature/materials-science-v040`
for Draft PR 2. The [review and acceptance record](TECHNICAL_FIRST_REVIEW.md)
contains F1–F6, the three actual AI review rounds, measured performance, failed
recordings and source/package evidence. The existing numerical/figure architecture
and approved English scientific UI remain in use.

Implemented: independent camera/view/result identities; explicit unnamed-plane
and chunk-first settings semantics; diagnostic signal evidence and physical
wavelength support; pinned quality/readiness; measured preview work; stable
reference/target/exclude polygons, masks and strips; exact map distributions and
spatial brushing; original-observation Study manifests, verified relocation and
source-bound figures/tables. Same raw dimensions retain ROI definitions across
preview epochs and RGB/Bayer changes. Different dimensions create new generic
ROIs with explicit placement feedback. Completed results clear on Start. Task
controls and terminal operation messages follow their actual context.

Production code is `fc01ac9b73a1d86b28512689bc6fa038d6c41be6`. The complete source
suite passes **698 tests** (66.51 s). The non-editable wheel and frozen program
both pass doctor/offline smoke outside the checkout, with fresh configurations
and space/Chinese paths. All 50 installed Python modules match the wheel bytes;
the frozen build verifies 45 archived-source modules. Package hashes and the
source/CI identity distinction are in the review record. Subsequent documentation
commits do not change the production code packaged at this revision.

Two actual RGB observations pass 81 independent numerical/provenance checks.
Native ECDF/one-pixel strip and Study exports pass 93 further checks (57 + 36).
A later native ROI export independently matches all 27 quantile cells, nine CSV
rows, pixel denominators and source/output hashes. These evidence groups have
overlapping scope and are not a new combined test-suite denominator.

The final hardware smoke ran the installed `3d1bc8d5` package: **20/20** recorded
frames completed/reopened; a raw snapshot saved; all four ROI definitions retained;
2,838 captured / 1,701 displayed, zero device gaps/timeouts, normal stop in 0.063 s
and successful release. All 20 saved frames were independently traversed/hashed.
Quality, map selection, profile and Study operations showed terminal outcomes.
Native inspection then found stale ECDF axes when a rectangle was chosen for a
strip profile. The final `fc01ac9b` patch only clears this invalid presentation
and restores axes for valid plots; acquisition/storage code is unchanged. The
final package was tested natively on saved real data, without another camera
session. Do not relabel the `3d1bc8d5` hardware receipt as an `fc01ac9b` run.

A visible printed scene was acquired using RGB 10/20/40 ms and BayerRG12 40 ms,
gain zero. This is actual imaging evidence, not a thermal-paint/defect dataset.
Measured native capture was about 34 fps; preview workload medians were about
16–17 displayed fps, with below-target windows retained. Host stage timings are
not calibrated exposure-to-screen latency. The latest short-smoke snapshot was
again near-black: 265 nonzero / 7,062,528 values, maximum 47 DN. Its optical cause
remains UNKNOWN, and it is not a qualified dark reference. The usable analysis
view uses the earlier saved visible real scene, explicitly labelled as retained
data. No matched radiometric references or material truth were invented.

High-rate 300-frame recording remains FAIL: successive attempts retained 96,
112 and 176 durable frames. The final attempt accepted/wrote 176, rejected one
writer frame and independently recorded 88 device gaps / five timeouts across
the storage-stressed session. Offline alternatives exposed a remaining Windows
durable synchronization limit and were not promoted. All partial prefixes and
negative receipts remain intact; a short smoke cannot qualify the 300-frame target.

H2/H3/H4 are not restored or physically validated. A bounded search of 508 known
vendor/cache files produced no verified FP API or matching calibration. The next
highest-value asset is this unit's previous working TruScope installation with
its controller plugin/API and linked per-unit configuration/calibration folders.
Normal single-owner imaging is authorized; resets, driver/firmware/permanent
writes and unknown FP/serial commands remain outside this work. All cameras are
normally released between package tests. Original-code licensing and public
binary release remain pending.

Local evidence and real data stay under ignored
`local/diagnostics/technical-first-20260906`. The private delivery report is
`local/HYPERLAB-0.5-DELIVERY.md`; `local/Start-HyperLab-0.5.cmd` opens the reviewed
package using process-scoped PowerShell execution-policy bypass. The launcher
was exercised from outside the project and refuses a duplicate app owner.
Hosted checks belong to the delivered branch/PR; retain terminal run receipts
with their associated head and actual checkout SHA separately. Follow the
[technical workflow](../user/TECHNICAL_WORKFLOW.md) and
[Study/SOP guide](../guides/studies.md). Preserve the prior 0.4.0 package and
failed cases. Stage reviewed source/tests/redacted English docs only; maintain
the existing Draft PR without merging or changing the default branch.

## Historical 0.4.0 materials and thermal-paint delivery

The previous owner request was implemented as S1–S9 in the
[research, three-round review and delivery record](SCIENCE_ROADMAP_REVIEW.md).
Current branch: `feature/materials-science-v040`, based on the already merged
0.3.1 PR at `904cc2f`. The earlier PR was merged externally during this work;
this increment does not merge or change the repository's default branch.
Three AI reviewers completed nine reports and converged before implementation.
The English UI retains the approved scientific palette and simplifies analysis
to a method selector, contextual parameters, Run, Results and one Export menu.
See the [complete technical/user guide](../user/MATERIALS_AND_THERMAL_PAINT.md).

The source suite passes 418 tests. The isolated installation smoke exercises
the new scientific modules, annotation/reference dialogs and output manifest.
Actual saved RGB/Bayer frames, a complete recording and a partial durable prefix
pass 14 independent checks with originals unchanged. A separate official USGS
measured coating spectrum passes 53 numerical/provenance and 36 export checks;
it is one external spectrum, never a HinaLea spatial image or temperature model.
The final wheel and frozen executable pass installation smokes outside the
checkout. Native delivery captures 1,223 frames with zero device gaps/timeouts,
saves an actual RGB frame, and normally restores/releases the camera. This fresh
scene is almost black; its cover/illumination state is unknown. The earlier actual
visible frame is used in REPLAY for the final ROI/table/map/export acceptance,
which passes 47 independent checks. Detailed counts, package hashes and remaining
limits are in the delivery record. Local evidence stays ignored and private.

The first integrated suite retained three failures: two old UI fixtures needed
the new explicit completed-analysis export contract, and a bounded fake-camera
gap test reached writer overflow first under concurrent disk load. The gap
fixture now fits its pre-gap prefix in its test queue; independent overflow tests
and every actual partial recording remain unchanged. Later native/integration
review fixes source pinning, source-switch invalidation, asynchronous Run recovery,
RGB/BGR labels, failed chart-selection identity and modeless figure settings.
Closed file mappings are rejected before hashing when a previous export dialog
outlives a replay-source switch. These changes have dedicated regressions.
The final native review also reproduced a stale pixel readout after a new frame;
new frames now clear the previous pixel value and quality tooltip. Both live and
replay transitions have regressions. The delivery package is built from
`a5c055fe4bb4f6da61fe6818f195262b39237ab1`.
Later closeout and platform-test edits do not change packaged production code.
The first hosted Linux suite exposed a checkbox test click outside its style's
indicator/text area. The fixture now clicks the actual Qt indicator and asserts
the toggle; all eight reference-dialog tests pass locally after this test fix.
The verified package is in
`local/distribution/materials-science-0.4.0-delivery`; the local delivery index
and `local/Start-HyperLab-0.4.cmd` point to it. Earlier 0.4.0 build directories
are preserved but superseded. The visible native window is left on actual-frame
ROI curves and normalized difference, with camera ownership released. The Draft
PR and its exact-head terminal checks record hosted validation separately.

Physical FP control/reconstruction/calibration, a temperature-history inverse
model and a validated defect classifier remain conditional on the evidence
listed in the plan. No reset, driver/firmware change or unknown control command
belongs to this increment. Original-code licensing/public release remain deferred.

## Historical 0.3.1 ROI/display follow-up and Phase 3

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
The earlier 0.3.1 package (source e809135) passed 229 offline tests and its own
1,803-frame native imaging check, 20/20 recording, real ROI/figure export and normal
settings restoration/release. Its actual frame 1261 ROI check remains evidence.
The earlier e06345b 2,512-frame run remains separate evidence.
The later owner-selected heatmap style adds a white map background, blue-white-red
PCA/difference display, grey invalid layer/key and readable unscaled colorbar.
It changes presentation only; the real-session receipts above remain unchanged.

The current package is 0.3.1 from source 3df0041, with 234 offline tests passing
and successful push/PR CI. The later real RGB session captured 6,437 frames,
zero device gaps/timeouts, and normally restored/released the camera. A 300-frame
recording attempt failed on writer overflow (64 persisted, one rejected); a
separate confirmed 20-frame recording passed. Preserve both outcomes. Native
ROI/L2 and R−G exports from actual frames 3321 and 912 match independent NumPy
checks. The final executable displays frame 912, R−G and ROI curves in REPLAY
with LIVE origin. Full-rate RGB writing and the observed 2.56 fps RGB display
remain performance limitations. Recording failures now retain the camera's
connection label, and maps use the recorded RGB/BGR channel names.

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
