# Reviewer 2, round 2: cross-review and revised numerical contract

Date: 2026-09-06. Read both other Round 1 reports in full and candidate plan
version 0. This is an AI engineering cross-review. No production code, camera,
native UI or data files were changed. Round 1's source audit remains the source
register; the revisions below are engineering decisions and explicit derivations.

## Direct response to reviewer 1: physical measurement

**Accept F-P1 as a blocking software defect.** The reproduced correction of
incompatible calibration/illumination/geometry inputs invalidates an assumption
in my initial description of the baseline as having strict reference matching.
Its existing numeric ratio/masks are useful, but its applicability admission is
incomplete. S1 must precede newly exposed physical correction and depth controls.
Requiring equal empty dictionaries would preserve the defect. Require supported,
nonempty evidence and distinguish MATCH, MISMATCH and UNKNOWN for each requirement.

**Agree on role-specific matching.** Sensor/response/axis/linearity and relevant
acquisition settings must be compatible across all four inputs. Sample and white
must have matching illumination and illuminated geometry. Dark sample and dark
white need a recorded blocked-light method and relevant sensor/exposure/processing
compatibility; demanding equal illuminated conditions from dark frames is wrong.
One dark input may legitimately be reused when compatible, and its identity must
remain the same variable for any later uncertainty calculation.

**Challenge how context evidence is admitted.** Analyst fields such as
`geometry_id` are useful declarations, but equality of two arbitrary strings is
not physical verification. Record their origin (for example analyst declaration
versus acquisition/readback versus calibration artifact), source/version, and
status. The preflight can establish documented compatibility, not certify
registration, illumination stability or a traceable calibration. Missing physical
evidence must not be filled by automatically generated matching IDs.

**Accept the interval-mean distinction and counterexample.** A sampled signal
integral and an instrument-response integral differ. Implement exact-axis
trapezoids and an interval mean with stated units; response-weighted resampling
needs supplied response functions. The [500,510,540] nm, [0.2,0.3,0.6] example
gives 16 nm and 0.4. Descending storage needs an orientation mapping, not a negative
physical area caused by storage order.

**Defer covariance uncertainty as an exposed feature in this increment.** The
proposed Jacobian is useful and should remain documented. However, none of the
current actual data supply independently supported covariance and shared-reference
structure. A new uncertainty form without such data would be a large, weakly
testable workflow. Preserve SD/IQR wording and uncertainty-unavailable status.
This is a scope deferral, not rejection of the mathematical model.

## Direct response to reviewer 3: software and interaction

**Accept the shared recipe and compact workflow.** PlotSpec should consume one
numerical result. Method, summary, support, feature selection, units, quality,
ROI definitions and source/context version must all participate in the analysis
identity. A chart title cannot be switched independently of its computed method.
Hashing should happen at explicit analysis/export boundaries, never every live
redraw. Source annotation edits must invalidate derived results while preserving
raw arrays and original acquisition sidecars.

**Revise the pairwise feature rule.** Merely choosing common finite features per
pair produces a matrix whose cells describe different wavelength populations.
Freeze one common feature list across all ROIs in a displayed comparison. Report
excluded features and each ROI's spatial support. Per-pair subsets can be a future
explicit mode; they must not be the silent matrix default.

**Prefer candidate S5 over RX now.** A reference-ROI amplitude distance is
interpretable with the current small dataset and does not estimate an unstable
covariance matrix. RX is scientifically useful after a background population,
conditioning rule, fit/apply scope and threshold validation are established.
Regularization alone does not supply independent background specimens. Retain RX
in the research roadmap; do not include a nominal chi-square probability in the
current UI. S5 should use the same selected features as its reference vector.

**Accept per-channel temporal traces as a real omission.** The average of R/G/B
means can hide one channel increasing while another decreases. The existing
recording pipeline should eventually offer per-channel or explicitly selected
feature traces from all durable frames. This is missing from candidate S1–S8;
record it as a small follow-up to existing repeatability, not an unqualified
completion claim. No SNR, camera-noise certificate or specimen CI follows from
that trace. If omitted from implementation, its status must remain DEFERRED.

**Agree on training leakage but strengthen the unit.** Whole-scene exploratory
PCA is valid as a description. Its fitted transform cannot be reused for an
independent prediction claim. Grouping by specimen and acquisition session must
precede fitted preprocessing; spatial receptive-field overlap also matters for
patch models. A train/test label on pixels alone is insufficient.

## Revised numerical/API requirements

### R2-A: distinguish feature support, spatial support and quality

Use the existing `bands`/feature-selection mechanism to define an ordered set
`B`, with original indices retained. New ROI support option:
`support='per_band'|'common'`; default per-band for backwards-compatible
descriptive statistics. For common support in each ROI, use the intersection
of policy-valid pixels over B, not over globally rejected bands.

Return the selected-feature indices, original quality counts, actual used counts,
support mode, common-pixel count and support-excluded counts separately. Do not
relabel a pixel lost only to common support as a saturated or invalid sample in
another otherwise valid band. `stats.count` must always be the denominator used
for the returned statistic; any `counts.valid` field must explicitly state
whether it is policy-valid or finally used, with a tested accounting identity.
Do not leave two contradictory unlabeled valid counts in the CSV/table.

For complete-vector spectral features/comparisons, require common support or
explicitly label a feature-of-per-band-summary diagnostic; the safe initial
default is common support for those operations. Empty common support is
unavailable, not a silent fallback. RGB medians/IQR can use either declared
support; one-plane Bayer common support equals per-band support.

### R2-B: pairwise metrics and RGB correlation

For selected summary vectors, freeze one finite common B across all named ROIs.
For target t and reference r, bias is `mean(t-r)` and RMSE is
`sqrt(mean((t-r)^2))`, both in source units. State that bands/samples receive
equal weights; irregular wavelength sampling does not turn this into an integral.
The signed direction must appear in the table/export. Zero-feature comparisons
are unavailable. For one feature RMSE is the absolute difference.

Correlation is a mathematical descriptive coefficient on at least three features,
not inferential evidence. It can be shown for RGB as **Channel correlation**,
with feature count 3 and no p-value, significance stars or spectral label.
For a documented spectrum use **Spectral-shape correlation**; raw scans use
**State-vector correlation**. Constant/near-constant vectors return unavailable
with a numerical reason, not zero. Bayer one-plane correlation is unavailable.
The existing capability rule continues to govern SAM: RGB gains no spectral
angle just because a generic vector calculation is possible. Its L2 display
remains an explicitly separate channel-shape diagnostic.

### R2-C: nonlinear operations and ribbons

Record `aggregation_order='summary_then_transform'` for initial ROI transforms,
plus `summary='mean'|'median'`, spatial support and selected band list. A feature
of an ROI mean is not the mean of per-pixel features: generally
`f(mean(X)) != mean(f(X))`. Likewise normalizing a median or transforming Q25/Q75
does not generally produce the quantiles of transformed pixels.

Therefore transformed curves initially have no propagated SD/IQR ribbon. Keep
the original amplitude+spatial ribbon accessible in its own branch. Later
`transform_then_summary` must calculate valid transformed pixel features and
summarize those values with its own counts; it is a separate operation, not a
display toggle. A scalar division of an SD by an estimated normalization factor
must not be labelled measurement uncertainty.

### R2-D: original-index gaps and irregular wavelengths

Contiguity means adjacent original spectral indices with valid samples, not just
adjacent entries in a compressed list of globally valid bands. The first S4
implementation may conservatively reject an interval containing a bad band or
invalid summary. This is simpler and safer than silently filling or integrating
across missing support. A naturally irregular documented wavelength grid is not
itself a missing-data gap; use its actual spacings.

Do not add SciPy just to support a scalar-spacing smoother. HyperLab currently
depends on NumPy. Either:

- implement wavelength-aware finite differences plus trapezoids and defer
  smoothing/second derivative explicitly; or
- implement one small local-polynomial least-squares operator on true wavelength
  offsets, supporting smoothing/first/second derivatives under one numerical
  contract. Call it **Local polynomial**, not irregular-grid Savitzky-Golay.

For the second choice, choose an odd window w and degree p with d<=p<w. Within
each complete original-index window use centered, scaled actual wavelength
offsets `u=(lambda-lambda_center)/scale`, fit a polynomial using rank-revealing
least squares, and return `d! * coefficient[d] / scale^d`. Reject rank-deficient
fits. Require complete windows; edge samples without a complete centered window
remain unavailable unless a separately documented one-sided policy is chosen.
This handles true irregular spacing without a hidden resampling operation.
Record window, degree, derivative, scaling, edge policy and output units.
An equal-spaced implementation may legitimately be called SG but must explicitly
reject irregular grids; candidate acceptance cannot promise both with one scalar
`delta` call. This choice must be frozen in Round 3 before code is written.

Numpy's current dependency floor is 1.24; explicit trapezoid summation avoids
requiring the newer `np.trapezoid` name merely for this feature. Test both axis
orientations, nm/µm, exact polynomials, declared bad-band gaps and true irregular
coordinates separately. No storage mutation or undocumented endpoint interpolation.

### R2-E: reflectance-only continuum depth

Accept candidate S4's stricter `reflectance_cube` gate. This revises reviewer 1's
broader phrase "documented spectra": wavelengths alone do not remove source
illumination or sensor response. Show the reference kind (relative or calibrated)
and context status. Imported declared reflectance remains declared external
evidence; it is not this instrument's H4 qualification.

Use the exact endpoint continuum and interval from Round 1. Reject a nonpositive
continuum, nonfinite values, unsupported interior/shoulders and gaps. Do not clip
negative depth or an above-one reflectance factor. Expose a sampled minimum only;
sub-band peak fitting and FWHM remain deferred. Keep dimensional area and interval
mean distinct. An interval integral on raw wavelength-indexed DN is a descriptive
DN·nm quantity, not radiant power or calibrated absorption.

### R2-F: S5 maps

Reference amplitude distance is `sqrt(mean((pixel[B]-reference[B])^2))`; the
reference summary uses declared/common spatial support, and every mapped pixel
must be complete on B. Units stay source units. This is a nonnegative distance
map, not an anomaly probability, and it needs a sequential colormap.

Normalized difference is `(a-b)/(a+b)` with an explicitly positive threshold in
source units on `abs(a+b)`. Use a zero-centered diverging map and grey invalid
pixels. It lies in [-1,1] only under nonnegative inputs; do not clip signed
processed values to that range. RGB labels are recorded channel names; no NDVI
or other physical index name without actual appropriate spectral bands.

## Votes on candidate version 0

| Package | Vote | Required revision/condition |
|---|---|---|
| S1 | REVISE, mandatory | Close F-P1 with nonempty documented evidence, role-specific dark matching and explicit source-of-evidence; no synthesized matching IDs. |
| S2 | ACCEPT WITH CONDITIONS | Preserve counts/quantile convention and backward-compatible amplitude; distinguish used spatial support from original quality counts per R2-A. |
| S3 | REVISE | Freeze one comparison-wide feature list; named bias direction; >=3-feature descriptive correlation with explicit RGB/state/spectral label; unavailable constant cases; no p-values or RGB SAM. |
| S4 | REVISE | Freeze one minimal derivative method in Round 3; no compressed-band gap bridging; no transformed-summary SD/IQR; reflectance-only depth; exact units and aggregation order. |
| S5 | ACCEPT WITH CONDITIONS | Deterministic reference RMSE rather than RX, common completeness, threshold semantics, correct map centers/units, no clipping of unbounded signed normalized difference. |
| S6 | ACCEPT WITH CONDITIONS | Versioned analyst context separate from acquisition evidence; temperature field role explicit; context equality alone not physical verification. |
| S7 | ACCEPT WITH CONDITIONS | Source digest, support/counts, aggregation order, algorithm/version and output hashes; no inferential ribbon; physical evidence class retained. |
| S8 | ACCEPT WITH CONDITIONS | Single method/result authority; always-accessible Stop while streaming; contextual unavailable reason; no duplicate chart controls; preserve approved colors. |

Deferred: RX/threshold probabilities, supervised segmentation, thermal inversion,
camera-certified SNR, covariance uncertainty, response-weighted library resampling,
sub-band peak/FWHM inference. A compact per-channel durable-frame repeatability
improvement should be included if time permits or explicitly recorded DEFERRED;
it must not disappear from a claimed complete roadmap.

Round 2 outcome: **REVISE BEFORE CONVERGENCE**. S1–S8 form a sound bounded
implementation after the specified decisions. No three-reviewer consensus or
implementation acceptance is claimed until Round 3.
