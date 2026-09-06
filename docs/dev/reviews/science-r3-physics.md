# Round 3 — physical measurement convergence vote

Reviewer: AI reviewer 1. Date: 2026-09-06. Read all three second-round reports
and all ten version-one decisions in `SCIENCE_CANDIDATE_PLAN.md`. This record
resolves my previous objections and freezes implementation acceptance conditions.
It does not certify implemented code or newly validate physical spectroscopy.
No production code, camera, native UI or source data were changed in this round.

**Final vote: ACCEPT S1–S9 as the bounded implementation plan under version 1.**
There is no remaining mathematical objection requiring another design round.
The conditions below are implementation checks, not new feature requests.
Completion must report their actual test status separately from H2–H4.

## Explicit disposition of earlier debate

**Response to the statistics reviewer.** I accept the single centered/scaled
local-polynomial operator proposed in statistics R2-D and selected by version 1.
My round-two preference for uniform SG plus separate derivatives was a simplicity
choice, not a physical requirement. One least-squares operator is now the smaller
coherent implementation: it uses true coordinates on regular or irregular grids,
avoids a production SciPy dependency and gives smoothing and derivatives the same
edge/gap policy. It must be called Local polynomial; no fictitious equally spaced
grid or interpolated observation is introduced.

For a window centred on sample i, let `u_j=(lambda_j-lambda_i)/s`, with `s` a
positive recorded scale from the actual offsets. Fit
`sum_(k=0..p) a_k * u_j^k` by rank-revealing least squares, then return
`d! * a_d / s^d` for derivative order d. Require `0 <= d <= p < w`, odd w,
positive finite s, complete centred original-index windows and full rank p+1.
The default w=5, p=2 supports d=0,1,2. Incomplete edge windows and windows touching
bad/missing samples remain unavailable. An interval's irregular physical spacing
is legitimate; removing a bad original band and compressing the remaining values
is not. Finite numerical conditioning/rank failure must be reported rather than
converted to a smooth curve. This operator does not add spectral resolution.

I accept comparison-wide common feature indices, separate original quality versus
actual support counts, and no propagated SD/IQR on summary-then-transform curves.
The original amplitude/SD or median/IQR branch remains available. This resolves
the statistical support and nonlinear-aggregation concerns raised in both rounds.

**Response to the software reviewer.** I accept the compact shared result record,
one active method/result authority, deferred RX, and independent annotation module.
The version-one distinction between source measurement context and editable
analyst annotations closes the proposed back door around applicability. Identical
typed specimen-condition IDs do not make a calibration artifact or matched source
readback. An applicability MATCH means recorded evidence is compatible; it must
not change a declared/documented source into an experimentally verified source.

The software review's null/finite numeric rules and temperature-meaning tuple are
sufficient for S6. A model prediction belongs to a later derived product, not a
measurement entry field. Keeping the full statement in Details/export while
showing a short source/unit/status line resolves my concern about simplification
removing physical meaning. I accept S9 as the bounded reuse of existing temporal
machinery, correcting the previously omitted stored-channel selection.

**Physics requirements resolved.** Version one adopts the fixed role-aware S1
contract, recursive known settings, compatible response/thermal context and
source-evidence origin. Only sample/white require the same illuminated geometry
and light condition; darks require their blocked-light role/method and compatible
sensor/settings. Reusing the same appropriate dark is allowed. There is no
synthetic bypass, no guessed temperature condition, no external trust framework.
Uncertainty covariance/Jacobian propagation stays documented and deferred, as do
RX probabilities, sensor-response resampling and temperature/defect inference.

## Final S1–S9 decisions

| Item | Vote | Frozen physical/numerical acceptance |
|---|---|---|
| S1 reference applicability | ACCEPT | Reject MISMATCH and required UNKNOWN before output creation; preserve every reason and evidence class. Match common instrument/response/thermal/settings/axis, illuminated sample/white context, and separate blocked dark roles. Legacy fixture migration declares synthetic evidence explicitly. |
| S2 robust ROI/support | ACCEPT | Mean/SD default; linear quartiles and raw MAD; per-band/default versus selected-feature common support explicit. Original quality, support exclusions and actual used counts remain distinct. No confidence interval or sensor-noise label. |
| S3 ROI pairs | ACCEPT | One comparison-wide finite feature set; target minus reference bias; equal-feature RMSE; descriptive correlation only for at least three nonconstant features. RGB remains channel analysis with no SAM. Unsupported metric cells retain a null/reason, not dropped rows. |
| S4 spectral transformations | ACCEPT | The true-coordinate local polynomial above; exact original-band intervals; increasing nm calculation and original axis mapping; complete common-support interval; no gap filling, extrapolation or transformed-summary ribbon. Reflectance-only continuum retains relative/reference-calibrated evidence and signed values. |
| S5 reference maps | ACCEPT | Reference RMS amplitude distance in source units with sequential colour; normalized difference with zero-centred divergence, denominator threshold in source units and grey invalid values. No defect probability, automatic threshold or forced [-1,1] clipping for signed inputs. |
| S6 experiment annotations | ACCEPT | Separate immutable revisions bound to exact source identity; nullable specimen/session/batch/substrate/conditions; temperature value/unit/meaning/source and dwell seconds. No camera-sidecar write, calibration promotion or inferred heat history. |
| S7 publication bundle | ACCEPT | Export the exact completed numerical result and context revision, source/output hashes, masks/counts, original feature mapping, units, method/parameters and aggregation order. Spatial/temporal/unknown uncertainty wording is preserved. |
| S8 simple UI | ACCEPT | Approved figures retained; one authoritative completed PlotSpec, contextual parameters, one Run and Export entry; actual source/units visible. Restore/analysis remain offline. Stop stays accessible across tabs during acquisition. |
| S9 stored-channel temporal trace | ACCEPT | Select a stored channel/feature and its recorded name, use all durable frames with correct clock/index, preserve partial/loss/settings evidence. Replaying/redrawing does not create additional acquisitions. Label observed temporal variation; no calibrated SNR claim. |

## Exact implementation acceptance checklist

1. **Applicability regression:** the round-one incompatible calibration/light/
   geometry counterexample is rejected, as are `{}`, nested unknown/nonfinite
   settings, missing response/thermal context and an unblocked or wrong-role
   dark. A valid dark with a different light-condition ID passes. Fully specified
   synthetic sample/white/darks reproduce the floating reference ratio, including
   valid negative and above-one outputs. Failure creates no completed product;
   raw arrays and metadata are unchanged.
2. **ROI oracle:** `[1,2,3,100]` produces median 2.5, Q25 1.75, Q75 27.25,
   raw MAD 1; mean/SD retain their existing definitions. Complementary missing
   pixels produce empty common support rather than a fabricated complete curve.
   Globally rejected unrelated bands do not remove common pixels. Policy-valid,
   support-excluded and used counts obey a documented tested identity.
3. **Comparison oracle:** identical, scaled and offset vectors distinguish
   amplitude error, angle and correlation as specified; constants/zero vectors
   give explicit unavailable cells where appropriate. Correlation of two features
   is unavailable. RGB wording and capability gates do not change. Signed bias
   reverses with target/reference; RMSE is symmetric.
4. **Derivative oracle:** on irregular wavelengths `[500,507,520,541,570]` nm,
   `y=(lambda-520)^2` yields centre value 0, first derivative 0 and second
   derivative 2 for the default five-point quadratic fit. A linear function
   yields its true slope; a constant yields zero derivatives. Compare uniform
   interior results with an independently invoked SciPy SG oracle. Reverse-axis
   and equivalent micrometre metadata produce the same canonical-nm values.
   Edges, a bad interior original band, invalid summary, unsupported window/order
   and rank-deficient windows are unavailable/rejected without interpolation.
5. **Integral/continuum oracle:** `[500,510,540]` nm with `[0.2,0.3,0.6]`
   gives area 16 nm and interval mean 0.4. `[500,560,700]` nm with reflectance
   `[0.8,0.736,1.2]` gives centre continuum 0.92, depth 0.2 and depth area
   20 nm. No axis reversal sign error, arithmetic-mean shoulder shortcut,
   unmarked bad-band bridge, clipped negative depth or invented endpoint.
6. **Map oracle:** independently calculate reference RMS distance and normalized
   difference on finite/masked/saturated fixtures. A signed-input case outside
   [-1,1] stays unclipped. A zero/weak denominator is grey/invalid rather than
   zero. Reference coordinates, summary/support, feature list and units match
   the exported numerical map and its visible title/colourbar.
7. **Source/context consistency:** changing annotations creates a new revision
   and invalidates the pending result; a same-path file with different bytes
   cannot inherit a previous annotation silently. The latest controls cannot
   rename or overwrite a previous completed plot. Deliberately stale callbacks,
   cancelled work and failed operations do not export mismatched captions/data.
8. **Temporal oracle:** a fixture with R increasing, G decreasing and a constant
   channel mean exposes the selected stored-channel change. The trace length is
   the durable prefix, not allocated recording capacity or GUI redraw count.
   Matching-settings failure/unknown state and partial recording losses remain
   reported. Bayer's one stored plane does not become a wavelength feature.
9. **Real-data and UI evidence:** exercise new descriptive statistics/maps and
   selected-channel temporal logic on immutable saved camera evidence. Use an
   independently sourced measured spectral example only after inspecting its
   actual axis, signal meaning and terms, and label it external evidence. Native
   UI and PNG/SVG/PDF/CSV must use the same completed arrays. No synthetic oracle
   or external example is reported as HinaLea wavelength/temperature validation.

## Remaining blockers versus implementation conditions

No physical calibration asset is required to implement and test the bounded
descriptive software or to analyse an appropriately documented external spectral
cube. These software functions are accepted for implementation, not yet PASS.

Local physical FP scanning still needs verified controller identity, protocol,
state acknowledgement, settling and frame association. Reconstruction still needs
matching response assets and independent spectral checks. Physical reflectance
needs applicable reconstructed measurements, references and independent validation.
Thermal-paint inversion and defect classification additionally need independently
labelled, applicable specimen histories and held-out specimen/session evaluation.
Those are scientific/hardware blockers, not reasons to pretend current RGB is
spectral or to withhold useful descriptive analysis.

Covariance uncertainty is a separate deferred capability: missing covariance is
unavailable, not zero. Raw paint differences, summary ribbons, local-polynomial
derivatives and continuous score maps do not resolve it. A powerful interface
should expose the strongest admitted operation for the supplied evidence while
keeping these remaining prerequisites candid and inspectable.

This reviewer approves freezing version one. The coordinator must still obtain
and retain the other two round-three records before claiming three-reviewer
convergence. Implementation assignment may proceed after that freeze.
