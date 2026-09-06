"""Per-user configuration and explicit data workspace, independent of CWD."""
import json
import os
from pathlib import Path
import tempfile
from PySide6.QtCore import QStandardPaths


def config_directory():
    override = os.environ.get('HYPERLAB_CONFIG_DIR')
    return Path(override).expanduser().resolve() if override else Path(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation))/'HyperLab'


def load_config():
    path = config_directory()/'settings.json'
    if not path.exists():
        return {'schema_version':1}
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise ValueError(f'Unsupported settings file; preserve it and select another HYPERLAB_CONFIG_DIR: {path}')
    return value


def save_config(value):
    from .acquisition.sequence import atomic_json
    directory = config_directory()
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(directory/'settings.json', dict(value, schema_version=1))


def workspace(explicit=None, *, create=True):
    value = explicit or os.environ.get('HYPERLAB_WORKSPACE') or load_config().get('workspace')
    if value is None:
        value = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))/'HyperLabData'
    path = Path(value).expanduser().resolve()
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=path):
                pass
        except OSError as error:
            raise ValueError(f'Workspace is not writable: {path}. Select a writable folder using --workspace or Workspace in the app.') from error
    return path


def select_workspace(path):
    path = workspace(path)
    config = load_config()
    config['workspace'] = str(path)
    save_config(config)
    return path
