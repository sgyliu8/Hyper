# Reviewer 2, round 1: ROI statistics and spectral mathematics

Reviewed 2026-09-06 (Europe/London). Independent AI engineering review; not a
human peer review or an exhaustive systematic literature review. Baseline:
`7ab867b2946035a162254f1d63cdc4d156b52e47`. Read AGENTS, current handoff,
architecture, Phase 3 review, the new review protocol, `analysis/core.py`,
`analysis/quality.py`, `analysis/capabilities.py`, `plots.py`, and analysis and
capability tests. No production edits, acquisition, native UI interaction,
downloads of datasets, or third-party code execution were performed.

## Decision

Build a reliable descriptive and feature-extraction chain before adding a
classifier. Thermal paint comparison and material/defect comparison are both
in scope. Real RGB/Bayer data can already exercise robust intensity summaries,
spatial distributions and repeatability. Wavelength-dependent functions need
an evidenced spectral cube; physical absorption features need a defensible
reflectance product. Neither a smooth spectrum nor a score map establishes a
temperature, coating thickness, material identity, or defect probability.

The current implementation is a strong starting point: immutable raw arrays,
per-band quality counts, population spatial SD, common selected features for
PCA/SAM, float precision checks, strict reference matching, and shared plot
numbers. It lacks robust summaries, explicit common spatial support for ROI
spectra, a compact pairwise comparison table, and wavelength-aware feature
contracts. These are higher priorities than adding many unrelated algorithms.

## Source audit and transferable examples

All links below were opened or returned with source text on 2026-09-06. Software
examples establish inspectable behavior, not empirical validation of HyperLab.

| Source and evidence class | Useful example and boundary |
|---|---|
| [NumPy quantile](https://numpy.org/doc/stable/reference/generated/numpy.quantile.html), primary software documentation | Explicit estimator choice, interpolation convention and examples. Record `method=linear`; never mutate raw input through `overwrite_input`. |
| [SciPy MAD](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.median_abs_deviation.html), primary software documentation | Robust dispersion and a worked outlier example; distinguish raw MAD from Gaussian-scaled MAD. |
| [SciPy Savitzky-Golay](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html), primary software documentation | Polynomial order, window, derivative, one scalar sample spacing, and boundary mode are part of the algorithm. |
| [NumPy trapezoid](https://numpy.org/doc/stable/reference/generated/numpy.trapezoid.html), primary software documentation | Integration follows supplied coordinates without sorting; reversed wavelength order changes sign. |
| [Clark and Roush, 1984](https://pubs.usgs.gov/publication/70013396), peer-reviewed original article; [USGS band-depth example](https://pubs.usgs.gov/of/2003/ofr-03-128/ofr-03-128.html), original application report | Divide reflectance by a continuum to isolate a feature. The second source provides the depth formula and an illustrated absorption example. Depth is affected by physical mixture and scattering conditions. |
| [hylite author repository](https://github.com/hifexplo/hylite), original software | Minimum-wavelength maps, ratios, reference libraries and associated preprocessing form a coherent workflow. Useful design reference; not an instruction to install its full dependency stack. |
| [Spectral Python algorithms](https://www.spectralpython.net/algorithms.html), primary software documentation | PCA score/covariance examples and reference-spectrum SAM; training-set maps in examples are not independent test accuracy. |
| [SciPy Pearson correlation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.pearsonr.html), primary software documentation | Defined coefficient and constant-input behavior. Spectral wavelengths are correlated features; a coefficient does not justify its default independent-sample significance test here. |
| [EMVA 1288 General 4.0](https://www.emva.org/wp-content/uploads/EMVA1288General_4.0Release.pdf), original standard; [official downloads](https://www.emva.org/standards-technology/emva-1288/emva-standard-1288-downloads-2/) | Temporal noise and spatial nonuniformity are different quantities. A scene ROI's texture SD is not an EMVA camera-noise measurement. |
| [Disjoint sampling, arXiv 2404.14944](https://arxiv.org/html/2404.14944v1), original preprint/full text; [author code](https://github.com/mahmad00/Disjoint-Sampling-for-Hyperspectral-Image-Classification) | A useful warning about evaluation leakage, but Algorithms 1–2 do not establish non-overlap of spatial patch footprints; see objection below. |
| [Objective evaluation, arXiv 2302.05297](https://arxiv.org/abs/2302.05297), original preprint abstract | Proposes non-overlapping windows. Method lead for later evaluation work; its network accuracy was not reproduced in this review. |
| [Grouped cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data), primary software documentation | Keeps dependent groups out of both training and validation. For this use case the independent unit is a specimen/batch/session, not a pixel. |
| [ICVL original Hugging Face card](https://huggingface.co/datasets/ICVL-BGU/ICVL_HS_2016/blob/main/README.md), dataset card | Describes natural-scene radiance cubes with a stored `bands` vector; the reduced product has 31 bands, 400–700 nm. An external real cube can test import and numerics, not HinaLea calibration or paint ground truth. |
| [Living Optics original Hugging Face card](https://huggingface.co/datasets/LivingOptics/hyperpspectral-forensics/blob/main/README.md), dataset card/vendor code example | Instance masks, sparse spectra, references, individual curves and range summaries illustrate ROI exploration. It has custom licensing and no prescribed train/validation split. Sparse sample counts are not dense pixel counts. |
| [Vehicle paint signatures, arXiv 2004.08228](https://arxiv.org/abs/2004.08228), original preprint; [linked author repository](https://github.com/mulhollanz/Hyperspectral_Vehicle_Paint_Signatures_Dataset) | Directly relevant calibrated VNIR paint concept. The linked repository currently has only a one-commit README stating the dataset is forthcoming; it is not an available validation dataset. |

The displayed-date field on the USGS repository is not the 1984 article's
publication year; use the article citation. Hugging Face hosting is not a
calibration certificate, and arXiv presence alone is not peer review.

## Eight priorities and numerical acceptance contracts

### 1. Robust ROI summary, alongside the existing mean and spatial SD

For each band, apply the existing explicit quality policy to obtain values
`v[0:n]`. Preserve mean and population SD. Add median, Q25, Q75, min, max and
raw MAD. With sorted values `z`, `h=(n-1)p`, `j=floor(h)`, `g=h-j`, define
`Qp=(1-g)z[j]+g z[min(j+1,n-1)]`. Define
`MAD=median(abs(v-median(v)))`. An optional Gaussian-consistent scale must be
separately named `MAD / 0.6744897501960817`, never silently called SD. [Quantile](https://numpy.org/doc/stable/reference/generated/numpy.quantile.html), [MAD](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.median_abs_deviation.html).

No valid samples gives NaN statistics and zero count; one valid sample gives
zero spatial SD/MAD, not evidence of measurement precision. Keep every existing
quality denominator. The first UI addition should be one summary selector:
`Mean ± spatial SD` or `Median + IQR`, with a compact full-statistics table/export.
IQR is the Q25–Q75 interval, not a symmetric `median ± IQR` ribbon. Preserve the
approved palette, line styles and white background.

Tests: `[1,2,3,100]` gives median 2.5, Q25 1.75, Q75 27.25, raw MAD 1;
masked/saturated/ignored values follow the same policy as existing means;
constant/empty/singleton cases; high-range integer precision; unchanged raw hash;
native/export figures use the identical stored quantiles. Compute bandwise to
keep working memory independent of the number of bands.

### 2. Make spatial support explicit before interpreting an ROI spectrum

Existing per-band validity means different points of a curve may average
different pixels. Keep this valid descriptive option and label it `Per-band
valid pixels`. For spectral features, offer `Common valid pixels`: for selected
features `B`, require `M(p)=AND(b in B) valid(p,b)` within each ROI, then compute
all selected summaries over this same spatial support. Excluded global bad bands
must not participate in that AND. Record both selected-feature indices and
support mode, ROI area, common count, per-band counts and rejection counts.

This is a proposed HyperLab contract arising from the local implementation,
not a claim that all existing studies use common support. It trades coverage
for comparability, so changing the choice must invalidate prior analysis.
Do not impute missing values to make curves look complete. Empty common support
is an explicit unavailable result; do not fall back silently to per-band means.

Tests: a two-pixel cube with complementary missing bands must not create a
complete common-support spectrum; a globally excluded missing band must not
invalidate otherwise complete vectors; changing selection changes denominators
and analysis identity; quality accounting and visualization agree.

### 3. Pairwise ROI similarity and amplitude comparison

For ROI summaries `x,y` on exactly the same selected finite features, add a
small pair table with `RMSE=sqrt(mean((x-y)^2))` in source units, signed mean
difference in source units, existing angle
`theta=acos(clip(dot(x,y)/(norm(x) norm(y)),-1,1))`, and Pearson
`r=dot(x-xmean,y-ymean)/(norm(x-xmean) norm(y-ymean))`.
Angle is invariant to positive multiplicative scale; correlation is additionally
invariant to additive offsets; RMSE preserves amplitude changes. [SAM examples](https://www.spectralpython.net/algorithms.html#spectral-angles), [correlation definition](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.pearsonr.html).

Require at least two features for angle and preferably three for displayed
spectral correlation; two-point correlation is trivially ±1. Reject zero-norm
angle vectors and constant/near-constant correlation vectors. Record the norm
threshold and why any cell is unavailable. Do not export Pearson p-values as
if wavelengths were independent replicates. Keep spectral/state capabilities;
RGB may have channel RMSE/difference, but no relabelled spectral SAM. Unit and
axis matching are mandatory for a future external reference library.

Tests: `y=2x` yields zero angle/correlation one but nonzero RMSE; `y=x+c`
has correlation one but generally nonzero angle; zero and constant vectors;
feature exclusions; unit mismatch; missing values; matrix symmetry and diagonal.

### 4. Explicit spectral preprocessing and derivative branch

Preserve raw amplitude as the default. Existing L2 normalization remains a
separate display/analysis branch. A wavelength derivative needs finite, strictly
monotone, unique, documented wavelengths with known length units. Normalize
descending axes consistently for calculations and retain the original mapping.
Never differentiate RGB indices or raw scan-state indices as wavelength.

The simplest first derivative is a wavelength-aware finite difference on each
contiguous valid segment. For SG, require an odd window `w`, polynomial order
`p<w`, derivative order `d<=p`, segment length at least `w`, and approximately
uniform spacing under a documented tolerance. Pass actual wavelength spacing
as `delta`, record the boundary mode, and retain NaN gaps. Output units are
signal units divided by wavelength units to power `d`. SciPy's scalar-spacing
SG interface is not a general irregular-coordinate fit. [SG contract](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html).

Do not let automatic smoothing determine band centers without an explicit
method choice. A future local-polynomial least-squares fit on true wavelengths
can support irregular sampling; that is a different method requiring its own
conditioning tests. Defer it if the simpler implementation is adequate.

Tests: constant and linear functions, quadratic derivative, reversed-axis
equivalence, nm/µm unit conversion, duplicate/nonmonotone wavelengths, masked
gaps, insufficient segments and polynomial/window rejection. Transformation of
ROI mean and mean of transformed pixels must be named separately for nonlinear
methods; a default smoothing operation must never mutate the stored cube.

### 5. Wavelength integral and continuum-relative band features

Implement a selected wavelength interval with actual bracketing bands shown.
The trapezoid integral is `sum((y[i]+y[i+1])/2 * (lambda[i+1]-lambda[i]))`;
its units are signal units times wavelength units. That is not a radiometric
band power unless the signal is documented as a spectral density. Do not
silently bridge an excluded band. The initial conservative contract can require
complete contiguous support across the selected interval. [Trapezoid](https://numpy.org/doc/stable/reference/generated/numpy.trapezoid.html).

For an explicit left/right continuum on a reflectance cube, define
`C(lambda)=R_L+(R_R-R_L)(lambda-lambda_L)/(lambda_R-lambda_L)`,
`q=R/C`, `depth=1-q`, and feature area `integral(depth d lambda)`.
Require positive finite continuum, valid shoulders and an interior sample.
Report the sampled minimum's wavelength, selected interval and exact method.
Do not clip negative depths or claim sub-band localization from an argmin.
Show the original reflectance with its continuum plus a separate depth curve.
[Physical continuum definition](https://pubs.usgs.gov/publication/70013396),
[USGS feature-depth example](https://pubs.usgs.gov/of/2003/ofr-03-128/ofr-03-128.html).

This first release should gate physical band-depth interpretation to reflectance;
raw DN carries illumination and sensor response. Do not infer coating thickness
or thermal-paint exposure from feature area alone. FWHM requires both resolved
half-depth crossings and a stated interpolation convention; defer an automatic
FWHM/peak-fitting suite until those cases have a stable API.

Tests: flat spectrum gives zero depth/area; asymmetric shoulder wavelengths use
wavelength interpolation (not the arithmetic mean); `lambda=[500,560,700]`,
`R=[0.8,0.736,1.2]` gives center continuum 0.92, center depth 0.2 and area
20 nm; zero continuum invalid; gaps and unresolved boundary minima; units;
`feature(mean(pixels))` is not mislabeled `mean(feature(pixels))`.

### 6. Finish PCA interpretation, not a second PCA engine

Retain the current common-feature mask, seed, sampled fit and chunked transform.
Expose existing loadings and explained variance alongside a selected score
map; annotate mean-centering versus standardization and fit sample count.
The current SVD contract is `Xc=U S Vt`, scores `Xc V`, component variance
`S^2/(n-1)`. Signs can flip; compare projectors or sign-aligned components in
tests. Adjacent or repeated eigenvalues mean individual component directions
need not be stable. [PCA reference example](https://www.spectralpython.net/algorithms.html#principal-components).

PCA highlighting a paint patch means variance differs, not that the patch is a
defect. No automatic cluster-to-material label. For later anomaly detection,
RX/Mahalanobis requires a defensible background ROI, covariance rank/conditioning
and independently chosen thresholds. A matrix inverse on K features with too
few independent observations is not a safe default. Defer automatic probabilities.

Tests: reconstruction for full-rank fixtures, sign-invariant component checks,
constant/rank-deficient data, standardization units, finite/masked fit counts,
and selected map/loadings/export provenance identity.

### 7. Temporal repeatability distinct from spatial variation

Preserve `TemporalStatistics` and the display-sampling disclaimer. Add an offline
sequence ROI trace summarizing all durable recorded frames, with valid frame
counts and setting consistency. Keep population temporal dispersion distinct
from a sample SD estimate (`n-1` denominator, undefined below two replicates).
If a descriptive signal/temporal-SD ratio is shown, require positive meaningful
signal, nonzero SD, matching settings and stationary scene evidence; call it
an estimate and state whether dark signal was removed. A perfectly constant
quantized sequence is not evidence of infinite instrumental SNR.

The EMVA standard separates temporal noise from spatial nonuniformity; normal
scene texture does not satisfy its camera-characterization conditions.
[EMVA source](https://www.emva.org/wp-content/uploads/EMVA1288General_4.0Release.pdf).
Until a controlled flat/dark acquisition exists, prefer reporting temporal SD
and drift to an impressive but ill-defined SNR number.

Tests: known time ramps versus spatial textures; missing and saturated frames;
single frame; duplicate frame identity; settings change; completed and failed
sequence prefixes; accounting includes excluded frames and never raw capacity.

### 8. Publication data model for paint and defect studies

Store analyst-entered specimen, material/coating family, coating batch, ROI role
(reference/test/background), session, geometry and illumination notes. Unknowns
stay unknown. Thermal-paint interpretation additionally needs independently
measured heat history, dwell time, coating application and a calibration study;
image color is not temperature. Material/defect studies need independently
assigned labels, negatives/confusers, and specimen/session-separated evaluation.

Never treat the thousands of pixels in one ROI as thousands of independent
specimens. Grouped validation must satisfy pairwise group intersections empty,
with all preprocessing fit inside training folds. Spatial patch models also
need explicit receptive-field exclusion/buffers. [Grouped evaluation](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data).

Publication export should keep CSV values, masks, selected/excluded features,
units, processing parameters, support/counts, source identity/hash and vector
figures together. Recommended plate: scene/ROIs, mean±spatial SD or median/IQR,
one purposeful transformed comparison, and a feature map with invalid-mask key.
Add independent specimen distributions only when those specimens exist. Every
caption must identify whether its interval is spatial, temporal or inferential.

Tests: saved/reopened analyst fields remain separate from acquisition facts;
duplicate specimen/session labels cannot leak across generated folds; group
overlap errors; numeric/export reproducibility. Training, uncertainty intervals
and temperature/defect accuracy stay conditional rather than synthetic claims.

## Strongest objections for cross-review

1. **Robustness cannot erase evidence.** A saturated reflection may be unwanted
   for quantitative analysis but is still a real part of the scene. Preserve
   counts and raw values while offering explicit exclusion and robust summaries.
2. **More algorithms can obscure the physical bottleneck.** Presenting SG,
   continuum removal or a neural spectral reconstruction beside real RGB must
   not suggest H2–H4 were recovered. Keep the current capability gate and explain
   one concise unavailable reason in a contextual panel.
3. **Common feature indices are not common spatial support.** An ROI mean curve
   assembled from changing valid pixels needs its support label before physical
   feature comparison. This is a substantive gap in the current local pipeline.
4. **A searched paper is not automatically a sound implementation template.**
   In [arXiv 2404.14944 full text, Algorithms 1–2](https://arxiv.org/html/2404.14944v1),
   overlapping patches are made before random class-index splits. Distinct
   center indices do not prove disjoint patch footprints. My engineering
   inference is that this procedure alone cannot demonstrate unseen-scene or
   unseen-specimen generalization; do not transfer that abstract's claim.
5. **Examples may contain inadmissible shortcuts.** The [Living Optics card](https://huggingface.co/datasets/LivingOptics/hyperpspectral-forensics/blob/main/README.md)
   illustrates wavelength construction from min/max with `linspace`. HyperLab
   must use the actual recorded vector, not this plotting shortcut. Its range
   shading is also a min/max envelope, not a confidence interval.
6. **Dataset availability must be verified.** The paint paper's linked GitHub
   repository currently provides no spectra. ICVL is natural-scene radiance,
   not ground-truthed thermal paint. Neither validates our camera's spectral
   response. Record these limits before choosing validation examples.

## Proposed acceptance sequence

First implement priorities 1–3 and their shared plot/export contracts. Implement
the minimal documented subset of priorities 4–5 on external evidenced spectra
and explicitly synthetic analytic fixtures, with rejected RGB/Bayer regressions.
Use existing PCA/temporal components for priorities 6–7 and add only the missing
interpretation or export links. Add specimen/context fields and a durable study
template now; postpone trained models until independent labelled studies exist.
Do not rewrite the UI around a catalog of algorithms: one analysis mode, one
contextual option panel and one active numeric/plot result are enough.

Round 1 outcome: **CONDITIONAL ACCEPT** of the bounded feature chain above.
Ready for independent cross-review; no implementation or physical acceptance
is claimed by this report.
