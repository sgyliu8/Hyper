"""Whitelisted support information; no personal paths, IDs or raw logs."""
import platform
from importlib.metadata import version, PackageNotFoundError
from . import __version__


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
            'device_state':status.get('state','not_connected'),
            'phases':[{'phase':p.get('phase'),'status':p.get('status'),
                       'exception_type':p.get('exception_type'),'deadline_exceeded':p.get('deadline_exceeded')}
                      for p in status.get('phases',[])],
            'excluded':'Raw frames, environment variables, paths, serials, full PnP IDs, raw exceptions and logs',
            'transmitted':False}
