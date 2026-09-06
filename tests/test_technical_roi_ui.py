"""Raw geometry/identity acceptance through the offline workbench workflow."""
from copy import deepcopy
import numpy as np
import pytest
from PySide6 import QtWidgets as W

from hyperlab.io import Cube
from hyperlab.analysis.regions import make_roi, resolve_roi
from hyperlab.ui.workbench import Workbench


@pytest.fixture
def window(qtbot):
    result=Workbench(); qtbot.addWidget(result)
    result.set_cube(Cube(np.arange(144,dtype=float).reshape(12,12,1),
                         {'data_level':'raw_frame','data_source':'SYNTHETIC','units':'DN'}))
    return result


def run_rois(window,qtbot):
    window.roi_timer.stop(); window.analyze_rois()
    qtbot.waitUntil(lambda:not window.task_busy,timeout=10000)
    window.roi_timer.stop()


def test_visibility_does_not_change_inclusion_and_reference_survives_reorder(window,qtbot):
    window.apply_roi_bounds(0,(0,0,4,4)); window.apply_roi_bounds(1,(4,0,8,4))
    reference=window.regions()[0]['roi_id']
    window.roi_visible[0].setChecked(False)
    run_rois(window,qtbot)
    assert len(window.roi_results)==2 and len(window.plot_spec.series)==1
    np.testing.assert_allclose(window.roi_results[0]['mean'],[19.5])
    window.roi_names[0].setText('Renamed reference'); window.reorder_roi(0,1)
    assert window.reference_roi_id==reference
    assert window.reference_roi.currentData()==reference
    assert window.regions()[1]['role']=='reference'
    window.roi_included[1].setChecked(False)
    run_rois(window,qtbot)
    assert len(window.roi_results)==1
    window.analyze('reference_rmse')
    assert not window.task_busy and 'missing or excluded' in window.message.text()


def test_polygon_hole_and_exclusion_use_membership_not_box(window,qtbot):
    window.roi_included[0].setChecked(False); window.roi_included[1].setChecked(False)
    polygon=make_roi(window.cube.shape,{'type':'polygon','vertices':[[0,0],[6,0],[6,6],[0,6]],
        'holes':[[[1,1],[3,1],[3,3],[1,3]]]},name='Coating')
    exclude=make_roi(window.cube.shape,{'type':'rectangle','bounds':[4,0,6,6]},name='Glare',role='exclude')
    window.add_roi(polygon['name'],record=polygon)
    window.add_roi(exclude['name'],record=exclude)
    run_rois(window,qtbot)
    assert len(window.roi_results)==1
    stats=window.roi_results[0]
    assert stats['counts']['total'][0]==32
    assert stats['geometry_excluded_count'][0]==12
    assert stats['count'][0]==20
    region=resolve_roi(window.cube.shape,window.regions()[2],exclusions=[exclude])
    np.testing.assert_allclose(stats['mean'][0],window.cube.data[:6,:6,0][region['selected']].mean())
    assert window.plot_spec.series[0]['roi_definition']['roi_id']==polygon['roi_id']


def test_mask_membership_visible_and_tamper_rejected(window,qtbot,tmp_path):
    from hyperlab.analysis.regions import mask_geometry
    path=tmp_path/'mask.npy'; mask=np.zeros((12,12),bool); mask[1,1]=mask[10,10]=True; np.save(path,mask)
    record=make_roi((12,12),mask_geometry(path,(12,12)),name='Two pixels')
    window.add_roi(record['name'],record=record)
    assert resolve_roi(window.cube.shape,window.regions()[-1])['selected_count']==2
    assert np.count_nonzero(window.rois[-1].image[...,3])==2
    mask[1,1]=False; np.save(path,mask)
    with pytest.raises(ValueError,match='changed'):
        resolve_roi(window.cube.shape,window.regions()[-1])


def test_roi_save_restore_retains_id_revision_geometry_and_reference(window,qtbot):
    from hyperlab.ui.state import save_state,restore_view
    from hyperlab.paths import load_config
    window.add_roi(kind='strip')
    window.roi_included[1].setChecked(False)
    expected=deepcopy(window.regions()); reference=window.reference_roi_id
    save_state(window)
    restored=Workbench(); qtbot.addWidget(restored)
    restored._pending_state=None
    restored.set_cube(Cube(window.cube.data.copy(),dict(window.cube.metadata)))
    restored._pending_state=load_config()['ui']; restore_view(restored)
    assert restored.regions()==expected
    assert restored.reference_roi_id==reference


def test_measured_wavelength_drag_selects_raw_interval_and_generates_map(window,qtbot):
    cube=Cube(np.broadcast_to(np.array([2.,4.,8.,16.]),(5,6,4)).copy(),
              {'data_source':'SYNTHETIC','data_level':'spectral_cube','wavelength_source':'explicit test fixture',
               'wavelengths':[450,500,610,730], 'wavelength_units':'nm','units':'DN'})
    window.set_cube(cube); run_rois(window,qtbot)
    window.analysis_method.setCurrentIndex(window.analysis_method.findData('interval_map'))
    assert window.interval_region is not None
    window.interval_region.setRegion([490,620])
    window.interval_region.sigRegionChangeFinished.emit(window.interval_region)
    qtbot.waitUntil(lambda:not window.task_busy,timeout=10000)
    assert window.feature_first.value()==1 and window.feature_last.value()==2
    assert window.product is not None,window.message.text()
    np.testing.assert_allclose(window.product['data'],660.)


def test_hidden_included_roi_keeps_common_normalization_features(window,qtbot):
    data=np.ones((12,12,3),float)
    data[:4,:4,2]=np.nan
    cube=Cube(data,{'data_source':'SYNTHETIC','units':'DN'})
    window.set_cube(cube)
    window.apply_roi_bounds(0,(0,0,4,4)); window.apply_roi_bounds(1,(4,0,8,4))
    window.shape_normalize.setChecked(True); run_rois(window,qtbot)
    expected=window.plot_spec.series[1]['normalized'].copy()
    window.roi_visible[0].setChecked(False); run_rois(window,qtbot)
    assert window.plot_spec.metadata['common_feature_indices']==[0,1]
    np.testing.assert_equal(window.plot_spec.series[0]['normalized'],expected)
    window.roi_included[0].setChecked(False); run_rois(window,qtbot)
    assert window.plot_spec.metadata['common_feature_indices']==[0,1,2]


def test_source_shape_change_replaces_old_polygon_coordinate_frame(window,qtbot):
    window.add_roi(kind='polygon'); window.add_roi(kind='strip')
    window.set_cube(Cube(np.ones((5,6,4)),{'data_source':'SYNTHETIC'}))
    for record in window.regions():
        assert record['coordinate_frame']['shape_hw']==[5,6]
        resolve_roi((5,6),record)
