"""Reference ratios of explicitly corrected, compatible reconstructed signals."""
from copy import deepcopy
from numbers import Real
from pathlib import Path
import json
import os

import numpy as np

from hyperlab.analysis.applicability import _known, _text
from hyperlab.analysis.core import _blocks, _floating, _valid, calculation_dtype
from hyperlab.experiment_metadata import source_fingerprint
from hyperlab.io import Cube
from hyperlab.io.cube import _dumps, wavelength_unit_scale


def _positive(value):
    return (isinstance(value, Real) and not isinstance(value, (bool, np.bool_))
            and bool(np.isfinite(value)) and value > 0)


def _same(first, second):
    """Compare numeric metadata including NumPy vectors without ambiguous truth."""
    try:
        return json.loads(_dumps(first)) == json.loads(_dumps(second))
    except (TypeError, ValueError):
        return False


def validate_reflectance_corrected(sample, white, *, reference_reflectance=None,
        reference_source=None, minimum_denominator=1e-12, output_path=None,
        chunk_pixels=65536, memory_threshold_bytes=256 * 1024**2):
    """Inspect metadata/parameters without allocating output or hashing source arrays."""
    checks = []
    def check(role, field, valid, reason):
        checks.append({'role': role, 'field': field, 'status': 'MATCH' if valid else 'MISMATCH',
                       'reason': 'Compatible recorded evidence' if valid else reason})

    check('parameters', 'minimum_denominator', _positive(minimum_denominator),
          'Minimum denominator must be finite and positive in signal units')
    for key, value in (('chunk_pixels', chunk_pixels), ('memory_threshold_bytes', memory_threshold_bytes)):
        check('parameters', key, isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_))
              and value > 0, f'{key} must be a positive integer')
    k = sample.shape[2]
    if reference_reflectance is not None:
        try:
            reference = np.asarray(reference_reflectance, dtype=np.float64)
            valid = reference.shape == (k,) and np.isfinite(reference).all() and np.all((reference >= 0) & (reference <= 1))
        except (TypeError, ValueError):
            valid = False
        check('reference', 'reflectance', valid, 'Reference reflectance must be a finite K-vector in [0,1]')
        check('reference', 'source', _text(reference_source), 'A known reference spectrum requires a source record')

    lineages, contexts = [], []
    for role, cube in (('sample', sample), ('white', white)):
        meta = cube.metadata
        lineage = meta.get('signal_lineage')
        lineage = lineage if isinstance(lineage, dict) else {}
        lineages.append(lineage)
        check(role, 'domain', meta.get('data_level') == 'spectral_cube' and meta.get('linear_intensity') is True,
              'Requires a linear spectral signal, not an already-reflectance product')
        wave = cube.wavelengths
        ordered = wave is not None and np.all(wave > 0) and (np.all(np.diff(wave) > 0) or np.all(np.diff(wave) < 0))
        check(role, 'wavelengths', ordered and wavelength_unit_scale(meta.get('wavelength_units')) is not None
              and _text(meta.get('wavelength_source')), 'Requires documented positive ordered wavelengths with known length units')
        check(role, 'completion', meta.get('completed') is True and meta.get('partial') is False,
              'Requires completed, non-partial input signals')
        check(role, 'correction_ownership', type(lineage.get('schema_version')) is int
              and lineage.get('schema_version') == 1 and lineage.get('domain') == 'reconstructed_linear_signal'
              and lineage.get('dark_subtracted') is True and type(lineage.get('exposure_normalized')) is bool,
              'Requires typed reconstructed signal lineage with dark subtraction already applied')
        check(role, 'raw_quality', lineage.get('raw_quality_propagated') is True and cube.valid_mask is not None,
              'Requires an explicit propagated source-validity mask; reconstructed values are not raw ADC counts')
        for key in ('response_bundle_id', 'operator_signature'):
            check(role, key, _text(lineage.get(key)), f'Requires {key} source evidence')
        for key in ('input_source_ids', 'state_order'):
            value = lineage.get(key)
            check(role, key, isinstance(value, list) and bool(value) and all(_text(v) for v in value),
                  f'Requires retained {key}')
        exposures = lineage.get('exposure_s')
        states = lineage.get('state_order')
        exposure_valid = (lineage.get('exposure_units') == 's' and isinstance(exposures, list)
                          and bool(exposures) and all(_positive(v) for v in exposures)
                          and isinstance(states, list) and len(exposures) == len(states))
        check(role, 'exposure_s', exposure_valid, 'Requires finite positive seconds for every recorded state')
        gain = meta.get('gain')
        check(role, 'gain', isinstance(gain, Real) and not isinstance(gain, (bool, np.bool_))
              and np.isfinite(gain), 'Requires a known finite fixed gain; no dB division is performed')
        check(role, 'gain_units', _text(meta.get('gain_units')), 'Requires recorded gain units')
        check(role, 'settings', isinstance(meta.get('settings'), dict) and _known(meta['settings']),
              'Requires known acquisition settings')
        check(role, 'optical_configuration', _known(meta.get('optical_configuration')),
              'Requires recorded optical configuration')
        check(role, 'units', _text(meta.get('units')) and meta.get('units') != 'dimensionless',
              'Requires declared linear signal units')
        if lineage.get('exposure_normalized') is True:
            evidence = lineage.get('normalization_linearity_evidence')
            evidence = evidence if isinstance(evidence, dict) else {}
            bounds = evidence.get('exposure_range_s')
            valid = (evidence.get('verified') is True and _text(evidence.get('source'))
                     and isinstance(bounds, list) and len(bounds) == 2 and all(_positive(v) for v in bounds)
                     and bounds[0] <= bounds[1] and exposure_valid
                     and all(bounds[0] <= value <= bounds[1] for value in exposures)
                     and isinstance(evidence.get('gain'), Real) and not isinstance(evidence.get('gain'), (bool, np.bool_))
                     and evidence.get('gain') == gain)
            check(role, 'normalization_linearity', valid, 'Exposure normalization needs applicable range/fixed-gain evidence')
        grid = lineage.get('spatial_grid')
        grid = grid if isinstance(grid, dict) else {}
        pattern, origin = grid.get('cfa_pattern'), grid.get('cfa_pattern_origin')
        cfa_valid = ((pattern is None and origin == 'not_applicable') or
                     (isinstance(pattern, str) and pattern in ('RGGB', 'GRBG', 'GBRG', 'BGGR')
                      and origin in ('sensor', 'delivered')))
        grid_valid = (_text(grid.get('grid_id')) and isinstance(grid.get('raw_shape_hw'), (list, tuple))
                      and _same(grid.get('raw_shape_hw'), list(cube.shape[:2]))
                      and isinstance(grid.get('sensor_roi_offset'), (list, tuple)) and len(grid['sensor_roi_offset']) == 2
                      and all(isinstance(v, (int, np.integer)) and not isinstance(v, (bool, np.bool_))
                              and v >= 0 for v in grid['sensor_roi_offset'])
                      and type(grid.get('flip_x')) is bool and type(grid.get('flip_y')) is bool
                      and cfa_valid)
        check(role, 'spatial_grid', grid_valid, 'Requires the explicit native delivered spatial grid; no implicit registration')
        context = meta.get('measurement_context')
        context = context if isinstance(context, dict) else {}
        contexts.append(context)
        check(role, 'measurement_role', context.get('role') == role, f'Requires measurement role={role}')
        check(role, 'measurement_evidence', context.get('evidence_kind') in ('declared', 'documented', 'experimentally_verified')
              and _text(context.get('evidence_source')), 'Requires a source measurement-context record')

    for key in ('shape', 'wavelengths', 'wavelength_units', 'units', 'gain', 'gain_units', 'settings',
                'optical_configuration', 'fwhm', 'measurement_gaps_nm'):
        values = ([list(c.shape) for c in (sample, white)] if key == 'shape' else
                  [c.metadata.get(key) for c in (sample, white)])
        check('pair', key, _same(*values), f'Sample/white {key} mismatch; no implicit conversion')
    for key in ('operator_signature', 'spatial_grid', 'exposure_normalized', 'state_order'):
        check('pair', key, _same(lineages[0].get(key), lineages[1].get(key)), f'Sample/white {key} mismatch')
    support = [c.metadata.get('band_validity') for c in (sample, white)]
    support = [[True] * c.shape[2] if value is None else value for value, c in zip(support, (sample, white))]
    check('pair', 'spectral_support', _same(*support), 'Sample/white supported spectral basis differs')
    if lineages[0].get('exposure_normalized') is False:
        check('pair', 'fixed_exposure', lineages[0].get('exposure_s') == lineages[1].get('exposure_s'),
              'Unnormalized signals require matching state exposures; normalize explicitly first')
    for key in ('instrument_id', 'temperature_condition_id', 'illumination_id', 'geometry_id'):
        values = [context.get(key) for context in contexts]
        check('pair', key, all(_text(value) for value in values) and values[0] == values[1],
              f'Requires matching known source {key}; specimen treatment does not establish instrument conditions')
    origins = [c.metadata.get('acquisition_source') for c in (sample, white)]
    check('pair', 'synthetic_origin', ('SYNTHETIC' in origins) is False or origins[0] == origins[1],
          'Synthetic and measured operands cannot create a measured reflectance product')
    dtype = np.result_type(calculation_dtype(sample.data), calculation_dtype(white.data))
    needed = int(np.prod(sample.shape)) * (dtype.itemsize + 1)
    check('output', 'budget', output_path is not None or (_positive(memory_threshold_bytes) and needed <= memory_threshold_bytes),
          f'Requires {needed} output bytes; provide output_path for bounded-memory output')
    if output_path is not None:
        path = Path(output_path)
        targets = (path, path.with_suffix('.npy.valid.npy'), path.with_suffix('.npy.json'))
        check('output', 'path', path.suffix.lower() == '.npy' and not any(p.exists() for p in targets),
              'Choose a new .npy path; existing results are never overwritten')
    allowed = all(item['status'] == 'MATCH' for item in checks)
    return {'schema_version': 1, 'status': 'MATCH' if allowed else 'MISMATCH', 'allowed': allowed,
            'checks': checks, 'output_bytes': needed, 'dtype': str(dtype),
            'interpretation': 'Recorded compatibility only; not physical validation or monochromatic reflectance truth'}


def reflectance_corrected(sample, white, *, reference_reflectance=None, reference_source=None,
        minimum_denominator=1e-12, output_path=None, stop=None, progress=None,
        chunk_pixels=65536, memory_threshold_bytes=256 * 1024**2):
    """Pixel reference ratio; no additional dark/exposure/gain correction.

    stop is an optional threading.Event. Progress receives checkpoint dictionaries.
    Cancellation/failure preserves a masked partial prefix when output_path is set.
    """
    preflight = validate_reflectance_corrected(sample, white, reference_reflectance=reference_reflectance,
        reference_source=reference_source, minimum_denominator=minimum_denominator,
        output_path=output_path, chunk_pixels=chunk_pixels, memory_threshold_bytes=memory_threshold_bytes)
    if not preflight['allowed']:
        raise ValueError('; '.join(f"{c['role']}.{c['field']}: {c['reason']}"
                                  for c in preflight['checks'] if c['status'] != 'MATCH'))
    def cancelled():
        if stop is not None and stop.is_set():
            raise InterruptedError('Reference ratio cancelled; any saved prefix remains partial')
    cancelled()
    fingerprints = {role: source_fingerprint(cube) for role, cube in (('sample', sample), ('white', white))}
    cancelled()
    dtype = np.dtype(preflight['dtype'])
    k = sample.shape[2]
    reference = np.ones(k) if reference_reflectance is None else np.asarray(reference_reflectance, dtype=float).copy()
    retained = ('wavelengths', 'wavelength_units', 'wavelength_source', 'wavelength_evidence', 'fwhm', 'measurement_gaps_nm',
                'band_validity', 'measurement_context', 'data_source', 'acquisition_source', 'display_mode', 'device', 'runtime')
    meta = {key: deepcopy(sample.metadata[key]) for key in retained if key in sample.metadata}
    meta.update(data_level='reflectance_cube', units='dimensionless',
        spatial_grid=deepcopy(sample.metadata['signal_lineage']['spatial_grid']),
        reflectance_kind='relative' if reference_reflectance is None else 'reference-calibrated',
        reference_reflectance=reference.tolist(), reference_source=reference_source,
        source_provenance={role: deepcopy(c.metadata) for role, c in (('sample', sample), ('white', white))},
        source_fingerprints=fingerprints, reference_applicability=preflight,
        processing_steps=[{'operation': 'corrected signal reference ratio', 'minimum_denominator': minimum_denominator,
            'denominator_units': sample.metadata['units'], 'clipped': False, 'additional_dark_subtraction': False,
            'additional_exposure_normalization': False, 'operator_signature': sample.metadata['signal_lineage']['operator_signature'],
            'spatial_grid': deepcopy(sample.metadata['signal_lineage']['spatial_grid']), 'estimator': 'pixel ratio before ROI summary'}],
        uncertainty={'status': 'not_computed', 'reason': 'Requires an explicit input covariance/model including shared references; spatial spread is not uncertainty'},
        interpretation='Relative/reference-calibrated reconstructed effective-band factor; not monochromatic point truth or physical certification',
        denominator_guard='Numerical guard in signal units; not a measured low-signal qualification',
        completed=False, partial=True, completed_pixels=0, total_pixels=int(np.prod(sample.shape[:2])),
        phase='computing', calculation_dtype=str(dtype), axis_order='HWK', shape=list(sample.shape),
        quality_counts={key: 0 for key in ('processed_values', 'input_invalid', 'low_denominator', 'nonfinite_result', 'valid', 'negative', 'above_one')},
        valid_count_by_band=[0] * k)
    _dumps(meta)
    return _calculate_ratio(sample, white, meta, reference, output_path=output_path,
        minimum_denominator=minimum_denominator, chunk_pixels=chunk_pixels, stop=stop, progress=progress)


def _calculate_ratio(sample, white, meta, reference, *, output_path, minimum_denominator,
                     chunk_pixels, stop, progress, backgrounds=()):
    """Shared bounded numeric engine after route-specific applicability checks.

    Optional backgrounds are raw matched on/off inputs. Their validity is checked
    before subtraction. Without them, inputs already own all raw corrections.
    """
    k = sample.shape[2]
    dtype = np.dtype(meta['calculation_dtype'])
    fingerprints = meta['source_fingerprints']
    sources = [('sample', sample), ('white', white)]
    sources += list(zip(('background_sample', 'background_white'), backgrounds))
    def cancelled():
        if stop is not None and stop.is_set():
            raise InterruptedError('Reference ratio cancelled; any saved prefix remains partial')
    cancelled()
    checkpoint = None
    output = validity = None
    if output_path is not None:
        path = Path(output_path)
        mask_path, checkpoint = path.with_suffix('.npy.valid.npy'), path.with_suffix('.npy.json')
        meta.update(source_file=str(path.resolve()), valid_mask_file=mask_path.name, storage='out-of-core NPY')

    def persist():
        if checkpoint is not None:
            output.flush()
            validity.flush()
            for target in (path, mask_path):
                with target.open('r+b') as stream:
                    os.fsync(stream.fileno())
            temporary = checkpoint.with_suffix(checkpoint.suffix + '.tmp')
            with temporary.open('w', encoding='utf-8') as stream:
                stream.write(_dumps(meta))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(checkpoint)

    try:
        if checkpoint is None:
            output = np.full(sample.shape, np.nan, dtype=dtype)
            validity = np.zeros(sample.shape, dtype=bool)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            output = np.lib.format.open_memmap(path, mode='w+', dtype=dtype, shape=sample.shape)
            validity = np.lib.format.open_memmap(mask_path, mode='w+', dtype=bool, shape=sample.shape)
            validity[:] = False
        flat_out, flat_valid = output.reshape(-1, k), validity.reshape(-1, k)
        # Validity was propagated in the raw domain. Reconstructed values must
        # not be reinterpreted using any inherited ADC/ignore-value thresholds.
        numeric = ([sample, white] if backgrounds else
                   [Cube(c.data, {'band_validity': c.metadata.get('band_validity')}, c.valid_mask)
                    for c in (sample, white)])
        policy = 'quantitative' if backgrounds else 'diagnostic'
        persist()
        for indices, selection, numerator, good in _blocks(numeric[0], chunk_pixels, policy):
            cancelled()
            denominator = _floating(white.data[selection], dtype=dtype)
            white_good = _valid(numeric[1], white.data[selection], selection, policy)
            if backgrounds:
                numerator = _floating(numerator, dtype=dtype).copy()
                numerator -= _floating(backgrounds[0].data[selection], dtype=dtype)
                denominator = denominator - _floating(backgrounds[1].data[selection], dtype=dtype)
                good &= _valid(backgrounds[0], backgrounds[0].data[selection], selection, policy)
                white_good &= _valid(backgrounds[1], backgrounds[1].data[selection], selection, policy)
                good &= np.isfinite(numerator)
                white_good &= np.isfinite(denominator)
                bounds = meta.get('qualified_raw_dn_range')
                if bounds is not None:
                    for source, validity_part in ((sample,good),(backgrounds[0],good),(white,white_good),(backgrounds[1],white_good)):
                        raw = source.data[selection]
                        validity_part &= (raw >= bounds[0]) & (raw <= bounds[1])
                summary = meta['white_signal']
                summary['sum_dn'] = (np.asarray(summary['sum_dn']) + np.where(white_good, denominator, 0).sum(axis=0)).tolist()
                summary['count'] = (np.asarray(summary['count']) + white_good.sum(axis=0)).tolist()
            good &= white_good
            counts = meta['quality_counts']
            counts['processed_values'] += int(good.size)
            counts['input_invalid'] += int(np.count_nonzero(~good))
            low = good & (denominator < minimum_denominator)
            counts['low_denominator'] += int(np.count_nonzero(low))
            good &= ~low
            values = np.full(numerator.shape, np.nan, dtype=dtype)
            with np.errstate(divide='ignore', over='ignore', invalid='ignore'):
                np.divide(numerator, denominator, out=values, where=good)
                values *= reference
            finite = np.isfinite(values)
            counts['nonfinite_result'] += int(np.count_nonzero(good & ~finite))
            good &= finite
            values[~good] = np.nan
            flat_out[indices], flat_valid[indices] = values, good
            counts['valid'] += int(np.count_nonzero(good))
            counts['negative'] += int(np.count_nonzero(good & (values < 0)))
            counts['above_one'] += int(np.count_nonzero(good & (values > 1)))
            meta['valid_count_by_band'] = (np.asarray(meta['valid_count_by_band']) + good.sum(axis=0)).tolist()
            meta['completed_pixels'] = int(indices[-1]) + 1
            persist()
            if progress:
                progress(deepcopy({key: meta[key] for key in ('phase', 'completed_pixels', 'total_pixels', 'quality_counts')}))
        cancelled()
        if any(source_fingerprint(cube) != fingerprints[role] for role, cube in sources):
            validity[:] = False
            meta['quality_counts']['source_invalidated'] = meta['quality_counts']['valid']
            meta['invalidated_quality_counts'] = {key: meta['quality_counts'][key] for key in ('negative', 'above_one')}
            meta['quality_counts']['valid'] = 0
            meta['quality_counts']['negative'] = meta['quality_counts']['above_one'] = 0
            meta['valid_count_by_band'] = [0] * k
            meta['source_integrity'] = 'changed; all computed values invalidated'
            raise ValueError('Source changed during reference ratio; result is not accepted')
        meta.update(completed=True, partial=False, phase='complete')
        persist()
        return Cube(output, meta, validity)
    except BaseException as error:
        meta.update(completed=False, partial=True,
                    phase='cancelled' if isinstance(error, InterruptedError) else 'failed', error=str(error))
        try:
            if output is not None and validity is not None:
                persist()
        except Exception as persistence_error:
            error.add_note(f'Partial checkpoint could not be updated: {persistence_error}')
        if checkpoint is not None:
            for array in (output, validity):
                if array is not None:
                    array._mmap.close()
        raise
