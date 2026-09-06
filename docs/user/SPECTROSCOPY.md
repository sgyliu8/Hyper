# Reflectance spectroscopy

Open **Reflectance…** in the existing workbench. The dialog separately reports
sensor connection, spectral-selector readiness and response-file checks. A sensor
image establishes imaging; it does not establish wavelength selection. The
supplied dependency installers/libraries do not contain a HinaLea selector API.

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
paired `validation_Y`/`validation_H`. Rows of H describe independently known
finite-band input spectra; Y contains their dark-corrected sensor responses in
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

The missing companion asset is the matching HinaLea API/SDK core with headers or
working examples, selector configuration/recipe and any per-unit response files.
Third-party camera, Qt, CUDA and MKL dependency files support that core but cannot
replace its command semantics or measured response. Once control is known, raw
scanning can proceed even if response characterization still needs measurement.

For physical reflectance verification, retain independently characterized input
spectra and an independent reference under the stated illumination/geometry.
Finite-band outputs are effective-band factors, not automatically monochromatic
reflectance at their nominal centers. Instrument optical temperature and specimen
thermal treatment are separate conditions. No material, defect or temperature
accuracy is established by a successful software example.
