"""A small local Study view of original observations and completed ROI features."""
from copy import deepcopy
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets as W

from hyperlab.experiment_metadata import _digest, _file_identity
from hyperlab.io import load_cube
from hyperlab.plots import COLORS, PlotSpec, export_figure_bundle
from hyperlab.study import (COMPARISON_LEVELS, COMPARISON_PURPOSES, add_observation, load_study, new_study,
    measurement_comparison, observation_from_cube, relocate_observation, save_study, study_summary, verify_study)


def _text(value):
    return 'Unknown' if value is None else f'{value:g}' if isinstance(value, float) else str(value)


def study_point_plot(study, feature_column, *, x_axis='observation', temperature_scope=None,
                     view='points', group_by='roi'):
    """Original ROI points only; temperature units and meanings define one scope."""
    summary = study_summary(study)
    if isinstance(feature_column, bool) or not isinstance(feature_column, int) or not 0 <= feature_column < len(summary['feature_columns']):
        raise ValueError('Choose one completed Study feature column')
    if x_axis not in ('observation', 'temperature', 'dwell'):
        raise ValueError('Study point x axis must be observation, temperature or dwell')
    if view not in ('points', 'contrast') or group_by not in ('roi', 'specimen', 'session'):
        raise ValueError('Choose original points or within-observation contrast, grouped by ROI, specimen or session')
    if temperature_scope is not None:
        temperature_scope = tuple(temperature_scope)
        if len(temperature_scope) != 2 or temperature_scope[0] not in ('degC', 'K') or temperature_scope[1] not in (
                'setpoint', 'independent_measurement', 'owner_label'):
            raise ValueError('Temperature scope requires one declared unit and meaning')
    feature = summary['feature_columns'][feature_column]
    definition = summary['definition_contexts'][feature['definition_id']]
    observations = {row['observation_id']: row for row in summary['observations']}
    originals = {row['observation_id']: row for row in study['observations']}
    reference_rows = {}
    for row in summary['feature_rows']:
        original = originals[row['observation_id']]
        reference_id = original['analysis_run']['recipe'].get('reference_roi_id')
        if reference_id and row['roi'].get('roi_id') == reference_id and row['roi'].get('role') == 'reference':
            reference_rows.setdefault(row['observation_id'], []).append(row)
    points, omitted, groups, roi_offsets = [], {}, {}, {}
    for row in summary['feature_rows']:
        observation = observations[row['observation_id']]
        original = originals[row['observation_id']]
        roi_index = roi_offsets.get(row['observation_id'], 0)
        roi_offsets[row['observation_id']] = roi_index + 1
        cell = row['cells'].get(feature_column)
        reason, x = None, None
        if cell is None or cell['value'] is None:
            reason = 'feature_unavailable'
        elif x_axis == 'observation':
            x = row['number']
        elif x_axis == 'dwell':
            x = observation['dwell_seconds']
            if x is None:
                reason = 'unknown_dwell'
        elif observation['temperature_value'] is None:
            reason = 'unknown_temperature'
        elif temperature_scope is None:
            reason = 'temperature_scope_not_selected'
        elif (observation['temperature_unit'], observation['temperature_meaning']) != temperature_scope:
            reason = 'different_temperature_unit_or_meaning'
        else:
            x = observation['temperature_value']
        reference, reference_cell = None, None
        value = cell['value'] if cell else None
        if view == 'contrast' and reason is None:
            references = reference_rows.get(row['observation_id'], [])
            if len(references) != 1:
                reason = 'reference_missing_or_ambiguous'
            elif feature['definition_status'] != 'KNOWN':
                reason = 'support_definition_unknown'
            else:
                reference = references[0]
                reference_cell = reference['cells'].get(feature_column)
                if reference['roi'].get('roi_id') == row['roi'].get('roi_id'):
                    reason = 'reference_operand'
                elif reference_cell is None or reference_cell['value'] is None:
                    reason = 'reference_definition_or_value_unavailable'
                else:
                    value -= reference_cell['value']
                    if not math.isfinite(value):
                        value, reason = None, 'nonfinite_contrast'
        if view == 'contrast' and reason is not None:
            value = None  # The original operand is retained separately, never labelled as a difference.
        point = {'observation_id': row['observation_id'], 'observation_number': row['number'],
            'source_id': original['source_fingerprint']['source_id'], 'source_name': original['source_name'],
            'source_origin': observation['origin'], 'frame_sequence': observation['sequence'],
            'analysis_run_id': original['analysis_run']['analysis_run_id'],
            'annotation_id': original['annotation']['annotation_id'] if original['annotation'] else None,
            'roi_id': row['roi'].get('roi_id'), 'roi_revision': row['roi'].get('revision'),
            'roi_name': next((item['roi_name'] for item in original['analysis_run']['features']
                if item['roi_index'] == roi_index), row['roi'].get('name', 'ROI')), 'roi_index': roi_index,
            **{key: observation[key] for key in ('specimen_id', 'technical_repeat_id', 'treatment_id',
                'session_id', 'comparison_level', 'temperature_value', 'temperature_unit',
                'temperature_meaning', 'temperature_reference_id', 'dwell_seconds')},
            'comparison_purpose': observation['comparison_purpose'],
            'definition_id': feature['definition_id'], 'definition_status': feature['definition_status'],
            'support_label': feature['support_label'], 'measurement_compatibility': None,
            'study_measurement_compatibility': summary['comparison_evidence']['status'],
            'original_y': cell['value'] if cell else None,
            'reference_roi_id': reference['roi'].get('roi_id') if reference else None,
            'reference_roi_revision': reference['roi'].get('revision') if reference else None,
            'reference_value': reference_cell['value'] if reference_cell else None,
            'reference_used': reference_cell['used'] if reference_cell else None,
            'reference_total': reference_cell['total'] if reference_cell else None,
            'x': x, 'y': value, 'used': cell['used'] if cell else None,
            'total': cell['total'] if cell else None, 'included': reason is None, 'omitted_reason': reason}
        points.append(point)
        if reason is not None:
            omitted[reason] = omitted.get(reason, 0) + 1
            continue
        name = point['roi_name']
        if group_by != 'roi':
            identifier = point[group_by + '_id']
            group = str(identifier) if identifier is not None else f"Unknown {group_by} · Obs {row['number']}"
            name = group + ' · ' + name
        if name not in groups:
            style_index = len(groups) % 3
            groups[name] = {'name': name, 'color': COLORS[style_index], 'style': 'none',
                'marker': ('o', 's', '^')[style_index], 'x': [], 'y': [], 'points': [],
                'feature_indices': [], 'sample_indices': [], 'used_counts': [], 'frame_identities': []}
        series = groups[name]
        series['x'].append(x)
        series['y'].append(value)
        series['points'].append(point)
        series['feature_indices'].append(feature['feature_index'])
        series['sample_indices'].append(row['number'] - 1)
        series['used_counts'].append(cell['used'])
        origin = original['source_fingerprint']['origin']
        series['frame_identities'].append([origin.get(key) for key in ('session_id', 'stream_epoch', 'sequence')])
    for series in groups.values():
        ids = {point['observation_id'] for point in series['points']}
        comparison = measurement_comparison([originals[identity] for identity in originals if identity in ids])
        series['comparison_evidence'] = comparison
        series['name'] += ' · ' + comparison['status']
        for point in series['points']:
            point['measurement_compatibility'] = comparison['status']
    plotted = [point for point in points if point['included']]
    counts = {'total_observations': summary['observation_count'], 'total_roi_rows': len(points),
        'observations_without_roi_results': summary['observation_count'] - len({row['observation_id'] for row in summary['feature_rows']}),
        'plotted_points': len(plotted), 'plotted_observations': len({point['observation_id'] for point in plotted}),
        'omitted_roi_rows': len(points)-len(plotted), 'omitted_by_reason': omitted}
    if x_axis == 'temperature':
        xlabel = (f"{temperature_scope[1].replace('_', ' ').capitalize()} temperature ({temperature_scope[0]})"
                  if temperature_scope else 'Declared temperature · choose unit and meaning')
    else:
        xlabel = 'Observation index (not time)' if x_axis == 'observation' else 'Dwell time (s)'
    origins = sorted({item['origin'] or 'UNKNOWN' for item in summary['observations']})
    caption = (f"{len(plotted)} / {len(points)} ROI points; {counts['plotted_observations']} / {summary['observation_count']} observations shown. "
        f"Settings {summary['settings_check']['status']}; measurement compatibility {summary['comparison_evidence']['status']}. "
        'No pooling, fit or independent n; coincident points remain separate records.')
    title = f"{feature['feature_label']} · original ROI {feature['metric']} observations"
    ylabel = f"{feature['metric'].title()} ({feature['units']})"
    if view == 'contrast':
        title = f"{feature['feature_label']} · target minus reference ROI {feature['metric']}"
        ylabel = f"{feature['metric'].title()} difference ({feature['units']})"
        caption += ' Within each observation: target summary minus its declared reference; no pixel pairing.'
    return PlotSpec('points', title, xlabel, ylabel, source={'study_id': study['study_id'],
            'acquisition_source': origins[0] if len(origins) == 1 else 'MIXED', 'origins': origins},
        series=list(groups.values()), metadata={'study_sha256': _digest(study), 'feature_column': feature,
            'x_axis': x_axis, 'temperature_scope': list(temperature_scope) if x_axis == 'temperature' and temperature_scope else None,
            'counts': counts, 'points': points, 'settings_check': summary['settings_check'],
            'definition': definition, 'comparison_evidence': summary['comparison_evidence'],
            'view': view, 'group_by': group_by, 'support_label': feature['support_label'],
            'colour_group': group_by + ' display groups only; no pooling or spatial registration',
            'declared_specimen_count': len(summary['declared_specimen_ids']),
            'unknown_specimen_observations': summary['unknown_specimen_observations'],
            'pairing': 'No cross-observation pair relations declared or inferred',
            'aggregation': 'original completed ROI summaries; no cross-observation aggregation' if view == 'points'
                else 'within_observation_summary_then_difference',
            'independent_replicate_count': None, 'study': deepcopy(study)}, caption=caption)


def export_study_points(study, spec, directory, *, dpi=300):
    """Verify all assets before/after exporting one completed multi-source plot."""
    if _digest(study) != spec.metadata.get('study_sha256'):
        raise ValueError('Study changed since these points were prepared; refresh the points first')
    before = verify_study(study)
    if before['status'] != 'MATCH':
        raise ValueError('Study point export requires every declared source/annotation/ROI asset to match')
    if not spec.metadata['counts']['plotted_points']:
        raise ValueError('No eligible points for the selected feature, x axis and comparison view')
    completed = deepcopy(spec)
    completed.metadata['integrity_before_export'] = before
    directory = export_figure_bundle(completed, directory, dpi=dpi)
    save_study(study, directory / 'study.json')
    points = spec.metadata['points']
    with (directory / 'points.csv').open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(points[0]))
        writer.writeheader()
        writer.writerows(points)
    after = verify_study(study)
    if after['status'] != 'MATCH':
        (directory / 'export_failure.json').write_text(json.dumps({'status': 'FAIL',
            'reason': 'Study source assets changed during export', 'integrity': after}, indent=2), encoding='utf-8')
        raise ValueError('Study assets changed during export; partial files retained without a COMPLETE manifest')
    outputs = []
    for path in sorted(directory.iterdir()):
        identity = _file_identity(path)
        outputs.append({'path': path.name, 'sha256': identity['sha256'], 'size_bytes': identity['size_bytes']})
    manifest = {'schema_version': 1, 'kind': 'study_figure_export', 'status': 'COMPLETE',
        'created_utc': datetime.now(timezone.utc).isoformat(), 'study_id': study['study_id'],
        'study_sha256': spec.metadata['study_sha256'], 'integrity_after_export': after,
        'counts': spec.metadata['counts'], 'outputs': outputs,
        'interpretation': 'Exact original observation values and declared contrast operands with verified source assets; no physical or independent-replicate qualification.'}
    (directory / 'study_export_manifest.json').write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding='utf-8')
    return directory


def _point_tip(*, x, y, data):
    return '\n'.join([f"Observation {data['observation_number']} · {data['roi_name']} · x={x:g}, y={y:g}",
        *[f'{key}: {_text(data[key])}' for key in ('observation_id', 'specimen_id', 'technical_repeat_id',
            'session_id', 'roi_id', 'roi_revision', 'source_id', 'temperature_value', 'temperature_unit',
            'temperature_meaning', 'temperature_reference_id', 'dwell_seconds')],
        f"Used {data['used']} / total {data['total']}",
        *[f'{key}: {_text(data.get(key))}' for key in ('support_label', 'measurement_compatibility',
            'comparison_purpose', 'original_y', 'reference_roi_id', 'reference_value', 'reference_used', 'reference_total')]])


class StudyDialog(W.QDialog):
    """All source loading and hashing use the workbench's existing worker queue."""

    def __init__(self, workbench):
        super().__init__(workbench)
        self.workbench = workbench
        previous = getattr(workbench, '_study_state', None)
        self.study, self.path, self.receipt, self.dirty = previous or (new_study('Untitled study'), None, None, False)
        self.busy = False
        self.setWindowTitle('Study · original observations')
        self.resize(1060, 650)
        layout = W.QVBoxLayout(self)
        self.controls = W.QWidget()
        control_layout = W.QVBoxLayout(self.controls)
        control_layout.setContentsMargins(0, 0, 0, 0)
        toolbar = W.QHBoxLayout()
        self.name = W.QLineEdit(self.study['name'])
        self.name.setPlaceholderText('Study name')
        self.name.editingFinished.connect(self.rename)
        toolbar.addWidget(self.name, 1)
        for label, action in (('New', self.new), ('Open…', self.open), ('Save…', self.save), ('Verify files', self.verify)):
            button = W.QPushButton(label)
            button.clicked.connect(action)
            toolbar.addWidget(button)
        control_layout.addLayout(toolbar)
        actions = W.QHBoxLayout()
        for label, action in (('Add current saved observation', self.add_current),
                              ('Add saved files…', self.choose_files), ('Relocate selected…', self.relocate_selected)):
            button = W.QPushButton(label)
            button.clicked.connect(action)
            actions.addWidget(button)
        actions.addStretch()
        self.order = W.QComboBox()
        for label, keys in (('Observation order', ()), ('Material / batch', ('material', 'coating_batch')),
                ('Dwell time', ('dwell_seconds',)), ('Session', ('session_id',)),
                ('Temperature meaning / value', ('temperature_meaning', 'temperature_unit', 'temperature_value'))):
            self.order.addItem(label, keys)
        self.order.currentIndexChanged.connect(self.refresh)
        actions.addWidget(self.order)
        control_layout.addLayout(actions)
        self.link_toggle = W.QCheckBox('Optional links for the next observation')
        control_layout.addWidget(self.link_toggle)
        self.link_fields = W.QWidget()
        form = W.QHBoxLayout(self.link_fields)
        form.setContentsMargins(0, 0, 0, 0)
        self.treatment = W.QLineEdit()
        self.treatment.setPlaceholderText('Treatment ID · unknown if blank')
        form.addWidget(self.treatment)
        self.comparison = W.QComboBox()
        self.comparison.addItem('Comparison level · unknown', None)
        for level in COMPARISON_LEVELS:
            self.comparison.addItem(level, level)
        form.addWidget(self.comparison)
        self.purpose = W.QComboBox()
        self.purpose.addItem('Comparison purpose · unknown', None)
        for purpose in COMPARISON_PURPOSES:
            self.purpose.addItem(purpose.replace('-', ' ').title(), purpose)
        form.addWidget(self.purpose)
        self.link_fields.setVisible(False)
        self.link_toggle.toggled.connect(self.link_fields.setVisible)
        control_layout.addWidget(self.link_fields)
        layout.addWidget(self.controls)
        note = W.QLabel('Specimen, repeat and thermal context come from saved annotations. '
            'Blank fields remain unknown. Add current uses the completed ROI result; file import performs no analysis.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = W.QTabWidget()
        self.table, self.heatmap = W.QTableWidget(), W.QTableWidget()
        for table in (self.table, self.heatmap):
            table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(W.QAbstractItemView.SelectionMode.SingleSelection)
        self.tabs.addTab(self.table, 'Observations')
        self.table.verticalHeader().setVisible(False)
        self.tabs.addTab(self.heatmap, 'ROI feature heatmap')
        self.points_panel = W.QWidget()
        points_layout = W.QVBoxLayout(self.points_panel)
        self.point_controls = W.QWidget()
        point_layout = W.QVBoxLayout(self.point_controls)
        point_layout.setContentsMargins(0, 0, 0, 0)
        point_row = W.QHBoxLayout()
        point_layout.addLayout(point_row)
        self.point_feature, self.point_x, self.point_temperature = W.QComboBox(), W.QComboBox(), W.QComboBox()
        self.point_feature.setMinimumContentsLength(18)
        self.point_feature.setSizeAdjustPolicy(W.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for label, key in (('Observation index', 'observation'), ('Declared temperature', 'temperature'), ('Dwell time', 'dwell')):
            self.point_x.addItem(label, key)
        point_row.addWidget(self.point_feature, 1)
        point_row.addWidget(self.point_x)
        point_row.addWidget(self.point_temperature)
        self.points_export = W.QPushButton('Export points + figure…')
        self.points_export.clicked.connect(self.choose_points_export)
        point_row.addWidget(self.points_export)
        comparison_row = W.QHBoxLayout()
        self.point_view, self.point_group = W.QComboBox(), W.QComboBox()
        self.point_view.addItem('Original observation points', 'points')
        self.point_view.addItem('Target minus declared reference', 'contrast')
        for label, key in (('Group by ROI', 'roi'), ('Group by specimen', 'specimen'), ('Group by session', 'session')):
            self.point_group.addItem(label, key)
        comparison_row.addWidget(self.point_view)
        comparison_row.addWidget(self.point_group)
        comparison_row.addStretch()
        point_layout.addLayout(comparison_row)
        points_layout.addWidget(self.point_controls)
        self.points_chart = pg.PlotWidget(background='w')
        self.points_chart.showGrid(x=True, y=True, alpha=.15)
        self.points_chart.addLegend(offset=(-12, 12), labelTextColor='#26313d', brush=pg.mkBrush(255,255,255,225), pen=None)
        for name in ('left', 'bottom'):
            axis = self.points_chart.getAxis(name)
            axis.setTextPen('#26313d')
            axis.setPen('#26313d')
            axis.setTickFont(QtGui.QFont('Segoe UI', 10))
            axis.enableAutoSIPrefix(False)
        points_layout.addWidget(self.points_chart, 1)
        self.points_note = W.QLabel()
        self.points_note.setWordWrap(True)
        points_layout.addWidget(self.points_note)
        self.tabs.addTab(self.points_panel, 'Observation points')
        self.point_feature.currentIndexChanged.connect(self.draw_points)
        self.point_x.currentIndexChanged.connect(self.draw_points)
        self.point_temperature.currentIndexChanged.connect(self.draw_points)
        self.point_view.currentIndexChanged.connect(self.draw_points)
        self.point_group.currentIndexChanged.connect(self.draw_points)
        self.points_spec = self.points_study = None
        self.point_items = []
        self.details = W.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.tabs.addTab(self.details, 'Integrity and provenance')
        layout.addWidget(self.tabs, 1)
        self.facts = W.QLabel()
        self.facts.setWordWrap(True)
        layout.addWidget(self.facts)
        self.status = W.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table.itemSelectionChanged.connect(self.show_details)
        self.refresh()

    def _remember(self):
        self.workbench._study_state = (self.study, self.path, self.receipt, self.dirty)

    def _status(self, text, error=False):
        self.status.setText(text)
        self.status.setStyleSheet('color: #a52a2a;' if error else '')

    def _ready(self):
        if self.busy or self.workbench.task_busy or self.workbench.closing:
            self._status('An operation is running. Wait for completion before changing the Study.', True)
            return False
        return True

    def _dispatch(self, function, completed, message):
        if not self._ready():
            return
        self.busy = True
        self.controls.setEnabled(False)
        self.point_controls.setEnabled(False)
        self._status(message)
        def run():
            try:
                return function(), None
            except Exception as error:
                return None, error
        def finish(outcome):
            self.busy = False
            self.controls.setEnabled(True)
            self.point_controls.setEnabled(True)
            value, error = outcome
            if error is not None:
                self._status(f'{type(error).__name__}: {error}', True)
                self.workbench.notify('Study · ' + self.status.text())
                return
            completed(value)
            self._remember()
            self.refresh()
            self.workbench.notify('Study · ' + self.status.text())
        self.workbench.background(run, finish, message)

    def rename(self):
        if self.name.text().strip() and self.name.text().strip() != self.study['name']:
            self.study = dict(self.study, name=self.name.text().strip())
            self.dirty = True
            self._remember()

    def _may_replace(self):
        if not self._ready():
            return False
        if self.dirty:
            self._status('Save this Study before creating or opening another one.', True)
            return False
        return True

    def new(self):
        if self._may_replace():
            self.study, self.path, self.receipt = new_study('Untitled study'), None, None
            self.name.setText(self.study['name'])
            self._remember()
            self.refresh()
            self._status('New Study. Add saved observations, then save the manifest.')

    def open(self):
        if not self._may_replace():
            return
        path, _ = W.QFileDialog.getOpenFileName(self, 'Open Study', str(self.workbench.workspace), 'Study JSON (*.json)')
        if path:
            self.open_path(path)

    def open_path(self, path):
        if not self._may_replace():
            return
        def run():
            study = load_study(path)
            return study, verify_study(study)
        def done(result):
            self.study, self.receipt = result
            self.path, self.dirty = Path(path), False
            self.name.setText(self.study['name'])
            self._status(f"Opened Study · file integrity {self.receipt['status']}")
        self._dispatch(run, done, 'Opening Study and checking every declared source asset…')

    def save(self):
        if not self._ready():
            return
        self.rename()
        path, _ = W.QFileDialog.getSaveFileName(self, 'Save Study manifest',
            str(self.path or self.workbench.workspace / 'studies' / 'study.json'), 'Study JSON (*.json)')
        if path:
            self.save_path(path)

    def save_path(self, path):
        study = deepcopy(self.study)
        def run():
            receipt = verify_study(study)
            return save_study(study, path), receipt
        def done(result):
            self.path, self.receipt = result
            self.dirty = False
            self._status(f"Saved {self.path.name} · file integrity {self.receipt['status']}")
        self._dispatch(run, done, 'Saving Study and checking source assets…')

    def verify(self):
        study = deepcopy(self.study)
        def done(receipt):
            self.receipt = receipt
            self._status(f"File integrity {receipt['status']} · original observation identities retained")
        self._dispatch(lambda: verify_study(study), done, 'Checking every declared file; no fallback search…')

    def _links(self):
        if not self.link_toggle.isChecked():
            return {}, None, None
        return {'treatment_id': self.treatment.text().strip() or None}, self.comparison.currentData(), self.purpose.currentData()

    def _added(self, result):
        self.study, self.receipt, message = result
        self.dirty = True
        self._status(message)

    def add_current(self):
        if not self._ready():
            return
        cube = self.workbench.cube
        if cube is None or not cube.metadata.get('source_file'):
            self._status('Save and open the current frame before adding it to a Study.', True)
            return
        study, annotation = deepcopy(self.study), deepcopy(self.workbench.annotation)
        annotation_path = self.workbench.annotation_path
        has_result = self.workbench.roi_source is cube and bool(self.workbench.roi_results)
        results = deepcopy(self.workbench.roi_results) if has_result else None
        context = deepcopy(self.workbench.roi_result_context) if has_result else None
        features = deepcopy(self.workbench.science_result) if has_result else None
        links, level, purpose = self._links()
        def run():
            observation = observation_from_cube(cube, annotation=annotation, annotation_path=annotation_path,
                roi_results=results, roi_context=context, feature_result=features, links=links, comparison_level=level,
                comparison_purpose=purpose)
            result = add_observation(study, observation)
            return result, verify_study(result), 'Added original observation · ' + (
                'completed ROI features retained' if observation['analysis_run'] else 'analysis NOT_RUN')
        self._dispatch(run, self._added, 'Pinning saved observation and completed ROI provenance…')

    def choose_files(self):
        if not self._ready():
            return
        paths, _ = W.QFileDialog.getOpenFileNames(self, 'Add saved observations', str(self.workbench.workspace),
                                                'Saved data (*.npy *.npz *.hdr)')
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths):
        study = deepcopy(self.study)
        links, level, purpose = self._links()
        def run():
            result, failures, added = study, [], 0
            for path in paths:
                try:
                    with load_cube(path) as cube:
                        observation = observation_from_cube(cube, links=links, comparison_level=level, comparison_purpose=purpose)
                    result = add_observation(result, observation)
                    added += 1
                except Exception as error:
                    failures.append(f'{Path(path).name}: {error}')
            return result, verify_study(result), f'Added {added}/{len(paths)} observations · analysis NOT_RUN.' + (
                ' Not added: ' + '; '.join(failures) if failures else '')
        self._dispatch(run, self._added, 'Loading saved observations and hashing their declared assets…')

    def _selected(self):
        item = self.table.item(self.table.currentRow(), 0)
        identity = item.data(QtCore.Qt.ItemDataRole.UserRole) if item is not None else None
        return next((entry for entry in self.study['observations'] if entry['observation_id'] == identity), None)

    def relocate_selected(self):
        if not self._ready():
            return
        observation = self._selected()
        if observation is None:
            self._status('Select an observation row first.', True)
            return
        dialog = W.QDialog(self)
        dialog.setWindowTitle('Explicit asset locations · all files must match')
        dialog.resize(820, 340)
        layout = W.QVBoxLayout(dialog)
        note = W.QLabel('Choose each recorded asset location. Blank or missing required files fail verification. '
                       'Original source and annotation identities are preserved.')
        note.setWordWrap(True)
        layout.addWidget(note)
        rows = W.QFormLayout()
        fields = {}
        for original, location in observation['asset_locations'].items():
            line = W.QLineEdit(location)
            line.setToolTip(original)
            fields[original] = line
            rows.addRow(Path(original).name, line)
        layout.addLayout(rows)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok | W.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != W.QDialog.DialogCode.Accepted:
            return
        locations = {key: field.text().strip() for key, field in fields.items()}
        if not all(locations.values()):
            self._status('Every asset needs an explicit location.', True)
            return
        study, identity = deepcopy(self.study), observation['observation_id']
        def run():
            result = relocate_observation(study, identity, locations)
            return result, verify_study(result), 'Explicit relocation verified for every asset. Save the Study to retain it.'
        self._dispatch(run, self._added, 'Verifying explicit relocation against every original hash…')

    def refresh(self):
        summary = study_summary(self.study)
        keys = self.order.currentData() or ()
        rows = sorted(summary['observations'], key=lambda row: tuple(
            (row[key] is None, row[key] if row[key] is not None else '') for key in keys))
        integrity = {entry['observation_id']: entry['status'] for entry in (self.receipt or {}).get('observations', [])}
        fields = [('number', 'Observation'), ('source_name', 'Source'), ('sequence', 'Frame'), ('origin', 'Origin'),
            ('specimen_id', 'Specimen'), ('treatment_id', 'Treatment'), ('material', 'Material / paint'),
            ('coating_batch', 'Batch'), ('dwell_seconds', 'Dwell (s)'), ('session_id', 'Session'),
            ('technical_repeat_id', 'Technical repeat'), ('temperature_value', 'Temperature'),
            ('temperature_unit', 'Unit'), ('temperature_meaning', 'Temperature meaning'),
            ('temperature_reference_id', 'Temperature source / reference'), ('comparison_level', 'Comparison level'),
            ('comparison_purpose', 'Declared purpose'),
            ('analysis_status', 'Analysis'), ('integrity', 'File integrity')]
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        self.table.setColumnCount(len(fields))
        self.table.setHorizontalHeaderLabels([label for _, label in fields])
        for row_index, row in enumerate(rows):
            row['integrity'] = integrity.get(row['observation_id'], 'NOT_CHECKED')
            for col, (key, _) in enumerate(fields):
                value = row[key]
                if key == 'origin' and value == 'LIVE':
                    value = 'Real camera capture'
                if key == 'session_id' and value is not None and len(str(value)) > 16:
                    value = str(value)[:12] + '…'
                item = W.QTableWidgetItem(_text(value))
                item.setData(QtCore.Qt.ItemDataRole.UserRole, row['observation_id'])
                item.setToolTip(_text(row[key]))
                if key == 'source_name' and row['same_array_observations']:
                    item.setToolTip('Identical array bytes also occur in another observation. This does not establish independence or identify a physical cause.')
                self.table.setItem(row_index, col, item)
        optional = {'treatment_id', 'coating_batch', 'dwell_seconds', 'technical_repeat_id',
                    'temperature_value', 'temperature_unit', 'temperature_meaning',
                    'temperature_reference_id', 'comparison_level', 'comparison_purpose'}
        temperature = any(row['temperature_value'] is not None for row in rows) or 'temperature_value' in keys
        for col, (key, _) in enumerate(fields):
            visible = key not in optional or key in keys or any(row[key] is not None for row in rows)
            if key.startswith('temperature_'):
                visible = temperature
            self.table.setColumnHidden(col, not visible)
        self.table.resizeColumnsToContents()
        for col in range(len(fields)):
            self.table.setColumnWidth(col, min(230, self.table.columnWidth(col)))
        self.table.blockSignals(False)
        from matplotlib import colormaps
        feature_rows, columns = summary['feature_rows'], summary['feature_columns']
        ranks = {row['observation_id']: index for index, row in enumerate(rows)}
        feature_rows.sort(key=lambda row: ranks[row['observation_id']])
        self.heatmap.setRowCount(len(feature_rows))
        self.heatmap.setColumnCount(len(columns))
        self.heatmap.setVerticalHeaderLabels([f"Obs {row['number']} · {row['roi'].get('name', 'ROI')}" for row in feature_rows])
        observations = {row['observation_id']: row for row in rows}
        for row_index, row in enumerate(feature_rows):
            context = observations[row['observation_id']]
            self.heatmap.verticalHeaderItem(row_index).setToolTip('\n'.join(
                f'{key}: {_text(context[key])}' for key in ('specimen_id', 'material', 'coating_batch',
                    'dwell_seconds', 'session_id', 'temperature_value', 'temperature_unit',
                    'temperature_meaning', 'temperature_reference_id')))
        self.heatmap.setHorizontalHeaderLabels([f"{column['feature_label']}\n{column['metric']} ({column['units']})\n"
            f"{column['support_label'][:65]}{'…' if len(column['support_label']) > 65 else ''}" for column in columns])
        for col in range(len(columns)):
            values = [row['cells'][col]['value'] for row in feature_rows if col in row['cells'] and row['cells'][col]['value'] is not None]
            low, high = (min(values), max(values)) if values else (0, 0)
            for row_index, row in enumerate(feature_rows):
                cell = row['cells'].get(col, {'value': None, 'used': 0, 'total': 0})
                value = cell['value']
                item = W.QTableWidgetItem(_text(value))
                if value is None:
                    color = QtGui.QColor('#dce1e6')
                else:
                    fraction = (value-low)/(high-low) if high > low else .5
                    rgba = colormaps['viridis'](fraction, bytes=True)
                    color = QtGui.QColor(*[int(channel) for channel in rgba])
                item.setBackground(color)
                item.setForeground(QtGui.QColor('#ffffff' if color.lightness() < 130 else '#17212b'))
                item.setToolTip(f"Used {cell['used']} / total {cell['total']} · per-column colour scale [{low:g}, {high:g}].\n"
                    f"{columns[col]['support_label']}\nDefinition {columns[col]['definition_status']}\n"
                    + json.dumps(summary['definition_contexts'][columns[col]['definition_id']], indent=2))
                self.heatmap.setItem(row_index, col, item)
        self.heatmap.resizeColumnsToContents()
        self.facts.setText(f"{summary['observation_count']} original observations · "
            f"{len(summary['declared_specimen_ids'])} declared specimen IDs · "
            f"{summary['unknown_specimen_observations']} observations with specimen unknown · "
            f"settings {summary['settings_check']['status']} · measurement compatibility {summary['comparison_evidence']['status']}. "
            'Independent replicate count unknown; registration not verified. Heatmap colours scale separately per column; no pooling.')
        self.refresh_point_choices(summary)
        self.show_details()

    def refresh_point_choices(self, summary):
        previous = self.point_feature.currentData()
        self.point_feature.blockSignals(True)
        self.point_feature.clear()
        for column in summary['feature_columns']:
            self.point_feature.addItem(f"{column['feature_label']} · {column['metric']} ({column['units']}) · "
                f"{column['support_label'][:65]}{'…' if len(column['support_label']) > 65 else ''}", column)
            self.point_feature.setItemData(self.point_feature.count()-1,
                f"{column['policy']} · {column['support_label']} · definition {column['definition_status']}",
                QtCore.Qt.ItemDataRole.ToolTipRole)
        self.point_feature.setCurrentIndex(max(0, self.point_feature.findData(previous)))
        self.point_feature.blockSignals(False)
        previous = self.point_temperature.currentData()
        scopes = sorted({(row['temperature_unit'], row['temperature_meaning']) for row in summary['observations']
                         if row['temperature_value'] is not None})
        self.point_temperature.blockSignals(True)
        self.point_temperature.clear()
        self.point_temperature.addItem('Choose temperature unit / meaning', None)
        for unit, meaning in scopes:
            self.point_temperature.addItem(f"{meaning.replace('_', ' ').title()} · {unit}", [unit, meaning])
        index = self.point_temperature.findData(previous) if previous is not None else -1
        self.point_temperature.setCurrentIndex(index if index > 0 else 1 if len(scopes) == 1 else 0)
        self.point_temperature.blockSignals(False)
        self.draw_points()

    def draw_points(self):
        self.points_chart.clear()
        self.points_chart.plotItem.legend.clear()
        self.point_items = []
        self.point_temperature.setVisible(self.point_x.currentData() == 'temperature')
        self.points_export.setEnabled(False)
        self.points_spec = self.points_study = None
        if self.point_feature.currentIndex() < 0:
            self.points_chart.setTitle('No completed observation points', color='#17212b')
            self.points_chart.setLabel('bottom', '')
            self.points_chart.setLabel('left', '')
            self.points_note.setText('No completed ROI feature columns. Add a saved observation after ROI analysis; imported files remain NOT_RUN.')
            return
        self.points_study = deepcopy(self.study)
        self.points_spec = study_point_plot(self.points_study, self.point_feature.currentIndex(),
            x_axis=self.point_x.currentData(), temperature_scope=self.point_temperature.currentData(),
            view=self.point_view.currentData(), group_by=self.point_group.currentData())
        spec = self.points_spec
        self.points_chart.setTitle(spec.title, color='#17212b', size='12pt')
        for axis, label in (('bottom', spec.xlabel), ('left', spec.ylabel)):
            self.points_chart.setLabel(axis, label, color='#26313d', siPrefixEnableRanges=())
            self.points_chart.getAxis(axis).setTicks(None if spec.series else [])
        if not spec.series:
            self.points_chart.setRange(xRange=(0, 1), yRange=(0, 1), padding=0)
            message = pg.TextItem('No points for this view\nSee omitted reasons below',
                                  anchor=(.5, .5), color='#5c6875')
            message.setPos(.5, .5)
            self.points_chart.addItem(message)
        for series in spec.series:
            item = pg.ScatterPlotItem(x=series['x'], y=series['y'], data=series['points'],
                name=series['name'], pen=pg.mkPen('w', width=.7), brush=series['color'],
                symbol={'o': 'o', 's': 's', '^': 't1'}[series['marker']], size=10,
                hoverable=True, hoverSize=13, tip=_point_tip)
            self.points_chart.addItem(item)
            self.point_items.append(item)
        self.points_chart.enableAutoRange()
        counts = spec.metadata['counts']
        missing = ', '.join(f"{reason.replace('_', ' ')}: {count}" for reason, count in counts['omitted_by_reason'].items())
        self.points_note.setText(spec.caption + f" Observations without ROI results: {counts['observations_without_roi_results']}. "
            + (f'Omitted: {missing}. ' if missing else '') + f" {spec.metadata['support_label']} · "
            'Hover points for supports, operands and source identity. No cross-observation pairing is inferred.')
        self.points_export.setEnabled(bool(counts['plotted_points']))

    def choose_points_export(self):
        if not self._ready() or self.points_spec is None:
            return
        parent = W.QFileDialog.getExistingDirectory(self, 'Choose parent folder for a new Study figure bundle', str(self.workbench.workspace))
        if parent:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            self.export_points_path(Path(parent) / ('study_points_' + stamp))

    def export_points_path(self, path):
        if self.points_spec is None:
            self._status('Choose a completed Study feature before exporting.', True)
            return
        study, spec = deepcopy(self.points_study), deepcopy(self.points_spec)
        def done(directory):
            self._status(f'Saved exact points, SVG/PDF/PNG and verified Study evidence: {directory}')
        self._dispatch(lambda: export_study_points(study, spec, path), done,
                       'Verifying all Study assets and exporting the completed original points…')

    def show_details(self):
        selected = self._selected()
        self.details.setPlainText(json.dumps({'study_id': self.study['study_id'],
            'path': str(self.path) if self.path else None, 'unsaved_changes': self.dirty,
            'settings_check': study_summary(self.study)['settings_check'], 'integrity': self.receipt,
            'selected_observation': selected}, indent=2, ensure_ascii=False, allow_nan=False))
