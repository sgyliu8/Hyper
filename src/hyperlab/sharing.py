"""Explicit metadata-reduced figure copies; numerical data are not anonymous."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

import numpy as np

from .plots import PlotSpec, export_figure_bundle, plain

_TEXT = set('''UNKNOWN REMOVED MATCH MISMATCH PASS FAIL NOT_RUN NOT_TESTED COMPLETE PARTIAL
completed partial continuous ram_burst acquiring persisting recovery abandoned
diagnostic quantitative common per_band mean median min max std mad q25 q75 iqr strip_profile
linear source_pixel_summary summary_then_transform pixel_transform_then_summary
raw_frame raw_sequence raw_scan spectral_cube reflectance_cube derived_frame derived_map
LIVE REPLAY SYNTHETIC unknown wavelength category index time x y state sensor_plane color_channel
rectangle polygon strip mask target reference exclude top_left exact increasing decreasing
ecdf histogram points contrast roi specimen session observation temperature dwell
difference ratio normalized_difference reference_rmse PCA pca smooth derivative1 derivative2
integral continuum mean_intensity spectral_interval_map map_roi_distribution map_range_selection
upper lower left right full robust locked none normalized scaled unscaled real bool float32 float64
uint8 uint16 RGB8 BGR8 BayerRG12 Off Continuous false true shape residual profile
source_invalid source_ignored source_saturated unsupported insufficient_support excluded valid invalid ignored
R G B Raw red green blue -- - steps-post steps-mid'''.split())
_TEXT.update(('L2 on common finite features', 'full finite range', '1–99 percentile radius',
              '1–99 percentile', 'upper left edge', 'x + 0.5, y + 0.5', 'integer (y, x)',
              'KNOWN', 'ASSESSED', 'DIAGNOSTIC_THRESHOLD', 'retained',
              'finite and supplied source validity; enabled features only',
              'exclude values >= threshold when known', '(a - b) / (a + b)',
              'finite(a + b) and abs(a + b) >= minimum_denominator',
              'abs(a) + abs(b)', 'abs(a) + abs(b) < threshold',
              'sqrt(mean((pixel - reference)**2))', 'all selected features at each pixel', 'equal',
              'within_observation_summary_then_difference', 'raw_pixels'))
_TEXT.update(('spatial_bin_then_summary', 'Sensor plane', 'all persisted frames',
              'retained completed ROI feature selection', 'output feature per-band support',
              'admitted = durable + unpersisted; written means confirmed durable prefix',
              'first acquired frame host_monotonic_ns; device clock is separate',
              'center and unit-std', 'mean-center only', 'vector length normalization',
              'subtract', 'add', 'multiply', 'divide', 'NOT_ASSESSED', 'THWC', 'THW',
              'recovery_required', 'nuisance-control', 'target-change', 'setpoint',
              'independent_measurement', 'owner_label', 'support_features', 'quantile_method',
              'acquisition_settings', 'response_calibration', 'illumination_id', 'geometry_id'))
_TEXT.update(('first requested path point', 'count zero and mean/SD NaN',
    'Raw pixel centres to nearest path segment; ties choose first canonical segment; round caps clamp to endpoints',
    'Equal canonical half-open distance bins, last endpoint included; reverse bin arrays for the requested path direction',
    'Multiple segments: float64 projected distances and edges; no snapping tolerance',
    'Single segment: normalized projection; exact binary-input rational comparisons near bin edges; no snapping tolerance',
    'Unweighted per-feature mean of policy-valid selected raw pixels in each cross-strip bin; no signal interpolation',
    'spatial SD, not uncertainty of the mean or temporal noise',
    'geometry_count is membership before exclusions; excluded_count may overlap source quality reasons; count + geometry_excluded_count = counts.valid',
    'spectral_interval_mean', 'spectral_interval_integral', 'common over every selected original band',
    'sum((s[i]+s[i+1])/2 * (lambda[i+1]-lambda[i]))',
    'sum((s[i]+s[i+1])/2 * (lambda[i+1]-lambda[i])) / wavelength span',
    'contiguous original bands plus explicit physical gap constraints; no interpolation or extrapolation',
    'support interior must not intersect an explicitly excluded open interval',
    'total = source_excluded + physical_gap_unsupported + nonfinite_calculation + used; source causes may overlap',
    'HW pixels; source causes overlap across features and source_excluded. '
    'total = source_excluded + low_denominator + nonfinite_calculation + enabled low_signal + used; '
    'unknown low_signal is not a mask. Saturation is retained under diagnostic policy.'))
_KEYS = set('''kind title xlabel ylabel source series metadata image valid_mask colour_label colormap limits caption categories brushes
name color style x y sd lower upper normalized feature_indices sample_indices used_counts valid_counts sample_count
roi roi_id revision roi_revision roi_index roi_name roi_definition roi_definitions rect descriptor geometry geometry_counts
geometry_count excluded_count selected_count excluded_geometry_count geometry_excluded_count support_excluded_count selection_excluded_count
counts total valid invalid ignored saturated used excluded after_exclusion invalid_after_exclusion reason_counts reason_masks
bin_edges_px bin_left_px bin_right_px position_units bin_edges bin_left bin_right bin_center bin_counts bins density cumulative_counts
fraction cumulative_fraction ecdf histogram distribution drawstyle values coordinates_yx mask statistics mean std median q25 q75 iqr mad min max
policy support requested_features feature_index feature_label feature_labels channel_index channel_label channel_labels axis_kind axis_order
axis_names wavelength wavelength_units wavelengths original_wavelength_units original_wavelengths feature_wavelengths wavelengths_nm
coordinate coordinate_units coordinate_frame origin extent pixel_centers pixel_centres array_indices coordinate_order membership_rule
shape source_shape_hw shape_hw bbox bounds vertices holes points width_px units source_units value_units saturation_units saturation_value
saturation_assessment saturation_status effective_bits sample_bits source_level data_level component operation indices reference interval_nm interval_span_nm
semantic_center normalization display_limits shared_limits shared_limit_key clipped_count clipped_fraction valid_count total_count scope
sampling sampled preview_only shared_edges histogram_bins distribution_mode aggregation_order summary std_ddof spatial_sd robust_computed
single_sensor_plane roi_comparison categorical_style common_feature_indices excluded_indices common_count selected_features output_feature
definition definition_id definition_status definition_contexts population features requested support_label definition_version version schema_version
quality quality_policy quality_thresholds signal_qualification low_signal_assessment minimum_denominator signal_threshold threshold threshold_units
status assessment evaluated_count excluded_low_signal reason numerical_guard physical_support minimum_window_span_nm max_gap_nm measurement_gaps_nm
fwhm fwhm_nm fwhm_original fwhm_units band_validity bandpass response_context processing_steps preprocessing reference_context quality_definition
role analysis_context map_recipe roi_results recipe method ordinal order right_task transform selected_range value_range range_rule selected_fraction_of_used
selected_fraction_of_geometry bin_width_px bin_centres_px bins_count invalid_reasons finite_support denominator_scope quantile_method mad_scale
count_semantics used_count_semantics raw_counts total_samples rejected_frames accepted_frames acquired_frames admitted_frames copied_frames
data_fsynced_frames durable_frames readable_frames written_frames unpersisted_frames explicitly_failed_frames expected_frames frame_count
recording_mode phase retained_frames retained_bytes volatile completed partial stopped error finalization_error writer_error writer_overflow
readable_status recovery_status save_reopen_verified recovery_required transport_status signal_status measurement_compatibility comparison_evidence
settings_check unknown mismatches compared_fields unavailable independent_specimens observation_count observations points_count group_count groups
original_y reference_value reference_used reference_total total_observations omitted_count omissions reference_roi_id pairwise paired pair_relation
feature_column feature_descriptor x_axis x_units group_by view grouping point_rows rows plotted_count replicate_count specimen_count
comparison_level comparison_purpose mathematical_comparability physical_qualification source_receipt scene_assessment source_kind acquisition_source data_source
display_mode calibration_source wavelength_evidence wavelength_source signal_evidence geometry_evidence illumination_evidence response_evidence
center_time relative_time time_units span duration_s duration_limit_s recording_budget_bytes memory_budget_bytes gain exposure ExposureTime Gain
quantitative_eligible settings chunk_settings readback_settings source_fingerprint source_id session_id specimen_id treatment_id observation_id
technical_repeat_id replicate_id analysis_run_id source_file source_files annotation annotation_path annotations paths path file file_path sha256
metadata_sha256 source_provenance frame_id frame_identity frame_identities stream_epoch sequence host_utc host_monotonic_ns device_timestamp_ns
export_quality low high endpoint_left endpoint_right integral interval_mean area depth maximum_gap_nm valid_fraction used_fraction values_file valid_file
data_fsynced copied admitted durable readable rejected unpersisted acquired target_frames retry_of errors buffer_capacity'''.split())
_KEYS.update('''type support_features label evidence_source unknown_fields applied_context invalid_rule data_ignore_value
saturation_rule reference_source reference_reflectance reflectance_kind reference_applicability response_id response_matrix_id
spectral_response_id spatial_calibration equation denominator_rule denominator_units expression exclusion_rule calculation_dtype
feature_weighting source_excluded low_denominator nonfinite_calculation low_signal numerical_denominator_valid
source_invalid source_ignored source_saturated temperature_scope temperature_value temperature_unit temperature_meaning
plotted_points plotted_observations omitted_roi_rows omitted_by_reason declared_specimen_count unknown_specimen_observations
independent_replicate_count pairing aggregation origins included shown geometry_total x_available value_available omission_reason
observation_index independent_specimen_count independent_samples summary_units count_used count_total point_index'''.split())
_KEYS.update('''recording accounting time_origin frame_settings PixelFormat ExposureAuto GainAuto BalanceWhiteAuto
GammaEnable Gamma LUTEnable BlackLevel BlackLevelAuto memory_preflight max_frames queue_length queue_capacity
overflow done expected_bytes free_bytes_at_start volatile_frames can_retry can_abandon abandoned_frames
discarded_ram_frames reopen_error previous_persistence_error camera_stop_attempt writer_capacity
reopen_verified_indices metric value minimum maximum parameters reference_summary reference_selected
exclusion_definitions total_roi_rows observations_without_roi_results observation_number reference_roi_revision
temperature_reference_id dwell_seconds omitted_reason study_measurement_compatibility marker markersize
feature_unavailable unknown_dwell unknown_temperature temperature_scope_not_selected different_temperature_unit_or_meaning
reference_missing_or_ambiguous support_definition_unknown reference_operand reference_definition_or_value_unavailable
nonfinite_contrast feature_results integral_units interval_mean_units actual_interval_nm interval_support
bandpass_evidence fwhm_unit_source response_source response_calibration_id depth_area_nm maximum_depth
sampled_minimum_nm sampled_minimum_index sampled_minimum_ratio minimum_at_boundary minimum_tie_policy
window degree derivative_order rank_rcond window_support center_band_index complete allowed span_nm
fit_sample_count candidate_sample_count seed scale components explained_variance_ratio
path_length_px requested_bin_width_px actual_bin_width_px position_origin canonical_path_points output_reversed
projection binning bin_boundary_arithmetic std_interpretation empty_bins band_indices max_adjacent_delta_nm
crossed_measurement_gaps_nm comparison_roundoff_nm statistic normalized_trapezoid_weights gap_policy
measurement_gap_rule physical_gap_unsupported'''.split())
_UNITS = re.compile(r'^(?:DN|nm|um|µm|μm|px|pixel|pixels|s|ms|us|ns|rad|deg|degC|K|dB|dimensionless|reflectance|relative intensity|unknown|score)(?:[*/·]nm(?:\^2)?|/s)?$')
_IDENTITY = re.compile(r'(?:^|_)(?:id|ids|identity|identities|path|paths|file|files|sha256|fingerprint|utc|timestamp|monotonic)(?:_|$)')


def sanitized_plot(spec):
    """Keep numerical arrays/structure; use deterministic aliases without an identity map."""
    if spec.kind not in {'map', 'lines', 'points'} or spec.colormap not in {'viridis', 'RdBu_r'}:
        raise ValueError('This custom plot kind or colour map needs the internal export')
    aliases, removed = {}, {'text_values': 0, 'unknown_fields': 0, 'identities': 0}

    def alias(value, category='Identity'):
        token = (category, json.dumps(plain(value), sort_keys=True))
        if token not in aliases:
            aliases[token] = f'{category} {1 + sum(k[0] == category for k in aliases)}'
        return aliases[token]

    def clean(value, key='', strict=False):
        strict = strict or key in {'definition', 'processing_steps', 'preprocessing'}
        if key == 'frame_identities' and isinstance(value, (list, tuple)):
            return [clean(item, 'frame_identity') for item in value]
        if (_IDENTITY.search(key) and key not in {'path_length_px', 'canonical_path_points'}) or key in {'sequence', 'stream_epoch', 'calibration_source',
                'wavelength_source', 'reference_source', 'response_source', 'shared_limit_key'}:
            if value is None:
                return None
            removed['identities'] += 1
            return alias(value)
        if isinstance(value, dict):
            result = {}
            for field, child in value.items():
                if field not in _KEYS:
                    if strict:
                        raise ValueError('A custom numerical definition needs the internal export; no reduced copy was made')
                    removed['unknown_fields'] += 1
                    continue
                result[field] = clean(child, field, strict)
            if key == 'comparison_evidence':
                result['status'] = 'MISMATCH' if value.get('status') == 'MISMATCH' else 'UNKNOWN'
            return result
        if isinstance(value, np.ndarray):
            if value.dtype.kind in 'buif':
                return value.copy()
            return [clean(item, key, strict) for item in value.tolist()]
        if isinstance(value, (list, tuple)):
            return [clean(item, key, strict) for item in value]
        if isinstance(value, str):
            if key in {'measurement_compatibility', 'study_measurement_compatibility'}:
                return 'MISMATCH' if value == 'MISMATCH' else 'UNKNOWN'
            if key in {'name', 'roi_name'}:
                return alias(value, 'Region')
            if (value in _TEXT or _UNITS.fullmatch(value) or
                    key == 'color' and re.fullmatch(r'#[0-9a-fA-F]{6,8}', value) or
                    key in {'label', 'feature_label', 'feature_labels'} and re.fullmatch(r'[-+0-9.eE]+ (?:nm|um|µm|μm)', value)):
                return value
            if strict:
                raise ValueError('A custom numerical definition needs the internal export; no reduced copy was made')
            removed['text_values'] += 1
            return 'REMOVED'
        if value is None or isinstance(value, (bool, int, float, np.number)):
            return deepcopy(value)
        raise ValueError('Unsupported object in figure metadata; use the internal export')

    safe = PlotSpec(spec.kind, 'Shared scientific figure', '', '',
        source=clean(spec.source), series=clean(spec.series), metadata=clean(spec.metadata),
        image=None if spec.image is None else spec.image.copy(),
        valid_mask=None if spec.valid_mask is None else spec.valid_mask.copy(),
        limits=spec.limits, colormap=spec.colormap, brushes=clean(spec.brushes))
    axis_units = re.search(r'\(([^()]*)\)$', spec.ylabel)
    units = str((axis_units[1] if axis_units and spec.kind != 'map' else None) or
                safe.metadata.get('units') or safe.metadata.get('definition', {}).get('units') or 'unknown')
    if spec.ylabel == 'Explained variance ratio':
        units = 'dimensionless'
    if not _UNITS.fullmatch(units):
        raise ValueError('Custom signal units need the internal export; no reduced copy was made')
    if safe.metadata.get('units') not in (None, units):
        safe.metadata.setdefault('source_units', safe.metadata['units'])
    safe.metadata['units'] = units
    summary = safe.metadata.get('summary') or safe.metadata.get('definition', {}).get('summary')
    if summary is None and re.fullmatch(r'(?:ROI )?[Mm]ean \([^()]+\)', spec.ylabel):
        summary = 'mean'
    if summary in {'mean', 'median'}:
        safe.metadata['summary'] = summary
    if spec.kind == 'map':
        safe.xlabel, safe.ylabel = 'Raw x (pixel)', 'Raw y (pixel)'
    else:
        wave_units = safe.metadata.get('wavelength_units')
        axis_wave = re.fullmatch(r'Wavelength \((nm|um|µm|μm)\)', spec.xlabel)
        if axis_wave:
            wave_units = axis_wave[1]
        if safe.metadata.get('operation') == 'strip_profile' or safe.metadata.get('right_task') == 'profile':
            safe.xlabel = 'Distance (px)'
        elif safe.metadata.get('x_axis') == 'temperature' and safe.metadata.get('temperature_scope'):
            unit, meaning = safe.metadata['temperature_scope']
            safe.xlabel = f'{meaning.replace("_", " ").capitalize()} temperature ({unit})'
        elif wave_units in {'nm', 'um', 'µm', 'μm'}:
            safe.xlabel = f'Wavelength ({wave_units})'
        elif safe.metadata.get('distribution_mode'):
            safe.xlabel = f'Map value ({units})'
        elif spec.categories and all(value in {'R', 'G', 'B'} for value in spec.categories):
            safe.xlabel = 'Colour channel'
        elif spec.xlabel in {'Time (s)', 'Dwell time (s)', 'Observation index (not time)', 'Raw distance (px)',
                'Distance (px)', 'Recorded host receive elapsed time (s)', 'Recorded frame index (not time)',
                'Scan state index', 'Stored feature index', 'Principal component'}:
            safe.xlabel = spec.xlabel
        else:
            safe.xlabel = 'Original coordinate (see numerical metadata)'
        safe.ylabel = ('Cumulative fraction' if safe.metadata.get('distribution_mode') == 'ecdf' else
                       'Pixel count' if safe.metadata.get('distribution_mode') == 'histogram' else
                       f'{summary.title() if summary else "Value"} ({units})')
        if safe.metadata.get('view') == 'contrast':
            safe.ylabel = f'{summary.title() if summary else "Value"} difference ({units})'
            safe.title = 'Target minus declared reference'
        if safe.metadata.get('operation') == 'strip_profile':
            for original, item in zip(spec.series, safe.series):
                item['name'] = clean(original['name'], 'feature_label')
    safe.colour_label = f'Value ({units})'
    safe.categories = None if spec.categories is None else [
        value if value in {'R', 'G', 'B'} else alias(value, 'Region') for value in spec.categories]
    safe.caption = ('Original numerical values and spatial support; identifying metadata removed. '
                    'Dispersion is not a confidence interval; a contrast is not defect probability. '
                    'External source/reference identity is UNKNOWN. Review before sharing; data are not anonymous.')
    if summary in {'mean', 'median'}:
        spread = (' with Q25–Q75' if summary == 'median' and any(item.get('lower') is not None for item in safe.series)
                  else ' ± 1 spatial SD' if any(item.get('sd') is not None for item in safe.series) else '')
        support = safe.metadata.get('support', safe.metadata.get('definition', {}).get('support'))
        safe.caption = (f'{summary.title()}{spread}. ' +
            ('Common pixels across enabled features. ' if support == 'common' else
             'Per-feature valid pixels. ' if support == 'per_band' else '') + safe.caption)
    if 'recording' in safe.metadata:
        recording = safe.metadata['recording']
        safe.title = f'Recorded ROI summary · {recording.get("frame_count", "UNKNOWN")} / {recording.get("expected_frames", "UNKNOWN")} frames'
        safe.caption = (f'Recording {recording.get("recording_mode", "UNKNOWN")}; '
            f'partial={recording.get("partial", "UNKNOWN")}. Recorded clocks only; temporal frames are not independent specimens. ' + safe.caption)
    safe.metadata['sharing'] = {'identity_status': 'REMOVED', 'measurement_compatibility': 'UNKNOWN',
        'redactions': removed, 'source_verification': 'Internal provenance retained separately',
        'alias_scope': 'This copy only; aliases cannot establish identity across separate copies',
        'warning': 'Values, images, coordinates and grouping can still identify a sample; no upload occurs.'}
    return safe


def export_share_bundle(spec, directory, *, source_cube=None, **options):
    """Export a separate safe copy after verifying the original pinned source when supplied."""
    from .experiment_metadata import source_fingerprint
    before = None if source_cube is None else source_fingerprint(source_cube)
    expected = spec.metadata.get('source_fingerprint')
    if expected is not None and before is not None and before != expected:
        raise ValueError('Source changed since this figure was computed; run analysis again')
    safe = sanitized_plot(spec)
    directory = Path(directory)
    export_figure_bundle(safe, directory, **options)
    if before is not None and source_fingerprint(source_cube) != before:
        raise ValueError('Source changed during share export; incomplete outputs retained')
    record = {'kind': 'metadata_reduced_figure_copy', 'status': 'COMPLETE', 'transmitted': False,
        'identity_status': 'REMOVED', 'source_verification': 'MATCH' if before is not None else 'NOT_RUN',
        'alias_scope': 'This copy only; aliases cannot establish identity across separate copies',
        'measurement_compatibility': 'UNKNOWN', 'warning': safe.caption,
        'files': {path.name: {'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in directory.iterdir() if path.is_file()}}
    (directory/'share_manifest.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    return directory
