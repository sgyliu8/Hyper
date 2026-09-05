# Physical model and data meaning

This is the working scientific contract, not a calibration certificate. The
sensor has demonstrated real single-frame imaging; current persistent-session
acceptance is blocked by a USB communication failure. No measured response matrix for this
instrument has been recovered. Scanner state, wavelength, time and colour are
different axes. Evidence and source applicability are recorded in [SOURCES](SOURCES.md).

## Measurement model

For a pixel/photosite `p`, a confirmed FP state `s`, and wavelength bin `j`, a
candidate linear measurement model is

```text
y[p,s] - d[p,s] ≈ t[s] · g[s] · Σ_j A[p,s,j] · L[p,j] + ε[p,s]
```

| Symbol | Meaning and units / evidence requirement |
|---|---|
| `p` | Raw sensor location including CFA phase and geometry; not automatically a reconstructed independent spectral pixel |
| `s` | Documented, repeatable optical state ID with acknowledgement and timing; a numeric state ID is not nm |
| `j`, `λ[j]`, `Δλ[j]` | Explicit wavelength discretization, units and mapping evidence |
| `y`, `d` | Raw measurement and matched dark expectation in DN; subtraction occurs in floating point |
| `t` | Exposure in seconds in this equation; UI ms and camera API µs are explicit conversions |
| `g` | Defined, dimensionless linear system gain relative to a stated reference; never multiply by the numeric dB setting (0 dB is not a factor of zero). Any dB-to-response conversion requires documented convention and validation |
| `L` | Spectral radiance, for example W m⁻² sr⁻¹ nm⁻¹, for the chosen spectral bins |
| `A` | Combined response including `Δλ`, FP transmission, optics, sensor/CFA response, and radiance-to-DN conversion consistent with `t`, `g`, and the chosen units |
| `ε` | Residual noise/model error in DN after the stated processing; not assumed independent, constant or Gaussian without evidence |

The equation must be checked over the intended exposure, signal, temperature,
position and processing range. Gamma, LUT, auto exposure/gain, white balance,
black level and nonlinear camera processing can invalidate a naive linear model.
Unknown node values remain unknown. Sensor temperature is not FP temperature.

The public TruTag patent describes calibration using narrowband illumination,
power reference, FP gap and temperature records, followed by reconstruction.
It supports separating measurements from reconstructed wavelengths, but neither
its example state counts nor its interface diagrams define this camera's command
protocol. [US10323985B2](https://patents.google.com/patent/US10323985B2/en)

One FP state may transmit several spectral orders. RGB/Bayer responses do not
automatically form independent narrow bands. `A` may depend on position, ray
angle, aperture and temperature; using one matrix across the field requires
support. Simultaneously estimating an unknown matrix and arbitrary unknown
scene spectra from a few images is generally non-identifiable: prior assumptions
can constrain a model, but do not measure this instrument's calibration.

No inverse/reconstruction implementation or physical validation is claimed here.
Before adding one, use independently generated synthetic forward/inverse cases,
report matrix dimensions, rank/conditioning and noise response, solve constrained
least squares or an explicitly regularized problem, and validate with independent
known spectra. Do not directly invert an ill-conditioned matrix. Nonnegative
solutions and plausible-looking colours do not demonstrate spectral accuracy.

## Data levels and provenance

| Level | Physical axis and permissible interpretation |
|---|---|
| `raw_frame` | One `HW` sensor mosaic/mono plane, or `HWC` named camera colour channels; original DN and processing evidence |
| `raw_sequence` | `THW` / `THWC` temporal samples at the current optical state; time does not become spectral features |
| `raw_scan` | Ordered, acknowledged FP states and associated images; state-vector comparisons are possible before wavelength calibration |
| `spectral_cube` | `HWK` with a declared/documented/experimentally verified wavelength axis and reconstruction provenance; evidence levels remain distinct |
| `reflectance_cube` | A derived wavelength product with matched measurement/reference conditions and a stated relative or reference-calibrated level |

An external cube with adequate metadata can be analysed without this instrument
reaching H3. Merely declaring wavelengths in a file does not experimentally
verify them. Missing wavelengths stay null; no generated linear axis is attached
to real data. Equivalent units may be converted with original text preserved;
conflicting, unknown, repeated or non-monotonic axes must not be silently repaired.

`acquisition_source` records LIVE/REPLAY/SYNTHETIC origin and `display_mode` records
what the user currently sees. Reopening a real saved frame displays REPLAY while
retaining its LIVE acquisition provenance. A session UUID plus sequence and
device evidence identifies a frame; device frame counters can reset on reconnect.
Device time, host monotonic receipt time and host UTC are separate. Without clock
calibration their difference is not an absolute transport-latency measurement.

Storage dtype, PFNC sample bits and ADC precision are three fields. `BayerRG12`
is preserved as 12-bit samples in a uint16 container; uint16 maximum does not
define saturation. ADC precision must come from actual nodes or an explicitly
qualified manufacturer source. RGB8 readout is not evidence of an 8-bit ADC.

Original arrays and acquisition receipts are immutable. Display stretch, gamma,
demosaicing, averaging, normalization and numerical analysis produce distinct
display/derived results. Store axis mapping, frame/settings/time records, quality
policy, completion/partial prefix, runtime, calibration references and processing
steps alongside results. Writer checkpoints advance only after durable data;
missing frames and failed states remain in the denominator.

## References and quality

When wavelength measurements and matched references make the formula applicable,

```text
R(λ) = (I(λ) - Ds(λ)) / (W(λ) - Dw(λ)) · Rref(λ)
```

The current minimum path requires compatible geometry, illumination, response
calibration, exposure, gain, automatic processing and axes. `Ds` and `Dw` are
the corresponding darks. Different exposures are not mathematically impossible,
but require independently verified linearity, true settings, matched darks and
normalization in the correct measurement domain. A state-wise white ratio through
a multi-passband FP is not automatically wavelength reflectance: reconstruction
and elementwise division generally do not commute.

Check positive usable denominator, saturation and masks after floating subtraction.
Do not silently clip legitimate zero, negative or >1 results; distinguish valid
calculation from a physically questionable value. Raw-DN ignore/saturation
sentinels belong to source provenance, not the derived reflectance value domain.
Derived validity masks govern downstream statistics.

Diagnostic statistics retain all finite, otherwise valid samples; quantitative
statistics apply the recorded quality exclusions. Report total, valid, saturated,
ignored and invalid counts with policy and reasons, and clarify overlap between
quality categories. Missing saturation/processing evidence cannot justify a claim
of quantitative acceptance. ROI spatial SD describes spatial variation; temporal
SD requires repeated observations of the same pixels/settings. Neither is a
temperature uncertainty or, by itself, pure sensor noise.

Use a common selected feature set for PCA/angles, excluding global bad bands
before per-pixel validity. Keep indices, reasons and reference selection. Do not
compare angles using different feature dimensions at each pixel. A one-component
positive vector gives zero angle to every other positive scalar and is disabled
as an informative multi-feature comparison. SAM uses radians, clipped normalized
dot products and rejects zero vectors. It is invariant to positive scaling, not
to additive offsets, stray light, saturation, BRDF or actual spectral change.
PCA variance is an observed data direction, not defect ground truth.

Keep an amplitude branch alongside any normalized-shape branch. The 4250
normalization study warns that noise/outliers affect normalizers and that some
normalizations can remove real target differences; its diffuse-target findings
are not metal-coating validation. [Mazdeyasna et al., 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC11763101/)

## Bayer, display and future materials work

Bayer R/G1/G2/B phase statistics use raw sensor coordinates, ROI parity, crop
offsets and flips. Four CFA phases are not four calibrated spectral bands.
Demosaicing is a labelled display derivation. Raw sensor dimensions alone do not
establish independent spectral spatial resolution. A generic camera RGB preview
is not measured sRGB; no CIEDE2000 or temperature map is derived from its PNG.

Fixed-state experiments can establish repeatability, drift, usable DN intervals
and candidate differences under documented scene conditions. Record workpiece,
ROI, illumination, angle, distance and unknowns. Do not convert differences into
unverified causes such as oxidation, scratches or thermal discoloration.
Future thermal-paint calibration needs temperature, dwell time, paint batch,
substrate and independent standards. Model splits must separate workpieces and
sessions; neighbouring pixels are not independent specimens. No learned model
can substitute here for missing factory spectral calibration.
