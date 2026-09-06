"""Frame-contiguous, bounded raw time recording with a durable valid prefix."""
from collections import OrderedDict
from io import BytesIO
import json
import os
from pathlib import Path
import queue
import shutil
import sys
import threading
import time
import numpy as np
from .session import utc_now
from hyperlab.profiling import StageTimings


def atomic_json(path, metadata):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(metadata, allow_nan=False))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _write_all(stream, data):
    view = memoryview(data).cast('B')
    while view:
        written = stream.write(view)
        if not written:
            raise OSError('Incomplete sequence write')
        view = view[written:]


class SequenceWriter:
    """Store THW/THWC frames; metadata completion advances after data flush."""

    def __init__(self, directory, frame_shape, dtype, max_frames, *, metadata=None, checkpoint_frames=8,
                 mapped=True):
        if len(frame_shape) not in (2, 3) or min(frame_shape) <= 0 or max_frames <= 0:
            raise ValueError("Positive frame shape and finite frame count required")
        if checkpoint_frames < 1:
            raise ValueError("Positive checkpoint frame count required")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.path = self.directory / "sequence.npy"
        self.frame_shape, self.dtype = tuple(frame_shape), np.dtype(dtype)
        self.storage_shape = (int(max_frames), *frame_shape)
        self.array = self._stream = None
        try:
            if mapped:
                self.array = np.lib.format.open_memmap(self.path, mode="w+", dtype=dtype,
                                                       shape=self.storage_shape)
            else:
                # RAM bursts persist only after acquisition, without another full mapped stack.
                self._stream = self.path.open('x+b', buffering=0)
                header = BytesIO()
                np.lib.format.write_array_header_2_0(header, {
                    'descr': np.lib.format.dtype_to_descr(self.dtype), 'fortran_order': False,
                    'shape': self.storage_shape})
                _write_all(self._stream, header.getbuffer())
                self._data_offset = self._stream.tell()
                self._stream.truncate(self._data_offset + int(np.prod(self.storage_shape)) * self.dtype.itemsize)
        except Exception:
            self._close_storage()
            raise
        self.meta = dict(metadata or {})
        self.meta.update(schema_version=3, data_level="raw_sequence", axis_kind="time",
                         axis_order="THWC" if len(frame_shape) == 3 else "THW",
                         axis_names=["time", "y", "x"] + (["color_channel"] if len(frame_shape) == 3 else []),
                         shape=list(self.storage_shape), dtype=self.dtype.str, units="DN", wavelengths=None,
                         expected_frames=int(max_frames), frame_count=0, frames=[], completed=False,
                         partial=True, status="partial", save_reopen_verified=False,
                         started_at=utc_now(), time_units="s",
                         time_origin="first acquired frame host_monotonic_ns; device clock is separate",
                         calibration_source=None, processing_steps=[])
        self.count = 0
        self.data_fsynced_count = self.durable_count = 0
        self.readable_count = None
        self._finalizing = False
        self.checkpoint_frames = checkpoint_frames
        self.closed = False
        self._samples = OrderedDict()
        self.timings = StageTimings()
        try:
            self._publish(0)
        except Exception:
            self._close_storage()
            self.closed = True
            raise

    def _close_storage(self):
        if self.array is not None:
            self.array._mmap.close()
        if self._stream is not None:
            self._stream.close()

    def _counts(self, durable):
        admitted = max(self.count, self.meta.get('accepted_frames', 0))
        self.meta.update(frame_count=durable, copied_frames=self.count,
                         data_fsynced_frames=self.data_fsynced_count, durable_frames=durable,
                         readable_frames=self.readable_count, admitted_frames=admitted,
                         accepted_frames=admitted, written_frames=durable,
                         unpersisted_frames=admitted - durable,
                         explicitly_failed_frames=admitted - durable if self._finalizing else 0,
                         accounting='admitted = durable + unpersisted; written means confirmed durable prefix')

    def _publish(self, durable):
        self._counts(durable)
        try:
            atomic_json(self.path.with_suffix('.npy.json'), self.meta)
        except Exception:
            # This sole writer's atomic_json replaces only after fsync of the candidate.
            # Exact candidate readback resolves a lost publication acknowledgement;
            # merely reading some pixels does not establish their durability.
            try:
                if self.path.with_suffix('.npy.json').read_text(encoding='utf-8') == json.dumps(self.meta, allow_nan=False):
                    self.durable_count = durable
                    self.meta['publication_ack_recovered'] = True
            except (OSError, ValueError):
                pass
            self._counts(self.durable_count)
            raise
        self.durable_count = durable

    def append(self, frame, record):
        if self.closed:
            raise RuntimeError("Writer already closed")
        if self.count >= self.storage_shape[0]:
            raise ValueError("More frames than declared")
        if frame.shape != self.frame_shape or frame.dtype != self.dtype:
            raise ValueError("Frame shape/dtype changed; refusing conversion")
        if record.get("valid") is not True:
            raise ValueError("Only valid acquired frames can enter the prefix")
        json.dumps(record, allow_nan=False)
        index = self.count
        with self.timings.measure('writer_array_copy'):
            if self.array is not None:
                self.array[index] = frame
            else:
                if not frame.flags.c_contiguous:
                    raise ValueError('Sequential burst persistence requires contiguous owned frames')
                self._stream.seek(self._data_offset + index * frame.nbytes)
                _write_all(self._stream, frame)
        self.meta["frames"].append(dict(record, index=index))
        self.count += 1
        # Keep only first/middle/latest samples, not another copy of the recording.
        if index in (0, self.storage_shape[0] // 2):
            self._samples[index] = np.array(frame, copy=True)
        if -1 in self._samples:
            del self._samples[-1]
        self._samples[-1] = np.array(frame, copy=True)
        if self.count % self.checkpoint_frames == 0:
            self.checkpoint()

    def checkpoint(self):
        if self.closed:
            return
        with self.timings.measure('writer_checkpoint'):
            with self.timings.measure('writer_data_flush'):
                (self.array if self.array is not None else self._stream).flush()
            # fsync the file as well as the mapped pages before publishing completion.
            with self.timings.measure('writer_data_fsync'):
                with self.path.open("r+b") as stream:
                    os.fsync(stream.fileno())
            self.data_fsynced_count = self.count
            with self.timings.measure('writer_manifest_publish'):
                self._publish(self.count)

    def finish(self, *, error=None, stopped=False, duration_complete=False):
        if self.closed:
            return self.path
        primary = None
        self._finalizing = True
        try:
            self.checkpoint()
            check = np.load(self.path, mmap_mode="r", allow_pickle=False)
            try:
                verified = []
                for index, samples in self._samples.items():
                    index = self.count - 1 if index == -1 else index
                    if not np.array_equal(check[index], samples, equal_nan=True):
                        raise RuntimeError(f"Sequence reopen content mismatch at frame {index}")
                    verified.append(index)
                self.meta["reopen_verified_indices"] = sorted(set(verified))
                self.readable_count = self.durable_count
            finally:
                check._mmap.close()
            complete = (self.count == self.meta["expected_frames"] or duration_complete) and self.count > 0 and not error and not stopped
            self.meta.update(completed=bool(complete), partial=not complete,
                             status="completed" if complete else "partial", error=error,
                             stopped=bool(stopped), ended_at=utc_now(), save_reopen_verified=True)
            self._publish(self.durable_count)
        except Exception as exc:
            primary = exc
            self.meta.update(completed=False, partial=True, status='partial', error=error or str(exc) or type(exc).__name__,
                             finalization_error=str(exc) or type(exc).__name__, ended_at=utc_now())
            try:
                self._publish(self.data_fsynced_count)
            except Exception as receipt_error:
                exc.add_note(f"Final receipt also failed: {receipt_error}")
        finally:
            try:
                self._close_storage()
            except Exception as close_error:
                self.meta.update(completed=False, partial=True, status='partial',
                                 error=error or str(close_error) or type(close_error).__name__,
                                 finalization_error=str(close_error) or type(close_error).__name__)
                try:
                    self._publish(self.data_fsynced_count)
                except Exception as receipt_error:
                    close_error.add_note(f'Close failure receipt also failed: {receipt_error}')
                if primary is None:
                    primary = close_error
                else:
                    primary.add_note(f"Mapping close also failed: {close_error}")
            self.closed = True
            self._samples.clear()
        if primary is not None:
            raise primary
        return self.path

    close = finish

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        try:
            self.finish(error=str(error) if error else None)
        except Exception as cleanup_error:
            if error is None:
                raise
            error.add_note(f"Sequence finalization also failed: {cleanup_error}")


class Sequence:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_dir():
            self.path /= "sequence.npy"
        self.metadata = json.loads(self.path.with_suffix(".npy.json").read_text(encoding="utf-8"))
        if self.metadata.get("data_level") != "raw_sequence" or self.metadata.get("axis_order") not in ("THW", "THWC"):
            raise ValueError("Expected a raw time sequence, not a spectral cube")
        count = self.metadata.get("frame_count")
        records = self.metadata.get("frames")
        if type(count) is not int or count < 0 or not isinstance(records, list) or len(records) < count:
            raise ValueError("Invalid durable sequence prefix or frame-record denominator")
        if any(not isinstance(record, dict) or record.get("valid") is not True for record in records[:count]):
            raise ValueError("Sequence valid prefix contains an invalid frame record")
        self._mapping = np.load(self.path, mmap_mode="r", allow_pickle=False)
        try:
            expected_ndim = 4 if self.metadata["axis_order"] == "THWC" else 3
            if self._mapping.ndim != expected_ndim or count > self._mapping.shape[0]:
                raise ValueError("Invalid sequence dimensions or durable prefix")
            if list(self._mapping.shape) != self.metadata.get("shape") or self._mapping.dtype.str != self.metadata.get("dtype"):
                raise ValueError("Sequence manifest shape/dtype differs from the NPY header")
            if self.metadata.get("expected_frames") != self._mapping.shape[0]:
                raise ValueError("Sequence expected-frame denominator differs from storage")
            self.array = self._mapping[:count]
        except Exception:
            self._mapping._mmap.close()
            raise
        self.data = self.array

    @property
    def frame_count(self):
        return len(self.array)

    def frame(self, index):
        from .frame import Frame
        if not -self.frame_count <= index < self.frame_count:
            raise IndexError(index)
        index %= self.frame_count
        record = self.metadata["frames"][index]
        metadata = dict(self.metadata)
        metadata.update(record)
        container_fields = ("frames", "frame_count", "expected_frames", "completed", "partial", "status",
                            "started_at", "ended_at", "error", "stopped", "time_units", "time_origin",
                            "save_reopen_verified", "reopen_verified_indices", "writer_error", "writer_overflow",
                            "writer_capacity", "accepted_frames", "acquired_frames", "recording_budget_bytes",
                            "free_bytes_at_start", "duration_limit_s", "failed_frame", "failed_transport_payload",
                            "failed_payload_write_error", "finalization_error", "index")
        container_fields += ('recording_mode', 'admitted_frames', 'copied_frames', 'data_fsynced_frames',
                             'durable_frames', 'readable_frames', 'written_frames', 'explicitly_failed_frames',
                             'unpersisted_frames', 'rejected_frames', 'memory_preflight', 'retry_of',
                             'previous_persistence_error', 'publication_ack_recovered', 'accounting',
                             'recording_started_at', 'admission_ended_at', 'persistence_started_at',
                             'camera_stop_attempt')
        for key in container_fields:
            metadata.pop(key, None)
        provenance = dict(self.metadata)
        records = provenance.pop("frames")
        # The immutable manifest retains the complete record list. Repeating it
        # in every selected Frame would make a T-frame summary retain O(T²)
        # metadata, although only one frame's pixels are accumulated at a time.
        source = {"path": str(self.path), "manifest_path": str(self.path.with_suffix(".npy.json")),
                  "time_index": index, "axis_kind": "time", "frame_records_count": len(records),
                  "container_provenance": provenance}
        metadata.update(data_level="raw_frame", display_mode="REPLAY",
                        axis_order="HWC" if self.array.ndim == 4 else "HW",
                        axis_kind="color_channel" if self.array.ndim == 4 else "sensor_plane",
                        axis_names=["y", "x"] + (["color_channel"] if self.array.ndim == 4 else []),
                        sequence_source=source,
                        shape=list(self.array.shape[1:]))
        # Independent ownership: the Frame stays valid after this file is closed.
        return Frame(np.array(self.array[index], copy=True), metadata)

    def close(self):
        self._mapping._mmap.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def load_sequence(path):
    return Sequence(path)


def _metadata_bytes(value):
    """Conservative owned metadata size; immutable shared values may be counted twice."""
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        size += sum(_metadata_bytes(key) + _metadata_bytes(item) for key, item in value.items())
    elif isinstance(value, (list, tuple)):
        size += sum(_metadata_bytes(item) for item in value)
    return size


def available_memory_bytes():
    import psutil
    return int(psutil.virtual_memory().available)


def recording_preflight(directory, frame, max_frames, *, recording_mode='continuous'):
    """Read-only budget preview; the recorder repeats this check before admission."""
    if int(max_frames) != max_frames or max_frames < 1:
        raise ValueError('Positive integer max_frames required')
    if recording_mode not in ('continuous', 'ram_burst'):
        raise ValueError('Choose continuous or ram_burst recording mode')
    destination = Path(directory)
    if destination.exists():
        raise FileExistsError(destination)
    ancestor = destination.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    expected = int(frame.data.nbytes * max_frames)
    free = shutil.disk_usage(ancestor).free
    metadata_limit = max(65536, 2 * _metadata_bytes(frame.metadata))
    memory = None
    reasons = []
    if expected + 256 * 1024**2 > free:
        reasons.append('Recording budget exceeds available space with 256 MiB reserve')
    if recording_mode == 'ram_burst':
        memory = {'available_bytes': available_memory_bytes(), 'raw_bytes': expected,
                  'metadata_budget_bytes': int(max_frames) * metadata_limit,
                  'runtime_buffer_headroom_bytes': 16 * frame.data.nbytes,
                  'filesystem_cache_headroom_bytes': 8 * frame.data.nbytes,
                  'reserve_bytes': 1024**3,
                  'interpretation': 'Admission budget, including reserved OS/cache capacity; not a guarantee against later pressure'}
        memory['required_bytes'] = sum(value for key, value in memory.items()
                                       if key.endswith('_bytes') and key != 'available_bytes')
        if memory['required_bytes'] > memory['available_bytes']:
            reasons.append(f"RAM burst requires {memory['required_bytes']} available bytes including reserve; "
                           f"available {memory['available_bytes']}; requested frame count unchanged")
    return {'allowed': not reasons, 'reasons': reasons, 'max_frames': int(max_frames),
            'recording_mode': recording_mode, 'expected_bytes': expected, 'free_bytes_at_start': free,
            'disk_reserve_bytes': 256 * 1024**2, 'memory_preflight': memory,
            'metadata_limit_bytes': metadata_limit}


class SequenceRecorder:
    """Independent bounded writer; overflow is an explicit partial recording."""

    def __init__(self, directory, frame, max_frames, *, duration_s=None, capacity=8, writer_factory=SequenceWriter,
                 recording_mode='continuous'):
        if int(max_frames) != max_frames or max_frames < 1:
            raise ValueError("Positive integer max_frames required")
        if duration_s is not None and (not np.isfinite(duration_s) or duration_s <= 0):
            raise ValueError("Recording duration must be positive and finite")
        if capacity < 1:
            raise ValueError("Positive bounded writer capacity required")
        if recording_mode not in ('continuous', 'ram_burst'):
            raise ValueError('Choose continuous or ram_burst recording mode')
        self.recording_mode = recording_mode
        self.directory = Path(directory)
        budget = recording_preflight(directory, frame, max_frames, recording_mode=recording_mode)
        self.expected_bytes, self.free_bytes = budget['expected_bytes'], budget['free_bytes_at_start']
        self.memory_preflight, self._metadata_limit = budget['memory_preflight'], budget['metadata_limit_bytes']
        if not budget['allowed']:
            error = MemoryError if any(reason.startswith('RAM') for reason in budget['reasons']) else OSError
            raise error('; '.join(budget['reasons']))
        self.queue = queue.Queue(maxsize=int(max_frames) if recording_mode == 'ram_burst' else capacity)
        self.max_frames = int(max_frames)
        self.duration_s = duration_s
        self.started = time.monotonic()
        self.started_utc = utc_now()
        self._persistence_started = None
        self.ended = None
        self.stop_event = threading.Event()
        self._admission = threading.RLock()
        self.done = threading.Event()
        self.error = None
        self.capture_error = None
        self.previous_error = None
        self.retry_of = None
        self.phase = 'acquiring'
        self.acquisition_ended = None
        self.admission_ended_utc = None
        self.camera_stop_attempt = None
        self.stopped = False
        self.duration_complete = False
        self.accepted = 0
        self.written = 0
        self.overflow = 0
        self.explicitly_failed = 0
        self.abandoned = 0
        self.discarded_ram_frames = 0
        self.rejected = 0
        self.failed_frame = None
        self.failed_payload = None
        self.path = self.directory / "sequence.npy"
        self.metadata = None
        self.readable = None
        self.reopen_error = None
        self._writer = None
        self._ram_frames = []
        self._ram_owners = set()
        self._ram_identities = set()
        self._retained_bytes = 0
        self._persistence_ready = threading.Event()
        self._writer_timings = None
        self._frame = frame
        self._shape, self._dtype = frame.data.shape, frame.data.dtype
        self._source_metadata = dict(frame.metadata)
        self._template = (frame.data.shape, frame.data.dtype.str,
                          *(frame.metadata.get(key) for key in
                            ('session_id', 'stream_epoch', 'pixel_format', 'readback_settings')))
        self._writer_factory = writer_factory
        self.thread = threading.Thread(target=self._run, name="HyperLabWriter", daemon=True)
        self.thread.start()

    def _end_admission(self):
        if not self.stop_event.is_set():
            self.acquisition_ended = time.monotonic()
            self.admission_ended_utc = utc_now()
        self.stop_event.set()

    def _duration(self):
        if not self.stop_event.is_set() and self.duration_s is not None and time.monotonic() - self.started >= self.duration_s:
            self.duration_complete = True
            self._end_admission()

    def release_persistence(self, *, error=None):
        """Camera owner calls only after its normal stop/restore attempt, including failure."""
        with self._admission:
            self.stop(error=error)
            self.camera_stop_attempt = {'status': 'FAILED' if error else 'RETURNED',
                                        'error': error, 'host_utc': utc_now()}
            self._persistence_ready.set()

    @property
    def needs_camera_stop(self):
        return self.recording_mode == 'ram_burst' and self.stop_event.is_set() and not self._persistence_ready.is_set()

    def submit(self, frame):
        # Admission and finalization share one lock. A true return guarantees
        # either a persisted frame or an explicitly failed accepted frame.
        with self._admission:
            if self.stop_event.is_set():
                self.rejected += 1
                return False
            self._duration()
            if self.stop_event.is_set():
                self.rejected += 1
                return False
            template = (frame.data.shape, frame.data.dtype.str,
                        *(frame.metadata.get(key) for key in
                          ('session_id', 'stream_epoch', 'pixel_format', 'readback_settings')))
            if template != self._template:
                self.rejected += 1
                self.failed_frame = dict(frame.metadata)
                self.stop(error='Frame shape, format, stream or setting epoch changed during recording')
                return False
            metadata_bytes = 0
            if self.recording_mode == 'ram_burst':
                metadata_bytes = _metadata_bytes(frame.metadata)
                if (frame.metadata.get('valid') is not True or not frame.data.flags.owndata or
                        frame.data.base is not None or frame.data.flags.writeable or isinstance(frame.data, np.memmap) or
                        not frame.data.flags.c_contiguous or id(frame.data) in self._ram_owners or
                        frame.identity in self._ram_identities or
                        metadata_bytes > self._metadata_limit):
                    self.rejected += 1
                    self.failed_frame = dict(frame.metadata)
                    self.stop(error='RAM burst requires distinct read-only owning arrays without base views and bounded metadata')
                    return False
            try:
                if self.recording_mode == 'ram_burst':
                    self._ram_frames.append(frame)
                    self._ram_owners.add(id(frame.data))
                    self._ram_identities.add(frame.identity)
                self.queue.put_nowait(frame)
                if self.recording_mode == 'ram_burst':
                    self._retained_bytes += frame.data.nbytes + metadata_bytes
            except MemoryError:
                if self._ram_frames and self._ram_frames[-1] is frame:
                    self._ram_frames.pop()
                    self._ram_owners.discard(id(frame.data))
                    self._ram_identities.discard(frame.identity)
                self.rejected += 1
                self.stop(error='MemoryError during frame admission; retained prefix requires persistence')
                return False
            except queue.Full:
                self.overflow += 1
                self.rejected += 1
                self.failed_frame = dict(frame.metadata)
                self.error = "Writer queue overflow: recording stopped; no silent frame drop"
                self._end_admission()
                return False
            self.accepted += 1
            if self.accepted >= self.max_frames:
                self._end_admission()
            return True

    def stop(self, *, error=None):
        with self._admission:
            self.stopped = self.accepted < self.max_frames and not self.duration_complete
            self.error = self.error or error
            self.capture_error = self.capture_error or error
            self._end_admission()

    def retry(self, directory):
        with self._admission:
            if not self.status()['can_retry']:
                raise ValueError('Wait for a failed persistence attempt before retrying retained frames')
            destination = Path(directory)
            if destination.exists():
                raise FileExistsError(destination)
            ancestor = destination.parent
            while not ancestor.exists():
                ancestor = ancestor.parent
            if shutil.disk_usage(ancestor).free < self.expected_bytes + 256 * 1024**2:
                raise OSError('Retry exceeds available disk space with reserve')
            headroom = self.memory_preflight['required_bytes'] - self.expected_bytes - self.memory_preflight['metadata_budget_bytes']
            if available_memory_bytes() < headroom:
                raise MemoryError('Retry requires available persistence/cache headroom; retained frames remain in RAM')
            self.retry_of, self.previous_error = str(self.path), self.error
            self.directory, self.path = destination, destination / 'sequence.npy'
            self.error = self.capture_error
            self._writer = self.metadata = None
            self.readable = None
            self.reopen_error = None
            self.written = self.explicitly_failed = 0
            self.ended = None
            self._persistence_started = None
            self.queue = queue.Queue(maxsize=self.max_frames)
            for frame in self._ram_frames:
                self.queue.put_nowait(frame)
            self.phase = 'persisting'
            self.thread = threading.Thread(target=self._run, name='HyperLabWriter', daemon=True)
            self.thread.start()

    def abandon(self):
        with self._admission:
            if not self.status()['can_abandon']:
                raise ValueError('Retained frames can be abandoned only after persistence has stopped')
            receipt = self.directory / 'abandonment.json'
            payload = dict(self.status(), abandonment_confirmed=True, abandoned_at=utc_now(),
                           abandoned_frames=self.accepted - self.written,
                           discarded_ram_frames=len(self._ram_frames),
                           retained_frame_records=[dict(frame.metadata) for frame in self._ram_frames])
            self.directory.mkdir(parents=True, exist_ok=True)
            atomic_json(receipt, payload)  # Failure retains every buffer and allows a different retry path.
            self.abandoned = self.accepted - self.written
            self.discarded_ram_frames = len(self._ram_frames)
            self._release_ram()
            self.phase = 'abandoned'
            self.done.set()
            return receipt

    def _release_ram(self):
        self._ram_frames.clear()
        self._ram_owners.clear()
        self._ram_identities.clear()
        self._retained_bytes = 0

    def _run(self):
        writer = None
        try:
            metadata = dict(self._source_metadata)
            if self.recording_mode == 'ram_burst':
                self._frame = None
                while not self.stop_event.wait(.05):
                    with self._admission:
                        self._duration()
                self.phase = 'waiting_for_camera_stop'
                self._persistence_ready.wait()
                self.phase = 'persisting'
            # Per-frame identity is kept under frames; no single-frame identity applies to T.
            for key in ("sequence", "frame_id", "device_timestamp_ns", "host_monotonic_ns", "host_utc", "host_received_at"):
                metadata.pop(key, None)
            metadata.update(recording_budget_bytes=self.expected_bytes, free_bytes_at_start=self.free_bytes,
                            writer_capacity=self.queue.maxsize, duration_limit_s=self.duration_s,
                            acquisition_source=metadata.get("acquisition_source") or metadata.get("data_source") or "UNKNOWN",
                            display_mode="REPLAY", recording_mode=self.recording_mode, accepted_frames=self.accepted,
                            memory_preflight=self.memory_preflight, retry_of=self.retry_of,
                            previous_persistence_error=self.previous_error,
                            recording_started_at=self.started_utc, admission_ended_at=self.admission_ended_utc,
                            persistence_started_at=utc_now(), camera_stop_attempt=self.camera_stop_attempt)
            self._persistence_started = time.monotonic()
            options = {'mapped': False} if self.recording_mode == 'ram_burst' else {}
            writer = self._writer_factory(self.directory, self._shape, self._dtype,
                                          self.max_frames, metadata=metadata, **options)
            self._writer = writer
            self._writer_timings = getattr(writer, 'timings', None)
            self._frame = None
            while True:
                with self._admission:
                    self._duration()
                    if self.stop_event.is_set():
                        self.phase = 'persisting'
                    if self.stop_event.is_set() and self.queue.empty():
                        break
                try:
                    frame = self.queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                try:
                    writer.meta.update(accepted_frames=self.accepted, rejected_frames=self.rejected)
                    writer.append(frame.data, dict(frame.metadata))
                finally:
                    self.queue.task_done()
                    self.written = writer.durable_count
        except Exception as exc:
            self.error = self.error or str(exc) or type(exc).__name__
        finally:
            with self._admission:
                self._end_admission()
            if writer is not None:
                writer.meta.update(writer_overflow=self.overflow, accepted_frames=self.accepted,
                                   rejected_frames=self.rejected,
                                   failed_frame=self.failed_frame, writer_error=self.error)
                if self.failed_payload is not None:
                    try:
                        failed_path = self.directory / "failed_transport_payload.bin"
                        with failed_path.open("xb") as stream:
                            stream.write(self.failed_payload)
                        writer.meta["failed_transport_payload"] = failed_path.name
                    except Exception as exc:
                        writer.meta["failed_payload_write_error"] = str(exc)
                        self.error = self.error or str(exc)
                try:
                    writer.finish(error=self.error, stopped=self.stopped, duration_complete=self.duration_complete)
                except Exception as exc:
                    self.error = self.error or str(exc) or type(exc).__name__
                self.written = writer.durable_count
                self.metadata = dict(writer.meta)
            try:
                with load_sequence(self.path) as saved:
                    self.readable = saved.frame_count
            except (OSError, ValueError, KeyError) as exc:
                self.readable = None
                self.reopen_error = str(exc)
                self.error = self.error or f'Recording reopen unavailable: {exc}'
            # Release any unsaved arrays after a disk failure; their absence is explicit.
            while not self.queue.empty():
                self.queue.get_nowait()
                self.queue.task_done()
            self._frame = None
            self.failed_payload = None
            self.ended = time.monotonic()
            self.explicitly_failed = self.accepted - self.written
            if self.recording_mode == 'ram_burst' and self.accepted and (
                    self.accepted > self.written or self.readable != self.accepted or
                    not (self.metadata or {}).get('save_reopen_verified')):
                self.phase = 'recovery_required'
            else:
                self._release_ram()
                self.phase = 'complete' if (self.metadata or {}).get('completed') and not self.error else 'partial'
                self.done.set()

    def status(self):
        metadata = self.metadata or {}
        writer = self._writer
        durable = writer.durable_count if writer else self.written
        fsynced = writer.data_fsynced_count if writer else 0
        copied = writer.count if writer else 0
        can_recover = self.phase == 'recovery_required' and not self.thread.is_alive()
        return {"path": str(self.path), "accepted_frames": self.accepted, "written_frames": durable,
                "explicitly_failed_frames": self.explicitly_failed, "rejected_frames": self.rejected,
                "max_frames": self.max_frames, "queue_length": self.queue.qsize(), "queue_capacity": self.queue.maxsize,
                "overflow": self.overflow, "error": self.error, "done": self.done.is_set(),
                "completed": metadata.get("completed", False) and not self.error,
                "partial": metadata.get("partial", True) or bool(self.error),
                "save_reopen_verified": metadata.get("save_reopen_verified", False) and self.readable is not None,
                "writer_fps": durable / max((self.ended or time.monotonic()) - (self._persistence_started or self.started), 0.001),
                "expected_bytes": self.expected_bytes, "free_bytes_at_start": self.free_bytes,
                "stage_timings": self._writer_timings.snapshot() if self._writer_timings else None,
                'recording_mode': self.recording_mode, 'phase': self.phase, 'admitted_frames': self.accepted,
                'copied_frames': copied, 'data_fsynced_frames': fsynced, 'durable_frames': durable,
                'readable_frames': self.readable, 'unpersisted_frames': self.accepted - durable,
                'volatile_frames': self.accepted - durable if self._ram_frames else 0,
                'retained_frames': len(self._ram_frames), 'retained_bytes': self._retained_bytes,
                'can_retry': can_recover, 'can_abandon': can_recover, 'abandoned_frames': self.abandoned,
                'discarded_ram_frames': self.discarded_ram_frames,
                'reopen_error': self.reopen_error,
                'memory_preflight': self.memory_preflight, 'retry_of': self.retry_of,
                'previous_persistence_error': self.previous_error}
