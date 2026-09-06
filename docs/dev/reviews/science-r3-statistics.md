# Reviewer 2, round 3: final mathematical convergence

Date: 2026-09-06. Read all three Round 2 reports and candidate plan Version 1
(ten decisions, S1–S9). This vote freezes a software specification, not executed
feature correctness or physical qualification. No production code, hardware,
native UI or scientific data were modified in this round.

## Final decision

**ACCEPT S1–S9 as specified in Version 1**, with the concrete acceptance contracts
below incorporated into implementation verification. There is no remaining
mathematical objection requiring another review round. The other reviewers and
coordinator still own their independent votes. No feature receives an
implementation PASS until its tests and evidence are complete.

## Dispute closure

| Dispute | Final resolution |
|---|---|
| Reference matching was described as strict, but F-P1 accepted incompatible contexts | Physics review prevails: S1 is mandatory and precedes exposing physical correction. Source measurement context, role-aware dark evidence and explicit UNKNOWN/MISMATCH checks close the gap. A typed study annotation never becomes source calibration evidence. |
| Common selected bands versus common spatial population | Both are necessary and distinct. Preserve original per-band quality counts; return used counts/support exclusions. Complete spectral feature workflows use common pixels over their actual selected interval. Bad bands excluded from a pairwise vector do not enter its support AND; a bad band inside a physical interval invalidates that interval. |
| Per-pair versus comparison-wide finite features | Use one frozen common feature set across every ROI in a displayed comparison. Null angle/correlation cells do not drop a pair or force its defined bias/RMSE to disappear. |
| Correlation on RGB | Allow descriptive **Channel correlation** only with at least three common nonconstant channels, with no p-value or spectral label. Existing RGB SAM restriction remains unchanged. |
| Uniform SG plus irregular finite differences versus a general method | Accept the coordinator's single NumPy **Local polynomial** operator. Centered/scaled actual wavelength offsets, complete odd windows and rank checks are small and explicit. This replaces two competing implementations. SciPy SG is only a local uniform-interior numerical oracle. |
| Nonlinear transformation and ribbons | Freeze `summary_then_transform`; transformed curves have no propagated SD/IQR. Keep the original mean/SD or median/IQR branch. A future per-pixel transformed distribution is a separately named operation. |
| Continuum depth on any wavelength-indexed signal | Require reflectance input and preserve relative/reference-calibrated/declared evidence. Raw DN integral remains descriptive DN·nm; it is not calibrated absorption. |
| RX/Mahalanobis now versus interpretable contrast | Defer RX and thresholds. S5 reference RMSE and normalized difference provide useful maps without unsupported covariance or probability claims. |
| Temporal color changes hidden by averaging R/G/B | S9 now explicitly selects an actual stored channel/feature and traces all durable frames. No camera-noise or independent-specimen inference is added. |
| General uncertainty and trained physical outputs | Defer executable covariance uncertainty, temperature inverse, supervised defect predictions and calibration recovery. Their needed evidence and equations remain in the research roadmap. |

## Final numerical/API shape

These names are illustrative and may match existing project style; their
semantics and output evidence are the frozen contract. Reuse existing Cube,
quality, feature selection and PlotSpec structures instead of adding a second
analysis engine.

1. **ROI summaries:** extend `roi_statistics(cube, rect, policy=...,
   bands=..., support='per_band')` and comparison/export paths. Preserve the
   existing mean/SD/count outputs. Add median, Q25, Q75, IQR=Q75-Q25, raw MAD,
   min/max, policy-valid fraction and actual used fraction. `count` is always
   the denominator for the reported statistics. Keep policy-quality counts and
   common-support exclusions separately named. Record `quantile_method='linear'`,
   `std_ddof=0`, support mode and selected original indices. A selected spectral
   transform uses the common-support summaries it actually received.
2. **Pairwise metrics:** receive pinned summaries/names/support, with target
   minus reference bias and unweighted-feature RMSE. Freeze one finite B for all
   included ROIs. Return one record per ordered or explicitly named pair,
   including all metric values, per-metric unavailable reasons, feature indices,
   units, summary type and support. Correlation requires >=3 dimensions and
   a scale-relative near-constant rule; use, for example,
   `norm(v-mean(v)) <= 1e-12 * norm(v)` in float64 (zero vectors included).
   Record that numerical rule. No correlation p-values. SAM remains capability
   gated, with radians/degrees explicit. A zero vector invalidates SAM, not a
   finite amplitude difference.
3. **Spectral coordinates:** admit ordered unique documented wavelengths with
   known units. Convert a derived coordinate vector to increasing nm and retain
   the exact original-index mapping plus original wavelength/unit evidence.
   Reversed storage is legitimate. Never sort one vector without applying the
   same mapping to signal, validity and indices. No gap filling or extrapolation.
4. **Local polynomial:** one function accepts wavelength/signal/validity plus
   operation smooth/d1/d2, window=5 and degree=2. Require integer odd window,
   degree smaller than window, derivative order <= degree, and enough samples.
   At a center, take its complete centered window in original-index-contiguous
   data; define `u=(lambda-lambda_center)/scale`, with scale equal to the largest
   absolute offset. Fit an increasing-power Vandermonde matrix by float64 least
   squares with a recorded rank tolerance. Output `d! * c[d] / scale**d`.
   A missing/invalid window or absent edge window yields an invalid output;
   rank failure has a reason. Units are signal, signal/nm or signal/nm². Keep
   valid-window counts and invalid reasons. Do not silently downgrade degree or
   enlarge a window. Canonical descending-index mapping uses absolute adjacent
   original-index differences of one, not only increasing index differences.
5. **Interval features:** resolve the requested endpoints to explicitly selected
   measured band centers, with no invented endpoint values. Require complete
   original-index-contiguous common support. Return trapezoid area and area/span,
   actual interval/span and source-unit·nm/source-unit labels. Reflectance-only
   endpoint continuum returns C, R/C, signed depth, area, and a sampled minimum
   with its original index. A nonpositive continuum or absent interior sample is
   invalid; no signed-value clipping, FWHM inference or fitted band-center claim.
   All results state `aggregation_order='summary_then_transform'` and summary type.
6. **Maps:** reference RMSE receives the pinned reference summary/ROI and fixed B;
   each output pixel is complete on B and gets an explicit validity mask.
   Normalized difference uses an explicit positive threshold on `abs(a+b)` in
   source units. Display its zero-centered signed quantity with no fixed [-1,1]
   clipping. Include role/channel names, equations, counts, units and reference
   support in output metadata.
7. **Annotations, exports and temporal traces:** annotation revision joins the
   source/ROI/method identity but never changes acquisition evidence. Export one
   completed result and its exact recipe; no recomputation from later controls.
   S9 selects an actual stored band/channel, retains source time/index and all
   durable-frame accounting, and records observed spatial/temporal meanings.

## Analytic counterexamples and acceptance list

These are explicit hand-derived oracles, not claims of executing the new code.
They exercise the previously disputed cases and must become numerical tests.

- **Changing spatial support:** pixels `[1, NaN]` and `[NaN, 9]` produce per-band
  means `[1,9]` but zero complete pixels. Common mode must be unavailable.
- **Nonlinear aggregation:** two pixels with numerator/denominator `[1,1]` and
  `[9,3]` have mean per-pixel ratio 2, whereas the ratio of ROI means is 2.5.
  A result labelled as one must not contain the other.
- **Quantiles:** `[1,2,3,100]` gives median 2.5, Q25 1.75, Q75 27.25 and raw
  MAD 1. No ribbon may be drawn as median plus/minus IQR.
- **Pair invariances:** `y=2x` has SAM zero and correlation one but nonzero RMSE;
  `y=x+c` has correlation one but generally nonzero SAM. Constant correlation
  and zero-norm angle are null with reasons while defined differences remain.
- **Polynomial on true irregular wavelengths:** at `[500,501,502,510,511]` nm,
  `y=((lambda-500)/10)^2` gives center y=0.04, first derivative 0.04/nm and
  second derivative 0.02/nm² at 502 nm under a degree-two window. Reverse storage
  and µm input must return the same physical result after canonical conversion.
- **Original-index gap:** selecting original bands `[0,1,3,4,5]` is not a
  five-band contiguous window and must not produce a center polynomial or a
  whole-interval trapezoid across missing band 2.
- **Asymmetric continuum:** at `[500,560,700]` nm with reflectance
  `[0.8,0.736,1.2]`, the center continuum is 0.92, depth is 0.2 and area is 20 nm.
  The arithmetic mean of shoulders would give the wrong center continuum.
- **Unbounded signed normalized difference:** a=-2 and b=1 gives 3, not 1.
  It is valid if the chosen denominator threshold permits magnitude one; do
  not clip it or mislabel the map as a physically specific vegetation index.
- **Chromatic repeatability:** a sequence with R increasing and G decreasing
  equally can have a constant channel average. S9's selected R/G traces must
  retain both changes, unique frame identities and recorded time/index.
- **Compatibility:** F-P1, empty/nested-unknown settings and wrong dark roles
  fail before output creation; legitimate blocked dark evidence need not share
  the illuminated sample's condition IDs. A fully documented synthetic example
  must pass with unchanged raw bytes and labelled synthetic provenance.

Beyond these exact cases, require invalid/ignored/saturated denominator checks,
empty/singleton/all-invalid support, scale/unit changes, rank/edge behavior,
native/CSV/vector-figure numeric identity, stale asynchronous result rejection,
annotation-source replacement detection, and immutable real RGB/Bayer hashes.
The local SG oracle checks uniform-grid interior values only; its edge behavior
does not override HyperLab's invalid-edge policy. External measured spectral
data validate software behavior under their supplied evidence, not HinaLea H3/H4.

## Final package votes

| Package | Final vote | Acceptance authority |
|---|---|---|
| S1 role-aware applicability | ACCEPT | F-P1 regression, required-evidence matrix and unchanged inputs |
| S2 robust ROI/common support | ACCEPT | Hand quantiles, original quality versus used counts, exact shared plots |
| S3 pairwise metrics | ACCEPT | Fixed B, defined/null metric cells, domain labels and invariances |
| S4 local polynomial/interval/continuum | ACCEPT | True-coordinate analytic oracles, rank/edge/gap tests and reflectance gate |
| S5 reference/normalized-difference maps | ACCEPT | Independent formulas, completeness and denominator masks, correct scale semantics |
| S6 versioned analyst context | ACCEPT | Source binding, typed nullable fields, revision invalidation and evidence separation |
| S7 publication bundles | ACCEPT | Pinned numbers/recipe/source and output hashes, labels and complete accounting |
| S8 concise workflow | ACCEPT | Actual completed method matches chart/export; contextual controls and accessible Stop |
| S9 stored-channel repeatability | ACCEPT | All durable frames, selected real feature, time/identity/mismatch/partial accounting |

All nine votes are acceptance of the frozen implementation contract. Physical
thermal-paint calibration, trained defect validity, camera-certified noise and
recovered spectroscopy remain conditional as stated in Version 1. This round
does not change their NOT_TESTED status.
