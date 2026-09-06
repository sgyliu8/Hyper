# Round 2 — physical measurement cross review

Reviewer: AI reviewer 1. Date: 2026-09-06. Inputs read: candidate plan version 0
and the complete first-round statistics, software and physics reports. No new
camera/UI operation, production edit or dataset download was performed. Source
evidence and access limitations remain those recorded in
[round 1](science-r1-physics.md); this round evaluates the proposed contracts.

## Direct response to reviewer 2: statistics and spectral mathematics

**Accept robust summaries and common support.** The statistics review correctly
identifies that per-band finite means may sample different spatial populations.
Retain the original per-band mode, label it, and make common support an explicit
analysis choice. For the first wavelength-feature workflow I prefer common
support across the selected interval by default. A globally bad feature should
not enter the common-pixel AND for unrelated pair comparisons, but a globally
bad band inside an integration/continuum interval must stop that interval. Those
are different rules, not contradictory masking policies. Preserve original
quality counts plus the extra common-support rejection count.

**Accept the numerical definitions, with two limits.** The quartile convention
and raw MAD are sufficient; a second Gaussian-scaled MAD option is unnecessary
for this increment. IQR shading runs from Q25 to Q75, never median ± IQR.
Pairwise RMSE/bias is useful immediately, including RGB channel summaries.
Pearson correlation may be displayed only with at least three common features
and nonconstant vectors, with no p-value or inferential significance. Spectral
SAM remains under the existing spectral/state capability rules; for raw scans
the label must say state-vector angle rather than wavelength-spectrum accuracy.

**Revise the preprocessing scope toward one auditable implementation.** I accept
actual-wavelength derivatives, uniform-grid SG and explicit interval features.
I do not require an irregular-grid polynomial fitting system, automatic peak
fitting or gap interpolation. A first version may reject an entire selected
interval when support is incomplete rather than introduce a complex segmentation
engine. Canonicalize coordinates to increasing nm in a derived result and retain
the original index/unit mapping. Never rewrite the source axis. SG order/window,
uniformity tolerance and edge mode must be frozen, not inferred per curve.

**Accept reflectance-only continuum depth, with a naming refinement.** A
relative reflectance ratio may still contain the reference panel's spectrum.
Its continuum result is a descriptive relative-spectrum feature unless the
reference factor is known. Therefore preserve `reflectance_kind` and geometry
in the feature result; do not imply all `reflectance_cube` inputs carry identical
physical evidence. Keep negative depths and unresolved minima visible. A
wavelength argmin is the minimum among measured samples, not a fitted band center
or a resolution estimate. The asymmetric-shoulder 20 nm example is a good oracle.

**Accept deferring camera SNR and predictive statistics.** Temporal SD and drift
are useful with current recordings. Incomplete/unknown stationary-scene or
processing evidence must remain explicit. I support the warning against random
pixel splits and against treating a retrieved paper's claimed disjoint sampling
as proof of nonoverlapping patch footprints. This increment needs a study/context
record, not a classifier or automated hypothesis test.

## Direct response to reviewer 3: software and interaction

**Accept one computation/plot/export contract and a simple workflow.** S7 should
extend PlotSpec plus one analysis record. No graph editor, plugin registry or
second data model is needed. Hash source artifacts at an explicit analysis/export
boundary and reuse that identity; do not hash every preview frame. An analysis
record must include its exact annotation revision, because specimen or treatment
corrections affect interpretation even when the numerical array is unchanged.

**Revise the proposed RX/Mahalanobis addition to deferred.** The candidate's
reference-ROI RMS distance avoids a covariance inverse, a regularization choice
and an inadequately defined background sample size. It is useful for locating
material/paint differences without pretending to estimate a defect probability.
RX would require a specified fit population, independent effective sample count,
conditioning diagnostics and threshold validation; it is not necessary to finish
the present descriptive chain. Existing PCA remains exploratory and already
records its fit scope; do not introduce a second engine.

**Accept role-aware references, rather than a large calibration manager.** A
small operation form can select sample/white/two dark sources and present the
same preflight used by the API. It must distinguish role correctness from simple
equality: a dark with blocked illumination is not supposed to have the same light
condition as the sample. Matching documented context means evidence compatibility,
not physical certification. An imported external spectral example can exercise
the arithmetic; it does not advance this camera's H2–H4 gates.

**Accept provenance-preserving experiment annotations.** A measured temperature,
an oven setpoint and a model estimate are distinct. Do not create a generic
temperature column that can mix them. Thermal history, paint chemistry/batch,
substrate and specimen/session IDs are useful for future design and analysis;
unknown values must remain null rather than become guessed labels. Entered
annotations must not rewrite an acquisition sidecar. The normal offline workflow
must neither open hardware nor imply the selected real replay is LIVE streaming.

**Accept removal of redundant UI controls, with an invariant.** Source origin,
the active numerical method, unit and source/derived distinction must remain
visible. Long explanations may move to Details; the active method cannot be
hidden behind a stale chart selector. A native check must show that the method
control, visible curve/map, saved recipe and exported numbers describe one result.

## S1: minimal implementable applicability contract

Use a fixed dictionary under cube metadata, separate from editable specimen
annotations. An illustrative name is `measurement_context`; the implementation
may choose the existing project's closest naming convention. No schema registry
or permission flow is required. The following fields have a concrete purpose:

| Field/group | Check and role |
|---|---|
| Existing shape, wavelength vector/units, source and linearity flag | Retain current numerical/admission checks. Do not turn declared wavelength metadata into experimentally verified calibration. |
| Existing `settings`, exposure, gain, units and processing steps | Settings must be a nonempty mapping. Required values must be finite and known recursively. Empty processing history is legitimate; it must not be rejected as an unknown setting. All four inputs must match the current conservative acquisition domain. |
| `instrument_id` | Nonempty opaque identity, common to all four sources. A local identifier or instrument record reference is sufficient; it need not be a public serial number. |
| `response_calibration_id` | Nonempty calibration/response applicability record common to all four sources. A human-readable filename alone is an assertion, not independent calibration verification. Preserve its source/evidence description. |
| `temperature_condition_id` or a documented equivalent in the response applicability record | Common thermal operating condition within which the response/dark correction was established. Do not infer this from room-temperature assumptions or treat sensor temperature as FP temperature. The narrow first path may use equality of an explicit condition record, with no invented tolerance. |
| `role` | Sample = `sample`, white = `white`, both dark inputs = `dark`. The same measured dark may serve both roles when the other checks pass; shared uncertainty is a later covariance concern. |
| `illumination_id`, `geometry_id` | Required and equal for sample and white. Do not apply this illuminated-condition equality to darks. Reference geometry must refer to the applicable optical arrangement/registration assumptions, not only array shape. |
| `light_blocked`, `dark_method` | Darks require `light_blocked=true` plus a nonempty method/evidence description. A sample merely renamed dark fails role checks. |
| `evidence_source` | Nonempty source or operator record describing these declarations. Export it with its declared/documented/verified level; do not manufacture a verified status. |

Unknown is not a fourth numerical value. Missing fields, null, whitespace,
nonfinite numeric settings and declared unknown/unavailable values are UNKNOWN.
Known conflicting values are MISMATCH. The report should return one overall
status and compact per-field `role`, `field`, `status`, `reason` items. MISMATCH
takes precedence over UNKNOWN, but retain both sets of details. The physical
correction entry point rejects either. The UI can inspect the report without
changing or applying references. Existing raw ROI/image analysis remains usable.

The thermal condition can be represented inside the existing response record
rather than as a second full metadata tree. The essential requirement is that
applicability is explicit and inspectable, not merely a string named calibration.
This is an intentionally conservative compatibility check, not a general
cross-instrument radiometric calibration framework.

**Synthetic migration is explicit.** Update each synthetic helper to declare
its known mathematical roles and context, e.g. a synthetic instrument/calibration,
shared synthetic optical setup and blocked-light dark method. Fixture provenance
must remain SYNTHETIC. Do not add a `synthetic` bypass, auto-fill missing context
when loading existing files, or weaken the check because previous tests omit
fields. Legacy missing metadata should receive an informative rejection.

Minimum S1 regression matrix: reproduced incompatible-context case; settings `{}`
and nested unknown; device/calibration/temperature mismatch; sample/white light
or geometry mismatch; wrong/unknown dark role; dark without blocked-light method;
different dark illumination IDs that correctly pass; matched fixture preserving
negative and above-one outputs; unchanged source metadata/arrays; UI/API share
the same report. No new camera session is needed for these cases.

## Vote on candidate S1–S8

| Candidate | Vote | Exact convergence condition |
|---|---|---|
| S1 applicability | REVISE, required | Use the role-aware fixed contract above; shallow equality and a nonempty arbitrary recipe alone do not establish applicability. Inspectable UNKNOWN/MISMATCH reasons; no synthetic bypass. |
| S2 robust ROI/support | ACCEPT with conditions | Mean/SD remain default. Linear quartiles/raw MAD; per-band versus selected-feature common pixels recorded; complete counts plus support exclusions; empty common support never silently falls back. |
| S3 pairwise comparison | ACCEPT with conditions | Fixed shared finite features and units, named comparison direction for signed bias, RGB descriptive labels, SAM gate unchanged, correlation at least three nonconstant features and no p-value. |
| S4 spectral transformations/features | REVISE | Restrict to evidenced ordered wavelength axis; canonical increasing nm with original mapping; explicit interval resolved to actual samples; complete interval support; SG only a supported uniform grid; units/edge policy; reflectance provenance retained for depth; no inferred peaks/resolution. |
| S5 reference maps | ACCEPT with conditions | Reference distance = `sqrt(mean((pixel-ref_mean)^2))` over the fixed features, in source units, no fitted probability. Normalized difference uses an explicit positive threshold for absolute denominator magnitude, retains negative/above-range valid values, and masks undefined values. Map provenance includes reference ROI/support and selected features. |
| S6 specimen/condition annotations | ACCEPT with conditions | Separate versioned annotation record referenced by derived identity; null unknowns, explicit temperature kind/source/dwell units; existing capture evidence immutable; no temperature inverse. |
| S7 publication bundles | ACCEPT with conditions | One recipe, source/artifact hashes, selected indices, support/masks, method parameters, units and annotation revision; caption states spatial SD/IQR/temporal meaning; no certification or automatic independent-specimen claim. |
| S8 simple Analysis UI | ACCEPT with conditions | Current approved appearance remains default. One active method/result, contextual parameters and export entry; actual source and units visible; native stale-mode, offline and display-scale checks. |

## Uncertainty: change from first-round proposal

My first-round optional uncertainty calculator was conditional P2. I now vote
**DEFER executable uncertainty propagation from S1–S8**. The current data do not
provide input uncertainty/covariance, and adding a general covariance editor,
uncertainty source model and nonlinear-coverage policy would make this increment
larger and easier to misinterpret. A 20-line Jacobian calculator alone would not
close that chain. The smaller correct delivery preserves the equations and input
contract, states uncertainty is not supplied where relevant, and never relabels
spatial SD or IQR as metrological uncertainty.

The later admission condition is explicit measured or documented covariance,
including shared dark/reference terms, its variable order/units and the applicable
measurement model. Validate the Jacobian against finite differences and correlated
examples, then assess first-order adequacy near weak denominators. An independent
Monte Carlo example may validate the implementation, but assumed variances are
still assumptions. Even complete propagation is not certification without a
complete uncertainty budget and physical validation. This follows the BIPM/GUM
and HYPERNETS distinctions already sourced in round 1.

Round 2 outcome: **conditional support for S1–S8**, with S1 and S4 revisions,
explicit deferral of RX, uncertainty propagation, learned reconstruction,
temperature inversion and trained defect decisions. This is my review vote;
consensus requires reviewer 2, reviewer 3 and the coordinator to resolve these
conditions in round 3 before implementation.
