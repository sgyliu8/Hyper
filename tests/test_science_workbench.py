import json

import numpy as np
import pytest
from PySide6 import QtWidgets as W

from hyperlab.acquisition.sequence import Sequence, SequenceWriter
from hyperlab.analysis import roi_comparison
from hyperlab.experiment_metadata import source_fingerprint
from hyperlab.io import Cube, make_synthetic_cube, save_cube
from hyperlab.plots import COLORS, export_figure_bundle, recorded_roi_plot, roi_plot, source_identity
from hyperlab.ui.workbench import Workbench


def rgb():
    return Cube(np.arange(12*16*3, dtype=np.uint16).reshape(12, 16, 3),
        {'data_level':'raw_frame', 'units':'DN', 'channel_labels':['R','G','B'], 'data_source':'SYNTHETIC'})


def complete(window, qtbot):
    qtbot.waitUntil(lambda:not window.task_busy, timeout=10000)


def test_recorded_opposite_channels_are_not_averaged_and_partial_prefix_retained(tmp_path):
    with SequenceWriter(tmp_path/'sequence', (3,4,3), np.dtype('uint8'), 6,
                        metadata={'channel_labels':['R','G','B'], 'data_source':'SYNTHETIC'}) as writer:
        for index in range(4):
            data = np.broadcast_to([10+index, 20-index, 5], (3,4,3)).astype(np.uint8).copy()
            writer.append(data, {'valid':True, 'session_id':'fixture', 'host_monotonic_ns':int(index*1e9),
                                 'sequence':index, 'readback_settings':{'ExposureTime':50}})
    with Sequence(tmp_path/'sequence'/'sequence.npy') as sequence:
        red = recorded_roi_plot(sequence, [(0,0,4,3)], ['Paint'], COLORS, band=0)
        green = recorded_roi_plot(sequence, [(0,0,4,3)], ['Paint'], COLORS, band=1)
        np.testing.assert_equal(red.series[0]['y'], [10,11,12,13])
        np.testing.assert_equal(green.series[0]['y'], [20,19,18,17])
        np.testing.assert_equal(red.series[0]['valid_counts'], [12]*4)
        np.testing.assert_equal(red.series[0]['x'], [0,1,2,3])
        assert red.metadata['recording']['partial'] and red.metadata['frame_count'] == 4
        assert red.metadata['recording']['expected_frames'] == 6
        assert red.metadata['channel_label'] == 'R' and red.metadata['settings_match']


def test_median_ribbon_is_asymmetric_quartiles_in_ui_and_export(qtbot,tmp_path):
    cube = Cube(np.array([0,1,2,9,100],float).reshape(1,5,1), {'data_level':'raw_frame','units':'DN'})
    results = roi_comparison(cube,[(0,0,5,1)])
    spec = roi_plot(results,['Paint'],COLORS,source=source_identity(cube),summary='median')
    np.testing.assert_equal(spec.series[0]['y'],[2])
    np.testing.assert_equal(spec.series[0]['lower'],[1])
    np.testing.assert_equal(spec.series[0]['upper'],[9])
    assert spec.series[0]['sd'] is None
    window=Workbench(); qtbot.addWidget(window); window.draw_plot(spec)
    assert window.error_bars[0].opts['bottom'][0] == 1
    assert window.error_bars[0].opts['top'][0] == 7
    export_figure_bundle(spec,tmp_path/'figure',dpi=72)
    record=json.loads((tmp_path/'figure'/'plot.json').read_text())
    assert record['metadata']['summary']=='median'
    assert 'spatial_q25' in (tmp_path/'figure'/'series.csv').read_text()


def test_unavailable_pca_selection_restores_completed_chart_identity(qtbot):
    window=Workbench(); qtbot.addWidget(window); window.set_cube(rgb())
    window.analyze_rois(); complete(window,qtbot)
    previous=window.plot_spec
    window.plot_mode.setCurrentIndex(4)
    assert window.plot_mode.currentIndex()==2 and window.plot_spec is previous
    assert 'corresponding analysis' in window.message.text()


def test_export_uses_completed_median_context_after_controls_change(qtbot,tmp_path):
    window=Workbench(); qtbot.addWidget(window); window.set_cube(rgb())
    window.roi_summary.setCurrentIndex(1)
    window.analyze_rois(); complete(window,qtbot)
    means=window.roi_results[0]['mean'].copy()
    version=window.roi_result_context['version']
    window.roi_summary.setCurrentIndex(0); window.roi_timer.stop()
    window.output_dir=tmp_path
    window.export_rois(); complete(window,qtbot)
    directory=next(tmp_path.glob('roi_*'))
    record=json.loads((directory/'comparison.json').read_text())
    assert record['analysis_context']['summary']=='median'
    assert record['analysis_context']['version']==version
    np.testing.assert_allclose(np.genfromtxt(directory/'roi_1.csv',delimiter=',',names=True)['mean'],means)
    assert (directory/'analysis_manifest.json').is_file()


def test_spectral_ui_uses_real_axis_and_common_support(qtbot):
    window=Workbench(); qtbot.addWidget(window); window.set_cube(make_synthetic_cube())
    window.analysis_method.setCurrentIndex(window.analysis_method.findData('derivative1'))
    window.run_analysis(); complete(window,qtbot)
    assert window.science_result is not None, window.message.text()
    assert window.plot_spec.xlabel=='Wavelength (nm)'
    assert window.plot_spec.metadata['support']=='common'
    assert not any('sd' in s for s in window.plot_spec.series)
    assert not np.isfinite(window.plot_spec.series[0]['y'][0])
    window.science_results_dialog()
    assert window._science_results_dialog.findChild(W.QTableWidget) is not None
    window._science_results_dialog.close()


def test_rgb_pair_and_map_gates_and_stop_accessibility(qtbot):
    window=Workbench(); qtbot.addWidget(window); window.show(); window.set_cube(rgb())
    window.tabs.setCurrentIndex(1)
    window.analysis_method.setCurrentIndex(window.analysis_method.findData('continuum'))
    assert not window.run_button.isEnabled()
    assert 'reflectance' in window.capability_label.text().lower()
    window.analysis_method.setCurrentIndex(window.analysis_method.findData('pairs'))
    window.run_analysis(); complete(window,qtbot)
    pair=window.science_result['pairs'][0]
    assert pair['angle'] is None and 'angle' in pair['unavailable']
    window.analysis_method.setCurrentIndex(window.analysis_method.findData('normalized_difference'))
    window.run_analysis(); complete(window,qtbot)
    assert window.map_spec.colormap=='RdBu_r'
    assert not window.preview_button.isVisible() and not window.metrics_label.isVisible()
    class Streaming:
        state='streaming'
    window.session=Streaming(); window.update_controls()
    assert window.stop_button.isVisible() and window.stop_button.isEnabled()
    window.session=None


def test_plot_export_rejects_same_path_source_replacement(tmp_path):
    cube=rgb(); path=tmp_path/'source.npy'; save_cube(cube,path)
    cube.metadata['source_file']=str(path)
    results=roi_comparison(cube,[(0,0,8,12),(8,0,16,12)])
    spec=roi_plot(results,['A','B'],COLORS,source=source_identity(cube))
    spec.metadata['source_fingerprint']=source_fingerprint(cube)
    np.save(path,np.zeros(cube.shape,dtype=cube.data.dtype))
    with pytest.raises(ValueError,match='Source changed'):
        export_figure_bundle(spec,tmp_path/'blocked',source_cube=cube,dpi=72)
    assert not (tmp_path/'blocked').exists()


def test_offline_run_reenabled_after_background_failure(qtbot):
    window=Workbench(); qtbot.addWidget(window); window.set_cube(rgb())
    def fail():
        raise ValueError('fixture invalid input')
    window.background(fail, lambda _:None, 'Fixture')
    assert not window.run_button.isEnabled()
    complete(window,qtbot)
    assert window.run_button.isEnabled() and 'fixture invalid input' in window.message.text()


def test_pca_chart_keeps_original_source_when_live_frame_advances(qtbot):
    from hyperlab.analysis import pca
    window=Workbench(); qtbot.addWidget(window)
    original=make_synthetic_cube(); window.set_cube(original)
    result=pca(original); result['metadata']['source_fingerprint']=source_fingerprint(original)
    window.show_product(result, original)
    window.set_cube(make_synthetic_cube(),live=True)
    window.plot_mode.setCurrentIndex(4)
    assert window.plot_source is original


def test_same_shape_color_order_updates_trace_labels(qtbot):
    window=Workbench(); qtbot.addWidget(window); window.set_cube(rgb())
    second=rgb(); second.metadata['channel_labels']=['B','G','R']
    window.set_cube(second)
    assert [window.trace_channel.itemText(i) for i in range(3)]==['B','G','R']


def test_failed_roi_chart_request_restores_completed_selector(qtbot,monkeypatch):
    import hyperlab.analysis
    window=Workbench(); qtbot.addWidget(window); window.set_cube(rgb())
    def fail(*args,**kwargs):
        raise ValueError('fixture ROI unavailable')
    monkeypatch.setattr(hyperlab.analysis,'roi_comparison',fail)
    window.plot_mode.setCurrentIndex(2); complete(window,qtbot)
    assert window.plot_mode.currentIndex()==0
    assert window.plot_spec.title=='Sampled histogram'


def test_new_same_shape_sequence_resets_old_result(qtbot,tmp_path):
    window=Workbench(); qtbot.addWidget(window)
    for index in range(2):
        with SequenceWriter(tmp_path/str(index),(3,4,3),np.dtype('uint8'),1,
                            metadata={'channel_labels':['R','G','B']}) as writer:
            writer.append(np.full((3,4,3),index+1,np.uint8), {'valid':True,'sequence':index+100})
    window.open_path(tmp_path/'0'); complete(window,qtbot)
    window.analyze_rois(); complete(window,qtbot)
    assert window.plot_spec.metadata['roi_comparison']
    version=window.analysis_version
    window.open_path(tmp_path/'1'); complete(window,qtbot)
    assert window.analysis_version>version and not window.roi_results
    assert window.plot_spec.title=='Sampled histogram'
    assert window.plot_source is window.cube and window.plot_spec.source['sequence']==101


def test_figure_dialog_is_modeless_and_keeps_opening_source(qtbot,monkeypatch):
    import hyperlab.ui.workbench as module
    window=Workbench(); qtbot.addWidget(window); first=rgb(); window.set_cube(first)
    captured={}
    monkeypatch.setattr(module,'export_figure_bundle',lambda spec,directory,**kwargs:captured.update(spec=spec,**kwargs))
    window.figure_export()
    assert not window._figure_dialog.isModal()
    window.set_cube(rgb(),live=True)
    buttons=window._figure_dialog.findChild(W.QDialogButtonBox)
    buttons.button(W.QDialogButtonBox.StandardButton.Save).click(); complete(window,qtbot)
    assert captured['source_cube'] is first


def test_modeless_figure_source_closed_by_replay_switch_is_rejected(qtbot,tmp_path):
    from hyperlab.io import load_cube
    path=tmp_path/'first.npy'; save_cube(rgb(),path)
    window=Workbench(); qtbot.addWidget(window); original=load_cube(path); window.set_cube(original)
    window.figure_export()
    original.close()
    window.set_cube(rgb())
    buttons=window._figure_dialog.findChild(W.QDialogButtonBox)
    buttons.button(W.QDialogButtonBox.StandardButton.Save).click(); complete(window,qtbot)
    assert 'Source mapping is closed' in window.message.text()
    assert window.run_button.isEnabled()
