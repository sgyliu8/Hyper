"""The recorder's retained/durable lifecycle remains distinct from camera state."""
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtWidgets as W

from hyperlab.acquisition.frame import Frame
from hyperlab.ui.workbench import Workbench


@pytest.fixture
def window(qtbot):
    result=Workbench(); qtbot.addWidget(result); result.timer.stop()
    return result


def receipt(phase='persisting', **updates):
    return dict({'recording_mode':'ram_burst','phase':phase,'admitted_frames':300,'max_frames':300,
        'copied_frames':0,'data_fsynced_frames':0,'durable_frames':0,'readable_frames':None,
        'unpersisted_frames':300,'volatile_frames':300,'retained_frames':300,'retained_bytes':60000,
        'rejected_frames':0,'can_retry':False,'can_abandon':False,'done':False,'completed':False,
        'partial':True,'save_reopen_verified':False,'error':None}, **updates)


def connect_fake(window, recording, *, state='ready', pending_close=None):
    status={'state':state,'recording':recording,'closed':False,'pending_close':pending_close}
    calls=[]
    session=SimpleNamespace(state=state,status=lambda:status,
        retry_recording=lambda path:calls.append(('retry',path)),
        abandon_recording=lambda:calls.append(('abandon',None)),
        close=lambda **kw:calls.append(('close',None)))
    window.session=session; window.last_status=status
    return session,status,calls


def test_acquired_target_with_zero_durable_does_not_complete_or_offer_restart(window):
    rec=receipt()
    connect_fake(window,rec)
    window.update_recording_result(rec); window.update_controls()
    text=window.recording_label.text()
    assert 'Persisting' in text and 'admitted 300 / 300' in text and 'durable 0' in text
    assert 'reopened not checked' in text and 'COMPLETE' not in text
    assert not window.preview_button.isEnabled() and not window.record_button.isEnabled()
    assert not window.apply_button.isEnabled() and not window.recording_recovery.isVisibleTo(window)
    window.start_preview()
    assert 'Finish burst persistence' in window.message.text()
    window.session=None


def test_recovery_close_keeps_arrays_and_requires_explicit_abandonment(window,monkeypatch,tmp_path):
    rec=receipt('recovery_required',can_retry=True,can_abandon=True,error='Synthetic disk failure')
    session,status,calls=connect_fake(window,rec,pending_close='recovery_required')
    window.update_recording_result(rec); window.update_controls()
    assert window.retry_recording_button.isEnabled() and window.abandon_recording_button.isEnabled()
    event=QtGui.QCloseEvent(); window.closeEvent(event)
    assert not event.isAccepted() and window.closing and calls == [('close',None)]
    assert rec['retained_frames'] == 300
    monkeypatch.setattr(W.QMessageBox,'question',lambda *a,**kw:W.QMessageBox.StandardButton.Cancel)
    window.abandon_recording(); assert len(calls) == 1
    window.output_dir=tmp_path
    window.retry_recording()
    assert calls[-1][0] == 'retry' and calls[-1][1].parent == tmp_path and not calls[-1][1].exists()
    monkeypatch.setattr(W.QMessageBox,'question',lambda *a,**kw:W.QMessageBox.StandardButton.Yes)
    window.abandon_recording(); assert calls[-1] == ('abandon',None)
    rec['can_retry']=rec['can_abandon']=False
    prior=list(calls); window.retry_recording(); window.abandon_recording()
    assert calls == prior
    window.closing=False; window.session=None


def test_complete_label_needs_verified_terminal_receipt(window):
    rec=receipt('complete',done=True,completed=True,partial=False,save_reopen_verified=True,
        durable_frames=300,readable_frames=300,retained_frames=0,unpersisted_frames=0,volatile_frames=0)
    window.update_recording_result(rec)
    assert 'COMPLETE' in window.recording_label.text() and 'reopened 300' in window.recording_label.text()
    bad=deepcopy(rec); bad['save_reopen_verified']=False
    window.update_recording_result(bad)
    assert 'inconsistent completion receipt' in window.recording_label.text()
    assert 'COMPLETE' not in window.recording_label.text()
    recovery=receipt('recovery_required',durable_frames=300,unpersisted_frames=0,
                     readable_frames=None,can_retry=True,can_abandon=True)
    window.update_recording_result(recovery)
    assert 'Recovery required' in window.recording_label.text() and 'retained in RAM 300' in window.recording_label.text()
    assert window.abandon_recording_button.isEnabled() and 'COMPLETE' not in window.recording_label.text()


def test_modal_preflight_uses_shared_budget_and_preserves_requested_count(window,monkeypatch):
    import hyperlab.acquisition.sequence as sequence
    frame=Frame(np.arange(30,dtype=np.uint16).reshape(5,6),{'session_id':'synthetic','sequence':1})
    calls=[]
    window.session=SimpleNamespace(state='streaming',status=lambda:{},latest_frame=lambda:frame,
        start_recording=lambda *args,**kwargs:calls.append((args,kwargs)))
    monkeypatch.setattr(sequence,'available_memory_bytes',lambda:1)
    def inspect():
        dialog=window.findChild(W.QDialog)
        mode=dialog.findChild(W.QComboBox,'recording_mode')
        count=dialog.findChild(W.QSpinBox,'recording_frames')
        mode.setCurrentIndex(mode.findData('ram_burst'))
        budget=dialog.findChild(W.QLabel,'recording_budget')
        assert count.value() == 300
        assert '300 requested frames' in budget.text() and 'RAM required' in budget.text()
        assert 'requested frame count unchanged' in budget.text()
        assert not dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.StandardButton.Ok).isEnabled()
        mode.setCurrentIndex(mode.findData('continuous'))
        assert 'Preview continues' in budget.text()
        assert dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.StandardButton.Ok).isEnabled()
        dialog.accept()
    QtCore.QTimer.singleShot(0,inspect)
    window.record_dialog()
    assert len(calls) == 1 and calls[0][0][1] == 300 and calls[0][1]['recording_mode'] == 'continuous'
    window.session=None
