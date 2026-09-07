# Reflectance spectroscopy

Open **Reflectance…** in the existing workbench. The dialog separately reports
sensor connection, spectral-selector readiness and response-file checks. A sensor
image establishes imaging; it does not establish wavelength selection. Choose
native optical-state reconstruction or characterized external illumination bands.
Controller evidence can come from documented, repeatable engineering measurements.

## Process saved measurements

1. Choose **Raw optical states → reconstructed signal → reference ratio**.
2. Select a response bundle's `manifest.json`, the completed sample/white raw
   scans and their matching blocked-light dark scans. Use the same spatial grid,
   optical setup, instrument conditions, state order and calibrated settings.
3. Optionally select band-matched reference factors in CSV columns
   `wavelength_nm,reflectance`. Without characterized factors, the result is a
   **relative reference ratio**. The software does not resample this vector.
4. Click **Check inputs**, then **Process saved scans**. Work runs in the
   background. **Stop spectroscopy** stays reachable on every workbench tab.
5. A completed product opens in Analysis. Select a wavelength, click a pixel or
   define named ROIs, and run ROI summary/comparison. Mean/SD or median/quartiles,
   valid counts, actual wavelength gaps and the existing figure palette are kept.

Sample and white are reconstructed separately before the pixelwise ratio. Each
input has one dark subtraction; no fabricated zero dark is used. The second
input mode accepts already reconstructed linear signals with typed correction
history. It performs no further dark/exposure correction. Incompatible inputs
remain listed with their mismatch reasons.

Reference paths and setup choices persist when the app closes normally. They
never reconnect hardware automatically. A new sample and every new output have
their own identity. Failed/cancelled output remains partial; the previously
completed display is retained. The output folder contains `processing.json`,
separate reconstructed sample/white signals, masks, raw-state residuals and the
final `reflectance.npy` with metadata. Reopen the sample/white signal to choose
**Reconstruction residual RMS** in Analysis; **Valid spectral fraction** shows
output coverage. Residual units are the corrected state-signal units, and support
fraction is a count fraction, not spectral resolution or measurement uncertainty.

## Command line

Run these commands with an installed HyperLab Python, or replace
`python -m hyperlab` with `HyperLab.exe` in a desktop distribution. Use new output
paths. None of these file commands opens a camera.

```powershell
python -m hyperlab spectroscopy inspect-response response/manifest.json
python -m hyperlab spectroscopy characterize --input known-inputs.npz --metadata context.json --output response
python -m hyperlab spectroscopy reconstruct --scan sample.npy --dark sample-dark.npy --response response --output sample-signal.npy
python -m hyperlab spectroscopy process --sample sample.npy --white white.npy --dark-sample sample-dark.npy --dark-white white-dark.npy --response response --reference-csv panel.csv --output result
python -m hyperlab spectroscopy ratio --sample sample-signal.npy --white white-signal.npy --reference-csv panel.csv --output ratio-result
python -m hyperlab spectroscopy roi result/reflectance.npy --roi 10 10 40 40 --support common --output roi.csv
python -m hyperlab spectroscopy demo --output new-synthetic-example
```

The demo executes the numerical chain with synthetic inputs and reports its
files and errors. Its response is illustrative and cannot calibrate an instrument.
The ROI CSV uses stored dimensionless values; spatial SD is pixel dispersion,
not a confidence interval. Mean of pixel ratios is different from ratio of ROI
means. Negative and above-one values remain available for assessment.

## Response characterization

The `characterize` NPZ contains `Y`, `H`, `wavelengths` and `region_map`, optionally
paired `validation_Y`/`validation_H`. H is wavelength × input (K × N): each
**column** describes one independently known finite input spectrum. Y is region ×
state × input; A is region × state × wavelength. Y contains dark-corrected responses in
matching units. The fit is `Y = A H`. A white panel alone does not identify A.
The synthetic example provides a complete, executable schema illustration.

Metadata records actual state IDs, physical wavelength units/source, measurement
conditions, fixed gain and units, raw format, spatial grid/CFA phase, source
bandpass/discretization, correction ownership and response evidence. A region
map assigns each supported native pixel its characterized response. No demosaic
creates independently measured spectra at missing CFA photosites.

Reconstruction uses a fixed weighted least-squares operator and optional
wavelength-coordinate regularization. Equal weights are the baseline; measured
noise weights require their source evidence. Diagnostics retain singular values,
rank, conditioning and effective response. Unsupported regions/bands stay masked.
An output wavelength count does not establish that many independently resolved
bands. Small forward residuals do not establish physical spectral accuracy.

Exposure normalization requires applicable linearity evidence and range. Without
it, use the exact fixed-exposure vector in the response model. Zero dB is a valid
fixed setting, never a divisor. Raw saturation/invalidity is propagated before
inversion; reconstructed values are not compared with the sensor ADC ceiling.

## Routine physical acquisition

**Acquire reflectance cube** requires a documented controller adapter that owns
the sensor and optical selector, its actual state recipe and applicable response
and reference inputs. The current package exposes the adapter/orchestration API;
it does not implement an unknown HinaLea ABI. See
`hyperlab.spectroscopy.scan.stationary_scan` for the required bounded methods.

The adapter preflight identifies the actual instrument, ownership and documented
command/settling/exposure-freshness behavior. Each state records acknowledgment,
settling, a fresh exposure identity and an owned raw frame before persistence.
A late host receive time alone cannot establish exposure after state change.
The recorded optical states remain states until a response supports wavelengths.

A live adapter must distinguish absent endpoint, driver failure and unknown
command semantics. Its `control_evidence` references a local protocol JSON and
SHA-256. The contract binds `identity`, `kind` (`engineer_characterized` or
`manufacturer_documented`), `transport_line_behavior`, `commands_and_ranges`,
`readback`, `settling`, `exposure_freshness`, `cleanup` and `observations`. These
are retained evidence, not executable commands. A flag or host UUID alone is
insufficient; live acknowledgments also retain device/measured readback records.
Preflight checks record consistency, not physical accuracy. The controller and
its actual command semantics must be established before an adapter is provided.

For physical reflectance verification, retain independently characterized input
spectra and an independent reference under the stated illumination/geometry.
Finite-band outputs are effective-band factors, not automatically monochromatic
reflectance at their nominal centers. Instrument optical temperature and specimen
thermal treatment are separate conditions. No material, defect or temperature
accuracy is established by a successful software example.

## Repeated physical states

Legacy recipes retain their unique `states` / `exposure_us` vectors. New recipes
may supply `steps`, each with a unique `step_id`, repeatable `state_id`, `role`,
`exposure_us` and `expected_source_band` (null when unknown). For example A1–B1–A2
may visit physical states A–B–A. This is three observations, not three independent
wavelengths. `acquisition_mode` is `native_fp_state_scan` or
`external_illumination_band_scan`; LIVE/REPLAY/SYNTHETIC remains a separate origin.

The complete scan preserves all visits and exposure identities. Reconstruction
still requires exactly one observation for each distinct response row. Select
visits explicitly in the response's state order, and apply a compatible selection
to the matched dark. No automatic sorting or averaging is performed:

```powershell
python -m hyperlab spectroscopy select-steps aba/cube.npy --steps A2 B1 --output selected-sample
```

The output retains original step IDs, source indices and fingerprints. Analyse
the untouched original for drift/repeatability; pixels are not independent repeats.

## External finite illumination bands

In **Reflectance…**, select **External illumination bands → finite-band reference
ratio**. Only a local measurement manifest is needed in the form; **Check inputs**
validates the saved observations and **Process saved scans** computes new products.
This file workflow does not open a selector or automate manual filter placement.

Start with 3–5 physically characterized inputs through the same aperture/geometry,
fixed exposure/gain and stable internal optical condition. Acquire background,
white, an independent check, sample and a repeated white. A broadband image or
RGB channel label cannot supply these bands. Retain the source's measured spectrum,
peak, FWHM and usable support; do not substitute nominal LED colours.

For matched source-on/off observations, compute `C = on - off` once. Source-off
includes ambient plus detector offset; do not also subtract a blocked-dark frame.
A lens-blocked background removes detector offset only and needs ambient-control
evidence. Raw saturation, explicit masks, nonfinite samples and weak white signals
are excluded before the ratio. The numerical white floor is in DN and must be
chosen from the intended experiment's noise/throughput assessment.

For each pixel and input k, `C = integral(q * R dλ)`, where q includes actual
illumination, internal optics, detector/CFA and geometric weighting. The software
calculates `C_sample / C_white` per pixel, then ROI summaries. Unknown reference
factors yield a relative ratio. Reference calibration needs either characterized
constancy across the entire supported band, or effective factors integrated with
the applicable measured kernel. A reference value at the nominal peak alone is
insufficient. Fluorescence requires a different measurement model.

The current reference-factor vector has one factor per observation. Kernel evidence
must establish that each factor applies throughout the accepted pixel region.
Spatially varying effective reference factors require a spatial calibration model;
do not apply a single ROI-derived factor to an unqualified Bayer field.

Outputs use `band_ratio_cube`, with `spectral_bands` and unique observation IDs;
`wavelengths` stays null. Plots show discrete source peaks with horizontal source
support bars, and retain duplicate observations. The source peak is not an asserted
detector-weighted band centre. Wavelength derivatives, interpolation and continuum
inference remain unavailable for this product. Existing ROI maps, mean/spatial SD,
robust summaries, negative/above-one results and exports remain usable.

### Measurement manifest

`external-bands` accepts UTF-8 JSON with `inputs`, `setup`, `minimum_white_dn` and
optional native-pixel `roi: [x0,y0,x1,y1]`. Input paths are relative to the manifest
or explicit local absolute paths. Four complete raw HWK scans are required:
`sample`, `white`, `background_sample`, `background_white`.

| Setup field | Meaning |
|---|---|
| `acquisition_mode` | `external_illumination_band_scan` |
| `step_ids` | Unique IDs matching each scan's stored step order; repeat bands allowed |
| `bands` | One record per observation: `band_id`, `source_peak_nm`, `source_fwhm_nm`, `support_nm: [low,high]`, `source_evidence`, `source_spectrum` |
| `source_spectrum` within a band | Characterized `wavelength_nm` and nonnegative `relative_power` arrays covering support; at least three samples |
| `fixed_internal_state`, `geometry`, `illumination_stability`, `elastic_reflection_evidence` | Actual setup/condition evidence, not a claim from camera connection |
| `background_kind` | `source_off_ambient_plus_dark` or `lens_blocked_detector_dark`; the latter also needs `ambient_evidence` |
| `reference` (optional) | Positive `factors` per observation and `source`; kind `constant_over_support` needs `support_nm` and `constancy_evidence`; kind `effective_kernel_weighted` needs `kernel_evidence` and `integration_evidence` |

Each raw scan records DN/saturation, pixel format, exact spatial/CFA grid,
`scan_states` containing band IDs, `scan_steps` containing step IDs, one fixed
`exposure_s` value repeated K times, gain/units and the settings snapshot.
`measurement_context` records its role, unique `observation_id`, `evidence_source`,
`instrument_id`, `geometry_id`, `fixed_internal_state_id`, `illumination_id` and
`temperature_condition_id`. Background contexts also record `background_kind`.
Settings must match across inputs, with automatic exposure/gain/white balance/black
level off. Known linear gamma/LUT settings are checked. Unknown gamma can instead
use `linearity` evidence with kind `measured_exposure_series`, `source`,
`exposure_range_s`, `raw_dn_range`, `gain`, matching `settings`, measured
`maximum_residual_fraction` and a `predeclared_limit_fraction`. This consistency
check does not establish physical linearity by itself; use an independently
reviewed measured range and stable illumination. Values outside that raw DN range
in any of the four inputs are masked. No exposure normalization occurs.

Optional input pairs `repeat_white` / `background_repeat_white` and `check` /
`background_check` produce separate ratio products. Their contexts use white /
background_white or check / background_check roles and distinct observation IDs.
Diagnostics report common-ROI repeat drift as mean pixel ratio minus one. Optional
`check_reference` supplies `values`, identical `bands`, matching `quantity`
(`relative` or `effective-band reference-calibrated`), `source` and
`matched_geometry_and_kernel_evidence`. Differences are reported without inventing
an uncertainty-based acceptance threshold. The calibration white cannot check itself.

### Import manual observations and export

`pack-bands` imports individual saved raw frames using an observation JSON:
`metadata` contains the raw-scan context/grid above; `frames` contains `path`,
`step_id`, `band_id` and the actual placement `confirmation` for every frame.
Acquisition identities, settings and masks come from the frame receipts. Reused
exposures, changed settings and grids are refused. Missing quantities are not
filled with plausible numbers. Original frames stay untouched; failed imports
retain their durable prefix.

```powershell
python -m hyperlab spectroscopy pack-bands --manifest sample-observation.json --output sample-scan
python -m hyperlab spectroscopy external-bands --manifest measurement.json --output measured-bands
python -m hyperlab spectroscopy roi measured-bands/band-ratios.npy --roi 10 10 40 40 --support common --output measured-roi.csv
```

Repeat packing for the other actual observations. The processing directory has
`band-ratios.npy`, a validity mask and sidecar, `band-diagnostics.json`, optional
repeat/check products and `processing.json`. The compact table shows actual source
bands, white signal and invalid fraction. ROI CSV includes explicit source peak,
support, bandwidth and step IDs; its detector wavelength column is empty. Source
profiles and interpretation also remain in figure/CSV metadata. Cancellation
keeps partial data without replacing the last completed display.
