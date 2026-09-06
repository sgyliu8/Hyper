# Candidate plan and convergence decisions

Version 0, 2026-09-06. Not frozen. Owner confirmed both thermal paint and defect
detection of paint/material differences. All mathematical results are descriptive
unless their calibration and independent validation conditions are established.

## Candidate implementation packages

| ID | Proposed behavior | Required acceptance |
|---|---|---|
| S1 | Shared reference-applicability report before correction: documented nonempty settings, response calibration, illumination and geometry, correct dark roles | Mismatched and unknown applicability rejected; compatible example reproduces ratio without clipping; diagnostics explain each missing field |
| S2 | ROI mean/SD plus median, quartiles, IQR, raw MAD, valid fraction and complete quality denominators; selectable per-band vs common spatial support | Independent hand-computed outlier/mask cases; empty and saturated bands preserved; no pixel-count CI or SNR claim |
| S3 | ROI-pair bias/RMSE, correlation and admissible spectral angle, with fixed common feature set and reference naming | Positive scale/offset/constant/zero-vector/gap examples; RGB has descriptive channel metrics only; no probability or defect class |
| S4 | Wavelength-aware ROI smoothing, first/second derivative, trapezoid integral, and endpoint-continuum depth/area with explicit interval | Physical nm conversion, descending/irregular axes, invalid bands and gaps handled explicitly; reflectance-only depth; no inferred nm for RGB/state axes |
| S5 | Reference-ROI amplitude-distance map and normalized difference map, alongside existing PCA/SAM/difference/ratio | Named features, units, completeness mask, same numeric arrays in UI and export; undefined denominators grey; no statistical significance/probability |
| S6 | Structured specimen/session/batch/substrate and thermal exposure/illumination/geometry annotations, separate from immutable acquisition evidence | Empty stays unknown; edits invalidate derived provenance; saved/exported/restored annotations; no guessed labels or temperature inversion |
| S7 | Publication bundles containing numerical summaries, selected transformations, parameters, units, masks, source and condition provenance | CSV/JSON and PNG/SVG/PDF agree; no source mutation; gaps and uncertainty semantics visible |
| S8 | Simpler Analysis workflow: ROIs → method → relevant parameters → Run → one Export menu; move chart controls out of Acquisition | Native before/after evidence, no competing chart selection vs visible plot, usable at current display scale; source truth remains visible |

Keep current mean/SD + L2 appearance as the default. Robust statistics and
transforms are explicit choices, with amplitude retained. A compact results dialog
or table can expose extra numbers without permanently shrinking the scene.

## Dependencies and verification

S1 and capability fixes precede physical spectral products. S2 precedes S3/S4.
S3/S4/S5 share PlotSpec and deterministic exports. S6 supplies experiment metadata
for S7. S8 integrates the same core functions through background jobs with pinned
source/ROI/method versions. Run baseline and regressions, independent numerical
oracles, actual saved RGB/Bayer evidence, one inspectable external measured
spectral example if its axis/provenance/license are sufficient, and native UI QA.

Current unknowns and deferred claims: FP control/reconstruction/calibration assets;
temperature regression and class probabilities; trained defect segmentation;
camera-certified SNR/measurement uncertainty; instrument drift qualification.
These must remain explicit conditions rather than cosmetic enabled controls.
Research should describe their correct later validation chain and required data.

## Root source and native audit notes

- [Griffin et al., ICPR 1996](https://cmp.felk.cvut.cz/~matas/papers/griffin-icpr96.pdf):
  full author-hosted paper inspected. Thermal-paint colour trajectories can have
  ambiguous inverse mappings; calibration and spatial assumptions are essential.
  Its planar demonstration does not validate shading correction on curved parts.
- [Ge et al., Measurement 2022](https://doi.org/10.1016/j.measurement.2022.111741):
  publisher-indexed abstract/highlights inspected; direct full text was blocked.
  Sub-band spectral statistics are a useful design example, not reproduced accuracy.
- [Mazdeyasna et al., Biosensors 2025](https://www.mdpi.com/2079-6374/15/1/20):
  indexed methods/discussion inspected; direct requests were limited. Normalizers
  have different noise sensitivities and can suppress true target variation.
- [SolarBlack coating study, Materials Letters 2019](https://doi.org/10.1016/j.matlet.2019.07.085):
  abstract inspected. VNIR/FTIR with PCA revealed coating nonuniformity; thermal
  control coatings are distinct from thermal history paints.
- [hylite](https://github.com/hifexplo/hylite): original package and documented
  minimum-wavelength, library, band-ratio and correction examples. Geological
  demonstrations provide computational patterns, not coating identification truth.

All sources accessed 2026-09-06. Do not transfer paper accuracy to this instrument.

Native audit captured the current real RGB replay at 2048 × 1104 through Computer
Use, with separate Acquisition/Analysis/Calibration screenshots retained locally.
The Analysis sidebar mixes many operations and exports in one long scroll. The
Acquisition chart selector shows PCA loadings while the computed figure shows
ROI amplitude/L2. Camera actions and empty metrics remain prominent offline. The
approved plot palette and raw/derived image arrangement should be retained.

## Version 1: frozen round-three implementation plan

The three round-two reports are the input to these decisions. All three
round-three reviewers accepted the conditions below; S1-S9 are now implemented
and verified in the [delivery record](SCIENCE_ROADMAP_REVIEW.md). The version-zero
record above remains the proposal history. Conditional extensions stay separate.

1. S1 uses the physics review's fixed, role-aware measurement_context fields.
   All four inputs require known matching instrument, response calibration,
   thermal condition and recursive nonempty settings. Sample/white share known
   illumination and geometry; darks require blocked light and a documented method,
   not equal illumination. Evidence origin remains declared/documented; entered
   experiment annotations cannot satisfy this source-evidence gate. Preserve
   UNKNOWN and MISMATCH details and the existing masks/positive denominator.
2. S2 retains per-band summaries as default, adds median/Q25/Q75/IQR/raw MAD,
   min/max, valid fraction and common support. Keep policy-quality counts and
   actual used counts/support exclusions separate. Common support intersects only
   the selected enabled features. Empty support never falls back. Robust figure
   ribbons are Q25 to Q75, with mean/SD still available.
3. S3 freezes one common feature set across all compared ROIs, direction target
   minus reference, equal-feature bias/RMSE and descriptive correlation for at
   least three nonconstant features. RGB correlation says channel correlation;
   RGB gains no SAM. Summary and spatial-support modes travel with the result.
4. S4 uses one small NumPy local-polynomial least-squares operator on centered,
   scaled ACTUAL wavelength offsets for smoothing/first/second derivatives.
   Name it Local polynomial, not irregular-grid Savitzky-Golay. Default window
   five, degree two; odd complete centered windows only; unsupported edges stay
   NaN, rank failure is explicit. Test exact polynomials, irregular spacing and
   uniform-grid interior agreement with an independent SciPy SG oracle. SciPy
   is a local validation tool, not a production dependency. Canonical increasing
   nm and original index/unit mapping are retained. No gap filling/resampling.
5. S4 interval integral/mean and straight endpoint-continuum depth/area use exact
   selected original bands, reject gaps and require valid complete common-support
   summaries. No hidden endpoint interpolation/extrapolation. Depth requires a
   reflectance cube, retaining relative/calibrated kind and evidence status.
   Signed depth and above-one reflectance remain unclipped. Sampled minimum is
   not a fitted band center/FWHM. Summary-then-transform results have no propagated
   SD/IQR; the original amplitude branch stays accessible.
6. S5 implements reference ROI RMSE (sequential color scale) and normalized
   difference (zero-centered diverging scale), with fixed selected features,
   explicit units/denominator threshold and masks. Reject empty/invalid reference
   support. RX/Mahalanobis and automatic thresholds/probabilities are deferred.
7. S6 is an isolated source-bound, versioned analyst-annotation record. Nullable
   specimen, batch, substrate, session/replicate and thermal-history fields retain
   temperature kind/source, dwell in seconds and unknowns. It never edits raw
   NPY or its acquisition sidecar and never promotes declared evidence to verified.
   Include annotations and their revision in every new analysis/export identity.
8. S7 uses existing PlotSpec/CSV/vector exports plus a bounded analysis manifest
   containing method, parameters, units, source hashes, annotation revision,
   feature/support/quality counts and output hashes. Hash at explicit save/export,
   not every preview. Raw byte identity must remain unchanged. Additional display
   modes and tables use the same numerical results; no second analysis engine.
9. S8 uses ROI controls, summary/support choices, one method selector with context
   controls and one Run, a compact result-table dialog, one Export menu and an
   expandable plot/view section. Move chart selection from Acquisition to Analysis.
   Actual completed PlotSpec is authoritative; in-flight requested method does
   not rename previous results. Keep Stop accessible across tabs while streaming,
   hide empty camera metrics offline, preserve short source/unit/capability text.
10. Add S9 as the bounded omitted repeatability improvement: recorded ROI traces
    select a real stored channel/feature instead of averaging R/G/B by default.
    Preserve source clock/index, all durable frames, partial status and mismatch
    checks. This is observed temporal variability, not calibrated sensor noise.

## Explicit conditional roadmap after this increment

| Future capability | Evidence needed before use |
|---|---|
| FP scan and spectral reconstruction | Correct hardware/controller identity, documented protocol, acknowledged states/settling/frame association, matching response assets and independent wavelength checks |
| Reflectance standard uncertainty | Input standard uncertainties and full dependence/shared-dark/reference covariance; stated measurement model and near-zero/nonlinear policy; no SD/sqrt(pixels) substitute |
| Thermal-paint temperature-history model | Independent calibrated coupon histories, paint/batch/substrate/dwell/atmosphere/geometry applicability, ambiguity/out-of-range rejection and held-out specimen/session validation |
| Learned defect segmentation, PLS/SVM/foundation model or RX thresholds | Defined normal/defect labels, source/domain compatibility, group-disjoint data with patch-footprint control, train-only fitting, untouched test set and complete specimen-level denominators |
| Spectral library matching/unmixing | Compatible units, illumination/geometry and response/wavelength support; supplied FWHM/response for resampling; physical mixture-model assumptions and independent mixtures |

Equations, examples and implementation requirements for these later capabilities
belong in the research guide. No model weights, fabricated labels or guessed
hardware controls are needed to complete the present S1-S9 implementation.
