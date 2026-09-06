"""Deterministic offline regressions for the Phase 3 review; no native runtime."""
import threading
import time
import numpy as np
import pytest

from hyperlab.acquisition.camera import CameraSession
from hyperlab.acquisition.sequence import SequenceRecorder, SequenceWriter
from hyperlab.adapters.gentl import _attribute
from hyperlab.io import Cube
from hyperlab.ui.workbench import Workbench
from test_camera_session import StreamingFake, wait_until
from test_sequence import frame


def test_f1_static_redraw_does_not_create_time_samples(qtbot, tmp_path):
    window = Workbench()
    qtbot.addWidget(window)
    window.output_dir = tmp_path
    window.set_cube(Cube(np.full((20, 24, 1), 12, np.uint16),
                         {'data_level': 'raw_frame', 'data_source': 'LIVE'}))
    window.plot_mode.setCurrentIndex(1)
    for _ in range(20):
        window.update_chart(window.image.image)
    assert len(window.temporal_plot) == 0
    assert window.display_mode == 'REPLAY'


def test_f2_restart_silence_cannot_use_old_template(tmp_path):
    class GatedCamera(StreamingFake):
        paused = False
        def fetch(self, timeout):
            if self.paused:
                time.sleep(.005)
                raise TimeoutError('injected new-stream silence')
            data, metadata, payload = super().fetch(timeout)
            if self.metadata.get('readback_settings', {}).get('PixelFormat') == 'RGB8':
                data = np.repeat(data[..., None], 3, axis=2).astype(np.uint8)
                metadata['pixel_format'] = 'RGB8'
            return data, metadata, payload
    backend = GatedCamera()
    session = CameraSession('fixture', 'fixture', backend_factory=lambda *a: backend)
    try:
        session.start_preview().result(5)
        wait_until(lambda: session.latest_frame() is not None)
        old = session.latest_frame()
        session.stop_preview().result(5)
        backend.paused = True
        session.set_settings({'PixelFormat': 'RGB8', 'ExposureTime': 20000}).result(5)
        session.start_preview().result(5)
        assert session.latest_frame() is None
        with pytest.raises(ValueError, match='frame|epoch'):
            session.start_recording(tmp_path/'stale', 2).result(5)
        assert not (tmp_path/'stale').exists()
        assert session.status()['capture_fps'] == 0
        backend.index = 0  # Device frame IDs can reset across streams.
        backend.paused = False
        wait_until(lambda: session.latest_frame() is not None)
        fresh = session.latest_frame()
        assert fresh.identity != old.identity
        assert fresh.metadata['stream_epoch'] > old.metadata['stream_epoch']
        assert fresh.data.ndim == 3 and fresh.data.dtype == np.uint8
    finally:
        session.close(wait=True)


def test_f3_optional_absent_is_not_transport_timeout():
    class Optional:
        @property
        def timeout(self):
            raise TimeoutError('GenCP read deadline')
    assert _attribute(Optional(), 'not_supported') is None
    with pytest.raises(TimeoutError, match='GenCP'):
        _attribute(Optional(), 'timeout')


def test_f4_admission_and_finalization_are_atomic(tmp_path):
    admission_entered, admit = threading.Event(), threading.Event()
    finalizing = threading.Event()
    class ObservedWriter(SequenceWriter):
        def finish(self, **kwargs):
            finalizing.set()
            return super().finish(**kwargs)
    recorder = SequenceRecorder(tmp_path/'race', frame(0), 10, writer_factory=ObservedWriter)
    original_put = recorder.queue.put_nowait
    def paused_put(value):
        admission_entered.set()
        assert admit.wait(5)
        original_put(value)
    recorder.queue.put_nowait = paused_put
    result = []
    producer = threading.Thread(target=lambda: result.append(recorder.submit(frame(1))))
    producer.start()
    assert admission_entered.wait(5)
    stopper = threading.Thread(target=recorder.stop)
    stopper.start()
    # Old implementation finalizes while put is parked. With atomic admission,
    # stop waits for the admitted operation and then drains it.
    finalizing.wait(.2)
    admit.set()
    producer.join(5)
    stopper.join(5)
    assert recorder.done.wait(5)
    assert result == [True]
    assert recorder.accepted == recorder.written == 1
    assert not recorder.submit(frame(2))


def test_f5_ignore_value_does_not_change_image_limits(qtbot, tmp_path):
    window = Workbench()
    qtbot.addWidget(window)
    window.output_dir = tmp_path
    values = np.full((20, 24, 1), 10., dtype=np.float64)
    values[:3] = -9999
    window.set_cube(Cube(values, {'data_ignore_value': -9999, 'units': 'DN'}))
    assert window.levels[0] >= 10
