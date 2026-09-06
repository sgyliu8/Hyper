"""Offline interaction tests using explicit synthetic scans and the actual workers."""
from copy import deepcopy

import numpy as np
import pytest
from PySide6 import QtWidgets as W

from hyperlab.io import Cube, make_synthetic_cube, save_cube
from hyperlab.spectroscopy.response import save_response
from hyperlab.ui.workbench import Workbench
from test_response import response_fixture, raw_fixture


@pytest.fixture
def window(qtbot):
    workbench = Workbench()
    qtbot.addWidget(workbench)
    return workbench


def open_dialog(window):
    window.spectroscopy_dialog()
    return window._spectroscopy_dialog


def test_process_actual_saved_scans_then_read_roi(window, qtbot, tmp_path):
    bundle = response_fixture(shape=(12, 16))
    white_values = np.full((12, 16, 2), 100.)
    expected = np.broadcast_to([.25, .75], white_values.shape).copy()
    expected[:, 8:] += .05
    sample, ds, _ = raw_fixture(bundle, expected * white_values)
    white, dw, _ = raw_fixture(bundle, white_values, role='white')
    dialog = open_dialog(window)
    dialog.fields['response'].setText(str(save_response(bundle, tmp_path/'response')))
    for key, cube in [('sample', sample), ('dark_sample', ds), ('white', white), ('dark_white', dw)]:
        path = tmp_path/(key+'.npy')
        save_cube(cube, path)
        dialog.fields[key].setText(str(path))
    dialog.process_saved()
    qtbot.waitUntil(lambda: not window.task_busy, timeout=10000)
    assert window.cube is not None, dialog.status.text()
    assert window.cube.metadata['data_level'] == 'reflectance_cube'
    assert window.cube.metadata['reflectance_kind'] == 'relative'
    assert window.cube.metadata['acquisition_source'] == 'SYNTHETIC'
    assert window.cube.metadata['spatial_grid'] == bundle['metadata']['spatial_grid']
    np.testing.assert_allclose(window.cube.data, expected, atol=1e-12)
    assert 'Product saved' in dialog.status.text()
    window.apply_roi_bounds(0, (0, 0, 16, 12))
    window.analyze_rois()
    qtbot.waitUntil(lambda: not window.task_busy)
    np.testing.assert_allclose(window.roi_results[0]['mean'], [.275, .775], atol=1e-12)
    assert window.plot_spec.xlabel == 'Wavelength (nm)'
    assert all(count == 192 for count in window.roi_results[0]['count'])


def test_failed_input_check_is_not_success_and_retains_display(window, qtbot, tmp_path):
    cube = make_synthetic_cube()
    window.set_cube(cube)
    path = tmp_path/'untyped.npy'
    save_cube(cube, path)
    dialog = open_dialog(window)
    dialog.input_kind.setCurrentIndex(1)
    for key in ('sample', 'white'):
        dialog.fields[key].setText(str(path))
    dialog.check_inputs()
    qtbot.waitUntil(lambda: not window.task_busy)
    assert dialog.status.text().startswith('Inputs are incompatible')
    assert 'correction_ownership' in dialog.details.toPlainText()
    assert window.cube is cube and not window.spectral_busy


def test_selector_and_response_are_independent_of_saved_camera_image(window):
    window.set_cube(Cube(np.ones((12, 16, 1), np.uint16),
        {'data_level': 'raw_frame', 'data_source': 'LIVE', 'pixel_format': 'BayerRG12'}))
    dialog = open_dialog(window)
    dialog._poll()
    assert 'Sensor: disconnected' in dialog.capabilities.text()
    assert 'Spectral selector: Not configured' in dialog.capabilities.text()
    assert 'Response: Not checked' in dialog.capabilities.text()
    assert not dialog.acquire_button.isEnabled()
    assert window.findChild(W.QPushButton, 'spectroscopy_setup') is not None


def test_spectroscopy_stop_stays_reachable_on_every_tab(window):
    window.spectral_busy = True
    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        window.update_controls()
        assert not window.stop_button.isHidden() and window.stop_button.isEnabled()
        assert window.stop_button.text() == '■ Stop spectroscopy'
    window.stop_button.click()
    assert window.spectral_stop.is_set()
    window.spectral_busy = False


def test_closing_busy_setup_cancels_worker_without_replacing_source(window, qtbot):
    cube = make_synthetic_cube()
    window.set_cube(cube)
    dialog = open_dialog(window)
    def job():
        assert window.spectral_stop.wait(3)
        return {'completed': False, 'partial': True}
    dialog._run(job, dialog._completed, 'Synthetic cancellation fixture')
    dialog.reject()
    assert window.spectral_stop.is_set() and dialog.isVisible()
    qtbot.waitUntil(lambda: not window.task_busy)
    assert window.cube is cube and not window.spectral_busy
    assert 'Partial acquisition retained' in dialog.status.text()


def test_grid_identity_changes_reset_roi_even_with_same_dimensions(window):
    first = make_synthetic_cube()
    first.metadata['spatial_grid'] = {'grid_id': 'synthetic-grid-a'}
    window.set_cube(first)
    window.apply_roi_bounds(0, (1, 2, 7, 9))
    same = Cube(first.data.copy(), deepcopy(first.metadata))
    window.set_cube(same)
    assert window.rectangles()[0] == (1, 2, 7, 9)
    changed = Cube(first.data.copy(), {**deepcopy(first.metadata), 'spatial_grid': {'grid_id': 'synthetic-grid-b'}})
    window.set_cube(changed)
    assert window.rectangles()[0] != (1, 2, 7, 9)


def test_reference_setup_persists_but_never_connects_hardware(window, qtbot, tmp_path):
    from hyperlab.ui.state import save_state
    dialog = open_dialog(window)
    response = str(tmp_path/'Unicode setup'/'response'/'manifest.json')
    dialog.fields['response'].setText(response)
    dialog.fields['white'].setText(str(tmp_path/'white.npy'))
    save_state(window)
    reopened = Workbench()
    qtbot.addWidget(reopened)
    restored = open_dialog(reopened)
    assert restored.fields['response'].text() == response
    assert restored.fields['white'].text() == str(tmp_path/'white.npy')
    assert reopened.session is None and reopened.spectral_adapter is None
    restored._poll()
    assert not restored.acquire_button.isEnabled()


def test_manual_response_change_invalidates_previous_check(window):
    dialog = open_dialog(window)
    window.response_summary = 'Previous response passed'
    dialog.fields['response'].setText('different-response/manifest.json')
    dialog._poll()
    assert window.response_summary is None
    assert 'Response: Not checked' in dialog.capabilities.text()


def test_reconstructed_residual_and_support_use_existing_map_panel(window, qtbot, tmp_path):
    from hyperlab.spectroscopy.response import reconstruct_scan
    mapping = np.zeros((12, 16), int)
    mapping[0, 0] = -1
    bundle = response_fixture(shape=(12, 16), region_map=mapping)
    sample, dark, _ = raw_fixture(bundle)
    path = tmp_path/'signal.npy'
    with reconstruct_scan(sample, dark, bundle, output_path=path):
        pass
    window.open_path(path)
    qtbot.waitUntil(lambda: not window.task_busy)
    window.analyze('reconstruction_residual')
    qtbot.waitUntil(lambda: not window.task_busy)
    assert window.product is not None, window.message.text()
    assert window.map_spec.title == 'Reconstruction residual RMS'
    assert window.map_spec.metadata['units'] == 'DN'
    assert not window.map_spec.valid_mask[0, 0]
    window.analyze('spectral_support')
    qtbot.waitUntil(lambda: not window.task_busy)
    assert window.map_spec.title == 'Valid spectral fraction'
    assert not window.map_spec.valid_mask[0, 0]
    assert np.all(window.map_spec.image[window.map_spec.valid_mask] == 1)
