"""Finite illumination-band ratios, without a fabricated native response matrix."""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import json
import os

import numpy as np

from hyperlab.acquisition.sequence import atomic_json
from hyperlab.acquisition.session import ScanWriter
from hyperlab.analysis.applicability import _text
from hyperlab.analysis.core import saturation_value, roi_statistics
from hyperlab.experiment_metadata import source_fingerprint
from hyperlab.io import Cube, load_cube
from .reflectance import _positive, _same, _calculate_ratio
from .response import _grid, _synthetic_origin


def validate_external_bands(sample, white, background_sample, background_white, setup, *,
                            minimum_denominator=1, output_path=None, chunk_pixels=65536):
    """Validate recorded finite-band applicability, not physical certification."""
    k = sample.shape[2]
    bands = setup.get('bands')
    if not isinstance(bands, list) or len(bands) != k:
        raise ValueError('One actual source-band record is required per observation')
    for band in bands:
        if not isinstance(band, dict) or not _text(band.get('band_id')) or not _text(band.get('source_evidence')):
            raise ValueError('Each source band needs an identity and characterization evidence')
        support = band.get('support_nm')
        peak, fwhm = band.get('source_peak_nm'), band.get('source_fwhm_nm')
        if (not isinstance(support, list) or len(support) != 2 or not all(_positive(v) for v in support)
                or support[0] >= support[1] or not _positive(peak) or not support[0] <= peak <= support[1]
                or not _positive(fwhm) or fwhm > support[1]-support[0]):
            raise ValueError('Source peak, positive measured bandwidth and support in nm are required')
        spectrum = band.get('source_spectrum', {})
        wave = np.asarray(spectrum.get('wavelength_nm', []), float)
        power = np.asarray(spectrum.get('relative_power', []), float)
        if (wave.ndim != 1 or len(wave) < 3 or power.shape != wave.shape or not np.isfinite(wave).all()
                or not np.isfinite(power).all() or np.any(np.diff(wave) <= 0) or np.any(power < 0)
                or not np.any(power > 0) or wave[0] > support[0] or wave[-1] < support[1]):
            raise ValueError('Retain the characterized source spectrum covering the declared support')
    definitions = {}
    for band in bands:
        if band['band_id'] in definitions and not _same(definitions[band['band_id']],band):
            raise ValueError('A repeated source-band identity must retain the same characterized profile/support')
        definitions[band['band_id']] = band
    steps = setup.get('step_ids')
    if (not isinstance(steps, list) or len(steps) != k or not all(_text(s) for s in steps) or len(set(steps)) != k):
        raise ValueError('Unique measurement step_ids must match K; a source band may recur')
    if setup.get('acquisition_mode') != 'external_illumination_band_scan':
        raise ValueError('This route implements external illumination bands only')
    for key in ('fixed_internal_state', 'geometry', 'illumination_stability', 'elastic_reflection_evidence'):
        if not _text(setup.get(key)):
            raise ValueError(f'Record {key}; unknown changing optics/geometry cannot cancel in a ratio')
    if setup.get('background_kind') not in ('source_off_ambient_plus_dark', 'lens_blocked_detector_dark'):
        raise ValueError('Declare source-off ambient plus dark or physically lens-blocked detector dark')
    if setup['background_kind'] == 'lens_blocked_detector_dark' and not _text(setup.get('ambient_evidence')):
        raise ValueError('Blocked-dark subtraction leaves ambient light; document ambient control')
    if not _positive(minimum_denominator) or isinstance(chunk_pixels, bool) or not isinstance(chunk_pixels, int) or chunk_pixels < 1:
        raise ValueError('Positive minimum white DN and integer chunk size are required')
    cubes = (sample, white, background_sample, background_white)
    numerator_role = setup.get('numerator_role', 'sample')
    if numerator_role not in ('sample', 'check', 'white'):
        raise ValueError('Numerator must be a sample, independent check or repeated white observation')
    roles = (numerator_role, 'white', 'background_'+numerator_role, 'background_white')
    if len({_synthetic_origin(c.metadata) for c in cubes}) != 1:
        raise ValueError('Synthetic and measured/unknown source operands cannot be mixed')
    origins = {c.metadata.get('acquisition_source') for c in cubes}
    if len(origins)!=1 or not origins <= {'LIVE','SYNTHETIC','EXTERNAL_MEASURED'}:
        raise ValueError('All four operands need the same declared measured or synthetic acquisition origin')
    for role, cube in zip(roles, cubes):
        meta = cube.metadata
        if (cube.shape != sample.shape or meta.get('data_level') != 'raw_scan' or meta.get('units') != 'DN'
                or meta.get('completed') is not True or meta.get('partial') is not False
                or cube.wavelengths is not None or meta.get('signal_lineage') or meta.get('processing_steps')):
            raise ValueError(f'{role}: requires complete matching raw DN observations with no prior background correction')
        if saturation_value(cube) is None:
            raise ValueError(f'{role}: record the raw saturation threshold')
        grid = _grid(meta.get('spatial_grid'))
        if grid['raw_shape_hw'] != list(cube.shape[:2]):
            raise ValueError(f'{role}: spatial grid does not match raw data')
        if meta.get('scan_states') != [band['band_id'] for band in bands]:
            raise ValueError(f'{role}: source-band order differs; no implicit sorting or repeat averaging')
        if [s.get('step_id') for s in meta.get('scan_steps',[])] != steps:
            raise ValueError(f'{role}: explicit step order differs from the measurement pairing')
        context = meta.get('measurement_context', {})
        if context.get('role') != role or not _text(context.get('evidence_source')) or not _text(context.get('observation_id')):
            raise ValueError(f'{role}: explicit measurement/background role and source record are required')
        if role.startswith('background') and context.get('background_kind') != setup['background_kind']:
            raise ValueError(f'{role}: background ownership differs from the setup')
        for key in ('instrument_id', 'geometry_id', 'fixed_internal_state_id', 'illumination_id', 'temperature_condition_id'):
            if not _text(context.get(key)) or context[key] != sample.metadata['measurement_context'].get(key):
                raise ValueError(f'{role}: incompatible or unknown {key}')
        for key in ('pixel_format', 'spatial_grid', 'exposure_s', 'gain', 'gain_units', 'settings'):
            if meta.get(key) is None or not _same(meta[key], sample.metadata.get(key)):
                raise ValueError(f'{role}: fixed {key} mismatch; this route performs no exposure/gain normalization')
        exposure = meta.get('exposure_s')
        if not isinstance(exposure, list) or len(exposure) != k or not all(_positive(v) for v in exposure) or len(set(exposure)) != 1:
            raise ValueError('Initial external measurement requires one fixed exposure across all bands and roles')
    settings = sample.metadata['settings']
    if isinstance(sample.metadata['gain'],bool) or not isinstance(sample.metadata['gain'],(int,float)) or not np.isfinite(sample.metadata['gain']) or not _text(sample.metadata['gain_units']):
        raise ValueError('Record finite fixed gain and its units; no dB division is performed')
    fixed = isinstance(settings, dict) and all(settings.get(key) == 'Off' for key in ('ExposureAuto','GainAuto','BalanceWhiteAuto','BlackLevelAuto'))
    processor_linear = fixed and settings.get('LUTEnable') is False and (settings.get('GammaEnable') is False or settings.get('Gamma') == 1)
    empirical = setup.get('linearity', {})
    if not processor_linear:
        bounds = empirical.get('exposure_range_s', [])
        dn_bounds = empirical.get('raw_dn_range', [])
        if (not fixed or empirical.get('kind') != 'measured_exposure_series' or not _text(empirical.get('source'))
                or len(bounds) != 2 or not all(_positive(v) for v in bounds) or not bounds[0] <= sample.metadata['exposure_s'][0] <= bounds[1]
                or len(dn_bounds) != 2 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and np.isfinite(v) for v in dn_bounds)
                or not 0 <= dn_bounds[0] < dn_bounds[1]
                or empirical.get('gain') != sample.metadata['gain'] or not _same(empirical.get('settings'), settings)
                or isinstance(empirical.get('maximum_residual_fraction'),bool)
                or not isinstance(empirical.get('maximum_residual_fraction'),(int,float))
                or not np.isfinite(empirical['maximum_residual_fraction']) or empirical['maximum_residual_fraction']<0
                or not _positive(empirical.get('predeclared_limit_fraction'))
                or empirical['maximum_residual_fraction'] > empirical['predeclared_limit_fraction']):
            raise ValueError('Requires fixed processing or an applicable measured exposure-series result and predeclared criterion')
    reference = setup.get('reference')
    if reference is not None:
        factors = np.asarray(reference.get('factors', []), float)
        if factors.shape != (k,) or not np.isfinite(factors).all() or np.any((factors <= 0) | (factors > 1)) or not _text(reference.get('source')):
            raise ValueError('Reference factors need a characterized positive K-vector in (0,1] and source')
        if reference.get('kind') == 'constant_over_support':
            bounds = reference.get('support_nm', [])
            if len(bounds) != 2 or not all(_positive(v) for v in bounds) or any(b['support_nm'][0] < bounds[0] or b['support_nm'][1] > bounds[1] for b in bands):
                raise ValueError('Reference constancy evidence must cover every actual source support')
            if not _text(reference.get('constancy_evidence')):
                raise ValueError('A nominal-center factor does not establish reference constancy over a band')
        elif reference.get('kind') == 'effective_kernel_weighted':
            if not _text(reference.get('kernel_evidence')) or not _text(reference.get('integration_evidence')):
                raise ValueError('Effective reference factors require the actual detector/source kernel and integration evidence')
        else:
            raise ValueError('Nominal-center reference values alone cannot calibrate arbitrary finite bands')
    needed = int(np.prod(sample.shape)) * 9
    if output_path is None and needed > 256 * 1024**2:
        raise ValueError('Provide output_path for bounded-memory external-band output')
    if output_path is not None:
        path = Path(output_path)
        if path.suffix.lower() != '.npy' or any(p.exists() for p in (path, path.with_suffix('.npy.json'), path.with_suffix('.npy.valid.npy'))):
            raise ValueError('Choose a new .npy output path')
    return dict(allowed=True, status='MATCH', quantity='effective finite-band factor' if reference else 'relative reference ratio',
        source_bands=deepcopy(bands), step_ids=list(steps), wavelength_inference=False,
        qualified_raw_dn_range=None if processor_linear else list(empirical['raw_dn_range']),
        interpretation='Source peak/support are known inputs; effective detector-weighted bandpass remains uncharacterized')


def external_band_ratio(sample, white, background_sample, background_white, setup, *,
                        minimum_denominator=1, output_path=None, chunk_pixels=65536, stop=None, progress=None):
    check = validate_external_bands(sample, white, background_sample, background_white, setup,
        minimum_denominator=minimum_denominator, output_path=output_path, chunk_pixels=chunk_pixels)
    k = sample.shape[2]
    reference = setup.get('reference')
    meta = dict(data_level='band_ratio_cube', units='dimensionless', acquisition_mode=setup['acquisition_mode'],
        data_source=sample.metadata['data_source'], acquisition_source=sample.metadata['acquisition_source'],
        synthetic=_synthetic_origin(sample.metadata), spatial_grid=deepcopy(sample.metadata['spatial_grid']),
        spectral_bands=deepcopy(setup['bands']), measurement_step_ids=setup['step_ids'], wavelengths=None,
        axis_kind='illumination_band', reference_applicability=check, measurement_setup=deepcopy(setup),
        qualified_raw_dn_range=check['qualified_raw_dn_range'],
        reflectance_kind='effective-band reference-calibrated' if reference else 'relative',
        source_provenance={role:deepcopy(c.metadata) for role,c in zip(('sample','white','background_sample','background_white'),(sample,white,background_sample,background_white))},
        source_fingerprints={role:source_fingerprint(c) for role,c in zip(('sample','white','background_sample','background_white'),(sample,white,background_sample,background_white))},
        processing_steps=[dict(operation='matched raw background subtraction then pixelwise reference ratio',
            background_kind=setup['background_kind'], background_subtractions=1, exposure_normalizations=0,
            estimator='pixel ratio before ROI summary', clipped=False, minimum_denominator_dn=minimum_denominator)],
        interpretation=check['interpretation'], uncertainty={'status':'not_computed','reason':'Spatial SD is pixel dispersion, not measurement uncertainty'},
        completed=False, partial=True, completed_pixels=0, total_pixels=int(np.prod(sample.shape[:2])), phase='computing',
        calculation_dtype='float64', axis_order='HWK', shape=list(sample.shape),
        quality_counts={key:0 for key in ('processed_values','input_invalid','low_denominator','nonfinite_result','valid','negative','above_one')},
        valid_count_by_band=[0]*k, white_signal={'sum_dn':[0.]*k,'count':[0]*k})
    factors = np.ones(k) if reference is None else np.asarray(reference['factors'],float)
    return _calculate_ratio(sample,white,meta,factors,output_path=output_path,minimum_denominator=minimum_denominator,
        chunk_pixels=chunk_pixels,stop=stop,progress=progress,backgrounds=(background_sample,background_white))


def band_diagnostics(product, *, roi=None):
    meta = product.metadata
    if meta.get('data_level') != 'band_ratio_cube':
        raise ValueError('Open an external-band ratio product')
    white = meta['white_signal']
    means = np.divide(white['sum_dn'], white['count'], out=np.full(product.shape[2],np.nan),where=np.asarray(white['count'])>0)
    rows = [dict(step_id=step, band_id=band['band_id'], source_peak_nm=band['source_peak_nm'],
        source_support_nm=band['support_nm'], source_fwhm_nm=band['source_fwhm_nm'],
        white_mean_dn=float(value) if np.isfinite(value) else None, white_valid_count=int(white['count'][i]),
        valid_ratio_count=int(meta['valid_count_by_band'][i]),
        invalid_ratio_fraction=1-meta['valid_count_by_band'][i]/int(np.prod(product.shape[:2])))
        for i,(step,band,value) in enumerate(zip(meta['measurement_step_ids'],meta['spectral_bands'],means))]
    result = dict(bands=rows, white_support='Raw-policy-valid pixels per band; not independent specimens',
                  effective_detector_bandpass='uncharacterized', independent_reference='NOT_TESTED')
    if roi is not None:
        stats = roi_statistics(product,roi,policy='quantitative')
        result['roi'] = dict(rect=stats['rect'], mean=[float(v) if np.isfinite(v) else None for v in stats['mean']],
            spatial_sd=[float(v) if np.isfinite(v) else None for v in stats['std']], count=stats['count'].tolist())
    return result


def pack_band_observation(manifest_path, directory):
    """Retain individually saved raw planes as explicitly confirmed manual steps.

    This imports observations; it does not certify the operator's band placement
    or claim device-trigger synchronization. Original frames remain unchanged.
    """
    manifest_path = Path(manifest_path)
    spec = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    frames, meta = spec['frames'], deepcopy(spec['metadata'])
    if not frames or len({f['step_id'] for f in frames}) != len(frames):
        raise ValueError('Manual observations require unique step IDs')
    meta.update(scan_states=[f['band_id'] for f in frames],
                scan_steps=[{key:f[key] for key in ('step_id','band_id','confirmation')} for f in frames],
                acquisition_mode='external_illumination_band_scan', scan_association='manual placement confirmation; not hardware-trigger proof')
    identities = set()
    writer = mask = None
    try:
        for record in frames:
            if not _text(record.get('confirmation')):
                raise ValueError('Each manually placed source band needs its actual confirmation record')
            with load_cube(manifest_path.parent/record['path']) as frame:
                actual = frame.metadata
                if frame.shape[2] != 1 or actual['data_level'] != 'raw_frame' or actual.get('valid') is not True:
                    raise ValueError('Import complete single raw sensor planes only')
                if actual.get('buffer_complete') is not True:
                    raise ValueError('Manual observations require a complete camera buffer receipt')
                fingerprint = source_fingerprint(frame)
                identity = (actual.get('session_id'), actual.get('stream_epoch'), actual.get('frame_id'))
                if any(v is None for v in identity) or identity in identities:
                    raise ValueError('Retain distinct actual session/stream/frame identities for manual observations')
                identities.add(identity)
                if writer is None:
                    meta['exposure_s'] = [actual['exposure_us']/1e6]*len(frames)
                    meta['gain'] = actual['gain']
                    meta['settings'] = deepcopy(actual['readback_settings'])
                    meta['pixel_format'] = actual['pixel_format']
                    meta['saturation_value'] = saturation_value(frame)
                    meta['valid_mask_file'] = 'cube.npy.valid.npy'
                    writer = ScanWriter(directory,(*frame.shape[:2],len(frames)),frame.data.dtype,
                        source=actual['acquisition_source'],metadata=meta,checkpoint_frames=1)
                    mask_path=Path(directory)/meta['valid_mask_file']
                    mask=np.lib.format.open_memmap(mask_path,mode='w+',dtype=bool,shape=(len(frames),*frame.shape[:2]))
                    mask[:]=False
                if (actual['exposure_us']/1e6 != meta['exposure_s'][0] or actual['gain'] != meta['gain']
                        or not _same(actual['readback_settings'],meta['settings']) or actual['pixel_format'] != meta['pixel_format']
                        or actual['acquisition_source'] != writer.meta['acquisition_source']):
                    raise ValueError('Manual frame settings/source changed; observations cannot share this fixed profile')
                grid = _grid(meta['spatial_grid'])
                if grid['raw_shape_hw'] != list(frame.shape[:2]):
                    raise ValueError('Manual observation grid shape differs from the raw frame')
                for key in ('sensor_roi_offset','flip_x','flip_y','cfa_pattern','cfa_pattern_origin'):
                    if not _same(actual.get(key),grid[key]):
                        raise ValueError(f'Manual frame {key} differs from the declared delivered grid')
                valid=frame.valid_mask
                mask[writer.meta['frame_count']]=True if valid is None else valid if valid.ndim==2 else valid[:,:,0]
                mask.flush()
                with mask_path.open('r+b') as stream:os.fsync(stream.fileno())
                writer.append(frame.data[:,:,0],dict(actual,step_id=record['step_id'],target_state=record['band_id'],
                    returned_state=None,manual_confirmation=record['confirmation'],source_fingerprint=fingerprint))
                if source_fingerprint(frame) != fingerprint:
                    raise ValueError('Raw source changed during manual import')
        return {'raw_path':str(writer.finish().resolve()),'completed':True,'association':meta['scan_association']}
    except BaseException as error:
        if writer is not None:
            try:
                writer.finish(error=str(error))
            except Exception as persistence_error:
                error.add_note(f'Manual import finalization also failed: {persistence_error}')
        raise
    finally:
        if mask is not None:
            mask._mmap.close()


def process_external_bands(manifest_path, directory, *, stop=None, progress=None, inspect_only=False):
    """Process explicitly paired saved observations; never open hardware."""
    manifest_path, directory = Path(manifest_path), Path(directory)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    setup, files = manifest['setup'], manifest['inputs']
    if not inspect_only and directory.exists():
        raise FileExistsError('Processing destination exists; choose a new directory')
    with ExitStack() as stack:
        cubes = [stack.enter_context(load_cube(manifest_path.parent/files[role]))
                 for role in ('sample','white','background_sample','background_white')]
        minimum = manifest['minimum_white_dn']
        check = validate_external_bands(*cubes,setup,minimum_denominator=minimum,
            output_path=None if inspect_only else directory/'band-ratios.npy')
        if inspect_only:
            return check
        directory.mkdir(parents=True)
        report = dict(completed=False,partial=True,phase='PROCESSING',manifest=str(manifest_path.resolve()))
        primary_error = None
        try:
            with external_band_ratio(*cubes,setup,minimum_denominator=minimum,
                    output_path=directory/'band-ratios.npy',stop=stop,progress=progress) as product:
                diagnostics = band_diagnostics(product,roi=manifest.get('roi'))
                roi = manifest.get('roi') or [0,0,product.shape[1],product.shape[0]]
                for name, role in (('repeat_white','white'),('check','check')):
                    if name not in files:
                        continue
                    observed = stack.enter_context(load_cube(manifest_path.parent/files[name]))
                    background = stack.enter_context(load_cube(manifest_path.parent/files['background_'+name]))
                    if observed.metadata.get('measurement_context',{}).get('observation_id') == cubes[1].metadata['measurement_context']['observation_id']:
                        raise ValueError('A reference cannot independently check itself or serve as its own repeat')
                    comparison_setup = dict(setup,numerator_role=role)
                    if name == 'repeat_white':
                        comparison_setup.pop('reference',None)
                    with external_band_ratio(observed,cubes[1],background,cubes[3],comparison_setup,
                            minimum_denominator=minimum,output_path=directory/(name+'-ratios.npy'),stop=stop,progress=progress) as comparison:
                        stats = roi_statistics(comparison,roi,policy='quantitative',support='common')
                        values = stats['mean']
                        entry = dict(roi=roi,count=stats['count'].tolist(),
                            mean=[float(v) if np.isfinite(v) else None for v in values],
                            definition='Mean of pixel ratios on common ROI support; reference covariance not estimated')
                        if name == 'repeat_white':
                            entry['drift_fraction'] = [float(v-1) if np.isfinite(v) else None for v in values]
                        elif manifest.get('check_reference'):
                            truth = manifest['check_reference']
                            expected = np.asarray(truth.get('values',[]),float)
                            if (expected.shape != values.shape or not np.isfinite(expected).all()
                                    or not _same(truth.get('bands'),setup['bands']) or not _text(truth.get('source'))
                                    or truth.get('quantity') != product.metadata['reflectance_kind']
                                    or not _text(truth.get('matched_geometry_and_kernel_evidence'))):
                                raise ValueError('Independent reference needs matching quantity, bands, geometry and effective kernel')
                            entry.update(reference=truth,difference=[float(v) if np.isfinite(v) else None for v in values-expected])
                            diagnostics['independent_reference'] = 'Compared; no uncertainty-based acceptance threshold asserted'
                        diagnostics[name] = entry
                atomic_json(directory/'band-diagnostics.json',diagnostics)
                report.update(completed=True,partial=False,phase='COMPLETE',product=str((directory/'band-ratios.npy').resolve()),
                              diagnostics=diagnostics,reflectance_kind=product.metadata['reflectance_kind'])
        except BaseException as error:
            primary_error = error
            report.update(phase='CANCELLED' if isinstance(error,InterruptedError) else 'FAILED',error=str(error))
            raise
        finally:
            try:
                atomic_json(directory/'processing.json',report)
            except Exception as receipt_error:
                if primary_error is None:
                    raise
                primary_error.add_note(f'Processing receipt also failed: {receipt_error}')
    return report
