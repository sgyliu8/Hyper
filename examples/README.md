# Synthetic and offline data contract

The generator creates a 48 x 64 x 24 `uint16` dataset with `synthetic=true` and
`data_source=SYNTHETIC`. It contains a changed simulated spectrum, a brightness
change, an 80 DN dark pedestal, noise, 12-bit saturation and declared invalid
pixels. Its wavelength vector is part of the synthetic design. It is never a
HinaLea measurement or a camera calibration.

From the project root, using the project virtual environment:

```powershell
.\.venv\Scripts\python.exe examples\generate_synthetic.py local\synthetic_example.npy
.\.venv\Scripts\python.exe -m hyperlab inspect local\synthetic_example.npy
```

Use a new output filename on each run; saves do not overwrite existing products.
Generated arrays belong in `local/` and do not need to be committed.

## Python interface

```python
from hyperlab.io import load_cube, save_cube
from hyperlab.analysis import roi_statistics, export_roi_csv, pca, spectral_angle

cube = load_cube("local/synthetic_example.npy")
roi_a = roi_statistics(cube, (8, 8, 26, 24))
roi_b = roi_statistics(cube, (35, 25, 55, 42))
export_roi_csv(roi_a, "local/roi_a.csv")
scores = pca(cube, max_samples=10000, standardize=False)
angles = spectral_angle(cube, roi_a["mean"])
```

`Cube.data` always has H,W,K axes. K means state/index when `wavelengths` is null.
`Cube.metadata` retains data level, signal units, declared wavelength units and
source, source device/runtime, exposure/gain, processing, completion state and
original provenance. `Cube.valid_mask` is a boolean HW or HWK array when supplied.
ENVI `data ignore value` and `bbl` are also respected by analysis functions.

An external NPY has no inherent axis names: provide `axis_order="KHW"`, `"HWK"`
or the actual permutation. `axis_order="HW"` explicitly maps one 2D sensor frame
to HW1. An ambiguous NPZ requires `dataset="actual_array_name"` as well. There
is no automatic proprietary DAT, Bayer-channel, MAT or HDF5 interpretation.

Saved NPY uses `<file>.npy.json` plus an optional `<file>.npy.valid.npy` mask.
NPZ stores `data`, JSON text `metadata`, and an optional `valid_mask`; loading NPZ
materializes the selected array, so use NPY or ENVI for large datasets.
ENVI supports BSQ/BIL/BIP, supported real numeric ENVI dtypes, byte order, header
offset and wavelength metadata. Complex-valued ENVI data needs an explicit
scientific interpretation and is rejected. The header identifies its binary
through `data file` or a unique matching binary filename; ambiguous cases need
`binary_path=`. The implementation follows the
[ENVI header specification](https://www.nv5geospatialsoftware.com/docs/enviheaderfiles.html).

Project scans use preallocated `cube.npy` and a JSON sidecar. The writer owns
`frame_count`, `expected_frames`, `frames`, `completed`, `partial` and `status`.
Loading presents only the recorded prefix `:frame_count`; zero acquired frames
raise a clear error. Missing states are never generated to complete a scan.

## Interpretation and memory

Rectangles are half-open `(x0,y0,x1,y1)`, with coordinates in the original image.
ROI results include per-index mean, population standard deviation (`ddof=0`) and
valid count. CSV never adds a wavelength or unit absent from the source.
Composite channels use a display stretch and are not colorimetrically calibrated.
Difference/ratio products retain NaN and an explicit validity mask.

PCA fits a bounded deterministic random sample, then transforms chunks. Its
default is mean centering without per-band standardization. Results include fit
sample counts, random seed, preprocessing and explained variance ratio. SAM is
Spectral Angle Mapper, returns radians, and invalidates zero vectors. Without
wavelength metadata its result is a state vector angle difference. These outputs
are descriptive differences, not validated defect diagnoses.

ENVI and NPY input arrays are memory mapped. ROI processes one band at a time;
PCA and SAM transform bounded chunks. The input estimate is
`H * W * K * itemsize`; output maps and masks also require memory. Reflectance
produces one float32 output cube and its boolean mask. NPZ, selected bands and
display products allocate memory; this is not a fully out-of-core application.

`reflectance(sample, white, dark_sample, dark_white)` requires completed spectral
cubes, matching wavelength vectors/units, known wavelength sources, explicit
`linear_intensity=true`, and identical known `settings`, `exposure`, `gain`,
`processing_steps` and signal units. Each input needs a known saturation value
or effective bit depth. Inputs are converted to float before subtracting dark
frames. Saturation, invalid samples and small/nonpositive white-minus-dark
denominators are masked. Values are not silently clipped to [0,1]. By default
the output is a relative reference ratio. A supplied reference reflectance
vector requires its source and changes the label to reference-calibrated; this
does not establish metrological accuracy or correct viewing/illumination geometry.
