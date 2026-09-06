# Phase 3 source decisions

Accessed 2026-09-05. Dates/versions below describe sources, not this instrument's
qualification. Sources were read with a bounded browser search; no datasets,
weights or private assets were uploaded/downloaded. [Earlier source register](archive/PHASE2_SOURCES.md)
retains the initial investigation. Source descriptions are deliberately scoped.

| Source / version or date | Adopted decision and evidence level | Not adopted / applicability limit |
|---|---|---|
| [HyperSpy linked ROI maps](https://hyperspy.org/hyperspy-doc/current/auto_examples/region_of_interest/map_signal.html), current 2.4 docs | Official example supports linked image/ROI/signal interaction; adopt interaction concept | No GPL source copied or HyperSpy dependency added |
| [SPy graphics](https://www.spectralpython.net/graphics.html), page 0.21, independent test reader installed 0.24 | Distinguish band index from wavelength and image display from spectrum | Page version is not proof of current API equivalence; no driver claims |
| [SpecimINSIGHT](https://www.specim.com/products/speciminsight/), current product page, publication date unstated | Commercial reference for image/region/spectral task organization | No reusable source, no HinaLea compatibility inference |
| [OpenHSI](https://openhsi.github.io/openhsi/), getting-started docs; cited 2022 paper, Apache-2.0 library | Explicit simulator and calibration/capture/processing separation | Pushbroom slit/grating acquisition is not this FP device's control implementation |
| [pyqtgraph FillBetweenItem](https://pyqtgraph.readthedocs.io/en/pyqtgraph-0.14.0/api_reference/graphicsItems/fillbetweenitem.html), pinned 0.14.0; installed source API checked | Spatial SD ribbons and shared computed plot values | No development-document API copied without checking installed signatures |
| [Matplotlib colormaps](https://matplotlib.org/stable/users/explain/colors/colormaps.html), installed 3.11.1 | Sequential ordered values; diverging maps around meaningful zero/one; editable vector figure text | No rainbow/default aesthetic used to imply quantitative differences |
| [Qt StandardPaths](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QStandardPaths.html), PySide6 6.10.3 runtime | Per-user config and Documents default workspace | CWD and installation tree do not own experiments |
| [Python 3.11 resources](https://docs.python.org/3.11/library/importlib.resources.html) and [packaging assets](https://packaging.python.org/en/latest/guides/using-manifest-in/) | Package-data + files/as_file lifetime; test the actual wheel | Latest Python docs alone were not used as a 3.11 API guarantee |
| [Hyperspectral Imaging primer](https://arxiv.org/html/2508.08107v1), 2025 v1 | Author full text: retain acquisition/calibration/geometry/environment metadata and reproducibility distinctions | General methodology is not a service manual or device-specific calibration |
| [Normalization study](https://pmc.ncbi.nlm.nih.gov/articles/PMC11763101/), Biosensors 2025, DOI 10.3390/bios15010020; published 4 Jan 2025 | Author article text retrieved in indexed PMC search: 4250 VNIR measurements require FP reconstruction; preserve amplitude alongside explicit normalized branch | Results depend on spectral content/noise/conditions; no claim L2 universally correct or transfer of 4250 settings to this unknown body. MDPI direct fetch failed and direct PMC open returned a browser challenge |
| [HyperVision paper](https://arxiv.org/abs/2605.17286), v3 28 Aug 2026; [author repository](https://github.com/lronkitty/HyperVision), release note 2 Jul 2026 | Future ground-based candidate only; inspected README pipeline with wavelength input, GSD and dataset-dependent [0,255] scaling | No license file found in visible repository listing; weight/code rights unresolved. No inference/training or reported performance reproduced; no invented wavelengths passed to a model |
| [CorkHSI author code](https://github.com/industoai/CorkHSI-Hyperspectral-Anomaly-Detection-in-Corks) and [dataset card](https://huggingface.co/datasets/industoai/CorkHSI), ICPR2026 material; exact upload date not established | Candidate for future domain-specific comparison; card says SPECIM FX17, 224 NIR channels with dark/white references; code/data CC BY-NC 4.0 | Not the current camera/domain; exact sample wavelength array must be inspected before reuse. Do not transfer normalization or performance. Dataset viewer reported an error; card is not a local evaluation. No 19.7 GB download |
| [FP field calibration US11867615B2](https://patents.google.com/patent/US11867615B2/en), grant publication 9 Jan 2024 | Read description: selected etalon gaps, field measurements and stored full calibration contribute to a reconstruction matrix | Mechanism evidence, not a controller command grammar, calibration file or proof of this hardware's implementation |
| [WO2026015900A1](https://patents.google.com/patent/WO2026015900A1/en), 2026 identifier | Body retrieval failed twice (internal tool error); retained as an unresolved bibliographic lead | No technical conclusion or free-run support claim from its title |
| [Balluff USB3 Vision troubleshooting](https://assets.balluff.com/documents/DRF_957356_AA_000/Troubleshooting_Windows_USB3VisionDeviceIsNotShownOrCannotBeUsed.html), page date unstated; installed runtime 3.7.2 | Official setup/error reference; distinguish OS driver from runtime and communication | No new reinstall/reset or assumption that a current SDK page describes every existing firmware feature |
| [PyInstaller usage](https://pyinstaller.org/en/stable/usage.html), 6.22.2 | One onedir ZIP, explicit resources/metadata, preserved dependency notices | No second installer or claim of clean-PC validation |
| [Qt for Python licenses](https://doc.qt.io/qtforpython-6/licenses.html), current official docs; installed metadata checked | Preserve actual dependency license texts and identify Qt/module/source obligations | Original-code license decision is separate; copying notices alone does not complete public release review |
| [GitHub licensing](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository), current official docs | Public visibility does not grant a general code reuse license; owner deferred selection | No LICENSE or public Release created; source remains on review branch |

## FP asset gap

The existing bounded scanner reports and installed-text search were inspected;
no new specific backup/vendor folder was supplied. They contain imaging-runtime
assets, not a verified control session/recipe/state acknowledgement or a complete
response/reconstruction matrix. No binary was executed as an inferred API and
no serial command was sent. Evidence is absence of a lead in the documented
scope, not proof of absence across all storage.

The next useful asset is a matching legacy control application/SDK session with
state acknowledgement and a device-matched calibration/reconstruction manifest.
H2 could first record acknowledged states with wavelength null. H3 requires
sourced and independently checked spectral mapping; H4 then validates references.
