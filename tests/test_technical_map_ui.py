"""Offscreen integration uses explicit numeric fixtures; no device sessions are opened."""
from copy import deepcopy
import csv
import json

import numpy as np
import pytest
from PySide6 import QtWidgets as W

from hyperlab.io import Cube
from hyperlab.ui.workbench import Workbench


@pytest.fixture
def window(qtbot):
    result = Workbench()
    qtbot.addWidget(result)
    return result


def idle(window, qtbot):
    qtbot.waitUntil(lambda: not window.task_busy, timeout=15000)


def sparse_source(sequence=7):
    raw = np.full((20, 50, 1), 100., np.float64)
    raw.reshape(-1)[[0, 99, 345, 678, 999]] = 200.
    return Cube(raw, {'data_level': 'raw_frame', 'data_source': 'SYNTHETIC', 'units': 'DN',
                     'channel_labels': None, 'pixel_format': 'Mono12', 'sequence': sequence})


def configure_regions(window, source, reference=(1, 0, 2, 1)):
    window.set_cube(source)
    window.apply_roi_bounds(0, reference)
    window.apply_roi_bounds(1, (0, 0, source.shape[1], source.shape[0]))
    window.roi_names[0].setText('Reference')
    window.roi_names[1].setText('Suspect')
    window.roi_timer.stop()
    return window.regions()[1]['roi_id']


def run_map(window, qtbot, method='reference_rmse'):
    window.analysis_method.setCurrentIndex(window.analysis_method.findData(method))
    assert window.run_button.isEnabled(), window.capability_label.text()
    window.run_analysis()
    idle(window, qtbot)
    assert window.map_distributions is not None, window.message.text()
    assert window.right_spec is not None, window.message.text()
    window.roi_timer.stop()


def select_tail(window, qtbot, roi_id):
    window.inspect_roi.setCurrentIndex(window.inspect_roi.findData(roi_id))
    window.brush_low.setValue(100.)
    window.brush_high.setValue(100.)
    window.apply_map_brush()
    idle(window, qtbot)
    assert len(window.map_brushes) == 1, window.message.text()
    return window.map_brushes[0]


def export_right(window, qtbot, directory):
    window.output_dir = directory
    window.figure_export()
    dialog = window._figure_dialog
    selector = next(combo for combo in dialog.findChildren(W.QComboBox)
                    if combo.findText('Right task plot + selections') >= 0)
    selector.setCurrentText('Right task plot + selections')
    next(spin for spin in dialog.findChildren(W.QSpinBox) if spin.maximum() == 1200).setValue(72)
    dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.StandardButton.Save).click()
    idle(window, qtbot)
    outputs = list(directory.glob('figure_*'))
    assert len(outputs) == 1, window.message.text()
    assert (outputs[0]/'analysis_manifest.json').is_file(), window.message.text()
    return outputs[0]


def test_sparse_map_to_amplitude_ecdf_inclusive_brush_and_real_export(window, qtbot, tmp_path):
    source = sparse_source()
    before = source.data.copy()
    roi_id = configure_regions(window, source)
    run_map(window, qtbot)
    assert window.plot_spec.metadata['roi_comparison']
    assert window.plot_spec.series[1]['y'][0] == 100.5
    assert window.roi_results[1]['median'][0] == 100. and window.roi_results[1]['mad'][0] == 0.
    assert window.right_spec.metadata['distribution_mode'] == 'ecdf'
    assert window.right_spec.metadata['aggregation_order'] == 'pixel_transform_then_summary'
    suspect = next(series for series in window.right_spec.series if series['roi']['roi_id'] == roi_id)
    np.testing.assert_equal(suspect['ecdf']['counts'], [995, 5])
    np.testing.assert_equal(suspect['ecdf']['fraction'], [.995, 1.])
    brush = select_tail(window, qtbot, roi_id)
    np.testing.assert_equal(np.flatnonzero(brush['mask']), [0, 99, 345, 678, 999])
    assert brush['metadata']['counts']['selected'] == 5 and brush['metadata']['counts']['used'] == 1000
    assert '5 / 1000 valid / 1000' in window.brush_note.text()
    displayed_x, displayed_y = window.brush_overlay.getData()
    np.testing.assert_equal(displayed_x, brush['coordinates_yx'][:, 1]+.5)
    np.testing.assert_equal(displayed_y, brush['coordinates_yx'][:, 0]+.5)
    directory = export_right(window, qtbot, tmp_path/'exports')
    np.testing.assert_equal(np.load(directory/'brush_01_mask.npy'), brush['mask'])
    with (directory/'brush_01_coordinates.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 5 and all(row['roi_id'] == roi_id and float(row['map_value']) == 100 for row in rows)
    saved = json.loads((directory/'plot.json').read_text())
    assert saved['source']['sequence'] == 7
    assert saved['brushes'][0]['value_range'] == [100., 100.]
    assert saved['metadata']['analysis_context']['regions'][1]['roi_id'] == roi_id
    np.testing.assert_equal(source.data, before)


def test_pinned_map_and_right_export_keep_original_source_after_view_changes(window, qtbot, tmp_path):
    original = sparse_source(sequence=7)
    roi_id = configure_regions(window, original)
    run_map(window, qtbot)
    original_map, original_spec = window.map_spec.image.copy(), window.right_spec
    context = deepcopy(window.map_distribution_context)
    newer = sparse_source(sequence=8)
    newer.data[:] = 17.
    window.set_cube(newer, live=True)
    window.roi_timer.stop()
    assert window.cube is newer and window.product_source is original
    assert window.right_spec is original_spec and window.right_spec.source['sequence'] == 7
    np.testing.assert_equal(window.map_spec.image, original_map)
    assert window.map_distribution_context == context
    brush = select_tail(window, qtbot, roi_id)
    assert brush['metadata']['counts']['selected'] == 5
    output = export_right(window, qtbot, tmp_path/'retained')
    record = json.loads((output/'plot.json').read_text())
    assert record['source']['sequence'] == 7
    assert record['metadata']['source_fingerprint'] == context['source_fingerprint']


@pytest.mark.parametrize('summary', ['median', 'mean'])
def test_rgb_category_points_render_independent_dispersion_whiskers(window, qtbot, summary):
    values = np.array([[[1., 4., 2.], [2., 6., 3.], [9., 8., 11.], [20., 40., 90.]]])
    source = Cube(values, {'data_level': 'raw_frame', 'data_source': 'SYNTHETIC',
                          'units': 'DN', 'channel_labels': ['R', 'G', 'B']})
    configure_regions(window, source, reference=(0, 0, 1, 1))
    window.categorical_style.setCurrentIndex(window.categorical_style.findData('points'))
    window.roi_summary.setCurrentIndex(window.roi_summary.findData(summary))
    run_map(window, qtbot)
    assert window.plot_spec.categories == ['R', 'G', 'B']
    assert window.plot_spec.metadata['categorical_style'] == 'points'
    assert window.curves[1].opts['pen'] is None
    errors = window.error_bars[1].opts
    stats = window.roi_results[1]
    np.testing.assert_equal(errors['x'], [0, 1, 2])
    np.testing.assert_equal(errors['y'], stats[summary])
    if summary == 'median':
        np.testing.assert_equal(errors['bottom'], stats['median']-stats['q25'])
        np.testing.assert_equal(errors['top'], stats['q75']-stats['median'])
        assert not np.array_equal(errors['bottom'], errors['top'])
    else:
        np.testing.assert_equal(errors['height'], 2*stats['std'])


def test_nonlinear_nd_map_summary_is_distinct_from_nd_of_channel_summaries(window, qtbot):
    source = Cube(np.array([[[9., 1.], [1., 1.]]]),
                  {'data_level': 'raw_scan', 'units': 'DN', 'data_source': 'SYNTHETIC'})
    configure_regions(window, source, reference=(0, 0, 1, 1))
    run_map(window, qtbot, 'normalized_difference')
    target = window.map_distributions['regions'][1]
    assert target['statistics']['mean'] == pytest.approx(.4)
    amplitude = window.plot_spec.series[1]['y']
    assert (amplitude[0]-amplitude[1])/(amplitude[0]+amplitude[1]) == pytest.approx(2/3)
    assert window.right_spec.metadata['map_recipe']['low_signal_assessment']['status'] == 'UNKNOWN'


@pytest.mark.parametrize('method,expected,units', [('interval_map', 50., 'DN*nm'), ('interval_mean_map', 5., 'DN')])
def test_interval_map_ui_uses_documented_actual_axis_and_completed_distribution(window, qtbot, method, expected, units):
    data = np.broadcast_to(np.array([0., 3., 10.]), (3, 4, 3)).copy()
    source = Cube(data, {'data_level': 'spectral_cube', 'units': 'DN', 'data_source': 'SYNTHETIC',
                         'wavelengths': [500., 503., 510.], 'wavelength_units': 'nm',
                         'wavelength_source': 'SYNTHETIC analytic fixture'})
    configure_regions(window, source)
    run_map(window, qtbot, method)
    np.testing.assert_allclose(window.map_spec.image, expected)
    assert window.map_spec.metadata['units'] == units
    assert window.right_spec.metadata['map_recipe']['interval_span_nm'] == 10.
    assert window.plot_spec.xlabel == 'Wavelength (nm)'
    assert window.right_spec.metadata['aggregation_order'] == 'pixel_transform_then_summary'


@pytest.mark.parametrize('method', ['interval_map', 'interval_mean_map'])
def test_rgb_cannot_run_wavelength_interval_maps(window, method):
    source = Cube(np.ones((3, 4, 3)), {'data_level': 'raw_frame', 'data_source': 'SYNTHETIC',
                                     'channel_labels': ['R', 'G', 'B']})
    configure_regions(window, source)
    window.analysis_method.setCurrentIndex(window.analysis_method.findData(method))
    assert not window.run_button.isEnabled()
    assert 'wavelength' in window.capability_label.text().lower()


def test_histogram_ui_uses_actual_bin_edges_instead_of_joining_bin_centres(window, qtbot):
    configure_regions(window, sparse_source())
    run_map(window, qtbot)
    window.right_task.setCurrentIndex(window.right_task.findData('histogram'))
    series = window.right_spec.series[1]
    rendered = window.shape_chart.listDataItems()[1]
    x, y = rendered.getData()
    edges, counts = series['histogram']['bin_edges'], series['histogram']['counts']
    np.testing.assert_equal(x, np.repeat(edges, 2)[1:-1])
    np.testing.assert_equal(y, np.repeat(counts, 2))


def test_applied_numeric_brush_range_matches_the_visible_region(window, qtbot):
    roi_id = configure_regions(window, sparse_source())
    run_map(window, qtbot)
    select_tail(window, qtbot, roi_id)
    assert window.brush_region.getRegion() == (100., 100.)


def test_histogram_initial_range_includes_extreme_map_values(window, qtbot):
    configure_regions(window, sparse_source())
    run_map(window, qtbot)
    window.right_task.setCurrentIndex(window.right_task.findData('histogram'))
    assert window.brush_low.value() == 0. and window.brush_high.value() == 100.
