# Round 1 — physical measurement and calibration reviewer

Reviewer: independent AI reviewer 1. Date/access date: 2026-09-06.
Baseline inspected: `7ab867b2946035a162254f1d63cdc4d156b52e47`.
This is an independent first-round engineering review, not a consensus or a
human peer-review certificate. No camera, serial port or native UI was operated.
Only this review document was added; production code was not changed.

## Recommendation

Build a defensible material/paint comparison workbench around explicit data
levels, reference applicability, robust ROI summaries, physical wavelength
intervals and repeatability. The existing imaging and plotting work is useful.
It does not establish a calibrated wavelength axis or temperature measurement.
The user confirms both thermal paint and material/defect comparison as use cases.
The paint chemistry, exposure protocol, independent temperature reference and
defect ground truth remain unspecified; unknown fields must stay unknown.

The highest-priority finding is a mismatch between the written reflectance
contract and executable admission checks. Correct that before adding more
algorithms. A smaller set of well-defined derived quantities is preferable to
an unrestricted menu of transforms whose input assumptions cannot be satisfied.

## Search and evidence register

Primary research, author repositories, standards and an author dataset card were
inspected. Search terms included dark/white reference calibration, spectral
response/FWHM integration, Fabry–Perot characterization, temporal versus spatial
variance, thermal paint temperature/time and hyperspectral reflectance datasets.
This bounded search is not a systematic review or proof that no other example
exists. Repository examples were inspected, not installed or benchmarked.

| ID | Primary source and evidence inspected | Transferable result and limit |
|---|---|---|
| P1 | [Mazdeyasna et al., 2025, normalization study](https://pmc.ncbi.nlm.nih.gov/articles/PMC11763101/), peer-reviewed full-text methods/equations inspected; a later fetch encountered a CAPTCHA | Actual HinaLea 4250 diffuse-target measurements used reconstructed wavelengths, matched dark/white observations and repeated acquisitions. Preserve amplitude beside L2/SNV because normalization can remove material differences. Its device settings, target geometry and performance do not calibrate this instrument or validate metal coatings. |
| P2 | [Picone et al., arXiv:2303.14076](https://arxiv.org/abs/2303.14076), author abstract; [IRCA author code and notebooks](https://github.com/danaroth83/irca), README inspected, linked Optics Express DOI 10.1364/OE.491698 | Monochromatic characterization fits a parametric FP transmission model. Modeling, characterization and simulation notebooks illustrate separation of forward model, calibration observations and reconstruction. The multi-aperture ImSPOC design differs from this unknown HinaLea optical/controller configuration. No interchangeable response matrix or control protocol is established. |
| P3 | [Pekkala et al., Metrologia 56, 065005, author project page](https://www.aalto.fi/en/department-of-electrical-engineering-and-automation/hyperspectral-camera-calibration-2017-2019); [institutional abstract](https://cris.vtt.fi/en/publications/setup-for-characterising-the-spectral-responsivity-of-fabry-perot/) | Monochromator, diffuser and angular control support spectral responsivity characterization; the reported setup detects channel leakage. Full reprint could not be opened during this review, so no detailed uncertainty or accuracy values are adopted. |
| P4 | [NIST SP 250-48, Spectral reflectance](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication250-48.pdf), measurement definitions and uncertainty tables inspected | A camera ratio must name its geometry and measurand. BRDF, bidirectional reflectance factor and directional-hemispherical reflectance differ. Viewing angle, wavelength, source stability and stray light enter uncertainty. A reflectance factor can exceed one; clipping is not a physical validity test. |
| P5 | [BIPM/JCGM guides](https://www.bipm.org/en/web/guest/publications/guides), official catalogue, including GUM 100:2008, 101:2008 and the 2026 nonlinearity amendment; [GUM 100 text](https://www.bipm.org/documents/20126/2071204/JCGM_100_2008_E.pdf/cb0ef43f-baa5-11cf-3f85-4dcd86f77bd6) | Measurement uncertainty belongs to an explicit model and input uncertainty/covariance evidence. First-order propagation and Monte Carlo are distinct methods with applicability conditions. A pixel SD is not automatically a standard uncertainty, and a coverage factor alone does not establish 95% coverage. The amendment was identified, not fully reviewed. |
| P6 | [EMVA 1288 release 4.0 Linear](https://www.emva.org/wp-content/uploads/EMVA1288Linear_4.0Release.pdf), temporal/spatial variance definitions inspected; [reference implementation](https://github.com/EMVA1288/emva1288) | Repeated observations and controlled illumination separate temporal effects from stationary spatial response. Its linear photon-transfer route requires appropriate raw linear measurements. An arbitrary scene and unknown processing cannot yield a compliant camera SNR, gain or PRNU certificate. The implementation's LGPL license is a separate consideration from HyperLab's deferred original-code license. |
| P7 | [Spectral Python BandResampler documentation](https://www.spectralpython.net/class_func_ref.html#spectral.BandResampler); [original implementation](https://github.com/spectralpython/spectral/blob/master/spectral/algorithms/resampling.py) | The documented Gaussian/FWHM resampling model makes response assumptions explicit and produces NaN for unsupported output bands. Its fallback bandwidth estimate must not be imported as measured instrument FWHM. For the first increment, exact-axis interval summaries are safer than automatic library resampling. |
| P8 | [HYPERNETS processing paper, 2024](https://www.frontiersin.org/journals/remote-sensing/articles/10.3389/frsen.2024.1347230/full), sections 3.4 and 4 inspected; [author processor](https://github.com/HYPERNETS/hypernets_processor) linked by the paper | A useful advanced example separates raw, calibrated and reflectance products, propagates error correlation, retains flags and valid/total counts, and distinguishes uncertainty components. Transfer this architecture, not its land/water-specific equations or placeholder uncertainty percentages. |
| P9 | [BGLab HSI-SC-NeRF dataset card](https://huggingface.co/datasets/BGLab/HSI-SC-NeRF), author card inspected, linked arXiv:2602.16950 | The card separates white references, original ENVI acquisitions and derived 3D products. It offers an exchange/provenance example and potential external research data, not HinaLea calibration or thermal-paint labels. The card declares CC-BY-NC-4.0 and a large collection; no download or numeric validation was performed. |
| P10 | [Thermal history analysis using temperature indicating paints](https://www.tandfonline.com/doi/full/10.1080/01430750.2020.1737838), publisher abstract/search extract only; full page unavailable | The abstract explicitly treats temperature and time together. It supports recording exposure history; it does not provide an inspectable inverse model for this paint. Do not transfer luminescent thermal-history paint equations to irreversible colour-change paint without establishing the material mechanism. |

Search also found the CVPR 2025 paper
[Automatic Spectral Calibration of Hyperspectral Images](https://openaccess.thecvf.com/content/CVPR2025/papers/Du_Automatic_Spectral_Calibration_of_Hyperspectral_Images_Method_Dataset_and_Benchmark_CVPR_2025_paper.pdf).
The indexed primary extract describes measured illumination and dark-corrected
reference data, but direct full-PDF access returned 403. It is a follow-up lead,
not evidence that learned illumination correction recovers a missing FP response.

## Executable baseline findings

The existing `PHYSICS_AND_DATA.md` correctly separates states, time, CFA, colour,
wavelengths and reflectance. `analysis/capabilities.py` prevents RGB spectral SAM
and PCA and admits documented external spectral cubes independently of local H3.
`analysis/core.py` uses floating dark subtraction, masks, saturation thresholds,
shared selected features and unclipped ratios. `analysis/quality.py` and
`experiments.py` already distinguish spatial variation from temporal observations.
Preserve these decisions; do not reimplement them under new names.

**F-P1 / P0: reference applicability is incomplete.** `reflectance()` compares
shape, wavelength vector, settings, exposure, gain, processing steps and units,
but does not check response calibration, device identity, optical geometry or
sample/white illumination evidence. Empty `settings={}` also passes the known
value test. A synthetic offline counterexample at this baseline used sample,
white and two dark arrays with values 30, 100, 10 and 10, respectively. Sample
and white explicitly carried different calibration, illumination and geometry
IDs; the result was accepted as relative reflectance, 0.222222 in both bands.
This is a reproduced admission gap, not a claim that previous real frames were
reflectance corrected. The counterexample did not access hardware or raw files.

Use a shared applicability report with MATCH / MISMATCH / UNKNOWN outcomes.
Apply sensor/response/axis/linearity/settings compatibility to all four inputs;
apply illumination and geometry agreement to sample versus white. A dark's
blocked-light acquisition method should be recorded, not forced to equal the
sample's illuminated condition. Unknown applicability must not silently pass a
physical reflectance workflow. Explicitly labelled synthetic fixtures may supply
synthetic context evidence; they must not bypass the numerical checks.

**F-P2 / P1: uncertainty is not yet represented.** Existing SD fields are sound
descriptive statistics. Retain their meaning. Add uncertainty only with explicit
input uncertainty and dependence evidence; absence must produce unavailable
uncertainty, not zeros or a default sensor-noise estimate.

**F-P3 / P1: interval features need a different contract from index averages.**
The importer already supports FWHM and monotonic wavelength order. A descending
axis is legitimate, but integration must record its internal orientation.
Disjoint globally valid bands must not create an unmarked trapezoid over a bad
spectral region. Interpolation must never create measured resolution.

## Mathematical and units contract

These are proposed implementation contracts and direct derivations for review.
They are not estimates of this instrument's presently unknown parameters.

1. A linear spectral measurement has the form
   `y[p,s] - d[p,s] = t[s] * sum_j A[p,s,j] * L[p,j] + error`.
   Here exposure `t` is in seconds, raw measurements in DN, and `A` includes the
   response and wavelength-bin integration appropriate to radiance units.
   Multiple FP orders and field/temperature dependence belong to `A`; RGB
   channels and state indices cannot be relabelled as narrow-band wavelengths.
   A numeric gain in dB is not a linear multiplicative factor. [P2, P3]
2. With compatible measurement domains, define `N = I - Ds`, `D = W - Dw`,
   `R = r_ref * N / D`. `R` is dimensionless; name the result relative ratio or
   reference-calibrated reflectance factor with measurement geometry. Preserve
   negative and greater-than-one values and flag interpretation separately.
   Require a positive usable denominator in the input units, masks and the
   existing saturation exclusions. A ratio of FP state integrals is generally
   not a monochromatic reflectance; reconstruction and division do not commute.
   Wavelength spacing, spectral resolution and reference accuracy differ. [P1–P4]
3. For `x = [I, Ds, W, Dw, r_ref]`, the first-order gradient is
   `J = [r_ref/D, -r_ref/D, -r_ref*N/D^2, r_ref*N/D^2, N/D]`.
   A supported standard uncertainty is `u_R = sqrt(J * Cov(x) * J.T)`.
   Shared dark/reference contributions require covariance. If the same dark
   variable is used twice, its combined derivative is
   `r_ref * (N - D) / D^2`; treating two copies as independent is incorrect.
   Covariance must be finite, symmetric and positive semidefinite with recorded
   units/order. Near-zero denominator/nonlinear cases need a justified model or
   an unavailable result, not an unqualified normal-error interval. [P5, P8]
4. Spatial mean and population SD describe selected pixels:
   `mean = sum(v)/n`, `SD = sqrt(sum((v-mean)^2)/n)`.
   Add median, IQR and unscaled MAD as robustness summaries with explicit
   quantile convention. Do not write `SD/sqrt(pixel_count)` as specimen-level
   uncertainty: neighbouring pixels and overlapping ROIs are correlated.
   Repeated same-pixel observations estimate temporal variability under the
   recorded conditions, including illumination/scene drift unless separated.
   Counts and policy travel with every band/feature. [P5, P6]
5. For physical wavelength intervals, a trapezoidal area is
   `A = sum_j 0.5*(R[j]+R[j+1])*(lambda[j+1]-lambda[j])`.
   Reflectance area has units nm when wavelengths are nm; `A/(lambda_b-lambda_a)`
   is a dimensionless interval mean. An actual sensor comparison instead uses
   `sum_j q[j]*R[j]*delta_lambda[j] / sum_j q[j]*delta_lambda[j]`, with explicitly
   supplied response/illumination weighting appropriate to its measurand.
   A simple interval average does not reproduce an arbitrary multi-order FP
   response. No guessed FWHM, extrapolation or bridging invalid gaps. [P7, P8]
6. A finite wavelength slope has units `signal_units/nm`. A straight shoulder
   continuum `C(lambda)` and `1 - R/C` band depth are conditional descriptive
   spectral features, not automatic chemical identification. Shoulder choices,
   interval bounds, bad-band support, denominator and preprocessing must be
   exported. Avoid an automatically selected peak being reported as an
   independently validated wavelength or a temperature calibration feature.

## Prioritized implementable functions

| Priority | Function and admission | Plot/export | Required acceptance |
|---|---|---|---|
| P0 | Shared reference applicability preflight and explicit measurement-context record | Compact status with expandable mismatches/unknowns; context in derived JSON | Reject F-P1, unknown nested settings and mismatched roles; accept a fully specified synthetic matched case; original cubes unchanged |
| P1 | ROI median, IQR, MAD, min/max and valid fraction alongside existing mean/SD | Existing amplitude plot may switch to median with IQR; one summary table, same ROI colours | Hand-calculated masked values, empty ROI band, saturation-policy changes, exact CSV and quantile convention; do not call IQR a confidence interval |
| P1 | Interval integral and wavelength-weighted mean | Highlight the selected interval on the original spectrum; compact feature table and map | For wavelengths [500,510,540] nm and values [0.2,0.3,0.6], area = 16 nm and mean = 0.4; descending axis gives same result; bad gap is rejected or explicitly segmented; RGB disabled |
| P1 | Explicit shoulder slope and continuum-relative depth for documented spectra | Original amplitude plus chosen baseline/derived branch; named bands and units | Linear continuum gives zero depth; imposed 20% depression gives 0.2; invalid/zero baseline, absent wavelength support and arbitrary extrapolation rejected |
| P1 | ROI temporal repeatability/drift report over saved matching frames | Mean versus actual clock/index, spatial and temporal quantities on distinct panels | Same saved frame/redraw does not increase repetitions; settings mismatch rejected; unknown settings labelled; partial recording prefix and all losses retained |
| P1 | Compare specimen/reference ROI vectors with amplitude residual, RMSE and existing SAM only where admitted | Residual line, parity plot and units, plus amplitude; common feature count | Identical vectors give zero residual, scale change affects RMSE but not SAM, offsets affect SAM; mismatch in units/axis rejects; no defect-probability label |
| P2, conditional inputs | Optional first-order reflectance uncertainty calculator with explicit covariance | Separate labelled standard-uncertainty band/table; no automatic 95% ribbon | Analytic derivative versus finite difference; correlated/shared-dark example; PSD and near-zero-denominator rejection; missing uncertainty remains unavailable |
| P1 | Publication analysis bundle linking ROI definitions, source hashes, methods, context, counts, figures and numbers | Existing vector/raster figure export plus machine-readable summary and compact methods text | Numeric and UI/export agreement; raw hashes unchanged; REAL/SYNTHETIC and spatial-SD/uncertainty labels retained; private context stays local |

## Experiment design for paint and defect studies

Record specimen/workpiece, coating identity and batch, substrate, surface
preparation, thickness if measured, thermal exposure schedule, dwell time,
atmosphere, cooling and time since exposure. Temperature values need their
independent measurement source and uncertainty; a filename or handwritten label
is an owner declaration until verified. Illumination spectrum/setup, warm-up,
sample/reference geometry, working distance, focus, camera settings and reference
timing are part of an acquisition, not hidden properties of a normalization.

Use independently prepared specimens across temperatures/exposure conditions,
with repeated acquisitions on different sessions. Keep repeat acquisitions and
multiple ROIs nested within a specimen. A future model must split by workpiece
and session before tuning features; adjacent pixel splits cannot establish
generalization. Keep a held-out session/specimen and independently assessed
defect reference, including non-defective controls and glare/geometry changes.
These are proposed design requirements, not a completed experiment.

## Objections and convergence conditions

- Reject any temperature inverse map, chemical/defect classifier confidence,
  material fractions or physical detection limit until an independently labelled
  and applicable calibration/validation study exists. Unsupervised scores may
  help inspection but are not probabilities or labels.
- Reject neural RGB-to-spectrum reconstruction as recovery of this instrument's
  missing response assets. Learned priors may generate plausible outputs while
  leaving the physical inverse non-identifiable.
- Reject automatic white correction using merely equal file shapes/settings.
  A reference-calibrated scalar/vector alone does not remove coating BRDF,
  illumination drift, registration errors or FP leakage.
- Do not implement sensor quantum efficiency, photon-transfer gain, certified
  SNR/PRNU/DSNU or metrological reflectance uncertainty from current scene
  recordings. Controlled input series and suitable linearity/response evidence
  are prerequisites; the EMVA example is a future verification route.
- Keep high-level workflows concise: Inspect → Compare ROIs → Spectral features
  when admitted → Export. An expandable Details area should carry units, quality,
  provenance and applicability without crowding the main chart controls.

Round 1 disposition: support the eight functions above subject to the stated
admission and tests. F-P1 is a required correction. Spectral features can be
implemented and independently tested now for evidenced external cubes; their
physical use on the connected instrument remains conditional on H2–H4 assets.
Hardware calibration, temperature inference and classifier validation are
NOT_TESTED in this review. Round 2 must challenge scope, uncertainty admission,
gap handling, context usability and computational cost before implementation.
