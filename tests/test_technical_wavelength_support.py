"""Physical support is explicit; true-coordinate polynomial mathematics stays intact."""
from copy import deepcopy
import json

import numpy as np
import pytest

from hyperlab.analysis import roi_statistics
from hyperlab.analysis.roi_features import local_polynomial, spectral_roi_features
from hyperlab.io import Cube
from hyperlab.plots import COLORS, export_figure_bundle, roi_feature_plot, source_identity


def spectrum(waves, *, units='nm', reverse=False, level='spectral_cube', **metadata):
    waves = np.asarray(waves, np.float64)
    nm = waves*(1000 if units == 'um' else 1)
    values = .002*nm+.3
    if reverse:
        waves, values = waves[::-1], values[::-1]
    return Cube(values[None, None, :], {'data_level': level, 'units': 'DN' if level == 'spectral_cube' else 'dimensionless',
        'wavelengths': waves.tolist(), 'wavelength_units': units,
        'wavelength_source': 'SYNTHETIC analytic fixture', 'data_source': 'SYNTHETIC', **metadata})


def feature(cube, operation='derivative1', **kwargs):
    result = roi_statistics(cube, (0, 0, 1, 1), support='common')
    return spectral_roi_features(cube, [result], operation, **kwargs)


def test_large_allowed_spacing_reports_actual_five_band_window():
    cube = spectrum([500, 501, 502, 503, 504, 900, 901, 902, 903], fwhm=[2.]*9)
    result = feature(cube)
    np.testing.assert_allclose(result['curves'][0]['y'][2:-2], .002, rtol=1e-10)
    support = result['metadata']['window_support'][4]
    assert support['band_indices'] == [2, 3, 4, 5, 6]
    assert support['center_band_index'] == 4
    assert support['span_nm'] == 399 and support['max_adjacent_delta_nm'] == 396
    assert support['complete'] and support['allowed']
    assert support['fwhm_nm'] == [2.]*5
    assert result['metadata']['max_gap_nm'] is None
    assert result['metadata']['bandpass_evidence']['response_evidence'] is None


def test_max_gap_invalidates_only_crossing_windows_not_raw_samples():
    cube = spectrum([500, 501, 502, 503, 504, 900, 901, 902, 903])
    before = cube.data.copy()
    result = feature(cube, max_gap_nm=10)
    np.testing.assert_array_equal(result['curves'][0]['valid_mask'], [False, False, True, False, False, False, False, False, False])
    assert 'max_gap_nm' in result['curves'][0]['invalid_reasons'][4]
    assert not result['metadata']['window_support'][4]['allowed']
    np.testing.assert_array_equal(cube.data, before)


@pytest.mark.parametrize('reverse', [False, True])
def test_nm_um_and_reversed_original_band_mapping(reverse):
    nm = np.array([500, 501, 502, 503, 504, 900, 901, 902, 903], np.float64)
    cube_nm = spectrum(nm, reverse=reverse, fwhm=[2.]*9)
    cube_um = spectrum(nm/1000, units='um', reverse=reverse, fwhm=[.002]*9)
    first, second = feature(cube_nm, max_gap_nm=10), feature(cube_um, max_gap_nm=10)
    np.testing.assert_allclose(first['curves'][0]['y'], second['curves'][0]['y'], equal_nan=True)
    support = first['metadata']['window_support'][2]
    assert support['band_indices'] == ([8, 7, 6, 5, 4] if reverse else [0, 1, 2, 3, 4])
    assert support['center_band_index'] == (6 if reverse else 2)
    assert second['metadata']['window_support'][2]['fwhm_nm'] == [2.]*5
    assert first['metadata']['window_support'][0]['complete'] is False


@pytest.mark.parametrize('operation,level', [('integral', 'spectral_cube'), ('continuum', 'reflectance_cube')])
def test_declared_gap_prevents_interval_bridging(operation, level):
    cube = spectrum([500, 501, 502, 800, 801, 802, 803], level=level,
                    measurement_gaps_nm=[[503, 799]])
    result = feature(cube, operation)
    assert result['curves'][0]['features']['status'] == 'unavailable'
    assert 'measurement gap' in result['curves'][0]['features']['reason']
    assert not result['metadata']['interval_support']['allowed']
    assert not result['curves'][0]['valid_mask'].any()
    # A caller cannot erase a source-declared gap with an empty additional list.
    assert feature(cube, operation, measurement_gaps_nm=[])['curves'][0]['features']['status'] == 'unavailable'


def test_declared_gap_boundaries_and_no_default_gap_policy():
    cube = spectrum([500, 501, 502, 503, 504], measurement_gaps_nm=[[504, 510]])
    result = feature(cube)
    assert result['curves'][0]['valid_mask'][2]  # A gap starting at the last sampled endpoint is not crossed.
    result = feature(cube, measurement_gaps_nm=[[502, 503]])
    assert not result['curves'][0]['valid_mask'][2]
    assert result['metadata']['measurement_gaps_nm'] == [[502., 503.], [504., 510.]]


def test_unknown_and_explicit_bandwidth_units_remain_distinct():
    unknown = feature(spectrum([500, 501, 502, 503, 504]))
    assert unknown['metadata']['bandpass_evidence']['fwhm_nm'] is None
    assert unknown['metadata']['window_support'][2]['fwhm_nm'] is None
    explicit = feature(spectrum([500, 501, 502, 503, 504], fwhm=[.002]*5, fwhm_units='um',
                                response_evidence={'source': 'synthetic response declaration'}))
    assert explicit['metadata']['window_support'][2]['fwhm_nm'] == [2.]*5
    bad_units = feature(spectrum([500, 501, 502, 503, 504], fwhm=[2.]*5, fwhm_units='unknown'))
    assert bad_units['metadata']['bandpass_evidence']['fwhm_original'] == [2.]*5
    assert bad_units['metadata']['bandpass_evidence']['fwhm_nm'] is None


@pytest.mark.parametrize('options', [{'max_gap_nm': 0}, {'max_gap_nm': float('nan')},
    {'measurement_gaps_nm': [[500, 500]]}, {'measurement_gaps_nm': [[600, 500]]},
    {'measurement_gaps_nm': [[500, float('inf')]]}])
def test_invalid_explicit_constraints_rejected(options):
    with pytest.raises(ValueError, match='gap'):
        local_polynomial([500, 501, 502, 503, 504], [1, 2, 3, 4, 5], **options)


def test_window_support_survives_completed_plot_export_without_ribbon(tmp_path):
    cube = spectrum([500, 501, 502, 503, 504], fwhm=[2.]*5)
    before = deepcopy(cube.metadata)
    result = feature(cube, max_gap_nm=2)
    spec = roi_feature_plot(result, ['Region'], COLORS, source=source_identity(cube))
    export_figure_bundle(spec, tmp_path/'support')
    saved = json.loads((tmp_path/'support'/'plot.json').read_text())
    assert saved['metadata']['window_support'][2]['span_nm'] == 4
    assert saved['metadata']['aggregation_order'] == 'summary_then_transform'
    assert all('sd' not in item and 'lower' not in item and 'upper' not in item for item in saved['series'])
    assert cube.metadata == before


def test_bandwidth_records_follow_original_reversed_indices():
    cube = spectrum([500, 501, 502, 503, 504, 900, 901, 902, 903], reverse=True,
                    fwhm=list(range(1, 10)), measurement_context={'response_calibration_id': 'synthetic-response-id'})
    result = feature(cube)
    assert result['metadata']['window_support'][2]['band_indices'] == [8, 7, 6, 5, 4]
    assert result['metadata']['window_support'][2]['fwhm_nm'] == [9., 8., 7., 6., 5.]
    assert result['metadata']['bandpass_evidence']['response_calibration_id'] == 'synthetic-response-id'


def test_decimal_spacing_at_explicit_limit_is_unit_invariant():
    nm = np.array([500.1, 500.2, 500.3, 500.4, 500.5])
    for units, wave in (('nm', nm), ('um', nm/1000)):
        result = feature(spectrum(wave, units=units), max_gap_nm=.1)
        assert result['curves'][0]['valid_mask'][2]
        assert result['curves'][0]['y'][2] == pytest.approx(.002, abs=1e-10)
        assert not feature(spectrum(wave, units=units), max_gap_nm=.099)['curves'][0]['valid_mask'][2]
