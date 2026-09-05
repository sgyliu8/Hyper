# Persistent imaging session and recording contract

`CameraSession` owns one exact-serial Harvester image acquirer on one Python
worker. Connecting opens the verified installed producer and device; preview
does not call the legacy single-frame function repeatedly. There is no synthetic
fallback and no serial/FP control path in this backend.

## API and thread ownership

```python
from hyperlab.acquisition import CameraSession, load_sequence

camera = CameraSession(cti_path, verified_serial,
                       settings={"PixelFormat": "BayerRG12", "ExposureTime": 50000,
                                 "Gain": 0}, mode="measurement")
camera.connect().result(timeout=30)  # CLI only; UI polls state instead of waiting.
camera.start_preview().result(timeout=5)
# A UI timer calls latest_frame(), retains that Frame, and calls mark_displayed().
displayed = camera.latest_frame()
# Only after a valid frame has arrived:
camera.snapshot(new_snapshot_directory, frame=displayed)
camera.start_recording(new_recording_directory, max_frames=300, duration_s=30)
# Recording automatically stops at the first finite limit; preview continues.
camera.stop_recording()
camera.stop_preview()               # Cooperative real stream stop and restore.
camera.close(wait=True, timeout=10)  # False means cleanup is still in progress.

with load_sequence(recording_path) as sequence:
    first = sequence.frame(0)       # Owned Frame; valid after the mapping closes.
```

Commands return `Future` objects. Native device calls, feature readback and
stream control occur only on the camera owner thread. UI code must not call
`Future.result()` or synchronous waits. `poll_events()` delivers small
state/snapshot/recording/error dictionaries, never an array per queued signal.
`latest_frame()` returns one owned read-only array with frozen evidence.
`snapshot(..., frame=displayed)` saves that exact frame identity, even if the
camera has advanced. Two snapshot tasks may be pending; excess requests report
busy. Disk work uses a separate worker, outside the transport buffer lifetime.

States are disconnected, connecting, ready, streaming, recording, stopping and
error. `stop_recording()` keeps preview running. `stop_preview()` stops the actual
sensor stream, attempts each restoration independently, and returns to ready
only after successful cleanup. It can return to ready while a bounded recording
queue finishes writing; the separate recording status describes this drain.
Closing first stops/releases the device, then waits for accepted disk work.
`closed`, `worker_alive`, `camera_released` and `snapshot_pending` are separately
reported. A failed release is never reported as successful merely because the
worker exited. `set_settings()` accepts changes only in ready/disconnected state.

Diagnostic export enumerates cached node names/types, but reads value/access/
range only for the explicitly reviewed `FEATURES` set. A real Phase 2 attempt
to inspect arbitrary vendor node values blocked in native code before streaming;
that attempt is failed evidence, not a successful stop. Unknown vendor nodes now
carry `NOT_READ_UNREVIEWED_NODE`; XML export is explicitly `NOT_EXPORTED`.
Reading an arbitrary node must not be assumed harmless merely because no write
or command is requested. GenApi 1.6 typed interfaces use `interface.node.name`;
categories do not directly expose `.name`.

## Buffer, settings and evidence

Installed Harvester **1.4.3** source was checked in this environment. Its normal
`fetch(timeout=...)` branch has a finite timeout; its background acquisition
branch waits on a queue differently. This implementation explicitly starts with
`run_as_thread=False` and fetches with a 0.25 s timeout. Each fetched buffer is
returned exactly once after copying raw samples and necessary identity/chunk
metadata. No image processing, PNG writing, statistics or disk I/O occurs while
the buffer is borrowed. The timeout bounds the fetch polling interval, not every
possible native driver operation; real stop latency remains a hardware result.

The producer path, Windows AMD64 architecture and OEM signature are checked once
per connection. Normal preview does not repeat verification, enumeration or CTI
loading. The adapter checks exact serial, USB3 Vision transport and the investigated
mvBlueFOX3 model family. Runtime and device identifiers are private evidence.

Measurement mode freezes available exposure/gain/white-balance auto controls to
Off and disables available gamma/LUT enable nodes. Free-run uses documented
AcquisitionMode=Continuous and TriggerMode=Off. Explicit format/exposure/gain
requests are checked against currently available enumeration/range/increment
and verified by readback. Unsupported nodes are not invented. Preview mode
preserves existing automatic/processing controls, except an explicit exposure or
gain request disables its corresponding auto control. It does not promise an
auto feature absent from the camera. Other fixed processing values, including
black level and selected Gain/Balance/Trigger contexts, are retained as evidence.
No selectors, UserSets, EEPROM, firmware or calibration are written.

Requested settings, session readback and chunk settings are distinct. Chunk
values are read only when ChunkModeActive was already enabled; missing per-frame
exposure is left missing. A session readback is not relabelled as a per-frame
measurement. Manual values are restored while automatic features remain off;
automatic features are restored last. Stop, each restore, destroy, Harvester
reset and DLL-directory close have independent attempted/succeeded/error receipts.
The first acquisition error remains primary if a cleanup or receipt write fails.

Frame identity is `session_id:sequence`; device frame IDs may restart after a
stream restart. Device timestamp, host monotonic receipt time and host UTC remain
separate. Frame age is host-monotonic-now minus host-monotonic-receipt, not an
uncalibrated device-to-host transport latency. Capture/display FPS, preview
replacement count, device frame-ID gaps, writer queue/overflow/FPS and stop
latency are separate metrics. A device frame-ID gap during a lossless recording
stops it explicitly as partial; preview may continue.

## File layout and crash/stop behavior

Raw time recordings use C-contiguous **THW** or **THWC** NPY memmaps, accompanied by
versioned `sequence.npy.json`. Time is never squeezed into a wavelength/state
axis. `Sequence.data` exposes only the durable `frame_count` prefix;
`Sequence.frame(index)` returns an independent raw frame with temporal origin
under `sequence_source`. `raw_scan` continues to use the `ScanWriter` API with
logical input shape HWK, but stores physical **KHW** so each sensor frame is
contiguous. `load_cube` exposes its logical HWK transpose view without copying
the entire recording. Both writers have finish/close/context-manager support.

Recording requires a positive finite frame limit, optional positive duration,
and sufficient free space for the declared array plus a 256 MiB reserve. The
default queue is eight owned frames; no unbounded array signals or queues are
used. On overflow, disk failure, device error or early stop, the receipt records
an explicit partial result and preserves its successful prefix. A failed/omitted
frame is recorded separately, never inserted as invented data. A recording's
frame list also preserves its denominator and original frame identities.

Data are flushed before atomic checkpoints advance completion, normally every
eight frames and on finish. The checkpoint JSON itself is flushed and fsynced
before replace. A crash can leave additional uncommitted samples in the allocated
tail; readers intentionally expose only the last published prefix. The final
reopen checks pixel contents of first/middle/latest retained samples for time
records and first/last for scans. Successful snapshots compare every raw sample.
Mappings are closed explicitly so Windows can rename/reopen the files afterward.
The sequence reader rejects inconsistent shape, dtype, time-axis dimensions or
frame-record denominators and closes the mapping even on rejection. Finalization
failures remain partial; scans distinguish acquired frames from the last durable
prefix. Cancelled snapshot futures release their bounded queue slots, and completed
writer FPS uses a fixed end time rather than falling while the user reviews data.

Saved acquisition provenance remains LIVE (or explicit SYNTHETIC fixture), while
opening a saved file has display_mode=REPLAY. Raw Bayer uint16 container width,
declared effective format bits and any documented ADC readback are different
fields. The delivered PFNC Bayer tag supplies the documented delivered CFA
pattern; actual sensor offsets and ReverseX/ReverseY readback are preserved
separately, so display/statistics do not apply offsets twice.

## Verification and sources

Offline contract tests inject start, fetch, incomplete-buffer, decode/size,
write, requeue, stop, restore and destroy failures. They check original-error
preservation, independent cleanup, no access after buffer return, one owner,
state/restart/close, exact snapshots, queue overflow, disk failure, time-axis
semantics, partial prefixes, device frame gaps and file-handle release.
These tests establish software behavior; they are not hardware acceptance.
Root HANDOFF and private hardware receipts hold current physical-test outcomes.

- [Harvester tutorial](https://harvesters.readthedocs.io/en/latest/TUTORIAL.html):
  read 2026-09-05; documented lifecycle/ownership, corroborated against installed
  1.4.3 source. The web page identifies a development documentation build, so it
  was not treated as a reason to install a development package.
- [Balluff mvBlueFOX3-2024 sensor/timing documentation](https://assets.balluff.com/documents/DRF_957345_AA_000/mvBC_subsubsection_sensors_CMOS_models_2024.html):
  read 2026-09-05; matching sensor-family reference. The current device node map
  controls actual available features and bounds. It establishes no HinaLea FP
  command protocol or unit-specific spectral calibration.
