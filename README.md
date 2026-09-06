# HyperLab

A local Windows workbench for imaging and spectral data, region comparisons,
bounded acquisition and reproducible scientific figures. Offline analysis works
without a camera. The English Qt interface uses white figures and consistent
orange, blue and teal region colours.

- Named rectangle/polygon/mask/strip regions, reference/target/exclude roles and
  separate display/statistical inclusion.
- Raw mean/SD or median/quartiles, exact map distributions and spatial selections,
  line profiles, residuals, PCA and supported wavelength operations.
- Original-observation Studies, explicit comparison conditions and source-bound
  PNG/SVG/PDF/CSV/NPY exports.
- NPY/NPZ/ENVI data, per-user workspaces and a supported USB3 Vision imaging path.

Original-code licensing and public binary release remain pending. The online
evaluation branch is `feature/materials-science-v040`; the default branch remains
`recovery/hinalea-local`. A locally supplied candidate may contain later changes;
use its BUILD.json and exact source revision, not a version label alone.

## Install and open

Windows x64 / Python 3.11 is the tested desktop environment. Linux supports
offline/offscreen checks; macOS is not qualified. For the online evaluation branch:

```powershell
git clone --branch feature/materials-science-v040 --single-branch https://github.com/sgyliu8/Hyper.git
cd Hyper
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m hyperlab doctor
.\Start-HyperLab.cmd
```

Startup does not connect a camera. Use a supplied authorized desktop ZIP when
available; keep its complete folder together. [Installation](docs/user/INSTALL.md)
covers independent wheels, workspaces, drivers and process-scoped PowerShell launch.

## Use and interpret

Open a saved observation or acquire/save one. Define regions, inspect quality,
Run analysis, choose the right-hand task plot, then inspect Results/Export. A
Study retains original observations and their recipes without inventing independent
specimens or pooling incompatible measurements.

[User guide](docs/user/USER_GUIDE.md) ·
[Data and methods](docs/user/DATA_AND_METHODS.md) ·
[Troubleshooting](docs/user/TROUBLESHOOTING.md) · [Changes](CHANGELOG.md)

Image acquisition requires the official Windows USB3 Vision driver and the
supported x64 Balluff Impact Acquire runtime; Python installs also need the
camera extra. No driver, CTI, calibration or raw data is bundled. A Bayer/RGB image
or time sequence is not a reconstructed hyperspectral cube. FP control,
state/frame synchronization and device-matched response calibration must be
established separately. No automatic temperature or defect-probability result is
claimed from uncalibrated DN. Recording modes require qualification on the actual
storage, scene and settings; finite successful runs do not prove sustained rates.

## Examples and support

`python -m hyperlab demo` opens explicitly synthetic data.
`python -m hyperlab figure-demo --output NEW_DIRECTORY` creates illustrative
figure/data bundles; use a new directory. See [data examples](examples/README.md).
Public examples are synthetic and are not camera or material-validation evidence.

For development, use `pip install -e ".[test]"` and focused/offline tests.
Preview a redacted support report before sharing; nothing is uploaded automatically.
Keep raw captures, source identifiers and calibration out of public issues.
[Third-party notices](THIRD_PARTY_NOTICES.md) preserve dependency obligations;
the repository does not grant a manufacturer or dataset license.
