import json

import numpy as np
import pytest

from hyperlab.io import Cube, save_cube, load_cube
from hyperlab.analysis import normalized_difference, roi_statistics
from hyperlab.analysis.distributions import brush_map, map_roi_distributions
from hyperlab.analysis.regions import make_roi
from hyperlab.experiment_metadata import source_fingerprint
from hyperlab.plots import map_plot, roi_plot, map_distribution_plot, source_identity, COLORS, plain, render_figure
from hyperlab.sharing import sanitized_plot, export_share_bundle


PRIVATE = 'PRIVATE_BOUNDARY_SENTINEL'


def cube():
    return Cube(np.arange(60, dtype=np.uint16).reshape(4, 5, 3)+10,
        {'data_level': 'raw_frame', 'channel_labels': ['R','G','B'], 'units': 'DN',
         'synthetic': True, 'source_file': 'C:/Private/'+PRIVATE+'/frame.npy',
         'session_id': PRIVATE, 'pixel_format': 'RGB8', 'effective_bits': 8})


def test_shared_map_preserves_formula_threshold_counts_geometry_and_colors(tmp_path):
    source = cube()
    product = normalized_difference(source, 0, 1, low_signal_threshold=50, low_signal_source=PRIVATE)
    roi = make_roi(source.shape[:2], {'type':'rectangle','bounds':[0,0,5,4]}, name=PRIVATE)
    spec = map_plot(product, source_identity(source))
    spec.title = PRIVATE
    spec.brushes = [brush_map(product, roi, [-1,1])]
    before = json.dumps(spec.record(), sort_keys=True)
    safe = sanitized_plot(spec)
    assert PRIVATE not in json.dumps(safe.record())
    assert safe.metadata['equation'] == product['metadata']['equation']
    assert safe.metadata['denominator_rule'] == product['metadata']['denominator_rule']
    assert safe.metadata['minimum_denominator'] == product['metadata']['minimum_denominator']
    assert safe.metadata['low_signal_assessment']['threshold'] == 50
    assert safe.metadata['low_signal_assessment']['status'] == 'DIAGNOSTIC_THRESHOLD'
    assert safe.metadata['reason_counts'] == product['metadata']['reason_counts']
    assert safe.metadata['count_semantics'] == product['metadata']['count_semantics']
    np.testing.assert_array_equal(safe.image, spec.image)
    np.testing.assert_array_equal(safe.valid_mask, spec.valid_mask)
    np.testing.assert_array_equal(safe.brushes[0]['mask'], spec.brushes[0]['mask'])
    np.testing.assert_array_equal(safe.brushes[0]['coordinates_yx'], spec.brushes[0]['coordinates_yx'])
    assert safe.limits == spec.limits and safe.colormap == spec.colormap
    assert safe.metadata['display_limits']['clipped_count'] == spec.metadata['display_limits']['clipped_count']
    assert safe.metadata['coordinate_frame'] == spec.metadata['coordinate_frame']
    assert json.dumps(spec.record(), sort_keys=True) == before
    directory = export_share_bundle(spec, tmp_path/'copy', dpi=72)
    for path in directory.iterdir():
        if path.suffix in {'.json','.csv','.svg'}:
            assert PRIVATE not in path.read_text(encoding='utf-8')
    assert json.loads((directory/'share_manifest.json').read_text())['transmitted'] is False
    np.testing.assert_array_equal(np.load(directory/'values.npy'), spec.image)


@pytest.mark.parametrize('mode', ['roi', 'ecdf', 'histogram'])
def test_shared_curves_keep_every_value_and_statistic(mode, tmp_path):
    source = cube()
    roi = make_roi(source.shape[:2], {'type':'rectangle','bounds':[0,0,5,4]}, name=PRIVATE)
    if mode == 'roi':
        spec = roi_plot([roi_statistics(source, roi, support='common')], [PRIVATE], COLORS,
            source=source_identity(source), summary='median')
    else:
        result = map_roi_distributions(normalized_difference(source, 0, 1), [roi])
        spec = map_distribution_plot(result, source=source_identity(source), mode=mode)
    safe = sanitized_plot(spec)
    assert len(safe.series) == len(spec.series)
    assert PRIVATE not in json.dumps(safe.record())
    for old, new in zip(spec.series, safe.series):
        for key in ('x','y','lower','upper','sd','used_counts','feature_indices'):
            if key in old:
                np.testing.assert_array_equal(new[key], old[key])
    if mode == 'roi':
        assert safe.categories == ['R','G','B'] and safe.metadata['summary'] == 'median'
    else:
        assert plain(safe.series[0]['ecdf']) == plain(spec.series[0]['ecdf'])
    export_share_bundle(spec, tmp_path/mode, dpi=72)


def test_shared_definition_keeps_common_population_and_unknown_removed_identity():
    spec = roi_plot([roi_statistics(cube(), (0,0,5,4), support='common')], [PRIVATE], COLORS,
        source=source_identity(cube()))
    spec.metadata['definition'] = {'support':'common', 'support_features': [
        {'feature_index':0, 'label':'R', 'coordinate':None, 'coordinate_units':None},
        {'feature_index':1, 'label':'G', 'coordinate':None, 'coordinate_units':None}],
        'quality': {'policy':'quantitative', 'saturation_value':255, 'saturation_units':'DN'},
        'applied_context': {'response_id': PRIVATE}, 'units':'DN'}
    spec.metadata['comparison_evidence'] = {'status':'MATCH'}
    spec.metadata[PRIVATE] = PRIVATE
    safe = sanitized_plot(spec)
    assert safe.metadata['definition']['support_features'] == spec.metadata['definition']['support_features']
    assert safe.metadata['definition']['quality'] == spec.metadata['definition']['quality']
    assert safe.metadata['comparison_evidence']['status'] == 'UNKNOWN'
    assert safe.metadata['sharing']['redactions']['unknown_fields'] > 0
    assert PRIVATE not in json.dumps(safe.record())
    figure = render_figure(safe, dpi=72)
    from matplotlib.text import Text
    assert all(PRIVATE not in text.get_text() for text in figure.findobj(Text))


def test_share_verifies_original_source_before_creating_copy(tmp_path):
    source = cube()
    save_cube(source, tmp_path/'source.npy')
    with load_cube(tmp_path/'source.npy') as loaded:
        spec = map_plot(normalized_difference(loaded,0,1), source_identity(loaded))
        spec.metadata['source_fingerprint'] = source_fingerprint(loaded)
        loaded.metadata['gain'] = 99
        with pytest.raises(ValueError, match='Source changed'):
            export_share_bundle(spec, tmp_path/'rejected', source_cube=loaded, dpi=72)
    assert not (tmp_path/'rejected').exists()


def test_shared_recording_keeps_each_identity_counts_partial_and_recorded_clock(tmp_path):
    from hyperlab.acquisition.sequence import Sequence
    from hyperlab.plots import recorded_roi_plot
    from test_technical_labels_settings import metadata, sequence_file

    path = sequence_file(tmp_path/'input', [metadata() for _ in range(12)], expected=20)
    with Sequence(path) as sequence:
        spec = recorded_roi_plot(sequence, [(0,0,3,2)], [PRIVATE], COLORS)
    safe = sanitized_plot(spec)
    identities = safe.series[0]['frame_identities']
    assert isinstance(identities, list) and len(set(identities)) == 12
    assert all(identity.startswith('Identity ') for identity in identities)
    assert safe.xlabel == spec.xlabel and safe.ylabel == 'Mean (DN)'
    assert safe.metadata['recording']['axis_names'] == spec.metadata['recording']['axis_names']
    for key in ('expected_frames','frame_count','copied_frames','data_fsynced_frames',
                'durable_frames','readable_frames','admitted_frames','written_frames',
                'unpersisted_frames','explicitly_failed_frames','partial','completed','accounting'):
        assert safe.metadata['recording'][key] == spec.metadata['recording'][key]
    assert safe.metadata['recording']['expected_frames'] == 20
    assert safe.metadata['recording']['partial']
    result = export_share_bundle(spec, tmp_path/'copy', dpi=72)
    import csv
    rows = list(csv.DictReader((result/'series.csv').open(encoding='utf-8')))
    assert len(rows) == 12 and [row['frame_identity'] for row in rows] == identities
    np.testing.assert_array_equal([float(row['y']) for row in rows], np.arange(10,22))
    assert (result/'share_manifest.json').exists()


def test_shared_profile_retains_channel_mean_sd_counts_gaps_and_distance():
    from hyperlab.analysis.regions import strip_profile
    from hyperlab.plots import strip_profile_plot

    source = cube()
    roi = make_roi(source.shape[:2], {'type':'strip','points':[[.5,1.5],[4.5,1.5]],'width_px':1}, name=PRIVATE)
    exclusion = make_roi(source.shape[:2], {'type':'rectangle','bounds':[0,0,2,4]}, role='exclude')
    result = strip_profile(source, roi, exclusions=[exclusion])
    spec = strip_profile_plot(result, source=source_identity(source), source_fingerprint={'source_id':PRIVATE})
    safe = sanitized_plot(spec)
    assert safe.xlabel == 'Distance (px)' and safe.ylabel == 'Mean (DN)'
    assert safe.metadata['operation'] == 'strip_profile'
    assert safe.metadata['aggregation_order'] == 'spatial_bin_then_summary'
    for key in ('path_length_px','canonical_path_points','position_origin','output_reversed',
                'binning','projection','bin_boundary_arithmetic','count_semantics','empty_bins'):
        assert safe.metadata[key] == spec.metadata[key]
    assert [item['name'] for item in safe.series] == ['R','G','B']
    for old, new in zip(spec.series, safe.series):
        for key in ('x','y','sd','used_counts','bin_edges_px','geometry_excluded_count'):
            np.testing.assert_array_equal(old[key], new[key])
        assert np.isnan(new['y'][:2]).all() and (new['used_counts'][:2] == 0).all()
    assert 'Mean ± 1 spatial SD' in safe.caption and 'Per-feature valid pixels' in safe.caption


def test_shared_actual_study_keeps_distinct_applied_parameters_and_units(tmp_path):
    from hyperlab.study import study_summary
    from hyperlab.ui.study_dialog import study_point_plot
    from test_study_definitions import observation, study_of, feature_columns

    definitions = []
    for value in (1,2):
        study = study_of(observation(tmp_path, value,
            metadata={'processing_steps':[{'operation':'subtract','value':value}]}))
        column = feature_columns(study_summary(study))[0][0]
        original = study_point_plot(study, column)
        safe = sanitized_plot(original)
        definitions.append(safe.metadata['definition'])
        assert safe.metadata['definition']['applied_context']['processing_steps'] == [{'operation':'subtract','value':value}]
        assert safe.metadata['definition']['support_features'] == original.metadata['definition']['support_features']
        assert safe.ylabel == 'Mean (DN)'
        assert safe.metadata['counts'] == original.metadata['counts']
        assert safe.series[0]['points'][0]['original_y'] == 55
    assert definitions[0] != definitions[1]


def test_custom_numerical_recipe_cannot_silently_lose_a_parameter_or_formula(tmp_path):
    from hyperlab.plots import PlotSpec

    for steps in ([{'operation':'subtract','PRIVATE_PARAMETER':1}],
                  [{'operation':PRIVATE,'value':1}]):
        original = PlotSpec('lines','Plot','Index','Mean (DN)',
            metadata={'definition':{'processing_steps':steps}},
            series=[{'name':'ROI','x':[0],'y':[1],'color':COLORS[0]}])
        with pytest.raises(ValueError, match='custom numerical definition'):
            export_share_bundle(original,tmp_path/'blocked',dpi=72)
        assert not (tmp_path/'blocked').exists()


def test_shared_contrast_retains_operands_omissions_and_known_mismatch(tmp_path):
    from hyperlab.study import study_summary
    from hyperlab.ui.study_dialog import study_point_plot
    from test_study_definitions import observation, study_of, feature_columns

    rois = [make_roi((1,5), {'type':'rectangle','bounds':[0,0,2,1]}, roi_id='ref',role='reference'),
            make_roi((1,5), {'type':'rectangle','bounds':[2,0,5,1]}, roi_id='target')]
    data = np.repeat(np.array([[[-4.],[-2.],[2.],[4.],[20.]]]),3,axis=2)
    study = study_of(*[observation(tmp_path,i+1,data=data,rois=rois,reference='ref',
        metadata={'readback_settings':{'ExposureTime':exposure}}) for i,exposure in enumerate((100,200))])
    column = feature_columns(study_summary(study))[0][0]
    original = study_point_plot(study,column,view='contrast')
    safe = sanitized_plot(original)
    assert safe.metadata['aggregation'] == 'within_observation_summary_then_difference'
    assert safe.metadata['counts'] == original.metadata['counts']
    assert safe.metadata['counts']['omitted_by_reason'] == {'reference_operand':2}
    assert safe.metadata['comparison_evidence']['status'] == 'MISMATCH'
    target_points = [point for point in safe.metadata['points'] if point['included']]
    assert len(target_points) == 2
    for point in target_points:
        assert point['y'] == pytest.approx(35/3)
        assert point['original_y'] == pytest.approx(26/3)
        assert point['reference_value'] == -3 and point['reference_used'] == 2 and point['used'] == 3
        assert point['study_measurement_compatibility'] == 'MISMATCH'
    assert safe.ylabel == 'Mean difference (DN)'


def test_shared_pca_axes_do_not_label_dimensionless_loadings_with_score_units():
    from hyperlab.analysis import pca
    from hyperlab.plots import pca_diagnostics

    source = Cube(cube().data, {'data_level':'spectral_cube','data_source':'SYNTHETIC',
        'units':'DN','wavelengths':[450.,530.,690.],'wavelength_units':'nm',
        'wavelength_source':'SYNTHETIC fixture design'})
    variance, loads = pca_diagnostics(pca(source, n_components=2), source)
    for original in (variance, loads):
        safe = sanitized_plot(original)
        assert safe.metadata['preprocessing'] == original.metadata['preprocessing']
        assert safe.metadata['fit_sample_count'] == original.metadata['fit_sample_count']
        assert safe.metadata['units'] == 'dimensionless'
        for old,new in zip(original.series,safe.series):
            np.testing.assert_array_equal(old['y'],new['y'])


def test_shared_metadata_never_upgrades_removed_comparison_identity():
    from hyperlab.plots import PlotSpec

    original = PlotSpec('points','Study','Observation index (not time)','Mean (DN)',
        series=[{'name':PRIVATE,'x':[1], 'y':[2],'color':COLORS[0],
            'comparison_evidence':{'status':'MATCH'},
            'points':[{'measurement_compatibility':'MATCH'}]}],
        metadata={'comparison_evidence':{'status':'MATCH'}})
    safe = sanitized_plot(original)
    assert safe.metadata['comparison_evidence']['status'] == 'UNKNOWN'
    assert safe.series[0]['comparison_evidence']['status'] == 'UNKNOWN'
    assert safe.series[0]['points'][0]['measurement_compatibility'] == 'UNKNOWN'


@pytest.mark.parametrize('units', ['nm','um','µm','μm'])
def test_shared_actual_wavelength_coordinates_retain_their_supplied_units(units):
    wavelengths = np.array([450.,532.,693.]) / (1 if units == 'nm' else 1000)
    source = Cube(cube().data, {'data_level':'spectral_cube','data_source':'SYNTHETIC',
        'units':'DN','wavelengths':wavelengths.tolist(),'wavelength_units':units})
    spec = roi_plot([roi_statistics(source,(0,0,5,4),support='common')], [PRIVATE], COLORS,
        source=source_identity(source))
    safe = sanitized_plot(spec)
    np.testing.assert_array_equal(safe.series[0]['x'], wavelengths)
    assert safe.xlabel == spec.xlabel and safe.ylabel == 'Mean (DN)'
    assert source.metadata['wavelength_units'] == ('nm' if units == 'nm' else 'um')


def test_shared_legacy_unknown_definition_remains_unknown_without_invented_support():
    from hyperlab.plots import PlotSpec

    spec = PlotSpec('points','Study','Observation index (not time)','Median (DN)',
        metadata={'definition':{'status':'UNKNOWN', 'unknown_fields':['support_features','quantile_method'],
            'summary':'median','support':'common','support_features':None,'quantile_method':None,'units':'DN'}})
    safe = sanitized_plot(spec)
    assert safe.metadata['definition'] == spec.metadata['definition']


@pytest.mark.parametrize('view', ['points', 'contrast'])
def test_shared_actual_study_renders_every_group_marker_and_declared_comparison_level(tmp_path, view):
    from hyperlab.study import COMPARISON_LEVELS, new_study, add_observation, observation_from_cube
    from hyperlab.ui.study_dialog import study_point_plot

    study = new_study(PRIVATE)
    rois = [make_roi((1,5), {'type':'rectangle','bounds':bounds}, roi_id=role, role=role)
        for role,bounds in [('reference',[0,0,2,1]),('target',[2,0,5,1])]]
    data = np.repeat(np.array([[[-5.],[-1.],[2.],[4.],[20.]]]),3,axis=2)
    for sequence,level in enumerate(COMPARISON_LEVELS):
        path = save_cube(Cube(data, {'data_level':'raw_frame','units':'DN','data_source':'SYNTHETIC',
            'channel_labels':['R','G','B'],'session_id':PRIVATE,'sequence':sequence}), tmp_path/f'input-{sequence}.npy')
        with load_cube(path) as source:
            results = [roi_statistics(source,roi,bands=[0,1],support='common') for roi in rois]
            context = {'source_fingerprint':source_fingerprint(source), 'summary':'median',
                'roi_definitions':rois, 'names':['Reference','Target'], 'reference_roi_id':'reference'}
            study = add_observation(study, observation_from_cube(source, roi_results=results,
                roi_context=context, comparison_level=level, comparison_purpose='nuisance-control'))
    original = study_point_plot(study,0,view=view,group_by='specimen')
    before = original.record()
    safe = sanitized_plot(original)
    assert {item['marker'] for item in safe.series} == {'o','s','^'}
    assert [item['marker'] for item in safe.series] == [item['marker'] for item in original.series]
    assert {point['comparison_level'] for point in safe.metadata['points']} == set(COMPARISON_LEVELS)
    assert safe.metadata['aggregation'] == original.metadata['aggregation']
    assert safe.metadata['pairing'] == original.metadata['pairing']
    assert safe.metadata['counts'] == original.metadata['counts']
    assert [point['omitted_reason'] for point in safe.metadata['points']] == [
        point['omitted_reason'] for point in original.metadata['points']]
    for old,new in zip(original.series,safe.series):
        for key in ('x','y','used_counts','feature_indices'):
            np.testing.assert_array_equal(old[key],new[key])
    output = export_share_bundle(original,tmp_path/'shared',dpi=72)
    record = json.loads((output/'plot.json').read_text())
    assert [item['marker'] for item in record['series']] == [item['marker'] for item in original.series]
    assert PRIVATE not in json.dumps(record)
    assert original.record() == before


@pytest.mark.parametrize('style', ['connected', 'points'])
def test_shared_actual_rgb_categorical_style_remains_exact(style):
    original = roi_plot([roi_statistics(cube(),(0,0,5,4))],[PRIVATE],COLORS,
        source=source_identity(cube()),categorical_style=style)
    safe = sanitized_plot(original)
    assert safe.metadata['categorical_style'] == style
    render_figure(safe,dpi=72)


@pytest.mark.parametrize('field', ['marker', 'style', 'drawstyle', 'categorical_style'])
def test_custom_renderer_text_is_rejected_before_creating_shared_output(tmp_path, field):
    from hyperlab.plots import PlotSpec

    original = PlotSpec('lines','Plot','Index','Mean (DN)',
        series=[{'name':'ROI','x':[0],'y':[1],'color':COLORS[0]}])
    (original.metadata if field == 'categorical_style' else original.series[0])[field] = PRIVATE
    with pytest.raises(ValueError,match='Custom rendering options') as error:
        export_share_bundle(original,tmp_path/'blocked',dpi=72)
    assert PRIVATE not in str(error.value) and not (tmp_path/'blocked').exists()


@pytest.mark.parametrize('operation', ['smooth', 'derivative1', 'derivative2', 'integral', 'continuum'])
def test_shared_spectral_features_keep_math_availability_and_gap_reasons(tmp_path, operation):
    from hyperlab.analysis.roi_features import spectral_roi_features
    from hyperlab.plots import roi_feature_plot
    from test_science_features import spectrum, pixel_rois

    source = spectrum([1.,2.,3.,2.,1.,2.,3.], level='reflectance_cube' if operation == 'continuum' else 'spectral_cube')
    result = spectral_roi_features(source,pixel_rois(source,support='common'),operation)
    original = roi_feature_plot(result,[PRIVATE],COLORS,source=source_identity(source))
    safe = sanitized_plot(original)
    for key in ('operation','units','feature_indices','window_support','interval_support','method',
                'window','degree','derivative_order','rank_rcond','offset_scale','edge_policy','feature_results'):
        if key in original.metadata:
            assert safe.metadata[key] == original.metadata[key]
    for old,new in zip(original.series,safe.series):
        for key in ('x','y','used_counts','invalid_reasons'):
            np.testing.assert_equal(old[key],new[key])
    export_share_bundle(original,tmp_path/'complete',dpi=72)

    unavailable = spectral_roi_features(source,pixel_rois(source,support='common'),operation,
        max_gap_nm=5,measurement_gaps_nm=[[515,535]])
    original = roi_feature_plot(unavailable,[PRIVATE],COLORS,source=source_identity(source))
    safe = sanitized_plot(original)
    assert safe.metadata['interval_support'] == original.metadata['interval_support']
    assert safe.series[0]['invalid_reasons'] == original.series[0]['invalid_reasons']
    assert safe.metadata['feature_results'] == original.metadata['feature_results']


@pytest.mark.parametrize('operation', ['difference', 'ratio', 'angle', 'pca', 'interval_integral', 'interval_mean'])
def test_shared_spectral_maps_keep_actual_operation_axis_and_values(tmp_path, operation):
    from hyperlab.analysis import difference, ratio, spectral_angle, pca
    from hyperlab.analysis.distributions import spectral_interval_map
    from test_science_features import spectrum

    source = spectrum([[1.,2.,3.],[2.,4.,7.],[3.,2.,5.]])
    if operation == 'difference':
        product = difference(source,0,1)
    elif operation == 'ratio':
        product = ratio(source,0,1)
    elif operation == 'angle':
        product = spectral_angle(source,np.array([1.,2.,3.]))
    elif operation == 'pca':
        product = pca(source,n_components=2)
    else:
        product = spectral_interval_map(source,statistic='mean' if operation == 'interval_mean' else 'integral')
    original = map_plot(product,source_identity(source))
    safe = sanitized_plot(original)
    for key in ('operation','axis','feature_indices','units','semantic_center','coordinate_frame',
                'equation','reason_counts','count_semantics','minimum_denominator','policy','interval_support'):
        if key in original.metadata:
            assert safe.metadata[key] == original.metadata[key]
    np.testing.assert_array_equal(safe.image,original.image)
    np.testing.assert_array_equal(safe.valid_mask,original.valid_mask)
    assert safe.colormap == original.colormap and safe.limits == original.limits
    export_share_bundle(original,tmp_path/'copy',dpi=72)


def test_shared_residual_retains_pair_statistics_and_private_operand_aliases(tmp_path):
    from hyperlab.analysis.roi_features import roi_pairwise
    from hyperlab.plots import roi_pair_plot
    from test_science_features import spectrum, pixel_rois

    source = spectrum([[1.,2.,3.],[2.,3.,4.]])
    results = pixel_rois(source,support='common')
    original = roi_pair_plot(source,results,roi_pairwise(source,results,[PRIVATE+'A',PRIVATE+'B']),COLORS)
    safe = sanitized_plot(original)
    for key in ('feature_count','feature_indices','weighting','bias_direction','angle_units','correlation_label',
                'correlation_near_constant_tolerance','metric_domain','support_counts','rectangles'):
        assert safe.metadata[key] == original.metadata[key]
    old,new = original.metadata['pair_results'][0],safe.metadata['pair_results'][0]
    for key in ('target_index','reference_index','bias','rmse','correlation','angle','unavailable','feature_count'):
        assert new[key] == old[key]
    assert new['target'] == safe.metadata['names'][new['target_index']]
    assert new['reference'] == safe.metadata['names'][new['reference_index']]
    assert PRIVATE not in json.dumps(safe.record())
    np.testing.assert_array_equal(safe.series[0]['y'],original.series[0]['y'])
    export_share_bundle(original,tmp_path/'copy',dpi=72)
