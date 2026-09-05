# Phase 2 review corrections

The review was reproduced against the working source, not inferred from a test
count. The pre-change analysis/I/O/color subset passed 30 tests. Seven new
scientific regression cases failed before their fixes; three independent ENVI
interoperability cases then failed before the ENVI corrections. Tests use small
synthetic fixtures. They do not validate a physical wavelength response.

## R1 — Shared features for PCA and angle

A declared globally bad band previously made every pixel fail the complete-vector
check. `feature_selection` now produces original feature indices, exclusions with
reasons, selected wavelengths/units and effective input dimension. PCA fitting,
mean/scale/components, transformation and the reference vector use that same
selection. A reference remains a K-vector in the original source order; missing
values in excluded bands are permitted, but a missing selected reference value or
zero selected norm is rejected. Local masks still invalidate an entire selected
vector, preventing angles between different feature spaces.

Regression coverage includes one/all bad bands, local invalid pixels, missing
selected reference values, zero reference, insufficient samples and one-dimensional
angle rejection. PCA scores/components and feature mapping survive numeric export.

## R2 — Reflectance metadata follows the product domain

The `sample=dark=10`, `white=100`, `dark_white=10`, raw-ignore=0 fixture previously
lost every legitimate zero in ROI statistics. Product metadata now removes raw
ignore, saturation, pixel format, ADC/container descriptors and old ENVI fields
from the active product domain. All four source metadata records remain under
`source_provenance`. The output validity mask governs inclusion. Negative and
above-one values remain unchanged and counted separately as quality observations.
No clipping or physical attribution is added.

## R3 — Shared analysis capabilities

`hyperlab.analysis.capabilities(cube)` is the single semantic gate consumed by the
analysis API and available to GUI/CLI. RGB permits named-channel ROI/CSV/histogram
and numeric export, with spectral/state PCA and angle disabled. A Bayer frame
remains one sensor plane and permits DN/CFA/quality/temporal statistics. Multi-state
raw scans support state-vector analysis. External spectral cubes do not depend on
this camera's H3 status: an ordered wavelength axis with recognized units and an
explicit source enables their offline vector operations. Declared file wavelengths
remain `declared`, not experimentally verified.

Unknown, duplicated or nonmonotonic wavelength axes remain viewable in their
original order and disable spectral analysis with a concrete reason. They are
never silently sorted. Time sequences are explicitly rejected by `load_cube`;
the acquisition sequence reader preserves T separately.

## R4 — Acquisition cleanup

The GenTL adapter now checks/copies a borrowed buffer and extracts necessary
frame evidence before returning it once. Saving, previews and statistics occur
after return. Stop, each setting restoration, destroy, producer reset and
DLL-directory cleanup are independently attempted; cleanup failures remain
secondary to the original acquisition error. Format/manual values are restored
before automatic features. Measurement mode freezes supported BlackLevelAuto
without attempting writes to absent/unavailable nodes.

`test_camera_session.py` injects start/fetch/incomplete/decode/payload-size/
write/stop/restore/destroy failures, verifies one return and no access to a
returned buffer, and checks independent cleanup plus primary-error retention.
Additional regressions cover restoration order, optional automatic controls,
typed INode names and refusal to read unreviewed node values/access state. Fake
persistent sessions cover restart, exact snapshot, bounded recording, device-gap
partial output, cooperative close and cancelled snapshot slot release.

These are offline lifecycle contracts, not proof that every native operation
returns or that this firmware releases successfully under every fault. The
actual broad-node native hang and later camera-open failure remain separate
failed receipts in [TEST_PLAN](TEST_PLAN.md) and [HANDOFF](../HANDOFF.md).

## R5 — ENVI interoperability

ENVI headers now export applicable `bbl`, `data ignore value`, `data units`,
`wavelength`, `wavelength units` and `fwhm`. An arbitrary HW/HWK mask is not `bbl`.
When a pixel mask is present, an external floating export encodes invalid samples
as NaN while preserving an exact mask sidecar and leaving the source array intact.
This is an explicit export representation, not a lossless duplicate of invalid raw
sample values; use NPY plus its mask sidecar for that. uint32 and float64 values
retain float64 precision. int64/uint64 samples beyond exact float64 range are
rejected for masked floating export rather than silently rounded.

Unit aliases normalize to nm or um while retaining the original spelling. Header
and sidecar axes are compared after conversion to a common length unit. Equivalent
0.5 um / 500 nm declarations agree; 500 um / 500 nm conflicts raise an error.
The header's physical axis stays authoritative. Sidecar units do not silently
override it. FWHM shares the wavelength unit.

The external export test uses Spectral Python 0.24, `envi.open` and `open_memmap`,
not HyperLab's reader. It checks bbl, ignore, units, FWHM, NaN mask encoding and
exact high-precision valid values. SPy's ordinary `load()` converts to float32,
so it is deliberately unsuitable for checking uint32/float64 preservation.
See the [SPy file I/O documentation](https://www.spectralpython.net/fileio.html)
(accessed 2026-09-05). NPY/NPZ remain lossless array/mask representations.

## R6 — Quality policies and arithmetic

ROI, PCA, angle, difference and ratio share explicit `diagnostic` and
`quantitative` policies. Both reject nonfinite, declared-invalid and ignored
samples. Diagnostic statistics retain known saturation; quantitative statistics
exclude it. Counts report total, valid, saturated, ignored and invalid per channel.
Invalid/ignored/saturated categories are disjoint; diagnostic valid includes
saturated values. Unknown saturation remains unknown, never a guessed container
maximum. Thresholds use explicit sample saturation/bit metadata, not ADC claims.

12/16-bit integer DN uses float32 where exact; uint32 and float64 use float64.
Values outside exact int64/uint64-to-float64 range require explicit rescaling
before analysis. Regression fixtures retain a +1 difference at 2**24 and a
1e-10 float64 difference, previously both rounded to zero. ROI uses float64
population spatial SD; it is not temporal noise or temperature uncertainty.

CFA statistics preserve R/G1/G2/B phase identity across odd ROI/crop offsets and
flips. Explicit sensor-origin patterns use offsets/flips; a pattern inferred from
the documented PFNC delivered format describes the delivered top-left instead.
No CFA phase is relabelled a wavelength band. `TemporalStatistics` accumulates
owned equal-shape frames with Welford mean/variance and bounded memory; its output
retains a time interpretation and no wavelength axis.

## R7 — Derived output scale and handles

Reflectance estimates output plus mask bytes. Above the default 256 MiB budget,
the caller must supply a new `.npy` output target. Targeted processing writes
float/mask memmaps in chunks. An atomic JSON checkpoint advances only after both
files flush; completion is set only after all pixels persist. Exceptions preserve
the valid completed prefix. Masks exclude unprocessed storage. `Cube.close()` and
context-manager exit release mapped handles, including KHW transpose views.

A forced one-byte budget test exercises the mapped path without allocating a
large fixture. An injected mid-computation failure reopens the durable prefix,
rejects unwritten pixels through the mask and verifies Windows file-handle release.
This checks the memory-storage design, not a multi-gigabyte throughput benchmark.
The separate acquisition writer owns frame-contiguous recording and scan storage.

## R8 and R9 — Integration evidence

Native acceptance additionally found and corrected sidebar clipping, a derived
pane initially collapsing to a sliver, linked aspect constraints causing range
feedback, display-derived saturation hiding saturated Bayer samples, and stale
axis/source selections. Tests cover these observed paths. ROI precision and
saved-file comparison were added; actual English workflows and evidence are in
HANDOFF. Saving a selected time frame now moves T counts/completion into container
provenance. Loading a copy makes source_file the file actually opened while
retaining earlier declarations, so reference registration selects that copy.

The default English Qt workbench connects through the persistent CameraSession,
requests actual stream stop/release and uses persistent image items and draggable
ROIs. Freeze display, stop recording and stop acquisition are separate actions.
GUI exposure/gain controls are implemented, validated against live capabilities
and reported with actual readback. The old Tk interface is explicit legacy only.

Qt regressions cover raw ROI coordinates through view/band changes, semantic
capability gates, exact retained-frame saving after stop, readback/status schema,
sequence time-axis replay, busy-reader and new-source handle lifecycle, release
before window close, sidebar fit, partial recording status and linked map-view
range feedback. Scientific UI tests cover common-feature normalized curves,
zero-norm rejection, amplitude/shape export provenance and capturing the SAM
reference ROI before background execution. CLI tests use the same capability
gates and verify numeric feature-mapping exports. Sequence tests independently
cover durable prefixes, overflow/disk failure, manifest validation, budget
rejection, source provenance and reopened content.

The final integrated suite count, revision, actual Windows interaction artifacts
and hosted CI status are recorded in [HANDOFF](../HANDOFF.md); intermediate subset
counts are not the final acceptance result. The current-turn Tk baseline really
captured one single frame, whereas three later persistent-session benchmark
attempts produced no frames. Continuous preview, real bounded recording and
hardware stop latency remain blocked pending USB reconnection. Tests, desktop
observations, literature and H0–H4 retain separate evidence/status.

## Reproduce the scientific subset

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_analysis.py tests/test_analysis_review.py tests/test_io.py tests/test_io_review.py tests/test_color_frame.py tests/test_capabilities.py -q
```

The two narrow baseline expectation updates document intentional semantics:
ENVI masked exports contain NaN, and recognized wavelength-unit spelling is
normalized with the original retained. Baseline tests were not deleted to make
the regressions disappear.
