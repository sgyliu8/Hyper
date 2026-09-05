from types import SimpleNamespace
import json
import threading
import time
import numpy as np
import pytest
from hyperlab.acquisition.camera import CameraSession
from hyperlab.acquisition.sequence import load_sequence
from hyperlab.adapters import gentl


class FakeNode:
    def __init__(self, name, value, entries=None, limits=(0, 20_000_000), fail_restore=False):
        self.name, self._value = name, value
        self.initial = value
        self.entries = [SimpleNamespace(symbolic=item) for item in entries] if entries else None
        self.min, self.max = limits
        self.inc, self.unit = None, "us" if name == "ExposureTime" else "dB" if name == "Gain" else None
        self.access_mode = "RW"
        self.writes = []
        self.fail_restore = fail_restore

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        self.writes.append(value)
        if self.fail_restore and value == self.initial:
            raise RuntimeError(f"restore failed {self.name}")
        self._value = value


class FakeApi:
    @staticmethod
    def is_readable(node):
        return True

    @staticmethod
    def is_writable(node):
        return True

    @staticmethod
    def is_available(node):
        return True


class FakeBuffer:
    def __init__(self, complete=True, fmt="BayerRG12", bad_size=False):
        self.returned = False
        self.returns = 0
        self.complete, self.fmt, self.bad_size = complete, fmt, bad_size
        self.module = self
        self.payload = SimpleNamespace(components=[self])
        self.height, self.width = 3, 4
        self.values = np.arange(12 if not bad_size else 5, dtype=np.uint16)

    def _valid(self):
        assert not self.returned, "accessed an obsolete GenTL buffer"

    @property
    def data(self):
        self._valid()
        return self.values

    @property
    def data_format(self):
        self._valid()
        return self.fmt

    @property
    def raw_buffer(self):
        self._valid()
        return self.values.tobytes()

    @property
    def frame_id(self):
        self._valid()
        return 6

    @property
    def timestamp_ns(self):
        self._valid()
        return 789

    def is_complete(self):
        self._valid()
        return self.complete

    def queue(self):
        self._valid()
        self.returns += 1
        self.returned = True
        self.values[:] = 65535  # recycled SDK memory must never affect owned frame


class FakeCamera:
    def __init__(self, faults=()):
        self.faults = set(faults)
        enums = {"PixelFormat": ["BayerRG12", "RGB8"], "TriggerMode": ["Off", "On"],
                 "AcquisitionMode": ["Continuous", "SingleFrame"], "ExposureAuto": ["Off", "Continuous"],
                 "GainAuto": ["Off", "Continuous"], "BalanceWhiteAuto": ["Off", "Continuous"]}
        values = {"Width": 4, "Height": 3, "PixelFormat": "BayerRG12", "ExposureTime": 20000,
                  "Gain": 0, "TriggerMode": "Off", "AcquisitionMode": "SingleFrame",
                  "ExposureAuto": "Continuous", "GainAuto": "Continuous", "BalanceWhiteAuto": "Off",
                  "GammaEnable": True, "LUTEnable": False, "TestPattern": "Off", "TestImageSelector": "Off",
                  "ChunkModeActive": False, "OffsetX": 0, "OffsetY": 0, "ReverseX": False, "ReverseY": False}
        self.nodes = SimpleNamespace(**{name: FakeNode(name, value, entries=enums.get(name),
                                                     fail_restore=name == "Gain" and "restore" in self.faults)
                                       for name, value in values.items()})
        self.nodes.nodes = list(vars(self.nodes).values())
        self.remote_device = SimpleNamespace(node_map=self.nodes)
        self.events = []
        self.buffer = FakeBuffer(complete="incomplete" not in self.faults,
                                 fmt="Unknown32" if "decode" in self.faults else "BayerRG12",
                                 bad_size="size" in self.faults)

    def start(self, **kwargs):
        self.events.append("start")
        assert kwargs == {"run_as_thread": False}
        if "start" in self.faults:
            raise RuntimeError("start primary")

    def fetch(self, timeout):
        self.events.append("fetch")
        assert timeout > 0
        if "fetch" in self.faults:
            raise RuntimeError("fetch primary")
        return self.buffer

    def stop(self):
        self.events.append("stop")
        if "stop" in self.faults:
            raise RuntimeError("stop secondary")

    def destroy(self):
        self.events.append("destroy")
        if "destroy" in self.faults:
            raise RuntimeError("destroy secondary")


class FakeHarvester:
    def __init__(self, camera):
        self.camera = camera
        self.reset_called = False
        self.device_info_list = [SimpleNamespace(serial_number="fixture", model="mvBlueFOX3-fixture",
                                                 vendor="fixture", tl_type="U3V")]

    def add_file(self, *args, **kwargs):
        pass

    def update(self):
        pass

    def create(self, identity):
        assert identity == {"serial_number": "fixture"}
        return self.camera

    def reset(self):
        self.reset_called = True


def make_backend(tmp_path, monkeypatch, faults=()):
    monkeypatch.setattr("importlib.metadata.version", lambda name: "fixture")
    cti = tmp_path / "mvGenTLProducer.cti"
    cti.write_text("not an executable, fake test only")
    camera = FakeCamera(faults)
    harvester = FakeHarvester(camera)
    backend = gentl.GenTLBackend(cti, "fixture", harvester_factory=lambda: harvester,
                                 producer_reviewer=lambda path: {"valid": True, "signer": "fixture"}, node_api=FakeApi)
    return backend, camera, harvester


@pytest.mark.parametrize("fault", ["start", "fetch", "incomplete", "decode", "size", "stop", "restore", "destroy"])
def test_gentl_fault_stages_attempt_independent_cleanup(tmp_path, monkeypatch, fault):
    backend, camera, harvester = make_backend(tmp_path, monkeypatch, [fault])
    primary = None
    try:
        backend.open()
        backend.configure({"ExposureTime": 50000, "Gain": 2})
        backend.start()
        raw, metadata, payload = backend.fetch(0.2, keep_transport=True)
        assert camera.buffer.returned and camera.buffer.returns == 1
        assert raw[0, 0] == 0  # SDK buffer has been overwritten after requeue
        assert metadata["chunk_settings"] == {}
        assert metadata["readback_settings"]["ExposureTime"] == 50000
    except Exception as exc:
        primary = exc
    finally:
        backend.close()
    assert "stop" in camera.events and "destroy" in camera.events and harvester.reset_called
    assert camera.nodes.ExposureTime.value == 20000
    assert camera.nodes.ExposureAuto.value == "Continuous"
    assert camera.nodes.GainAuto.value == "Continuous"
    if "fetch" in camera.events and fault != "fetch":
        assert camera.buffer.returns == 1
    if fault in ("start", "fetch", "incomplete", "decode", "size"):
        assert primary is not None
    else:
        assert any(not item["succeeded"] for item in backend.cleanup)


def test_capture_primary_error_not_overwritten_by_cleanup(tmp_path, monkeypatch):
    backend, camera, harvester = make_backend(tmp_path, monkeypatch, ["fetch", "stop", "restore", "destroy"])
    monkeypatch.setattr(gentl, "GenTLBackend", lambda *args: backend)
    with pytest.raises(RuntimeError, match="fetch primary"):
        gentl.capture_single(tmp_path / "mvGenTLProducer.cti", "fixture", tmp_path / "failed", gain=2, exposure_us=50000)
    receipt = json.loads((tmp_path / "failed/frame.npy.json").read_text())
    assert receipt["primary_error"] == "fetch primary"
    assert len(receipt["cleanup_errors"]) >= 3
    assert harvester.reset_called and camera.nodes.ExposureTime.value == 20000


def test_capture_write_is_after_return_and_write_failure_still_cleans(tmp_path, monkeypatch):
    backend, camera, harvester = make_backend(tmp_path, monkeypatch)
    monkeypatch.setattr(gentl, "GenTLBackend", lambda *args: backend)
    def write_fail(*args, **kwargs):
        assert camera.buffer.returned and camera.buffer.returns == 1
        raise OSError("disk write primary")
    monkeypatch.setattr("hyperlab.acquisition.frame.save_frame", write_fail)
    with pytest.raises(OSError, match="disk write primary"):
        gentl.capture_single(tmp_path / "mvGenTLProducer.cti", "fixture", tmp_path / "failed")
    assert camera.events[-2:] == ["stop", "destroy"] and harvester.reset_called
    receipt = json.loads((tmp_path / "failed/frame.npy.json").read_text())
    assert receipt["primary_error"] == "disk write primary" and receipt["device_released"]


def test_capture_normal_reopen_and_restoration_receipt(tmp_path, monkeypatch):
    backend, camera, harvester = make_backend(tmp_path, monkeypatch)
    monkeypatch.setattr(gentl, "GenTLBackend", lambda *args: backend)
    path = gentl.capture_single(tmp_path / "mvGenTLProducer.cti", "fixture", tmp_path / "frame",
                               exposure_us=50000, gain=2)
    receipt = json.loads(path.with_suffix(".npy.json").read_text())
    assert receipt["completed"] and receipt["save_reopen_verified"]
    assert receipt["stop_returned"] and receipt["device_released"]
    assert not receipt["cleanup_errors"]
    assert receipt["settings_restored"]["ExposureTime"]["readback"] == 20000
    assert camera.buffer.returns == 1 and np.array_equal(np.load(path), np.arange(12, dtype=np.uint16).reshape(3, 4))


def test_requeue_secondary_never_hides_decode_error(tmp_path, monkeypatch):
    backend, camera, harvester = make_backend(tmp_path, monkeypatch, ["decode"])
    original_queue = camera.buffer.queue
    def fail_queue():
        original_queue()
        raise RuntimeError("queue secondary")
    camera.buffer.queue = fail_queue
    backend.open()
    backend.configure({})
    backend.start()
    try:
        with pytest.raises(RuntimeError, match="Unmapped pixel format") as failure:
            backend.fetch(0.2)
        assert any("queue secondary" in note for note in failure.value.__notes__)
    finally:
        backend.close()
    assert camera.buffer.returns == 1


def test_buffer_identity_read_error_preserves_primary_and_requeues(tmp_path, monkeypatch):
    backend,camera,_ = make_backend(tmp_path,monkeypatch,['decode'])
    def identity_timeout(self):
        raise TimeoutError('identity transport failure')
    monkeypatch.setattr(FakeBuffer,'frame_id',property(identity_timeout))
    backend.open(); backend.configure({}); backend.start()
    try:
        with pytest.raises(RuntimeError,match='Unmapped pixel format'):
            backend.fetch(.2)
        assert backend.failed_frame_metadata['frame_id'] is None
        assert 'TimeoutError' in backend.failed_frame_metadata['frame_id_read_error']
    finally:
        backend.close()
    assert camera.buffer.returns==1


def test_genicam_typed_category_name_uses_inode_property(tmp_path, monkeypatch):
    backend, camera, harvester = make_backend(tmp_path, monkeypatch)
    backend.open()
    category = SimpleNamespace(node=SimpleNamespace(name="Root", access_mode="RO"))
    command = SimpleNamespace(node=SimpleNamespace(name="AcquisitionStart", access_mode="WO"),
                              execute=lambda: pytest.fail("Commands must never execute during description"))
    camera.nodes.Root = category
    camera.nodes.AcquisitionStart = command
    camera.nodes.nodes = [category, command, camera.nodes.Width]
    try:
        descriptions = backend.describe_nodes(all_nodes=True)
        assert descriptions["Root"]["value_status"] == "NOT_READ_UNREVIEWED_NODE"
        assert descriptions["AcquisitionStart"] == {"node_type": "command", "executed": False}
        assert descriptions["Width"]["value"] == 4
    finally:
        backend.close()


def test_continuous_float_has_no_fixed_increment(tmp_path, monkeypatch):
    backend,camera,_=make_backend(tmp_path,monkeypatch)
    class ContinuousFloat:
        value=50000.0
        min,max,unit=10.0,20_000_000.0,'us'
        def has_inc(self): return False
        @property
        def inc(self): raise RuntimeError('node does not have an increment')
    camera.nodes.ExposureTime=ContinuousFloat()
    try:
        backend.open()
        assert backend.capabilities['ExposureTime']['inc'] is None
        backend.configure({'ExposureTime':20000.0},mode='preview')
        assert backend.readback['ExposureTime']==20000.0
    finally:
        backend.close()


def test_increment_support_query_preserves_transport_error(tmp_path, monkeypatch):
    backend,camera,_=make_backend(tmp_path,monkeypatch)
    def broken_query(): raise TimeoutError('increment support communication timeout')
    camera.nodes.ExposureTime.has_inc=broken_query
    try:
        with pytest.raises(TimeoutError,match='increment support communication'):
            backend.open()
        assert backend.node_evidence['ExposureTime']['status']=='read_error'
    finally:
        backend.close()


def test_unreviewed_node_export_never_reads_value_or_access(tmp_path, monkeypatch):
    backend, camera, harvester = make_backend(tmp_path, monkeypatch)
    backend.open()
    class VendorNode:
        node = SimpleNamespace(name="VendorRegisterBank")
        @property
        def value(self):
            pytest.fail("Unreviewed native register read may block and is forbidden")
        def get_access_mode(self):
            pytest.fail("Unreviewed access query must not execute")
    camera.nodes.nodes = [VendorNode()]
    try:
        assert backend.describe_nodes(all_nodes=True)["VendorRegisterBank"]["value_status"] == "NOT_READ_UNREVIEWED_NODE"
    finally:
        backend.close()


def test_restore_format_before_exposure_and_auto_last(tmp_path, monkeypatch):
    backend, camera, harvester = make_backend(tmp_path, monkeypatch)
    camera.nodes.PixelFormat._value = "RGB8"
    camera.nodes.PixelFormat.initial = "RGB8"
    class FormatDependentExposure(FakeNode):
        @FakeNode.value.setter
        def value(self, value):
            if value == self.initial:
                if camera.nodes.PixelFormat.value != "RGB8":
                    raise ValueError("Original exposure requires the original pixel format")
                if camera.nodes.ExposureAuto.value != "Off":
                    raise ValueError("Manual exposure must restore before re-enabling auto")
            FakeNode.value.fset(self, value)
    camera.nodes.ExposureTime = FormatDependentExposure("ExposureTime", 20000)
    backend.open()
    backend.configure({"PixelFormat": "BayerRG12", "ExposureTime": 50000, "Gain": 2})
    backend.start()
    try:
        cleanup = backend.stop_restore()
        assert all(item["succeeded"] for item in cleanup)
        names = [item["step"] for item in cleanup]
        assert names.index("restore:PixelFormat") < names.index("restore:ExposureTime")
        assert names.index("restore:ExposureTime") < names.index("restore:ExposureAuto")
        assert camera.nodes.ExposureTime.value == 20000
    finally:
        backend.close()


def test_measurement_freezes_available_black_level_auto_and_restores_it(tmp_path, monkeypatch):
    backend, camera, harvester = make_backend(tmp_path, monkeypatch)
    camera.nodes.BlackLevelAuto = FakeNode("BlackLevelAuto", "Continuous", entries=["Off", "Continuous"])
    backend.open()
    try:
        backend.configure({})
        assert backend.readback["BlackLevelAuto"] == "Off"
        assert camera.nodes.BlackLevelAuto.writes == ["Off"]
        events = backend.stop_restore()
        assert camera.nodes.BlackLevelAuto.value == "Continuous"
        assert any(item["step"] == "restore:BlackLevelAuto" and item["succeeded"] for item in events)
    finally:
        backend.close()


def test_no_unsupported_black_level_auto_write(tmp_path, monkeypatch):
    backend, camera, harvester = make_backend(tmp_path, monkeypatch)
    camera.nodes.BlackLevelAuto = FakeNode("BlackLevelAuto", "Continuous", entries=["Continuous"])
    backend.open()
    try:
        with pytest.raises(ValueError, match="enumeration"):
            backend.configure({})
        assert camera.nodes.BlackLevelAuto.writes == []
    finally:
        backend.close()


class StreamingFake:
    def __init__(self, *args, fail_after=None):
        self.calls = []
        self.cleanup = []
        self.original = {}
        self.start_attempted = False
        self.capabilities = {"ExposureTime": {"value": 50000, "unit": "us", "min": 10, "max": 20000000}}
        self.metadata = {"model": "explicit offline fake"}
        self.index = 0
        self.fail_after = fail_after

    def _call(self, operation):
        self.calls.append((operation, threading.get_ident()))

    def open(self):
        self._call("open")
        return self.metadata

    def configure(self, settings, mode):
        self._call("configure")
        self.original = dict(settings)
        self.metadata.update(readback_settings=dict(settings), requested_settings=dict(settings))

    def start(self):
        self._call("start")
        self.start_attempted = True

    def fetch(self, timeout):
        self._call("fetch")
        time.sleep(0.003)
        if self.fail_after is not None and self.index >= self.fail_after:
            raise ConnectionError("injected cable loss")
        self.index += 1
        return np.full((3, 4), self.index, np.uint16), dict(self.metadata, frame_id=self.index,
                    host_monotonic_ns=time.monotonic_ns(), host_utc="fixture", valid=True,
                    acquisition_source="SYNTHETIC", data_source="SYNTHETIC", pixel_format="BayerRG12"), None

    def stop_restore(self):
        self._call("stop_restore")
        self.start_attempted = False
        self.original.clear()
        events = [{"step": "stop", "attempted": True, "succeeded": True}]
        self.cleanup.extend(events)
        return events

    def close(self):
        self._call("close")
        events = self.stop_restore() + [{"step": "destroy", "attempted": True, "succeeded": True}]
        self.cleanup.append(events[-1])
        return events


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise TimeoutError("fixture condition did not complete")


def test_persistent_state_restart_latest_exact_snapshot_record(tmp_path):
    fake = StreamingFake()
    session = CameraSession("fixture", "fixture", settings={"ExposureTime": 50000}, backend_factory=lambda *args: fake)
    try:
        assert session.connect().result(5) == "ready"
        identity = session.session_id
        assert session.start_preview().result(5) == "streaming"
        wait_until(lambda: session.status()["captured_frames"] >= 5)
        displayed = session.latest_frame()
        session.mark_displayed(displayed)
        path = session.snapshot(tmp_path / "exact", frame=displayed).result(5)
        assert np.array_equal(np.load(path), displayed.data)
        assert json.loads(path.with_suffix(".npy.json").read_text())["sequence"] == displayed.metadata["sequence"]
        assert session.start_recording(tmp_path / "sequence", 8).result(5) == "recording"
        wait_until(lambda: session.status()["recording"]["done"])
        assert session.state == "streaming"
        with load_sequence(tmp_path / "sequence") as sequence:
            assert sequence.frame_count == 8 and sequence.metadata["completed"]
            assert np.all(np.diff(sequence.data[:, 0, 0]) == 1)
        assert session.stop_preview().result(5) == "ready"
        before = session.status()["captured_frames"]
        time.sleep(0.03)
        assert session.status()["captured_frames"] == before
        session.set_settings({"ExposureTime": 20000}).result(5)
        session.start_preview().result(5)
        wait_until(lambda: session.status()["captured_frames"] > before)
        assert session.session_id == identity
        assert session.latest_frame().metadata["sequence"] > displayed.metadata["sequence"]
        assert session.status()["latest_queue_length"] == 1
        assert session.status()["preview_dropped"] > 0
    finally:
        assert session.close(wait=True)
    assert session.status()["camera_released"]
    assert len({owner for _, owner in fake.calls}) == 1
    assert fake.calls[0][1] != threading.get_ident()
    assert [call for call, _ in fake.calls].count("open") == 1


def test_fault_close_retains_primary_and_stops_recording(tmp_path):
    fake = StreamingFake(fail_after=12)
    # Isolate the injected acquisition failure from writer startup scheduling.
    # At most 12 fixture frames fit; separate tests exercise bounded overflow.
    session = CameraSession("fixture", "fixture", backend_factory=lambda *args: fake, writer_capacity=32)
    try:
        session.connect().result(5)
        session.start_preview().result(5)
        wait_until(lambda: session.latest_frame() is not None)
        session.start_recording(tmp_path / "partial", 100).result(5)
        session.wait_for_state("error", timeout=5)
        wait_until(lambda: session.status()["recording"]["done"])
        assert session.status()["error"] == "injected cable loss"
        with load_sequence(tmp_path / "partial") as sequence:
            assert sequence.metadata["partial"]
            assert sequence.metadata["error"] == "injected cable loss"
    finally:
        assert session.close(wait=True)


def test_close_during_stream_cooperative_and_settings_only_ready():
    fake = StreamingFake()
    session = CameraSession("fixture", "fixture", backend_factory=lambda *args: fake)
    session.connect().result(5)
    session.start_preview().result(5)
    with pytest.raises(ValueError, match="Stop acquisition"):
        session.set_settings({"ExposureTime": 80000}).result(5)
    started = time.monotonic()
    assert session.close(wait=True, timeout=2)
    assert time.monotonic() - started < 2
    assert session.status()["camera_released"]


def test_disconnect_stop_error_survives_destroy_exception(tmp_path):
    class CleanupFault(StreamingFake):
        def stop_restore(self):
            raise TimeoutError('primary stop timeout')
        def close(self):
            raise ConnectionError('secondary destroy fault')
    fake=CleanupFault()
    log=tmp_path/'phases.json'
    session=CameraSession('fixture','fixture',backend_factory=lambda *args:fake,phase_log=log)
    try:
        session.start_preview().result(5)
        with pytest.raises(TimeoutError,match='primary stop timeout'):
            session.disconnect().result(5)
        session.wait_for_state('error',timeout=5)
        assert session.status()['error']=='primary stop timeout'
        assert not session.status()['camera_released']
        assert any('secondary destroy fault' in str(item) for item in session.status()['cleanup'])
    finally:
        assert session.close(wait=True)
    receipt=json.loads(log.read_text())
    assert receipt['error']=='primary stop timeout' and not receipt['camera_released']
    assert any('secondary destroy fault' in str(item) for item in receipt['cleanup'])


def test_device_frame_gap_makes_recording_partial(tmp_path):
    class GapFake(StreamingFake):
        def fetch(self, timeout):
            if self.index == 12:
                self.index += 2
            return super().fetch(timeout)
    fake = GapFake()
    session = CameraSession("fixture", "fixture", backend_factory=lambda *args: fake)
    try:
        session.connect().result(5)
        session.start_preview().result(5)
        wait_until(lambda: session.latest_frame() is not None)
        session.start_recording(tmp_path / "gap", 50).result(5)
        wait_until(lambda: session.status()["recording"]["done"])
        assert session.state == "streaming"
        with load_sequence(tmp_path / "gap") as sequence:
            assert sequence.metadata["partial"]
            assert "Device frame ID gap" in sequence.metadata["error"]
        assert session.status()["device_frame_gaps"] == 2
    finally:
        session.close(wait=True)


def test_cancelled_snapshot_releases_bounded_slot(tmp_path, monkeypatch):
    from hyperlab.acquisition.frame import Frame
    allow_write = threading.Event()
    writer_entered = threading.Event()
    def blocked_snapshot(directory, frame):
        writer_entered.set()
        assert allow_write.wait(5)
        return directory
    monkeypatch.setattr("hyperlab.acquisition.camera.save_frame", blocked_snapshot)
    displayed = Frame(np.zeros((2, 2), np.uint16), {"session_id": "fixture", "sequence": 1})
    session = CameraSession("fixture", "fixture", backend_factory=StreamingFake)
    try:
        first = session.snapshot(tmp_path / "one", frame=displayed)
        assert writer_entered.wait(5)
        second = session.snapshot(tmp_path / "two", frame=displayed)
        with pytest.raises(RuntimeError, match="Two snapshots"):
            session.snapshot(tmp_path / "overflow", frame=displayed)
        assert second.cancel()
        replacement = session.snapshot(tmp_path / "replacement", frame=displayed)
        assert session.status()["snapshot_pending"] == 2
        allow_write.set()
        first.result(5)
        replacement.result(5)
        wait_until(lambda: session.status()["snapshot_pending"] == 0)
    finally:
        allow_write.set()
        session.close(wait=True)
