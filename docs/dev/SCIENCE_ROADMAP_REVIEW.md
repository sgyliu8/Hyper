# Scientific workbench review and implementation record

Status: S1-S9 implementation, source/package validation and bounded native imaging/export acceptance complete. Opened and closed 2026-09-06. Physical spectroscopy and application-model qualification remain conditional below.

## Scope and method

The owner requests a source-backed scientific feature roadmap, three independent
AI reviewers and three documented review rounds, implementation, and a simpler
English UI. Preserve the approved white figures and orange/blue/green ROI palette.
This is an engineering evidence review, not an exhaustive systematic review or a
claim of independent human peer review. All reviewers use the configured model
family; disagreements and unresolved conditions must remain visible.

Research question: which ROI summaries, spectral transformations, comparisons,
quality measures and publication outputs are mathematically appropriate for
material/coating measurements, and what data and hardware evidence admit each?

Search primary papers and original author repositories/documentation, including
arXiv, GitHub and Hugging Face. Include numerical definitions, applicability,
validation examples and maintained or inspectable implementations. Separate
peer-reviewed articles, preprints, software examples and dataset/model cards.
Exclude marketing-only claims and opaque pretrained classifiers as validation.
Record access dates, links, limits and transferable implementation ideas.

Current baseline: 7ab867b2946035a162254f1d63cdc4d156b52e47. Review local code and
current evidence before making changes. RGB/Bayer imaging is evidenced; controlled
FP scanning, matching reconstruction assets and physical reflectance validation
are outstanding. External evidenced spectral cubes are admissible independently.
Do not manufacture wavelengths, calibration, specimen labels or model accuracy.

## Review protocol

1. Independent review: physical measurement and calibration; ROI statistics and
   spectral algorithms; scientific software and user interaction. Each reviewer
   searches primary sources and states prioritized proposals, objections and tests.
2. Cross review: each receives the other reports and a shared candidate plan,
   challenges assumptions, and identifies fixes or necessary deferrals.
3. Convergence: resolve each disagreement explicitly, freeze mathematical and UI
   acceptance criteria, and name any remaining conditional capabilities.

Implementation follows the converged dependencies. Verify independent numerical
examples and invalid-input regressions, meaningful offline tests, actual saved
camera data, source/units/mask provenance, and native UI/export consistency.
Synthetic fixtures remain labelled; real camera data remain local and immutable.
Update this record, research sources, implementation status and the handoff.

## Round records and decision matrix

| Reviewer | Independent round | Cross-review round | Convergence round |
|---|---|---|---|
| Physical measurement | [R1](reviews/science-r1-physics.md) | [R2](reviews/science-r2-physics.md) | [R3](reviews/science-r3-physics.md) |
| Statistics and spectra | [R1](reviews/science-r1-statistics.md) | [R2](reviews/science-r2-statistics.md) | [R3](reviews/science-r3-statistics.md) |
| Software and interaction | [R1](reviews/science-r1-software.md) | [R2](reviews/science-r2-software.md) | [R3](reviews/science-r3-software.md) |

All three final reviews accept [Version 1 of the implementation plan](SCIENCE_CANDIDATE_PLAN.md),
with explicit tests and conditional physical claims. This freezes S1-S9. Design
acceptance is not implementation PASS or physical validation. The baseline suite
passed 234 tests in 53.68 seconds before production changes.

| Disagreement | Final decision |
|---|---|
| Empty settings and mismatched reference conditions | Required P0 role-aware applicability fix; darks need blocked-light evidence, not matching illuminated conditions |
| Mean/SD versus robust summaries | Preserve default mean/SD; explicit median and Q25-Q75 ribbon, raw MAD, separate original quality and used counts |
| Per-band versus common pixels | Retain both named modes; common selected-feature support for spectral features; no silent fallback |
| Uniform SG versus irregular derivatives | One small true-coordinate Local polynomial operator; NumPy least squares, rank checks, complete centered windows and NaN edges |
| Transforming summary versus summarizing transforms | Initial summary-then-transform only, explicitly named, without propagated raw SD/IQR |
| RX/covariance uncertainty immediately | Defer until defensible covariance/background/input evidence; implement reference RMSE and preserve uncertainty equations/requirements |
| Typed context versus calibration evidence | Versioned analyst annotations are source-bound and never overwrite or elevate acquisition/calibration evidence |
| More methods versus a crowded UI | Contextual method controls, one Run/export entry, completed result determines chart identity, Stop remains accessible during acquisition |
| Colour-averaged repeatability | S9 adds actual stored-channel selection, retaining every durable frame and partial/loss accounting |

## Implementation acceptance tracking

| Package | State | Required evidence |
|---|---|---|
| S1 applicability | PASS | Counterexample and role/unknown/mismatch matrix |
| S2 robust ROI/support | PASS | Independent quantiles/counts and real-frame immutability |
| S3 pair comparisons | PASS | Metric invariances, null reasons, common features |
| S4 spectral features | PASS | Irregular polynomials, independent uniform oracle, interval/depth/gap/unit cases |
| S5 maps | PASS | Independent distance/normalized-difference, named units/masks |
| S6 annotations | PASS | Unknowns/revisions/source binding and preserved raw sidecars |
| S7 publication outputs | PASS | Pinned numeric/UI/CSV/PNG/SVG/PDF agreement and hashes |
| S8 simple workflow | PASS | Native current-data flow and stale/missing/disabled-state tests |
| S9 temporal channels | PASS | Opposing R/G trace and actual durable recording prefix |

Research synthesis: [materials and thermal-paint guide](../user/MATERIALS_AND_THERMAL_PAINT.md).
Source access failures and unverified examples remain in the reviewer records.
One optional original ICVL cube download returned HTTP 401; that attempt is not
claimed as external-data validation. Local validation-only SciPy/h5py wheels are
isolated under ignored diagnostics, with no new production dependency.

## Final delivery evidence

The delivery executable and wheel contain source commit
`a5c055fe4bb4f6da61fe6818f195262b39237ab1`, version 0.4.0. Subsequent closeout and
platform-test edits do not change packaged production code. The new branch is
`feature/materials-science-v040`, based on the already merged `904cc2f` baseline;
the earlier PR was merged externally during this increment. This work does not
merge, change the default branch or publish a binary release. Hosted checks
belong to the new Draft PR and its exact head.

| Acceptance | Result and limit |
|---|---|
| Full Windows source suite | PASS, 418 tests in 71.19 s |
| Ordinary wheel installation | PASS in an isolated noneditable environment; smoke run outside the checkout, including new calculations, source manifests and context/reference dialogs |
| Frozen Windows executable | PASS, same offline smoke outside the checkout; 36 archived source modules verified; no vendor CTI/SYS bundled |
| Actual saved sensor data | PASS, 14 independent checks of RGB/Bayer frames, the 20-frame complete sequence and 64-frame durable prefix of the earlier failed recording; original hashes unchanged |
| External measured coating spectrum | PASS, official USGS painted-aluminum spectrum: 53 numerical/provenance and 36 export checks; one external spectrum, not a local camera cube |
| Final native imaging | PASS for transport/save/normal release: 1,223 captured, 122 displayed, zero device gaps, zero fetch timeouts, saved RGB frame 534, camera released normally |
| Native real-scene analysis/export | PASS, 47 independent checks of actual frame 912 ROI statistics, table observations, L2, normalized-difference arrays/masks, PNG/SVG/PDF/CSV and source/output hashes |
| Current optical scene | DARK_SCENE_OBSERVED; cover/illumination state unknown. Visible-scene analysis uses the earlier actual frame, explicitly REPLAY with LIVE origin |
| Spectroscopy and task performance | NOT_TESTED by this imaging run: no reconstructed wavelength cube, calibrated reflectance, temperature-history inverse model or validated defect classifier |

Final package artifacts remain local under
`local/distribution/materials-science-0.4.0-delivery`:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| HyperLab-0.4.0-a5c055fe-win-x64.zip | 84,192,832 | a6e4068d7b45ea09cf0a3fffbdbe9a66cca685473ac9acf0f878d0844ebbce3a |
| hyperlab-0.4.0-py3-none-any.whl | 149,460 | 9355d77b3c2396d83f218ed666e24fa905fd66b8fa65fa24aa7ed9861ce6b144 |

### Native workflow and retained limitations

The final native executable was operated through the visible English UI at
2048 × 1104: Connect, Start, Save frame, switch to Analysis, Stop, Disconnect,
open the earlier actual scene, compare three ROIs, inspect the results table,
plot pair residuals, compute normalized R/G difference, and export both numeric
and publication bundles. Stop remained available on Analysis while streaming.
The final window shows the actual scene, orange/blue/green median and Q25-Q75
curves, separate L2 shape, and the blue-white-red map with grey invalid pixels.

The final short acquisition used RGB8, 1216 × 1936 × 3, 20 ms exposure, gain 0.
Median observed capture rate was 34.027 fps and display rate 3.490 fps; this is
not full-rate display or recording qualification. The latest-preview replacement
counter was 1,222 and is distinct from zero device frame gaps. Stop took about
0.031 s; settings restoration and normal destruction/release returned successfully.
An earlier interim executable run separately captured 1,760 frames with zero
device gaps/timeouts and normal release. Do not combine these sessions into a
single sustained test or omit the historical writer-overflow failure.

The fresh frame has only 143 nonzero values among 7,062,528, a maximum of 33 DN
and mean 0.000040637 DN. It establishes an almost-black observation, not a
validated dark reference or a diagnosis of its cause. The earlier visible frame
912 has no specimen identity, paint label or defect truth. Its three ROI medians
are [22, 34, 41], [37, 55, 45] and [17, 24, 23] DN on R/G/B, respectively.
The normalized-difference map retains 2,282,348 of 2,354,176 valid pixels.
All figures keep RGB category labels and the original acquisition provenance;
the saturation-exclusion policy does not establish radiometric calibration.

The USGS example is the official measured painted-aluminum library spectrum,
with the provider's AREF meaning and original sample support retained. No
resampling was used. Independent 50-digit Decimal local-polynomial calculations
from the original ASCII samples agree with the first/second derivatives within
2.0e-16/3.2e-16. Visible interval integration and signed continuum depth/area
also pass independent numerical checks. This validates computational behavior
on measured spectral data, not local instrument or thermal-paint calibration.

Native review reproduced and fixed stale pixel values after a new frame. It
also exercised the source-pinning and closed-memory-map export guards. Earlier
failed regression/fixture attempts and the incorrect smoke CLI invocation remain
in local logs; the final suite and correctly invoked installation smokes pass.
The local export verifier initially expected a 2-D native array; native derived
files correctly retain the singleton feature axis, while publication map arrays
are 2-D. The corrected verifier explicitly checks both contracts before comparison.

The first hosted Linux suite retained one failure (417 passed): the reference
test's default click at the center of a full-width checkbox missed its clickable
indicator/text area under that platform's font/style. A separate wide-checkbox
experiment reproduces the missed center click and successful indicator click.
The fixture now obtains the indicator rectangle from Qt's current style, clicks
its center and explicitly asserts the toggle before checking the calibration
gate. All eight reference-dialog tests pass locally after this test-only change;
the hosted full-suite rerun is required at the corrected PR head. Production
behavior, scientific criteria and the delivered binary are unchanged.

Receipts, raw data, figures, UI screenshots and identifiers remain under ignored
`local/diagnostics/science-20260906`. The local delivery index and startup wrapper
provide direct entry points without changing machine execution policy or
automatically connecting. No device reset, firmware/driver change, permanent
configuration write or guessed FP command was used in this increment.

The frozen plan lists the exact evidence still needed for physical FP scanning,
spectral calibration, reflectance uncertainty, thermal-paint temperature-history
models, learned defect detection and spectral-library/unmixing extensions.
Original-code licensing and public binary release remain deferred.
