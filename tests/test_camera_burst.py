import json
import threading

import pytest

from hyperlab.acquisition.camera import CameraSession
from hyperlab.acquisition import sequence as module
from test_camera_session import StreamingFake, wait_until


@pytest.fixture(autouse=True)
def memory(monkeypatch):
    monkeypatch.setattr(module, 'available_memory_bytes', lambda: 16 * 1024**3)
    monkeypatch.setattr('hyperlab.acquisition.camera._UNRELEASED_TARGETS', set())


def started(fake, **kwargs):
    session = CameraSession('synthetic', 'synthetic', backend_factory=lambda *args: fake, **kwargs)
    session.start_preview().result(5)
    wait_until(lambda: session.latest_frame() is not None)
    return session


def test_camera_stop_precedes_burst_storage_and_restart_is_blocked(tmp_path):
    fake = StreamingFake()
    gate = threading.Event()
    entered = threading.Event()
    class PausedWriter(module.SequenceWriter):
        def __init__(self, *args, **kwargs):
            assert any(name == 'stop_restore' for name, _ in fake.calls)
            assert not fake.start_attempted
            entered.set()
            assert gate.wait(5)
            super().__init__(*args, **kwargs)
    def recorder(*args, **kwargs):
        return module.SequenceRecorder(*args, writer_factory=PausedWriter, **kwargs)
    session = started(fake, recorder_factory=recorder)
    try:
        session.start_recording(tmp_path / 'burst', 8, recording_mode='ram_burst').result(5)
        assert entered.wait(5)
        status = session.status()
        assert status['state'] == 'ready'
        assert status['recording']['admitted_frames'] == 8
        assert status['recording']['durable_frames'] == 0
        with pytest.raises(ValueError, match='recovery must finish'):
            session.start_preview().result(5)
        gate.set()
        wait_until(lambda: session.status()['recording']['done'])
        assert session.status()['recording']['completed']
        session.start_preview().result(5)
        assert session.stream_epoch == 2
    finally:
        gate.set()
        assert session.close(wait=True)


def test_close_waits_for_persistence_without_abandoning_ram(tmp_path):
    fake = StreamingFake()
    gate = threading.Event()
    entered = threading.Event()
    def factory(*args, **kwargs):
        def writer(*args, **kwargs):
            entered.set()
            assert gate.wait(5)
            return module.SequenceWriter(*args, **kwargs)
        return module.SequenceRecorder(*args, writer_factory=writer, **kwargs)
    session = started(fake, recorder_factory=factory)
    session.start_recording(tmp_path / 'burst', 8, recording_mode='ram_burst').result(5)
    assert entered.wait(5)
    assert not session.close(wait=True, timeout=.02)
    assert session.status()['pending_close'] == 'waiting_for_persistence'
    assert session.status()['recording']['retained_frames'] == 8
    gate.set()
    wait_until(lambda: session.closed)
    assert session.status()['recording']['durable_frames'] == 8
    assert session.status()['camera_released']


@pytest.mark.parametrize('action', ['retry', 'abandon'])
def test_close_recovery_keeps_session_alive_until_explicit_action(tmp_path, action):
    fake = StreamingFake()
    class Failure(module.SequenceWriter):
        def checkpoint(self):
            raise OSError('injected persistence failure')
    def factory(*args, **kwargs):
        return module.SequenceRecorder(*args, writer_factory=Failure, **kwargs)
    session = started(fake, recorder_factory=factory)
    session.start_recording(tmp_path / 'partial', 8, recording_mode='ram_burst').result(5)
    wait_until(lambda: session.status()['recording']['can_retry'])
    assert not session.close(wait=True, timeout=.03)
    assert session.status()['pending_close'] == 'recovery_required'
    assert session.status()['recording']['retained_frames'] == 8
    assert session.status()['worker_alive']
    if action == 'retry':
        session._recording._writer_factory = module.SequenceWriter
        session.retry_recording(tmp_path / 'retry').result(5)
    else:
        path = session.abandon_recording().result(5)
        assert json.loads(path.read_text())['abandonment_confirmed']
    wait_until(lambda: session.closed)
    result = session.status()['recording']
    assert result['retained_frames'] == 0
    assert result['phase'] == ('complete' if action == 'retry' else 'abandoned')


@pytest.mark.parametrize('failure', ['fetch', 'restore'])
def test_camera_failure_releases_persistence_gate_and_preserves_error(tmp_path, failure):
    class Fault(StreamingFake):
        def stop_restore(self):
            events = super().stop_restore()
            if failure == 'restore':
                events[-1]['succeeded'] = False
            return events
    fake = Fault(fail_after=7 if failure == 'fetch' else None)
    session = started(fake)
    try:
        session.start_recording(tmp_path / 'partial', 8, recording_mode='ram_burst').result(5)
        wait_until(lambda: session.status()['recording']['done'])
        result = session.status()['recording']
        assert result['admitted_frames'] > 0
        assert result['durable_frames'] == result['admitted_frames']
        assert result['partial'] and result['error']
        assert session.state == 'error'
        assert not result['can_retry']
        with module.load_sequence(tmp_path / 'partial') as saved:
            assert saved.metadata['partial'] and saved.metadata['error']
    finally:
        assert session.close(wait=True)


def test_failed_release_blocks_same_target_across_close_and_new_sessions(tmp_path):
    class Unreleased(StreamingFake):
        def stop_restore(self):
            events = super().stop_restore()
            events[-1]['succeeded'] = False
            return events
        def close(self):
            events = super().close()
            events[-1]['succeeded'] = False
            return events
    session = started(Unreleased())
    session.start_recording(tmp_path / 'partial', 2, recording_mode='ram_burst').result(5)
    wait_until(lambda: session.status()['recording']['done'])
    assert not session.status()['camera_released']
    assert session.close(wait=True)
    calls = []
    def unopened(*args):
        calls.append(args)
        return StreamingFake()
    replacement = CameraSession('synthetic', 'synthetic', backend_factory=unopened)
    try:
        with pytest.raises(ValueError, match='release is unconfirmed'):
            replacement.start_preview().result(5)
        assert not calls and replacement.state == 'error'
        assert not replacement.status()['camera_released']
    finally:
        assert replacement.close(wait=True)
    unrelated = CameraSession('different-producer', 'synthetic', backend_factory=unopened)
    try:
        unrelated.start_preview().result(5)
        assert len(calls) == 1
    finally:
        assert unrelated.close(wait=True)


def test_normally_released_target_can_open_a_new_session():
    first = started(StreamingFake())
    assert first.close(wait=True) and first.status()['camera_released']
    second = started(StreamingFake())
    try:
        assert second.state == 'streaming'
    finally:
        assert second.close(wait=True)
