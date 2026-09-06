"""Categorical right tasks honor the same points/connected PlotSpec as export."""
import numpy as np
import pytest

from hyperlab.analysis import roi_comparison
from hyperlab.io import Cube
from hyperlab.plots import COLORS, roi_plot, roi_transform_plot, source_identity
from hyperlab.ui.workbench import Workbench


@pytest.mark.parametrize('task', ['residual', 'shape'])
@pytest.mark.parametrize('style', ['points', 'connected'])
def test_right_categorical_plot_uses_requested_connection_style(qtbot, task, style):
    window = Workbench()
    qtbot.addWidget(window)
    cube = Cube(np.array([[[10.,20.,30.],[20.,30.,50.]]]),
                {'data_level':'raw_frame','units':'DN','data_source':'SYNTHETIC',
                 'channel_labels':['R','G','B']})
    statistics = roi_comparison(cube, [(0,0,1,1),(1,0,2,1)])
    amplitude = roi_plot(statistics, ['Reference','Target'], COLORS, source=source_identity(cube),
                         categorical_style=style)
    transformed = roi_transform_plot(amplitude, task, reference=statistics[0]['mean'])
    window.draw_right_plot(transformed)
    curves = window.shape_chart.listDataItems()
    assert len(curves) == len(transformed.series)
    assert transformed.metadata['categorical_style'] == style
    for actual, expected in zip(curves, transformed.series):
        assert (actual.opts['pen'] is None) == (style == 'points')
        assert actual.opts['symbol'] == 'o'
        from pyqtgraph import mkColor
        assert mkColor(actual.opts['symbolBrush']).name() == mkColor(expected['color']).name()
        np.testing.assert_equal(actual.getData()[0], expected['x'])
        np.testing.assert_equal(actual.getData()[1], expected['y'])
