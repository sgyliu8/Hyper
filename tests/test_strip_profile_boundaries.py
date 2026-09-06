"""Independent bin-edge oracles, including adjacent representable coordinates."""
from fractions import Fraction

import numpy as np
import pytest

from hyperlab.analysis.regions import make_roi, resolve_roi, strip_profile
from hyperlab.io import Cube


@pytest.mark.parametrize('vertical', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_long_axis_strip_uses_integer_half_open_bins_without_changing_membership(vertical, reverse):
    # Geometry from the real saved-frame failure; samples below are an offline
    # coordinate ramp. The capsule and bin oracles use direct integer distances.
    shape = (1300, 900) if vertical else (900, 1300)
    raw = np.broadcast_to(np.arange(1300.)[:, None] if vertical else np.arange(1300.)[None, :], shape)
    cube = Cube(raw[..., None], {'data_level':'raw_frame', 'units':'DN'})
    points = [[430.5,740.5],[1250.5,740.5]]
    excluded_bounds = [380,525,710,820]
    if vertical:
        points = [point[::-1] for point in points]
        excluded_bounds = [525,380,820,710]
    roi = make_roi(shape, {'type':'strip','points':points[::-1] if reverse else points,'width_px':21})
    exclusion = make_roi(shape, {'type':'rectangle','bounds':excluded_bounds}, role='exclude')
    before = resolve_roi(shape, roi, exclusions=[exclusion])
    result = strip_profile(cube, roi, policy='quantitative', exclusions=[exclusion], bin_width_px=10)
    after = resolve_roi(shape, roi, exclusions=[exclusion])
    for key in ('membership', 'selected', 'excluded'):
        np.testing.assert_equal(after[key], before[key])

    cross, along = np.mgrid[728:754,418:1264]
    distance = np.clip(along-430, 0, 820)
    member = (along-430-distance)**2+(cross-740)**2 <= 10.5**2
    excluded = member & (along >= 380) & (along < 710) & (cross >= 525) & (cross < 820)
    selected = member & ~excluded
    index = np.minimum(distance//10, 81)
    expected_counts = lambda mask: np.bincount(index[mask], minlength=82)
    orientation = slice(None, None, -1) if reverse else slice(None)
    for field, mask in (('geometry_count', member), ('excluded_count', excluded), ('selected_count', selected)):
        np.testing.assert_equal(result[field], expected_counts(mask)[orientation])
    assert result['geometry_count'].sum() == before['geometry_count'] == 17569
    np.testing.assert_equal(expected_counts(member)[1:-1], np.full(80, 210))
    curve = result['curves'][0]
    np.testing.assert_equal(curve['count'], expected_counts(selected)[orientation])
    np.testing.assert_equal(curve['count']+curve['geometry_excluded_count'], curve['counts']['valid'])
    expected_mean, expected_sd = [], []
    for k in range(82):
        values = along[selected & (index == k)].astype(float)
        expected_mean.append(values.mean() if values.size else np.nan)
        expected_sd.append(values.std(ddof=0) if values.size else np.nan)
    np.testing.assert_allclose(curve['mean'], np.asarray(expected_mean)[orientation], equal_nan=True)
    np.testing.assert_allclose(curve['std'], np.asarray(expected_sd)[orientation], equal_nan=True)


@pytest.mark.parametrize('delta,step,requested_width', [((820,820),(1,1),14.15), ((492,656),(3,4),10.)])
@pytest.mark.parametrize('reverse', [False, True])
def test_diagonal_bins_cancel_length_roots_and_reverse_exactly(delta, step, requested_width, reverse):
    shape = (delta[1]+2,delta[0]+2)
    cube = Cube(np.ones((*shape,1)), {'data_level':'raw_frame','units':'DN'})
    points = [[.5,.5],[delta[0]+.5,delta[1]+.5]]
    roi = make_roi(shape, {'type':'strip','points':points[::-1] if reverse else points,'width_px':.1})
    result = strip_profile(cube, roi, bin_width_px=requested_width)
    n_steps = delta[0]//step[0]
    # Integer lattice locations along this narrow strip; no projection/norm in
    # the oracle. Equal distance bins have the same fractions of total steps.
    expected = np.bincount(np.minimum(np.arange(n_steps+1)*82//n_steps,81), minlength=82)
    assert len(result['geometry_count']) == 82
    np.testing.assert_equal(result['geometry_count'], expected[::-1] if reverse else expected)
    np.testing.assert_equal(result['curves'][0]['count'], result['geometry_count'])
    assert result['geometry_count'].sum() == n_steps+1


@pytest.mark.parametrize('start', [np.nextafter(.5,-np.inf), .5, np.nextafter(.5,np.inf)])
@pytest.mark.parametrize('diagonal', [False, True])
def test_representable_points_on_opposite_sides_are_not_snapped_to_the_boundary(start, diagonal):
    shape = (822,822) if diagonal else (1,822)
    mask = np.zeros(shape, bool)
    mask[30 if diagonal else 0,30] = True
    cube = Cube(np.ones((*shape,1)), {'data_level':'raw_frame','units':'DN'}, mask)
    points = [[start,start if diagonal else .5],[820.5,820.5 if diagonal else .5]]
    roi = make_roi(shape, {'type':'strip','points':points,'width_px':.1})
    result = strip_profile(cube, roi, bin_width_px=14.15 if diagonal else 10.)
    # Compare exact supplied coordinates against the affine 3/82 edge. A
    # blanket one-ULP snap loses the below-edge case even though it is distinct.
    start_exact = Fraction(float(start))
    edge_x = start_exact+(Fraction(820.5)-start_exact)*Fraction(3,82)
    expected_bin = 2 if Fraction(30.5) < edge_x else 3
    assert np.flatnonzero(result['curves'][0]['count']).tolist() == [expected_bin]
    assert result['curves'][0]['count'][expected_bin] == 1


def test_multisegment_profile_keeps_explicit_floating_distance_policy():
    cube = Cube(np.ones((3,3,1)), {'data_level':'raw_frame','units':'DN'})
    roi = make_roi((3,3), {'type':'strip','points':[[.5,.5],[.5,2.5],[2.5,2.5]],'width_px':.1})
    result = strip_profile(cube, roi)
    np.testing.assert_equal(result['geometry_count'], [1,1,1,2])
    assert 'float64' in result['metadata']['bin_boundary_arithmetic']
    assert 'no snapping' in result['metadata']['bin_boundary_arithmetic']
