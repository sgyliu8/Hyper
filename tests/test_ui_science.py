"""Offline scientific display/export regressions; no camera or native UI tools."""
import json

import numpy as np
import pytest

from hyperlab.analysis import export_product, roi_statistics
from hyperlab.io import Cube, load_cube
from hyperlab.ui.view import bayer_cell_rgb
from hyperlab.ui.workbench import Workbench


@pytest.fixture
def window(qtbot, tmp_path):
    workbench = Workbench()
    workbench.output_dir = tmp_path
    qtbot.addWidget(workbench)
    return workbench


def test_cfa_display_does_not_hide_raw_saturation(window):
    raw = np.array([[10, 4095], [10, 10]], np.uint16)
    meta = {'data_level': 'raw_frame', 'pixel_format': 'BayerRG12', 'effective_bits': 12,
            'readback_settings': {'ReverseX': False, 'ReverseY': False, 'OffsetX': 0, 'OffsetY': 0}}
    window.set_cube(Cube(raw[..., None], meta))
    window.update_chart(bayer_cell_rgb(raw, meta))
    assert '25.00%' in window.quality_label.text()
    assert '1/4 eligible' in window.quality_label.text()


def test_raw_quality_uses_quantitative_masks_and_reports_denominator(window):
    raw = np.array([[[10], [4095]], [[0], [20]]], np.uint16)
    cube = Cube(raw, {'data_level': 'raw_frame', 'effective_bits': 12, 'data_ignore_value': 0},
                np.array([[True, True], [True, False]]))
    window.set_cube(cube)
    window.policy.setCurrentIndex(1)
    window.update_chart(raw[..., 0])
    text = window.quality_label.text()
    assert '50.00%' in text and '1/2 eligible' in text
    assert 'quantitative mean 10.00' in text


def roi_fixture(window):
    cube = Cube(np.array([[[1., 1.], [1., 100.]]]), valid_mask=np.array([[[True, False], [True, True]]]))
    window.set_cube(cube)
    return cube, [(0, 0, 1, 1), (1, 0, 2, 1)]


def test_roi_shape_curves_use_common_finite_features(window):
    cube, rects = roi_fixture(window)
    window.shape_normalize.setChecked(True)
    window.show_rois([roi_statistics(cube, rect) for rect in rects])
    # Phase 3 keeps amplitude and the normalized branch visible together.
    for curve in window.shape_curves:
        _, values = curve.getData()
        assert values[0] == 1 and np.isnan(values[1])


def test_zero_norm_shape_is_unavailable_without_overwriting_raw_means(window):
    cube = Cube(np.array([[[0., 0.], [1., 2.]]]))
    window.set_cube(cube)
    window.shape_normalize.setChecked(True)
    results = [roi_statistics(cube, rect) for rect in ((0, 0, 1, 1), (1, 0, 2, 1))]
    window.show_rois(results)
    assert np.isnan(window.shape_curves[0].getData()[1]).all()
    np.testing.assert_array_equal(window.curves[0].getData()[1], [0, 0])
    np.testing.assert_array_equal(results[0]['mean'], [0, 0])
    assert 'unavailable' in window.message.text()


def test_roi_export_keeps_amplitude_and_shared_shape_provenance(window, monkeypatch):
    _, rects = roi_fixture(window)
    window.shape_normalize.setChecked(True)
    monkeypatch.setattr(window, 'rectangles', lambda: rects)
    monkeypatch.setattr(window, 'background', lambda run, done, message: done(run()))
    window.export_rois()
    directory = next(window.output_dir.glob('roi_*'))
    comparison = json.loads((directory / 'comparison.json').read_text())
    branch = comparison['shape_branch']
    assert branch['feature_indices'] == [0]
    assert branch['normalized_means'] == [[1, None], [1, None]]
    # Raw amplitudes remain independently available, including ROI B channel 1.
    assert '100.0' in (directory / 'roi_2.csv').read_text()
    sidecar = json.loads((directory / 'roi_2.csv.json').read_text())
    assert sidecar['metadata']['shape_comparison']['feature_indices'] == [0]


def test_sam_captures_reference_roi_before_worker_and_keeps_it_on_export(window, monkeypatch):
    cube = Cube(np.arange(48, dtype=float).reshape(4, 4, 3) + 1)
    window.set_cube(cube)
    rect = (0, 0, 2, 2)
    monkeypatch.setattr(window, 'rectangles', lambda: [rect, (2, 2, 4, 4)])
    window.roi_names[0].setText('Reference patch')
    pending = {}
    monkeypatch.setattr(window, 'background', lambda run, done, message: pending.update(run=run, done=done))
    window.analyze('spectral_angle')
    window.roi_names[0].setText('Renamed later')
    result = pending['run']()
    assert result['metadata']['reference_roi']['name'] == 'Reference patch'
    assert result['metadata']['reference_roi']['rect'] == list(rect)
    path = export_product(result, window.output_dir / 'angle.npy', cube)
    with load_cube(path) as reopened:
        assert reopened.metadata['reference_roi']['name'] == 'Reference patch'
