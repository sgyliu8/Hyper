"""Small SYNTHETIC scan-to-ROI example; no hardware or calibration acceptance."""
from copy import deepcopy
from pathlib import Path
import csv
import time

import numpy as np

from hyperlab.acquisition.frame import Frame
from hyperlab.acquisition.sequence import atomic_json
from hyperlab.analysis import roi_comparison, export_roi_csv, spectral_roi_features
from hyperlab.io import Cube, load_cube, save_cube
from hyperlab.plots import COLORS, export_figure_bundle, plain, roi_plot, source_identity
from .response import characterize_response, save_response
from .scan import stationary_scan
from .workflow import process_spectroscopy


class _ModelAdapter:
    """Generate owned model exposures; tokens describe only this synthetic model."""
    def __init__(self, values, metadata):
        self.values, self.metadata = values, metadata

    def preflight(self, recipe):
        return dict(verified=True, identity='SYNTHETIC numerical model',
            documentation='Model state token binds a newly copied generated plane; no device protocol',
            source='SYNTHETIC', exclusive=True, shape=list(self.values.shape[:2]),
            dtype=str(self.values.dtype), spatial_grid=self.metadata['spatial_grid'],
            pixel_format='Mono12', saturation_value=4095., synthetic=True)

    def open(self):
        pass

    def configure(self, recipe):
        self.recipe = recipe

    def set_state(self, state, attempt_id):
        self.index = self.recipe['states'].index(state)
        return dict(state_id=state, acknowledged=True, token=attempt_id,
                    readback_source='SYNTHETIC model state')

    def wait_settled(self, ack, stop):
        return dict(settled=True, token=ack['token'] + ':settled', evidence='SYNTHETIC instantaneous model')

    def capture(self, ack, settled, stop):
        return Frame(self.values[..., self.index].copy(), dict(valid=True, buffer_complete=True,
            state_id=ack['state_id'], state_token=ack['token'], settling_token=settled['token'],
            exposure_id=ack['token'] + ':exposure', freshness_method='trigger_token',
            freshness_source='SYNTHETIC generated after model settling', host_monotonic_ns=time.monotonic_ns(),
            session_id='SYNTHETIC-example', stream_epoch=0, frame_id=self.index, sequence=self.index,
            exposure_us=self.recipe['exposure_us'][self.index], gain=self.recipe['gain'],
            pixel_format='Mono12', spatial_grid=self.metadata['spatial_grid']))

    def close(self):
        pass


def generate_example(directory):
    """Create a new local numerical example, preserving raw and negative cases."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    h, w, k, m = 32, 48, 12, 16
    wave = np.linspace(450., 900., k)
    centers = np.linspace(440., 910., m)
    A = np.exp(-.5 * ((centers[:, None] - wave) / 35.)**2)
    A /= A.sum(axis=1, keepdims=True)
    # Each known source illuminates several bins; these are finite sources, not delta lines.
    H = np.exp(-.5 * ((wave[:, None] - wave) / 30.)**2)
    H /= H.sum(axis=0, keepdims=True)
    held_out = np.column_stack((np.ones(k), np.linspace(.2, 1., k)))
    grid = dict(grid_id='SYNTHETIC-example-native', raw_shape_hw=[h, w], sensor_roi_offset=[0, 0],
                flip_x=False, flip_y=False, cfa_pattern=None, cfa_pattern_origin='not_applicable')
    applicability = dict(instrument_id='SYNTHETIC-example', temperature_condition_id='SYNTHETIC-fixed',
        settings={'ExposureAuto': 'Off', 'GainAuto': 'Off', 'gamma': 'off'},
        gain=0., gain_units='dB', optical_configuration={'model': 'SYNTHETIC fixed geometry'})
    states = [f'model-state-{index:02d}' for index in range(m)]
    metadata = dict(state_ids=states, model='multiplexed', spatial_grid=grid, pixel_format='Mono12',
        wavelength_source='SYNTHETIC known bin coordinates', wavelength_evidence='SYNTHETIC',
        signal_units='DN', output_units='relative linear signal', applicability=applicability,
        response_evidence={'kind': 'SYNTHETIC', 'source': 'Known overlapping forward matrix'},
        discretization='H and L are bin-integrated linear coefficients; no additional quadrature; grid spacing is not resolution',
        correction={'dark_subtracted': True, 'exposure_normalized': False, 'exposure_s': [.01] * m})
    bundle = characterize_response(A @ H, H, wavelengths=wave, metadata=metadata,
        region_map=np.zeros((h, w), int), validation_H=held_out, validation_Y=A @ held_out)
    response_path = save_response(bundle, directory/'response')

    yy, xx = np.indices((h, w))
    texture = 1 + .045 * np.sin(xx / 2.) * np.cos(yy / 3.)
    base = .22 + .40 * np.exp(-.5 * ((wave - 670.) / 85.)**2)
    rectangles = [(4, 4, 16, 16), (20, 6, 32, 18), (32, 20, 44, 30)]
    names = ['Region A', 'Region B', 'Region C']
    shapes = [base * .92 - .055 * np.exp(-.5 * ((wave - 540.) / 30.)**2),
              base * .98, base * 1.04 - .045 * np.exp(-.5 * ((wave - 790.) / 35.)**2)]
    truth = np.broadcast_to(base * .75, (h, w, k)).copy()
    for rect, signal in zip(rectangles, shapes):
        x0, y0, x1, y1 = rect
        truth[y0:y1, x0:x1] = texture[y0:y1, x0:x1, None] * signal
    illumination = (600 + 200 * np.exp(-.5 * ((wave - 650.) / 150.)**2)) * (.85 + .15 * xx[..., None] / w)
    reference = .94 + .02 * np.sin((wave - 450.) / 450. * np.pi)
    dark_values = np.broadcast_to(12. + np.arange(m) * .1, (h, w, m)).copy()
    sample_values = np.einsum('hwk,mk->hwm', illumination * truth, A) + dark_values
    white_values = np.einsum('hwk,mk->hwm', illumination * reference, A) + dark_values
    reference_csv = directory/'synthetic-reference.csv'
    with reference_csv.open('x', newline='', encoding='utf8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['wavelength_nm', 'reflectance'])
        writer.writerows(zip(wave, reference))
    save_cube(Cube(truth, dict(data_level='reflectance_cube', units='dimensionless', wavelengths=wave,
        wavelength_units='nm', wavelength_source='SYNTHETIC model truth', synthetic=True,
        data_source='SYNTHETIC', completed=True, partial=False)), directory/'expected-factor.npy')

    raw_paths, scans = {}, {}
    noise = np.random.default_rng(7).normal(0, 1., sample_values.shape)
    for name, role, values in [('sample', 'sample', sample_values), ('white', 'white', white_values),
            ('dark-sample', 'dark', dark_values), ('dark-white', 'dark', dark_values),
            ('sample-noisy', 'sample', sample_values + noise)]:
        context = dict(role=role, instrument_id=applicability['instrument_id'],
            temperature_condition_id=applicability['temperature_condition_id'], illumination_id='SYNTHETIC lamp',
            geometry_id='SYNTHETIC geometry', evidence_kind='declared', evidence_source='SYNTHETIC numerical model')
        if role == 'dark':
            context.update(light_blocked=True, dark_method='SYNTHETIC blocked-light model')
        recipe = dict(id='SYNTHETIC-example', states=states, exposure_us=[10000.] * m,
            gain=0., gain_units='dB', settings=applicability['settings'],
            optical_configuration=applicability['optical_configuration'], measurement_context=context)
        receipt = stationary_scan(_ModelAdapter(values, metadata), recipe, directory/'raw'/name)
        scans[name] = {key: receipt[key] for key in ('completed', 'accepted', 'durable', 'unpersisted')}
        if not receipt['completed']:
            raise RuntimeError(f'Synthetic {name} scan failed: {receipt.get("error")}')
        raw_paths[name] = receipt['raw_path']
    options = dict(response_path=response_path, dark_sample_path=raw_paths['dark-sample'],
                   dark_white_path=raw_paths['dark-white'], reference_csv=reference_csv)
    clean = process_spectroscopy(raw_paths['sample'], raw_paths['white'], directory/'clean', **options)
    noisy = process_spectroscopy(raw_paths['sample-noisy'], raw_paths['white'], directory/'noisy', **options)
    with load_cube(clean['product']) as cube, load_cube(noisy['product']) as noisy_cube:
        results = roi_comparison(cube, rectangles, policy='quantitative', support='common')
        features = spectral_roi_features(cube, results, 'integral')
        atomic_json(directory/'roi-integral.json', plain(features))
        for index, result in enumerate(results):
            export_roi_csv(result, directory/f'roi-{index + 1}.csv')
        spec = roi_plot(results, names, COLORS[:3], source=source_identity(cube), normalized=True)
        export_figure_bundle(spec, directory/'roi-figure', source_cube=cube, dpi=120)
        numerical = dict(clean_max_abs_error=float(np.max(np.abs(cube.data - truth))),
            noisy_rmse=float(np.sqrt(np.mean((noisy_cube.data - truth)**2))),
            noise_model='SYNTHETIC independent additive normal sample-state noise, SD=1 DN, seed=7; dark/white are exact',
            raw_state_count=m, reconstructed_coefficient_count=k,
            roi=[dict(name=name, color=color, rect=rect, mean=result['mean'], spatial_sd=result['std'],
                      used_count=result['count']) for name, color, rect, result in zip(names, COLORS, rectangles, results)],
            integral=[dict(name=name, used_count=curve['used_count'], **curve['features'])
                      for name, curve in zip(names, features['curves'])],
            response_rank=int(np.linalg.matrix_rank(A)),
            fit_max_abs_error=float(np.max(np.abs(bundle['A'][0] - A))))

    with load_cube(raw_paths['sample']) as raw:
        wrong = deepcopy(raw.metadata)
        wrong['scan_states'] = list(reversed(wrong['scan_states']))
        wrong_path = save_cube(Cube(np.array(raw.data), wrong), directory/'wrong-state.npy')
    try:
        process_spectroscopy(wrong_path, raw_paths['white'], directory/'rejected-wrong-state', **options)
    except ValueError as error:
        if 'state identity/order mismatch' not in str(error):
            raise
        rejection = dict(rejected=True, error=str(error), input=str(wrong_path),
                         receipt=str(directory/'rejected-wrong-state'/'processing.json'))
    else:
        raise RuntimeError('Wrong-state example was not rejected')
    report = plain(dict(origin='SYNTHETIC', hardware_validation='NOT_TESTED',
        physical_validation='NOT_ESTABLISHED_BY_COMPUTATION', directory=str(directory),
        response=str(response_path), raw=raw_paths, scans=scans, reference_csv=str(reference_csv),
        product=clean['product'], noisy_product=noisy['product'], expected_factor=str(directory/'expected-factor.npy'),
        roi_figure=str(directory/'roi-figure'/'figure.png'), roi_integral=str(directory/'roi-integral.json'),
        numerical=numerical, wrong_state=rejection))
    atomic_json(directory/'example.json', report)
    return report
