"""Colour transforms preserve operation centers and raw-coordinate semantics."""
from copy import deepcopy

import numpy as np
import pytest

from hyperlab.io import Cube
from hyperlab.plots import map_display_limits, map_limit_key, map_plot, render_figure
from hyperlab.ui.workbench import Workbench


def product(values, operation='normalized_difference'):
    data = np.asarray(values, float).reshape(2, 2)
    return {'data':data, 'valid_mask':np.isfinite(data),
            'metadata':{'operation':operation, 'indices':[0,1], 'units':'DN'}}


@pytest.mark.parametrize('values', [[-.9,-.6,-.4,-.1],[1,2,3,7],[-3,-1,2,7],[0,0,0,0],
                                  [3,3,3,3],[np.nan]*4])
@pytest.mark.parametrize('operation,center', [('normalized_difference',0.),('difference',0.),('ratio',1.)])
@pytest.mark.parametrize('robust', [False,True])
def test_every_center_and_sign_survives_full_and_robust(values, operation, center, robust):
    result = product(values, operation)
    original = result['data'].copy()
    spec = map_plot(result, {'data_source':'SYNTHETIC','units':'DN'})
    map_display_limits(spec, robust=robust)
    low, high = spec.limits
    assert np.isfinite(spec.limits).all() and low < high
    assert (center-low)/(high-low) == pytest.approx(.5)
    valid = spec.image[spec.valid_mask]
    coordinate = (valid-low)/(high-low)
    assert np.all(coordinate[valid < center] < .5)
    assert np.all(coordinate[valid > center] > .5)
    np.testing.assert_equal(result['data'], original)
    np.testing.assert_equal(spec.image, original)
    np.testing.assert_equal(spec.valid_mask, np.isfinite(original))
    record = spec.metadata['display_limits']
    assert record['valid_count'] == np.isfinite(original).sum()
    assert record['clipped_count'] == np.count_nonzero((valid < low) | (valid > high))
    assert record['normalization'] == 'linear' and record['semantic_center'] == center


@pytest.mark.parametrize('operation,values,center', [
    ('normalized_difference',[-.9,-.6,-.4,-.1],0.),
    ('difference',[1.,2.,3.,7.],0.),('ratio',[2.,3.,4.,8.],1.)])
def test_actual_qt_export_and_locked_scale_match(qtbot, operation, values, center):
    window = Workbench(); qtbot.addWidget(window)
    source = Cube(np.ones((3,4,3)), {'data_level':'raw_frame','units':'DN',
                  'channel_labels':['R','G','B'],'data_source':'SYNTHETIC'})
    window.set_cube(source); window.roi_timer.stop()
    window.prepare_map_panels = lambda: None
    window.robust_map_limits.setChecked(True)
    result = product(values, operation)
    window.show_product(result, source)
    spec = window.map_spec
    limits = spec.limits
    figure = render_figure(spec, width_mm=80, height_mm=70, dpi=72)
    image = figure.axes[0].images[0]
    assert image.norm(center) == pytest.approx(.5)
    np.testing.assert_equal(window.derived_image.levels, limits)
    window.derived_image.render()
    actual = np.asarray([[window.derived_image.qimage.pixelColor(x,y).getRgb() for x in range(2)] for y in range(2)])
    expected = (image.cmap(image.norm(result['data']))*255).astype(int)
    np.testing.assert_allclose(actual, expected, atol=1)
    assert tuple(image.get_extent()) == (0,2,2,0)
    assert window.derived_image.boundingRect().getRect() == (0.,0.,2.,2.)
    assert spec.metadata['coordinate_frame']['array_indices'] == 'integer (y, x)'
    figure.clear()
    window.show_product(product([value*5 for value in values], operation), source)
    assert window.map_spec.limits == limits
    assert window.map_spec.metadata['display_limits']['shared_limits'] is True
    assert window.map_spec.metadata['display_limits']['clipped_count'] > 0
    np.testing.assert_equal(window.map_spec.image, np.asarray(values).reshape(2,2)*5)


def test_shared_key_distinguishes_units_direction_and_stored_support():
    source = {'units':'DN','data_level':'raw_frame','feature_labels':['R','G','B']}
    baseline = map_plot(product([1,2,3,4]), source)
    key = map_limit_key(baseline, True)
    for patch in ({'units':'relative intensity'}, {'feature_labels':['B','G','R']}, {'data_level':'raw_scan'}):
        changed = map_plot(product([1,2,3,4]), dict(source, **patch))
        assert map_limit_key(changed, True) != key
    changed = deepcopy(baseline); changed.metadata['indices'] = [1,0]
    assert map_limit_key(changed, True) != key
    assert map_limit_key(baseline, False) != key
    with pytest.raises(ValueError, match='center'):
        map_display_limits(baseline, locked_limits=(-1,2))


@pytest.mark.parametrize('robust', [False,True])
def test_sequential_magnitude_never_uses_negative_domain(robust):
    for values in ([1,2,3,4],[0,0,0,0],[np.nan]*4):
        spec = map_plot(product(values, 'reference_rmse'), {'units':'DN'})
        map_display_limits(spec, robust=robust)
        assert spec.limits[0] == 0 and spec.limits[1] > 0
        assert spec.metadata['semantic_center'] is None
