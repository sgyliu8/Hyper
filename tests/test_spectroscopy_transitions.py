"""Synthetic source-transition and correction-status regressions; no hardware."""
from copy import deepcopy

import numpy as np
import pytest

from hyperlab.acquisition.sequence import SequenceWriter
from hyperlab.io import Cube, load_cube, save_cube
from hyperlab.spectroscopy.reflectance import reflectance_corrected
from hyperlab.spectroscopy.response import reconstruct_scan, save_response
from hyperlab.spectroscopy.workflow import process_spectroscopy
from hyperlab.ui.workbench import Workbench
from test_response import raw_fixture, response_fixture
from test_roi_source_transition import EpochSession


@pytest.fixture
def window(qtbot):
    result = Workbench()
    qtbot.addWidget(result)
    return result


@pytest.fixture
def signals(tmp_path):
    bundle = response_fixture(shape=(24, 32))
    sample, ds, _ = raw_fixture(bundle, np.full((24, 32, 2), 20.))
    white, dw, _ = raw_fixture(bundle, np.full((24, 32, 2), 100.), role='white')
    s, w = reconstruct_scan(sample, ds, bundle), reconstruct_scan(white, dw, bundle)
    paths = {name: save_cube(cube, tmp_path/(name+'.npy')) for name, cube in
             [('sample', sample), ('ds', ds), ('white', white), ('dw', dw), ('s', s), ('w', w)]}
    paths['response'] = save_response(bundle, tmp_path/'response')
    with reflectance_corrected(s, w) as result:
        paths['result'] = save_cube(result, tmp_path/'result.npy')
    return paths


def test_completed_product_detaches_time_sequence_and_retains_spectral_slider(window, qtbot, tmp_path, signals):
    with SequenceWriter(tmp_path/'old-series', (24, 32), np.dtype('uint16'), 3,
                        metadata={'acquisition_source': 'SYNTHETIC'}) as writer:
        for index in range(3):
            writer.append(np.full((24, 32), index+1, np.uint16),
                {'session_id': 'SYNTHETIC-transition', 'sequence': index, 'frame_id': index, 'valid': True,
                 'host_monotonic_ns': 100+index, 'pixel_format': 'Mono12',
                 'acquisition_source': 'SYNTHETIC', 'data_source': 'SYNTHETIC'})
    window.open_path(writer.path)
    qtbot.waitUntil(lambda: not window.task_busy)
    previous = window.sequence
    assert previous is not None
    window.spectroscopy_dialog()
    window._spectroscopy_dialog._completed({'completed': True, 'partial': False, 'product': str(signals['result'])})
    assert window.sequence is None and previous.data._mmap.closed
    assert window.band.maximum() == 1
    assert '500 nm' in window.axis_label.text()
    window.band.setValue(1)
    assert window.cube.metadata['data_level'] == 'reflectance_cube'
    assert '600 nm' in window.axis_label.text()
    np.testing.assert_allclose(window.cube.data, .2, atol=1e-13)


def test_completed_product_releases_previous_saved_cube(window, qtbot, signals):
    window.open_path(signals['s'])
    qtbot.waitUntil(lambda: not window.task_busy)
    previous = window.cube
    assert not previous.data._mmap.closed
    window.spectroscopy_dialog()
    window._spectroscopy_dialog._completed({'completed': True, 'product': str(signals['result'])})
    closed = previous.data._mmap.closed
    if not closed:
        previous.close()
    assert closed
    assert window.cube.metadata['data_level'] == 'reflectance_cube'


def test_start_preview_rejects_known_to_unknown_grid_roi_reuse(window):
    window.set_cube(Cube(np.ones((24, 32, 2)), {'data_level': 'spectral_cube',
        'wavelengths': [500, 600], 'wavelength_units': 'nm', 'data_source': 'SYNTHETIC',
        'spatial_grid': {'grid_id': 'SYNTHETIC-different-native-grid'}}))
    window.apply_roi_bounds(0, (2, 3, 8, 9))
    old_ids = {record['roi_id'] for record in window.regions()}
    window.session = EpochSession(channels=1)
    window.start_preview()
    assert window.cube is None
    window.tick()
    assert window.cube.metadata.get('spatial_grid') is None
    assert old_ids.isdisjoint(record['roi_id'] for record in window.regions())
    assert 'spatial grid changed' in window.message.text().lower()


def test_raw_input_check_defers_reference_pair_compatibility(window, qtbot, signals, tmp_path):
    with load_cube(signals['white']) as white:
        changed = deepcopy(white.metadata)
        changed['measurement_context']['illumination_id'] = 'SYNTHETIC different illumination'
        signals['white'] = save_cube(Cube(np.array(white.data), changed), tmp_path/'different-white.npy')
    window.spectroscopy_dialog()
    dialog = window._spectroscopy_dialog
    for field, key in [('response', 'response'), ('sample', 'sample'), ('dark_sample', 'ds'),
                       ('white', 'white'), ('dark_white', 'dw')]:
        dialog.fields[field].setText(str(signals[key]))
    dialog.check_inputs()
    qtbot.waitUntil(lambda: not window.task_busy)
    assert 'Recorded input compatibility passed' not in dialog.status.text()
    assert 'Reference compatibility is checked after reconstruction' in dialog.status.text()
    with pytest.raises(ValueError, match='illumination_id'):
        process_spectroscopy(signals['sample'], signals['white'], tmp_path/'rejected',
            response_path=signals['response'], dark_sample_path=signals['ds'], dark_white_path=signals['dw'])


def test_failed_report_preserves_primary_ownership_error_and_secondary_note(signals, tmp_path, monkeypatch):
    import hyperlab.spectroscopy.workflow as workflow
    original = workflow.atomic_json
    calls = []
    def failing_final(path, report):
        calls.append(report['phase'])
        if report['phase'] == 'FAILED':
            raise OSError('SYNTHETIC final receipt disk failure')
        return original(path, report)
    monkeypatch.setattr(workflow, 'atomic_json', failing_final)
    with pytest.raises(ValueError, match='correction_ownership') as failure:
        process_spectroscopy(signals['sample'], signals['white'], tmp_path/'failed')
    assert calls == ['REFERENCE_RATIO', 'FAILED']
    assert any('SYNTHETIC final receipt disk failure' in note for note in failure.value.__notes__)
