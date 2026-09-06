"""A separate share preview keeps the internal scientific result intact."""
from copy import deepcopy
import json

import numpy as np
from PySide6 import QtWidgets as W

from hyperlab.io import Cube
from hyperlab.ui.workbench import Workbench


def test_share_preview_then_save_preserves_internal_result(qtbot, tmp_path):
    window=Workbench(); qtbot.addWidget(window)
    cube=Cube(np.arange(432,dtype=float).reshape(12,12,3)+1,
        {'data_level':'raw_frame','data_source':'SYNTHETIC','units':'DN','channel_labels':['R','G','B']})
    window.set_cube(cube)
    window.roi_names[0].setText('PRIVATE_NAME_SENTINEL')
    window.roi_timer.stop(); window.analyze('normalized_difference')
    qtbot.waitUntil(lambda:not window.task_busy,timeout=10000)
    original=window.map_spec
    before=deepcopy(original.record()); pixels=original.image.copy()
    window.output_dir=tmp_path
    window.share_figure()
    qtbot.waitUntil(lambda:not window.task_busy,timeout=10000)
    dialog=window._share_dialog
    assert dialog.isVisible()
    selector=dialog.findChild(W.QComboBox)
    selector.setCurrentText('Derived map')
    qtbot.waitUntil(lambda:not window.task_busy,timeout=10000)
    assert any('not anonymous' in item.text() for item in dialog.findChildren(W.QLabel))
    buttons=dialog.findChild(W.QDialogButtonBox)
    assert buttons.button(W.QDialogButtonBox.StandardButton.Save).isEnabled()
    assert any(item.pixmap() is not None and not item.pixmap().isNull() for item in dialog.findChildren(W.QLabel))
    assert not list(tmp_path.glob('share_*'))
    buttons.button(W.QDialogButtonBox.StandardButton.Save).click()
    qtbot.waitUntil(lambda:not window.task_busy,timeout=10000)
    outputs=list(tmp_path.glob('share_*'))
    assert len(outputs)==1,window.message.text()
    saved=json.loads((outputs[0]/'plot.json').read_text())
    assert 'PRIVATE_NAME_SENTINEL' not in json.dumps(saved)
    assert original.record()==before
    np.testing.assert_equal(original.image,pixels)
    assert saved['metadata']['semantic_center']==original.metadata['semantic_center']
    assert saved['limits']==list(original.limits)
    assert 'saved locally' in window.message.text()
