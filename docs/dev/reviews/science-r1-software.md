# Scientific roadmap review: reviewer 3, round 1

Date: 2026-09-06. Reviewer role: scientific software, reproducibility and English
workflow. Baseline inspected: `7ab867b2946035a162254f1d63cdc4d156b52e47`, branch
`feature/scientific-workbench-portable-v3`. The only pre-existing untracked file
observed at entry was `docs/dev/SCIENCE_ROADMAP_REVIEW.md`; it was preserved.

This is an independent AI engineering review, not human peer review or an
exhaustive systematic literature review. The owner identified thermal paint,
coating/material differences and defect detection as the actual use cases. I
read the current rules, handoff, architecture, Phase 3 review, scientific review
protocol, analysis gates/core/products, cube I/O, plotting, experiment comparison
and workbench state/control code. I did not operate the UI, start a camera
session, download datasets/models, run external notebooks or edit production
code. Public-source observations below were accessed on 2026-09-06.

## Recommendation

Keep the current image/map/paired-chart layout and approved palette. Add a small
set of auditable operations around that layout: richer ROI distributions and
counts, explicit spectral preprocessing, pairwise comparisons, bounded spectral
features, reference/background comparison and repeatability. Give each operation
one result definition used by the UI, numeric export and publication figure.
Defer automatic temperature or defect decisions until specimen-level reference
data and independent evaluation exist. A longer algorithm menu alone would not
provide scientific completeness.

The necessary sequence is: establish the data meaning and quality; select the
regions and specimen identity; compute a stated transformation; compare with a
compatible reference; inspect numerical maps and distributions; export an exact
recipe with its source identity and limitations. External documented spectral
cubes can exercise the spectral branch while HinaLea FP scanning/reconstruction
remains unavailable. Camera RGB and Bayer remain their own descriptive branches.

## Primary examples and transferable ideas

The table records examples, not recommendations to install another full stack.
Repository popularity is not a validation criterion. No performance claim from
an external example is adopted as HyperLab accuracy.

| Source and evidence type | What was inspected and can be reused conceptually | Limitation for this instrument/use case |
|---|---|---|
| [Spectral Python algorithms](https://www.spectralpython.net/algorithms.html), original software documentation | PCA covariance/components, SAM against reference means, RX background Mahalanobis scores and band-response resampling examples. Retain numerical scores, fit population, rejected features and map limits. | Examples include training-image classification and assumed Gaussian/FWHM responses. Neither provides held-out coating accuracy or measured HinaLea response. RX thresholds need assumptions and separate validation. |
| [Spectral Python file I/O](https://www.spectralpython.net/fileio.html), original documentation | Explicit ENVI access and memory-mapped array processing. This supports retaining HyperLab's current bounded-memory I/O instead of loading an entire cube for every action. | A file that opens correctly has not thereby gained physical wavelength, radiance or reflectance validity. |
| [hylite](https://github.com/hifexplo/hylite), original repository | Spectral libraries, imagery and derived minimum-wavelength maps share analysis/visualization concepts. Reference-library alignment and feature maps are directly relevant to materials. | Geological/illumination workflows are not thermal-paint calibration. Do not silently copy response or illumination assumptions. |
| [napari-sediment](https://github.com/guiwitz/napari-sediment), original repository | A staged workflow exposes import, white/dark correction, masks, dimensionality reduction, representative spectra and absorption maps. | Its domain indices and endmembers are sediment-specific. A new Napari/PyTorch application would add dependencies without solving the current Qt workflow. |
| [napari-sediment spectral indices](https://guiwitz.github.io/napari-sediment/Spectral_indices.html), original tutorial | User-selected spectral intervals produce index maps and spatial ROI profiles. This is a useful interaction pattern for coating features. | An interval selected because it looks different is exploratory; it must be frozen before validation on held-out specimens. |
| [MASSIMAL code](https://github.com/mh-skjelvareid/massimal) and [dataset documentation](https://github.com/mh-skjelvareid/massimal-dataset), original project | Dataset documentation ties measurements to time/location/modality and distinguishes radiance, downwelling irradiance and annotations. Transfer the explicit campaign/specimen/session grouping pattern. | Coastal UAV data and spatial annotation groups do not validate laboratory coating measurements. No data were imported. |
| [Cuvis.Ai paper](https://arxiv.org/abs/2411.11324), author preprint listing WHISPERS 2024; [current original code](https://github.com/cubert-hyperspectral/cuvis-ai) | The paper motivates explicit operation dependencies and serialized processing. The current repository separates framework, schemas, domain nodes and data loaders. Adopt a compact saved recipe and fit/apply distinction. | The current repository is not identical to the 2024 paper version. A generic graph editor, gRPC service or plugin ecosystem is unnecessary for this bounded local task. |
| [Cubert lentils dataset card](https://huggingface.co/datasets/cubert-gmbh/XMR_Demo_Industrial_Foreign_Object_Detection_Lentils), vendor-authored demonstration | Card describes a 69-frame session with white/dark measurements, annotations and a notebook comparing three channel-selection pipelines. Separate input, continuous score, threshold and ground-truth overlays. | Food foreign objects, Cubert response and selected-channel pretrained models do not validate paint defects or HinaLea. The single demonstrated sequence is not evidence of independent specimen generalization. SDK/weights were not installed. |
| [Living Optics fruit card](https://huggingface.co/datasets/LivingOptics/hyperspectral-fruit), vendor-authored example | Code extracts spectra by annotation masks and shows individual spectra plus aggregate envelopes. It distinguishes sparse spectral samples from RGB and lists a separate validation set. | Sparse sampling requires recorded sample locations. Its example may create a linear wavelength axis from endpoints; HyperLab must require an actual supported wavelength vector instead. Data access/license and SDK differ. |
| [Liang et al., sampling strategy](https://arxiv.org/abs/1605.05829), primary methods paper/preprint | Explains bias from spatial overlap when spectral-spatial models use random pixels from the same image for training/testing. | Lab extension is an inference: split by physical coupon/batch/session and by spatial support where relevant; many pixels from one coupon are not many independently treated coupons. |
| [scikit-learn leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html) and [GroupKFold](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupKFold.html), original library documentation | Split before learning preprocessing; fit only on training data and reuse transforms. Groups are held out together. | Library mechanics do not decide the correct experimental unit. Group IDs must come from physical acquisition and specimen history, with class support checked per split. |
| [Li et al., HAD100](https://arxiv.org/abs/2303.18001), author preprint with TGRS 2023 reference | The paper describes a multi-scene hyperspectral anomaly benchmark and generalization between scenes/sensors. Use scene-level evaluation as a research example. | Remote-sensing anomaly targets are not industrial coating defects. No pretrained results, numerical benchmark or model weights were reproduced here. |

A search also found *HSIFoodInspection: A Comprehensive Hyperspectral Dataset for
Industrial Food Anomaly Detection* in the [CVPR 2026 workshop PDF](https://openaccess.thecvf.com/content/CVPR2026W/MTF/papers/Zhang_HSIFoodInspection_A_Comprehensive_Hyperspectral_Dataset_for_Industrial_Food_Anomaly_Detection_CVPRW_2026_paper.pdf).
The full-text fetch returned HTTP 403; it is a follow-up lead, not evidence for
this review's mathematical or implementation recommendations.

Queries covered original software examples, `hyperspectral` Hub dataset cards,
industrial anomaly detection, and spectral-spatial evaluation leakage on arXiv.
Search snippets and public example labels were not treated as physical truth.
No verified thermal-paint temperature dataset was identified in this software
review; the physical reviewer owns the dedicated thermal-paint literature search.

## Code-derived findings

1. **The semantic foundation should be retained.** `io/cube.py` keeps HWK axes,
   wavelength units/order, FWHM, global bad bands and pixel validity. It rejects a
   time sequence as a spectral cube. `analysis/capabilities.py` distinguishes
   color channels, state vectors and documented wavelength axes. RGB/Bayer must
   not gain spectral derivative, band-depth or temperature controls merely
   because new methods become available. A `raw_scan` declaration currently
   admits state-vector diagnostics without requiring actual FP state records;
   preserve the distinction between mathematical index-vector analysis and H2
   acquisition evidence in any new method gate.
2. **ROI summaries are currently narrow.** `roi_statistics` supplies mean,
   population spatial SD (`ddof=0`) and disjoint invalid/ignored/saturated counts.
   `roi_comparison` adds 64 shared-bin density curves for a single plane. There
   are no per-feature median, quartiles, MAD, explicit valid-fraction plots or
   between-ROI comparison tables. These additions have immediate value on the
   already acquired RGB/Bayer data and external spectral cubes.
3. **Exploratory PCA is not a prediction model.** `analysis/core.py:pca` fits a
   seeded sample from the current full image, then transforms its valid pixels.
   This is a reasonable descriptive view. A later classifier cannot reuse this
   full-scene fit and claim held-out prediction. `analysis/products.py` already
   exports components/mean/scale/variance; extend their identity and fit-scope
   evidence rather than introducing another PCA implementation.
4. **A shared computation/plot contract already exists.** `plots.py:PlotSpec`
   drives Qt and the Matplotlib PNG/SVG/PDF bundle with numeric CSV/NPY artifacts.
   Source identity, units, invalid masks, semantic map centers, normalization and
   spatial-SD wording are present. New methods should extend this contract. The
   compact `source_identity` does not include a file-content digest; an immutable
   experiment analysis record should identify source bytes, algorithm/version,
   recipe, selected features/ROIs, fit scope and output artifact hashes. Hash once
   on explicit analysis/export, not at live preview frequency.
5. **Specimen context is largely free text.** Calibration UI has scene label and
   conditions; `experiments.py` checks acquisition settings and correctly states
   that identical geometry is not verified registration. Thermal paint needs
   explicit coupon/material/coating batch, treatment identity, exposure duration,
   acquisition session and replicate unit to support later comparisons. These
   are versioned experiment annotations referencing immutable source identity;
   adding or correcting them must not rewrite the raw array or original camera
   evidence sidecar. Unknown values should remain unknown. A field called temperature must also state
   whether it is a setpoint, independent measured reference or model estimate.
6. **Current repeatability is descriptive.** Sequence statistics retain source
   frame identity, counts and settings checks. The all-recorded-ROI plot averages
   valid channel means for color; this is documented, but it can hide a chromatic
   change relevant to paint. Offer per-channel traces or selected spectral
   feature traces rather than only their arithmetic average.
7. **The Analysis panel has overlapping responsibilities.** The code combines
   ROI geometry, quality, comparison/export, PCA/SAM, pair indices, map options,
   multiple exports and a synthetic loader. Its plot-mode selector is built in
   Acquisition, while PCA controls in Analysis change it. This is a code-derived
   workflow problem; actual clipping/visibility was not measured by this reviewer.
8. **Reference correction has an API but no operation form.** The Calibration
   panel explains external correction in text. A compact form can expose the
   existing guarded API and explain concrete incompatibilities. It must not
   suggest that a dark/white image recovers the missing FP response.

The coordinator independently reported native UI observations at 2048 x 1104:
long mixed Analysis scrolling, acquisition actions and an empty metrics row
occupying offline space, clipped quality-policy text, and a PCA-loadings selector
conflicting with displayed ROI curves. These are coordinator-observed findings,
not a claim that reviewer 3 operated or visually inspected that window.

## Prioritized implementation proposal

| Priority | Bounded addition | Meaning and required gate | Verification |
|---|---|---|---|
| P0 | ROI summary table and distribution mode | Count/valid fraction, mean, spatial SD, median, Q25/Q75, MAD per enabled feature; valid pixel population stated. No pixel-based CI. | Independent arrays with outliers, missing/saturated/ignored samples; exact counts; raw hashes unchanged. |
| P0 | Compact analysis workflow | Keep ROIs and Compare primary; one method selector, contextual parameters and Run for map/feature operations. One chart selector in Analysis, one Export menu. | Selected mode matches plotted result; keyboard operation; no clipped primary controls at 125/150%; no camera connection on analysis/restore. |
| P0 | Operation recipe/evidence | Exact source/ROI/features/masks, parameters, units, version, fit scope and outputs. | Reload/recompute equals saved numbers; source replacement detected; cancellation/stale async results cannot overwrite current analysis. |
| P1 | Pairwise ROI table/curves | Signed mean difference and RMSE preserve signal units; angle preserves angular units; normalized comparison is a separate branch. Use common finite features and report their indices. | Identical, scaled, offset, orthogonal, zero-norm and disjoint-valid-feature examples; no inferred wavelengths or material labels. |
| P1 | Explicit spectral preprocessing and interval features | Wavelength-aware smoothing/derivatives, continuum/band-depth or interval area only when the method's wavelength/order/units and signal prerequisites are met. Raw curve remains accessible. | Known polynomial/absorption examples; reject unsupported spacing or gaps; state boundary policy and derivative/integral units. |
| P1 | Background anomaly score | A simple documented regularized RX/Mahalanobis baseline with explicit normal-background ROI and fit scope; score map/histogram and background covariance diagnostics. | Independent quadratic-form calculation; singular/constant backgrounds; finite conditioning; anomalies excluded from fit when specified; no automatic probability/defect claim. |
| P1 | Metadata and repeatability comparison | Explicit coupon/batch/treatment/session/replicate fields; all persisted frame traces per channel/feature; distinct within-frame spatial and across-frame temporal summaries. | Missing metadata remain unknown; mismatched axes/settings reject pooling; repeated pixels do not increment independent specimen count. |
| P2 | Reference library, calibrated thermal-paint model and supervised defect evaluation | Matched wavelength/response/units; independent specimen labels and normal/defect definition; fit/apply separation; grouped train/validation/test and reject/unknown outcome. | Group disjointness, train-only fitting, held-out operating threshold and complete confusion/PR/ROC metrics with unit-level denominators. Physical temperature/defect performance remains NOT_TESTED without real references. |

P1 order should be frozen after cross-review: robust ROI statistics, spectral
features and contextual UI can be implemented before any model-training system.
An exploratory RX score is useful but not mandatory to replace a validated,
interpretable ROI contrast when the sample set is small. Do not add a generic
plugin server, graph editor, cloud inference or large model dependency for these
operations.

## Proposed English workflow

**Data / Acquisition:** open an existing measurement or connect normally; show
source kind, specimen name and current acquisition state. Hide inactive camera
rate/detail rows offline. During streaming retain always-accessible Stop even
when the analysis tab is selected. Saving the displayed raw frame, freezing the
display and stopping acquisition must remain distinct.

**Analysis:** image with named ROIs; compact ROI table; Compare; a method selector
and only the relevant parameters; an Analysis chart-view selector; raw/map and
bottom amplitude/shape or distribution panels. Advanced display limits, mask
details and fit diagnostics can be expanded. Do not repeat long capability
reasons in every visible row; display the selected method's concise reason and
provide full details on demand.

**References / Experiment:** registered sources and specimen/treatment context;
settings compatibility and repeatability; the guarded external reflectance form.
Move long FP/hardware setup descriptions to Diagnostics/About while leaving one
short truthful capability status visible.

**Export:** a single entry offering Numeric results + recipe, Publication figure
and Display image, with descriptions of what each contains. Preserve all raw
arrays and failures. Keep examples available under Help/Examples, with synthetic
origin clearly shown, rather than among day-to-day analysis actions.

## Objections for round 2

- Do not rename a spatial SD or a quantile envelope as measurement uncertainty
  or a confidence interval. A valid pixel count is not an independent coupon
  count. The mathematical reviewer should define any later repeated-measures
  inference and denominator explicitly.
- Do not add spectral interpolation that fills invalid wavelength gaps or
  extrapolates a reference library without a recorded resampling policy and
  spectral response assumptions. Missing FWHM is not permission to invent the
  instrument response.
- Do not infer temperature from color differences, derivatives, SAM, PCA or RX.
  The physical reviewer must distinguish irreversible exposure-history paint
  from reversible/current-temperature sensing and require the relevant
  calibration and nuisance-factor controls.
- Do not copy visually attractive external demo normalizers into quantitative
  analysis. Per-image min/max changes can remove amplitude information and
  change sample comparability; keep display stretch separate.
- Do not fit PCA, feature selection, reference means, standardization or anomaly
  thresholds on held-out data and then report defect accuracy. Whole-image
  exploratory fitting must remain explicitly descriptive.
- A polished false-color map must identify the underlying numeric quantity and
  invalid pixels. A thresholded score is a candidate region, not a confirmed
  defect. Preserve all false positives, failures and rejected/unscorable cases.

Round 1 disposition: proceed to cross-review with the proposal above. No consensus
or implementation acceptance is claimed until rounds 2 and 3 have been recorded.
