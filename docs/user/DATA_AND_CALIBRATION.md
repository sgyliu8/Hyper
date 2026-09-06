# Data, references and portability

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
and reference correction are separate. No recovered controller/calibration assets
currently establish H2-H4. A labelled reference file does not supply the missing
response matrix, a temperature calibration or cross-device validity.

## Storage

Configuration contains the workspace, device profile, references, recent files,
ROI definitions and view. Normal close saves it; restore does not connect hardware.
Experiment outputs go in the workspace's `experiments` folder. Raw files and
partial recordings are preserved. Never commit data, reference ZIPs or device
profiles to the public repository. The redacted support report deliberately omits
raw exceptions, file paths, full identifiers and images; preview it before sharing.
