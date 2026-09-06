"""ROI task binding and source lifetime regressions; offline fixtures only."""
from copy import deepcopy
from threading import Event
import numpy as np
import pytest
from PySide6 import QtWidgets as W

from hyperlab.io import Cube
from hyperlab.analysis.regions import make_roi
from hyperlab.ui.workbench import Workbench


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('HYPERLAB_CONFIG_DIR', str(tmp_path/'config'))
    monkeypatch.setenv('HYPERLAB_WORKSPACE', str(tmp_path/'workspace'))


def idle(window, qtbot):
    qtbot.waitUntil(lambda: not window.task_busy, timeout=10000)
    window.roi_timer.stop()


@pytest.fixture
def mapped(window, qtbot):
    window.set_cube(Cube(np.arange(144, dtype=float).reshape(12,12,1),
        {'data_level':'raw_frame','data_source':'SYNTHETIC','units':'DN','sequence':7}))
    for i, y in enumerate((.5, 10.5)):
        window.roi_records[i] = make_roi((12,12), {'type':'strip','points':[[.5,y],[10.5,y]],'width_px':.5},
            name=f'ROI {chr(65+i)}', role='reference' if i == 0 else 'target')
    window.reference_roi_id = window.roi_records[0]['roi_id']
    window.rebuild_roi_graphics(); window.roi_changed(); window.roi_timer.stop()
    window.analyze('reference_rmse'); idle(window, qtbot)
    assert window.map_distributions is not None, window.message.text()
    return window


@pytest.fixture
def window(qtbot):
    value = Workbench(); qtbot.addWidget(value)
    return value


def test_profile_selection_changed_during_compute_never_labels_old_roi_as_current(mapped, qtbot, monkeypatch):
    import hyperlab.analysis.regions as regions
    entered, release = Event(), Event()
    actual = regions.strip_profile
    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return actual(*args, **kwargs)
    monkeypatch.setattr(regions, 'strip_profile', paused)
    mapped.inspect_roi.setCurrentIndex(0)
    mapped.right_task.setCurrentIndex(mapped.right_task.findData('profile'))
    qtbot.waitUntil(entered.is_set, timeout=3000)
    mapped.inspect_roi.setCurrentIndex(1)
    requested = mapped.inspect_roi.currentData()
    release.set(); idle(mapped, qtbot)
    assert mapped.right_spec.metadata.get('roi_definition', {}).get('roi_id') == requested, (
        'The completed profile belongs to the old ROI while the inspector shows the new ROI',
        mapped.right_spec.metadata.get('roi_definition', {}), requested, mapped.message.text())


def test_brush_selection_changed_during_compute_never_rebinds_old_roi_to_current(mapped, qtbot, monkeypatch):
    import hyperlab.analysis.distributions as distributions
    entered, release = Event(), Event()
    actual = distributions.brush_map
    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return actual(*args, **kwargs)
    monkeypatch.setattr(distributions, 'brush_map', paused)
    mapped.inspect_roi.setCurrentIndex(0)
    mapped.brush_low.setValue(0); mapped.brush_high.setValue(999)
    mapped.apply_map_brush(); qtbot.waitUntil(entered.is_set, timeout=3000)
    mapped.inspect_roi.setCurrentIndex(1)
    requested = mapped.inspect_roi.currentData()
    release.set(); idle(mapped, qtbot)
    assert mapped.map_brushes and mapped.map_brushes[0]['metadata']['roi']['roi_id'] == requested, (
        'The applied selection belongs to the old ROI while the inspector shows the new ROI',
        mapped.map_brushes[0]['metadata']['roi']['roi_id'], requested, mapped.brush_note.text())


def test_role_editor_replaces_reference_without_leaving_two_reference_roles(mapped):
    from hyperlab.ui.roi_dialog import edit_regions
    edit_regions(mapped)
    dialog = mapped._roi_bounds_dialog
    target = dialog.findChild(W.QComboBox, 'roi_bounds_target')
    target.setCurrentIndex(1)
    role = next(item for item in dialog.findChildren(W.QComboBox) if item.findText('exclude') >= 0)
    role.setCurrentText('reference')
    dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.StandardButton.Apply).click()
    records = mapped.regions()
    assert [item['roi_id'] for item in records if item['role'] == 'reference'] == [mapped.reference_roi_id]


def test_offline_source_replacement_during_analysis_discards_completed_old_result(window, qtbot, monkeypatch):
    import hyperlab.analysis as analysis
    entered, release = Event(), Event()
    actual = analysis.roi_comparison
    def paused(*args, **kwargs):
        entered.set(); assert release.wait(5)
        return actual(*args, **kwargs)
    monkeypatch.setattr(analysis, 'roi_comparison', paused)
    window.set_cube(Cube(np.full((8,8,1),10.), {'data_level':'raw_frame','data_source':'SYNTHETIC','sequence':1}))
    window.roi_timer.stop(); window.analyze_rois(); qtbot.waitUntil(entered.is_set,timeout=3000)
    window.set_cube(Cube(np.full((8,8,1),50.), {'data_level':'raw_frame','data_source':'SYNTHETIC','sequence':2}))
    window.roi_timer.stop(); release.set(); idle(window,qtbot)
    assert window.roi_results == []
    assert window.cube.metadata['sequence'] == 2
    assert 'obsolete result discarded' in window.message.text()


def test_histogram_inplace_renews_source_recipe_and_curve_with_current_frame(window):
    first = Cube(np.arange(36.).reshape(6,6,1), {'data_level':'raw_frame','data_source':'SYNTHETIC','sequence':1,'units':'DN'})
    second = Cube(np.arange(36.).reshape(6,6,1)+100, {'data_level':'raw_frame','data_source':'SYNTHETIC','sequence':2,'units':'DN'})
    window.set_cube(first); window.roi_timer.stop()
    old_curve = window.curves[0]
    window.set_cube(second,live=True); window.last_quality=0; window.render_current()
    assert window.curves[0] is old_curve
    assert window.plot_spec.source['sequence'] == 2 and window.plot_source is second
    assert np.min(window.curves[0].getData()[0]) >= 100
    assert window.plot_spec.metadata['statistics_source']['sequence'] == 2


def test_open_geometry_editor_keeps_stable_target_after_another_roi_is_removed(window):
    from hyperlab.ui.roi_dialog import edit_regions
    window.set_cube(Cube(np.arange(144.).reshape(12,12,1),{'data_level':'raw_frame','data_source':'SYNTHETIC'}))
    window.add_roi('ROI C', (8,8,11,11))
    records = window.regions()
    unchanged_id, unchanged_geometry = records[2]['roi_id'], deepcopy(records[2]['geometry'])
    edit_regions(window)
    dialog = window._roi_bounds_dialog
    dialog.findChild(W.QComboBox, 'roi_bounds_target').setCurrentIndex(1)  # The visible target is ROI B.
    window.remove_roi(0)  # Main-window row controls remain accessible while the editor is open.
    dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.StandardButton.Apply).click()
    current = next(item for item in window.regions() if item['roi_id'] == unchanged_id)
    assert current['geometry'] == unchanged_geometry, 'Applying the visible ROI B editor changed ROI C after row removal'


def test_figure_dialog_does_not_retain_closed_mmap_as_export_source(window, qtbot, tmp_path):
    from hyperlab.io import save_cube, load_cube
    first, second = tmp_path/'first.npy', tmp_path/'second.npy'
    for path, value in ((first,10.),(second,20.)):
        save_cube(Cube(np.full((8,8,1),value),{'data_level':'raw_frame','data_source':'SYNTHETIC'}),path)
    old = load_cube(first)
    window.set_cube(old); window.roi_timer.stop(); window.figure_export()
    dialog = window._figure_dialog
    assert dialog.isVisible()
    window.open_path(second); idle(window, qtbot)
    # Do not dereference a closed mmap: that can terminate CPython on Windows.
    dangling_source = bool(dialog.isVisible()) and bool(old.data._mmap.closed)
    if dangling_source:
        pytest.fail('Modeless Figure export remains callable after open_path closes its previously captured source mmap')


def test_large_brush_overview_keeps_sparse_edge_hits_and_exact_full_mask(window, qtbot):
    from hyperlab.plots import PlotSpec
    shape = (603,73)
    values = np.zeros(shape)
    values[:400] = 1
    values[602,[0,3,21,51,72]] = 1
    window.set_cube(Cube(values[...,None],{'data_level':'raw_frame','data_source':'SYNTHETIC'}))
    window.roi_timer.stop()
    record = make_roi(shape,{'type':'rectangle','bounds':[0,0,73,603]})
    window.map_distribution_product = {'data':values,'valid_mask':np.ones(shape,bool),'metadata':{'units':'DN'}}
    window.map_distribution_context = {'regions':[record],'exclusions':[]}
    window.inspect_roi.blockSignals(True); window.inspect_roi.clear()
    window.inspect_roi.addItem('Large target',record['roi_id']); window.inspect_roi.blockSignals(False)
    window.map_distributions = {}
    window.right_spec = PlotSpec('lines','Fixture','Value','Count')
    window.brush_low.setValue(1); window.brush_high.setValue(1)
    window.apply_map_brush(); idle(window,qtbot)
    actual = window.map_brushes[0]
    expected = values == 1
    np.testing.assert_equal(actual['mask'],expected)
    assert actual['metadata']['counts']['selected'] == 29205
    assert actual['metadata']['display_selection']['stride_yx'] == [2,1]
    oracle = np.stack([expected[start:start+2].any(axis=0) for start in range(0,603,2)])
    np.testing.assert_equal(window.brush_mask_overlay.image,oracle)
    np.testing.assert_equal(np.flatnonzero(window.brush_mask_overlay.image[-1]),[0,3,21,51,72])
    assert len(actual['coordinates_yx']) == 29205
