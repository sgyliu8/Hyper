import numpy as np
import pytest

from hyperlab.analysis.maps import normalized_difference, reference_rmse
from hyperlab.io import Cube
from hyperlab.plots import map_plot


def test_rgb_contrast_uses_signed_float_and_joint_support():
    cube = Cube(np.array([[[250, 10, 8], [10, 250, 8], [0, 0, 8]]], np.uint8),
                {'data_level': 'raw_frame', 'units': 'DN', 'channel_labels': ['R', 'G', 'B']})
    result = normalized_difference(cube, 0, 1)
    np.testing.assert_allclose(result['data'][0, :2], [240 / 260, -240 / 260])
    assert not result['valid_mask'][0, 2]
    spec = map_plot(result, {'channel_labels': ['R', 'G', 'B']})
    assert spec.colormap == 'RdBu_r' and spec.limits[0] == -spec.limits[1]
    assert 'R' in spec.title and 'G' in spec.title
    with pytest.raises(ValueError):
        normalized_difference(cube, 0, 1, minimum_denominator=0)


def test_reference_rmse_fixed_features_and_masks():
    values = np.array([[[1., 2., 100.], [4., 6., np.nan], [np.nan, 5., 9.]]])
    cube = Cube(values, {'data_level': 'raw_scan', 'units': 'DN'})
    result = reference_rmse(cube, [1., 2., np.nan], bands=[0, 1])
    np.testing.assert_allclose(result['data'][0, :2], [0., np.sqrt(12.5)])
    assert not result['valid_mask'][0, 2]
    assert result['metadata']['feature_indices'] == [0, 1]
    np.testing.assert_equal(values, cube.data)
    with pytest.raises(ValueError, match='finite'):
        reference_rmse(cube, [1., 2., np.nan])


def test_one_plane_reference_is_absolute_intensity_contrast():
    cube = Cube(np.array([[[2], [8]]], np.uint16), {'data_level': 'raw_frame', 'units': 'DN'})
    np.testing.assert_equal(reference_rmse(cube, [5])['data'], [[3, 3]])


def test_subset_reference_export_keeps_excluded_features_null(tmp_path):
    import json
    from hyperlab.analysis import export_product
    cube = Cube(np.array([[[1., 2., 8.], [4., 6., 3.]]]), {'data_level':'raw_scan','units':'DN'})
    result = reference_rmse(cube, [1., 2., np.nan], bands=[0, 1])
    export_product(result, tmp_path/'subset.npy', source_cube=cube)
    assert result['metadata']['reference'] == [1., 2., None]
    json.loads((tmp_path/'subset.npy.json').read_text())
