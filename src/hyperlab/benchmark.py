"""Explicit local hardware acceptance. No hardware is exercised by importing this module."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import psutil


def run(output, *, seconds=10, cycles=1, record_frames=0, exposure_us=50000, pixel_format='BayerRG12'):
    from hyperlab.devices import discover_profile
    from hyperlab.acquisition.camera import CameraSession
    from hyperlab.acquisition.sequence import load_sequence, atomic_json
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=False)
    report = {'schema_version':2, 'hardware':True, 'started_at':datetime.now(timezone.utc).isoformat(),
              'requested_seconds':seconds, 'requested_cycles':cycles, 'record_frames':record_frames,
              'settings':{'PixelFormat':pixel_format,'ExposureTime':exposure_us,'Gain':0},
              'preview_metrics':[], 'cycles':[], 'status':'RUNNING',
              'scene_conditions':'unknown; fixed optical state, no claimed material or spectral validation'}
    session = None
    primary = None
    started = time.monotonic()
    try:
        profile = discover_profile()
        report['profile'] = profile
        session = CameraSession(profile['cti'], profile['serial'], settings=report['settings'], mode='measurement')
        session.connect().result(timeout=60)
        for cycle in range(cycles):
            session.start_preview().result(timeout=30)
            start_state = session.status()
            deadline = time.monotonic() + (seconds if cycle == 0 else 1)
            last_report = 0
            last_identity = None
            while time.monotonic() < deadline:
                state = session.status()
                if state['error']:
                    raise RuntimeError(state['error'])
                frame = session.latest_frame()
                if frame_belongs_to_start(frame, start_state):
                    last_identity = frame.identity
                # This is a headless poll, deliberately not marked as displayed.
                if time.monotonic() - last_report >= 1:
                    last_report = time.monotonic()
                    report['preview_metrics'].append(dict(state, elapsed_s=time.monotonic()-started,
                        rss_bytes=psutil.Process().memory_info().rss, cycle=cycle))
                    atomic_json(directory/'progress.json', report)
                time.sleep(.05)
            if last_identity is None:
                raise RuntimeError('No real frame received within the preview interval')
            if cycle == 0:
                frame = session.latest_frame()
                report['snapshot_identity'] = frame.identity
                report['snapshot_path'] = str(session.snapshot(directory/'snapshot', frame=frame).result(timeout=30))
                if record_frames:
                    session.start_recording(directory/'recording', record_frames).result(timeout=30)
                    recording_deadline = time.monotonic() + max(30, record_frames * exposure_us/1e6 * 3 + 20)
                    while time.monotonic() < recording_deadline:
                        state = session.status()
                        recording = state.get('recording') or {}
                        if recording.get('error'):
                            raise RuntimeError(recording['error'])
                        if recording.get('done'):
                            report['recording'] = recording
                            break
                        time.sleep(.1)
                    else:
                        raise TimeoutError('Bounded recording did not complete in its acceptance budget')
                    with load_sequence(directory/'recording') as sequence:
                        report['sequence_reopen'] = {'frame_count':sequence.frame_count,
                            'shape':list(sequence.data.shape), 'axis_order':sequence.metadata['axis_order'],
                            'wavelengths':sequence.metadata['wavelengths'],
                            'verified_indices':sequence.metadata.get('reopen_verified_indices'),
                            'completed':sequence.metadata['completed']}
                        if sequence.frame_count != record_frames or not sequence.metadata['completed']:
                            raise RuntimeError('Recording prefix is incomplete')
            stop_begin = time.monotonic()
            session.stop_preview().result(timeout=max(10, exposure_us/1e6 + 5))
            report['cycles'].append({'cycle':cycle,'stop_seconds':time.monotonic()-stop_begin,
                                      'state':session.state,'last_frame_identity':last_identity,
                                      'stream_epoch':start_state['stream_epoch'],
                                      'cleanup':session.status()['cleanup']})
        report['status'] = 'PASS'
    except Exception as error:
        primary = error
        report.update(status='FAIL', error=f'{type(error).__name__}: {error}')
    finally:
        if session:
            session.close(wait=True, timeout=30)
            report['final_session'] = session.status()
            if not report['final_session']['closed'] or not report['final_session']['camera_released']:
                report.update(status='FAIL', release_error='Camera release not confirmed')
        report.update(elapsed_seconds=time.monotonic()-started, ended_at=datetime.now(timezone.utc).isoformat())
        atomic_json(directory/'receipt.json', report)
    print(json.dumps({'status':report['status'],'receipt':str(directory/'receipt.json'),'error':report.get('error')}, indent=2))
    if primary:
        raise primary
    return report


def frame_belongs_to_start(frame, start_state):
    return (frame is not None and frame.metadata.get('stream_epoch') == start_state['stream_epoch']
            and frame.metadata.get('host_monotonic_ns', -1) >= start_state['stream_started_ns'])


def main():
    parser = argparse.ArgumentParser(description='Explicit real camera preview / bounded recording acceptance')
    parser.add_argument('--hardware', action='store_true', help='Required: perform real camera operations')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--cycles', type=int, default=1)
    parser.add_argument('--record-frames', type=int, default=0)
    parser.add_argument('--exposure-us', type=float, default=50000)
    parser.add_argument('--pixel-format', choices=['BayerRG12','RGB8','BGR8'], default='BayerRG12')
    args = parser.parse_args()
    if not args.hardware:
        parser.error('--hardware is required; offline tests do not open a camera')
    if not 0 < args.seconds <= 600 or not 1 <= args.cycles <= 10 or not 0 <= args.record_frames <= 600:
        parser.error('Acceptance limits: seconds (0,600], cycles 1..10, frames 0..600')
    result = run(args.output, seconds=args.seconds, cycles=args.cycles, record_frames=args.record_frames,
                 exposure_us=args.exposure_us, pixel_format=args.pixel_format)
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
