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
| 1 | F1 labels, F2 mailbox events, F3 settings evidence, F4 independent UI states, F5 signal qualification, F6 wavelength support; measured preview optimization/readiness | Reproductions, focused numerical/Qt regressions, real baseline and updated native run | 495 offline tests PASS; updated native run PENDING |
| 2 | Stable mask-backed ROIs, exclusions/line strips, exact map distributions and spatial brush, linked task plots; observation Study | Geometry/tail/aggregation oracles, relocation and duplicate handling, actual saved observations | PLANNED |
| 3 | Physical support/export integration, bounded H2/H3 asset advancement, documentation and package verification | Three actual-code reviews; offline suite, wheel/frozen/native/outside-CWD checks; exact source/package/CI identities | PLANNED |

## Three reviewers, three rounds

Three separate AI reviewers cover measurement physics (A), statistics (B), and
software/performance/UX (C). These are agent reviews, not external human peer
review. New round-one reports inspected actual functions and ran counterexamples;
new round-two reports read both other reviews and exchanged explicit challenges.
The previous nine design reports remain historical evidence. Round three will
inspect the implemented diff and test receipts, rather than re-approve this plan.

Private full reports and scripts are in
`local/diagnostics/technical-first-20260906/reviews/`.

| Issue | Round-one evidence | Round-two challenge and convergence | Round-three outcome |
|---|---|---|---|
| F1 | Persisted Bayer/Mono explicit None raises TypeError | Display-only shared labels; never mutate channel labels or create a colour axis | PENDING |
| F2 | 2 captured + 2 displayed + 1 replacement | Rename overlapping mailbox events; reject a false loss partition or premature display acknowledgement | PENDING |
| F3 | Sparse/empty/auto-only settings falsely MATCH; conflicting chunks missed | Reuse the existing chunk-first tri-state matcher; UNKNOWN traces remain available but unqualified | PENDING |
| F4 | Old replay retains receive age and `stream None` | Camera, viewing and each completed result keep independent identity; explicit return to live | PENDING |
| F5 | Equal small DN perturbations produce different weak/bright ND sensitivity | Numerical denominator validity differs from signal evidence; default UNKNOWN; optional analyst `abs(a)+abs(b)` threshold | PENDING |
| F6 | Correct irregular-grid fits span large undocumented physical gaps | Keep fitting math; disclose window spans/indices/max delta/FWHM evidence; only explicit gap constraints reject crossings | PENDING |
| Sparse tails | 5/1000 targets disappear from median/MAD/P99 | Exact ECDF and coordinate brush; preserve hits in sampled overview; selected contrast is not defect truth | PENDING |
| Aggregation | Mean pixel ND = 0.4; ND of means = 2/3 | Pin and export the operation order; no hidden interchange | PENDING |
| Geometry | Bounding boxes overcount polygons/holes | One membership path and geometry denominators for summaries and distributions | PENDING |
| Study | Identical moved files have a different path-bound fingerprint | Keep old strict identity; verify all required assets and record a relocation association | PENDING |

No unresolved round-two disagreement blocks these small implementations. Automatic
noise estimation, statistical inference, a new claim/ack state machine, learned
defect classes, thermal-history inversion and undocumented FP commands are excluded.

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

Reviewer A inspected 508 files in known vendor/cache roots without locating the
missing control/calibration assets. No full-drive search or guessed control call
was used. The highest-value next asset is an authorized copy of this instrument's
previous working TruScope installation, including controller plugin/API and
linked per-unit configuration/calibration directories. Manufacturer specification
revisions differ; a generic brochure does not identify this unit or its protocol.

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
