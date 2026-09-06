"""Terminal recording receipts stay visible independently of camera/view state."""
from copy import deepcopy
import time

import pytest

from hyperlab.ui.workbench import Workbench


class ReceiptSession:
    def __init__(self):
        self.state = 'streaming'
        self.recording = None
        self.events = []
        self.closed = False

    def status(self):
        return {'state':self.state, 'closed':self.closed, 'recording':self.recording}

    def poll_events(self):
        events, self.events = self.events, []
        return events

    def latest_frame(self):
        return None

    def stop_preview(self):
        self.state = 'ready'
        self.events.append({'kind':'state', 'state':'ready'})

    def close(self, wait=False):
        self.closed = True


@pytest.fixture
def window(qtbot):
    value = Workbench()
    qtbot.addWidget(value)
    value.show()
    value.session = ReceiptSession()
    value.last_log = time.monotonic()
    return value


def partial_receipt():
    return {'done':True, 'partial':True, 'completed':False,
        'written_frames':96, 'accepted_frames':96, 'max_frames':300,
        'explicitly_failed_frames':0, 'rejected_frames':1, 'overflow':1,
        'error':'Writer queue overflow: recording stopped; no silent frame drop',
        'save_reopen_verified':True, 'path':'sequence-partial/sequence.npy'}


def test_partial_receipt_survives_later_state_message_tabs_and_stop(window):
    receipt = partial_receipt()
    before = deepcopy(receipt)
    window.session.recording = receipt
    window.session.events = [dict(receipt, kind='recording'), {'kind':'state','state':'streaming'}]
    window.tick()
    assert window.message.text() == 'Device state: streaming'
    assert window.device_label.text() == 'Camera: Previewing'
    assert 'PARTIAL' in window.recording_label.text()
    assert '96 / 300 frames written' in window.recording_label.text()
    assert receipt['error'] in window.recording_label.text()
    assert 'reopen verified' in window.recording_label.text()
    for tab in (0, 1):
        window.tabs.setCurrentIndex(tab)
        assert window.recording_label.isVisible()
    window.stop_preview(); window.tick()
    assert window.session.state == 'ready'
    assert 'PARTIAL' in window.recording_label.text() and window.recording_label.isVisible()
    assert window.device_label.text() == 'Camera: Connected · idle'
    assert receipt == before


def test_status_only_receipt_replaces_previous_result_after_next_recording(window):
    window.last_status = {'state':'streaming','recording':partial_receipt()}
    window.update_status()
    previous = window.recording_label.text()
    window.last_status = {'state':'recording','recording':{'done':False,'written_frames':4,'max_frames':300}}
    window.update_status()
    assert window.recording_label.text() == previous
    complete = dict(partial_receipt(), path='sequence-complete/sequence.npy', partial=False, completed=True,
                    written_frames=300, accepted_frames=300, rejected_frames=0, overflow=0, error=None)
    window.last_status = {'state':'streaming','recording':complete}
    window.update_status()
    assert 'COMPLETE' in window.recording_label.text() and 'PARTIAL' not in window.recording_label.text()
    assert '300 / 300 frames written' in window.recording_label.text()
    assert 'overflow' not in window.recording_label.text()
    assert 'sequence-complete' in window.recording_label.toolTip()


def test_receipt_absence_and_unknown_reason_do_not_invent_success(window):
    window.last_status = {'state':'streaming','recording':None}
    window.update_status()
    assert window.recording_label.isHidden()
    window.last_status['recording'] = dict(partial_receipt(), error=None, save_reopen_verified=False)
    window.update_status()
    assert 'PARTIAL' in window.recording_label.text()
    assert 'Reason not recorded' in window.recording_label.text()
    assert 'reopen not verified' in window.recording_label.text()
    assert 'COMPLETE' not in window.recording_label.text()
