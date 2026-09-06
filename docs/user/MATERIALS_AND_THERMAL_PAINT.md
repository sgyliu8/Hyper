# Materials, coatings and thermal-paint analysis

Research and engineering guide, 2026-09-06. The owner uses HyperLab for both
thermal paint and paint/material defect investigation. Implementation status is
tracked in the [review and delivery record](../dev/SCIENCE_ROADMAP_REVIEW.md).
The approved white figures and orange/blue/green ROI palette remain the default.

## Using the implemented 0.4.0 workflow

Open an actual saved frame/cube or normally acquire a frame. In **Analysis**, name
the ROIs, select mean/SD or median/quartiles, choose pixel support and a method,
then **Run analysis**. **Results** shows the completed numerical tables;
**Export** contains publication figures, ROI tables, derived arrays and display
images. **Plot and view options** holds L2 shape, spatial spread and PCA chart
selection. Export settings keep the result and source that were selected when
the window opened; later controls or live frames cannot silently change them.

For paint/material contrast, start with **ROI summary**, **ROI pair comparison**
and **Reference ROI RMSE map**. The first ROI supplies the map reference. RGB
results name the stored channels; correlation is a channel-shape descriptor and
spectral angle remains unavailable. **Normalized difference map** uses selected
stored features and an explicit denominator threshold. Neither map classifies a
defect or assigns a temperature. Keep amplitude and recorded conditions visible.

For a documented spectral cube, choose smoothing, a derivative or an interval.
The first/last controls are inclusive **original stored feature indices**.
Spectral feature operations use common pixels and canonical increasing nm,
retaining the original index/unit mapping. Five-point quadratic windows are the
default. Missing bands/windows and unsupported edges remain unavailable.
**Endpoint continuum / band depth** additionally requires reflectance data.
Results distinguishes sampled minima from fitted centers and reports signed area.

Use **Specimen / thermal context** to save a new analyst revision with nullable
material, coating batch, substrate, replicate, temperature meaning/reference,
dwell, illumination and geometry. Loading a revision verifies its source hash.
Freeze a live display or open a saved frame before entering its context. These
annotations cannot satisfy a missing calibration condition. **Calibration →
Reflectance correction** inspects separately recorded sample, white and two dark
sources; the Check report identifies each mismatch/unknown before correction.

For repeatability, open a saved sequence and select **Recorded ROI trace** and
the stored channel. All durable frames use their recorded clock or explicit
index; partial recordings and loss counts remain in the recipe. The display-only
ROI time trend is explicitly a visited/displayed subset, with separate segments
when its definition changes.

The CLI uses the same calculation functions. Each output path must be new:

```powershell
python -m hyperlab analyze cube.npy pairs --reference-roi 0 0 20 20 --roi 30 30 50 50 --summary median --support common --output pairs.json
python -m hyperlab analyze cube.npy derivative1 --roi 0 0 20 20 --bands 2 3 4 5 6 --support common --window 5 --degree 2 --output derivative.json
python -m hyperlab analyze frame.npy reference-rmse --reference-roi 0 0 20 20 --summary median --support common --output distance.npy
```

These geometry/feature indices are examples; select bounds present in the actual
source. No spectral operation becomes available by renaming RGB axes.

## Start with the measurement, then choose the statistic

An image can show a difference without identifying its physical cause. Glare,
surface orientation, illumination, focus, clipping, coating composition and
thermal treatment can all change an observed signal. Retain the raw amplitude,
quality mask and acquisition conditions beside every normalized curve or map.
Use independent material/temperature references before making a causal or
predictive claim. The HinaLea 4250 normalization study specifically shows why
normalization must be evaluated against the target and nuisance variation rather
than selected solely because curves overlap. [Mazdeyasna et al., 2025](https://www.mdpi.com/2079-6374/15/1/20).

The current local instrument has demonstrated Bayer/RGB imaging. A verified FP
scan protocol, matching response assets and independent spectral/reflectance
validation remain outstanding. RGB channels, sensor CFA phases, time frames and
optical scan states have different meanings. A supplied external cube with a
documented wavelength axis can exercise spectral analysis independently of the
local camera. Declared external calibration remains declared evidence.

For a calibrated linear acquisition, a useful forward model is

```text
measurement[p,state] - dark[p,state]
    = exposure[state] * sum_j(response[p,state,j] * radiance[p,j]) + error
```

The response includes spectral integration and relevant instrument effects.
Sampling interval is not spectral resolution. Multi-order FP transmission,
field-angle dependence, radiometric linearity and state/frame synchronization
cannot be recovered by assigning evenly spaced wavelengths to RGB values.
Monochromatic characterization is an explicit measurement step in the
[IRCA paper and author implementation](https://github.com/danaroth83/irca).

## ROI questions, numbers and figures

| Question | Summary/calculation | Figure and interpretation |
|---|---|---|
| How bright and variable is each region? | Mean, population spatial SD, min/max and valid counts | Mean with spatial SD ribbon; intensity distribution for one sensor plane. Spatial dispersion is not a confidence interval. |
| Does a small bright/glare patch dominate the mean? | Median, Q25, Q75, IQR and unscaled MAD | Median with asymmetric Q25–Q75 ribbon, compared with mean/SD and quality fractions. Neither automatically removes glare from raw evidence. |
| Do curves average the same pixels at every band? | Per-band support versus common valid pixels over selected bands | Used/quality-valid counts and support exclusions. Empty common support stays unavailable. |
| Is a difference amplitude, offset or spectral shape? | Target-minus-reference bias, RMSE, descriptive correlation, admissible SAM | Pair table and residual curves with original amplitudes. Different metrics have different invariances. |
| Where does a chosen region differ from the rest? | Reference-ROI RMSE map, difference, ratio, normalized difference | Sequential scale for nonnegative distance; diverging scale for signed contrast. Grey means invalid. A score is not a defect probability. |
| Which wavelength intervals change? | Actual-wavelength integral and interval mean | Original curve and selected measured interval, with units and exact participating indices. A DN·nm integral is not radiant power. |
| Where does the slope or curvature change? | Local polynomial smooth/first/second derivative | Separate transformation branch, stated window/degree/edge policy; original amplitude stays available. Unsupported edges remain gaps. |
| Is there a resolved reflectance depression? | Explicit shoulder continuum, depth, area and sampled minimum | Original reflectance/continuum and depth curve. No automatic chemical identity or sub-band resolution claim. |
| What dominates scene variance? | Existing centered PCA, scores, loadings, explained variance and fit population | Score map plus loading/variance plots. PC signs are arbitrary; variance is not accuracy or ground truth. |
| Is acquisition repeatable? | All persisted-frame ROI traces for a selected actual channel; temporal SD/drift with settings checks | Actual recorded clock or explicit frame index, complete frame denominator and partial/loss status. Temporal changes include scene/illumination changes. |

Quartiles use the explicit linear quantile convention. Raw MAD is
`median(abs(values - median(values)))`; it is not Gaussian-scaled SD. For example,
`[1,2,3,100]` has median 2.5, Q25 1.75, Q75 27.25 and raw MAD 1. It has a large
spatial range despite a small central dispersion. [NumPy quantile](https://numpy.org/doc/stable/reference/generated/numpy.quantile.html),
[SciPy MAD](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.median_abs_deviation.html).

The original quality counts and the actual samples used after common support are
different denominators. A pixel may be valid in red but excluded from a common
RGB statistic because green is saturated. Report that as a support exclusion,
not as a newly invented red-sensor fault. Do not fill a missing spectral region
to create a visually continuous curve.

## Comparison and feature definitions

For target and reference summary vectors on one recorded common feature set B:

```text
bias = mean(target[B] - reference[B])
RMSE = sqrt(mean((target[B] - reference[B])**2))
SAM = acos(clip(dot(target,reference)/(norm(target)*norm(reference)), -1, 1))
correlation = dot(centered_target,centered_reference)
              / (norm(centered_target)*norm(centered_reference))
normalized_difference(a,b) = (a-b)/(a+b)
```

Bias/RMSE preserve source units and use equal feature weights. SAM is invariant
to positive scaling; correlation additionally removes constant offsets. These
invariances can also remove a physically useful difference. Zero-vector SAM and
constant-vector correlation are undefined. Correlation requires at least three
features here and has no p-value. RGB permits descriptive channel correlation,
not a spectral-angle result. [Spectral Python algorithms](https://www.spectralpython.net/algorithms.html),
[Pearson definition](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.pearsonr.html).

The normalized-difference denominator must exceed the recorded positive
threshold in absolute magnitude. Signed inputs can produce values outside
[-1,1]; they are retained, not clipped into a misleading physical range.

Local polynomial processing fits centered/scaled actual wavelength offsets in
one complete odd window. The d-th derivative is `d! * coefficient[d]/scale**d`.
Units are signal/nm^d. This handles documented irregular coordinates without
inventing interpolated measurements. Complete centered windows are required;
unsupported edges and invalid windows stay unavailable. On a uniform grid its
interior can be checked against Savitzky–Golay coefficients, whose usual
scalar-delta API assumes one spacing. [SciPy Savitzky–Golay contract](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html).

For increasing wavelengths and a complete selected interval:

```text
area = sum(0.5*(signal[i]+signal[i+1])*(lambda[i+1]-lambda[i]))
interval_mean = area/(lambda_right-lambda_left)
continuum(lambda) = R_left + (R_right-R_left)
                   * (lambda-lambda_left)/(lambda_right-lambda_left)
depth(lambda) = 1 - R(lambda)/continuum(lambda)
depth_area = integral(depth(lambda) d lambda)
```

The continuum requires positive supported shoulders and reflectance data. For
`lambda=[500,560,700] nm` and `R=[0.8,0.736,1.2]`, the center continuum is 0.92,
center depth is 0.2 and trapezoid depth area is 20 nm. Negative depth is retained.
The selected sampled minimum is not a fitted center or FWHM. A feature of the
ROI mean is not the mean of nonlinear pixel features; transformed curves do not
inherit the raw spatial SD/IQR as an uncertainty band. [Clark and Roush](https://pubs.usgs.gov/publication/70013396),
[USGS band-depth example](https://pubs.usgs.gov/of/2003/ofr-03-128/ofr-03-128.html).

## Reference correction and uncertainty

For compatible, linear, reconstructed sample/white/two-dark observations:
`R = r_reference * (sample-dark_sample)/(white-dark_white)`. The software checks
the measurement domain, response applicability, optical conditions and each
source's role. Darks need evidence of blocked light; they must not pretend to
have the illuminated sample's geometry. Compatibility of recorded declarations
is not independent metrological certification. Keep negative and greater-than-one
reflectance factors for inspection with masks and conditions. [NIST SP 250-48](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication250-48.pdf).

Spatial SD, temporal SD, specimen uncertainty and reference uncertainty are
separate. With `N=sample-dark_sample`, `D=white-dark_white` and input order
`[sample,dark_sample,white,dark_white,r_reference]`, the first-order Jacobian is
`J=[r/D,-r/D,-r*N/D**2,r*N/D**2,N/D]`; a standard uncertainty would be
`sqrt(J Cov(inputs) J.T)`. Shared dark/reference observations produce covariance.
The present scene data do not supply that covariance or a justified sensor-noise
model, so no automatic uncertainty/95% ribbon is produced. [JCGM measurement guides](https://www.bipm.org/en/web/guest/publications/guides),
[EMVA 1288](https://www.emva.org/standards-technology/emva-1288/emva-standard-1288-downloads-2/).

## Two application workflows

For thermal paint, assign independently prepared coupons their coating/batch,
substrate, preparation and thermal exposure record. Keep oven setpoint, owner
label and independently measured temperature distinct. Record dwell, atmosphere,
cooling and time since treatment where known. Acquire repeat observations under
documented lighting/geometry. Compare robust amplitude, shape and interval
features first. A future inverse model must handle ambiguous colour/spectral
trajectories and out-of-range samples, then be evaluated on unseen specimens and
sessions. A single spectrum cannot establish which thermal history occurred.
[Griffin et al., ICPR 1996](https://cmp.felk.cvut.cz/~matas/papers/griffin-icpr96.pdf),
[Ge et al., Measurement 2022](https://doi.org/10.1016/j.measurement.2022.111741).

For material/defect inspection, define a reference region and independent normal/
defect labels. Include negative controls for glare, orientation, texture and
illumination change. Use ROI summaries, residuals and descriptive maps to inspect
candidate differences. A later supervised model needs specimen/session grouping
before fitting normalization, PCA, feature selection or thresholds. For spatial
networks, also keep patch footprints separate. Report unscorable samples, false
positives and full specimen denominators. [Liang et al.](https://arxiv.org/abs/1605.05829),
[training leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html).

## What open examples teach, and what they do not validate

| Example | Useful transferable pattern | Boundary |
|---|---|---|
| [hylite](https://github.com/hifexplo/hylite) and [HyTools](https://github.com/EnSpec/hytools) | Explicit spectral features, libraries, masks, correction and ENVI exchange | Geology/remote-sensing corrections are not automatically appropriate for laboratory paint or this instrument. |
| [Spectral Python](https://www.spectralpython.net/algorithms.html) | Inspectable PCA/SAM/resampling definitions and numerical examples | Library defaults do not supply instrument calibration or independent defect labels. |
| [Cuvis.Ai](https://github.com/cubert-hyperspectral/cuvis-ai) and [lentils example](https://huggingface.co/datasets/cubert-gmbh/XMR_Demo_Industrial_Foreign_Object_Detection_Lentils) | Recorded processing steps, white/dark references and separation of score, threshold and truth | A vendor's food demonstration is not a paint benchmark; one sequence is not unseen-specimen validation. |
| [ICVL original HF dataset](https://huggingface.co/datasets/ICVL-BGU/ICVL_HS_2016) | Measured natural scenes with actual wavelength vectors for import/numerical exercises | Natural-scene radiance is not reflectance or HinaLea data; declared license restricts redistribution. |
| [Living Optics forensics example](https://huggingface.co/datasets/LivingOptics/hyperpspectral-forensics) | Instance masks, sparse spectra, reference spectra and curve distributions | Sparse samples need their locations. Its endpoint-linspace plotting shortcut is not accepted wavelength evidence. |
| [Vehicle paint signatures](https://arxiv.org/abs/2004.08228) | A directly relevant calibrated paint-method lead | The linked author repository still advertises forthcoming data; it is not a downloaded validation dataset. |
| [HAD100](https://arxiv.org/abs/2303.18001) | Multi-scene anomaly evaluation and background/target separation | Remote-sensing anomaly scores do not establish coating defects or calibrated probabilities. |
| [SpecAware, revised 2026](https://arxiv.org/html/2510.27219v2) and [HyperFM, 2026](https://arxiv.org/abs/2604.21127) | Sensor-aware or grouped spectral representations illustrate current foundation-model research | AVIRIS/PACE pretraining and benchmark gains do not recover missing FP calibration or prove generalization to these paint batches. No weights or performance claims are imported. |

The reviewers rejected two tempting shortcuts: treating an unavailable repository
as a reproduced example, and accepting a paper's phrase “disjoint sampling”
without checking whether neighboring patches actually overlap. The complete
source tables, access limitations and nine review-round records are linked from
the [review record](../dev/SCIENCE_ROADMAP_REVIEW.md). This is a broad, bounded
engineering search, not a claim of exhaustive literature coverage.

## Publication package checklist

Export the exact completed analysis: source hash and origin, ROI coordinates and
names, selected features/wavelengths, units, quality and used-count denominators,
support mode, summary/transform parameters, fit population if applicable, specimen
annotation revision, numerical CSV/NPY and editable SVG/PDF plus PNG. Captions
state what each ribbon means. Keep real specimen data local unless deliberately
shared. Preserve failed/partial acquisitions. Report software validation,
physical calibration and application prediction as separate outcomes.
