"""Synthetic finite-band numerical oracles; no physical spectroscopy claims."""
from copy import deepcopy
import json
import threading
import numpy as np
import pytest

from hyperlab.io import Cube, save_cube, load_cube
from hyperlab.analysis import roi_statistics
from hyperlab.analysis.capabilities import capabilities
from hyperlab.plots import roi_plot, render_figure, COLORS
from hyperlab.spectroscopy.external_bands import (external_band_ratio, validate_external_bands,
    band_diagnostics, process_external_bands, pack_band_observation)


def inputs():
    bands = [dict(band_id=name,source_peak_nm=peak,source_fwhm_nm=10,support_nm=[peak-10,peak+10],
        source_evidence='SYNTHETIC triangular input',source_spectrum={'wavelength_nm':[peak-10,peak,peak+10],
        'relative_power':[0,1,0]}) for name,peak in [('A',510),('B',625),('A',510)]]
    setup = dict(acquisition_mode='external_illumination_band_scan',bands=bands,step_ids=['A1','B1','A2'],
        fixed_internal_state='SYNTHETIC fixed transfer',geometry='SYNTHETIC common aperture',
        illumination_stability='SYNTHETIC fixed source',elastic_reflection_evidence='SYNTHETIC elastic model',
        background_kind='source_off_ambient_plus_dark')
    cubes=[]
    base = dict(data_level='raw_scan',completed=True,partial=False,data_source='SYNTHETIC',synthetic=True,
        units='DN',saturation_value=4095,pixel_format='Mono12',scan_states=['A','B','A'],
        scan_steps=[{'step_id':s} for s in ['A1','B1','A2']],
        exposure_s=[.01]*3,gain=0,gain_units='dB',settings=dict(ExposureAuto='Off',GainAuto='Off',
        BalanceWhiteAuto='Off',BlackLevelAuto='Off',GammaEnable=False,LUTEnable=False),
        spatial_grid=dict(grid_id='SYNTHETIC-grid',raw_shape_hw=[2,3],sensor_roi_offset=[0,0],
        flip_x=False,flip_y=False,cfa_pattern=None,cfa_pattern_origin='not_applicable'))
    white=np.broadcast_to(np.array([100.,200.,100.]),(2,3,3)).copy()
    ratio=np.broadcast_to([.2,.7,.2],white.shape).copy()
    ratio[:,1,:]+=.1
    for role,data in zip(('sample','white','background_sample','background_white'),
                         (white*ratio+11,white+11,np.full(white.shape,11.),np.full(white.shape,11.))):
        meta=deepcopy(base)
        meta['measurement_context']=dict(role=role,observation_id='SYNTHETIC-'+role,evidence_source='SYNTHETIC fixture',
            instrument_id='SYNTHETIC camera',geometry_id='SYNTHETIC geometry',fixed_internal_state_id='SYNTHETIC fixed',
            illumination_id='SYNTHETIC source',temperature_condition_id='SYNTHETIC room',background_kind=setup['background_kind'])
        cubes.append(Cube(data,meta))
    return cubes,setup,ratio


def saved_manifest(tmp_path, *, extras=False):
    cubes,setup,_=inputs()
    files={}
    for role,cube in zip(('sample','white','background_sample','background_white'),cubes):
        path=tmp_path/(role+'.npy');save_cube(cube,path);files[role]=path.name
    if extras:
        for name,index,scale,role in [('repeat_white',1,1.02,'white'),('background_repeat_white',3,1,'background_white'),
                                     ('check',0,1,'check'),('background_check',2,1,'background_check')]:
            cube=cubes[index]
            meta=deepcopy(cube.metadata);meta['measurement_context'].update(role=role,observation_id='SYNTHETIC-'+name)
            data=(cube.data-11)*scale+11
            path=tmp_path/(name+'.npy');save_cube(Cube(data,meta),path);files[name]=path.name
    record=dict(setup=setup,inputs=files,minimum_white_dn=1,roi=[0,0,3,2])
    path=tmp_path/'measurement.json';path.write_text(json.dumps(record),encoding='utf8')
    return path


def test_finite_ratio_correction_once_roi_and_discrete_plot():
    cubes,setup,expected=inputs()
    before=[c.data.copy() for c in cubes]
    product=external_band_ratio(*cubes,setup,chunk_pixels=2)
    np.testing.assert_allclose(product.data,expected,atol=1e-14)
    for c,original in zip(cubes,before):np.testing.assert_array_equal(c.data,original)
    assert product.wavelengths is None and product.metadata['data_level']=='band_ratio_cube'
    assert product.metadata['processing_steps'][0]['background_subtractions']==1
    assert not capabilities(product)['operations']['spectral_features']
    stats=roi_statistics(product,(0,0,3,2),policy='quantitative')
    np.testing.assert_allclose(stats['mean'],expected.mean(axis=(0,1)))
    spec=roi_plot([stats],['ROI'],COLORS,source=product.metadata,normalized=True)
    assert spec.metadata['discrete_bands'] and 'Illumination peak' in spec.xlabel
    np.testing.assert_array_equal(spec.series[0]['x'],[510,625,510])
    fig=render_figure(spec,dpi=80)
    assert fig.axes[0].lines[0].get_linestyle()=='None'
    assert fig.axes[0].lines[0].get_marker()=='o'
    assert band_diagnostics(product)['bands'][0]['white_mean_dn']==100


def test_ratio_of_roi_means_is_not_pixel_ratio_mean():
    cubes,setup,_=inputs()
    cubes[0].data[:]=21
    cubes[1].data[0]=21;cubes[1].data[1]=111
    product=external_band_ratio(*cubes,setup)
    np.testing.assert_allclose(roi_statistics(product,(0,0,3,2))['mean'],.55)
    assert not np.isclose(.55,(cubes[0].data.mean()-11)/(cubes[1].data.mean()-11))


def test_raw_validity_low_reference_signed_and_above_one():
    cubes,setup,_=inputs()
    cubes[1].data[0,0,0]=11
    cubes[1].data[0,1,0]=11.5
    cubes[0].data[1,0,0]=4095
    cubes[2].data[1,1,0]=np.nan
    cubes[0].data[0,0,1]=1
    cubes[0].data[0,1,1]=500
    product=external_band_ratio(*cubes,setup,minimum_denominator=1)
    assert np.count_nonzero(~product.valid_mask)==4
    assert product.data[0,0,1]<0 and product.data[0,1,1]>1
    counts=product.metadata['quality_counts']
    assert counts['low_denominator']==2 and counts['input_invalid']==2
    assert counts['processed_values']==sum(counts[k] for k in ('input_invalid','low_denominator','nonfinite_result','valid'))


@pytest.mark.parametrize('fault',['support','profile','role','double_dark','settings','exposure','background','reference','origin'])
def test_refuses_physically_ambiguous_operands(fault):
    cubes,setup,_=inputs()
    if fault=='support':setup['bands'][0].pop('source_fwhm_nm')
    if fault=='profile':setup['bands'][0]['source_spectrum']['relative_power']=[0,0,0]
    if fault=='role':cubes[2].metadata['measurement_context']['role']='dark'
    if fault=='double_dark':cubes[0].metadata['processing_steps']=['already corrected']
    if fault=='settings':cubes[1].metadata['settings']['GammaEnable']=True
    if fault=='exposure':cubes[0].metadata['exposure_s'][1]=.02
    if fault=='background':setup['background_kind']='unexplained black image'
    if fault=='reference':setup['reference']=dict(kind='nominal_center',factors=[.9]*3,source='SYNTHETIC point table')
    if fault=='origin':cubes[0].metadata.update(synthetic=False,data_source='LIVE',acquisition_source='LIVE')
    with pytest.raises(ValueError):external_band_ratio(*cubes,setup)


def test_reference_constant_over_full_support_and_blocked_dark():
    cubes,setup,expected=inputs()
    setup.update(background_kind='lens_blocked_detector_dark',ambient_evidence='SYNTHETIC no ambient',
        reference=dict(kind='constant_over_support',factors=[.9]*3,source='SYNTHETIC flat standard',
                       support_nm=[490,650],constancy_evidence='SYNTHETIC constant model'))
    for c in cubes[2:]:c.metadata['measurement_context']['background_kind']=setup['background_kind']
    np.testing.assert_allclose(external_band_ratio(*cubes,setup).data,expected*.9)
    setup['reference']['support_nm']=[510,620]
    with pytest.raises(ValueError,match='every actual source support'):external_band_ratio(*cubes,setup)


def test_empirical_linearity_may_resolve_unknown_gamma_with_applicable_evidence():
    cubes,setup,_=inputs()
    for cube in cubes:cube.metadata['settings']['GammaEnable']=None
    with pytest.raises(ValueError,match='measured exposure-series'):external_band_ratio(*cubes,setup)
    setup['linearity']=dict(kind='measured_exposure_series',source='SYNTHETIC numerical response',exposure_range_s=[.005,.02],
        raw_dn_range=[0,1000],
        gain=0,settings=deepcopy(cubes[0].metadata['settings']),maximum_residual_fraction=.002,predeclared_limit_fraction=.01)
    assert validate_external_bands(*cubes,setup)['allowed']
    cubes[0].data[0,0,0]=2000
    assert not external_band_ratio(*cubes,setup).valid_mask[0,0,0]
    setup['linearity']['maximum_residual_fraction']=.02
    with pytest.raises(ValueError,match='measured exposure-series'):external_band_ratio(*cubes,setup)


def test_cancel_preserves_prefix_and_checks_background_integrity(tmp_path):
    cubes,setup,_=inputs();stop=threading.Event()
    path=tmp_path/'cancel.npy'
    with pytest.raises(InterruptedError):
        external_band_ratio(*cubes,setup,output_path=path,chunk_pixels=1,stop=stop,progress=lambda _:stop.set())
    with load_cube(path) as partial:
        assert partial.metadata['partial'] and partial.metadata['completed_pixels']==1
        assert int(partial.valid_mask.sum())==3
    changed=False
    def mutate(_):
        nonlocal changed
        if not changed:cubes[2].data[0,0,0]+=1;changed=True
    path=tmp_path/'changed.npy'
    with pytest.raises(ValueError,match='Source changed'):
        external_band_ratio(*cubes,setup,output_path=path,chunk_pixels=1,progress=mutate)
    with load_cube(path) as partial:assert not partial.valid_mask.any()


def test_file_workflow_preserves_repeats_and_independent_check(tmp_path):
    path=saved_manifest(tmp_path,extras=True)
    manifest=json.loads(path.read_text())
    manifest['check_reference']=dict(values=[.2333333333333333,.7333333333333333,.2333333333333333],
        source='SYNTHETIC independent oracle',bands=manifest['setup']['bands'],quantity='relative',
        matched_geometry_and_kernel_evidence='SYNTHETIC analytic truth')
    path.write_text(json.dumps(manifest))
    result=process_external_bands(path,tmp_path/'result')
    np.testing.assert_allclose(result['diagnostics']['repeat_white']['drift_fraction'],.02,atol=1e-14)
    np.testing.assert_allclose(result['diagnostics']['check']['difference'],0,atol=1e-14)
    assert result['completed']
    with load_cube(result['product']) as product:assert product.metadata['measurement_step_ids']==['A1','B1','A2']


def test_manual_frame_pack_retains_real_identity_boundary_and_refuses_reused_exposure(tmp_path):
    cubes,setup,_=inputs()
    metadata=deepcopy(cubes[0].metadata)
    records=[]
    for i,step in enumerate(setup['step_ids']):
        meta=dict(metadata,data_level='raw_frame',scan_states=None,session_id='SYNTHETIC-session',stream_epoch=1,
            frame_id=i,valid=True,buffer_complete=True,exposure_us=10000,readback_settings=metadata['settings'],
            **{key:metadata['spatial_grid'][key] for key in ('sensor_roi_offset','flip_x','flip_y','cfa_pattern','cfa_pattern_origin')})
        valid=np.ones((2,3),bool);valid[0,0]=False
        path=tmp_path/(step+'.npy');save_cube(Cube(cubes[0].data[:,:,i:i+1],meta,valid),path)
        records.append(dict(path=path.name,step_id=step,band_id=setup['bands'][i]['band_id'],confirmation='SYNTHETIC placement receipt'))
    path=tmp_path/'manual.json';path.write_text(json.dumps(dict(metadata=metadata,frames=records)))
    result=pack_band_observation(path,tmp_path/'packed')
    with load_cube(result['raw_path']) as cube:
        assert cube.metadata['scan_states']==['A','B','A'] and cube.wavelengths is None
        np.testing.assert_array_equal(cube.data,cubes[0].data)
        assert [f['frame_id'] for f in cube.metadata['frames']]==[0,1,2]
        assert 'manual' in cube.metadata['scan_association']
        assert not cube.valid_mask[0,0].any() and cube.valid_mask[1,1].all()
    records[1]['path']=records[0]['path'];path.write_text(json.dumps(dict(metadata=metadata,frames=records)))
    with pytest.raises(ValueError,match='distinct actual'):
        pack_band_observation(path,tmp_path/'reused')
    with load_cube(tmp_path/'reused'/'cube.npy') as partial:
        assert partial.metadata['partial'] and partial.shape[2]==1


def test_missing_repeat_pair_or_bad_independent_truth_does_not_claim_complete(tmp_path):
    path=saved_manifest(tmp_path,extras=True)
    spec=json.loads(path.read_text());spec['check_reference']=dict(values=[.2]*3,quantity='monochromatic')
    path.write_text(json.dumps(spec))
    with pytest.raises(ValueError,match='Independent reference'):
        process_external_bands(path,tmp_path/'bad')
    receipt=json.loads((tmp_path/'bad'/'processing.json').read_text())
    assert receipt['partial'] and not receipt['completed']


def test_roi_csv_explicit_source_coordinate_is_not_a_detector_wavelength(tmp_path):
    import csv
    from hyperlab.analysis import export_roi_csv
    cubes,setup,_=inputs();product=external_band_ratio(*cubes,setup)
    path=tmp_path/'roi.csv';export_roi_csv(roi_statistics(product,(0,0,3,2)),path)
    with path.open() as stream:rows=list(csv.DictReader(stream))
    assert rows[0]['wavelength']=='' and rows[0]['source_peak_nm']=='510'
    assert [r['measurement_step_id'] for r in rows]==['A1','B1','A2']


def test_external_ui_uses_manifest_compact_table_and_band_points(qtbot,tmp_path):
    from hyperlab.ui.workbench import Workbench
    window=Workbench();qtbot.addWidget(window)
    window.spectroscopy_dialog();dialog=window._spectroscopy_dialog
    dialog.input_kind.setCurrentIndex(dialog.input_kind.findData('external'))
    assert dialog.fields['response'].parentWidget().isHidden()
    assert dialog.acquire_button.isHidden()
    dialog.fields['external'].setText(str(saved_manifest(tmp_path)))
    dialog.check_inputs();qtbot.waitUntil(lambda:not window.task_busy,timeout=10000)
    assert 'compatibility passed' in dialog.status.text()
    dialog.process_saved();qtbot.waitUntil(lambda:not window.task_busy,timeout=10000)
    assert window.cube.metadata['data_level']=='band_ratio_cube',dialog.status.text()
    assert dialog.band_table.rowCount()==3
    assert 'SYNTHETIC' in dialog.status.text() and 'Response:' not in dialog.capabilities.text()
    window.analyze('roi');qtbot.waitUntil(lambda:not window.task_busy,timeout=10000)
    assert window.plot_spec.metadata['discrete_bands']
    assert window.curves[0].opts['pen'] is None
    dialog.input_kind.setCurrentIndex(0)
    assert dialog.band_table.isHidden() and dialog.details.toPlainText()==''


def test_finite_band_effective_reference_differs_from_nominal_center():
    cubes,setup,_=inputs()
    # Independent three-node quadrature with unequal effective flank response.
    q=np.array([1.,2.,3.])
    white_spectrum=np.array([.4,.8,.9])
    sample_spectrum=np.array([.2,.3,.7])
    expected=float(q@sample_spectrum/q.sum())
    relative=float((q@sample_spectrum)/(q@white_spectrum))
    cubes[0].data[:]=relative*100+11;cubes[1].data[:]=111
    for band in setup['bands']:
        band['source_spectrum']['relative_power']=[1,1,1]
        band['source_fwhm_nm']=20
    np.testing.assert_allclose(external_band_ratio(*cubes,setup).data,relative)
    assert not np.isclose(relative*white_spectrum[1],expected)
    setup['reference']=dict(kind='effective_kernel_weighted',factors=[float(q@white_spectrum/q.sum())]*3,
        source='SYNTHETIC independent quadrature',kernel_evidence='SYNTHETIC q=[1,2,3]',
        integration_evidence='SYNTHETIC weighted three-node integral')
    np.testing.assert_allclose(external_band_ratio(*cubes,setup).data,expected)
