# HyperLab architecture — Phase 2

HyperLab 0.2 uses PySide6 6.10.3 and pyqtgraph 0.14.0 for its default local
workbench. `python -m hyperlab app` launches it; `app --legacy` explicitly opens
the earlier Tk/Matplotlib interface. The UI language is English. Neither startup
nor offline analysis implicitly opens a camera. No server, cloud service, model
weights or reconstruction SDK is required for the implemented workbench.

## Device boundary and session ownership

`probe.py` and `scripts/Probe-Devices.ps1` perform read-only Windows inventory.
`devices.py` selects the healthy, exact OEM imaging interface and persists a
private profile under `local/config/`. Inventory does not load CTI/DLLs, open
serial or stream. Bounded asset investigation is an explicit
`hyperlab.controller.diagnostics` operation, separate from Connect.

`adapters/gentl.py` validates the installed OEM producer location, x64 architecture
and signature, then selects the exact serial, model and U3V device.
`acquisition/camera.py` provides `CameraSession`: one worker thread creates,
configures, fetches from and releases that backend. Preview frames reuse the
producer and acquisition handle. Commands have a bounded queue; latest display
data has capacity one. A slow display replaces obsolete preview frames instead
of growing a backlog.

States are disconnected, connecting, ready, streaming, recording, stopping and
error. Stop/close requests use events observed between finite fetch calls. A
native vendor call that does not return cannot be cancelled by a Python event;
the Phase 2 node-read failure is recorded in [SCANNER_RECOVERY](SCANNER_RECOVERY.md).
Cleanup independently attempts stop, original-setting restoration, destruction
and producer reset. A cleanup exception does not erase the primary failure.

Pixel format, exposure and gain are validated against live nodes. Measurement
mode disables supported automatic/processing features needed for a controlled
raw measurement. Changes are transient and restored in dependency order. No
UserSet, EEPROM, firmware, permanent calibration or FP command is written.
Requested settings, session readback and per-frame chunk evidence remain
distinct; a session value is not proof of a setting in every frame.

The borrowed transport buffer exists only during validity checks, metadata
extraction and copying into an owned `Frame`. It is requeued once before saving,
plotting or analysis. `Frame` contains an immutable owned HW/HWC array, frozen
metadata and session/sequence identity. Snapshot saving receives the exact
displayed `Frame`; it does not fetch a replacement. Native single-frame capture
can also retain `transport_payload.bin`; every streaming frame does not promise
that optional byte artifact.

## Recording and data axes

| Product | Storage and meaning |
|---|---|
| `raw_frame` | HW sensor plane or HWC named camera color channels; no inferred wavelengths |
| `raw_sequence` | THW/THWC time series in `sequence.npy` and `sequence.npy.json`; time is not a spectral/state axis |
| `raw_scan` | Physical KHW storage with a logical HWK view, ordered optical state records and nullable wavelengths |
| `spectral_cube` | HWK logical cube with evidenced wavelength/reconstruction provenance |
| `reflectance_cube` | Matched references, units, invalid masks and stated relative/reference calibration |

`SequenceRecorder` has a bounded writer queue and separate writing thread.
Preview is not recorded by default. Before recording, frame/duration limits and
available disk space are checked. `SequenceWriter` exclusively creates a memmap,
flushes/fsyncs data before atomic manifest checkpoints, and exposes only the
durable frame prefix. Overflow, dropped device frames, disk errors and
interruption preserve partial data with its denominator and reason. Normal
completion reopens first/middle/last content. Windows mmap handles are explicitly
closed. Recording can stop while preview continues.

`acquisition/session.py` retains `ScanWriter` for ordered scan persistence; its
software fixture is SYNTHETIC. No real FP scanner is implemented. Time frames
cannot be relabelled as scan states. `io/cube.py` rejects a time-axis sequence as
a spectral `Cube`; sequence playback materializes one frame with frame-axis
metadata. NPY and ENVI remain memory mapped; NPZ is explicitly an in-memory load.

## Analysis and provenance

`analysis/capabilities.py` supplies common CLI/GUI admissibility rules. RGB
supports descriptive ROI statistics, not spectral SAM. One-plane Bayer supports
raw/CFA diagnostics, not fabricated multiband spectra. Derived CFA-cell RGB needs
known phase, offsets and flip state and never replaces raw samples. A supplied,
evidenced external spectral cube may be analysed while this instrument's H3 is
blocked.

PCA/SAM select common features after global bad-band exclusion, then apply pixel
completeness to that selection. Outputs record selected/rejected indices and
reasons. Diagnostic and quantitative quality policies are explicit. Saturation
comes from supported acquisition/metadata evidence, not the integer container
maximum. Precision preserves supported integer values or rejects unsafe
conversion. ROI exports retain amplitude; optional shape normalization is a
separate branch.

Reference correction checks settings, linearity and reference conditions,
propagates validity masks, and removes inherited DN/ignore metadata that would
mislabel a result. Large correction products require an output path and use
chunked, checkpointed memmaps. ENVI exchanges standard BBL, ignore value, units,
wavelength and FWHM fields; conflicting header/sidecar metadata is rejected.
Arbitrary pixel masks use invalid float values plus explicit mask/provenance
artifacts rather than pretending BBL represents a pixel mask.

`analysis/products.py` exports numeric maps, masks and source/operation metadata
as NPY/ENVI; display PNG is separate. `experiments.py` compares known settings and
computes bounded-memory temporal mean, SD, counts, saturation and drift. These
descriptive statistics do not establish illumination stability, material
identity, spectral accuracy or temperature.

## UI execution and limits

`ui/workbench.py` owns widgets and persistent row-major image items. Its timer
polls status/latest data; timer frequency is not camera FPS. File reads, analysis
and exports run in background work and return results on the GUI thread. Source
changes invalidate derived-product provenance. Stop acquisition, freeze display
and stop recording have separate meanings. Closing waits for the camera worker
and pending file work without blocking the Qt event loop. See [UI_SPEC](UI_SPEC.md).

There is no guessed serial protocol, trained model, spectral inverse solver or
temperature estimator behind an enabled control. Controller recovery, matching
reconstruction assets and physical reflectance validation remain separate gates.
Current acceptance and failures belong in [TEST_PLAN](TEST_PLAN.md) and the final
[HANDOFF](../HANDOFF.md), not an inferred claim from this architecture.
