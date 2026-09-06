"""File-based reconstruction and reference ratio used by both CLI and workbench."""
from contextlib import ExitStack
from pathlib import Path
import csv

import numpy as np

from hyperlab.acquisition.sequence import atomic_json
from hyperlab.acquisition.session import utc_now
from hyperlab.io import load_cube
from hyperlab.io.cube import wavelength_unit_scale


def read_reference_factors(path, wavelengths_nm):
    """Explicit band-matched factors; never silently interpolate a certificate."""
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        table = list(csv.DictReader(stream))
    try:
        wavelength = np.asarray([float(row['wavelength_nm']) for row in table])
        factor = np.asarray([float(row['reflectance']) for row in table])
    except (KeyError, ValueError) as error:
        raise ValueError('Reference CSV needs wavelength_nm and reflectance columns') from error
    if (wavelength.shape != np.shape(wavelengths_nm) or not np.isfinite(wavelength).all() or
            not np.allclose(wavelength, wavelengths_nm, rtol=1e-10, atol=1e-8)):
        raise ValueError('Reference vector must match the actual wavelength bands; no implicit resampling')
    if not np.isfinite(factor).all() or np.any((factor < 0) | (factor > 1)):
        raise ValueError('Reference factors must be finite dimensionless values in [0,1]')
    return factor


def process_spectroscopy(sample_path, white_path, directory, *, response_path=None,
                         dark_sample_path=None, dark_white_path=None, reference_csv=None,
                         minimum_denominator=1e-12, stop=None, progress=None):
    """Always reconstruct sample and white separately before their pixelwise ratio.

    Without a response bundle inputs must already be documented linear spectral
    products. Correction ownership is checked by the same ratio validator as UI.
    """
    from .reflectance import reflectance_corrected
    if not response_path and (dark_sample_path or dark_white_path):
        raise ValueError('Dark scans require a raw-state response bundle; corrected signals must not be dark-subtracted again')
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError('Processing destination exists; select a new directory')
    sources = {'sample': str(Path(sample_path).resolve()), 'white': str(Path(white_path).resolve())}
    report = {'schema_version': 1, 'started_at': utc_now(), 'sources': sources,
              'completed': False, 'partial': True, 'phase': 'PREFLIGHT', 'error': None}
    with ExitStack() as stack:
        sample = stack.enter_context(load_cube(sample_path))
        white = stack.enter_context(load_cube(white_path))
        if response_path and (not dark_sample_path or not dark_white_path):
            raise ValueError('Raw-state reconstruction requires both matched blocked-light dark scans')
        directory.mkdir(parents=True)

        def stage(name, detail=None):
            report['phase'] = name
            atomic_json(directory/'processing.json', report)
            if progress:
                progress(dict(phase=name, **(detail or {})))

        primary_error = None
        try:
            if response_path:
                from .response import load_response, reconstruct_scan
                bundle = load_response(response_path)
                dark_sample = stack.enter_context(load_cube(dark_sample_path))
                dark_white = stack.enter_context(load_cube(dark_white_path))
                report.update(response_bundle=str(Path(response_path).resolve()),
                    dark_sample=str(Path(dark_sample_path).resolve()), dark_white=str(Path(dark_white_path).resolve()))
                stage('RECONSTRUCT_SAMPLE')
                sample = stack.enter_context(reconstruct_scan(sample, dark_sample, bundle,
                    output_path=directory/'sample-signal.npy', stop=stop,
                    progress=lambda completed, total: progress(dict(phase='RECONSTRUCT_SAMPLE', completed_pixels=completed, total_pixels=total)) if progress else None))
                if not sample.metadata.get('completed'):
                    raise InterruptedError('Sample reconstruction cancelled; the saved prefix is retained')
                stage('RECONSTRUCT_WHITE')
                white = stack.enter_context(reconstruct_scan(white, dark_white, bundle,
                    output_path=directory/'white-signal.npy', stop=stop,
                    progress=lambda completed, total: progress(dict(phase='RECONSTRUCT_WHITE', completed_pixels=completed, total_pixels=total)) if progress else None))
                if not white.metadata.get('completed'):
                    raise InterruptedError('White reconstruction cancelled; the saved prefix is retained')
            if stop is not None and stop.is_set():
                raise InterruptedError('Processing cancelled; completed intermediate products are retained')
            factors = None
            if reference_csv:
                if sample.wavelengths is None:
                    raise ValueError('Reference factors require actual wavelengths')
                scale = wavelength_unit_scale(sample.metadata.get('wavelength_units'))
                if scale is None:
                    raise ValueError('Reference factors require known wavelength units')
                factors = read_reference_factors(reference_csv, sample.wavelengths * scale)
            stage('REFERENCE_RATIO')
            destination = directory/'reflectance.npy'
            with reflectance_corrected(sample, white, reference_reflectance=factors,
                    reference_source=str(Path(reference_csv).resolve()) if reference_csv else None,
                    minimum_denominator=minimum_denominator, output_path=destination,
                    stop=stop, progress=progress) as product:
                report.update(completed=product.metadata['completed'], partial=product.metadata['partial'],
                              product=str(destination.resolve()), source_origin=product.metadata.get('acquisition_source'),
                              units=product.metadata['units'], reflectance_kind=product.metadata.get('reflectance_kind'))
            stage('COMPLETE' if report['completed'] else 'PARTIAL')
        except InterruptedError as error:
            primary_error = error
            report.update(error=str(error), phase='CANCELLED')
            raise
        except Exception as error:
            primary_error = error
            report.update(error=f'{type(error).__name__}: {error}', phase='FAILED')
            raise
        finally:
            report['ended_at'] = utc_now()
            try:
                atomic_json(directory/'processing.json', report)
            except Exception as checkpoint_error:
                if primary_error is None:
                    raise
                primary_error.add_note(f'Processing receipt write also failed: {checkpoint_error}')
    return report
