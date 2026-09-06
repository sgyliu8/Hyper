"""Saved ROI templates survive equal raw dimensions, not arbitrary grid resets."""
from copy import deepcopy
import time

import numpy as np
import pytest

from hyperlab.acquisition.frame import Frame
from hyperlab.analysis.regions import make_roi, resolve_roi
from hyperlab.io import Cube, save_cube
from hyperlab.paths import save_config
from hyperlab.ui.workbench import Workbench


class EpochSession:
    def __init__(self, channels=3):
        self.state, self.closed = 'ready', False
        self.channels, self.epoch, self.frame = channels, 0, None

    def set_settings(self, settings, mode):
        pass

    def start_preview(self):
        self.state = 'streaming'; self.epoch += 1
        data = np.full((24,32,3) if self.channels == 3 else (24,32), self.epoch+40, np.uint16)
        self.frame = Frame(data, {'session_id':'offline-transition', 'stream_epoch':self.epoch,
            'sequence':1, 'host_monotonic_ns':time.monotonic_ns(), 'data_level':'raw_frame',
            'pixel_format':'RGB8' if self.channels == 3 else 'BayerRG12',
            'channel_labels':['R','G','B'] if self.channels == 3 else None, 'effective_bits':12})

    def stop_preview(self):
        self.state = 'ready'

    def poll_events(self):
        return []

    def status(self):
        return {'state':self.state, 'closed':self.closed, 'has_current_frame':self.frame is not None}

    def latest_frame(self):
        return self.frame

    def mark_displayed(self, frame):
        pass

    def close(self, wait=False):
        self.closed = True


@pytest.fixture
def window(qtbot, tmp_path):
    shape = (24,32)
    definitions = [make_roi(shape, geometry, name=name, role=role, roi_id=f'fixture-region-{i}', revision=2,
                            visible=role != 'exclude')
        for i,(name,role,geometry) in enumerate([
            ('Reference','reference',{'type':'rectangle','bounds':[2,2,8,9]}),
            ('Suspect','target',{'type':'rectangle','bounds':[12,3,23,12]}),
            ('Glare exclude','exclude',{'type':'rectangle','bounds':[16,4,19,8]}),
            ('Profile','target',{'type':'strip','points':[[.5,16.5],[29.5,16.5]],'width_px':3})])]
    path = save_cube(Cube(np.ones((*shape,3),np.uint16), {'data_level':'raw_frame','units':'DN',
        'pixel_format':'RGB8','channel_labels':['R','G','B'],'data_source':'SYNTHETIC'}),tmp_path/'saved.npy')
    save_config({'schema_version':1,'workspace':str(tmp_path/'workspace'),
        'ui':{'last_path':str(path),'roi_definitions':definitions,'reference_roi_id':definitions[0]['roi_id']}})
    result = Workbench(); qtbot.addWidget(result)
    qtbot.waitUntil(lambda: result.cube is not None and not result.task_busy, timeout=5000)
    result.roi_timer.stop()
    assert result.regions() == definitions
    return result


@pytest.mark.parametrize('channels', [3,1])
def test_saved_definitions_survive_start_preview_and_next_epoch(window, channels):
    expected, reference = deepcopy(window.regions()), window.reference_roi_id
    window.session = EpochSession(channels)
    for epoch in (1,2):
        window.start_preview()
        assert window.cube is None
        window.tick()
        assert window.cube.metadata['stream_epoch'] == epoch
        assert window.regions() == expected
        assert window.reference_roi_id == window.reference_roi.currentData() == reference
        assert window.regions()[2]['role'] == 'exclude'
        assert window.regions()[3]['geometry']['type'] == 'strip'
        assert 'verify placement' in window.message.text()
        window.stop_preview(); window.tick()


def test_channel_axis_change_preserves_raw_geometry_without_a_camera_session(window):
    expected = deepcopy(window.regions())
    window.set_cube(Cube(np.ones((24,32,1),np.uint16), {'data_level':'raw_frame','pixel_format':'BayerRG12'}))
    assert window.regions() == expected
    assert window.feature_last.maximum() == 0


def test_start_invalidates_completed_science_result_without_redefining_rois(window, qtbot):
    window.analyze_roi_features('pairs')
    qtbot.waitUntil(lambda: not window.task_busy, timeout=5000)
    assert window.science_result is not None and window.roi_results
    expected = deepcopy(window.regions())
    window.session = EpochSession()
    window.start_preview(); window.tick()
    assert window.science_result is None
    assert window.roi_results == [] and window.roi_result_context is None
    assert window.roi_source is None and window.plot_source is None
    assert window.regions() == expected


def test_new_raw_dimensions_use_new_generic_definitions_and_explicit_feedback(window):
    old = deepcopy(window.regions())
    window.set_cube(Cube(np.ones((30,40,3),np.uint16), {'data_level':'raw_frame','channel_labels':['R','G','B']}))
    current = window.regions()
    assert {record['roi_id'] for record in current}.isdisjoint(record['roi_id'] for record in old)
    assert [record['name'] for record in current] == ['ROI A','ROI B','ROI C','ROI D']
    assert all(record['geometry']['type'] == 'rectangle' for record in current)
    assert all(record['coordinate_frame']['shape_hw'] == [30,40] for record in current)
    assert all(record['visible'] and record['included'] for record in current)
    for record in current:
        resolve_roi((30,40),record)
    assert 'Raw image dimensions changed' in window.message.text()
    assert 'new default ROIs' in window.message.text()


def test_file_open_completion_keeps_dimension_change_feedback(window, qtbot, tmp_path):
    path = save_cube(Cube(np.ones((30,40,3), np.uint16), {'data_level':'raw_frame',
        'data_source':'SYNTHETIC', 'channel_labels':['R','G','B']}), tmp_path/'different-size.npy')
    window.open_path(path)
    qtbot.waitUntil(lambda: not window.task_busy, timeout=5000)
    assert window.cube.shape == (30,40,3)
    assert 'Reopened' in window.message.text()
    assert 'Raw image dimensions changed; new default ROIs created.' in window.message.text()
