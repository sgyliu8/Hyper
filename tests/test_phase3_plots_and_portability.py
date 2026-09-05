import csv
import json
from pathlib import Path
from types import SimpleNamespace
import time
import zipfile

import numpy as np
import pytest
from PySide6 import QtCore

from hyperlab.io import Cube, make_synthetic_cube, save_cube
from hyperlab.analysis import roi_statistics, pca, difference, spectral_angle
from hyperlab.plots import (COLORS, TemporalTrace, sequence_coordinates, source_identity,
    roi_plot, map_plot, pca_diagnostics, export_figure_bundle)
from hyperlab.ui.view import display_selection
from hyperlab.ui.workbench import Workbench
from hyperlab.paths import workspace, config_directory
from hyperlab.calibration import export_references, import_references, locate_reference, file_digest
from hyperlab.devices import profiles_from_snapshot
from test_camera_session import make_backend


def test_same_live_frame_twenty_redraws_and_definition_segments():
    trace = TemporalTrace()
    meta = {'session_id':'fixture','stream_epoch':1,'sequence':4,'host_monotonic_ns':10**12,'display_mode':'LIVE'}
    for _ in range(20):
        trace.add(meta,[12,14],{'roi':[0,0,3,3]})
    assert len(trace)==1
    trace.add(dict(meta,sequence=5,host_monotonic_ns=10**12+50_000_000),[13,15],{'roi':[0,0,3,3]})
    assert list(trace.points.values())[-1][0] == .05
    trace.add(meta,[4,8],{'roi':[1,1,4,4]})
    assert len(trace)==1 and trace.segment==2


def test_replay_coordinates_are_independent_of_visit_order():
    records = [{'session_id':'fixture','host_monotonic_ns':10**12+i*50_000_000} for i in range(3)]
    sequence = SimpleNamespace(path='sequence.npy',metadata={'frames':records})
    results=[]
    for order in ([0,1,2],[2,0,1,2,2]):
        trace=TemporalTrace()
        for index in order:
            trace.add({},[index],{'roi':[0,0,2,2]},sequence=sequence,index=index)
        results.append(trace.plot(['ROI A'],COLORS,{}).series[0]['x'])
    np.testing.assert_equal(results[0],results[1])
    np.testing.assert_allclose(results[0],[0,.05,.1])
    records[1]['session_id']='another_clock'
    x,label=sequence_coordinates(records)
    np.testing.assert_equal(x,[0,1,2]); assert 'index' in label


@pytest.mark.parametrize('mask_kind',['HW','HWK'])
@pytest.mark.parametrize('policy,expected',[('diagnostic',2),('quantitative',1)])
def test_display_validity_histogram_limits_and_bad_band(mask_kind,policy,expected):
    data=np.array([[[10,1],[4095,2]], [[-9999,3],[20,4]]],float)
    mask=np.array([[True,True],[True,False]])
    if mask_kind=='HWK': mask=np.repeat(mask[...,None],2,axis=2)
    cube=Cube(data,{'data_ignore_value':-9999,'effective_bits':12,'band_validity':[True,False]},mask)
    selection=display_selection(cube,0,policy=policy)
    assert selection['sample_count']==expected
    assert selection['levels'][0]>=10
    assert np.isfinite(selection['image']).sum()==expected
    assert display_selection(cube,1,policy=policy)['sample_count']==0
    assert not np.isnan(data[1,0,0])  # Raw sentinel is preserved.


def test_plot_bundle_values_units_gaps_and_vector_text(tmp_path):
    cube=make_synthetic_cube()
    cube.metadata['band_validity']=[i!=2 for i in range(cube.shape[2])]
    results=[roi_statistics(cube,rect) for rect in ((0,0,12,12),(16,16,28,28))]
    spec=roi_plot(results,['Reference ROI','Sample ROI'],COLORS,source=source_identity(cube),normalized=True)
    assert np.isnan(spec.series[0]['y'][2])
    output=export_figure_bundle(spec,tmp_path/'figure',dpi=100)
    record=json.loads((output/'plot.json').read_text())
    assert record['metadata']['std_ddof']==0 and record['series'][0]['y'][2] is None
    rows=list(csv.DictReader((output/'series.csv').open()))
    assert float(rows[0]['y'])==spec.series[0]['y'][0]
    svg=(output/'figure.svg').read_text()
    assert '<text' in svg and 'Wavelength' in svg and 'Reference ROI' in svg and 'SYNTHETIC' in svg
    assert (output/'figure.pdf').stat().st_size>1000


def test_map_semantic_centres_angle_conversion_and_pca_features(tmp_path):
    cube=make_synthetic_cube()
    result=difference(cube,0,1)
    spec=map_plot(result,source_identity(cube))
    assert spec.limits[0]==-spec.limits[1] and spec.metadata['semantic_center']==0
    output=export_figure_bundle(spec,tmp_path/'map',dpi=100)
    np.testing.assert_equal(np.load(output/'values.npy'),result['data'])
    assert 'Invalid / masked' in (output/'figure.svg').read_text()
    angle=spectral_angle(cube,roi_statistics(cube,(0,0,10,10))['mean'])
    degrees=map_plot(angle,source_identity(cube),degrees=True)
    np.testing.assert_allclose(degrees.image,np.rad2deg(angle['data']))
    cube.metadata['band_validity']=[i!=3 for i in range(cube.shape[2])]
    pcs=pca(cube)
    variance,loadings=pca_diagnostics(pcs,cube)
    assert np.isnan(loadings.series[0]['y'][3])
    np.testing.assert_equal(variance.series[0]['y'],pcs['explained_variance_ratio'])
    assert map_plot(pcs,source_identity(cube),component=1).title.endswith('PC2 score')


def test_required_read_preserves_timeout_and_optional_absence(tmp_path,monkeypatch):
    backend,camera,_=make_backend(tmp_path,monkeypatch)
    backend.open()
    class Broken:
        @property
        def value(self): raise TimeoutError('injected transport timeout')
    camera.nodes.Width=Broken()
    with pytest.raises(TimeoutError,match='transport'):
        backend.read_settings()
    assert backend.node_evidence['Width']['status']=='read_error'
    assert backend.node_evidence['Width']['exception_type']=='TimeoutError'
    assert backend.probe_node('MissingOptional')['status']=='unsupported'
    backend.close()


def test_isolated_deadline_does_not_block_qt(qtbot,tmp_path):
    from hyperlab.diagnostics import IsolatedDiagnostic, _offline_delay
    ticks=[]
    timer=QtCore.QTimer(); timer.timeout.connect(lambda:ticks.append(1)); timer.start(10)
    entered=tmp_path/'native-entered.txt'
    job=IsolatedDiagnostic(_offline_delay,(10,str(entered)),timeout=3,receipt=tmp_path/'timeout.json')
    result=[]
    def poll():
        value=job.poll()
        if value: result.append(value)
        return bool(result)
    qtbot.waitUntil(poll,timeout=5000)
    timer.stop()
    assert len(ticks)>10
    assert entered.read_text()=='ENTERED_NATIVE_WAIT'
    assert result[0]['status']=='TIMEOUT' and result[0]['device_release']=='NOT_CONFIRMED'


def test_benchmark_rejects_cached_epoch_and_prestart_receive():
    from hyperlab.benchmark import frame_belongs_to_start
    from hyperlab.acquisition.frame import Frame
    state={'stream_epoch':2,'stream_started_ns':1000}
    def sample(epoch,received):
        return Frame(np.ones((2,2),np.uint16),{'session_id':'fixture','sequence':1,
            'stream_epoch':epoch,'host_monotonic_ns':received})
    assert not frame_belongs_to_start(sample(1,2000),state)
    assert not frame_belongs_to_start(sample(2,500),state)
    assert frame_belongs_to_start(sample(2,2000),state)


def test_reference_export_refuses_external_sidecar_mask(tmp_path):
    path=tmp_path/'sample.npy'; cube=make_synthetic_cube(); save_cube(cube,path)
    sidecar=path.with_suffix('.npy.json')
    metadata=json.loads(sidecar.read_text()); metadata['valid_mask_file']='../unrelated.npy'
    sidecar.write_text(json.dumps(metadata))
    record={'path':str(path),'metadata':cube.metadata}
    with pytest.raises(ValueError,match='adjacent'):
        export_references([record],tmp_path/'blocked.zip')
    assert not (tmp_path/'blocked.zip').exists()


def test_multiple_rois_references_and_view_restore(qtbot,tmp_path):
    path=tmp_path/'source.npy'; save_cube(make_synthetic_cube(),path)
    first=Workbench(); qtbot.addWidget(first)
    first.open_path(path); qtbot.waitUntil(lambda:first.cube is not None and not first.task_busy)
    first.add_roi('Third region',(4,5,18,20))
    first.roi_names[0].setText('Reference region')
    first.roi_visible[1].setChecked(False)
    first._reference_added({'kind':'sample','label':'Fixture','path':str(path),'metadata':first.cube.metadata})
    first.add_recent(path)
    first.band.setValue(2)
    first.close()
    assert (config_directory()/'settings.json').exists()
    second=Workbench(); qtbot.addWidget(second)
    qtbot.waitUntil(lambda:second.cube is not None and not second.task_busy)
    assert len(second.rois)==3 and second.rectangles()[2]==(4,5,18,20)
    assert second.roi_names[0].text()=='Reference region'
    assert not second.rois[1].isVisible()
    assert second.references.count()==1 and second.recent_list.count()==1
    assert second.band.value()==2


def test_stale_roi_result_does_not_replace_new_definition(qtbot,monkeypatch):
    window=Workbench(); qtbot.addWidget(window); window.set_cube(make_synthetic_cube())
    pending={}
    monkeypatch.setattr(window,'background',lambda run,done,message:pending.update(run=run,done=done))
    window.analyze_rois()
    result=pending['run']()
    window.roi_names[0].setText('Changed while working')
    pending['done'](result)
    assert not window.roi_results
    assert 'obsolete' in window.message.text().lower()


def test_same_geometry_new_source_invalidates_pending_analysis(qtbot,monkeypatch):
    window=Workbench(); qtbot.addWidget(window); window.set_cube(make_synthetic_cube())
    pending={}
    monkeypatch.setattr(window,'background',lambda run,done,message:pending.update(run=run,done=done))
    window.analyze_rois(); result=pending['run']()
    window.set_cube(make_synthetic_cube())
    pending['done'](result)
    assert not window.roi_results and 'obsolete' in window.message.text().lower()


def test_new_source_clears_previous_pca_chart_and_export(qtbot):
    window=Workbench(); qtbot.addWidget(window)
    first=make_synthetic_cube(); first.metadata['source_file']='first.npy'
    window.set_cube(first)
    window.product=pca(first); window.product_source=first
    window.plot_mode.setCurrentIndex(4)
    window.update_chart(window.image.image)
    assert window.plot_spec.title=='PCA loadings'
    second=make_synthetic_cube(); second.metadata['source_file']='second.npy'
    window.set_cube(second)
    assert window.plot_spec.source['source_file']=='second.npy'
    assert window.plot_spec.title=='Sampled histogram'
    assert window.product is None and window.map_spec is None


def test_reference_bundle_roundtrip_device_mismatch_and_locate(tmp_path):
    path=tmp_path/'sample.npy'; cube=make_synthetic_cube(); save_cube(cube,path)
    record={'kind':'reference','label':'Fixture','path':str(path),'metadata':dict(cube.metadata,serial='SYNTHETIC_DEVICE')}
    package=export_references([record],tmp_path/'private.zip')
    result=import_references(package,tmp_path/'imported',device_serial='ANOTHER_SYNTHETIC_DEVICE')[0]
    assert result['device_compatibility']=='MISMATCH' and not result['calibration_applied']
    np.testing.assert_equal(np.load(result['path']),cube.data)
    assert locate_reference(dict(record,sha256=file_digest(path)),result['path'])['relocation_evidence']=='BYTE_MATCH'
    with zipfile.ZipFile(tmp_path/'bad.zip','w') as archive:
        archive.writestr('../outside.txt','bad')
    with pytest.raises(ValueError,match='Unsafe'):
        import_references(tmp_path/'bad.zip',tmp_path/'blocked')


def test_packaged_resource_and_cwd_independent_workspace(tmp_path,monkeypatch):
    from importlib.resources import files
    resource=files('hyperlab.resources').joinpath('Probe-Devices.ps1')
    assert resource.is_file() and 'Get-PnpDevice' in resource.read_text(encoding='utf-8')
    before=workspace()
    monkeypatch.chdir(tmp_path)
    assert workspace()==before and workspace()!=tmp_path/'local'
    report=profiles_from_snapshot({'devices':[]},[])
    assert {item['code'] for item in report['issues']}=={'NO_CAMERA','RUNTIME_MISSING'}


def test_support_report_contains_no_raw_identifiers():
    from hyperlab.support import redacted_report
    output=json.dumps(redacted_report({'serial':'PRIVATE_SERIAL','error':r'C:\private\file',
        'phases':[{'phase':'open','status':'FAILED','error':'PRIVATE_SERIAL','exception_type':'TimeoutError'}]}))
    assert 'PRIVATE_SERIAL' not in output and 'C:\\private' not in output


def test_missing_package_error_survives_worker_string_transport():
    from hyperlab.devices import connection_error_kind
    assert connection_error_kind("No module named 'harvesters'")=='Python acquisition package missing'
    assert connection_error_kind('GenCP timeout')=='Communication fault'


def test_default_qt_entry_does_not_require_legacy_tk():
    import subprocess
    import sys
    code = """
import importlib.abc, sys
class NoTk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('tkinter'):
            raise ModuleNotFoundError('Tk deliberately absent')
sys.meta_path.insert(0, NoTk())
import hyperlab.ui
from hyperlab.ui.workbench import launch
assert hyperlab.ui.launch is launch
assert 'tkinter' not in sys.modules
"""
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
