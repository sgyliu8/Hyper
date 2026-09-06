"""Counter interleaving, bounded timing and display-only sampling contracts."""
import threading
import numpy as np
import pytest

from hyperlab.acquisition.camera import CameraSession
from hyperlab.acquisition.sequence import SequenceRecorder
from hyperlab.io import Cube
from hyperlab.profiling import StageTimings
from hyperlab.ui.view import display_selection
from test_camera_session import StreamingFake, make_backend, wait_until
from test_sequence import frame


def test_render_arrival_replacement_overlaps_rendered_and_is_cumulative():
    permits = threading.Semaphore(0)
    selected, finish = threading.Event(), threading.Event()

    class GatedFake(StreamingFake):
        def fetch(self, timeout):
            if not permits.acquire(timeout=.01):
                raise TimeoutError('Synthetic arrival gate')
            return super().fetch(timeout)

    session = CameraSession('fixture', 'fixture', backend_factory=GatedFake)
    def render():
        held = session.latest_frame()
        selected.set()
        assert finish.wait(3)
        session.mark_displayed(held)
    worker = threading.Thread(target=render)
    try:
        session.start_preview().result(3)
        permits.release()
        wait_until(lambda: session.status()['captured_frames'] == 1)
        worker.start()
        assert selected.wait(3)
        permits.release()
        wait_until(lambda: session.status()['captured_frames'] == 2)
        assert session.status()['mailbox_replacement_events'] == 1
        assert session.status()['displayed_frames'] == 0
        finish.set()
        worker.join(3)
        assert not worker.is_alive()
        latest = session.latest_frame()
        session.mark_displayed(latest)
        session.mark_displayed(latest)
        session.stop_preview().result(3)
        status = session.status()
        assert (status['captured_frames'], status['displayed_frames'], status['mailbox_replacement_events']) == (2, 2, 1)
        assert status['device_frame_gaps'] == 0
        assert 'overlaps displayed_frames' in status['mailbox_replacement_definition']
        assert 'lifetime' in status['counter_scope']
        session.start_preview().result(3)
        assert session.latest_frame() is None
        permits.release()
        wait_until(lambda: session.status()['captured_frames'] == 3)
        session.stop_preview().result(3)
        assert session.status()['stream_epoch'] == 2
        assert session.status()['mailbox_replacement_events'] == 1
        assert session.status()['stage_timings']['stages']['metadata_frame_build']['total_count'] == 3
    finally:
        finish.set()
        if worker.ident is not None:
            worker.join(3)
        assert session.close(wait=True)


def test_timings_are_bounded_and_propagate_exceptions():
    timings = StageTimings(capacity=3)
    assert timings.snapshot()['stages'] == {}
    for milliseconds in (1, 2, 3, 4, 5):
        timings.record('stage', milliseconds * 1_000_000)
    result = timings.snapshot()['stages']['stage']
    assert result['n'] == 3 and result['total_count'] == 5
    assert result['min_ms'] == 3 and result['median_ms'] == 4
    assert result['p95_ms'] == pytest.approx(4.9) and result['max_ms'] == 5
    with pytest.raises(TimeoutError, match='original failure'):
        with timings.measure('wait'):
            raise TimeoutError('original failure')
    assert timings.snapshot()['stages']['wait']['exception_count'] == 1


@pytest.mark.parametrize('mask_kind', ['HW', 'HWK'])
@pytest.mark.parametrize('policy', ['diagnostic', 'quantitative'])
@pytest.mark.parametrize('labels', [['R', 'G', 'B'], ['B', 'G', 'R']])
def test_strided_display_uses_same_raw_coordinates_masks_and_order(mask_kind, policy, labels):
    raw = np.arange(5 * 7 * 3, dtype=np.uint8).reshape(5, 7, 3)
    raw[2, 3, 1] = 255
    raw[0, 0, 0] = 9
    mask = np.ones(raw.shape if mask_kind == 'HWK' else raw.shape[:2], dtype=bool)
    mask[4, 6] = False
    if mask_kind == 'HWK':
        mask[0, 3, 2] = False
    cube = Cube(raw, {'data_level': 'raw_frame', 'channel_labels': labels,
                     'data_ignore_value': 9, 'effective_bits': 8}, mask)
    before = raw.copy()
    timings = StageTimings()
    selected = display_selection(cube, policy=policy, display_stride=(2, 3), diagnostics=False, timings=timings)
    sampled = raw[::2, ::3]
    valid = mask[::2, ::3]
    if mask_kind == 'HW':
        valid = np.broadcast_to(valid[..., None], sampled.shape)
    valid = valid & (sampled != 9)
    if policy == 'quantitative':
        valid &= sampled < 255
    image_valid = np.broadcast_to(valid.all(axis=2)[..., None], sampled.shape)
    expected = np.where(image_valid, sampled, np.nan)
    if labels[0] == 'B':
        expected = expected[..., ::-1]
    np.testing.assert_equal(selected['image'], expected)
    assert selected['image'].flags.c_contiguous
    np.testing.assert_equal(raw, before)
    assert selected['statistics_scope'] == 'strided raw samples'
    assert selected['statistics_sample_count'] == sampled.size
    assert selected['statistics_sample_total'] == raw.size
    assert selected['raw_counts']['total'] == sampled.size
    assert selected['raw_counts']['valid'] == valid.sum()
    assert selected['raw_mean'] == pytest.approx(sampled[valid].mean())
    assert selected['raw_extent'] == [0, 0, 7, 5]
    assert selected['display_stride'] == [2, 3]
    assert selected['display_extent'] == [0, 0, 7, 5]
    assert selected['display_sample_origin_yx'] == [0, 0]
    assert set(timings.snapshot()['stages']) == {'display_validity', 'display_levels', 'display_diagnostics', 'display_selection_total'}


def test_strided_display_can_keep_full_diagnostics_and_default_path():
    raw = np.arange(35, dtype=np.float64).reshape(5, 7, 1)
    raw[1, 1, 0] = np.nan  # This unsampled invalid value must remain in full diagnostics.
    cube = Cube(raw, {'data_level': 'raw_frame'})
    full = display_selection(cube)
    selected = display_selection(cube, display_stride=2)
    np.testing.assert_equal(full['image'], raw[..., 0])
    assert full['raw_counts'] == selected['raw_counts']
    assert full['raw_counts']['invalid'] == 1
    assert selected['raw_mean'] == pytest.approx(np.nanmean(raw))
    assert selected['statistics_scope'] == 'full raw frame'
    assert selected['statistics_sample_count'] == raw.size


@pytest.mark.parametrize('dtype,value,display_dtype', [(np.uint8, 251, np.float32),
    (np.uint16, 65531, np.float32), (np.uint32, 2**31+1, np.float64),
    (np.float64, 2**40+.125, np.float64)])
def test_compact_display_preserves_raw_precision_and_current_frame_validity(dtype, value, display_dtype):
    from hyperlab.ui.view import display_levels
    raw = np.full((5, 7, 3), value, dtype=dtype)
    mask = np.ones(raw.shape, dtype=bool)
    mask[2, 3, 1] = False
    metadata = {'data_level': 'raw_frame', 'channel_labels': ['B', 'G', 'R'], 'sequence': 10}
    cube = Cube(raw, metadata, mask)
    first = display_selection(cube, display_stride=(2, 3), diagnostics=False)
    assert first['image'].dtype == display_dtype and first['image'].flags.c_contiguous
    assert first['image'][0, 0, 0] == value
    assert np.isnan(first['image'][1, 1]).all()
    assert first['raw_counts']['invalid'] == 1 and first['statistics_source']['sequence'] == 10
    assert first['levels'] == display_levels(first['image'], first['valid_mask'])
    second_mask = np.ones(raw.shape, dtype=bool)
    second_mask[4, 6] = False
    second = display_selection(Cube(raw, {**metadata, 'sequence': 11}, second_mask),
                               display_stride=(2, 3), diagnostics=False)
    assert np.isfinite(second['image'][1, 1]).all() and np.isnan(second['image'][2, 2]).all()
    assert second['raw_counts']['invalid'] == 3 and second['statistics_source']['sequence'] == 11
    np.testing.assert_equal(raw, np.full(raw.shape, value, dtype=dtype))


def test_cfa_stride_retains_full_cell_phase_and_odd_offset_rejection():
    raw = np.arange(35, dtype=np.uint16).reshape(5, 7, 1)
    settings = {'ReverseX': False, 'ReverseY': False, 'OffsetX': 0, 'OffsetY': 0}
    cube = Cube(raw, {'data_level': 'raw_frame', 'pixel_format': 'BayerRG12', 'readback_settings': settings})
    selected = display_selection(cube, cfa=True, display_stride=3, diagnostics=False)
    expected = np.stack((raw[:4:2, :6:2, 0],
        (raw[:4:2, 1:6:2, 0].astype(float) + raw[1:4:2, :6:2, 0]) / 2,
        raw[1:4:2, 1:6:2, 0]), axis=2)
    np.testing.assert_equal(selected['image'], expected)
    assert selected['requested_display_stride'] == [3, 3]
    assert selected['display_stride'] == [1, 1]
    assert selected['raw_extent'] == [0, 0, 7, 5]
    assert selected['display_extent'] == [0, 0, 6, 4]
    cube.metadata['readback_settings']['OffsetX'] = 1
    with pytest.raises(ValueError, match='even sensor offsets'):
        display_selection(cube, cfa=True, display_stride=3)


def test_backend_timings_keep_owned_copy_and_requeue_contract(tmp_path, monkeypatch):
    backend, camera, _ = make_backend(tmp_path, monkeypatch)
    try:
        backend.open()
        backend.configure({'ExposureTime': 20000, 'Gain': 0})
        backend.start()
        raw, metadata, _ = backend.fetch()
        assert raw[0, 0] == 0 and camera.buffer.returned
        assert metadata['channel_labels'] is None
        stages = backend.timings.snapshot()['stages']
        assert set(stages) == {'fetch_wait', 'owned_copy_and_shape', 'metadata_and_chunk', 'buffer_requeue'}
        assert all(result['n'] == 1 and result['exception_count'] == 0 for result in stages.values())
    finally:
        backend.close()


def test_writer_profile_retains_durable_prefix_and_accounting(tmp_path):
    recorder = SequenceRecorder(tmp_path / 'profile', frame(0), 3, capacity=3)
    for index in range(3):
        assert recorder.submit(frame(index))
    assert recorder.done.wait(5)
    status = recorder.status()
    assert status['accepted_frames'] == status['written_frames'] == 3
    assert status['completed'] and status['save_reopen_verified']
    stages = status['stage_timings']['stages']
    assert stages['writer_array_copy']['total_count'] == 3
    assert stages['writer_checkpoint']['total_count'] >= 1
