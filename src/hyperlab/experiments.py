"""Small local experiment products; time statistics are not spatial uncertainty."""
import json
from pathlib import Path
import numpy as np
from hyperlab.analysis import TemporalStatistics
from hyperlab.io import Cube, save_cube


def _unknown(value):
    if value is None or (isinstance(value, str) and value.strip().lower() in ('', 'unknown', 'unavailable', 'not_tested')):
        return True
    if isinstance(value, (float, np.floating)):
        return not np.isfinite(value)
    if isinstance(value, (list, tuple, dict)):
        values = value.values() if isinstance(value, dict) else value
        return not value or any(_unknown(item) for item in values)
    return False


def _setting_values(item):
    settings = dict(item.get('readback_settings') or item.get('current_settings') or {})
    chunks = item.get('chunk_settings') or {}
    for target, chunk in (('ExposureTime', 'ChunkExposureTime'), ('Gain', 'ChunkGain')):
        if not _unknown(chunks.get(chunk)):
            settings[target] = chunks[chunk]
    return settings


def matching_settings(metadata):
    if len(metadata) < 2:
        raise ValueError('At least two references required')
    keys = ('PixelFormat', 'ExposureTime', 'Gain', 'ExposureAuto', 'GainAuto',
            'BalanceWhiteAuto', 'GammaEnable', 'Gamma', 'LUTEnable', 'BlackLevel', 'BlackLevelAuto')
    settings = [_setting_values(item) for item in metadata]
    unknown, mismatches, unavailable = [], [], []
    compared = []
    for key in keys:
        values = [item.get(key) for item in settings]
        absent = [(item.get('capabilities') or item.get('feature_capabilities') or {}).get(key, {}).get('supported') is False
                  for item in metadata]
        if all(absent) and all(_unknown(value) for value in values):
            unavailable.append(key)
        elif any(absent):
            mismatches.append(key)
        else:
            known = [value for value in values if not _unknown(value)]
            if len(known) != len(values):
                unknown.append(key)
            if known and any(value != known[0] for value in known[1:]):
                mismatches.append(key)
            elif len(known) == len(values):
                compared.append(key)
    for key in ('shape', 'model', 'serial', 'pixel_format'):
        values = [item.get(key) or (item.get('device', {}).get(key) if isinstance(item.get('device'), dict) else None)
                  for item in metadata]
        values = [list(value) if isinstance(value, tuple) else value for value in values]
        known = [value for value in values if not _unknown(value)]
        if len(known) != len(values):
            unknown.append(key)
        if known and any(value != known[0] for value in known[1:]):
            mismatches.append(key)
        elif len(known) == len(values):
            compared.append(key)
    # Equal session readbacks are insufficient while an automatic mode can vary
    # frame settings. Chunk evidence can establish exposure/gain per frame.
    for automatic, chunk in (('ExposureAuto', 'ChunkExposureTime'), ('GainAuto', 'ChunkGain'),
                             ('BalanceWhiteAuto', None), ('BlackLevelAuto', None)):
        active = any(not _unknown(item.get(automatic)) and item[automatic] not in ('Off', False, 0)
                     for item in settings)
        if active and (chunk is None or any(_unknown((item.get('chunk_settings') or {}).get(chunk)) for item in metadata)):
            unknown.append(automatic + ': active without per-frame evidence')
    return {'status': 'MISMATCH' if mismatches else 'UNKNOWN' if unknown else 'MATCH',
            'mismatches': mismatches, 'unknown': unknown, 'unavailable': unavailable,
            'compared_fields': compared, 'value_evidence': 'per-frame chunks where available, otherwise session readback',
            'note': 'Settings consistency only; illumination/geometry and spectral calibration require evidence.'}


def summarize_sequence(sequence, directory):
    """Online Welford moments; one input frame at a time, immutable source retained."""
    if sequence.frame_count < 2:
        raise ValueError('Temporal repeatability requires at least two saved frames')
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError(directory)
    first = sequence.frame(0)
    bits = first.metadata.get('pfnc_sample_bits', first.metadata.get('effective_bits'))
    saturation = first.metadata.get('saturation_value', (2 ** int(bits) - 1) if bits else None)
    stats = TemporalStatistics(first.data.shape, saturation_value=saturation)
    trend = []
    observed_metadata = []
    for index in range(sequence.frame_count):
        frame = sequence.frame(index)
        observed_metadata.append(frame.metadata)
        good = np.isfinite(frame.data)
        if frame.metadata.get('valid') is False:
            good[:] = False
        ignore = frame.metadata.get('data_ignore_value')
        if ignore is not None:
            good &= frame.data != ignore
        stats.update(frame.data, good)
        mean = float(np.mean(frame.data[good], dtype=np.float64)) if np.any(good) else None
        trend.append({'index': index, 'identity': frame.identity,
                      'host_utc': frame.metadata.get('host_utc'), 'mean_dn': mean,
                      'valid_sample_count': int(np.count_nonzero(good)), 'total_sample_count': int(frame.data.size)})
    result = stats.result()
    settings_check = matching_settings(observed_metadata)
    if settings_check['status'] == 'MISMATCH':
        raise ValueError(f"Cannot pool temporal frames: settings mismatch: {', '.join(settings_check['mismatches'])}")
    directory.mkdir(parents=True, exist_ok=False)
    source = dict(sequence.metadata)
    for key in ('mean', 'std', 'count', 'saturated_count'):
        data = result[key]
        meta = {'data_level': 'derived_frame', 'data_source': source.get('acquisition_source', source.get('data_source', 'unknown')),
                'acquisition_source': source.get('acquisition_source', source.get('data_source', 'unknown')),
                'display_mode': 'REPLAY', 'units': 'DN' if key in ('mean', 'std') else 'count',
                'wavelengths': None, 'pixel_format': 'derived', 'source_provenance': source,
                'processing_steps': [{'operation': 'temporal ' + key, 'frames': sequence.frame_count,
                                      'policy': 'diagnostic; finite, declared valid, non-ignored samples; includes saturation'}],
                'settings_check': settings_check,
                'completed': True, 'partial': False}
        # A temporal colour-derived image keeps explicit colour meaning; no T/K conversion.
        if data.ndim == 3:
            labels = first.metadata.get('channel_labels')
            if labels is None:
                fmt = first.metadata.get('pixel_format')
                labels = list(fmt[:3]) if fmt in ('RGB8', 'BGR8') else [f'channel_{i}' for i in range(data.shape[2])]
            meta['channel_labels'] = list(labels)
        validity = result['count'] > 0 if key in ('mean', 'std') else None
        if data.ndim == 2 and validity is not None:
            validity = validity[..., None]
        save_cube(Cube(data if data.ndim == 3 else data[..., None], meta, validity), directory / (key + '.npy'))
    drift = None if trend[0]['mean_dn'] is None or trend[-1]['mean_dn'] is None else trend[-1]['mean_dn'] - trend[0]['mean_dn']
    (directory / 'temporal.json').write_text(json.dumps({'frame_count': sequence.frame_count, 'source': source,
        'trend': trend, 'mean_drift_dn': drift, 'settings_check': settings_check,
        'interpretation': 'Temporal observations; incomplete settings evidence is explicit. Not spatial SD, temperature uncertainty or material diagnosis'},
        indent=2, default=str, allow_nan=False), encoding='utf-8')
    return directory


def compare_saved_frames(paths, rectangle=None, policy='diagnostic'):
    """Compare two saved ROI summaries; equal geometry does not establish registration."""
    from contextlib import ExitStack
    from hyperlab.analysis import quality_summary
    from hyperlab.io import load_cube

    paths = list(paths)
    if len(paths) != 2:
        raise ValueError('Select exactly two saved frames for comparison')
    paths = [Path(path).resolve(strict=True) for path in paths]
    if paths[0] == paths[1]:
        raise ValueError('Select two distinct saved frames for comparison')
    with ExitStack() as opened:
        cubes = [opened.enter_context(load_cube(path)) for path in paths]
        if any(cube.metadata['data_level'] not in {'raw_frame', 'derived_frame'} for cube in cubes):
            raise ValueError('Saved comparison requires raw_frame or derived_frame inputs')
        if any(cube.wavelengths is not None for cube in cubes):
            raise ValueError('Saved frame comparison does not accept a wavelength axis')
        if cubes[0].shape[:2] != cubes[1].shape[:2]:
            raise ValueError('Saved frames must have matching HW geometry')
        schemas = [(cube.shape[2], tuple(cube.metadata.get('channel_labels') or ())) for cube in cubes]
        if schemas[0] != schemas[1]:
            raise ValueError('Saved frames must have matching channel count and channel labels')
        h, w, _ = cubes[0].shape
        rectangle = (0, 0, w, h) if rectangle is None else tuple(rectangle)
        files = []
        for path, cube in zip(paths, cubes):
            summary = quality_summary(cube, rectangle, policy=policy)
            # Retain provenance once per source instead of duplicating the full
            # sidecar again inside the per-channel statistics metadata.
            summary['per_channel']['metadata'].pop('source_provenance', None)
            files.append({'path': str(path), 'data_level': cube.metadata['data_level'],
                          'acquisition_source': cube.metadata.get('acquisition_source', 'unknown'),
                          'summary': summary, 'source_provenance': dict(cube.metadata)})
        report = {'schema_version': 1, 'operation': 'saved_frame_comparison',
                  'paths': [str(path) for path in paths], 'rectangle': list(rectangle), 'policy': policy,
                  'geometry_hw': [h, w],
                  'channel_schema': {'count': schemas[0][0], 'labels': list(schemas[0][1]) or None},
                  'registration': 'NOT_VERIFIED', 'matching_settings': matching_settings([cube.metadata for cube in cubes]),
                  'files': files,
                  'interpretation': 'Separate ROI summaries in each saved image. Equal geometry and matching settings do not establish spatial registration, identical illumination, material cause or spectral calibration.'}

    def strict_value(value):
        if isinstance(value, np.ndarray):
            return strict_value(value.tolist())
        if isinstance(value, np.generic):
            return strict_value(value.item())
        if isinstance(value, dict):
            return {key: strict_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [strict_value(item) for item in value]
        if isinstance(value, float) and not np.isfinite(value):
            return None
        return value

    report = strict_value(report)
    json.dumps(report, allow_nan=False)  # Enforce the returned strict-JSON contract.
    return report
