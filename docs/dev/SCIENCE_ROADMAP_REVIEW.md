# Scientific workbench review and implementation record

Status: S1-S9 implemented and source validation passed; packaged/native closeout in progress. Opened 2026-09-06.

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
