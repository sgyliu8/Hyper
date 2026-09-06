"""Explicit isolated diagnostics; importing this module never opens a device."""
import multiprocessing
from pathlib import Path
import queue
import time
from .acquisition.sequence import atomic_json


def _worker(function, arguments, result_queue):
    try:
        result_queue.put({'status':'PASS', 'result':function(*arguments)})
    except Exception as exc:
        result_queue.put({'status':'FAIL', 'exception_type':type(exc).__name__, 'error':str(exc)})


class IsolatedDiagnostic:
    """Pollable process boundary, including for a native call that retains the GIL.

    Only this owned helper may be terminated at its deadline. That outcome does
    not confirm device release and must not be used as an automatic retry signal.
    """
    def __init__(self, function, arguments=(), *, timeout=30, receipt=None):
        if timeout <= 0:
            raise ValueError('Positive diagnostic deadline required')
        context = multiprocessing.get_context('spawn')
        self.queue = context.Queue(maxsize=1)
        self.process = context.Process(target=_worker, args=(function, arguments, self.queue), daemon=True)
        self.deadline = time.monotonic()+timeout
        self.receipt = Path(receipt) if receipt else None
        self.result = None
        self.process.start()

    def poll(self):
        if self.result is not None:
            return self.result
        try:
            self.result = self.queue.get_nowait()
        except queue.Empty:
            if time.monotonic() < self.deadline:
                return None
            was_alive = self.process.is_alive()
            if was_alive:
                self.process.terminate()
            self.result = {'status':'TIMEOUT', 'owned_helper_terminated':was_alive,
                           'device_release':'NOT_CONFIRMED', 'retry_permitted':False,
                           'error':'Diagnostic deadline elapsed; terminating a process does not prove device cleanup'}
        self.process.join(timeout=.1)
        self.queue.close()
        if self.receipt:
            self.receipt.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(self.receipt, self.result)
        return self.result


def _node_export(cti, serial, directory):
    from .adapters.gentl import GenTLBackend
    backend = GenTLBackend(cti, serial)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    events = []
    def phase(name, operation):
        event = {'phase':name, 'entered_ns':time.monotonic_ns(), 'status':'ENTERED'}
        events.append(event)
        atomic_json(directory/'phases.json', events)
        try:
            result = operation()
            event['status'] = 'RETURNED'
            return result
        except Exception as error:
            event.update(status='FAILED', error=str(error), exception_type=type(error).__name__)
            raise
        finally:
            event['exited_ns'] = time.monotonic_ns()
            atomic_json(directory/'phases.json', events)
    primary = None
    try:
        phase('open', backend.open)
        nodes = phase('reviewed_node_export', lambda: backend.describe_nodes(all_nodes=True))
        atomic_json(directory/'nodes.json', {'nodes':nodes, 'xml':'NOT_EXPORTED',
                    'commands_executed':False, 'selectors_changed':False})
    except Exception as error:
        primary = error
    finally:
        try:
            phase('close', backend.close)
        except Exception as cleanup_error:
            if primary is None:
                primary = cleanup_error
            else:
                primary.add_note(f'Closing diagnostic also failed: {cleanup_error}')
        atomic_json(directory/'cleanup.json', backend.cleanup)
    if primary:
        raise primary
    return {'directory':str(directory), 'device_release': 'CONFIRMED' if any(
            e['step']=='destroy' and e['succeeded'] for e in backend.cleanup) else 'NOT_CONFIRMED'}


def start_node_export(cti, serial, directory, *, hardware=False, owner_released=False, timeout=30):
    if not hardware or not owner_released:
        raise ValueError('Explicit hardware diagnostic and confirmed release of the existing camera owner are required')
    return IsolatedDiagnostic(_node_export, (cti, serial, str(directory)), timeout=timeout,
                              receipt=Path(directory).parent/(Path(directory).name+'-supervisor.json'))


def _offline_delay(seconds, entered=None):
    """Native sleep retaining the child GIL; no device or driver is involved."""
    import ctypes
    import sys
    if entered:
        Path(entered).write_text('ENTERED_NATIVE_WAIT',encoding='ascii')
    if sys.platform == 'win32':
        wait = ctypes.PyDLL('kernel32').Sleep
        wait.argtypes, wait.restype = [ctypes.c_ulong], None
        wait(int(seconds*1000))
    else:
        wait = ctypes.PyDLL(None).sleep
        wait.argtypes, wait.restype = [ctypes.c_uint], ctypes.c_uint
        wait(int(seconds))
    return {'hardware':False}
