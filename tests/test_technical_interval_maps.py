"""Actual-coordinate interval maps, independent physical and denominator oracles."""
from copy import deepcopy

import numpy as np
import pytest

from hyperlab.analysis.distributions import map_roi_distributions, spectral_interval_map
from hyperlab.io import Cube


def cube(values, waves=(500., 503., 510.), *, units='nm', **metadata):
    return Cube(np.asarray(values), {'data_level': 'spectral_cube', 'units': 'DN',
        'wavelengths': list(waves), 'wavelength_units': units,
        'wavelength_source': 'SYNTHETIC analytic test fixture', 'data_source': 'SYNTHETIC', **metadata})


def test_irregular_axis_interval_mean_is_not_arithmetic_band_average_and_uses_every_row():
    scale = np.arange(1., 259.).reshape(129, 2, 1)
    source = cube(scale*np.array([0., 3., 10.]))
    before, metadata = source.data.copy(), deepcopy(source.metadata)
    integral = spectral_interval_map(source)
    mean = spectral_interval_map(source, statistic='mean')
    np.testing.assert_allclose(integral['data'], scale[..., 0]*50.)
    np.testing.assert_allclose(mean['data'], scale[..., 0]*5.)
    assert mean['data'][0, 0] != pytest.approx(source.data[0, 0].mean())
    assert integral['metadata']['units'] == 'DN*nm' and mean['metadata']['units'] == 'DN'
    assert integral['metadata']['interval_span_nm'] == 10
    assert integral['metadata']['reason_counts']['used'] == 258
    assert integral['metadata']['aggregation_order'] == 'pixel_transform_then_summary'
    result = map_roi_distributions(mean, [(0, 0, 2, 129)])
    assert result['regions'][0]['statistics']['mean'] == pytest.approx(647.5)
    np.testing.assert_equal(source.data, before)
    assert source.metadata == metadata


def test_descending_um_interval_preserves_original_indices_bandpass_and_units():
    source = cube(np.array([[[10., 3., 0.]]]), waves=[.510, .503, .500], units='um',
                  fwhm=[.004, .003, .002], response_evidence={'origin': 'analytic fixture'})
    result = spectral_interval_map(source)
    assert result['data'][0, 0] == pytest.approx(50.)
    metadata = result['metadata']
    assert metadata['feature_indices'] == [2, 1, 0]
    assert metadata['interval_support']['band_indices'] == [2, 1, 0]
    assert metadata['wavelengths_nm'] == [500., 503., 510.]
    assert metadata['bandpass_evidence']['fwhm_nm'] == [2., 3., 4.]
    assert metadata['bandpass_evidence']['response_evidence'] == {'origin': 'analytic fixture'}


def test_complete_pixel_support_separates_source_reasons_and_saturation_policy():
    values = np.full((3, 3, 3), 10.)
    values[0, 1, 1], values[0, 2, 0], values[1, 0, 2] = np.nan, -99., 255.
    source = cube(values, data_ignore_value=-99., saturation_value=255.)
    source.valid_mask = np.ones(values.shape, bool)
    source.valid_mask[1, 1, 1] = False
    diagnostic, quantitative = spectral_interval_map(source), spectral_interval_map(source, policy='quantitative')
    assert diagnostic['valid_mask'].sum() == 6 and quantitative['valid_mask'].sum() == 5
    for product, excluded in ((diagnostic, 3), (quantitative, 4)):
        counts = product['metadata']['reason_counts']
        assert counts['source_invalid'] == 2 and counts['source_ignored'] == 1 and counts['source_saturated'] == 1
        assert counts['source_excluded'] == excluded
        assert counts['total'] == sum(counts[key] for key in
            ('source_excluded', 'physical_gap_unsupported', 'nonfinite_calculation', 'used'))
        assert np.isnan(product['data'][~product['valid_mask']]).all()
    assert diagnostic['valid_mask'][1, 0] and not quantitative['valid_mask'][1, 0]


def test_declared_physical_gap_cannot_be_erased_and_bounded_interval_remains_available():
    source = cube(np.ones((2, 3, 3)), measurement_gaps_nm=[[503., 507.]])
    unavailable = spectral_interval_map(source, measurement_gaps_nm=[])
    assert unavailable['metadata']['interval_support']['allowed'] is False
    assert unavailable['metadata']['reason_counts']['physical_gap_unsupported'] == 6
    assert not unavailable['valid_mask'].any()
    supported = spectral_interval_map(source, bands=[0, 1])
    np.testing.assert_equal(supported['data'], np.full((2, 3), 3.))
    assert supported['metadata']['measurement_gaps_nm'] == [[503., 507.]]


@pytest.mark.parametrize('units,waves', [('nm', [500.1, 500.2, 500.3]), ('um', [.5001, .5002, .5003])])
def test_explicit_gap_limit_uses_existing_coordinate_roundoff_contract(units, waves):
    source = cube(np.ones((1, 1, 3)), waves=waves, units=units)
    assert spectral_interval_map(source, max_gap_nm=.1)['valid_mask'][0, 0]
    assert not spectral_interval_map(source, max_gap_nm=.099)['valid_mask'][0, 0]


def test_finite_interval_mean_survives_unrepresentable_integral():
    source = cube(np.full((1, 1, 3), 1e308))
    assert spectral_interval_map(source, statistic='mean')['data'][0, 0] == pytest.approx(1e308)
    integral = spectral_interval_map(source)
    assert not integral['valid_mask'][0, 0]
    assert integral['metadata']['reason_counts']['nonfinite_calculation'] == 1


@pytest.mark.parametrize('options', [{'bands': [0, 2]}, {'bands': [True, 1]}, {'bands': [0]},
    {'bands': [0, 0]}, {'bands': [3]}, {'statistic': 'arithmetic'}, {'policy': 'unknown'}])
def test_invalid_interval_recipe_is_rejected(options):
    with pytest.raises(ValueError):
        spectral_interval_map(cube(np.ones((1, 1, 3))), **options)


def test_disabled_band_and_unphysical_axis_are_not_interpolated():
    source = cube(np.ones((1, 1, 3)), band_validity=[True, False, True])
    with pytest.raises(ValueError, match='globally invalid'):
        spectral_interval_map(source)
    for source in (Cube(np.ones((1, 1, 3)), {'data_level': 'raw_frame', 'channel_labels': ['R', 'G', 'B']}),
                   cube(np.ones((1, 1, 3)), waves=[500, 510, 503]),
                   cube(np.ones((1, 1, 3)), units='unknown')):
        with pytest.raises(ValueError, match='wavelength'):
            spectral_interval_map(source)


@pytest.mark.parametrize('flag', [{'preview_only': True}, {'sampled': True}, {'sampling': 'stride 4'}])
def test_interval_map_rejects_interactive_preview_sampling(flag):
    with pytest.raises(ValueError, match='sampled'):
        spectral_interval_map(cube(np.ones((1, 1, 3)), **flag))
