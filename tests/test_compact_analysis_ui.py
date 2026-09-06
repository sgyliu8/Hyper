"""Usable task actions and explicit per-panel support without a camera."""
from copy import deepcopy
import json
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6 import QtCore, QtWidgets as W

from hyperlab.io import Cube
from hyperlab.analysis.regions import make_roi
from hyperlab.plots import profile_bin_text
from hyperlab.ui.workbench import Workbench


def source():
    return Cube(np.arange(432, dtype=float).reshape(12,12,3),
        {'data_level':'raw_frame','data_source':'SYNTHETIC','units':'DN','channel_labels':['R','G','B']})


def test_actions_reachable_with_eight_rois_and_stop_in_every_tab(qtbot):
    window = Workbench(); qtbot.addWidget(window); window.set_cube(source())
    for i in range(6):
        window.add_roi(name=f'Added {i}')
    window.roi_timer.stop()
    window.tabs.setCurrentIndex(1)
    window.analysis_method.setCurrentIndex(window.analysis_method.findData('normalized_difference'))
    window.show()
    for width,height in ((1220,820),(1920,1080)):
        window.resize(width,height); qtbot.wait(5)
        for widget in (window.run_button,window.results_button,window.findChild(W.QToolButton,'analysis_export')):
            rect = QtCore.QRect(widget.mapTo(window,QtCore.QPoint()),widget.size())
            assert window.rect().contains(rect) and widget.isVisibleTo(window)
            assert not window.side_scroll.isAncestorOf(widget)
    window.session = SimpleNamespace(state='streaming')
    for index in (0,1,2):
        window.tabs.setCurrentIndex(index); window.update_controls()
        assert window.stop_button.isEnabled() and window.stop_button.isVisibleTo(window)
    window.session = None


def test_stored_feature_identity_changes_without_changing_integer_values(qtbot):
    window = Workbench(); qtbot.addWidget(window); window.set_cube(source())
    assert window.pair_a.text() == '0 · R' and window.pair_b.text() == '1 · G'
    window.pair_a.setValue(2)
    assert window.pair_a.value() == 2 and window.pair_a.text() == '2 · B'
    data = Cube(source().data, {'data_level':'spectral_cube','units':'DN','data_source':'SYNTHETIC',
        'wavelengths':[.45,.55,.65],'wavelength_units':'um','wavelength_source':'Synthetic fixture'})
    window.set_cube(data)
    assert window.pair_a.text() == '2 · 0.65 um'
    assert window.feature_first.text() == '0 · 0.45 um'
    assert window.trace_channel.itemText(1) == '1 · 0.55 um'


def test_use_off_strip_preserves_amplitude_support_and_original_empty_bins(qtbot):
    window = Workbench(); qtbot.addWidget(window); cube=source(); window.set_cube(cube)
    window.roi_records[1] = make_roi((12,12),
        {'type':'strip','points':[[.5,10.5],[10.5,10.5]],'width_px':.5},name='Inspection strip')
    window.rebuild_roi_graphics(); window.roi_included[1].setChecked(False)
    window.add_roi(record=make_roi((12,12), {'type':'rectangle','bounds':[0,0,3,12]}, role='exclude'))
    window.roi_summary.setCurrentIndex(window.roi_summary.findData('median'))
    window.roi_support.setCurrentIndex(window.roi_support.findData('common'))
    window.roi_changed(); window.roi_timer.stop()
    window.analyze('reference_rmse')
    qtbot.waitUntil(lambda:not window.task_busy,timeout=10000)
    amplitude = window.plot_spec
    values=deepcopy(amplitude.series)
    assert len(amplitude.series) == 1 and amplitude.metadata['support'] == 'common'
    strip_id = window.roi_records[1]['roi_id']
    assert window.inspect_roi.findData(strip_id) == -1
    window.right_task.setCurrentIndex(window.right_task.findData('profile'))
    window.inspect_roi.setCurrentIndex(window.inspect_roi.findData(strip_id))
    qtbot.waitUntil(lambda:not window.task_busy,timeout=10000)
    spec=window.right_spec
    assert spec.metadata['operation'] == 'strip_profile'
    assert spec.metadata['support'] == 'per_band' and spec.metadata['summary'] == 'mean'
    assert not spec.metadata['roi_definition']['included']
    assert spec.metadata['bin_edges_px'][0] == 0
    assert spec.series[0]['used_counts'][0] == 0 and np.isnan(spec.series[0]['y'][0])
    text=profile_bin_text(spec,.5)
    assert 'excluded 1' in text and 'used 0' in text and 'unavailable' in text
    assert 'empty bins' in window.brush_note.text()
    assert 'Mean / spatial SD' in window.chart_title(spec)
    assert 'Median / Q25–Q75' in window.chart_title(amplitude)
    np.testing.assert_equal(window.plot_spec.series[0]['y'],values[0]['y'])
    assert window.plot_spec is amplitude and not window.roi_included[1].isChecked()
    window.right_task.setCurrentIndex(window.right_task.findData('ecdf'))
    assert window.inspect_roi.findData(strip_id) == -1
    assert len(window.right_spec.series) == 1


def test_cfa_request_fallback_is_effective_display_without_mutating_evidence(qtbot):
    window=Workbench(); qtbot.addWidget(window)
    cube=Cube(np.arange(64,dtype=np.uint16).reshape(8,8,1),
        {'data_level':'raw_frame','data_source':'SYNTHETIC','pixel_format':'BayerRG12','units':'DN',
         'readback_settings':{'ReverseX':None,'ReverseY':False,'OffsetX':0,'OffsetY':0}})
    original=deepcopy(cube.metadata)
    window.set_cube(cube); window.view_mode.setCurrentIndex(1); window.render_current()
    assert window.effective_display['effective'] == 'Raw gray'
    assert 'ReverseX' in window.effective_display['fallback_reason']
    assert 'Display: Raw gray (CFA unavailable; Details)' in window.axis_label.text()
    window.refresh_details()
    assert json.loads(window.detail_text.toPlainText())['effective_display']['effective'] == 'Raw gray'
    assert cube.metadata == original
