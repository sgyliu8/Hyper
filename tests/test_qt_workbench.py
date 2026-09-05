"""Offline Qt contracts; no producer, serial or real camera is opened."""
from concurrent.futures import Future
import time
import numpy as np
import pytest
from PySide6 import QtCore
from hyperlab.io import Cube, make_synthetic_cube
from hyperlab.ui.workbench import Workbench
from hyperlab.ui.view import roi_rect, bayer_cell_rgb
from hyperlab.acquisition.frame import Frame
from hyperlab.acquisition.sequence import SequenceWriter


@pytest.fixture
def window(qtbot, tmp_path):
    workbench = Workbench()
    workbench.output_dir = tmp_path
    qtbot.addWidget(workbench)
    return workbench


def test_rgb_roi_available_but_not_sam(window, qtbot):
    cube = Cube(np.full((24, 32, 3), 17, np.uint8),
                {'data_level': 'raw_frame', 'pixel_format': 'RGB8', 'channel_labels': ['R','G','B'], 'data_source':'LIVE'})
    window.set_cube(cube)
    assert window.display_mode == 'REPLAY'
    assert not window.analysis_buttons['spectral_angle'].isEnabled()
    window.analyze_rois()
    qtbot.waitUntil(lambda: bool(window.roi_results))
    np.testing.assert_equal(window.roi_results[0]['mean'], [17,17,17])


def test_roi_coordinates_survive_zoom_pan_band(window):
    window.set_cube(make_synthetic_cube())
    window.rois[0].setPos((8, 5))
    window.rois[0].setSize((12, 10))
    before = window.rectangles()
    window.plot.setRange(xRange=(3,22), yRange=(2,19), padding=0)
    window.band.setValue(5)
    assert window.rectangles() == before
    assert before[0] == (8,5,20,15)
    assert roi_rect((-1.2, 2), (5, 3), (10,10)) == (0,2,4,5)


def test_one_plane_gate_and_product_source(window):
    original = make_synthetic_cube()
    window.set_cube(original)
    result = {'data':np.ones(original.shape[:2]), 'valid_mask':np.ones(original.shape[:2],bool), 'metadata':{'operation':'fixture'}}
    window.show_product(result, original)
    assert window.product_source is original
    window.set_cube(Cube(np.ones((8,9,1),np.uint16), {'data_level':'raw_frame','pixel_format':'BayerRG12'}))
    assert window.product is None
    assert not window.analysis_buttons['pca'].isEnabled()
    assert not window.analysis_buttons['ratio'].isEnabled()


def test_bayer_display_requires_evidenced_phase():
    raw = np.array([[100,20],[40,10]],np.uint16)
    with pytest.raises(ValueError, match='ReverseX'):
        bayer_cell_rgb(raw, {'pixel_format':'BayerRG12'})
    image = bayer_cell_rgb(raw, {'pixel_format':'BayerRG12','readback_settings':
                    {'ReverseX':False,'ReverseY':False,'OffsetX':0,'OffsetY':0}})
    np.testing.assert_equal(image, [[[100,30,10]]])
    np.testing.assert_equal(raw, [[100,20],[40,10]])


class FakeSession:
    state = 'ready'
    def __init__(self):
        self.closed = False
        self.saved = None
        self.commands = []
    def status(self):
        return {'state':self.state,'closed':self.closed, 'frame_age_s':0.125,
                'settings':{'ExposureTime':50000}, 'connection_metadata':
                {'readback_settings':{'ExposureTime':49998,'PixelFormat':'BayerRG12','Gain':0}},
                'recording':{'writer_fps':17,'queue_length':1}}
    def poll_events(self): return []
    def latest_frame(self): return None
    def snapshot(self, directory, *, frame): self.saved = frame
    def close(self, wait=False): self.closed = True; return True
    def set_settings(self, settings, mode): self.commands.append('settings')
    def start_preview(self): self.commands.append('start')


def test_stopped_snapshot_retains_exact_raw_frame(window):
    raw = np.arange(80,dtype=np.uint16).reshape(8,10)
    frame = Frame(raw, {'session_id':'offline','sequence':3,'pixel_format':'BayerRG12',
                       'host_monotonic_ns':time.monotonic_ns()})
    window.session = FakeSession()
    window.set_cube(Cube(raw[...,None], {'data_level':'raw_frame'}), live=True)
    window.displayed_frame = frame
    window.display_mode = 'REPLAY'
    window.snapshot()
    assert window.session.saved is frame
    assert window.session.saved.data.ndim == 2


def test_readback_and_metric_schema(window):
    window.last_status = FakeSession().status()
    window.update_status()
    assert '49998' in window.readback_label.text()
    assert '125 ms' in window.metrics_label.text()
    assert 'Writer 17.0' in window.metrics_label.text()
    assert 'writer queue 1' in window.metrics_label.text()


def test_sequence_reopen_via_recorded_npy_and_time_is_not_band(window, qtbot, tmp_path):
    directory = tmp_path/'sequence'
    with SequenceWriter(directory,(8,10),np.uint16,2,metadata={'acquisition_source':'SYNTHETIC','data_source':'SYNTHETIC','pixel_format':'BayerRG12'}) as writer:
        for index in range(2):
            writer.append(np.full((8,10),index,np.uint16), {'valid':True,'session_id':'fixture','sequence':index})
    window.open_path(directory/'sequence.npy')
    qtbot.waitUntil(lambda: not window.task_busy)
    assert window.sequence is not None
    assert window.cube is not None, window.message.text()
    window.band.setValue(1)
    assert window.cube.data[0,0,0] == 1
    assert window.band.maximum() == 1
    window.session = FakeSession()
    window.start_preview()
    assert window.sequence is None
    assert window.band.maximum() == 0


def test_busy_reader_not_closed_by_open(window, tmp_path):
    class Reader:
        closed=False
        def close(self): self.closed=True
    reader=Reader()
    window.sequence=reader
    window.task_busy=True
    window.open_path(tmp_path/'absent.npy')
    assert not reader.closed
    window.synthetic()
    assert not reader.closed
    window.task_busy=False
    window.sequence=None


def test_new_source_resets_axis_and_closes_previous_sequence(window):
    window.set_cube(make_synthetic_cube())
    window.band.setValue(5)
    window.set_cube(make_synthetic_cube())
    assert window.band.value() == 0
    class Reader:
        closed = False
        def close(self): self.closed = True
    reader = Reader()
    window.sequence = reader
    window.synthetic()
    assert reader.closed
    assert window.sequence is None
    assert window.display_mode == 'SYNTHETIC'


def test_close_requests_camera_release_before_window_closes(window):
    window.session=FakeSession()
    window.show()
    assert window.close() is False
    assert window.session.closed
    window.tick()
    assert not window.isVisible()


def test_sidebar_fits_viewport_without_hidden_controls(window, qtbot):
    window.resize(1220, 760)
    window.show()
    qtbot.wait(50)
    assert window.sidebar.width() <= window.side_scroll.viewport().width()
    for index in range(3):
        window.tabs.setCurrentIndex(index)
        qtbot.wait(10)
        page = window.sidebar.currentWidget()
        assert page.width() <= window.side_scroll.viewport().width()


def test_recording_start_is_not_saved_and_failure_remains_visible(window, tmp_path):
    session = FakeSession()
    session.state = 'streaming'
    window.session = session
    window.device_label.setText('Test camera')
    events = [{'kind':'recording','path':str(tmp_path/'sequence.npy'), 'done':False}]
    session.poll_events = lambda: events[:]
    window.tick()
    assert window.recent_list.count() == 0
    events[:] = [{'kind':'recording','path':str(tmp_path/'sequence.npy'), 'done':True,
                 'partial':True, 'save_reopen_verified':True, 'error':'writer overflow'}]
    window.tick()
    assert window.recent_list.count() == 1
    assert window.recent_list.item(0).text().startswith('PARTIAL')
    assert window.message.text() == 'writer overflow'
    assert window.device_label.text() == 'Test camera'
    events[:] = [{'kind':'error', 'error':'snapshot disk full', 'operation':'snapshot'}]
    window.tick()
    assert window.message.text() == 'snapshot disk full'
    assert window.device_label.text() == 'Test camera'
    session.state = 'error'
    events[:] = [{'kind':'error', 'error':'transport timeout'}]
    window.tick()
    assert window.device_label.text() == 'Communication fault'


def test_linked_product_view_is_visible_without_range_feedback(window, qtbot):
    cube = make_synthetic_cube()
    window.set_cube(cube)
    window.show()
    result = {'data':np.ones(cube.shape[:2]), 'metadata':{'operation':'fixture'}}
    window.show_product(result, cube)
    qtbot.wait(20)
    window.fit()
    qtbot.wait(20)
    initial = np.array(window.plot.viewRange())
    qtbot.wait(50)
    assert window.derived_graphics.width() > window.images.width() * .3
    np.testing.assert_allclose(window.plot.viewRange(), initial, rtol=0, atol=1e-6)
    assert not window.derived_plot.getViewBox().state['aspectLocked']
