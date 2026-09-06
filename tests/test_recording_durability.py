import json
import threading

import numpy as np
import pytest

from hyperlab.acquisition.frame import Frame
from hyperlab.acquisition.sequence import SequenceRecorder, SequenceWriter, load_sequence
from hyperlab.acquisition import sequence as module


def owned(index):
    return Frame(np.full((3, 4), index, np.uint16), {'valid': True, 'session_id': 'synthetic',
        'stream_epoch': 2, 'sequence': index, 'frame_id': index + 100,
        'pixel_format': 'Mono16', 'readback_settings': {'ExposureTime': 20000},
        'data_source': 'SYNTHETIC'})


@pytest.mark.parametrize('permanent', [False, True])
def test_checkpoint_after_eighth_copy_reconciles_with_readable_prefix(tmp_path, permanent):
    admitted = threading.Event()
    failures = []

    class Fault(SequenceWriter):
        def checkpoint(self):
            if self.count == 8 and (permanent or not failures):
                failures.append(1)
                raise OSError('injected data checkpoint')
            super().checkpoint()

    def factory(*args, **kwargs):
        assert admitted.wait(5)
        return Fault(*args, **kwargs)

    recorder = SequenceRecorder(tmp_path / 'record', owned(0), 8, capacity=8, writer_factory=factory)
    for i in range(8):
        assert recorder.submit(owned(i))
    admitted.set()
    assert recorder.done.wait(5)
    recorder.thread.join(5)
    with load_sequence(recorder.path) as saved:
        expected = 0 if permanent else 8
        assert saved.frame_count == expected
        assert recorder.status()['written_frames'] == expected
        assert recorder.status()['explicitly_failed_frames'] == 8 - expected
        assert saved.metadata['written_frames'] == expected
        assert saved.metadata['explicitly_failed_frames'] == 8 - expected
        assert saved.metadata['partial'] and 'injected' in saved.metadata['error']
        assert all(np.all(saved.array[i] == i) and saved.frame(i).identity == owned(i).identity
                   for i in range(saved.frame_count))
    assert recorder.queue.unfinished_tasks == 0


@pytest.mark.parametrize('mapped', [True, False])
@pytest.mark.parametrize('point', ['manifest_entry', 'manifest_lost_ack', 'final_entry', 'final_lost_ack', 'close'])
def test_publication_and_close_faults_never_shrink_recovered_prefix(tmp_path, monkeypatch, mapped, point):
    gate = threading.Event()
    original_publish = module.atomic_json
    failures = []
    publications = []

    def publish(path, metadata):
        selected = (metadata.get('frame_count') == 8 and
                    (point.startswith('manifest') or point.startswith('final') and metadata.get('ended_at')))
        fail = selected and not failures
        if fail:
            failures.append(point)
        if fail and point.endswith('entry'):
            raise OSError('publication fixture')
        original_publish(path, metadata)
        if path.name == 'sequence.npy.json':
            publications.append(metadata['frame_count'])
        if fail:
            raise OSError('published but acknowledgement lost')

    monkeypatch.setattr(module, 'atomic_json', publish)
    class Fault(SequenceWriter):
        def _close_storage(self):
            super()._close_storage()
            if point == 'close' and not failures:
                failures.append(point)
                raise OSError('closed but acknowledgement lost')

    def factory(*args, **kwargs):
        assert gate.wait(5)
        return Fault(*args, mapped=mapped, **kwargs)
    recorder = SequenceRecorder(tmp_path / 'record', owned(0), 8, capacity=8, writer_factory=factory)
    for i in range(8):
        assert recorder.submit(owned(i))
    gate.set()
    assert recorder.done.wait(5)
    with load_sequence(recorder.path) as saved:
        assert saved.frame_count == recorder.status()['durable_frames'] == recorder.status()['written_frames'] == 8
        assert recorder.status()['readable_frames'] == 8
        assert recorder.status()['explicitly_failed_frames'] == 0
        assert not saved.metadata['completed'] and saved.metadata['partial']
        assert not recorder.status()['completed'] and recorder.status()['partial']
        assert saved.metadata['error'] and recorder.status()['error']
        assert all(np.all(saved.array[i] == i) for i in range(8))
    assert publications == sorted(publications)


def test_repeated_lost_manifest_ack_keeps_eight_readable_and_counted(tmp_path, monkeypatch):
    original = module.atomic_json
    def lost(path, metadata):
        original(path, metadata)
        if metadata.get('frame_count') == 8:
            raise OSError('lost every publication acknowledgement')
    monkeypatch.setattr(module, 'atomic_json', lost)
    gate = threading.Event()
    def factory(*args, **kwargs):
        assert gate.wait(5)
        return SequenceWriter(*args, **kwargs)
    recorder = SequenceRecorder(tmp_path / 'record', owned(0), 8, capacity=8, writer_factory=factory)
    for i in range(8):
        recorder.submit(owned(i))
    gate.set()
    assert recorder.done.wait(5)
    with load_sequence(recorder.path) as saved:
        assert saved.frame_count == recorder.status()['durable_frames'] == 8
        assert recorder.status()['explicitly_failed_frames'] == 0
        assert not recorder.status()['completed'] and 'lost' in recorder.status()['error']


def test_unavailable_reopen_is_unknown_not_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'load_sequence', lambda *args: (_ for _ in ()).throw(OSError('read denied')))
    recorder = SequenceRecorder(tmp_path / 'record', owned(0), 1)
    recorder.submit(owned(0))
    assert recorder.done.wait(5)
    assert recorder.status()['readable_frames'] is None
    assert recorder.status()['durable_frames'] == 1
