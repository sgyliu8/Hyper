"""Presentation of camera state and independently pinned observations."""
from pathlib import Path


def observation_label(metadata, *, compact=False):
    """Describe origin and identity without turning saved captures into live views."""
    origin = metadata.get('acquisition_source') or metadata.get('data_source')
    if origin == 'LIVE':
        label = 'Real camera capture'
    elif origin == 'SYNTHETIC' or metadata.get('synthetic'):
        label = 'Synthetic example'
    else:
        label = 'External data' if metadata.get('source_file') else 'Data origin unknown'
    parts = [label]
    path = metadata.get('source_file')
    if path and (not compact or metadata.get('sequence') is None):
        path = Path(path)
        name = f'{path.parent.name}/{path.name}' if path.name in ('frame.npy', 'sequence.npy') else path.name
        parts.append(name if not compact or len(name) <= 45 else '…' + name[-44:])
    frame = metadata.get('sequence')
    if frame is not None:
        parts.append(f'frame {frame}')
    timestamp = metadata.get('host_utc')
    if timestamp and not compact:
        parts.append(str(timestamp))
    return ' · '.join(parts)


def viewing_label(mode):
    return {'EMPTY': 'No data', 'LIVE': 'Live preview', 'STALE': 'Preview stalled',
            'FROZEN': 'Frozen display', 'REPLAY': 'Saved / retained frame',
            'SYNTHETIC': 'Synthetic example'}.get(mode, mode)


def camera_label(state, *, discovering=False):
    if discovering:
        return 'Camera: Checking connection…'
    text = {'ready': 'Connected · idle', 'streaming': 'Previewing', 'recording': 'Recording',
            'connecting': 'Connecting…', 'stopping': 'Stopping…', 'disconnected': 'Disconnected',
            'error': 'Connection error', 'closing': 'Releasing…'}.get(state, state.title())
    return f'Camera: {text}'
