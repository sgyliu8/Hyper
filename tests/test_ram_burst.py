import json
from pathlib import Path
import threading
import time

import numpy as np
import pytest

from hyperlab.acquisition import sequence as module
from hyperlab.acquisition.frame import Frame
from test_recording_durability import owned


def until(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(.005)


@pytest.fixture(autouse=True)
def plentiful_memory(monkeypatch):
    monkeypatch.setattr(module, 'available_memory_bytes', lambda: 16 * 1024**3)


def burst(path, count=8, **kwargs):
    return module.SequenceRecorder(path, owned(99), count, recording_mode='ram_burst', **kwargs)


def finish(recorder):
    recorder.release_persistence()
    assert recorder.done.wait(5)
    recorder.thread.join(5)


def test_burst_has_no_file_before_camera_stop_and_keeps_owned_arrays_once(tmp_path):
    recorder = burst(tmp_path / 'burst')
    frames = [owned(i) for i in range(8)]
    for frame in frames:
        assert recorder.submit(frame)
    until(lambda: recorder.phase == 'waiting_for_camera_stop')
    assert not recorder.directory.exists()
    status = recorder.status()
    assert status['admitted_frames'] == status['retained_frames'] == status['volatile_frames'] == 8
    assert status['durable_frames'] == 0 and status['readable_frames'] is None
    assert not status['done'] and not status['can_abandon']
    assert all(a is b for a, b in zip(recorder._ram_frames, frames))
    finish(recorder)
    assert recorder._writer.array is None and recorder._writer._stream.closed
    assert recorder.status()['phase'] == 'complete' and recorder.status()['retained_frames'] == 0
    with module.load_sequence(recorder.path) as saved:
        assert saved.frame_count == saved.metadata['durable_frames'] == 8
        assert saved.metadata['recording_mode'] == 'ram_burst'
        selected = saved.frame(0)
        assert 'durable_frames' not in selected.metadata and 'recording_mode' not in selected.metadata
        assert selected.metadata['sequence_source']['container_provenance']['durable_frames'] == 8
        assert all(np.array_equal(saved.array[i], frames[i].data) and saved.frame(i).identity == frames[i].identity
                   for i in range(8))


def test_preflight_is_read_only_and_constructor_rechecks_without_silent_cap(tmp_path, monkeypatch):
    destination = tmp_path / 'absent' / 'burst'
    preview = module.recording_preflight(destination, owned(0), 300, recording_mode='ram_burst')
    assert preview['allowed'] and preview['max_frames'] == 300
    memory = preview['memory_preflight']
    assert memory['required_bytes'] > 300 * owned(0).data.nbytes
    assert not destination.parent.exists()
    monkeypatch.setattr(module, 'available_memory_bytes', lambda: memory['required_bytes'] - 1)
    with pytest.raises(MemoryError, match='frame count unchanged'):
        burst(destination, 300)
    assert not destination.parent.exists()


@pytest.mark.parametrize('end', ['stop', 'duration', 'epoch', 'borrowed', 'duplicate', 'memory'])
def test_burst_admission_end_persists_valid_prefix(tmp_path, end):
    recorder = burst(tmp_path / end, duration_s=.03 if end == 'duration' else None)
    first = owned(0)
    assert recorder.submit(first)
    if end == 'stop':
        recorder.stop()
    elif end == 'duration':
        until(lambda: recorder.stop_event.is_set())
    else:
        if end == 'epoch':
            candidate = Frame(np.ones((3, 4), np.uint16), dict(owned(1).metadata, stream_epoch=3))
        elif end == 'borrowed':
            candidate = Frame(np.frombuffer(bytearray(24), dtype=np.uint16).reshape(3, 4), dict(owned(1).metadata))
        elif end == 'duplicate':
            candidate = first
        else:
            class NoSpace(list):
                def append(self, value):
                    raise MemoryError('allocation fixture')
            recorder._ram_frames = NoSpace(recorder._ram_frames)
            candidate = owned(1)
        assert not recorder.submit(candidate)
    finish(recorder)
    with module.load_sequence(recorder.path) as saved:
        assert saved.frame_count == 1 and np.all(saved.array[0] == 0)
        assert saved.metadata['expected_frames'] == 8
        assert saved.metadata['completed'] is (end == 'duration')
    assert recorder.queue.unfinished_tasks == 0


def test_failed_burst_retains_all_frames_and_retry_preserves_original_output(tmp_path):
    class Failure(module.SequenceWriter):
        def checkpoint(self):
            raise OSError('permanent fsync fixture')
    recorder = burst(tmp_path / 'partial', writer_factory=Failure)
    frames = [owned(i) for i in range(8)]
    for frame in frames:
        assert recorder.submit(frame)
    recorder.release_persistence()
    until(lambda: recorder.status()['can_retry'])
    assert not recorder.done.is_set() and recorder.status()['volatile_frames'] == 8
    previous = {path.name: path.read_bytes() for path in recorder.directory.iterdir()}
    with pytest.raises(FileExistsError):
        recorder.retry(recorder.directory)
    recorder._writer_factory = module.SequenceWriter
    recorder.retry(tmp_path / 'recovered')
    assert recorder.done.wait(5)
    assert recorder.status()['completed'] and recorder.status()['retained_frames'] == 0
    assert {path.name: path.read_bytes() for path in (tmp_path / 'partial').iterdir()} == previous
    with module.load_sequence(recorder.path) as saved:
        assert saved.metadata['retry_of'] == str(tmp_path / 'partial' / 'sequence.npy')
        assert 'fsync fixture' in saved.metadata['previous_persistence_error']
        assert all(saved.frame(i).identity == frames[i].identity and np.all(saved.array[i] == i) for i in range(8))


def test_abandon_only_after_writer_stops_and_only_after_receipt_saved(tmp_path, monkeypatch):
    gate = threading.Event()
    def failure(*args, **kwargs):
        assert gate.wait(5)
        raise OSError('cannot open output')
    recorder = burst(tmp_path / 'abandon', writer_factory=failure)
    recorder.submit(owned(0))
    recorder.stop()
    recorder.release_persistence()
    with pytest.raises(ValueError, match='persistence has stopped'):
        recorder.abandon()
    gate.set()
    until(lambda: recorder.status()['can_abandon'])
    # Writer construction failed before mkdir; abandonment creates only its receipt folder.
    original = module.atomic_json
    monkeypatch.setattr(module, 'atomic_json', lambda *args: (_ for _ in ()).throw(OSError('receipt full')))
    with pytest.raises(OSError, match='receipt full'):
        recorder.abandon()
    assert recorder.status()['retained_frames'] == 1 and not recorder.done.is_set()
    monkeypatch.setattr(module, 'atomic_json', original)
    path = recorder.abandon()
    assert json.loads(path.read_text())['abandoned_frames'] == 1
    assert recorder.done.is_set() and recorder.status()['phase'] == 'abandoned'
    assert recorder.status()['retained_frames'] == 0


def test_sequential_header_and_frame_short_writes_reopen_exactly(tmp_path, monkeypatch):
    original = Path.open
    handles = []
    class ShortFile:
        def __init__(self, stream):
            self.stream = stream
            handles.append(self)
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def write(self, value):
            return self.stream.write(value[:3])
    def opened(path, mode='r', *args, **kwargs):
        value = original(path, mode, *args, **kwargs)
        return ShortFile(value) if path.name == 'sequence.npy' and mode == 'x+b' else value
    monkeypatch.setattr(Path, 'open', opened)
    recorder = burst(tmp_path / 'short', 3)
    for i in range(3):
        recorder.submit(owned(i))
    finish(recorder)
    assert handles[0].closed
    with module.load_sequence(recorder.path) as saved:
        assert [saved.array[i, 0, 0] for i in range(3)] == [0, 1, 2]


@pytest.mark.parametrize('fault', ['open', 'header', 'truncate', 'partial_frame'])
def test_sequential_storage_failures_retain_owned_burst(tmp_path, monkeypatch, fault):
    original = Path.open
    handles = []
    class FailingFile:
        def __init__(self, stream):
            self.stream = stream
            handles.append(self)
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def write(self, value):
            if fault == 'header':
                return 0
            if fault == 'partial_frame' and self.stream.tell() >= 128 + 24:
                if self.stream.tell() == 128 + 24:
                    return self.stream.write(value[:2])
                raise OSError('partial pixel write')
            return self.stream.write(value)
        def truncate(self, size):
            if fault == 'truncate':
                raise OSError('disk allocation failed')
            return self.stream.truncate(size)
    def opened(path, mode='r', *args, **kwargs):
        if path.name == 'sequence.npy' and mode == 'x+b':
            if fault == 'open':
                raise OSError('cannot open data')
            return FailingFile(original(path, mode, *args, **kwargs))
        return original(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', opened)
    recorder = burst(tmp_path / fault, 3)
    for i in range(3):
        recorder.submit(owned(i))
    recorder.release_persistence()
    until(lambda: recorder.status()['can_retry'])
    assert recorder.status()['retained_frames'] == 3 and not recorder.done.is_set()
    assert all(handle.closed for handle in handles)
    if fault == 'partial_frame':
        with module.load_sequence(recorder.path) as saved:
            assert saved.frame_count == 1 and np.all(saved.array[0] == 0)
    recorder.abandon()


def test_empty_message_memory_error_keeps_named_failure_and_recovery(tmp_path):
    class Failure(module.SequenceWriter):
        def checkpoint(self):
            raise MemoryError
    recorder = burst(tmp_path / 'oom', 1, writer_factory=Failure)
    assert recorder.submit(owned(0))
    recorder.release_persistence()
    until(lambda: recorder.status()['can_retry'])
    assert recorder.status()['error'] == 'MemoryError'
    assert recorder.status()['retained_frames'] == 1
    assert not recorder.status()['completed']
    assert json.loads(recorder.path.with_suffix('.npy.json').read_text())['error'] == 'MemoryError'
    recorder.abandon()


def test_reopen_unavailable_does_not_complete_or_release_ram(tmp_path, monkeypatch):
    original = module.load_sequence
    monkeypatch.setattr(module, 'load_sequence', lambda *args: (_ for _ in ()).throw(OSError('read denied')))
    recorder = burst(tmp_path / 'read', 1)
    recorder.submit(owned(0))
    recorder.release_persistence()
    until(lambda: recorder.status()['can_retry'])
    result = recorder.status()
    assert result['readable_frames'] is None and result['durable_frames'] == 1
    assert result['retained_frames'] == 1 and not result['completed']
    assert not result['save_reopen_verified'] and 'read denied' in result['reopen_error']
    monkeypatch.setattr(module, 'load_sequence', original)
    recorder.abandon()


@pytest.mark.parametrize('kind', ['large_view', 'writable_base', 'writable_owner'])
def test_admission_rejects_hidden_or_writable_backing_storage(tmp_path, kind):
    owner = np.ones(1024 * 1024 if kind == 'large_view' else 12, np.uint16)
    if kind == 'writable_owner':
        owner.shape = (3, 4)
        frame = Frame(owner, dict(owned(0).metadata))
        owner.flags.writeable = True
    else:
        frame = Frame(owner[:12].reshape(3, 4), dict(owned(0).metadata))
    recorder = burst(tmp_path / kind, 1)
    assert not recorder.submit(frame)
    assert recorder.status()['retained_bytes'] == recorder.status()['admitted_frames'] == 0
    assert recorder.status()['rejected_frames'] == 1
    finish(recorder)
    assert not recorder.status()['completed']
    assert recorder.status()['max_frames'] == 1
    with module.load_sequence(recorder.path) as saved:
        assert saved.frame_count == 0 and saved.metadata['partial']
