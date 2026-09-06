import csv
import json

import numpy as np
import pytest

from hyperlab.experiment_metadata import save_annotation
from hyperlab.io import load_cube
from hyperlab.plots import render_figure
from hyperlab.study import add_observation, new_study
from hyperlab.ui.study_dialog import (StudyDialog, export_study_points, study_point_plot)
from test_technical_study import WorkbenchStub, saved, with_analysis


def make_study(tmp_path, conditions):
    study, paths = new_study('SYNTHETIC Study point test'), []
    for index, values in enumerate(conditions):
        path = saved(tmp_path / str(index), sequence=index+1)
        paths.append(path)
        with load_cube(path) as cube:
            annotation, annotation_path = save_annotation(tmp_path / 'annotations', cube,
                dict(specimen_id='same coupon', replicate_id=f'repeat {index+1}', **values))
            observation = with_analysis(cube, annotation=annotation, annotation_path=annotation_path,
                                        comparison_level='within-session')
        study = add_observation(study, observation)
    return study, paths


def temperature(value=20, unit='degC', meaning='independent_measurement'):
    return {'temperature_value': value, 'temperature_unit': unit, 'temperature_meaning': meaning,
            'temperature_reference_id': 'synthetic temperature log'}


def test_original_observation_points_preserve_identical_repeats_and_do_not_draw_lines(tmp_path):
    study, _ = make_study(tmp_path, [{}] * 6)
    spec = study_point_plot(study, 0)
    assert spec.metadata['counts']['plotted_points'] == spec.metadata['counts']['plotted_observations'] == 6
    np.testing.assert_equal(spec.series[0]['x'], np.arange(1, 7))
    assert len({point['observation_id'] for point in spec.metadata['points']}) == 6
    assert len({point['specimen_id'] for point in spec.metadata['points']}) == 1
    assert len({point['technical_repeat_id'] for point in spec.metadata['points']}) == 6
    assert spec.metadata['independent_replicate_count'] is None
    assert all(series['style'] == 'none' and series['marker'] for series in spec.series)
    figure = render_figure(spec, dpi=72)
    line = figure.axes[0].lines[0]
    assert line.get_linestyle() == 'None'
    assert line.get_marker() == 'o'  # Six points must not disappear in shared figure export.
    assert 'not time' in spec.xlabel
    assert all(point['source_id'] for point in spec.metadata['points'])


def test_temperature_requires_one_unit_and_meaning_unknowns_remain_omitted(tmp_path):
    study, _ = make_study(tmp_path, [temperature(), temperature(), temperature(293.15, 'K'),
        temperature(20, meaning='setpoint'), temperature(20, meaning='owner_label'), {}])
    unselected = study_point_plot(study, 0, x_axis='temperature')
    assert unselected.metadata['counts']['plotted_points'] == 0
    assert unselected.metadata['counts']['omitted_by_reason'] == {
        'temperature_scope_not_selected': 5, 'unknown_temperature': 1}
    spec = study_point_plot(study, 0, x_axis='temperature', temperature_scope=('degC', 'independent_measurement'))
    counts = spec.metadata['counts']
    assert counts['total_roi_rows'] == 6 and counts['plotted_points'] == 2
    assert counts['omitted_by_reason'] == {'different_temperature_unit_or_meaning': 3, 'unknown_temperature': 1}
    assert sum(counts['omitted_by_reason'].values()) + counts['plotted_points'] == counts['total_roi_rows']
    np.testing.assert_equal(spec.series[0]['x'], [20, 20])
    assert spec.xlabel == 'Independent measurement temperature (degC)'
    assert all(point['temperature_reference_id'] == 'synthetic temperature log' for point in spec.series[0]['points'])
    assert len(spec.series[0]['points']) == 2  # Same x/y remains two exact records, never averaged.
    with pytest.raises(ValueError, match='unit and meaning'):
        study_point_plot(study, 0, x_axis='temperature', temperature_scope=('C', 'predicted'))


def test_dwell_zero_is_known_and_missing_values_are_not_inferred(tmp_path):
    study, _ = make_study(tmp_path, [{'dwell_seconds': 0}, {'dwell_seconds': 30}, {}])
    spec = study_point_plot(study, 0, x_axis='dwell')
    np.testing.assert_equal(spec.series[0]['x'], [0, 30])
    assert spec.metadata['counts']['omitted_by_reason'] == {'unknown_dwell': 1}
    assert spec.metadata['points'][-1]['x'] is None
    assert not spec.metadata['points'][-1]['included']
    assert spec.xlabel == 'Dwell time (s)'


def test_export_preserves_exact_included_and_omitted_points_and_all_source_hashes(tmp_path):
    study, _ = make_study(tmp_path, [temperature(), {}])
    spec = study_point_plot(study, 0, x_axis='temperature', temperature_scope=('degC', 'independent_measurement'))
    output = export_study_points(study, spec, tmp_path / 'export with spaces', dpi=72)
    rows = list(csv.DictReader((output / 'points.csv').open(encoding='utf-8')))
    assert len(rows) == 2
    assert rows[0]['included'] == 'True' and float(rows[0]['x']) == 20
    assert float(rows[0]['y']) == spec.series[0]['y'][0]
    assert rows[1]['included'] == 'False' and rows[1]['x'] == ''
    assert rows[1]['omitted_reason'] == 'unknown_temperature'
    record = json.loads((output / 'plot.json').read_text(encoding='utf-8'))
    original = record['metadata']['study']['observations'][0]
    assert original['source_fingerprint'] == study['observations'][0]['source_fingerprint']
    assert original['analysis_run']['rois'] == study['observations'][0]['analysis_run']['rois']
    assert rows[0]['analysis_run_id'] == original['analysis_run']['analysis_run_id']
    manifest = json.loads((output / 'study_export_manifest.json').read_text(encoding='utf-8'))
    assert manifest['status'] == 'COMPLETE'
    assert manifest['integrity_after_export']['status'] == 'MATCH'
    assert {item['path'] for item in manifest['outputs']} >= {'plot.json', 'points.csv', 'study.json', 'figure.svg', 'figure.pdf', 'figure.png'}
    assert all(item['sha256'] and item['size_bytes'] > 0 for item in manifest['outputs'])
    assert 'SYNTHETIC' in (output / 'figure.svg').read_text(encoding='utf-8')


def test_export_refuses_changed_source_before_creating_any_output(tmp_path):
    study, paths = make_study(tmp_path, [{}])
    spec = study_point_plot(study, 0)
    paths[0].with_suffix('.npy.json').write_text('{}', encoding='utf-8')
    output = tmp_path / 'not created'
    with pytest.raises(ValueError, match='every declared'):
        export_study_points(study, spec, output, dpi=72)
    assert not output.exists()


def test_export_preserves_partial_outputs_without_complete_on_mid_export_change(tmp_path, monkeypatch):
    import hyperlab.ui.study_dialog as module
    study, paths = make_study(tmp_path, [{}])
    spec = study_point_plot(study, 0)
    original_export = module.export_figure_bundle
    def change_after_render(*args, **kwargs):
        output = original_export(*args, **kwargs)
        paths[0].with_suffix('.npy.json').write_text('{}', encoding='utf-8')
        return output
    monkeypatch.setattr(module, 'export_figure_bundle', change_after_render)
    output = tmp_path / 'partial'
    with pytest.raises(ValueError, match='changed during export'):
        export_study_points(study, spec, output, dpi=72)
    assert (output / 'figure.png').exists()
    assert (output / 'points.csv').exists()
    assert json.loads((output / 'export_failure.json').read_text())['status'] == 'FAIL'
    assert not (output / 'study_export_manifest.json').exists()


def test_dialog_keeps_mixed_temperature_scope_explicit_and_tooltip_identity(qtbot, tmp_path):
    study, _ = make_study(tmp_path, [temperature(), temperature(20, meaning='owner_label'), {}])
    workbench = WorkbenchStub(tmp_path)
    workbench._study_state = (study, None, None, False)
    qtbot.addWidget(workbench)
    dialog = StudyDialog(workbench)
    qtbot.addWidget(dialog)
    assert dialog.points_spec.metadata['counts']['plotted_points'] == 3
    dialog.point_x.setCurrentIndex(dialog.point_x.findData('temperature'))
    assert dialog.point_temperature.currentData() is None
    assert dialog.points_spec.metadata['counts']['plotted_points'] == 0
    assert not dialog.points_export.isEnabled()
    dialog.point_temperature.setCurrentIndex(dialog.point_temperature.findData(['degC', 'independent_measurement']))
    assert dialog.points_spec.metadata['counts']['plotted_points'] == 1
    point = dialog.point_items[0].points()[0]
    tip = dialog.point_items[0].opts['tip'](x=point.pos().x(), y=point.pos().y(), data=point.data())
    assert 'same coupon' in tip and 'repeat 1' in tip and point.data()['observation_id'] in tip
    assert 'different temperature unit or meaning' in dialog.points_note.text()
    dialog.new()
    assert dialog.points_spec is None
    assert not dialog.points_export.isEnabled()
