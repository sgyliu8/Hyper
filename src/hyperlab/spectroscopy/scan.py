"""State-by-state acquisition through an explicitly supplied, reviewed adapter.

An adapter owns both controller and sensor. No vendor protocol is inferred here.
Its methods are synchronous and bounded; run this function on a worker thread.
"""
from copy import deepcopy
from pathlib import Path
import json
import math
import shutil
import threading
import time
import uuid

import numpy as np
import psutil

from hyperlab.acquisition.frame import Frame
from hyperlab.acquisition.sequence import atomic_json
from hyperlab.acquisition.session import ScanWriter, utc_now


def validate_recipe(recipe):
    """State identifiers are ordered commands, never inferred wavelengths."""
    recipe = deepcopy(recipe)
    states = recipe.get('states')
    if (not recipe.get('id') or not isinstance(states, list) or not states or
            any(not isinstance(s, str) or not s.strip() for s in states) or len(set(states)) != len(states)):
        raise ValueError('Recipe needs an id and ordered, distinct, nonempty state identifiers')
    supplied = recipe.get('exposure_us')
    if not isinstance(supplied, list) or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in supplied):
        raise ValueError('Exposure values must be numeric magnitudes, not booleans or strings')
    exposure = np.asarray(supplied, dtype=float)
    if exposure.shape != (len(states),) or not np.isfinite(exposure).all() or np.any(exposure <= 0):
        raise ValueError('Recipe needs one finite positive exposure_us per state')
    if isinstance(recipe.get('gain'), bool) or not isinstance(recipe.get('gain'), (int, float)) or not np.isfinite(recipe['gain']):
        raise ValueError('Recipe needs fixed gain in recorded device units; zero dB is allowed')
    if not recipe.get('gain_units'):
        raise ValueError('Recipe needs explicit gain_units')
    json.dumps(recipe, allow_nan=False)
    return recipe


def scan_preflight(adapter, recipe, directory):
    recipe = validate_recipe(recipe)
    if adapter is None:
        raise ValueError('Spectral selector is not configured. Supply the matching HinaLea API, '
                         'controller documentation and device recipe; a dependency pack alone cannot control the selector.')
    facts = deepcopy(adapter.preflight(deepcopy(recipe)))
    if facts.get('verified') is not True or not facts.get('identity') or not facts.get('documentation'):
        raise ValueError('Adapter needs verified identity and command/settling/freshness documentation')
    if facts.get('source') not in ('LIVE', 'REPLAY', 'SYNTHETIC'):
        raise ValueError('Adapter must declare LIVE, REPLAY or SYNTHETIC')
    if facts.get('exclusive') is not True:
        raise ValueError('Release the previous controller/camera owner before acquisition')
    shape = facts.get('shape')
    if (not isinstance(shape, (list, tuple)) or len(shape) != 2 or
            any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in shape)):
        raise ValueError('Adapter must declare an HW raw sensor plane; RGB is not a spectral state')
    dtype = np.dtype(facts['dtype'])
    if dtype.kind not in 'uif':
        raise ValueError('Raw plane must be real numeric data')
    if not facts.get('spatial_grid') or not facts.get('pixel_format'):
        raise ValueError('Raw pixel format and spatial/CFA grid must be recorded')
    plane_bytes = int(np.prod(shape)) * dtype.itemsize
    # Mapped output remains on disk; no full float cube or per-pixel MxK matrix.
    memory = plane_bytes * 5 + 64 * 1024**2
    disk = plane_bytes * len(recipe['states']) + 16 * 1024**2
    parent = Path(directory).resolve().parent
    while not parent.exists():
        parent = parent.parent
    if psutil.virtual_memory().available < memory or shutil.disk_usage(parent).free < disk:
        raise MemoryError(f'Stationary scan needs {memory} available working bytes and {disk} free disk bytes')
    facts.update(required_memory_bytes=memory, required_disk_bytes=disk)
    return facts


def _frame_association(frame, state, acknowledgement, settling, previous):
    if not isinstance(frame, Frame) or frame.data.ndim != 2:
        raise ValueError('Adapter must return an owned immutable HW Frame')
    if (not frame.data.flags.owndata or frame.data.base is not None or frame.data.flags.writeable or
            isinstance(frame.data, np.memmap) or not frame.data.flags.c_contiguous):
        raise ValueError('Borrowed or mutable frame buffer cannot enter a stationary scan')
    meta = frame.metadata
    if meta.get('valid') is not True or meta.get('buffer_complete') is not True:
        raise ValueError('Invalid or incomplete camera buffer')
    if (meta.get('state_id') != state or meta.get('state_token') != acknowledgement['token'] or
            not meta.get('exposure_id') or not meta.get('freshness_source')):
        raise ValueError('Frame lacks verified state/exposure identity; receive-after-ACK alone is insufficient')
    # A token binds the actual exposure, not merely a host receive event.
    if meta.get('freshness_method') == 'trigger_token':
        if meta.get('settling_token') != settling['token']:
            raise ValueError('Exposure trigger was not linked to this completed settling interval')
    elif meta.get('freshness_method') == 'exposure_clock':
        clock = settling.get('clock_domain')
        unit = settling.get('clock_units')
        start, end = meta.get('exposure_start'), settling.get('settled_at')
        if (not isinstance(clock, str) or not clock or not isinstance(unit, str) or not unit or
                meta.get('exposure_clock') != clock or meta.get('exposure_clock_units') != unit or
                any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end)) or
                meta['exposure_start'] < settling['settled_at']):
            raise ValueError('Exposure precedes settling or clock domains are not mapped')
    else:
        raise ValueError('Unverified exposure freshness method')
    if isinstance(meta.get('host_monotonic_ns'), bool) or not isinstance(meta.get('host_monotonic_ns'), int) or meta['host_monotonic_ns'] < 0:
        raise ValueError('Missing host receipt clock')
    if previous is not None:
        if meta['host_monotonic_ns'] < previous['host_monotonic_ns']:
            raise ValueError('Host monotonic clock moved backwards')
        if meta.get('exposure_id') == previous.get('exposure_id'):
            raise ValueError('Repeated exposure identity')
        if (meta.get('session_id'), meta.get('stream_epoch')) != (previous.get('session_id'), previous.get('stream_epoch')):
            raise ValueError('Sensor stream identity changed within a scan')
        if isinstance(meta.get('frame_id'), int) and isinstance(previous.get('frame_id'), int):
            if meta['frame_id'] <= previous['frame_id']:
                raise ValueError('Repeated or backwards camera frame identifier')


def stationary_scan(adapter, recipe, directory, *, stop=None, progress=None, writer_factory=ScanWriter):
    """Persist every accepted optical state; return a complete or explicit partial receipt.

    Adapter methods: preflight(recipe), open(), configure(recipe), set_state(state,
    attempt_id), wait_settled(ack, stop), capture(ack, settled, stop), close().
    No plugin or command is loaded from a response bundle or recipe JSON.
    """
    recipe = validate_recipe(recipe)
    facts = scan_preflight(adapter, recipe, directory)
    stop = stop or threading.Event()
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError('Scan destination exists; retries require a new attempt directory')
    run_id = uuid.uuid4().hex
    manifest = {'schema_version': 1, 'attempt_id': run_id, 'started_at': utc_now(),
                'recipe': recipe, 'adapter': facts, 'phase': 'PREFLIGHT', 'events': [],
                'captured': 0, 'accepted': 0, 'owned': 0, 'durable': 0, 'completed': False,
                'partial': True, 'error': None, 'cleanup': [], 'source': facts['source'],
                'host_clock': vars(time.get_clock_info('monotonic'))}
    writer = None
    opened = False
    previous = None
    exposure_ids = set()
    state_tokens = set()

    def event(phase, **fields):
        manifest['phase'] = phase
        manifest['events'].append(dict(phase=phase, host_utc=utc_now(), host_monotonic_ns=time.monotonic_ns(), **fields))
        if directory.exists():
            atomic_json(directory / 'scan.json', manifest)
        if progress:
            progress(deepcopy(manifest))

    def cancelled():
        if stop.is_set():
            raise InterruptedError('Scan cancelled; the accepted prefix is retained')

    try:
        writer = writer_factory(directory, (*facts['shape'], len(recipe['states'])), facts['dtype'],
            source=facts['source'], checkpoint_frames=1, metadata=dict(facts,
                scan_states=recipe['states'], exposure_us=recipe['exposure_us'], exposure=recipe['exposure_us'],
                exposure_s=[value / 1e6 for value in recipe['exposure_us']], scan_recipe_id=recipe['id'],
                exposure_units='us', gain=recipe['gain'], gain_units=recipe['gain_units'],
                settings=recipe.get('settings', {}), recipe_id=recipe['id'], attempt_id=run_id,
                measurement_context=recipe.get('measurement_context', {}),
                scan_association='verified state and exposure identities', optical_configuration=recipe.get('optical_configuration')))
        manifest['raw_path'] = str(writer.path.resolve())
        event('EXCLUSIVE')
        cancelled()
        opened = True  # A partly successful open must also be released.
        adapter.open()
        event('CONFIGURE')
        adapter.configure(deepcopy(recipe))
        for index, state in enumerate(recipe['states']):
            cancelled()
            event('SET_STATE', index=index, state=state)
            ack = deepcopy(adapter.set_state(state, f'{run_id}:{index}'))
            if (ack.get('state_id') != state or ack.get('acknowledged') is not True or
                    not isinstance(ack.get('token'), str) or not ack['token'] or
                    ack['token'] in state_tokens or not ack.get('readback_source')):
                raise ValueError('Selector did not acknowledge the requested state')
            state_tokens.add(ack['token'])
            event('ACKNOWLEDGE', index=index, acknowledgement=ack)
            cancelled()
            settled = deepcopy(adapter.wait_settled(deepcopy(ack), stop))
            if settled.get('settled') is not True or not settled.get('token') or not settled.get('evidence'):
                raise ValueError('Selector settling is not established')
            event('SETTLE', index=index, settling=settled)
            cancelled()
            event('FRESH_EXPOSURE', index=index)
            frame = adapter.capture(deepcopy(ack), deepcopy(settled), stop)
            manifest['captured'] += 1
            _frame_association(frame, state, ack, settled, previous)
            if frame.metadata['exposure_id'] in exposure_ids:
                raise ValueError('Exposure identity was already used by an earlier state')
            if (frame.metadata.get('exposure_us') != recipe['exposure_us'][index] or
                    frame.metadata.get('gain') != recipe['gain']):
                raise ValueError('State exposure/gain readback differs from the recipe')
            if (frame.data.shape != tuple(facts['shape']) or frame.data.dtype != np.dtype(facts['dtype']) or
                    json.dumps(frame.metadata.get('spatial_grid'), sort_keys=True) != json.dumps(facts['spatial_grid'], sort_keys=True) or
                    frame.metadata.get('pixel_format') != facts['pixel_format']):
                raise ValueError('Raw format or spatial grid changed during acquisition')
            exposure_ids.add(frame.metadata['exposure_id'])
            manifest['owned'] += 1
            manifest['accepted'] += 1
            event('COPY_VALIDATE', index=index)
            record = dict(frame.metadata, target_state=state, returned_state=state, acknowledgement=ack, settling=settled)
            writer.append(frame.data, record)
            manifest['durable'] = writer.meta['frame_count']
            previous = frame.metadata
            event('STATE_SAVED', index=index)
        event('RAW_COMPLETE')
    except Exception as error:
        manifest['error'] = f'{type(error).__name__}: {error}'
        manifest['failed_phase'] = manifest['phase']
    finally:
        if opened:
            try:
                adapter.close()
                manifest['cleanup'].append({'operation': 'adapter.close', 'status': 'PASS'})
            except Exception as error:
                manifest['cleanup'].append({'operation': 'adapter.close', 'status': 'FAIL', 'error': str(error)})
        if writer is not None:
            try:
                writer.finish(error=manifest['error'], stopped=stop.is_set())
                saved = json.loads(writer.path.with_suffix('.npy.json').read_text(encoding='utf8'))
                manifest['durable'] = saved['frame_count']
                manifest.update(raw_path=str(writer.path.resolve()), completed=saved['completed'], partial=saved['partial'])
            except Exception as error:
                manifest['persistence_error'] = str(error)
                manifest.update(completed=False, partial=True)
        manifest['unpersisted'] = manifest['accepted'] - manifest['durable']
        manifest['ended_at'] = utc_now()
        manifest['phase'] = 'RAW_COMPLETE' if manifest['completed'] else 'PARTIAL'
        if directory.exists():
            try:
                atomic_json(directory / 'scan.json', manifest)
            except Exception as error:
                manifest.update(receipt_error=str(error), completed=False, partial=True, phase='RECEIPT_FAILED')
                if manifest['error'] is None:
                    manifest['error'] = f'Final scan receipt write failed: {error}'
        if progress:
            progress(deepcopy(manifest))
    return manifest
