"""Whitelisted support information; no personal paths, IDs or raw logs."""
import platform
from importlib.metadata import version, PackageNotFoundError
from . import __version__

_STATES = {'not_connected', 'disconnected', 'connecting', 'ready', 'streaming',
           'recording', 'stopping', 'error'}
_PHASES = {'open', 'configure', 'start', 'stop_restore', 'destroy', 'error_cleanup'}
_OUTCOMES = {'ENTERED', 'RETURNED', 'FAILED'}
_ERRORS = {'RuntimeError', 'ValueError', 'TypeError', 'TimeoutError', 'OSError',
           'PermissionError', 'FileNotFoundError', 'MemoryError', 'ImportError',
           'ModuleNotFoundError', 'GenericException', 'TimeoutException',
           'AccessException', 'InvalidArgumentException', 'LogicalErrorException'}


def _choice(value, allowed):
    return value if isinstance(value, str) and value in allowed else 'UNKNOWN'


def redacted_report(status=None):
    status = status or {}
    dependencies = {}
    for name in ('PySide6','pyqtgraph','numpy','matplotlib','harvesters','genicam'):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = 'NOT_INSTALLED'
    return {'schema_version':1,'hyperlab_version':__version__,'python':platform.python_version(),
            'os':platform.system(),'architecture':platform.machine(),'dependencies':dependencies,
            'device_state':_choice(status.get('state','not_connected'), _STATES),
            'phases':[{'phase':_choice(p.get('phase'), _PHASES),'status':_choice(p.get('status'), _OUTCOMES),
                       'exception_type':None if p.get('exception_type') is None else _choice(p.get('exception_type'), _ERRORS),
                       'deadline_exceeded':p.get('deadline_exceeded') if type(p.get('deadline_exceeded')) is bool else None}
                      for p in status.get('phases',[])],
            'excluded':'Raw frames, environment variables, paths, serials, full PnP IDs, raw exceptions and logs',
            'transmitted':False}
