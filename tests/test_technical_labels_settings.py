"""Actual stored sequence schemas, including explicit-null sensor labels."""
from copy import deepcopy
import csv
import json

import numpy as np
import pytest

from hyperlab.acquisition.sequence import Sequence, SequenceWriter
from hyperlab.analysis.capabilities import capabilities
from hyperlab.io import Cube
from hyperlab.plots import COLORS, export_figure_bundle, recorded_roi_plot


def metadata(fmt='RGB8'):
    color = fmt in ('RGB8', 'BGR8')
    return {'pixel_format': fmt, 'channel_labels': list(fmt[:3]) if color else None,
            'data_level': 'raw_frame', 'data_source': 'SYNTHETIC', 'units': 'DN',
            'model': 'synthetic camera', 'serial': 'synthetic-only', 'valid': True,
            'effective_bits': 8 if color else 12,
            'readback_settings': {'PixelFormat': fmt, 'ExposureTime': 1000, 'Gain': 0,
                'ExposureAuto': 'Off', 'GainAuto': 'Off', 'BalanceWhiteAuto': 'Off',
                'GammaEnable': False, 'Gamma': 1, 'LUTEnable': False,
                'BlackLevel': 0, 'BlackLevelAuto': 'Off'}}


def sequence_file(tmp_path, records, fmt='RGB8', expected=3):
    color = fmt in ('RGB8', 'BGR8')
    shape, dtype = ((2, 3, 3), np.dtype('uint8')) if color else ((2, 3), np.dtype('uint16'))
    with SequenceWriter(tmp_path/'sequence', shape, dtype, expected,
                        metadata={'data_source': 'SYNTHETIC', 'acquisition_source': 'SYNTHETIC'}) as writer:
        for index, record in enumerate(records):
            if color:
                data = np.broadcast_to([10+index, 20-index, 5], shape).astype(dtype).copy()
            else:
                data = np.array([[1+index, 2+index, 4095], [4+index, 0, 6+index]], dtype=dtype)
                record = {**record, 'data_ignore_value': 0}
            writer.append(data, {**record, 'valid': True, 'session_id': 'fixture', 'stream_epoch': 1,
                                'sequence': index, 'host_monotonic_ns': (100+index)*1_000_000_000})
    return writer.path


@pytest.mark.parametrize('fmt', ['BayerRG12', 'Mono12'])
@pytest.mark.parametrize('labels_present', [True, False])
def test_sensor_trace_null_and_missing_labels_keep_counts_clock_partial_and_source(tmp_path, fmt, labels_present):
    records = [metadata(fmt) for _ in range(2)]
    if not labels_present:
        for item in records:
            item.pop('channel_labels')
    path = sequence_file(tmp_path, records, fmt)
    before = path.with_suffix('.npy.json').read_bytes()
    with Sequence(path) as sequence:
        spec = recorded_roi_plot(sequence, [(0, 0, 3, 2)], ['Region'], COLORS, policy='quantitative')
        assert spec.metadata['channel_label'] == 'Sensor plane'
        np.testing.assert_equal(spec.series[0]['x'], [0, 1])
        np.testing.assert_equal(spec.series[0]['y'], [3.25, 4.25])
        np.testing.assert_equal(spec.series[0]['valid_counts'], [4, 4])
        assert spec.metadata['frame_count'] == 2 and spec.metadata['recording']['expected_frames'] == 3
        assert spec.metadata['recording']['partial'] and not spec.metadata['recording']['completed']
        assert spec.metadata['settings_check']['status'] == 'MATCH'
        frame = sequence.frame(0)
        cube = Cube(frame.data[..., None], dict(frame.metadata))
        assert cube.metadata.get('channel_labels') is None
        assert capabilities(cube)['axis_kind'] == 'sensor_plane'
    assert path.with_suffix('.npy.json').read_bytes() == before


@pytest.mark.parametrize('fmt,labels', [('RGB8', ['R', 'G', 'B']), ('BGR8', ['B', 'G', 'R'])])
def test_named_trace_uses_selected_stored_channel(tmp_path, fmt, labels):
    path = sequence_file(tmp_path, [metadata(fmt), metadata(fmt)], fmt)
    with Sequence(path) as sequence:
        spec = recorded_roi_plot(sequence, [(0, 0, 3, 2)], ['Region'], COLORS, band=1)
    assert spec.metadata['channel_label'] == labels[1]
    np.testing.assert_equal(spec.series[0]['y'], [20, 19])
    np.testing.assert_equal(spec.series[0]['valid_counts'], [6, 6])


@pytest.mark.parametrize('labels', [['R', 'G'], ['R', 'G', 'B', 'A']])
def test_wrong_label_lengths_remain_rejected(tmp_path, labels):
    records = [metadata(), metadata()]
    for item in records:
        item['channel_labels'] = labels
    path = sequence_file(tmp_path, records)
    with Sequence(path) as sequence, pytest.raises(ValueError, match='matching labels|channel labels'):
        recorded_roi_plot(sequence, [(0, 0, 3, 2)], ['Region'], COLORS)


def test_display_labels_do_not_change_signal_domain():
    from hyperlab.io.labels import display_labels
    raw = {'data_level': 'raw_frame', 'pixel_format': 'BayerRG12', 'channel_labels': None}
    before = deepcopy(raw)
    assert display_labels(raw, 1) == ['Sensor plane']
    assert raw == before
    assert display_labels({'data_level': 'raw_scan'}, 2) == ['State 0', 'State 1']
    assert display_labels({'data_level': 'raw_frame'}, 3) == ['Feature 0', 'Feature 1', 'Feature 2']
    assert display_labels({'wavelengths': [0.5, 0.6], 'wavelength_units': 'um'}, 2) == ['0.5 um', '0.6 um']
    for labels in ('RGB', ['R', '', 'B'], ['R', 1, 'B']):
        with pytest.raises(ValueError, match='channel labels'):
            display_labels({'channel_labels': labels}, 3)


@pytest.mark.parametrize('case,status', [('fixed', 'MATCH'), ('sparse', 'UNKNOWN'), ('empty', 'UNKNOWN'),
    ('auto', 'UNKNOWN'), ('chunk-change', 'MISMATCH'), ('chunk-same', 'MATCH')])
def test_trace_reuses_setting_evidence(tmp_path, case, status):
    records = [metadata(), metadata()]
    for index, item in enumerate(records):
        if case == 'sparse':
            item['readback_settings'] = {'ExposureTime': 1000}
        elif case == 'empty':
            item['readback_settings'], item['current_settings'] = {}, {}
        elif case == 'auto':
            item['readback_settings']['ExposureAuto'] = 'Continuous'
        elif case == 'chunk-change':
            item['chunk_settings'] = {'ChunkExposureTime': 1000+index*1000}
        elif case == 'chunk-same':
            item['chunk_settings'] = {'ChunkExposureTime': 1500}
            item['readback_settings']['ExposureTime'] = 1000+index*1000
    path = sequence_file(tmp_path, records)
    with Sequence(path) as sequence:
        spec = recorded_roi_plot(sequence, [(0, 0, 3, 2)], ['Region'], COLORS)
    assert spec.metadata['settings_check']['status'] == status
    assert status in spec.caption
    assert spec.metadata['pooling_qualification'] == ('settings consistent only' if status == 'MATCH' else 'not qualified')
    np.testing.assert_equal(spec.series[0]['y'], [10, 11])  # Unknown/changed settings do not hide raw observations.
    if case.startswith('chunk-'):
        assert spec.metadata['frame_setting_sources'][0]['ExposureTime'] == 'chunk_settings.ChunkExposureTime'
    if case == 'chunk-same':
        assert [item['ExposureTime'] for item in spec.metadata['frame_settings']] == [1500, 1500]


def test_single_record_is_inspectable_without_consistency_claim(tmp_path):
    path = sequence_file(tmp_path, [metadata()])
    with Sequence(path) as sequence:
        spec = recorded_roi_plot(sequence, [(0, 0, 3, 2)], ['Region'], COLORS)
    assert spec.metadata['settings_check']['status'] == 'UNKNOWN'
    assert len(spec.series[0]['y']) == 1


def test_durable_prefix_only_controls_trace_clock(tmp_path):
    path = sequence_file(tmp_path, [metadata(), metadata()])
    sidecar = path.with_suffix('.npy.json')
    record = json.loads(sidecar.read_text())
    record['frames'].append({'valid': True, 'session_id': 'unwritten', 'host_monotonic_ns': None})
    sidecar.write_text(json.dumps(record), encoding='utf-8')
    with Sequence(path) as sequence:
        spec = recorded_roi_plot(sequence, [(0, 0, 3, 2)], ['Region'], COLORS)
    assert 'elapsed time (s)' in spec.xlabel
    np.testing.assert_equal(spec.series[0]['x'], [0, 1])


def test_trace_export_distinguishes_frame_sample_and_signal_channel(tmp_path):
    path = sequence_file(tmp_path, [metadata('Mono12'), metadata('Mono12')], 'Mono12')
    with Sequence(path) as sequence:
        spec = recorded_roi_plot(sequence, [(0, 0, 3, 2)], ['Region'], COLORS, policy='quantitative')
    export_figure_bundle(spec, tmp_path/'export')
    with (tmp_path/'export'/'series.csv').open(encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    assert [int(row['sample_index']) for row in rows] == [0, 1]
    assert [int(row['feature_index']) for row in rows] == [0, 0]
    assert [int(row['channel_index']) for row in rows] == [0, 0]
    assert [row['channel_label'] for row in rows] == ['Sensor plane', 'Sensor plane']
    assert [float(row['y']) for row in rows] == [3.25, 4.25]
    assert [int(row['used_count']) for row in rows] == [4, 4]
    assert [row['frame_identity'] for row in rows] == ['fixture:1:0', 'fixture:1:1']
    saved = json.loads((tmp_path/'export'/'plot.json').read_text())
    assert saved['metadata']['settings_check']['status'] == 'MATCH'
    assert saved['metadata']['recording']['partial']


def test_trace_rejects_a_changed_stored_channel_identity(tmp_path):
    records = [metadata(), metadata('BGR8')]
    path = sequence_file(tmp_path, records)
    with Sequence(path) as sequence, pytest.raises(ValueError, match='channel identity changed'):
        recorded_roi_plot(sequence, [(0, 0, 3, 2)], ['Region'], COLORS, band=0)


def test_trace_unknown_frame_cannot_hide_known_setting_change(tmp_path):
    records = [metadata() for _ in range(3)]
    records[0]['readback_settings']['ExposureTime'] = 'unknown'
    records[2]['readback_settings']['ExposureTime'] = 2000
    path = sequence_file(tmp_path, records, expected=3)
    with Sequence(path) as sequence:
        spec = recorded_roi_plot(sequence, [(0, 0, 3, 2)], ['Region'], COLORS)
    check = spec.metadata['settings_check']
    assert check['status'] == 'MISMATCH'
    assert 'ExposureTime' in check['unknown'] and 'ExposureTime' in check['mismatches']
    assert spec.metadata['pooling_qualification'] == 'not qualified'


def test_empty_recording_and_boolean_channel_have_no_trace(tmp_path):
    path = sequence_file(tmp_path, [])
    with Sequence(path) as sequence, pytest.raises(ValueError, match='persisted frame'):
        recorded_roi_plot(sequence, [(0, 0, 3, 2)], ['Region'], COLORS)
    path = sequence_file(tmp_path/'nonempty', [metadata()])
    with Sequence(path) as sequence, pytest.raises(ValueError, match='stored feature index'):
        recorded_roi_plot(sequence, [(0, 0, 3, 2)], ['Region'], COLORS, band=True)


def test_sequence_without_acquisition_identity_keeps_explicit_sample_index(tmp_path):
    with SequenceWriter(tmp_path/'anonymous', (2, 3), np.dtype('uint8'), 2,
                        metadata={'data_source': 'SYNTHETIC', 'channel_labels': None}) as writer:
        writer.append(np.ones((2, 3), np.uint8), {'valid': True})
        writer.append(np.full((2, 3), 2, np.uint8), {'valid': True})
    with Sequence(writer.path) as sequence:
        spec = recorded_roi_plot(sequence, [(0, 0, 3, 2)], ['Region'], COLORS)
    assert 'frame index' in spec.xlabel
    assert spec.series[0]['frame_identities'] == [None, None]
    assert spec.series[0]['sample_indices'] == [0, 1]
    assert spec.metadata['settings_check']['status'] == 'UNKNOWN'
