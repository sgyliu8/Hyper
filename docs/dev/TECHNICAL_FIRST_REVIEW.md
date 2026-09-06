# Technical-first implementation and review

2026-09-06. Incremental work on `feature/materials-science-v040`, starting from
`dfa7af00171a4c9152d1c58e31d4324760403487`. Draft PR 2 remains Draft. The owner
requested the technical-first specification and correction of confusing UI state.
Original-code licensing and public release remain deferred.

## Scope and acceptance

Keep the current Qt, pyqtgraph, Matplotlib and PlotSpec architecture and approved
white/orange/blue/teal figures. Raw acquisition evidence stays immutable. Imaging,
scene usefulness, reference applicability and spectroscopy are separate outcomes.

| Slice | Implementation | Required verification | Current status |
|---|---|---|---|
| 1 | F1 labels, F2 mailbox events, F3 settings evidence, F4 independent UI states, F5 signal qualification, F6 wavelength support; measured preview optimization/readiness | Reproductions, focused numerical/Qt regressions, real baseline and updated native run | F1–F6 implemented and regression-tested; real RGB/Bayer frames saved; workload display medians now 16–17 fps (below-target intervals retained) |
| 2 | Stable mask-backed ROIs, exclusions/line strips, exact map distributions and spatial brush, linked task plots; observation Study | Geometry/tail/aggregation oracles, relocation and duplicate handling, actual saved observations | Implemented; exact sparse/aggregation/geometry/Study checks PASS; two real saved observations pass 81 independent numerical/provenance checks |
| 3 | Physical support/export integration, bounded H2/H3 asset advancement, documentation and package verification | Three actual-code reviews; offline suite, wheel/frozen/native/outside-CWD checks; exact source/package/CI identities | Source review and installed acceptance PASS at e457cc06; final native UI integration fixes and CI closeout in progress |

## Three reviewers, three rounds

Three separate AI reviewers cover measurement physics (A), statistics (B), and
software/performance/UX (C). These are agent reviews, not external human peer
review. New round-one reports inspected actual functions and ran counterexamples;
new round-two reports read both other reviews and exchanged explicit challenges.
The previous nine design reports remain historical evidence. Round three inspected
the implemented diff and executed new counterexamples. Its failures and subsequent
closure receipts are retained separately; review agreement is not physical validation.

Private full reports and scripts are in
`local/diagnostics/technical-first-20260906/reviews/`.

| Issue | Round-one evidence | Round-two challenge and convergence | Round-three outcome |
|---|---|---|---|
| F1 | Persisted Bayer/Mono explicit None raises TypeError | Display-only shared labels; never mutate channel labels or create a colour axis | PASS: None Bayer/Mono and RGB/BGR regressions; real Bayer raw/ROI display |
| F2 | 2 captured + 2 displayed + 1 replacement | Rename overlapping mailbox events; reject a false loss partition or premature display acknowledgement | PASS counter semantics; earlier native runs had 0/0 gaps/timeouts, later storage-stressed run had 88/5 (retained) |
| F3 | Sparse/empty/auto-only settings falsely MATCH; conflicting chunks missed | Reuse the existing chunk-first tri-state matcher; UNKNOWN traces remain available but unqualified | PASS: chunk-first MATCH/MISMATCH/UNKNOWN; real exposure mismatch retained |
| F4 | Old replay retains receive age and `stream None` | Camera, viewing and each completed result keep independent identity; explicit return to live | PASS: independent source labels; stale editor/export/worker counterexamples fixed |
| F5 | Equal small DN perturbations produce different weak/bright ND sensitivity | Numerical denominator validity differs from signal evidence; default UNKNOWN; optional analyst `abs(a)+abs(b)` threshold | PASS: signed ND preserved; numerical and signal evidence separate |
| F6 | Correct irregular-grid fits span large undocumented physical gaps | Keep fitting math; disclose window spans/indices/max delta/FWHM evidence; only explicit gap constraints reject crossings | PASS: physical support metadata and declared-gap counterexamples |
| Sparse tails | 5/1000 targets disappear from median/MAD/P99 | Exact ECDF and coordinate brush; preserve hits in sampled overview; selected contrast is not defect truth | PASS: exact five-pixel selection retained despite unchanged median/MAD/P99 |
| Aggregation | Mean pixel ND = 0.4; ND of means = 2/3 | Pin and export the operation order; no hidden interchange | PASS: independent 0.4 versus 2/3 oracle; order exported |
| Geometry | Bounding boxes overcount polygons/holes | One membership path and geometry denominators for summaries and distributions | PASS: exact raw counts and straight-strip edge oracles; multi-segment floating policy remains explicit |
| Study | Identical moved files have a different path-bound fingerprint | Keep old strict identity; verify all required assets and record a relocation association | PASS original relocation/duplicate/context regressions; two real observations verified |

No unresolved round-two disagreement blocks these small implementations. Automatic
noise estimation, statistical inference, a new claim/ack state machine, learned
defect classes, thermal-history inversion and undocumented FP commands are excluded.

## Actual-code convergence and integration findings

Round 3 audited `aaed7ce8c22046ada9b544d7febf57894cce6aad` with a clean worktree.
A found one received-frame geometry counterexample (1 FAIL / 5 PASS). B found
four profile/transform export defects (4 FAIL / 4 PASS). C found five reachable
source/editor/callback defects (5 FAIL / 3 PASS in safe isolated probes). A Qt
failure-representation crash in an earlier offscreen probe is preserved separately;
it was not a native camera crash or an additional successful test.

At `395ff7885e0c76147232ef3c417f5bfcf38160f7`, the original cases were corrected:
original receipt geometry survives Cube normalization; completed strip profiles
retain their source fingerprint, actual channel identity, spatial bin edges and
counts; residual/L2 plots shed incompatible amplitude branches and keep correct
units/summary labels; modeless dialogs and asynchronous results follow stable ROI
IDs and are invalidated before old file mappings are released. Independent A/B/C
closure runs passed 48, 54 and 19 checks respectively (overlapping suites, not a
new total denominator).

A/B then exposed an unknown-saturation CSV ambiguity. The correction exports
UNKNOWN with blank counts/threshold, while assessed counts retain the criterion
and original signal units. A independently passed the original probe plus the
committed profile export tests (19 checks) at `29a8ae5b9b0293759384719a34c5c219f9c1933e`.
C/root also reproduced and fixed disappearing recording failures and inconsistent
right-task point connections/colours. The complete source suite at that commit
passed 648 tests in 60.38 s. Failed attempts remain alongside the passing receipts.

Real and installed integration additionally exposed two cases not covered by that
checkpoint: legacy Windows stdout could not emit a Chinese directory in `doctor`,
and exact strip-bin boundary pixels could land in the preceding bin through
floating roundoff. The CLI correction passes a legacy-code-page JSON roundtrip regression. A straight
strip now uses normalized projection and exact binary-input rational comparisons
only near a bin boundary; a representable point on either side is never snapped
across it. Horizontal, vertical, reversed and diagonal counterexamples pass.
Multi-segment distance binning retains its documented float64 policy. The two real
20/40 ms observations pass 81 independent checks, including every map pixel,
profile bin/count/SD, source-bound figure/CSV and Study asset. No threshold is
relaxed to turn a failed case into a pass.

## Actual baseline and hardware boundary

The unchanged baseline passed **418 offline tests**. A normally connected native
0.4.0 application then displayed a newly received real RGB scene at 20 ms and gain
0. The scene contains printed material and a bright region; it is not a labelled
thermal-paint or defect dataset. Observed capture was about 34 fps and application
display about 2–3 fps (medians 34.045 and 2.535; 49 live telemetry samples).
The run captured 2,129 and displayed 156 frames. A raw frame was saved, acquisition stopped and the camera
was normally released. Full counters and hashes remain in the private receipt.
The older almost-black frame and failed/partial sequences are preserved.

Offscreen profiling identifies display selection as a measured bottleneck. It
does not prove native display performance. Preview sampling is an explicitly
labelled display derivative; exact raw ROI/mask/map/export computation remains
independent. Full quality uses a pinned observation and an explicit background
inspection, avoiding a periodic full-frame Qt stall. Host image enqueue time is
not exposure-to-screen latency.

The first updated native run used the isolated Slice 1 source snapshot at
`28007809498d87efe689eda72c5e1242e3f53b96`, RGB8 / 20 ms / gain 0. It captured
3,855 and displayed 773 frames; 3,854 overlapping mailbox replacement events,
zero device gaps/timeouts, and normal stop/release were retained. Approximate
display rate improved to 6.5 fps, below the 15 fps objective. That incomplete
performance result is preserved. Further fixes compact sampled buffers without
changing numerical values, avoid repeated histogram/layout reconstruction and
record image paint duration. Offline function speedups are not native FPS.

New integration checks found and fixed histogram slopes in place of steps,
brush shading that did not follow numeric input, bin-centre brush bounds that
excluded extrema, and stale polygon coordinate frames during source-shape
changes. A hidden included ROI still contributes to common-feature normalization;
visibility no longer silently changes the calculation set. All failed receipts
remain local alongside their later regressions.

The `395ff788` native session used one verified owner and the existing installed
producer. RGB 20 ms workload telemetry (overlapping 2 s windows) gave:

| Displayed workload | Rows | Capture median fps | Display median / P5 fps |
|---|---:|---:|---:|
| Preview | 45 | 34.027 | 15.996 / 14.240 |
| Preview with two ROI results | 17 | 34.257 | 17.276 / 15.737 |
| Preview with eight ROI results | 93 | 34.027 | 16.897 / 15.609 |
| Preview with map/eight ROI results | 77 | 34.045 | 15.996 / 13.597 |
| Initial bounded recording attempt | 5 | 34.306 | 11.296 / 9.630 |

These are measured workload windows, not an all-ROI/map recomputation on every
received frame or a guaranteed minimum FPS. Explicit analyses pin an observation
and show Computing while running. Full distributions/maps can take longer.
Representative preview UI-update median/P95 was 26.558/44.017 ms and image paint
13.773/25.960 ms. Stage collectors hold the latest 240 observations; their
percentiles can span prior work and overlapping stages are not additive.

A measured Windows/Python 3.11 clock issue also contributed: the installed
Harvesters polling loop uses a coarse `time.time` clock. A cooperative 8 ms yield
after an empty poll leaves GUI work time while a monotonic outer deadline remains
in force; available buffers return immediately. No producer, device timing,
firmware or global timer setting changed. The Python clock implementation change
is documented in the [official time reference](https://docs.python.org/3.13/library/time.html).

Four fresh saved observations have matching requested/session exposure readback:
RGB 10/20/40 ms and BayerRG12 40 ms, gain zero. Full raw saturation counts are
36,014 / 7,062,528; 126,784 / 7,062,528; 236,887 / 7,062,528; and
22,210 / 2,354,176 respectively. These are channel-sample denominators for RGB
and sensor-site denominators for Bayer. Recorded Gamma qualification remains
unknown, chunks are absent, and a session readback does not establish per-frame
settings. Visible scene response is observed; material/illumination/reference
conditions and the cause of the old almost-black image remain UNKNOWN.

The initial 300-frame request failed after 96 durable frames with an eight-slot
writer queue. A packaged 16-slot repeat failed after 112 durable frames. Each had
one rejected frame and retained every accepted frame, its partial status, and
reopen receipt. Buffer size alone did not solve the write bottleneck. The visible
Last recording receipt survived preview, Stop and tab changes. Subsequent writer
work preserves the eight-frame durable checkpoint, data flush/fsync and atomic
manifest publication; it targets JSON serialization overhead. Final recording
acceptance is recorded separately below, without replacing these failures.

Reviewer A inspected 508 files in known vendor/cache roots without locating the
missing control/calibration assets. No full-drive search or guessed control call
was used. The highest-value next asset is an authorized copy of this instrument's
previous working TruScope installation, including controller plugin/API and
linked per-unit configuration/calibration directories. Manufacturer specification
revisions differ; a generic brochure does not identify this unit or its protocol.

## Recording limit found during installed acceptance

Native UI acceptance additionally reproduced a destructive ROI transition:
starting preview replaced saved reference/exclusion/strip definitions with tiled
rectangles while retaining their names. The correction checks raw coordinate
dimensions, preserves matching definitions across channel/stream changes, and
clears old computed results. A genuinely different grid creates new generic IDs
and explicit placement feedback. Native task switching also exposed irrelevant
range controls and an indefinitely Computing profile status. Contextual controls,
pending-request guards and completion messages pass 70 focused regressions.
Previous completed export receipts remain immutable when the active brush clears.

The actual Study Add/Save/Verify workflow exposed the same unfinished-progress
message in the main window despite completed dialog results. Four queued success
and failure counterexamples reproduced it; the two-line notification correction
passes 27 Study tests. A subsequent bounded callback audit found related missing
terminal messages in quality, recorded traces, mask/annotation import, reference
checks and cancelled device selection. Local completion/rejection notices retain
the existing source guards and operation semantics. The quality button now says
**Frame quality / readiness**; ROI counts remain in Results and numeric exports.

Two native exports from the actual scene independently pass 57 numerical/hash
checks: the inclusive Suspect selection contains 1,071 / 102,469 valid pixels
within 185,500 geometric pixels. The native one-pixel strip profile retains 820
bins, including 280 empty bins per channel, with 17,569 geometric / 6,044 excluded
pixels and 11,525 used pixels per channel. Empty bins remain empty. These are
descriptive contrast and spatial dispersion, not defect labels or repeatability.

Native Study Add/Save/Verify also retains two real observations with three ROI
rows each. Independent recomputation passes 36 additional checks: all 18 RGB
median/common feature cells, the six exported R points, source/AnalysisRun
identities and seven declared output hashes match. Settings are MISMATCH for
20 versus 40 ms; specimen, temperature, dwell and independent-replicate count
remain unknown. Selecting temperature natively shows 0/6 points and six explicit
unknown-temperature omissions. The saved-data workflow has no camera session.

The `e457cc06` installed native repeat retained **176 / 300** requested frames:
accepted/written 176, one writer rejection/overflow, and a verified partial prefix.
The complete session also recorded **88 device gaps and 5 timeouts** under this
storage-stressed workload. Those transport observations are separate from the
writer denominator and do not replace the earlier zero-gap runs. A fresh RGB8
20 ms snapshot was saved and the camera was normally released.

Its 23 checkpoints had median/P95 data-flush times of 25.020/835.484 ms,
data-fsync 51.089/97.684 ms, and manifest publication 27.011/77.657 ms;
checkpoint total was 101.543/992.807 ms. Nested timings are not additive
percentile estimates. In CPython 3.11.9 on Windows, `mmap.flush` calls
`FlushViewOfFile` while holding the GIL; this explains a mechanism by which a long
mapped flush can also delay host acquisition/UI work. See the
[exact upstream implementation](https://github.com/python/cpython/blob/v3.11.9/Modules/mmapmodule.c).

Four bounded offline writer comparisons used a new local output each and kept
checkpoint8, queue16, a 300-frame request and a scheduled 34 fps producer. The
existing full-map and page-range variants retained 120/300 and 64/300. Two direct
sequential-write variants retained 32/300 and 24/300. In the latter trials producer
lateness remained below 2 ms but data-fsync medians were 739/829 ms. This isolates
a remaining measured durable-storage synchronization limit on this Windows path;
it does not diagnose an SSD fault. No experimental variant was promoted, and no
queue, durability requirement or original target was relaxed.

High-rate 300-frame recording remains **FAIL**. A separate short-recording smoke,
if successful, establishes only its own bounded frame count. Each earlier partial
recording and negative experiment remains available locally.

At `e457cc06`, the complete source suite passed **664 tests** (73.00 s). The
non-editable wheel and frozen executable both passed doctor and offline smoke
from an outside-checkout directory containing spaces and Chinese characters,
with fresh empty configs and producer environment variables removed. These
checks did not open a camera or load a producer. The existing driver was still
installed on Windows; this was not a blank-VM driver test.

## Primary-source design examples

Accessed 2026-09-06. These examples guide implementation, not hardware acceptance.

| Source and reading depth | Adopted decision | Limit |
|---|---|---|
| [HyperSpy ROI map example](https://hyperspy.org/hyperspy-doc/current/auto_examples/region_of_interest/map_signal.html), official example page | Link signal interval selection and spatial maps using declared coordinates | No extra framework dependency |
| [hylite](https://github.com/hifexplo/hylite), original repository README/examples index | Keep spectral features, ROI libraries and wavelength metadata explicit | Geological examples do not identify coatings |
| [Cubert lentil demo](https://huggingface.co/datasets/cubert-gmbh/XMR_Demo_Industrial_Foreign_Object_Detection_Lentils), manufacturer dataset card | Keep raw sequence, reference acquisition and spatial labels distinct | Card inspected; 69-frame dataset/models not downloaded or reproduced |
| [Living Optics orchard](https://huggingface.co/datasets/LivingOptics/hyperspectral-orchard), manufacturer dataset card | Group related frames by original acquisition; split by raw file rather than frame to avoid leakage | Sparse spectra require their recorded coordinates; no dense-cube claim |
| [Living Optics forensics](https://huggingface.co/datasets/LivingOptics/hyperpspectral-forensics), manufacturer dataset card | Keep instance masks, sparse samples and library spectra separate | Scene/domain evidence does not transfer to this camera |

Detailed measurement sources and exact reading depths are retained in reviewer A's
reports. Existing thermal-paint references remain in the materials guide; abstract
access is not described as full-paper reproduction.

## Delivery identities

Final code commits, package code revision/hash, actual native configuration and
terminal CI receipts will be entered here after verification. A GitHub PR check's
associated head SHA is distinct from its actual `refs/pull/.../merge` checkout.
Both identities must be recorded; no unfinished run is PASS.
