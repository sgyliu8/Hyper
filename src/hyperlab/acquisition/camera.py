"""Persistent camera owner, latest-frame mailbox and separate bounded disk work."""
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import queue
import threading
import time
from uuid import uuid4
from .frame import Frame, save_frame
from .sequence import SequenceRecorder, atomic_json
from .session import utc_now
from hyperlab.profiling import StageTimings


class CameraSession:
    def __init__(self, cti, serial, *, settings=None, mode="measurement", backend_factory=None,
                 writer_capacity=8, recorder_factory=SequenceRecorder, fetch_timeout=0.25, phase_log=None):
        if not 0 < fetch_timeout <= 1:
            raise ValueError("Fetch timeout must be in (0,1] seconds")
        self.cti, self.serial = str(cti), str(serial)
        self.settings = dict(settings or {})
        self.mode = mode
        self._backend_factory = backend_factory
        self._recorder_factory = recorder_factory
        self.writer_capacity = writer_capacity
        self.fetch_timeout = fetch_timeout
        self._commands = queue.Queue(maxsize=32)
        self._events = deque(maxlen=64)
        self._lock = threading.RLock()
        self._state = "disconnected"
        self._error = None
        self._backend = None
        self._backend_timings = None
        self._latest = None
        self._display_identity = None
        self._stop_requested = threading.Event()
        self._close_requested = threading.Event()
        self._closed = threading.Event()
        self._camera_released = True
        self._recording = None
        self._recording_reported = False
        self._last_recording = None
        self._capture_times = deque(maxlen=120)
        self._display_times = deque(maxlen=120)
        self._sequence = 0
        self._captured = 0
        self._displayed = 0
        self._mailbox_replacement_events = 0
        self.timings = StageTimings()
        self._device_gaps = 0
        self._previous_device_id = None
        self._fetch_timeouts = 0
        self._last_received = None
        self._stream_started = None
        self.stream_epoch = 0
        self._stream_started_ns = None
        self._phases = deque(maxlen=200)
        self.phase_log = Path(phase_log) if phase_log else None
        self._last_stop_seconds = None
        self._stop_request_time = None
        self._capabilities = {}
        self._connection_metadata = {}
        self._cleanup = []
        self._snapshots = ThreadPoolExecutor(max_workers=1, thread_name_prefix="HyperLabSnapshot")
        self._snapshot_slots = threading.BoundedSemaphore(2)
        self._snapshot_pending = 0
        self.session_id = None
        self._worker = threading.Thread(target=self._run, name="HyperLabCameraOwner", daemon=True)
        self._worker.start()

    @property
    def state(self):
        with self._lock:
            return self._state

    @property
    def closed(self):
        return self._closed.is_set()

    def _emit(self, kind, **values):
        with self._lock:
            self._events.append(dict(kind=kind, host_utc=utc_now(), **values))

    def _set_state(self, state):
        with self._lock:
            self._state = state
        self._emit("state", state=state)

    def poll_events(self):
        with self._lock:
            result = list(self._events)
            self._events.clear()
        return result

    def _submit(self, operation, **values):
        if self._close_requested.is_set() or self.closed:
            raise RuntimeError("Camera session is closing or closed")
        future = Future()
        self._commands.put_nowait((operation, values, future))
        return future

    def connect(self):
        return self._submit("connect")

    def start_preview(self):
        return self._submit("start")

    def stop_preview(self):
        self._stop_request_time = time.monotonic()
        self._stop_requested.set()
        return self._submit("stop")

    def set_settings(self, settings, mode="measurement"):
        return self._submit("settings", settings=dict(settings), mode=mode)

    def start_recording(self, directory, max_frames, duration_s=None):
        return self._submit("record", directory=directory, max_frames=max_frames, duration_s=duration_s)

    def stop_recording(self):
        return self._submit("record_stop")

    def disconnect(self):
        self._stop_request_time = time.monotonic()
        self._stop_requested.set()
        return self._submit("disconnect")

    def close(self, wait=False, timeout=10):
        self._stop_request_time = time.monotonic()
        self._stop_requested.set()
        self._close_requested.set()
        if wait:
            self._worker.join(timeout)
        return self.closed

    def wait_for_state(self, states, timeout=10):
        states = {states} if isinstance(states, str) else set(states)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.state in states:
                return self.state
            time.sleep(0.01)
        raise TimeoutError(f"Camera state is {self.state}; expected {sorted(states)}")

    def latest_frame(self):
        with self._lock:
            return self._latest

    def mark_displayed(self, frame):
        with self._lock:
            if frame.identity != self._display_identity:
                self._display_identity = frame.identity
                self._displayed += 1
                self._display_times.append(time.monotonic())

    def snapshot(self, directory, *, frame):
        if self._close_requested.is_set():
            raise RuntimeError("Camera session is closing")
        if not isinstance(frame, Frame):
            raise ValueError("Snapshot requires the exact displayed Frame")
        if not self._snapshot_slots.acquire(blocking=False):
            raise RuntimeError("Two snapshots are already pending; wait for disk completion")
        identity = frame.identity
        with self._lock:
            self._snapshot_pending += 1
        def finished(future):
            with self._lock:
                self._snapshot_pending -= 1
            self._snapshot_slots.release()
            if future is not None and future.cancelled():
                self._emit("snapshot", identity=identity, succeeded=False, cancelled=True)
        def work():
            try:
                path = save_frame(directory, frame)
                self._emit("snapshot", path=str(path), identity=frame.identity, succeeded=True)
                return path
            except Exception as exc:
                self._emit("snapshot", identity=frame.identity, succeeded=False, error=str(exc))
                raise
        try:
            future = self._snapshots.submit(work)
        except Exception:
            finished(None)
            raise
        future.add_done_callback(finished)
        return future

    def export_diagnostics(self, directory):
        """Read-only node description export from the connected owner thread."""
        return self._submit("diagnostics", directory=directory)

    @staticmethod
    def _fps(times):
        cutoff = time.monotonic() - 2.0
        times = [value for value in times if value >= cutoff]
        if len(times) < 2:
            return 0.0
        return (len(times) - 1) / max(times[-1] - times[0], 1e-6)

    def status(self):
        with self._lock:
            current = self._latest
            age = ((time.monotonic_ns() - current.metadata["host_monotonic_ns"]) / 1e9) if current else None
            recording = self._recording.status() if self._recording else self._last_recording
            return {"state": self._state, "error": self._error, "session_id": self.session_id,
                    "stream_epoch": self.stream_epoch, "stream_started_ns": self._stream_started_ns,
                    "has_current_frame": current is not None and current.metadata.get('stream_epoch') == self.stream_epoch,
                    "phases": list(self._phases),
                    "closed": self.closed, "worker_alive": self._worker.is_alive(),
                    "camera_released": self._camera_released,
                    "capture_fps": self._fps(self._capture_times) if self._state in ("streaming", "recording") else 0,
                    "display_fps": self._fps(self._display_times) if self._state in ("streaming", "recording") else 0,
                    "captured_frames": self._captured, "displayed_frames": self._displayed,
                    "mailbox_replacement_events": self._mailbox_replacement_events,
                    "mailbox_replacement_definition": "Incoming frame replaced a cached latest identity before display acknowledgement; "
                        "the replaced frame may still be rendered, so this overlaps displayed_frames and is not device loss",
                    "counter_scope": "CameraSession object lifetime; cumulative across stream epochs and reconnects",
                    "displayed_frames_definition": "Unique frame identities acknowledged after application image update; not measured screen paint",
                    "latest_queue_definition": "Cached latest-frame occupancy; not a pending or unseen-frame count",
                    "stage_timings": self.timings.snapshot(),
                    "backend_stage_timings": self._backend_timings.snapshot() if self._backend_timings else None,
                    "backend_timing_scope": "Current or most recently owned backend instance",
                    "device_frame_gaps": self._device_gaps,
                    "fetch_timeouts": self._fetch_timeouts, "latest_queue_length": int(current is not None),
                    "latest_queue_capacity": 1, "frame_age_s": age,
                    "frame_age_definition": "host monotonic now minus host buffer receive; excludes uncalibrated device clock",
                    "stale": (age if age is not None else time.monotonic() - (self._stream_started or time.monotonic())) > max(1.0, 3 * (self.settings.get("ExposureTime", 100000) or 100000) / 1e6),
                    "last_stop_seconds": self._last_stop_seconds, "recording": recording,
                    "snapshot_pending": self._snapshot_pending, "settings": dict(self.settings), "mode": self.mode,
                    "capabilities": dict(self._capabilities), "connection_metadata": dict(self._connection_metadata),
                    "cleanup": list(self._cleanup),
                    "frame_metadata": dict(current.metadata) if current else None}

    def _connect(self):
        if self._backend is not None:
            if self.state == "error":
                raise RuntimeError("Disconnect the failed session before reconnecting")
            return
        self._set_state("connecting")
        factory = self._backend_factory
        if factory is None:
            from hyperlab.adapters.gentl import GenTLBackend
            factory = GenTLBackend
        self._backend = factory(self.cti, self.serial)
        self._backend_timings = getattr(self._backend, 'timings', None)
        self._camera_released = False
        self._connection_metadata = dict(self._phase('open', self._backend.open, 30) or {})
        self._capabilities = dict(self._backend.capabilities)
        self.session_id = str(uuid4())
        self._sequence = 0
        self._latest = None
        self._error = None
        self._set_state("ready")

    def _start(self):
        if self.state in ("streaming", "recording"):
            return
        if self._backend is None:
            self._connect()
        if self.state != "ready":
            raise RuntimeError("Preview requires a ready camera session")
        self._stop_requested.clear()
        with self._lock:
            self.stream_epoch += 1
            self._latest = None
            self._display_identity = None
            self._capture_times.clear()
            self._display_times.clear()
        self._phase('configure', lambda: self._backend.configure(self.settings, mode=self.mode), 15)
        self._capabilities = dict(self._backend.capabilities)
        self._connection_metadata = dict(self._backend.metadata)
        self._stream_started_ns = time.monotonic_ns()
        self._phase('start', self._backend.start, 10)
        self._previous_device_id = None
        self._stream_started = time.monotonic()
        self._last_received = None
        self._set_state("streaming")

    def _phase(self, name, operation, deadline_s):
        """Deadlines are observations, never a claim of native cancellation."""
        started = time.monotonic_ns()
        event = {'phase': name, 'entered_utc': utc_now(), 'entered_ns': started,
                 'deadline_ns': started + int(deadline_s * 1e9), 'status': 'ENTERED',
                 'cancellation': 'native call is not cancellable by Future timeout'}
        self._phases.append(event)
        self._emit('phase', **event)
        self._save_phases()
        try:
            result = operation()
            event['status'] = 'RETURNED'
            return result
        except Exception as exc:
            event.update(status='FAILED', exception_type=type(exc).__name__, error=str(exc))
            raise
        finally:
            event.update(exited_ns=time.monotonic_ns(), exited_utc=utc_now())
            event['deadline_exceeded'] = event['exited_ns'] > event['deadline_ns']
            self._emit('phase', **event)
            self._save_phases()

    def _save_phases(self):
        if self.phase_log:
            try:
                self.phase_log.parent.mkdir(parents=True, exist_ok=True)
                atomic_json(self.phase_log, {'phases':list(self._phases), 'session_id':self.session_id,
                                            'cleanup':list(self._cleanup), 'camera_released':self._camera_released,
                                            'error':self._error})
            except OSError as error:
                self._emit('phase_log_error', error=str(error))

    def _stop(self):
        self._stop_requested.clear()
        if self._backend is None:
            return
        if self._recording and not self._recording.done.is_set():
            self._recording.stop()
        if self.state in ("streaming", "recording", "stopping") or self._backend.original or self._backend.start_attempted:
            self._set_state("stopping")
            started = time.monotonic()
            events = self._phase('stop_restore', self._backend.stop_restore, 10)
            self._cleanup.extend(events)
            self._last_stop_seconds = time.monotonic() - (self._stop_request_time or started)
            self._stop_request_time = None
            if any(not item["succeeded"] for item in events):
                raise RuntimeError("Camera stop or setting restoration failed; inspect cleanup evidence")
        self._set_state("ready")

    def _disconnect(self):
        primary = None
        try:
            self._stop()
        except Exception as exc:
            primary = exc
        finally:
            if self._backend is not None:
                try:
                    events = self._phase('destroy', self._backend.close, 10)
                    self._cleanup.extend(events)
                    released = [item for item in events if item["step"] == "destroy"]
                    self._camera_released = bool(released and released[-1]["succeeded"])
                    if any(not item["succeeded"] for item in events) and primary is None:
                        primary = RuntimeError("Camera release failed; inspect cleanup evidence")
                except Exception as exc:
                    self._camera_released = False
                    self._cleanup.append({'step':'destroy', 'attempted':True, 'succeeded':False,
                                          'exception_type':type(exc).__name__, 'error':str(exc)})
                    primary = primary or exc
                finally:
                    self._backend = None
        if primary is not None:
            raise primary
        self._set_state("disconnected")
        self._save_phases()

    def _command(self, operation, values):
        if operation == "connect":
            self._connect()
        elif operation == "start":
            self._start()
        elif operation == "stop":
            self._stop()
        elif operation == "disconnect":
            self._disconnect()
        elif operation == "settings":
            if self.state not in ("ready", "disconnected"):
                raise ValueError("Stop acquisition before changing camera settings")
            if values["mode"] not in ("measurement", "preview"):
                raise ValueError("Choose measurement or preview mode")
            self.settings = values["settings"]
            self.mode = values["mode"]
        elif operation == "record":
            if self.state != "streaming" or self._latest is None or self._latest.metadata.get('stream_epoch') != self.stream_epoch:
                raise ValueError("Receive a valid frame from the current stream epoch before recording")
            if self._recording and not self._recording.done.is_set():
                raise ValueError("Previous recording is still draining to disk")
            self._recording = self._recorder_factory(values["directory"], self._latest, values["max_frames"],
                                                    duration_s=values["duration_s"], capacity=self.writer_capacity)
            self._recording_reported = False
            self._set_state("recording")
            self._emit("recording", **self._recording.status())
        elif operation == "record_stop":
            if self._recording:
                self._recording.stop()
            if self.state == "recording":
                self._set_state("streaming")
        elif operation == "diagnostics":
            if self._backend is None or self.state != "ready":
                raise ValueError("Connect and stop acquisition before exporting node descriptions")
            directory = Path(values["directory"])
            directory.mkdir(parents=True, exist_ok=False)
            output = {"session_id": self.session_id, "metadata": self._connection_metadata,
                      "nodes": self._backend.describe_nodes(all_nodes=True), "commands_executed": False,
                      "selector_changes": False, "host_utc": utc_now(),
                      "value_read_scope": "reviewed FEATURES only; other nodes have cached name/type only",
                      "xml_export": "NOT_EXPORTED"}
            atomic_json(directory / "genicam-nodes.json", output)
            return directory / "genicam-nodes.json"
        return self.state

    def _failure(self, exc):
        # The first acquisition failure remains primary even if every cleanup
        # operation also fails. Cleanup receipts remain individually inspectable.
        self._error = self._error or str(exc)
        if self._recording and not self._recording.done.is_set():
            if self._backend is not None:
                self._recording.failed_frame = getattr(self._backend, "failed_frame_metadata", None) or self._recording.failed_frame
                self._recording.failed_payload = getattr(self._backend, "failed_payload", None)
            self._recording.stop(error=self._error)
        if self._backend is not None:
            try:
                self._cleanup.extend(self._phase('error_cleanup', self._backend.close, 10))
            except Exception as cleanup_error:
                self._cleanup.append({'step':'error_cleanup', 'attempted':True, 'succeeded':False,
                                      'error':str(cleanup_error)})
            destroy = [item for item in self._backend.cleanup if item["step"] == "destroy"]
            self._camera_released = bool(destroy and destroy[-1]["succeeded"])
            self._backend = None
        self._set_state("error")
        self._emit("error", error=self._error, cleanup=list(self._cleanup))
        self._save_phases()

    def _observe_recording(self):
        recording = self._recording
        if recording is None:
            return
        if recording.stop_event.is_set() and self.state == "recording":
            self._set_state("streaming")
        if recording.done.is_set() and not self._recording_reported:
            self._last_recording = recording.status()
            self._recording_reported = True
            self._emit("recording", **self._last_recording)

    def _fetch(self):
        try:
            with self.timings.measure('backend_fetch'):
                raw, metadata, _ = self._backend.fetch(self.fetch_timeout)
        except Exception as exc:
            # GenTL timeout is expected for long exposure, but prolonged silence
            # eventually becomes an explicit stream error rather than eternal LIVE.
            if isinstance(exc, TimeoutError) or type(exc).__name__ == "TimeoutException":
                self._fetch_timeouts += 1
                allowed = max(5.0, 2 * (self.settings.get("ExposureTime", 100000) or 100000) / 1e6 + 1)
                if time.monotonic() - (self._last_received or self._stream_started) > allowed:
                    raise TimeoutError("No frame received within the exposure-aware stream deadline") from exc
                return
            raise
        self._last_received = time.monotonic()
        with self.timings.measure('metadata_frame_build'):
            metadata.update(session_id=self.session_id, sequence=self._sequence,
                            stream_epoch=self.stream_epoch, stream_started_ns=self._stream_started_ns)
            self._sequence += 1
            frame = Frame(raw, metadata)
        device_id = metadata.get("frame_id")
        if isinstance(device_id, int) and isinstance(self._previous_device_id, int) and device_id > self._previous_device_id + 1:
            missing = device_id - self._previous_device_id - 1
            self._device_gaps += missing
            if self._recording and not self._recording.stop_event.is_set():
                self._recording.failed_frame = dict(metadata)
                self._recording.stop(error=f"Device frame ID gap: {missing} missing frame(s); recording stopped")
        self._previous_device_id = device_id
        with self.timings.measure('mailbox_publish'), self._lock:
            if self._latest is not None and self._latest.identity != self._display_identity:
                self._mailbox_replacement_events += 1
            self._latest = frame
            self._captured += 1
            self._capture_times.append(self._last_received)
        if self._recording and not self._recording.stop_event.is_set():
            with self.timings.measure('writer_admission'):
                self._recording.submit(frame)

    def _run(self):
        try:
            while not self._close_requested.is_set():
                try:
                    operation, values, future = self._commands.get(timeout=0 if self.state in ("streaming", "recording") else 0.02)
                except queue.Empty:
                    operation = None
                if operation is not None:
                    try:
                        future.set_result(self._command(operation, values))
                    except Exception as exc:
                        future.set_exception(exc)
                        if operation in ("connect", "start", "stop", "disconnect"):
                            self._failure(exc)
                        else:
                            self._emit("error", error=str(exc), operation=operation)
                    self._commands.task_done()
                if self._stop_requested.is_set() and self.state in ("streaming", "recording"):
                    try:
                        self._stop()
                    except Exception as exc:
                        self._failure(exc)
                if self.state in ("streaming", "recording"):
                    try:
                        self._fetch()
                    except Exception as exc:
                        self._failure(exc)
                self._observe_recording()
        finally:
            try:
                self._disconnect()
            except Exception as exc:
                self._error = self._error or str(exc)
                self._set_state("error")
                self._emit("error", error=self._error, cleanup=list(self._cleanup))
            if self._recording:
                self._recording.stop()
                self._recording.thread.join()
                self._observe_recording()
            self._snapshots.shutdown(wait=True)
            while not self._commands.empty():
                _, _, future = self._commands.get_nowait()
                future.set_exception(RuntimeError("Camera session closed before command execution"))
            self._closed.set()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close(wait=True)
