"""Numeric response characterization and native-grid linear reconstruction.

Response bundles contain data, not executable controller code. A numerical fit
or compatible declaration does not establish physical calibration acceptance.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from numbers import Real
from pathlib import Path
import uuid

import numpy as np

from hyperlab.acquisition.sequence import atomic_json
from hyperlab.analysis.applicability import _known
from hyperlab.analysis.core import _floating, _quality, saturation_value
from hyperlab.analysis.roi_features import _gap_constraints, _physical_support
from hyperlab.io import Cube
from hyperlab.io.cube import wavelength_unit_scale


ARRAYS = ('A', 'region_map', 'wavelength_validity', 'characterization_H',
          'characterization_Y', 'validation_H', 'validation_Y')
REGULARIZER = 'first differences / sqrt(delta_nm); integrated squared slope; no unsupported/gap connections'


def _plain(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f'Unsupported response metadata: {type(value).__name__}')


def _json(value):
    return json.dumps(value, default=_plain, allow_nan=False, sort_keys=True,
                      separators=(',', ':'), ensure_ascii=False)


def _positive(values, size, name):
    if isinstance(values, (list, tuple)) and any(isinstance(v, (bool, np.bool_)) for v in values):
        raise ValueError(f'{name} must not contain boolean quantities')
    original = np.asarray(values)
    if original.dtype.kind not in 'uif' or original.dtype.kind == 'b':
        raise ValueError(f'{name} must contain positive real quantities, not booleans')
    values = np.asarray(values, np.float64)
    if values.shape != (size,) or not np.isfinite(values).all() or np.any(values <= 0):
        raise ValueError(f'{name} needs {size} finite positive quantities')
    return values


def _grid(grid):
    if not isinstance(grid, dict) or not isinstance(grid.get('grid_id'), str) or not _known(grid['grid_id']):
        raise ValueError('An explicit spatial grid identity is required')
    for key, length, minimum in (('raw_shape_hw', 2, 1), ('sensor_roi_offset', 2, 0)):
        value = grid.get(key)
        if (not isinstance(value, (list, tuple)) or len(value) != length or
                any(isinstance(n, (bool, np.bool_)) or not isinstance(n, (int, np.integer)) or n < minimum for n in value)):
            raise ValueError(f'Spatial grid {key} must be explicit integer coordinates')
    if any(type(grid.get(key)) is not bool for key in ('flip_x', 'flip_y')):
        raise ValueError('Spatial grid flips must be explicit booleans')
    pattern, origin = grid.get('cfa_pattern'), grid.get('cfa_pattern_origin')
    if pattern is None:
        if origin != 'not_applicable':
            raise ValueError('A non-CFA grid must explicitly declare not_applicable')
    elif pattern not in ('RGGB', 'GRBG', 'GBRG', 'BGGR') or origin not in ('sensor', 'delivered'):
        raise ValueError('CFA grid needs a known pattern and its sensor/delivered origin')
    return deepcopy(grid)


def _linearity(evidence, exposures, gain):
    if (not isinstance(evidence, dict) or evidence.get('verified') is not True or
            not isinstance(evidence.get('source'), str) or not _known(evidence['source'])):
        raise ValueError('Exposure normalization requires retained applicable verified linearity evidence')
    bounds = _positive(evidence.get('exposure_range_s'), 2, 'Linearity exposure_range_s')
    if bounds[0] > bounds[1] or np.any(exposures < bounds[0]) or np.any(exposures > bounds[1]):
        raise ValueError('Exposure lies outside the verified linearity range')
    if isinstance(evidence.get('gain'), bool) or evidence.get('gain') != gain:
        raise ValueError('Linearity evidence does not match the fixed gain')


def _array_signature(value):
    array = np.ascontiguousarray(value)
    return {'shape': list(array.shape), 'dtype': str(array.dtype),
            'sha256': hashlib.sha256(array.tobytes()).hexdigest()}


def _synthetic_origin(metadata):
    values = {str(metadata.get(key, '')).upper() for key in ('acquisition_source', 'data_source')}
    synthetic = metadata.get('synthetic') is True or bool(values & {'SYNTHETIC', 'SYNTHETIC_MODEL_FROM_EXTERNAL_MEASURED_SPECTRA'})
    if synthetic and values & {'LIVE', 'EXTERNAL_MEASURED', 'EXTERNAL_MEASURED_AVERAGE'}:
        raise ValueError('Conflicting synthetic and measured source-origin declarations')
    return synthetic


def _validate(bundle):
    if bundle.get('schema_version') != 1 or bundle.get('kind') != 'spectral_response_bundle':
        raise ValueError('Unsupported spectral response bundle')
    if not isinstance(bundle.get('bundle_id'), str) or not _known(bundle['bundle_id']):
        raise ValueError('Response bundle needs an identity')
    meta = deepcopy(bundle.get('metadata', {}))
    A = np.asarray(bundle.get('A'), np.float64)
    if A.ndim == 2:
        A = A[None, ...]
    if A.ndim != 3 or min(A.shape) < 1 or not np.isfinite(A).all():
        raise ValueError('A must be finite region x state x wavelength data')
    regions, m, k = A.shape
    states = meta.get('state_ids')
    if (not isinstance(states, list) or len(states) != m or
            any(not isinstance(s, str) or not s.strip() for s in states) or len(set(states)) != m):
        raise ValueError('Response state IDs must be distinct, ordered and match A rows')
    scale = wavelength_unit_scale(meta.get('wavelength_units'))
    wave = _positive(meta.get('wavelengths'), k, 'Response wavelengths')
    if scale is None or not np.isfinite(wave * scale).all() or np.any(np.diff(wave) <= 0):
        raise ValueError('Response wavelengths must be increasing with known physical units')
    wave = wave * scale
    if meta.get('fwhm') is not None:
        fwhm_scale = wavelength_unit_scale(meta.get('fwhm_units', meta['wavelength_units']))
        if fwhm_scale is None:
            raise ValueError('Response bandwidth units must be known')
        meta['fwhm'] = (_positive(meta['fwhm'], k, 'Response fwhm') * fwhm_scale).tolist()
        meta['fwhm_units'] = 'nm'
    meta['wavelengths'], meta['wavelength_units'] = wave.tolist(), 'nm'
    for key in ('wavelength_source', 'response_evidence', 'discretization', 'pixel_format', 'signal_units', 'output_units'):
        if not _known(meta.get(key)):
            raise ValueError(f'Response requires explicit {key}')
    grid = _grid(meta.get('spatial_grid'))
    if ('bayer' in str(meta['pixel_format']).lower()) != (grid['cfa_pattern'] is not None):
        raise ValueError('Raw pixel format and declared CFA grid disagree')
    mapping = np.asarray(bundle.get('region_map'))
    if (mapping.dtype.kind not in 'iu' or mapping.shape != tuple(grid['raw_shape_hw']) or
            np.any(mapping < -1) or np.any(mapping >= regions)):
        raise ValueError('region_map must match native HW, with -1 unsupported or valid response indices')
    support = np.asarray(bundle.get('wavelength_validity'))
    if support.dtype != np.bool_ or support.shape != (regions, k):
        raise ValueError('wavelength_validity must be a region x wavelength boolean mask')
    if not support.any() or not np.any(mapping >= 0):
        raise ValueError('Response has no supported wavelength or spatial region')
    if np.any(np.where(support[:, None, :], 0, A) != 0):
        raise ValueError('Unsupported wavelength columns with nonzero response cannot be silently omitted')
    applicability = meta.get('applicability')
    if not isinstance(applicability, dict):
        raise ValueError('Response needs recorded instrument/settings applicability')
    for key in ('instrument_id', 'temperature_condition_id', 'settings', 'gain', 'gain_units', 'optical_configuration'):
        if not _known(applicability.get(key)):
            raise ValueError(f'Response applicability needs known {key}')
    if isinstance(applicability['gain'], (bool, np.bool_)) or not isinstance(applicability['gain'], Real):
        raise ValueError('Fixed gain must be a real setting, not a divisor or boolean')
    correction = meta.get('correction', {})
    if correction.get('dark_subtracted') is not True or type(correction.get('exposure_normalized')) is not bool:
        raise ValueError('Characterized A requires typed dark/exposure correction ownership')
    calibration_exposure = _positive(correction.get('exposure_s'), m, 'Calibration exposure_s')
    if correction['exposure_normalized']:
        _linearity(correction.get('linearity_evidence'), calibration_exposure, applicability['gain'])
    solver = meta.get('solver', {})
    if set(solver) - {'alpha', 'rcond', 'weights', 'weighting', 'weight_evidence', 'constraint', 'regularizer'}:
        raise ValueError('Response solver contains unsupported options')
    if solver.get('constraint', 'unconstrained') != 'unconstrained':
        raise ValueError('This response baseline implements an unconstrained linear solver only')
    if solver.get('regularizer', REGULARIZER) != REGULARIZER:
        raise ValueError('Response regularizer definition does not match this numerical baseline')
    alpha, rcond = solver.get('alpha', 0.), solver.get('rcond', 1e-12)
    if isinstance(alpha, bool) or not np.isscalar(alpha) or not np.isfinite(alpha) or alpha < 0:
        raise ValueError('Regularization alpha must be finite and nonnegative')
    if isinstance(rcond, bool) or not np.isscalar(rcond) or not np.isfinite(rcond) or not 0 < rcond < 1:
        raise ValueError('SVD rcond must be finite and strictly between zero and one')
    weights = _positive(solver.get('weights', [1.] * m), m, 'State weights')
    weighting = solver.get('weighting', 'equal')
    if weighting == 'equal':
        if not np.array_equal(weights, np.ones(m)):
            raise ValueError('Equal weighting must use unit weights')
    elif weighting != 'measured_diagonal_inverse_variance' or not _known(solver.get('weight_evidence')):
        raise ValueError('Nonuniform weights require supplied diagonal noise-weight evidence')
    model = meta.get('model', 'multiplexed')
    if model not in ('multiplexed', 'direct_band'):
        raise ValueError('Use a measured direct_band or multiplexed response model')
    if model == 'direct_band':
        _positive(meta.get('fwhm'), k, 'Direct-band fwhm')
        if m != k or alpha != 0 or np.any(A < 0):
            raise ValueError('Direct bands require nonnegative diagonal/permutation A, M=K and alpha=0')
        if np.any(np.count_nonzero(A, axis=1) > 1) or np.any(np.count_nonzero(A, axis=2) > 1):
            raise ValueError('Direct-band rows cannot mix spectral coefficients')
    _, gaps = _gap_constraints(None, meta.get('measurement_gaps_nm'))
    operators, diagnostics = [], []
    for region in range(regions):
        selected = np.flatnonzero(support[region])
        matrix = A[region][:, selected]
        weighted = np.sqrt(weights)[:, None] * matrix
        singular = np.linalg.svd(weighted, compute_uv=False)
        rank = int(np.count_nonzero(singular > (singular[0] * rcond if singular.size else 0)))
        if rank != len(selected):
            raise ValueError(f'Response region {region} is rank deficient: rank {rank} for {len(selected)} supported coefficients')
        derivative = []
        for column in range(len(selected) - 1):
            first, second = selected[column:column + 2]
            if second != first + 1 or not _physical_support(wave[[first, second]], [first, second], None, gaps)['allowed']:
                continue
            row = np.zeros(len(selected))
            row[column:column + 2] = [-1., 1.]
            derivative.append(row / np.sqrt(wave[second] - wave[first]))
        D = np.asarray(derivative).reshape(-1, len(selected)) if len(selected) else np.empty((0, 0))
        augmented = np.vstack((weighted, np.sqrt(alpha) * D))
        rhs = np.vstack((np.diag(np.sqrt(weights)), np.zeros((len(D), m))))
        B = np.linalg.lstsq(augmented, rhs, rcond=rcond)[0] if len(selected) else np.empty((0, m))
        operators.append((selected, B))
        diagnostics.append({'region': region, 'rank': rank, 'supported_coefficients': len(selected),
            'singular_values': singular.tolist(), 'condition_number': float(singular[0] / singular[-1]) if singular.size else None,
            'effective_resolution': (B @ matrix).tolist(), 'regularizer_rows': D.tolist(),
            'negative_response_coefficients': int(np.count_nonzero(matrix < 0))})
    meta.update(model=model, spatial_grid=grid)
    meta['solver'] = {**solver, 'alpha': float(alpha), 'rcond': float(rcond), 'weights': weights.tolist(),
        'weighting': weighting, 'constraint': 'unconstrained',
        'regularizer': REGULARIZER}
    definition = {key: meta[key] for key in ('model', 'wavelengths', 'wavelength_units', 'signal_units',
        'output_units', 'discretization', 'spatial_grid')}
    definition['solver'] = {key: value for key, value in meta['solver'].items() if key != 'weight_evidence'}
    definition.update(state_ids=states, correction={'dark_subtracted': True,
        'exposure_normalized': correction['exposure_normalized'],
        'fixed_exposure_s': None if correction['exposure_normalized'] else calibration_exposure.tolist()},
        required_row_policy='complete_recipe_per_pixel' if model == 'multiplexed' else 'required_direct_band_row',
        measurement_gaps_nm=gaps, fwhm=meta.get('fwhm'),
        A=_array_signature(A), region_map=_array_signature(mapping), wavelength_validity=_array_signature(support))
    signature = hashlib.sha256(_json(definition).encode('utf-8')).hexdigest()
    _json(meta)
    return {'A': A, 'region_map': mapping, 'wavelength_validity': support, 'metadata': meta,
            'operators': operators, 'diagnostics': diagnostics, 'operator_definition': definition,
            'operator_signature': signature}


def characterize_response(Y, H, *, wavelengths, metadata, region_map, wavelength_units='nm',
                          alpha=0., weights=None, validation_Y=None, validation_H=None, rcond=1e-12,
                          wavelength_validity=None):
    """Fit Y=A H from declared corrected signals and known finite source spectra.

    Y is region,state,input (or state,input); H is wavelength,input. H describes
    the actual finite source, using metadata.discretization, not nominal colors.
    """
    H, Y = np.asarray(H, np.float64), np.asarray(Y, np.float64)
    if Y.ndim == 2:
        Y = Y[None, ...]
    if (H.ndim != 2 or min(H.shape) < 1 or Y.ndim != 3 or min(Y.shape) < 1 or
            Y.shape[-1] != H.shape[1] or not np.isfinite(H).all() or not np.isfinite(Y).all() or
            np.any(H < 0) or np.any(H.sum(axis=0) <= 0)):
        raise ValueError('Finite-source characterization requires finite Y and nonnegative known H with nonzero inputs')
    wave = _positive(wavelengths, H.shape[0], 'Characterization wavelengths')
    scale = wavelength_unit_scale(wavelength_units)
    if scale is None or not np.isfinite(wave * scale).all() or len(np.unique(wave)) != len(wave):
        raise ValueError('Characterization wavelength coordinates must be unique with known units')
    order = np.argsort(wave)
    H, wave = H[order], wave[order] * scale
    if isinstance(rcond, bool) or not np.isfinite(rcond) or not 0 < rcond < 1:
        raise ValueError('Characterization rcond must be between zero and one')
    singular = np.linalg.svd(H, compute_uv=False)
    rank = int(np.count_nonzero(singular > singular[0] * rcond))
    if rank != H.shape[0]:
        raise ValueError(f'Known input spectra do not identify A: H rank {rank} for {H.shape[0]} coefficients')
    A = np.stack([np.linalg.lstsq(H.T, values.T, rcond=rcond)[0].T for values in Y])
    meta = deepcopy(metadata)
    meta.update(wavelengths=wave.tolist(), wavelength_units='nm',
                original_wavelengths=np.asarray(wavelengths).tolist(), original_wavelength_units=wavelength_units,
                original_wavelength_indices=order.tolist())
    meta['solver'] = {'alpha': alpha, 'rcond': rcond, 'weights': [1.] * Y.shape[1] if weights is None else np.asarray(weights).tolist(),
        'weighting': 'equal' if weights is None else 'measured_diagonal_inverse_variance',
        'weight_evidence': meta.get('weight_evidence')}
    support = np.any(A != 0, axis=1)
    if wavelength_validity is not None:
        support = np.asarray(wavelength_validity)
        if support.dtype != np.bool_ or support.shape != (A.shape[0], A.shape[2]):
            raise ValueError('Declared wavelength_validity must be a region x wavelength boolean mask')
        support = support[:, order]
        tolerance = float(64 * np.finfo(float).eps * np.max(np.abs(A)) * singular[0] / singular[-1] * max(H.shape))
        if np.any(np.abs(np.where(support[:, None, :], 0, A)) > tolerance):
            raise ValueError('Declared unsupported columns have a measured nonzero response; model their contribution')
        A = np.where(support[:, None, :], A, 0)
        meta['declared_unsupported_arithmetic_tolerance'] = tolerance
    if meta.get('fwhm') is not None:
        fwhm_scale = wavelength_unit_scale(meta.get('fwhm_units', wavelength_units))
        if fwhm_scale is None:
            raise ValueError('Response bandwidth units must be known')
        meta['fwhm'] = (_positive(meta['fwhm'], len(wave), 'Response fwhm')[order] * fwhm_scale).tolist()
        meta['fwhm_units'] = 'nm'
    if meta.get('model') == 'direct_band':
        tolerance = np.max(np.abs(A)) * np.finfo(np.float64).eps * 32
        A[np.abs(A) <= tolerance] = 0
        meta['direct_arithmetic_zero_tolerance'] = float(tolerance)
    residual = np.einsum('rmk,kn->rmn', A, H) - Y
    meta['characterization'] = {'model': 'Y = A H', 'H_rank': rank, 'H_singular_values': singular.tolist(),
        'H_condition_number': float(singular[0] / singular[-1]), 'training_residuals': residual.tolist(),
        'validation_status': 'NOT_SUPPLIED', 'physical_validation': 'Not established by numerical fitting'}
    bundle = {'schema_version': 1, 'kind': 'spectral_response_bundle', 'bundle_id': str(uuid.uuid4()),
        'metadata': meta, 'A': A, 'region_map': np.asarray(region_map),
        'wavelength_validity': support, 'characterization_H': H, 'characterization_Y': Y}
    if (validation_Y is None) != (validation_H is None):
        raise ValueError('Both validation_Y and validation_H are required for held-out checks')
    if validation_H is not None:
        vh, vy = np.asarray(validation_H, float), np.asarray(validation_Y, float)
        if vy.ndim == 2:
            vy = vy[None, ...]
        if (vh.ndim != 2 or vh.shape[0] != len(wave) or vy.shape != (*Y.shape[:2], vh.shape[1]) or
                not np.isfinite(vh).all() or not np.isfinite(vy).all() or np.any(vh < 0)):
            raise ValueError('Held-out input/signal dimensions or finite values are invalid')
        vh = vh[order]
        bundle.update(validation_H=vh, validation_Y=vy)
        meta['characterization'].update(validation_status='NUMERIC_RESIDUAL_ONLY',
            validation_residuals=(np.einsum('rmk,kn->rmn', A, vh) - vy).tolist())
    checked = _validate(bundle)
    bundle['metadata'] = checked['metadata']
    bundle['metadata']['response_diagnostics'] = checked['diagnostics']
    return bundle


def save_response(bundle, path):
    """Create a new hashed numeric directory; never overwrite calibration assets."""
    checked = _validate(bundle)
    path = Path(path)
    if path.exists():
        raise FileExistsError('Response destination exists; choose a new directory')
    for name in ARRAYS:
        if name in bundle:
            value = np.asarray(bundle[name])
            if value.dtype.kind not in 'buif' or not np.isfinite(value).all():
                raise ValueError('Response assets must be finite real numeric arrays')
    path.mkdir(parents=True)
    manifest = {'schema_version': 1, 'kind': 'spectral_response_bundle', 'bundle_id': bundle['bundle_id'],
                'metadata': checked['metadata'], 'arrays': {}}
    for name in ARRAYS:
        if name not in bundle:
            continue
        value = checked.get(name, np.asarray(bundle[name]))
        if np.asarray(value).dtype.kind not in 'buif' or not np.isfinite(value).all():
            raise ValueError('Response assets must be finite real numeric arrays')
        target = path / f'{name}.npy'
        with target.open('xb') as stream:
            np.save(stream, value, allow_pickle=False)
            stream.flush()
            os.fsync(stream.fileno())
        with target.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        manifest['arrays'][name] = {'file': target.name, 'bytes': target.stat().st_size, 'sha256': digest}
    atomic_json(path / 'manifest.json', json.loads(_json(manifest)))
    return path


def load_response(path):
    """Read finite NPY assets from one allowlisted directory; never execute imports."""
    path = Path(path)
    manifest_path = path / 'manifest.json' if path.is_dir() else path
    directory = manifest_path.parent.resolve()
    if manifest_path.stat().st_size > 8 * 1024**2:
        raise ValueError('Response metadata exceeds the 8 MiB limit')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assets = manifest.get('arrays', {})
    if not isinstance(assets, dict) or not {'A', 'region_map', 'wavelength_validity'} <= set(assets) or not set(assets) <= set(ARRAYS):
        raise ValueError('Response contains missing or unknown numeric assets')
    if sum(record.get('bytes', 0) for record in assets.values()) > 2 * 1024**3:
        raise ValueError('Response numeric assets exceed the 2 GiB limit')
    if {p.name for p in directory.iterdir()} != {manifest_path.name} | {f'{name}.npy' for name in assets}:
        raise ValueError('Response directory contains undeclared files')
    bundle = {key: deepcopy(manifest[key]) for key in ('schema_version', 'kind', 'bundle_id', 'metadata')}
    for name, record in assets.items():
        if record.get('file') != f'{name}.npy':
            raise ValueError('Response assets must have their declared adjacent numeric filenames')
        target = directory / record['file']
        if target.is_symlink() or target.resolve().parent != directory or target.stat().st_size != record.get('bytes'):
            raise ValueError('Response asset path or byte count mismatch')
        with target.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != record.get('sha256'):
                raise ValueError('Response asset hash mismatch')
        bundle[name] = np.load(target, allow_pickle=False)
        if bundle[name].dtype.kind not in 'buif' or not np.isfinite(bundle[name]).all():
            raise ValueError('Response assets must be finite real numeric arrays')
    checked = _validate(bundle)
    bundle['metadata'] = checked['metadata']
    return bundle


def validate_reconstruction(scan, dark, bundle):
    """Validate declared applicability before allocating output; not H3 certification."""
    checked = _validate(bundle)
    meta, A = checked['metadata'], checked['A']
    if not isinstance(scan, Cube) or not isinstance(dark, Cube):
        raise ValueError('Reconstruction requires raw scan and dark Cubes')
    scan_synthetic, dark_synthetic = _synthetic_origin(scan.metadata), _synthetic_origin(dark.metadata)
    if scan_synthetic != dark_synthetic:
        raise ValueError('Synthetic and measured/unknown scan-dark origins cannot be mixed')
    evidence = meta['response_evidence']
    response_kind = evidence.get('kind') if isinstance(evidence, dict) else evidence
    response_synthetic = str(response_kind).upper() in {'SYNTHETIC', 'SYNTHETIC_MODEL_FROM_EXTERNAL_MEASURED_SPECTRA'} or _synthetic_origin(meta)
    if response_synthetic and not scan_synthetic:
        raise ValueError('An explicitly synthetic response cannot calibrate measured/unknown raw scans')
    expected_shape = (*meta['spatial_grid']['raw_shape_hw'], A.shape[1])
    exposures = []
    for name, cube in (('scan', scan), ('dark', dark)):
        if not isinstance(cube, Cube) or cube.shape != expected_shape:
            raise ValueError(f'{name} must match the native HW and complete response state count')
        source = cube.metadata
        if source.get('data_level') != 'raw_scan' or source.get('completed') is not True or source.get('partial') is not False:
            raise ValueError(f'{name} must be a completed non-partial raw_scan; no second reconstruction')
        if source.get('wavelengths') is not None or source.get('channel_labels') is not None:
            raise ValueError('Raw state rows must not masquerade as wavelength/color channels')
        if source.get('scan_states') != meta['state_ids']:
            raise ValueError(f'{name} state identity/order mismatch; no implicit row permutation')
        if source.get('signal_lineage') is not None:
            raise ValueError('Already processed signal cannot enter raw dark subtraction again')
        if source.get('spatial_grid') != meta['spatial_grid'] or source.get('pixel_format') != meta['pixel_format']:
            raise ValueError(f'{name} spatial grid/CFA/pixel-format mismatch')
        if source.get('units') != 'DN':
            raise ValueError('Raw reconstruction expects DN with explicit upstream correction ownership')
        if saturation_value(cube) is None:
            raise ValueError(f'{name} needs a known raw saturation threshold before reconstruction')
        exposure = _positive(source.get('exposure_s'), A.shape[1], f'{name} exposure_s')
        exposures.append(exposure)
        context = source.get('measurement_context', {})
        for key in ('instrument_id', 'temperature_condition_id'):
            if not _known(context.get(key)) or context[key] != meta['applicability'][key]:
                raise ValueError(f'{name} {key} applicability mismatch or unknown')
        for key in ('settings', 'gain', 'gain_units', 'optical_configuration'):
            if not _known(source.get(key)) or source[key] != meta['applicability'][key]:
                raise ValueError(f'{name} {key} applicability mismatch or unknown')
        if isinstance(source['gain'], (bool, np.bool_)) or not isinstance(source['gain'], Real):
            raise ValueError('Gain must not be a boolean')
        if meta['correction']['exposure_normalized']:
            _linearity(meta['correction'].get('linearity_evidence'), exposure, source['gain'])
        elif not np.array_equal(exposure, meta['correction']['exposure_s']):
            raise ValueError('Unnormalized response requires the exact characterized exposure vector')
    if not np.array_equal(exposures[0], exposures[1]):
        raise ValueError('Raw sample and blocked-light dark exposures must match before subtraction')
    dark_context = dark.metadata.get('measurement_context', {})
    if dark_context.get('role') != 'dark' or dark_context.get('light_blocked') is not True or not _known(dark_context.get('dark_method')):
        raise ValueError('Dark requires actual blocked-light role/method evidence')
    normalized = meta['correction']['exposure_normalized']
    if meta['signal_units'] != ('DN/s' if normalized else 'DN'):
        raise ValueError('Response signal units do not match declared exposure handling')
    return {'status': 'MATCH_RECORDED_APPLICABILITY', 'operator_signature': checked['operator_signature'],
            'shape': [*scan.shape[:2], A.shape[2]], 'exposure_normalized': normalized,
            'exposure_s': exposures[0].tolist(), 'diagnostics': checked['diagnostics'],
            'interpretation': 'Recorded source/response compatibility, not independent physical validation'}


def reconstruct_scan(scan, dark, bundle, *, output_path=None, stop=None, progress=None,
                     chunk_pixels=4096, memory_threshold_bytes=256 * 1024**2):
    """Subtract once and reconstruct a measured response on the native grid.

    Cancellation returns a partial Cube. Persistent products include an exact
    residual NPY; in-memory products expose ``cube.reconstruction_residual``.
    Use output_path to persist all auxiliary data rather than a lone Cube save.
    """
    applicability = validate_reconstruction(scan, dark, bundle)
    checked = _validate(bundle)
    if isinstance(chunk_pixels, bool) or not isinstance(chunk_pixels, int) or chunk_pixels < 1 or memory_threshold_bytes < 1:
        raise ValueError('Reconstruction chunk and memory limits must be positive')
    A, mapping, support = checked['A'], checked['region_map'], checked['wavelength_validity']
    cm = checked['metadata']
    h, w, m = scan.shape
    k, n = A.shape[2], h * w
    needed = n * (k * 9 + m * 8)
    if output_path is None and needed > memory_threshold_bytes:
        raise ValueError(f'Reconstruction needs {needed} output bytes; supply output_path')
    path = Path(output_path) if output_path is not None else None
    assets = None
    if path is not None:
        if path.suffix.lower() != '.npy':
            raise ValueError('Reconstruction output_path must end in .npy')
        assets = [path, path.with_suffix('.npy.valid.npy'), path.with_suffix('.npy.residual.npy'), path.with_suffix('.npy.json')]
        if any(p.exists() for p in assets):
            raise FileExistsError('Reconstruction output exists; preserve it and select a new path')
    from hyperlab.experiment_metadata import source_fingerprint
    fingerprints = [source_fingerprint(cube) for cube in (scan, dark)]
    normalized = applicability['exposure_normalized']
    lineage = {'schema_version': 1, 'domain': 'reconstructed_linear_signal', 'dark_subtracted': True,
        'exposure_normalized': normalized, 'exposure_units': 's', 'exposure_s': applicability['exposure_s'],
        'normalization_linearity_evidence': deepcopy(cm['correction'].get('linearity_evidence')),
        'response_bundle_id': bundle['bundle_id'], 'operator_signature': checked['operator_signature'],
        'spatial_grid': deepcopy(cm['spatial_grid']), 'state_order': list(cm['state_ids']),
        'input_source_ids': [item['source_id'] for item in fingerprints], 'raw_quality_propagated': True}
    context = deepcopy(scan.metadata.get('measurement_context', {}))
    context['response_calibration_id'] = bundle['bundle_id']
    meta = {key: deepcopy(scan.metadata.get(key)) for key in ('data_source', 'acquisition_source', 'display_mode', 'synthetic',
        'gain', 'gain_units', 'settings', 'optical_configuration', 'exposure', 'exposure_units', 'scan_recipe_id')}
    meta.update(data_level='spectral_cube', wavelengths=cm['wavelengths'], wavelength_units='nm',
        wavelength_source=cm['wavelength_source'], wavelength_evidence=cm.get('wavelength_evidence', 'declared'),
        units=cm['output_units'], linear_intensity=True, completed=False, partial=True, completed_pixels=0,
        shape=[h, w, k], axis_order='HWK', dtype='float64', schema_version=2,
        band_validity=support.any(axis=0).tolist(), signal_lineage=lineage, measurement_context=context,
        spatial_grid=deepcopy(cm['spatial_grid']), response_evidence=deepcopy(cm['response_evidence']),
        response_source=bundle['bundle_id'], calibration_source=bundle['bundle_id'],
        processing_steps=[{'operation': 'dark subtraction and measured-response reconstruction', 'exposure_normalized': normalized}],
        source_provenance={'scan': deepcopy(scan.metadata), 'dark': deepcopy(dark.metadata)},
        input_fingerprints=fingerprints, uncertainty={'status': 'not_computed', 'reason': 'No propagated noise/covariance model; spatial spread is not measurement uncertainty'},
        reconstruction={'method': 'weighted augmented least squares, unconstrained', 'operator_signature': checked['operator_signature'],
            'operator_definition': checked['operator_definition'], 'response_diagnostics': checked['diagnostics'],
            'applicability': applicability, 'residual_units': cm['signal_units'], 'residual_definition': 'A L - corrected state signal',
            'output_grid_size_is_not_independent_bands': True, 'physical_validation': 'NOT_ESTABLISHED_BY_COMPUTATION'},
        quality_counts={'total_pixels': n, 'processed_pixels': 0, 'unsupported_spatial_pixels': int(np.count_nonzero(mapping < 0)),
            'output_valid_per_wavelength': [0] * k, 'scan': {name: [0] * m for name in ('total', 'valid', 'invalid', 'ignored', 'saturated')},
            'dark': {name: [0] * m for name in ('total', 'valid', 'invalid', 'ignored', 'saturated')}})
    for key in ('fwhm', 'measurement_gaps_nm'):
        if cm.get(key) is not None:
            meta[key] = deepcopy(cm[key])
    if path is None:
        output, valid, residual = np.full((h, w, k), np.nan), np.zeros((h, w, k), bool), np.full((h, w, m), np.nan)
        meta['reconstruction']['residual_storage'] = 'in-memory reconstruction_residual attribute; output_path persists this array'
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        mappings = []
        try:
            for asset, dtype, shape in zip(assets, ('f8', bool, 'f8'), ((h, w, k), (h, w, k), (h, w, m))):
                mappings.append(np.lib.format.open_memmap(asset, mode='w+', dtype=dtype, shape=shape))
            output, valid, residual = mappings
            output[:] = np.nan
            valid[:] = False
            residual[:] = np.nan
        except BaseException as error:
            for mapped in mappings:
                try:
                    mapped._mmap.close()
                except BaseException as secondary:
                    error.add_note(f'Reconstruction allocation cleanup also failed: {secondary}')
            raise
        meta.update(source_file=str(path.resolve()), valid_mask_file=assets[1].name)
        meta['reconstruction'].update(residual_storage='adjacent NPY', residual_file=assets[2].name)
    flat_out, flat_valid, flat_residual = output.reshape(n, k), valid.reshape(n, k), residual.reshape(n, m)

    def checkpoint(*, bind_residual=False):
        if assets is not None:
            for array, asset in zip((output, valid, residual), assets):
                array.flush()
                with asset.open('r+b') as stream:
                    os.fsync(stream.fileno())
            if bind_residual:
                with assets[2].open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                meta['reconstruction']['residual_asset'] = {'file': assets[2].name,
                    'sha256': digest, 'bytes': assets[2].stat().st_size, 'shape': [h, w, m], 'dtype': 'float64',
                    'operator_signature': checked['operator_signature'], 'input_source_ids': lineage['input_source_ids'],
                    'completed_pixels': meta['completed_pixels']}
            atomic_json(assets[3], json.loads(_json(meta)))

    try:
        checkpoint()
        for batch, first in enumerate(range(0, n, chunk_pixels)):
            if stop is not None and (stop() if callable(stop) else stop.is_set()):
                meta['reconstruction']['cancelled'] = True
                break
            ids = np.arange(first, min(n, first + chunk_pixels))
            ys, xs = ids // w, ids % w
            selection = (ys, xs, slice(None))
            values, goods = [], []
            for role, cube in (('scan', scan), ('dark', dark)):
                raw = cube.data[selection]
                good, counts, _ = _quality(cube, raw, selection, policy='quantitative')
                values.append(_floating(raw, np.float64))
                goods.append(good)
                for name, mask in counts.items():
                    meta['quality_counts'][role][name] = (np.asarray(meta['quality_counts'][role][name]) + mask.sum(axis=0)).tolist()
            z = values[0] - values[1]
            if normalized:
                z = z / np.asarray(applicability['exposure_s'])[None, :]
            good = goods[0] & goods[1] & np.isfinite(z)
            for region, (selected, B) in enumerate(checked['operators']):
                member = np.flatnonzero(mapping[ys, xs] == region)
                if not len(member) or not len(selected):
                    continue
                if cm['model'] == 'multiplexed':
                    member = member[good[member].all(axis=1)]
                    if not len(member):
                        continue
                    signal = z[member] @ B.T
                    finite = np.isfinite(signal).all(axis=1)
                    member, signal = member[finite], signal[finite]
                    flat_out[np.ix_(ids[member], selected)] = signal
                    flat_valid[np.ix_(ids[member], selected)] = True
                    flat_residual[ids[member]] = signal @ A[region][:, selected].T - z[member]
                else:
                    for column in selected:
                        row = int(np.flatnonzero(A[region, :, column])[0])
                        used = member[good[member, row]]
                        signal = z[used, row] / A[region, row, column]
                        finite = np.isfinite(signal)
                        used, signal = used[finite], signal[finite]
                        flat_out[ids[used], column] = signal
                        flat_valid[ids[used], column] = True
                        flat_residual[ids[used], row] = signal * A[region, row, column] - z[used, row]
            meta['completed_pixels'] = int(ids[-1]) + 1
            meta['quality_counts']['processed_pixels'] = meta['completed_pixels']
            meta['quality_counts']['output_valid_per_wavelength'] = (np.asarray(meta['quality_counts']['output_valid_per_wavelength']) + flat_valid[ids].sum(axis=0)).tolist()
            if batch % 16 == 15:
                checkpoint()
            if progress is not None:
                progress(meta['completed_pixels'], n)
        if [source_fingerprint(cube) for cube in (scan, dark)] != fingerprints:
            raise ValueError('Source changed during reconstruction; completed product is withheld')
        complete = meta['completed_pixels'] == n
        meta.update(completed=complete, partial=not complete)
        meta['reconstruction']['completed_utc'] = datetime.now(timezone.utc).isoformat()
        checkpoint(bind_residual=True)
    except BaseException as error:
        meta.update(completed=False, partial=True)
        meta['reconstruction']['error'] = str(error)
        try:
            checkpoint(bind_residual=True)
        except BaseException as secondary:
            error.add_note(f'Partial reconstruction checkpoint also failed: {secondary}')
        if assets is not None:
            for array in (output, valid, residual):
                try:
                    array._mmap.close()
                except BaseException as secondary:
                    error.add_note(f'Reconstruction mapping cleanup also failed: {secondary}')
        raise
    result = Cube(output, meta, valid)
    if assets is not None:
        residual._mmap.close()
        result.reconstruction_residual = None
    else:
        result.reconstruction_residual = residual
    return result
