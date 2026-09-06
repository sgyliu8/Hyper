# Scientific roadmap review: reviewer 3, round 3

Date: 2026-09-06. Inputs read in full: all three round-two reports
([physics](science-r2-physics.md), [statistics](science-r2-statistics.md),
[software](science-r2-software.md)) and the ten version-one decisions in
`docs/dev/SCIENCE_CANDIDATE_PLAN.md`. No production code or hardware changed in
this review. This is a final design vote, not implementation or physical PASS.

## Resolution of the remaining disagreements

I accept the coordinator's **one true-coordinate local-polynomial operator** for
S4. This replaces my round-two suggestion of separate finite-difference and SG
interfaces. Reviewer 2's revised contract handles irregular measured spacing
without inventing a resampled axis and uses the existing NumPy dependency. It is
a smaller software surface than two derivative APIs if its window, rank and edge
rules are enforced. The UI must call it `Local polynomial`, with derivative order
0/1/2. Uniform-grid agreement with SciPy SG is an independent validation example,
not a reason to label irregular-grid results SG or add SciPy to production.

I accept reviewer 1's role-specific measurement-context contract. The source
metadata tree used by S1 is separate from editable S6 study annotations. It can
state declared/documented compatibility; it cannot certify the instrument,
optical registration, light stability or reference uncertainty. Empty nested
settings are unknown, while zero gain, disabled Boolean processing flags and an
explicitly empty processing history can be valid known values. Darks need their
own role and blocked-light method, not sample/white illuminated-condition values.

I accept reviewer 2's comparison-wide feature set, not pair-specific finite
subsets, and separate quality versus support counts. Missing correlation or angle
remains an unavailable cell with a reason. IQR describes Q25 to Q75 of the actual
used samples. No transformed-summary uncertainty ribbon is inferred from that
interval or from the raw spatial SD.

I accept **S9 as an explicit implemented package**. It resolves the omission
identified in rounds 1 and 2: averaging stored color channels can hide a paint
color change. It is one selected stored-channel trace over the durable sequence,
not a new recorder or an SNR/temperature-analysis system.

## Final S1-S9 votes

All ACCEPT votes below accept the bounded implementation specification and its
listed checks. They do not assert that code already exists or tests have passed.

| Package | Final vote | Frozen software acceptance |
|---|---|---|
| S1 | **ACCEPT** | Shared role-aware preflight retains every UNKNOWN/MISMATCH reason and evidence source. It rejects incompatible or missing required context before correction. Analyst annotation edits cannot satisfy or override it; no synthetic bypass. |
| S2 | **ACCEPT** | Preserve mean/SD default and original quality counts; add linear quartiles/raw MAD/range and explicit actual used/support-excluded counts. `stats.count` is the denominator of each returned statistic. Common support intersects selected enabled features only; empty support never falls back. |
| S3 | **ACCEPT** | One common finite selected-feature list for the entire comparison; equal-feature weighting; target-minus-reference bias; unit-preserving RMSE; at least three nonconstant features for correlation with axis-specific labels and no p-values. RGB retains its SAM restriction. |
| S4 | **ACCEPT** | Single true-coordinate local polynomial for smooth/d1/d2; complete centered original-index windows, default width 5/degree 2, rank rejection and unsupported edges NaN. Exact-band interval integral/mean and reflectance-only endpoint-continuum depth/area reject gaps. Retain increasing-nm calculation mapping, original axis/index metadata, reflectance kind and summary-then-transform semantics. |
| S5 | **ACCEPT** | Reference ROI RMSE uses fixed features, valid reference support and complete mapped pixels; sequential scale. Normalized difference uses a positive documented threshold on absolute denominator and a zero-centered diverging scale; invalid grey and no clipping or defect probability. |
| S6 | **ACCEPT** | Small isolated source-bound, versioned analyst record; nullable specimen/batch/substrate/session/replicate and thermal-history fields with explicit temperature meaning/reference and dwell seconds. Saving or correcting it changes derived context identity, not raw/source evidence. |
| S7 | **ACCEPT** | Export one pinned completed numeric result/PlotSpec, recipe, actual support/units, source identity, annotation revision and artifact hashes. Figure/CSV/JSON agree. Failure/partial evidence and raw source bytes survive; no per-preview hashing. |
| S8 | **ACCEPT** | One method selector/context panel/Run and one Export menu, compact results dialog, Analysis-owned chart controls and expandable view options. Current completed PlotSpec owns the chart label. Stop remains accessible across tabs during streaming; offline empty metrics are hidden without hiding failures or capability reasons. |
| S9 | **ACCEPT** | Select an actual stored channel/feature, preserve its index/name, and trace every durable frame with the existing source clock/index. No default average of RGB. Preserve selected-channel used/quality counts, missing-frame gaps, settings mismatch/unknown status and partial-prefix accounting. |

No unresolved design rejection remains for S1-S9 under these conditions. The
deferred items remain RX, automated thresholds/probabilities, model training,
thermal inversion, sensor-noise certification, covariance uncertainty,
response-weighted library resampling and automatic sub-band/FWHM inference.
No public example or newly added control changes the connected camera's H2-H4
status.

## Counterexamples that the implementation must resist

These are acceptance cases, not claims that reviewer 3 executed new tests.

- **Annotation cannot repair source applicability:** sample and white carry
  different response-calibration IDs, then the analyst types equal illumination
  and geometry IDs into S6. S1 must still reject the source mismatch, and both
  acquisition sidecars must remain byte-identical.
- **Comparison cells cannot silently change their features:** for summary
  vectors A=`[1,2,NaN]`, B=`[1,2,3]`, C=`[NaN,2,4]`, the common comparison-wide
  finite set is the middle feature. Bias/RMSE can use that one feature; correlation
  and angle are unavailable. An A-B two-feature angle and B-C two-feature angle
  must not appear as a supposedly comparable matrix without an explicit new mode.
- **Compressed bands do not restore a gap:** a selected original-index sequence
  `[0,1,3,4,5]` cannot form a complete five-band polynomial or continuum interval.
  By contrast, adjacent original indices with naturally irregular documented
  wavelength spacing are admissible to the true-coordinate fit.
- **A known polynomial does not need edge invention:** over five irregular
  measured wavelengths, a quadratic `2 + 3*(lambda-c) + 0.5*(lambda-c)^2`
  centered at the middle sample has smooth value 2, d1 3 and d2 1 there, with
  appropriate signal/nm powers. With window 5 only that centered location has
  support; the four edge positions remain unavailable. Descending storage and
  nm/um representations must describe the same physical calculation.
- **The channel average can conceal change:** stored RGB values
  `[10,30,5]`, `[20,20,5]`, `[30,10,5]` all average to 15. S9 must show selected
  R as 10,20,30 and selected G as 30,20,10 with the recorded channel identity.
  BGR storage must use its recorded labels rather than silently assuming RGB.
- **Partial capacity is not recorded data:** for an allocated 300-frame sequence
  with 64 durable frames and a recorded rejected frame, S9 reads only those 64,
  retains the partial/overflow metadata and does not add 236 zero-valued samples.
  It can complete analysis of that partial prefix without relabelling acquisition
  as a successful 300-frame recording.
- **Requested work is not displayed work:** while ROI curves are displayed,
  request PCA loadings and inject failure. The selector/title/export must either
  stay with the old explicitly pinned ROI result or show no result; it cannot
  claim PCA loadings while exporting ROI numbers. Repeat with annotation edits
  and a late callback to exercise context versioning.

## Final minimal annotation, UI and export contracts

Use the isolated `experiment_metadata.py` proposal from round 2 with small
normalization/validation/read/save functions and JSON records in the ignored
workspace. Empty strings become null; finite numeric zero stays zero. Temperature
has a value/unit/meaning tuple and a reference for an independent-measurement
declaration; thermal dwell and camera integration time are different fields.
No complete study form is required for basic descriptive ROI analysis. Only a
selected physical operation's evidence gate can block that operation.

Every saved annotation revision identifies its source and predecessor; no raw
array or acquisition/calibration sidecar is edited. On restore, same path with
different source identity is a mismatch. A missing annotation file remains
unresolved, not silently reconstructed from another specimen. A live session
draft may stay lightweight, but export pins the actual annotation content/revision
to the exact frame/sequence used. Record evidence kind as analyst annotation;
never manufacture `verified` status or matching instrument/calibration IDs.

The main English Analysis workflow is named ROIs, summary/support, method and
relevant parameters, Run, results and Export. The completed result has one
source/ROI/feature/support/summary/method/annotation identity. A pending request
has a separate computing state. Only completion atomically changes the active
PlotSpec, view selector, caption and export target; a stale callback is discarded.
The selected unavailable method displays a short reason and Details. Stop is
available whenever the camera worker may still be acquiring, regardless of tab.
Keep source origin, units, actual method and current error visible while moving
verbose diagnostic descriptions out of the main working area.

S9's channel selector belongs with the recorded-trace method and is populated
from the opened sequence schema. A Bayer plane is `Sensor plane`, a declared
color channel uses its stored label, and an unnamed feature uses its recorded
index. Do not offer a wavelength name without wavelength evidence. Settings
MISMATCH rejects inappropriate pooling; UNKNOWN may remain an explicit
descriptive limitation. Invalid ROI frames appear as gaps with counts, not zero.

Export uses the completed numerical result rather than rerunning analysis from
the current controls. The bundle includes the exact parameters, raw/effective
feature mappings, support/quality counts, aggregation order, units, origin,
annotation revision, source digests and output digests. Hash on explicit save or
export, not live redraw. An export failure remains a failed/partial record and
must not announce success. Native visual checks and independent numerical oracles
are separate evidence; neither alone validates a material or temperature claim.

Reviewer 3 final design disposition: **ACCEPT S1-S9 for implementation with the
frozen contracts above**. All nine requested review records must exist before
production edits begin. Implementation acceptance remains pending its numerical,
state/UX, real saved-data and packaging checks; physical claims remain bounded by
the source evidence.
