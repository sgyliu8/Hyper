# Third-party notices and distribution boundary

HyperLab 0.3.0 is a research preview. The owner has **not selected an original-code
license**. No new LICENSE file or public release is authorized by this notice.
Public repository visibility is not a reuse or redistribution license. The
local wheel and desktop ZIP are evaluation artifacts pending ownership,
licensing and maintainer review.

The build uses these separately licensed dependencies. Versions below are the
2026-09-05 local build environment; BUILD.json in each desktop artifact records
the actual versions. Wheel resolution may differ within pyproject.toml bounds.

| Component | Version | Upstream license / attribution |
|---|---|---|
| Python | 3.11 | PSF license and bundled component notices |
| NumPy | 2.4.6 | BSD-3-Clause and included component licenses (including bundled numerical libraries) |
| Matplotlib | 3.11.1 | Matplotlib license; included font and other notices |
| Pillow | 12.3.0 | MIT-CMU and bundled imaging-library notices |
| PySide6 / Qt / Shiboken | 6.10.3 | LGPL-3.0 / GPL / commercial alternatives; module and third-party terms apply separately |
| pyqtgraph | 0.14.0 | MIT |
| psutil | 7.2.2 | BSD-3-Clause |
| Harvester (optional acquisition) | 1.4.3 | Apache-2.0 |
| GenICam (Harvester dependency) | 1.6.0 | GenICam license and included component notices; retained unmodified |
| contourpy, cycler, kiwisolver, pyparsing, python-dateutil, six, packaging, fonttools, typing_extensions | Recorded in BUILD.json | Their installed distribution license texts are retained in the desktop package |
| PyInstaller build tool / bootloader | 6.22.2 | GPL with bootloader distribution exception; not a license for HyperLab |

The onedir layout preserves shared libraries so that applicable replacement and
debugging rights are not obstructed. Do not remove the `_internal/licenses`
directory or the notices shipped with dependency metadata. Qt's source and
additional component attributions must remain available for a public release:
[Qt licensing](https://doc.qt.io/qt-6/licensing.html),
[Qt for Python notices](https://doc.qt.io/qtforpython-6/licenses.html),
[Qt 6.10.3 source archive](https://download.qt.io/archive/qt/6.10/6.10.3/single/),
[PySide source](https://code.qt.io/cgit/pyside/pyside-setup.git/).
The release checklist includes verifying the final binary's actual Qt modules
and complete corresponding source/notice obligations. Copying license texts alone
does not close that checklist.

**Not bundled:** Balluff/MATRIX VISION CTI, vendor DLLs or drivers, HinaLea/TruTag
software, calibration, acquired frames, private identifiers or user workspaces.
Those assets retain their owners' terms. The GenICam Python package is distinct
from a manufacturer CTI and cannot connect a device without a prepared runtime.

HyperSpy, OpenHSI, SPy graphics, SpecimINSIGHT, HyperVision and CorkHSI were
references, not code imported into the product. SPy 0.24 is an optional developer
test reader only. No model weights or external datasets are included.
