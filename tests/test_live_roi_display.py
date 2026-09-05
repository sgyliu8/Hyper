from copy import copy, deepcopy
import json

import numpy as np
import pytest

from hyperlab.acquisition.frame import Frame
from hyperlab.analysis import roi_statistics, roi_comparison
from hyperlab.io import Cube
from hyperlab.plots import COLORS, roi_plot, source_identity, export_figure_bundle
from hyperlab.ui.workbench import Workbench


def live_frame(color=False):
    shape = (12, 16, 3) if color else (12, 16)
    data = np.arange(np.prod(shape), dtype=np.uint8 if color else np.uint16).reshape(shape)
    metadata = {'data_level':'raw_frame', 'units':'DN', 'data_source':'LIVE',
        'acquisition_source':'LIVE', 'display_mode':'LIVE', 'session_id':'fixture',
        'sequence':7, 'stream_epoch':1, 'host_monotonic_ns':1000000000,
        'pixel_format':'RGB8' if color else 'BayerRG12',
        'readback_settings':{'ExposureTime':50000, 'Gain':0},
        'node_evidence':{'ExposureTime':{'status':'value', 'value':50000}},
        'processing_steps':[{'operation':'owned transport copy'}]}
    if color:
        metadata['channel_labels'] = ['R','G','B']
    frame = Frame(data, metadata)
    return frame, Cube(frame.data if color else frame.data[...,None], frame.metadata)


@pytest.mark.parametrize('color',[False,True])
def test_live_roi_nested_frozen_evidence_can_be_copied_and_exported(color,tmp_path):
    frame,cube = live_frame(color)
    before = json.dumps(frame.metadata, sort_keys=True)
    result = roi_statistics(cube,(2,3,8,9))
    np.testing.assert_allclose(result['mean'],cube.data[3:9,2:8].mean(axis=(0,1)))
    assert result['metadata']['source_provenance']['readback_settings']['ExposureTime'] == 50000
    assert copy(frame.metadata) == deepcopy(frame.metadata) == frame.metadata
    spec = roi_plot([result],['Sample ROI'],COLORS,source=source_identity(cube))
    export_figure_bundle(spec,tmp_path/'figure',dpi=80)
    assert json.dumps(frame.metadata,sort_keys=True) == before
    with pytest.raises(TypeError,match='immutable'):
        frame.metadata['node_evidence']['ExposureTime']['value'] = 1
    with pytest.raises(ValueError):
        frame.data[0,0] = 0


def test_single_plane_comparison_uses_roi_categories_not_one_invisible_point():
    cube = Cube(np.arange(48,dtype=np.uint16).reshape(6,8,1),
                {'data_level':'raw_frame','units':'DN','pixel_format':'BayerRG12'})
    results = [roi_statistics(cube,r) for r in ((0,0,3,3),(4,3,8,6))]
    spec = roi_plot(results,['Dark ROI','Bright ROI'],COLORS,source=source_identity(cube),normalized=True)
    assert spec.categories == ['Dark ROI','Bright ROI']
    np.testing.assert_equal([s['x'][0] for s in spec.series],[0,1])
    assert not any('normalized' in s for s in spec.series)
    assert 'single sensor plane' in spec.caption.lower()


def test_workbench_compares_real_frame_contract_in_background(qtbot):
    frame,cube = live_frame()
    window = Workbench(); qtbot.addWidget(window)
    window.displayed_frame = frame
    window.display_mode = 'LIVE'
    window.set_cube(cube,live=True)
    window.roi_timer.stop()
    window.analyze_rois()
    qtbot.waitUntil(lambda:not window.task_busy,timeout=5000)
    assert len(window.roi_results) == 2, window.message.text()
    assert window.plot_spec.source['sequence'] == 7
    assert window.curves[0].opts['symbol'] is not None
    assert len(window.error_bars) == 2
    np.testing.assert_allclose(window.error_bars[0].opts['height'],2*window.roi_results[0]['std'])


def test_repeated_distribution_plot_keeps_actual_density_tick_units(qtbot):
    window = Workbench(); qtbot.addWidget(window)
    _,cube = live_frame()
    results = roi_comparison(cube,[(0,0,8,12),(8,0,16,12)])
    spec = roi_plot(results,['ROI A','ROI B'],COLORS,source=source_identity(cube))
    window.show()
    for _ in range(3):
        window.draw_plot(spec)
        qtbot.wait(40)
        axis = window.shape_chart.getAxis('left')
        assert axis.autoSIPrefixScale == 1
        assert float(axis.tickStrings([.005],axis.autoSIPrefixScale,.005)[0]) == pytest.approx(.005)


def test_multiband_spatial_sd_has_renderable_fill_path(qtbot):
    import pyqtgraph as pg
    from PySide6.QtCore import QPointF
    from hyperlab.plots import PlotSpec

    window = Workbench(); qtbot.addWidget(window)
    spec = PlotSpec('lines','ROI amplitude','Wavelength (nm)','Mean (DN)',series=[
        {'name':'ROI A','x':[500,600,700],'y':[10,12,10],'sd':[2,2,2],
         'color':COLORS[0],'style':'-'}])
    window.draw_plot(spec)
    ribbon, = [item for item in window.chart.getPlotItem().items if isinstance(item,pg.FillBetweenItem)]
    assert not ribbon.path().isEmpty()
    assert ribbon.path().contains(QPointF(600,13))
    assert not ribbon.path().contains(QPointF(600,20))
    assert ribbon.brush().color().alpha() == 44


def test_native_map_distinguishes_masked_pixels_and_preserves_signed_scale(qtbot):
    window = Workbench(); qtbot.addWidget(window)
    cube = Cube(np.zeros((2,3,2)),{'data_level':'raw_frame','units':'DN'})
    data = np.array([[-5000.,0.,5000.],[100.,200.,300.]])
    valid = np.array([[True,True,True],[True,False,True]])
    result = {'data':data,'valid_mask':valid,'metadata':{'operation':'difference','units':'DN'}}
    window.set_cube(cube); window.roi_timer.stop(); window.show()
    for _ in range(2):
        window.show_product(result,cube); qtbot.wait(40)
        np.testing.assert_equal(window.derived_invalid.image,~valid)
        assert window.derived_invalid.lut[1].tolist() == [220,225,229,255]
        assert window.derived_invalid.lut[0,3] == 0
        assert window.map_spec.colormap == 'RdBu_r'
        assert window.map_spec.limits == (-5000,5000)
        assert window.colorbar.axis.autoSIPrefixScale == 1
        assert np.isnan(window.derived_image.image[1,1])
        assert window.derived_image.image[0,1] == 0
    assert window.derived_graphics.backgroundBrush().color().name() == '#ffffff'
    legend_item = window.derived_plot.legend.items[0][0].item
    import pyqtgraph as pg
    assert pg.mkBrush(legend_item.opts['brush']).color().name() == '#dce1e5'
    np.testing.assert_equal(result['data'],[[-5000,0,5000],[100,200,300]])


@pytest.mark.parametrize('policy,left_count',[('diagnostic',4),('quantitative',3)])
def test_single_plane_distributions_share_bins_and_preserve_counts(policy,left_count,tmp_path):
    data = np.array([[10,20,4095,20,30,40],[-9999,np.nan,30,30,40,50]],float)[...,None]
    mask = np.ones((2,6),bool); mask[1,5] = False
    cube = Cube(data,{'data_level':'raw_frame','units':'DN','effective_bits':12,'data_ignore_value':-9999},mask)
    results = roi_comparison(cube,[(0,0,3,2),(3,0,6,2),(0,1,2,2)],policy=policy)
    for result,expected in zip(results,[left_count,5,0]):
        d = result['distribution']
        assert d['sample_count'] == expected == d['counts'].sum()
        np.testing.assert_equal(d['bin_edges'],results[0]['distribution']['bin_edges'])
        if expected:
            assert np.sum(d['y']*np.diff(d['bin_edges'])) == pytest.approx(1)
        else:
            assert np.all(np.isnan(d['y']))
    spec = roi_plot(results,['Sample A','Sample B','Empty ROI'],COLORS,source=source_identity(cube),normalized=True)
    output = export_figure_bundle(spec,tmp_path/'figure',dpi=80)
    import csv
    rows = list(csv.DictReader((output/'distributions.csv').open()))
    assert sum(int(r['count']) for r in rows if r['series']=='Sample A') == left_count
    values = [float(r['density']) for r in rows if r['series']=='Sample B']
    np.testing.assert_equal(values,results[1]['distribution']['y'])
    svg = (output/'figure.svg').read_text()
    assert 'ROI intensity distribution' in svg and 'Wavelength' not in svg
    assert data[1,0,0] == -9999 and np.isnan(data[1,1,0])
