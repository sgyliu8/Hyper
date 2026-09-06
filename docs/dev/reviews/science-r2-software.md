# Scientific roadmap review: reviewer 3, round 2

Date: 2026-09-06. Read both complete independent reports
[physics R1](science-r1-physics.md), [statistics R1](science-r1-statistics.md),
and candidate plan version 0 in `docs/dev/SCIENCE_CANDIDATE_PLAN.md`.
This response cross-reviews those records; it is not an independent new physical
experiment or a claim of three-reviewer consensus. No production code, camera
state or native UI was changed by reviewer 3.

## Direct response to reviewer 1: physical measurement

**F-P1 is a required first change.** The reproduced acceptance of explicitly
mismatched response/illumination/geometry evidence is more consequential than
adding another plot. I accept a shared MATCH / MISMATCH / UNKNOWN applicability
report, with MISMATCH taking precedence over UNKNOWN, and unknown required
evidence blocking the physical correction route. Sensor/response/axis/linearity
and relevant acquisition settings apply to all four inputs; illuminated geometry
and illumination agreement apply to sample/white. A dark requires its stated
role and blocked-light method, rather than fabricated illuminated conditions.

The software distinction needs one refinement: a user typing identical IDs into
an experiment form is not independent evidence that those conditions matched.
The report should retain the provenance class of each compared field. Existing
acquisition/readback or imported calibration declarations cannot be overwritten
by experiment annotations. A syntactically complete annotation may supply study
context; it does not manufacture a response matrix, verified wavelength axis,
per-frame setting or reference certificate. `MATCH` means the required recorded
evidence is compatible, not that HyperLab has physically validated the claims.
Do not add signatures, an online registry or a trust server for this distinction.

**F-P2: defer automatic uncertainty.** I support the derived covariance/Jacobian
contract as a later explicit calculator. S1-S8 need not acquire a covariance
model, a default sensor noise level or an uncertainty ribbon. Spatial SD, IQR,
temporal dispersion and reference uncertainty must remain distinct. Missing
uncertainty stays unavailable, including for an otherwise valid reflectance
ratio. This is a scope decision, not rejection of the proposed mathematics.

**F-P3: accept exact-axis intervals first.** The no-extrapolation/no-bad-gap rule
is implementable and makes the output auditable. Show the actual participating
band centers, since a requested interval and its sampled support may differ.
Defer general sensor-response resampling, automatic FWHM and peak fits; a Gaussian
response fallback from a library is not measured HinaLea calibration.

I accept the thermal-history metadata requirements and distinction between
setpoint, independent temperature reference and model estimate. To keep the form
small, expose specimen ID, coating/batch, substrate, session and a compact
thermal-history subsection. Longer preparation/atmosphere/cooling/geometry notes
can be optional. Requiring a large completed form before any descriptive ROI
plot would harm usability without improving the validity of that simple plot.
Only the selected physical operation's required evidence should block it.

## Direct response to reviewer 2: statistics and mathematics

**Priorities 1 and 2 are accepted together.** Adding median/IQR while leaving
changing pixel support implicit would retain a real interpretation gap. Keep
per-band valid pixels as the existing descriptive default. Offer common valid
pixels over an explicit selected-feature set, and require or prominently state
that choice for wavelength feature extraction. Globally excluded bands must not
participate in the common-support AND. Empty support is an unavailable result;
there is no silent imputation or fallback.

The data model must preserve two different counts: original quality accounting
and the samples actually used after the common-support restriction. Do not rename
valid samples in one band as sensor-invalid merely because a different band
excluded their pixel from the common analysis. Add an explicit support-rejection
count and actual used count. The table, ROI curve and CSV must use the same
support result. I accept `method=linear`, unscaled MAD, `ddof=0`, and asymmetric
Q25/Q75 shading; no `median +/- IQR` shortcut.

**Priority 3 is accepted with separate unavailable cells.** Bias/RMSE can remain
defined when angle or correlation is not. Require at least three common features
for a displayed correlation and a recorded near-constant criterion; no p-value.
RGB metrics must say channel comparison. Do not weaken the current RGB spectral
angle gate. Reference/test naming fixes the sign of the bias and the reference
for a distance map. Zero-vector, constant-vector and incomplete-feature cases
must not silently disappear from an exported comparison table.

**Priorities 4 and 5 need a narrow first release.** I accept wavelength-aware
finite differences for supported irregular coordinates and SG only under its
explicit regular-spacing/window/order contract. The method name and boundary
policy must distinguish them. Retain NaN gaps and do not create a measured point
at an interpolated location. The minimal continuum uses stated endpoint
shoulders on admitted reflectance, positive finite continuum and an interior
sample. Label these outputs `Feature of ROI mean` when that is what was computed;
the result is not the mean of nonlinear pixel-level features.

**Priorities 6 and 7 should reuse the current implementation.** Do not add a new
PCA engine or model trainer. Show the current fit population, preprocessing,
variance and loadings with a consistent selected result. For repeatability,
route to the existing all-persisted-frame trace rather than duplicating its
recorder/clock handling. Per-channel traces are a useful later extension for
paint, but no SNR or camera-noise certificate is needed in this increment.

**Priority 8 and all six objections are accepted.** In particular, saturation
exclusion must preserve the source/counts; selected feature indices are not
common spatial support; distinct patch centers are not disjoint spatial
footprints; a `linspace` made from wavelength endpoints is not recorded axis
evidence; and an empty paint repository is not an available validation dataset.
PCA/normalizers/feature selection and thresholds used for prediction must be fit
inside the training groups. That supervised evaluation system is deferred, with
its required specimen/session identity recorded now.

## Candidate votes and minimum acceptance

| Package | Vote | Required revision or precise scope |
|---|---|---|
| S1 reference applicability | **REVISE, then accept** | Add field-level reason and evidence origin; nonempty nested settings are necessary but not sufficient. Trusted source/calibration values are never replaced by typed experiment context. Preserve sample/white versus dark role requirements. Reject both the F-P1 counterexample and unknown required applicability before creating an output. |
| S2 robust ROI/support | **ACCEPT with count contract** | Mean/spatial SD remains default; median with Q25-Q75 is optional. Counts distinguish raw quality from selected common support. Exact linear quantiles/raw MAD; one-band working memory; no CI. Changing support/selected bands invalidates the old result definition. |
| S3 ROI pairs | **ACCEPT with cell validity** | Signed bias uses test minus named reference; RMSE retains signal units. Record common indices/count and support mode. Undefined angle/correlation is a reasoned null, not a dropped row. RGB has explicitly named channel metrics and retains the spectral-angle restriction. |
| S4 spectral features | **REVISE, then accept** | Finite differences and uniform-grid SG are distinct named choices; no general resampler. Wavelength unit normalization/original indices retained. Strict contiguous support for the first interval/continuum implementation; reflectance-only depth; transformed-ROI-mean meaning recorded. Automatic peak FWHM is deferred. |
| S5 maps | **ACCEPT narrowed scope** | Reference-ROI amplitude distance and normalized difference are sufficient now. Their exact feature set, reference ROI, equation/denominator tolerance and units travel with the map. RGB maps use channel wording; single-plane distance can be absolute DN contrast if explicitly admitted, but cannot pretend to be multiband. Keep undefined pixels grey. Defer RX and learned defect scores from my R1 broader suggestions. |
| S6 experiment annotations | **REVISE, then accept** | One isolated metadata module and a compact form; absent fields null, finite numeric values only; explicit temperature meaning and source reference. Versioned records refer to immutable sources. Editing annotations increments the analysis definition but never changes acquisition/calibration capability facts. |
| S7 publication bundle | **ACCEPT with pinned result** | Export the exact completed result, recipe and context revision used to draw it; never recompute with new controls while retaining an old caption. Source/outputs have private hashes; explicit complete/failed status. Preserve uncertainty and source-origin labels. |
| S8 workflow | **REVISE, then accept** | Contextual method/parameters and one Run; one chart-view selector in Analysis; one Export entry. Hide inactive offline camera metrics, but keep Stop accessible while streaming on any tab and keep failures visible. Disabled selected methods show one concise reason plus Details. Current PlotSpec is the chart-selection authority. |

No package receives an unconditional implementation PASS in this review. The
votes freeze the required behavior for round 3; coding and validation still
follow. Conditional physical features must not be described as newly validated
on the connected RGB/Bayer imaging branch.

## Minimal experiment metadata module

Proposed file: `src/hyperlab/experiment_metadata.py`. This is a proposal, not an
instruction to create a general study database. Small pure functions can normalize
empty input, validate supported scalar fields, read an existing record and save a
new record under the ignored workspace. No extra schema dependency is required.

An illustrative record structure is:

```json
{
  "schema_version": 1,
  "annotation_id": "generated-local-id",
  "supersedes": null,
  "created_utc": "recorded save time",
  "source_identity": {"file_sha256": "computed on save", "frame_identity": null},
  "evidence_kind": "analyst_annotation",
  "specimen": {"id": null, "material": null, "coating_batch": null, "substrate": null},
  "experiment": {"session_label": null, "replicate_id": null},
  "thermal_history": {
    "temperature_value": null,
    "temperature_unit": null,
    "temperature_meaning": null,
    "dwell_seconds": null,
    "reference_id": null
  },
  "conditions": {"illumination_id": null, "geometry_id": null, "notes": null},
  "reference_ids": []
}
```

`generated-local-id` and the text describing timestamps/hashes above are schema
illustrations, not values to insert into a scientific record. Real saved IDs,
timestamps and digests come from the application. Empty strings normalize to
null; numeric zero is retained. The temperature meaning is selected from
`setpoint`, `independent_measurement` or `owner_label`; a future model estimate
belongs to a derived product, not this input form. An independent-measurement
declaration must name its reference, while its uncertainty may remain unavailable.
The UI label must make clear that this is an entered declaration.

Temperature value/unit/meaning form a complete tuple when a value is supplied;
dwell must be finite and nonnegative. Reject NaN and infinity; do not infer units
or extract values from filenames. IDs describe relationships and never by
themselves establish calibration. Do not reuse `session_label` as the camera's
`session_id`, or thermal dwell as sensor integration exposure.

Save creates a new annotation revision with `supersedes` pointing to the previous
annotation ID. It does not patch raw NPY/ENVI, the camera evidence sidecar or
imported calibration bytes. UI state stores the selected annotation record and
verifies its source identity on restore. A same-path different-source file must
not silently inherit old specimen annotations. An active live frame may carry a
session-level draft annotation, but a publication export pins that draft/revision
to the exact displayed frame identity. Missing source bytes or annotation files
produce an explicit unresolved record, not invented replacement metadata.

Editing study annotations increments `analysis_version` and is part of the
background job's captured context. The saved original annotations remain part of
already exported results. The application can compare declared conditions, but
must use an independently named applicability input/report for the guarded
reflectance route. This prevents context usability from becoming a back door
around S1.

## Minimal UI and result-state contract

1. Keep the current scientific canvas: raw image, optional map, and bottom
   approved plots. A compact summary dialog/table exposes additional numbers
   without permanently consuming image space.
2. Keep named ROIs, Compare and the mean/SD versus median/IQR choice easy to
   reach. Advanced support selection should display its current state beside
   that choice. A data-dependent method selector exposes one relevant parameter
   panel and one Run button. Do not show irrelevant index boxes, PC controls,
   degree toggles and continuum controls simultaneously.
3. Inactive capabilities remain discoverable. Selecting an unavailable operation
   leaves Run disabled and shows a concise reason, such as `Requires documented
   wavelengths`; Details contains all failed/unknown requirements. Do not hide
   the reason in a hover-only tooltip or manufacture an enabled placeholder.
4. Chart selection describes the **actual completed PlotSpec**. A new request can
   show a separate Computing state, but cannot change the displayed chart label
   to PCA loadings while the old ROI curve remains. On success, atomically update
   spec, label, source and selector. On error/cancellation, retain the previous
   result explicitly labelled with its own source or clear it; never label it as
   the failed operation. Eliminate the competing selector in Acquisition.
5. While a camera worker is streaming/recording/stopping, keep Stop acquisition
   accessible from Analysis and References. Offline replay can hide Start/Record
   and rate rows. A failed save/record/compute operation keeps its failure message
   and durable evidence even when detailed diagnostics are collapsed. Retain
   normal camera connection state for a recorder-only failure.
6. Export opens choices for numeric result + recipe, publication figure and
   display image. Each uses the selected completed result and indicates if it is
   pinned to an earlier frame/ROI definition. A raw/source save is still a
   separate acquisition action. Source origin, units and unavailable-value
   semantics remain visible in the resulting file and caption.

Acceptance tests should deliberately submit a slow calculation, then change
source/ROI/support/method/annotation; obsolete callbacks must not update the
current result. Trigger a compute failure and verify selector/caption/numbers
remain consistent. Restore an annotation with a replaced source file and verify
the mismatch remains unresolved. Verify camera Stop access in an offline fake
streaming-state UI test; no new native session is required for that regression.
Native QA should check the visible layouts and keyboard route separately from
the numerical tests.

Round 2 disposition: **conditional accept of S1-S8 after the listed revisions**.
I withdraw RX as an immediate requirement and accept bounded reference-distance
maps first. Uncertainty propagation, sensor-response resampling, trained models,
temperature inference and defect accuracy remain separately gated/deferred.
Round 3 must confirm the trusted-evidence/annotation distinction, count semantics,
spectral gap rules and visible-result state before implementation is frozen.
