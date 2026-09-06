"""Independent raw-coordinate membership, exclusions and core-statistics oracles."""
from copy import deepcopy
import csv
import json
import numpy as np
import pytest

from hyperlab.analysis import export_roi_csv, roi_comparison, roi_statistics
from hyperlab.analysis.regions import make_roi, mask_geometry, resolve_roi, strip_profile
from hyperlab.io import Cube


def full_mask(shape, resolved):
    result = np.zeros(shape, dtype=bool)
    x0, y0, x1, y1 = resolved['bbox']
    result[y0:y1, x0:x1] = resolved['selected']
    return result


@pytest.mark.parametrize('bounds', [[0, 0, 4, 3], [.5, .5, 3.5, 2.5], [-3, -4, 2, 2]])
def test_polygon_rectangle_equivalence_and_half_open_centres(bounds):
    shape = (5, 7)
    x0, y0, x1, y1 = bounds
    rectangle = make_roi(shape, {'type': 'rectangle', 'bounds': bounds})
    vertices = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    yy, xx = np.indices(shape)
    expected = (xx+.5 >= x0) & (xx+.5 < x1) & (yy+.5 >= y0) & (yy+.5 < y1)
    for ring in (vertices, vertices[::-1]):
        polygon = make_roi(shape, {'type': 'polygon', 'vertices': ring})
        np.testing.assert_equal(full_mask(shape, resolve_roi(shape, polygon)), expected)
    np.testing.assert_equal(full_mask(shape, resolve_roi(shape, rectangle)), expected)


def test_triangle_hypotenuse_boundary_uses_declared_half_open_rule():
    shape = (5, 5)
    roi = make_roi(shape, {'type': 'polygon', 'vertices': [[0, 0], [4, 0], [0, 4]]})
    yy, xx = np.indices(shape)
    expected = (xx+.5 >= 0) & (yy+.5 >= 0) & (xx+yy+1 < 4)
    np.testing.assert_equal(full_mask(shape, resolve_roi(shape, roi)), expected)


def test_holes_exclusion_union_and_common_support_counts_match_raw_oracle(tmp_path):
    shape = (4, 5)
    raw = np.arange(60, dtype=float).reshape(*shape, 3) + 10
    raw[3, 0, 0] = -999
    raw[0, 4, 1] = 255
    validity = np.ones_like(raw, dtype=bool)
    validity[3, 4, 0] = False
    cube = Cube(raw, {'data_ignore_value': -999, 'effective_bits': 8}, validity)
    roi = make_roi(shape, {'type': 'polygon', 'vertices': [[0, 0], [5, 0], [5, 4], [0, 4]],
        'holes': [[[1, 1], [4, 1], [4, 3], [1, 3]]]}, name='With hole', role='reference')
    exclusions = [make_roi(shape, {'type': 'rectangle', 'bounds': bounds}, role='exclude')
                  for bounds in ([0, 0, 2, 2], [1, 0, 3, 1])]
    geometry = np.ones(shape, dtype=bool)
    geometry[1:3, 1:4] = False
    excluded = np.zeros(shape, dtype=bool)
    excluded[:2, :2] = True
    excluded[0, 1:3] = True
    excluded &= geometry
    good = validity & (raw != -999) & (raw < 255)
    common = geometry & ~excluded & good[..., :2].all(axis=2)
    before = raw.copy()
    resolved = resolve_roi(shape, roi, exclusions=exclusions)
    result = roi_statistics(cube, resolved, policy='quantitative', bands=[0, 1], support='common')
    assert resolved['geometry_count'] == 14 and resolved['excluded_count'] == 4
    assert result['common_count'] == 7
    np.testing.assert_equal(result['counts']['total'], [14, 14, 14])
    for band in (0, 1):
        values = raw[..., band][common]
        assert result['mean'][band] == pytest.approx(values.mean())
        assert result['std'][band] == pytest.approx(values.std(ddof=0))
        np.testing.assert_allclose([result[key][band] for key in ('q25', 'median', 'q75')], np.quantile(values, [.25, .5, .75]))
        assert result['mad'][band] == pytest.approx(np.median(abs(values - np.median(values))))
    assert np.isnan(result['mean'][2])
    np.testing.assert_equal(result['count'] + result['support_excluded_count'] + result['selection_excluded_count']
                            + result['geometry_excluded_count'], result['counts']['valid'])
    np.testing.assert_equal(raw, before)
    assert result['metadata']['roi_definition'] == roi
    assert result['metadata']['exclusion_definitions'] == exclusions
    path = export_roi_csv(result, tmp_path / 'roi.csv')
    rows = list(csv.DictReader(path.open()))
    assert [int(row['geometry_excluded_count']) for row in rows] == [4, 4, 4]
    sidecar = json.loads(path.with_suffix('.csv.json').read_text())
    assert sidecar['metadata']['roi_definition']['roi_id'] == roi['roi_id']


@pytest.mark.parametrize('support', ['common', 'per_band'])
def test_single_plane_distribution_uses_exact_same_polygon_and_exclusions(support):
    raw = np.arange(20, dtype=float).reshape(4, 5, 1)
    cube = Cube(raw, {'data_level': 'raw_frame'})
    roi = make_roi((4, 5), {'type': 'polygon', 'vertices': [[0, 0], [5, 0], [0, 4]]})
    exclude = make_roi((4, 5), {'type': 'rectangle', 'bounds': [0, 0, 1, 1]}, role='exclude')
    yy, xx = np.indices((4, 5))
    selected = ((xx+.5)/5 + (yy+.5)/4 < 1)
    selected[0, 0] = False
    expected = raw[..., 0][selected]
    stats = roi_comparison(cube, [roi], support=support, exclusions=[exclude])[0]
    assert stats['count'][0] == len(expected) == stats['distribution']['sample_count']
    assert stats['mean'][0] == pytest.approx(expected.mean())
    counts, _ = np.histogram(expected, bins=stats['distribution']['bin_edges'])
    np.testing.assert_equal(stats['distribution']['counts'], counts)
    assert np.sum(stats['distribution']['y'] * np.diff(stats['distribution']['bin_edges'])) == pytest.approx(1)


def test_empty_new_geometry_is_missing_not_zero_and_legacy_error_remains():
    cube = Cube(np.ones((3, 4, 1)), {'data_level': 'raw_frame'})
    roi = make_roi((3, 4), {'type': 'polygon', 'vertices': [[8, 8], [9, 8], [9, 9]]})
    result = roi_comparison(cube, [roi])[0]
    assert result['count'][0] == result['counts']['total'][0] == 0
    assert np.isnan(result['mean'][0]) and np.isnan(result['used_fraction'][0])
    assert result['distribution']['sample_count'] == 0
    with pytest.raises(ValueError, match='empty or outside'):
        roi_statistics(cube, (0, 0, 0, 1))


@pytest.mark.parametrize('extension,scale', [('.npy', 1), ('.png', 255)])
def test_external_binary_mask_identity_and_raw_shape_are_verified(tmp_path, extension, scale):
    mask = np.zeros((4, 6), dtype=np.uint8)
    mask[1, 3] = mask[3, 1] = scale
    path = tmp_path / ('binary' + extension)
    def save(values):
        if extension == '.npy':
            np.save(path, values)
        else:
            from PIL import Image
            Image.fromarray(values).save(path)
    save(mask)
    roi = make_roi(mask.shape, mask_geometry(path, mask.shape))
    np.testing.assert_equal(full_mask(mask.shape, resolve_roi(mask.shape, roi)), mask != 0)
    changed = mask.copy()
    changed[0, 0] = scale
    save(changed)
    with pytest.raises(ValueError, match='asset changed'):
        resolve_roi(mask.shape, roi)
    with pytest.raises(ValueError, match='raw HW shape'):
        mask_geometry(path, (6, 4))


def test_nongrey_mask_and_missing_asset_are_not_inferred(tmp_path):
    path = tmp_path / 'not_binary.npy'
    np.save(path, np.array([[0, 7], [1, 0]]))
    with pytest.raises(ValueError, match='only 0/1 or 0/255'):
        mask_geometry(path, (2, 2))
    with pytest.raises(FileNotFoundError):
        mask_geometry(tmp_path / 'missing.npy', (2, 2))


def test_strip_width_round_caps_direction_and_raw_cfa_samples():
    shape = (5, 7)
    for points in ([[.5, 2.5], [5.5, 2.5]], [[5.5, 2.5], [.5, 2.5]]):
        roi = make_roi(shape, {'type': 'strip', 'points': points, 'width_px': 2})
        expected = np.zeros(shape, dtype=bool)
        expected[1:4, :6] = True
        expected[2, 6] = True
        np.testing.assert_equal(full_mask(shape, resolve_roi(shape, roi)), expected)
    raw = np.arange(35, dtype=np.uint16).reshape(5, 7, 1)
    cube = Cube(raw, {'data_level': 'raw_frame', 'pixel_format': 'BayerRG12', 'sensor_roi_offset': [1, 1]})
    roi = make_roi(shape, {'type': 'rectangle', 'bounds': [1, 1, 4, 4]})
    result = roi_statistics(cube, roi)
    assert result['mean'][0] == pytest.approx(raw[1:4, 1:4, 0].mean())
    assert result['count'][0] == 9 and result['channel_labels'] is None


def test_id_revision_visibility_and_resolved_mask_checks():
    shape = (3, 4)
    cube = Cube(np.arange(12).reshape(*shape, 1))
    original = make_roi(shape, {'type': 'rectangle', 'bounds': [0, 0, 2, 2]}, role='reference')
    renamed = make_roi(shape, original['geometry'], name='Renamed', role='reference',
                       roi_id=original['roi_id'], revision=2, visible=False)
    assert resolve_roi(shape, renamed)['roi_id'] == original['roi_id']
    np.testing.assert_equal(roi_statistics(cube, original)['mean'], roi_statistics(cube, renamed)['mean'])
    disabled = make_roi(shape, original['geometry'], role='exclude', included=False)
    assert resolve_roi(shape, original, exclusions=[disabled])['excluded_count'] == 0
    resolved = resolve_roi(shape, original)
    with pytest.raises(ValueError, match='read-only'):
        resolved['selected'][0, 0] = False
    with pytest.raises(ValueError, match='original exclusions'):
        resolve_roi(shape, resolved, exclusions=[original])
    corrupt = dict(resolved, geometry_count=100)
    with pytest.raises(ValueError, match='counts'):
        resolve_roi(shape, corrupt)
    altered = deepcopy(original)
    altered['coordinate_frame']['shape_hw'] = [4, 3]
    with pytest.raises(ValueError, match='coordinate frame'):
        resolve_roi(shape, altered)


def test_strip_profile_exact_raw_cross_strip_bins_and_direction_reversal():
    shape = (3, 7)
    raw = np.arange(21, dtype=float).reshape(*shape, 1)
    cube = Cube(raw, {'data_level': 'raw_frame'})
    points = [[.5, 1.5], [5.5, 1.5]]
    roi = make_roi(shape, {'type': 'strip', 'points': points, 'width_px': 2})
    result = strip_profile(cube, roi)
    expected = [raw[:, i, 0] for i in range(4)] + [np.r_[raw[:, 4:6, 0].ravel(), raw[1, 6, 0]]]
    curve = result['curves'][0]
    np.testing.assert_equal(result['geometry_count'], [3, 3, 3, 3, 7])
    np.testing.assert_allclose(curve['mean'], [values.mean() for values in expected])
    np.testing.assert_allclose(curve['std'], [values.std(ddof=0) for values in expected])
    np.testing.assert_allclose(result['position_px'], np.arange(5)+.5)
    backwards = make_roi(shape, {'type': 'strip', 'points': points[::-1], 'width_px': 2})
    reverse = strip_profile(cube, backwards)
    for key in ('geometry_count', 'selected_count', 'excluded_count'):
        np.testing.assert_equal(reverse[key], result[key][::-1])
    for key in ('mean', 'std', 'count', 'geometry_excluded_count'):
        np.testing.assert_equal(reverse['curves'][0][key], curve[key][::-1])
    for key in curve['counts']:
        np.testing.assert_equal(reverse['curves'][0]['counts'][key], curve['counts'][key][::-1])
    assert reverse['metadata']['output_reversed'] is True
    assert result['metadata']['position_units'] == 'px'
    assert result['metadata']['roi_definition'] == roi
    np.testing.assert_equal(cube.data, raw)


def test_strip_profile_quality_exclusion_partitions_and_empty_bins():
    shape = (3, 7)
    raw = np.arange(21, dtype=float).reshape(*shape, 1)
    raw[0, 2, 0] = -999
    raw[2, 3, 0] = 255
    valid = np.ones(shape, dtype=bool)
    valid[0, 0] = False
    cube = Cube(raw, {'data_level': 'raw_frame', 'effective_bits': 8, 'data_ignore_value': -999}, valid)
    roi = make_roi(shape, {'type': 'strip', 'points': [[.5, 1.5], [5.5, 1.5]], 'width_px': 2})
    excluded = make_roi(shape, {'type': 'rectangle', 'bounds': [1, 0, 2, 3]}, role='exclude')
    result = strip_profile(cube, roi, exclusions=[excluded], policy='quantitative')
    curve = result['curves'][0]
    np.testing.assert_equal(curve['count'], [2, 0, 2, 2, 7])
    np.testing.assert_equal(curve['geometry_excluded_count'], [0, 3, 0, 0, 0])
    np.testing.assert_equal(curve['counts']['invalid'], [1, 0, 0, 0, 0])
    np.testing.assert_equal(curve['counts']['ignored'], [0, 0, 1, 0, 0])
    np.testing.assert_equal(curve['counts']['saturated'], [0, 0, 0, 1, 0])
    np.testing.assert_equal(curve['count'] + curve['geometry_excluded_count'], curve['counts']['valid'])
    assert np.isnan(curve['mean'][1]) and np.isnan(curve['std'][1])
    stats = roi_statistics(cube, roi, exclusions=[excluded], policy='quantitative')
    assert curve['count'].sum() == stats['count'][0]
    assert np.nansum(curve['mean']*curve['count']) / curve['count'].sum() == pytest.approx(stats['mean'][0])
    outside = make_roi(shape, {'type': 'strip', 'points': [[20, 20], [24, 20]], 'width_px': 1})
    empty = strip_profile(cube, outside)['curves'][0]
    assert empty['count'].sum() == 0 and np.isnan(empty['mean']).all() and np.isnan(empty['std']).all()


def test_strip_profile_polyline_projection_labels_features_and_stable_spatial_sd():
    raw = np.arange(27, dtype=float).reshape(3, 3, 3) + 1e12
    cube = Cube(raw, {'data_level': 'raw_frame', 'channel_labels': ['Blue', 'Green', 'Red'],
                     'band_validity': [True, False, True]})
    roi = make_roi((3, 3), {'type': 'strip', 'points': [[.5, .5], [.5, 2.5], [2.5, 2.5]], 'width_px': .2})
    result = strip_profile(cube, roi, bands=[2, 1, 0])
    np.testing.assert_equal(result['geometry_count'], [1, 1, 1, 2])
    assert [curve['label'] for curve in result['curves']] == ['Red', 'Blue']
    assert result['metadata']['feature_indices'] == [2, 0]
    for curve in result['curves']:
        band = curve['feature_index']
        expected = [raw[0, 0, band], raw[1, 0, band], raw[2, 0, band], raw[2, 1:3, band].mean()]
        np.testing.assert_equal(curve['mean'], expected)
        np.testing.assert_equal(curve['std'], [0, 0, 0, 1.5])
    with pytest.raises(ValueError, match='Booleans'):
        strip_profile(cube, roi, bands=[True])
    with pytest.raises(ValueError, match='positive'):
        strip_profile(cube, roi, bin_width_px=0)
    with pytest.raises(ValueError, match='100000 bins'):
        strip_profile(cube, roi, bin_width_px=1e-9)
    with pytest.raises(ValueError, match='strip ROI'):
        strip_profile(cube, (0, 0, 2, 2))
