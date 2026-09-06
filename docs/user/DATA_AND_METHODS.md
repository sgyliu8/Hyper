# Data and method interpretation

| Level | Axes / meaning |
|---|---|
| raw_frame | HW sensor / HWC colour; not hyperspectral |
| raw_sequence | THW/THWC time, not wavelength |
| raw_scan | KHW storage or HWK logical; K is an acknowledged scan state |
| spectral_cube | HWK with sourced wavelength/reconstruction metadata |
| reflectance_cube | Compatible linear intensity/reference ratio with validity |
| derived_map | Component/score/difference/angle; no invented wavelength axis |

NPY requires explicit metadata or `inspect --axis-order`; NPZ and ENVI preserve
the supported fields and masks. Do not enable pickle loading. Wavelengths can be
null. A wavelength interval is not spectral resolution/FWHM. PFNC bits, ADC bits,
container bits and measurement precision are distinct. Floating reconstructed
spectra do not inherit an ADC saturation threshold as a physical assertion.

## Reference registry

Save and reopen an immutable file before registering it in Calibration. Record
kind, scene label and known lighting, distance, angle and conditions. The registry
stores a SHA-256 digest, metadata and applicability (device, calibration source,
wavelength units/order, scan states, geometry/CFA, temperature range and settings).
Unknown fields remain unknown. Select references and Check settings to compare
known settings; same shape is not proof of alignment or calibration validity.

Export selected references creates a **private reference ZIP**, separate from the
application package. Supported exchange arrays are NPY/NPZ with adjacent JSON
and validity NPY assets, bounded to 2 GiB. ENVI references must first be converted
with explicit preserved metadata. The archive manifest records asset hashes and
applicability; imports reject traversal, undeclared assets and digest mismatch.
Import does not apply a calibration. A known device mismatch is labelled and
prevents the compatibility shortcut. Missing device identity is UNKNOWN.

If a reference moves, select it and Locate. A registered digest must match; a
mismatch requires new registration. Legacy records without a digest are explicitly
user-selected/unverified. Old path and metadata provenance remain. Recent-file
Locate is also explicit and retains prior path, but does not claim byte matching.

## Reflectance boundary

`R = (I - Ds) / (W - Dw) * Rref` requires matching data meaning, linear response,
settings, geometry, references and positive reliable denominator. FP reconstruction
and reference correction are separate. Controlled scanning and reconstruction
require supported control and response assets matched to the instrument and
acquisition conditions. A labelled reference file does not supply a
response matrix, a temperature calibration or cross-device validity.

## Storage

Configuration contains the workspace, device profile, references, recent files,
ROI definitions and view. Normal close saves it; restore does not connect hardware.
Experiment outputs go in the workspace's `experiments` folder. Raw files and
partial recordings are preserved. Never commit data, reference ZIPs or device
profiles to the public repository. The redacted support report deliberately omits
raw exceptions, file paths, full identifiers and images; preview it before sharing.


## ROI questions, numbers and figures

| Question | Summary/calculation | Figure and interpretation |
|---|---|---|
| How bright and variable is each region? | Mean, population spatial SD, min/max and valid counts | Mean with spatial SD ribbon; intensity distribution for one sensor plane. Spatial dispersion is not a confidence interval. |
| Does a small bright/glare patch dominate the mean? | Median, Q25, Q75, IQR and unscaled MAD | Median with asymmetric Q25–Q75 ribbon, compared with mean/SD and quality fractions. Neither automatically removes glare from raw evidence. |
| Do curves average the same pixels at every band? | Per-band support versus common valid pixels over selected bands | Used/quality-valid counts and support exclusions. Empty common support stays unavailable. |
| Is a difference amplitude, offset or spectral shape? | Target-minus-reference bias, RMSE, descriptive correlation, admissible SAM | Pair table and residual curves with original amplitudes. Different metrics have different invariances. |
| Where does a chosen region differ from the rest? | Reference-ROI RMSE map, difference, ratio, normalized difference | Sequential scale for nonnegative distance; diverging scale for signed contrast. Grey means invalid. A score is not a defect probability. |
| Is a small spatial tail hidden by central summaries? | Exact map ECDF, shared-bin histogram and inclusive value selection | Linked raw-pixel mask and coordinates with complete geometry/excluded/used counts; display sampling does not remove tail pixels. |
| How does signal vary along an edge or coating strip? | Raw-centre projection and cross-strip mean/population SD | Pixel-distance profile, channel identity and per-bin denominators; empty bins stay gaps, and SD is spatial dispersion. |
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

The normalized-difference denominator must meet the recorded positive numerical
minimum in absolute magnitude. This epsilon guard only makes division eligible;
it is not a noise or signal threshold. The optional **Analyst signal threshold**
tests `abs(A)+abs(B)` in source units, requires a reason/evidence source, and
records excluded pixels separately. Without that evidence, low-signal
qualification remains UNKNOWN; no SNR is inferred. Signed inputs can produce
values outside [-1,1]; they are retained, not clipped into a physical range.

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
The application does not infer the required covariance or sensor-noise model
from an arbitrary scene, so no automatic uncertainty/95% ribbon is produced. [JCGM measurement guides](https://www.bipm.org/en/web/guest/publications/guides),
[EMVA 1288](https://www.emva.org/standards-technology/emva-1288/emva-standard-1288-downloads-2/).

## Coordinates, support and display limits

Arrays use row/column indices (y,x). A raw pixel at [y,x] has centre
(x+0.5,y+0.5); image edges span x=0..W and y=0..H, increasing downward.
Rectangles include centres in half-open bounds. Polygon holes and the union of
included Exclude regions subtract statistical membership. They do not redefine
sensor faults or overwrite a global raw/derived map. Brush exports store original
(y,x,value) coordinates; display zoom and overview sampling do not change them.

Per-band support uses each feature's own eligible pixels. Common support uses
the intersection over the explicitly selected features within each region.
Different common feature populations are different analysis recipes, even when
they report the same R or wavelength value. Keep incompatible/unknown observation
recipes visible and separate; identical region geometry is not required across
specimens and does not establish registration.

Summary-then-transform differs from pixel-transform-then-summary. For
(a,b)=[(9,1),(1,1)], mean pixel ND is 0.4, whereas ND of channel means is 2/3.
Sparse tails can be invisible to robust summaries: 995 values of 100 and 5 of 200
have median/P99=100, MAD=0, mean=100.5. Exact ECDF and coordinate selections
retain the five high values. A selected contrast pixel is not defect truth.

Colour bounds describe display only. Signed difference/ND/PCA maps retain centre
zero; ratio uses centre one. Robust bounds retain that declared centre, and
clipped fractions use the finite displayed-map denominator. Locked bounds are
compatible only with the declared operation/features/units/normalization.
Sequential magnitudes do not imply negative distances. Raw values, ECDF, masks,
statistics and exports remain available beyond display clipping. A numerical
epsilon prevents invalid division; it is not measured low-signal qualification.

## Study and repeat observations

An observation is one saved acquisition and its completed analysis, not an
independent specimen. Several images of one specimen remain repeated observations;
unknown specimen IDs do not become independent samples through paths or hashes.
Temperature annotations preserve value, unit, meaning and source. Setpoint,
independent specimen measurement and operator label are different evidence.
No automatic temperature, thermal history, material identity or defect probability
is inferred. Treatment duration and camera exposure are different quantities.

Settings compatibility uses known per-frame chunks before session readback;
missing evidence is UNKNOWN. File MATCH establishes integrity, not measurement
equivalence. Unknown/mismatched recipes and settings must not silently enter
pooled repeatability. Spatial SD/quartiles remain spatial dispersion; original
observation points are not automatically fitted or given 95% confidence bands.


## Export

Select Figure export in Analysis; choose current chart, **Right task plot +
selections** or derived map, title,
width/height (mm) and DPI. The directory contains:

- `figure.svg`, `figure.pdf`, `figure.png`: annotated renders, editable text in
  SVG/PDF; dense maps are rasterized inside vector figures.
- `plot.json`: PlotSpec, source/quality/ROI/feature metadata, dimensions, version.
- `series.csv`: actual x/y/SD/normalized values, stable ROI ID/revision and used
  counts; profiles also retain channel feature indices, pixel-bin edges and
  geometry/exclusion/source-quality denominators.
- `analysis_manifest.json`: exact source/output SHA-256, recipe and optional
  analyst revision for workbench exports. A changed source invalidates an old
  result export; completed results do not adopt new controls or a later live frame.
  Replacing the underlying source closes affected export dialogs. Reopen the
  export for a current completed result; export cannot silently rebind old arrays.
- Quartile bounds and used counts accompany applicable curves. The ROI table
  export also includes full statistics, optional pair/feature CSV and pinned recipe.
- `values.npy`, `valid.npy`: numerical map and mask for map bundles.
- `ecdf.csv`, `map_histograms.csv`: exact map-value counts/fractions and shared
  bin counts/densities for map distribution plots.
- `brush_01_mask.npy`, `brush_01_coordinates.csv`: full raw selection mask and
  every selected pixel's raw indices/value, with the ROI revision and range recipe.

For CSV rows with source-quality counts, `saturation_assessment=UNKNOWN` has a
blank saturated count/threshold, not zero. `ASSESSED` identifies an available
threshold; zero then means no counted sample reached it. `saturation_units`
remains the original signal unit even for a dimensionless L2 result. An unknown
assessment does not invent an exclusion mask or certify the scene as usable.

Full local figure/Study/reference bundles can contain paths, source identifiers,
specimen labels and hashes. Preview them before sharing. A digest is not
anonymization. A shareable copy is a separate explicit operation; it does not
replace the complete internal record or upload anything. Scientific units,
statistics, axis meaning and quality limitations must remain understandable.
