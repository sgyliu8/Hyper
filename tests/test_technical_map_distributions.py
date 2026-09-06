"""Independent sparse-tail, nonlinearity, geometry and publication-data oracles."""
from copy import deepcopy
import csv
import hashlib
import json

import numpy as np
import pytest

from hyperlab.analysis import roi_statistics
from hyperlab.analysis.distributions import brush_map, map_roi_distributions
from hyperlab.analysis.maps import normalized_difference, reference_rmse
from hyperlab.analysis.regions import make_roi, mask_geometry, resolve_roi
from hyperlab.io import Cube
from hyperlab.plots import COLORS, export_figure_bundle, map_distribution_plot, render_figure, roi_plot, source_identity


def rectangle(shape, bounds, **kwargs):
    return make_roi(shape, {'type': 'rectangle', 'bounds': bounds}, **kwargs)


def sparse_case():
    raw = np.full((20, 50, 1), 100., np.float64)
    indices = [0, 99, 345, 678, 999]
    raw.reshape(-1)[indices] = 200.
    cube = Cube(raw, {'data_level': 'raw_frame', 'units': 'DN', 'data_source': 'SYNTHETIC'})
    return cube, reference_rmse(cube, [100.]), indices


def test_five_of_thousand_tail_survives_unchanged_robust_summaries():
    cube, product, indices = sparse_case()
    before = cube.data.copy()
    stats = roi_statistics(cube, (0, 0, 50, 20))
    assert stats['mean'][0] == 100.5 and stats['median'][0] == 100 and stats['mad'][0] == 0
    assert np.quantile(cube.data, .99) == 100
    roi = rectangle((20, 50), [0, 0, 50, 20], roi_id='target', name='Paint', color=COLORS[0])
    result = map_roi_distributions(product, [roi], bins=4)
    region = result['regions'][0]
    assert region['statistics']['mean'] == .5 and region['statistics']['median'] == 0
    np.testing.assert_equal(region['ecdf']['values'], [0, 100])
    np.testing.assert_equal(region['ecdf']['counts'], [995, 5])
    np.testing.assert_equal(region['ecdf']['cumulative_counts'], [995, 1000])
    np.testing.assert_equal(region['ecdf']['fraction'], [.995, 1])
    np.testing.assert_equal(region['histogram']['counts'], [995, 0, 0, 5])
    brush = brush_map(product, roi, [100, 100])
    assert brush['metadata']['counts']['selected'] == 5 and brush['metadata']['counts']['used'] == 1000
    np.testing.assert_equal(np.flatnonzero(brush['mask']), indices)
    np.testing.assert_equal(brush['coordinates_yx'], [[0, 0], [1, 49], [6, 45], [13, 28], [19, 49]])
    assert brush['metadata']['selected_fraction_of_used'] == .005
    assert result['metadata']['sampling'] == 'exact'
    np.testing.assert_array_equal(cube.data, before)


def test_nonlinear_orders_are_distinct_and_use_the_same_pixels():
    cube = Cube(np.array([[[9., 1.], [1., 1.]]]), {'data_level': 'raw_scan', 'units': 'DN'})
    product = normalized_difference(cube, 0, 1)
    stats = roi_statistics(cube, (0, 0, 2, 1), support='common')
    channel_means = stats['mean']
    summary_then_transform = (channel_means[0]-channel_means[1])/(channel_means[0]+channel_means[1])
    result = map_roi_distributions(product, [(0, 0, 2, 1)])
    assert result['regions'][0]['statistics']['mean'] == .4
    assert summary_then_transform == pytest.approx(2/3)
    assert result['metadata']['aggregation_order'] == 'pixel_transform_then_summary'
    assert result['metadata']['map_recipe']['low_signal_assessment']['status'] == 'UNKNOWN'


def test_exclusion_invalidity_and_map_reasons_have_explicit_denominators():
    _, product, _ = sparse_case()
    product['valid_mask'][1, 49] = False
    reasons = np.zeros((20, 50), bool)
    reasons[1, 49] = True
    product['reason_masks'] = {'source_invalid': reasons}
    roi = rectangle((20, 50), [0, 0, 50, 20])
    exclude = rectangle((20, 50), [0, 0, 1, 1], role='exclude')
    result = map_roi_distributions(product, [roi], exclusions=[exclude])['regions'][0]
    assert result['counts'] == {'geometry': 1000, 'excluded': 1, 'after_exclusion': 999,
                                'invalid_after_exclusion': 1, 'used': 998}
    assert result['reason_counts']['source_invalid'] == 1
    assert result['ecdf']['counts'].sum() == result['histogram']['counts'].sum() == 998
    brush = brush_map(product, roi, [50, 100], exclusions=[exclude])
    np.testing.assert_equal(np.flatnonzero(brush['mask']), [345, 678, 999])
    assert brush['metadata']['counts']['selected'] == 3
    assert np.isfinite(brush['values']).all()


def test_polygon_mask_hole_resolved_input_and_shared_bins_agree(tmp_path):
    data = np.arange(24, dtype=float).reshape(4, 6)
    product = {'data': data, 'valid_mask': np.ones((4, 6), bool), 'metadata': {'units': 'DN'}}
    polygon = make_roi((4, 6), {'type': 'polygon', 'vertices': [[1, 0], [5, 0], [5, 4], [1, 4]],
                                'holes': [[[2, 1], [4, 1], [4, 3], [2, 3]]]})
    membership = np.zeros((4, 6), bool)
    membership[:, 1:5] = True
    membership[1:3, 2:4] = False
    np.save(tmp_path/'mask.npy', membership)
    mask = make_roi((4, 6), mask_geometry(tmp_path/'mask.npy', (4, 6)))
    result = map_roi_distributions(product, [polygon, resolve_roi((4, 6), mask)], bins=7)
    expected = data[membership]
    for item in result['regions']:
        assert item['counts']['geometry'] == 12 and item['counts']['used'] == 12
        assert item['statistics']['mean'] == expected.mean()
        np.testing.assert_equal(item['ecdf']['values'], np.sort(expected))
        assert item['roi']['membership_sha256']
    np.testing.assert_equal(result['regions'][0]['histogram']['bin_edges'], result['regions'][1]['histogram']['bin_edges'])
    with pytest.raises(ValueError, match='resolved|exclusions'):
        map_roi_distributions(product, [resolve_roi((4, 6), mask)], exclusions=[polygon])


def test_empty_geometry_all_invalid_and_no_matches_keep_empty_results():
    product = {'data': np.full((3, 4), np.nan), 'valid_mask': np.zeros((3, 4), bool), 'metadata': {'units': 'DN'}}
    empty = rectangle((3, 4), [1, 1, 1, 1])
    result = map_roi_distributions(product, [empty, (0, 0, 4, 3)])
    assert result['regions'][0]['counts']['geometry'] == 0
    assert result['regions'][1]['counts']['invalid_after_exclusion'] == 12
    assert all(item['statistics']['median'] is None and item['ecdf']['sample_count'] == 0 for item in result['regions'])
    for roi in (empty, (0, 0, 4, 3)):
        brush = brush_map(product, roi, [0, 1])
        assert brush['coordinates_yx'].shape == (0, 2) and brush['values'].size == 0
        assert not brush['mask'].any() and brush['metadata']['selected_fraction_of_used'] is None


@pytest.mark.parametrize('flag', [{'preview_only': True}, {'sampled': True}, {'sampling': 'stride 4'}])
def test_preview_sampling_never_enters_formal_distribution_or_brush(flag):
    product = {'data': np.ones((3, 4)), 'valid_mask': np.ones((3, 4), bool), 'metadata': flag}
    with pytest.raises(ValueError, match='sampled'):
        map_roi_distributions(product, [(0, 0, 4, 3)])
    with pytest.raises(ValueError, match='sampled'):
        brush_map(product, (0, 0, 4, 3), [0, 2])


@pytest.mark.parametrize('bounds', [[1, 0], [0, float('nan')], [0, float('inf')], [0]])
def test_ambiguous_brush_bounds_rejected(bounds):
    _, product, _ = sparse_case()
    with pytest.raises(ValueError, match='range'):
        brush_map(product, (0, 0, 50, 20), bounds)


def test_exact_ecdf_histogram_brush_and_manifest_exports(tmp_path):
    cube, product, indices = sparse_case()
    roi = rectangle((20, 50), [0, 0, 50, 20], roi_id='paint-A', name='Paint A', revision=3)
    result = map_roi_distributions(product, [roi], bins=4)
    brush = brush_map(product, roi, [50, 100])
    spec = map_distribution_plot(result, source=source_identity(cube), brushes=[brush])
    record = spec.record()
    assert 'mask' not in record['brushes'][0] and 'coordinates_yx' not in record['brushes'][0]
    assert record['brushes'][0]['counts']['selected'] == 5
    figure = render_figure(spec)
    assert figure.axes[0].lines[0].get_drawstyle() == 'steps-post'
    output = export_figure_bundle(spec, tmp_path/'figure', source_cube=cube)
    with (output/'ecdf.csv').open() as stream:
        ecdf = list(csv.DictReader(stream))
    assert [int(row['count_at_value']) for row in ecdf] == [995, 5]
    assert [float(row['cumulative_fraction']) for row in ecdf] == [.995, 1]
    with (output/'series.csv').open() as stream:
        assert all(row['feature_index'] == '' for row in csv.DictReader(stream))
    with (output/'map_histograms.csv').open() as stream:
        histogram = list(csv.DictReader(stream))
    assert sum(int(row['count']) for row in histogram) == 1000
    np.testing.assert_equal(np.flatnonzero(np.load(output/'brush_01_mask.npy')), indices)
    with (output/'brush_01_coordinates.csv').open() as stream:
        coordinates = list(csv.DictReader(stream))
    assert len(coordinates) == 5
    assert [(int(row['raw_y_index']), int(row['raw_x_index'])) for row in coordinates] == [(0, 0), (1, 49), (6, 45), (13, 28), (19, 49)]
    assert all(float(row['map_value']) == 100 for row in coordinates)
    saved = json.loads((output/'plot.json').read_text())
    assert saved['metadata']['aggregation_order'] == 'pixel_transform_then_summary'
    assert saved['brushes'][0]['mask_file'] == 'brush_01_mask.npy'
    manifest = json.loads((output/'analysis_manifest.json').read_text())
    for item in manifest['outputs']:
        assert hashlib.sha256((output/item['path']).read_bytes()).hexdigest() == item['sha256']


def test_categorical_median_uses_asymmetric_whiskers_and_preserves_connected_option():
    cube = Cube(np.array([[[1., 4., 2.], [2., 6., 3.], [9., 8., 11.], [20., 40., 90.]]]),
                {'data_level': 'raw_frame', 'units': 'DN', 'channel_labels': ['R', 'G', 'B']})
    result = [roi_statistics(cube, (0, 0, 4, 1))]
    before = deepcopy(result[0])
    spec = roi_plot(result, ['Paint'], COLORS, source=source_identity(cube), summary='median', categorical_style='points')
    figure = render_figure(spec)
    line = figure.axes[0].lines[0]
    assert line.get_linestyle() == 'None' and line.get_marker() == 'o'
    assert len(figure.axes[0].containers) == 1
    segments = figure.axes[0].containers[0].lines[2][0].get_segments()
    for i, segment in enumerate(segments):
        np.testing.assert_allclose(segment[:, 1], [result[0]['q25'][i], result[0]['q75'][i]])
    connected = roi_plot(result, ['Paint'], COLORS, source={}, summary='median')
    assert connected.metadata['categorical_style'] == 'connected'
    np.testing.assert_equal(result[0]['median'], before['median'])
    np.testing.assert_equal(result[0]['mean'], before['mean'])


def test_histogram_render_uses_real_bin_edges_and_shared_source():
    cube, product, _ = sparse_case()
    result = map_roi_distributions(product, [(0, 0, 50, 20)], bins=4)
    spec = map_distribution_plot(result, source=source_identity(cube), mode='histogram')
    figure = render_figure(spec)
    values, edges, _ = figure.axes[0].patches[0].get_data()
    np.testing.assert_equal(values, [995, 0, 0, 5])
    np.testing.assert_equal(edges, [0, 25, 50, 75, 100])
    assert spec.source['acquisition_source'] == 'SYNTHETIC'


def test_constant_map_ecdf_includes_its_full_initial_jump():
    product = {'data': np.zeros((2, 3)), 'valid_mask': np.ones((2, 3), bool)}
    result = map_roi_distributions(product, [(0, 0, 3, 2)])
    spec = map_distribution_plot(result, source={})
    np.testing.assert_equal(spec.series[0]['ecdf']['counts'], [6])
    figure = render_figure(spec)
    np.testing.assert_equal(figure.axes[0].collections[0].get_segments()[0], [[0, 0], [0, 1]])


def test_amplitude_export_keeps_roi_revision_geometry_exclusions_and_complete_denominators(tmp_path):
    source = Cube(np.ones((3, 4, 3)), {'data_level': 'raw_frame', 'units': 'DN', 'channel_labels': ['R', 'G', 'B']})
    roi = rectangle((3, 4), [0, 0, 4, 3], roi_id='paint-A', revision=4)
    excluded = rectangle((3, 4), [0, 0, 1, 1], roi_id='glint-1', role='exclude')
    stats = roi_statistics(source, roi, exclusions=[excluded])
    spec = roi_plot([stats], ['Paint A'], COLORS, source=source_identity(source), categorical_style='points')
    output = export_figure_bundle(spec, tmp_path/'amplitude', source_cube=source)
    saved = json.loads((output/'plot.json').read_text())['series'][0]
    assert saved['roi_definition']['roi_id'] == 'paint-A' and saved['roi_definition']['revision'] == 4
    assert saved['exclusion_definitions'][0]['roi_id'] == 'glint-1'
    assert saved['geometry_counts'] == {'geometry_count': 12, 'excluded_count': 1, 'selected_count': 11}
    product = {'data': np.ones((3, 4)), 'valid_mask': np.ones((3, 4), bool)}
    derived = map_roi_distributions(product, [roi], exclusions=[excluded])
    brush = brush_map(product, roi, [1, 1], exclusions=[excluded])
    assert derived['regions'][0]['roi']['exclusion_definitions'][0]['roi_id'] == 'glint-1'
    assert brush['metadata']['roi']['exclusion_definitions'][0]['roi_id'] == 'glint-1'
    with (output/'series.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 3
    for row in rows:
        assert row['roi_id'] == 'paint-A' and row['roi_revision'] == '4'
        assert row['geometry_count'] == '12' and row['excluded_geometry_count'] == '1'
        assert row['geometry_excluded_count'] == '1' and row['used_count'] == '11'
