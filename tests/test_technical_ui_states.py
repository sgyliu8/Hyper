"""Independent camera/view/result semantics without any native device calls."""
import time
from types import SimpleNamespace

import numpy as np
import pytest

from hyperlab.acquisition.frame import Frame
from hyperlab.io import Cube
from hyperlab.plots import PlotSpec, source_identity
from hyperlab.ui.presentation import observation_label
from hyperlab.ui.workbench import Workbench


@pytest.fixture
def window(qtbot):
    result = Workbench()
    qtbot.addWidget(result)
    return result


def capture(value=10, sequence=7):
    return Cube(np.full((8, 10, 1), value, np.uint16),
                {'data_level': 'raw_frame', 'data_source': 'LIVE', 'pixel_format': 'BayerRG12',
                 'channel_labels': None, 'sequence': sequence, 'host_utc': '2026-09-06T11:00:00Z'})


def test_saved_real_origin_and_disconnected_camera_are_independent(window):
    window.set_cube(capture())
    window.last_status = {'state': 'disconnected', 'capture_fps': 35., 'display_fps': 22.,
                          'frame_age_s': 999., 'preview_dropped': 123}
    window.update_status()
    window.update_controls()
    assert window.display_mode == 'REPLAY'
    assert window.device_label.text() == 'Camera: Disconnected'
    assert window.mode_label.text() == 'Viewing: Saved / retained frame'
    assert 'Real camera capture' in window.source_label.text()
    assert 'frame 7' in window.source_label.text()
    assert '2026-09-06' in window.source_label.text()
    assert 'LIVE' not in window.source_label.text()
    assert window.metrics_label.isHidden() and not window.metrics_label.text()
    assert 'stream None' not in window.analysis_label.text()


def test_frozen_frame_age_is_separate_from_latest_capture_age(window):
    cube = capture()
    window.set_cube(cube, live=True)
    window.display_mode = 'FROZEN'
    window.displayed_frame = Frame(cube.data[..., 0],
        dict(cube.metadata, host_monotonic_ns=time.monotonic_ns() - 2_000_000_000))
    window.last_status = {'state': 'streaming', 'capture_fps': 30., 'display_fps': 0., 'frame_age_s': .02}
    window.update_status()
    text = window.metrics_label.text()
    assert 'Latest capture age 20 ms' in text
    assert 'Displayed frame age 20' in text
    assert 'Writer' not in text and 'drop' not in text


def test_new_view_does_not_become_live_just_because_camera_streams(window):
    latest = Frame(np.ones((8, 10), np.uint16),
                   {'session_id': 'fixture', 'stream_epoch': 1, 'sequence': 8,
                    'host_monotonic_ns': time.monotonic_ns(), 'pixel_format': 'BayerRG12'})
    status = {'state': 'streaming', 'closed': False}
    session = SimpleNamespace(state='streaming', poll_events=lambda: [], status=lambda: status,
                              latest_frame=lambda: latest, close=lambda **kw: status.update(closed=True))
    window.session = session
    saved = capture(value=22)
    window.set_cube(saved)
    window.tick()
    assert window.cube is saved and window.display_mode == 'REPLAY'
    assert 'Previewing' in window.device_label.text()
    assert window.metrics_label.isHidden()
    window.session = None


def test_pending_method_retains_completed_plot_and_identity(window):
    cube = capture()
    window.set_cube(cube)
    spec = PlotSpec('lines', 'Completed ROI', 'Sensor plane', 'Mean (DN)',
                    source=source_identity(cube), metadata={'analysis_version': 4},
                    series=[{'x': [0], 'y': [10.], 'name': 'A', 'color': '#c47a28'}])
    window.draw_plot(spec)
    original = window.analysis_label.text()
    window.task_busy = True
    window.analysis_method.setCurrentIndex(window.analysis_method.findData('normalized_difference'))
    window.plot_mode.blockSignals(True)
    window.plot_mode.setCurrentIndex(1)
    window.plot_mode.blockSignals(False)
    window.update_chart(window.image.image)
    assert window.plot_spec is spec
    assert window.analysis_label.text() == original
    assert 'ROI revision 4' in original
    window.task_busy = False


def test_presentation_does_not_invent_stream_or_timestamp():
    assert observation_label({'data_source': 'LIVE', 'sequence': 2}) == 'Real camera capture · frame 2'
    assert observation_label({'data_source': 'SYNTHETIC'}) == 'Synthetic example'


def test_open_replay_during_capture_keeps_owner_and_explicit_return(window, qtbot, tmp_path):
    from hyperlab.io import save_cube
    path = tmp_path / 'saved.npy'
    save_cube(capture(22), path)
    status = {'state': 'streaming', 'closed': False}
    latest = Frame(np.ones((8, 10), np.uint16),
                   {'session_id': 'fixture', 'stream_epoch': 1, 'sequence': 8,
                    'host_monotonic_ns': time.monotonic_ns(), 'pixel_format': 'BayerRG12'})
    session = SimpleNamespace(state='streaming', poll_events=lambda: [], status=lambda: status,
                              latest_frame=lambda: latest, close=lambda **kw: status.update(closed=True))
    window.session, window.follow_camera = session, True
    window.open_path(path)
    qtbot.waitUntil(lambda: not window.task_busy)
    window.tick()
    assert window.cube.data[0, 0, 0] == 22
    assert window.session is session and not window.follow_camera
    assert window.preview_button.text() == 'Return to live'
    window.start_preview()
    assert window.session is session and window.follow_camera
    window.session = None


def test_preview_sampling_keeps_raw_cursor_and_full_detail(window):
    cube = Cube(np.arange(645*965, dtype=np.uint32).reshape(645, 965, 1),
                {'data_level': 'raw_frame', 'data_source': 'LIVE'})
    window.display_mode = 'LIVE'
    window.set_cube(cube, live=True)
    assert window.display_selection['display_stride'] != [1, 1]
    assert 'Overview samples' in window.axis_label.text()
    assert 'Strided raw samples' in window.quality_label.text()
    window.one_to_one()
    assert window.image.image.shape == cube.shape[:2]
    assert window.cube is cube
