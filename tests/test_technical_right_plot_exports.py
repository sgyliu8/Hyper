"""Spatial-bin identity and clean completed right-task publication contracts."""
import csv
import json

import numpy as np
import pytest

from hyperlab.analysis import roi_comparison
from hyperlab.analysis.regions import make_roi, strip_profile
from hyperlab.experiment_metadata import compute_pinned
from hyperlab.io import Cube, save_cube
from hyperlab.plots import (COLORS, PlotSpec, export_figure_bundle, render_figure, roi_plot,
                            roi_transform_plot, source_identity, strip_profile_plot)


def profile_fixture(tmp_path):
    data = np.broadcast_to(np.arange(5.)[None,:,None]+[10.,20.,30.], (3,5,3)).copy()
    data[1,2,0] = -99.
    mask = np.ones(data.shape, bool)
    mask[1,3,1] = False
    cube = Cube(data, {'data_level':'raw_frame', 'units':'DN', 'data_source':'SYNTHETIC',
        'channel_labels':['R','G','B'], 'data_ignore_value':-99., 'saturation_value':32.}, mask)
    path = save_cube(cube, tmp_path/'source.npy')
    cube.metadata['source_file'] = str(path)
    roi = make_roi((3,5), {'type':'strip', 'points':[[.5,1.5],[4.5,1.5]], 'width_px':1.},
                   roi_id='strip-A', revision=3)
    exclusion = make_roi((3,5), {'type':'rectangle','bounds':[1,1,2,2]}, role='exclude', roi_id='glint')
    result, fingerprint = compute_pinned(cube, lambda:strip_profile(cube,roi,exclusions=[exclusion],policy='quantitative'))
    spec = strip_profile_plot(result, source=source_identity(cube), source_fingerprint=fingerprint,
                              analysis_context={'version':17})
    return cube, path, result, spec


def test_profile_csv_preserves_real_channels_bins_and_all_quality_denominators(tmp_path):
    cube, _, result, spec = profile_fixture(tmp_path)
    output = export_figure_bundle(spec,tmp_path/'profile',source_cube=cube,dpi=72)
    rows = list(csv.DictReader((output/'series.csv').open()))
    expected_used = [[1,0,0,2], [1,0,1,1], [1,0,0,0]]
    for band,label in enumerate(['R','G','B']):
        channel = [row for row in rows if row['series']==label]
        assert [int(row['feature_index']) for row in channel] == [band]*4
        assert [int(row['sample_index']) for row in channel] == [0,1,2,3]
        assert [int(row['used_count']) for row in channel] == expected_used[band]
        assert [float(row['bin_left_px']) for row in channel] == [0,1,2,3]
        assert [float(row['bin_right_px']) for row in channel] == [1,2,3,4]
        assert [int(row['geometry_count']) for row in channel] == [1,1,1,2]
        assert [int(row['excluded_geometry_count']) for row in channel] == [0,1,0,0]
        assert all(row['position_units']=='px' and row['value_units']=='DN' for row in channel)
        assert all(row['roi_id']=='strip-A' and row['roi_revision']=='3' for row in channel)
        for row in channel:
            assert int(row['used_count'])+int(row['geometry_excluded_count']) == int(row['policy_valid_count'])
    red = [row for row in rows if row['series']=='R']
    green = [row for row in rows if row['series']=='G']
    blue = [row for row in rows if row['series']=='B']
    assert red[2]['source_ignored_count']=='1'
    assert green[3]['source_invalid_count']=='1'
    assert [row['source_saturated_count'] for row in blue] == ['0','0','1','2']
    assert float(red[3]['y']) == 13.5 and float(red[3]['spatial_sd_ddof0']) == .5
    saved = json.loads((output/'plot.json').read_text())
    assert saved['metadata']['bin_edges_px'] == [0,1,2,3,4]
    assert saved['metadata']['geometry_count'] == [1,1,1,2]
    assert saved['metadata']['analysis_context'] == {'version':17}
    assert saved['metadata']['source_fingerprint'] == spec.metadata['source_fingerprint']
    assert saved['series'][0]['exclusion_definitions'][0]['roi_id']=='glint'
    assert saved['metadata']['aggregation_order']=='spatial_bin_then_summary'
    assert (output/'analysis_manifest.json').is_file()
    np.testing.assert_equal(spec.series[0]['used_counts'],result['curves'][0]['count'])


def test_profile_snapshot_rejects_later_same_path_source_change(tmp_path):
    cube,path,_,spec = profile_fixture(tmp_path)
    np.save(path,cube.data+100.)
    with pytest.raises(ValueError,match='Source changed'):
        export_figure_bundle(spec,tmp_path/'rejected',source_cube=cube,dpi=72)
    assert not (tmp_path/'rejected').exists()


def test_profile_spec_copies_computed_arrays_and_context(tmp_path):
    cube,_,result,_ = profile_fixture(tmp_path)
    fingerprint = compute_pinned(cube,lambda:None)[1]
    context={'version':1}
    spec=strip_profile_plot(result,source=source_identity(cube),source_fingerprint=fingerprint,analysis_context=context)
    original=spec.series[0]['y'].copy()
    result['curves'][0]['mean'][:] = -123.
    result['geometry_count'][:] = 0
    context['version']=2
    np.testing.assert_equal(spec.series[0]['y'],original)
    assert spec.metadata['geometry_count']==[1,1,1,2] and spec.metadata['analysis_context']['version']==1


@pytest.mark.parametrize('fingerprint',[None,{}, {'source_id':''}])
def test_profile_requires_a_captured_fingerprint(fingerprint):
    with pytest.raises(ValueError,match='captured'):
        strip_profile_plot({},source={},source_fingerprint=fingerprint)


def test_single_plane_residual_drops_inherited_intensity_distribution(tmp_path):
    cube=Cube(np.array([1.,3.,9.,11.]).reshape(1,4,1),
              {'data_level':'raw_frame','data_source':'SYNTHETIC','units':'DN'})
    stats=roi_comparison(cube,[(0,0,1,1),(0,0,4,1)])
    original=roi_plot(stats,['Reference','Target'],COLORS,source=source_identity(cube))
    before=original.record()
    spec=roi_transform_plot(original,'residual',reference=[1.],reference_roi_id='reference-A')
    np.testing.assert_allclose([item['y'][0] for item in spec.series],[0.,5.])
    assert len(render_figure(spec,dpi=72).axes)==1
    assert all('distribution' not in item and 'normalized' not in item and 'sd' not in item for item in spec.series)
    assert spec.metadata['units']=='DN' and spec.metadata['aggregation_order']=='summary_then_transform'
    assert spec.metadata['reference_roi_id']=='reference-A' and spec.metadata['reference_summary']==[1.]
    assert original.record()==before
    output=export_figure_bundle(spec,tmp_path/'residual',dpi=72)
    assert not (output/'distributions.csv').exists()
    assert 'Mean residual' in json.loads((output/'plot.json').read_text())['ylabel']


@pytest.mark.parametrize('summary,expected',[('mean',[8.,14.5,26.5]),('median',[5.5,7.,7.])])
def test_l2_uses_included_common_features_and_summary_specific_dimensionless_single_plot(summary,expected,tmp_path):
    cube=Cube(np.array([[[1.,4.,2.],[2.,6.,3.],[9.,8.,11.],[20.,40.,90.]]]),
              {'data_level':'raw_frame','data_source':'SYNTHETIC','units':'DN','channel_labels':['R','G','B']})
    stats=roi_comparison(cube,[(0,0,1,1),(0,0,4,1)])
    original=roi_plot(stats,['Reference','Target'],COLORS,source=source_identity(cube),
                      summary=summary,normalized=True,categorical_style='points')
    before=original.record()
    common=np.array([True,True,False])  # A hidden included ROI made B unavailable.
    spec=roi_transform_plot(original,'shape',common=common)
    normalized=np.asarray(expected[:2])/np.linalg.norm(expected[:2])
    np.testing.assert_allclose(spec.series[1]['y'],[*normalized,np.nan],equal_nan=True)
    assert spec.ylabel==f'Normalized {summary} (dimensionless)'
    assert spec.metadata['units']=='dimensionless' and spec.metadata['source_units']=='DN'
    assert spec.metadata['common_feature_indices']==[0,1] and spec.metadata['excluded_indices']==[2]
    assert spec.metadata['categorical_style']=='points'
    assert len(render_figure(spec,dpi=72).axes)==1
    assert all(not any(key in item for key in ('normalized','distribution','sd','lower','upper')) for item in spec.series)
    assert original.record()==before
    output=export_figure_bundle(spec,tmp_path/summary,dpi=72)
    rows=list(csv.DictReader((output/'series.csv').open()))
    assert all(row['value_units']=='dimensionless' and row['normalized']=='' and row['spatial_q25']=='' for row in rows)


def test_l2_zero_norm_and_huge_finite_signals_retain_one_common_support():
    original=PlotSpec('lines','Amplitude','Feature','Mean (DN)',metadata={'units':'DN','summary':'mean'},
        series=[{'x':[0,1,2],'y':[0.,0.,0.],'name':'Zero','color':COLORS[0]},
                {'x':[0,1,2],'y':[1e308,1e308,np.nan],'name':'Large','color':COLORS[1]}])
    spec=roi_transform_plot(original,'shape',common=np.ones(3,bool))
    assert np.isnan(spec.series[0]['y']).all()
    np.testing.assert_allclose(spec.series[1]['y'],[2**-.5,2**-.5,np.nan],equal_nan=True)
    assert spec.metadata['common_feature_indices']==[0,1]


def test_residual_retains_finite_pair_values_and_omits_nonrepresentable_differences():
    original=PlotSpec('lines','Amplitude','Feature','Mean (DN)',metadata={'units':'DN'},
        series=[{'x':[0,1,2],'y':[4.,np.nan,1e308],'name':'A','color':COLORS[0]}])
    result=roi_transform_plot(original,'residual',reference=[1.,2.,-1e308])
    np.testing.assert_allclose(result.series[0]['y'],[3.,np.nan,np.nan],equal_nan=True)
    assert result.metadata['finite_support']=='finite target and reference summary pairs'


@pytest.mark.parametrize('task,options',[('unexpected',{}),('residual',{'reference':[1.]}),
    ('shape',{'common':[1,1]}),('shape',{'common':[True]})])
def test_ambiguous_right_task_inputs_are_rejected(task,options):
    original=PlotSpec('lines','Amplitude','Feature','Mean',
        series=[{'x':[0,1],'y':[1.,2.],'name':'A','color':COLORS[0]}])
    with pytest.raises(ValueError):
        roi_transform_plot(original,task,**options)
