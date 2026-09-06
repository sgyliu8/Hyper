"""Native-grid support and residual diagnostics; neither is a confidence map."""
from copy import deepcopy
import hashlib
from pathlib import Path

import numpy as np

from hyperlab.analysis.applicability import _text
from hyperlab.experiment_metadata import _mapped_path
from hyperlab.io.cube import wavelength_unit_scale
from .response import _grid


def _sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def diagnostic_map(cube, kind, *, chunk_pixels=65536):
    """Compute an HW map in bounded chunks without materializing a raw cube.

    Support is valid wavelength-grid entries / full output K. Zero-support and
    unprocessed pixels remain masked. Residual RMS uses finite retained state
    residuals, at pixels with valid reconstructed output support.
    """
    if kind not in ('reconstruction_residual', 'spectral_support'):
        raise ValueError('Unknown spectroscopy diagnostic map')
    if isinstance(chunk_pixels, bool) or not isinstance(chunk_pixels, int) or chunk_pixels < 1:
        raise ValueError('chunk_pixels must be a positive integer')
    meta = cube.metadata
    wave = cube.wavelengths
    if (meta.get('data_level') not in ('spectral_cube', 'reflectance_cube') or wave is None
            or not np.all(wave > 0) or wavelength_unit_scale(meta.get('wavelength_units')) is None
            or not _text(meta.get('wavelength_source')) or cube.valid_mask is None):
        raise ValueError('Requires a documented spectral product with explicit propagated validity')
    lineage = meta.get('signal_lineage') or {}
    grid = _grid(meta.get('spatial_grid') or lineage.get('spatial_grid'))
    h, w, k = cube.shape
    if tuple(grid['raw_shape_hw']) != (h, w):
        raise ValueError('Diagnostic grid must match the native source HW axes')
    completed = meta.get('completed') is True and meta.get('partial') is False
    prefix = meta.get('completed_pixels', h * w if completed else None)
    if (isinstance(prefix, bool) or not isinstance(prefix, int) or not 0 <= prefix <= h * w
            or completed and prefix != h * w):
        raise ValueError('Requires an explicit consistent processed-pixel prefix')
    bands = np.asarray(meta.get('band_validity') if meta.get('band_validity') is not None else [True] * k, bool)
    residual = owned = None
    residual_path = asset_hash = None
    association = None
    details = {}
    try:
        if kind == 'reconstruction_residual':
            reconstruction = meta.get('reconstruction') or {}
            signature = lineage.get('operator_signature')
            states = lineage.get('state_order')
            if (meta.get('data_level') != 'spectral_cube' or lineage.get('domain') != 'reconstructed_linear_signal'
                    or not _text(signature) or reconstruction.get('operator_signature') != signature
                    or not isinstance(states, list) or not states or not all(_text(value) for value in states)):
                raise ValueError('Residual requires its reconstructed source, operator and original state order')
            units = reconstruction.get('residual_units')
            if units not in ('DN', 'DN/s'):
                raise ValueError('Residual units must be the recorded corrected-state DN or DN/s units')
            expected_shape = (h, w, len(states))
            residual = getattr(cube, 'reconstruction_residual', None)
            if residual is not None:
                if not str(reconstruction.get('residual_storage', '')).startswith('in-memory'):
                    raise ValueError('In-memory residual lacks its source storage association')
                association = 'in-memory source attribute; not a separately certified asset'
            else:
                source = meta.get('source_file')
                if not source or Path(source).suffix.lower() != '.npy':
                    raise ValueError('Reopen the reconstructed NPY with its adjacent residual asset')
                source = Path(source).resolve()
                mapped_source = _mapped_path(cube.data)
                if mapped_source is None or mapped_source.resolve() != source:
                    raise ValueError('Residual association requires the actual mapped reconstructed source')
                residual_path = source.with_suffix('.npy.residual.npy')
                if reconstruction.get('residual_file') != residual_path.name:
                    raise ValueError('Residual must be the canonical adjacent asset of this reconstructed source')
                if not residual_path.is_file() or residual_path.resolve().parent != source.parent:
                    raise ValueError('Residual asset is missing or outside the reconstructed source directory')
                asset_hash = _sha256(residual_path)
                receipt = reconstruction.get('residual_asset')
                if receipt is not None:
                    if (not isinstance(receipt, dict) or receipt.get('file') != residual_path.name
                            or receipt.get('sha256') != asset_hash or receipt.get('bytes') != residual_path.stat().st_size
                            or receipt.get('shape') != list(expected_shape) or receipt.get('dtype') != 'float64'
                            or receipt.get('operator_signature') != signature
                            or receipt.get('input_source_ids') != lineage.get('input_source_ids')
                            or receipt.get('completed_pixels') != prefix):
                        raise ValueError('Residual asset does not match its recorded source/operator/hash receipt')
                    association = 'matched saved source/operator/hash receipt'
                else:
                    association = 'declared adjacent asset; no saved hash receipt'
                owned = np.load(residual_path, mmap_mode='r', allow_pickle=False)
                residual = owned
            if (not isinstance(residual, np.ndarray) or residual.shape != expected_shape
                    or residual.dtype.kind != 'f'):
                raise ValueError('Residual shape/dtype must match native HW and the original state count')
            if residual_path is not None and reconstruction.get('residual_asset') is not None and residual.dtype != np.dtype('float64'):
                raise ValueError('Residual dtype does not match its saved receipt')
            details = dict(residual_definition=reconstruction.get('residual_definition'),
                residual_association=association, residual_asset_sha256=asset_hash,
                residual_file=str(residual_path) if residual_path else None,
                operator_signature=signature, state_order=deepcopy(states),
                input_source_ids=deepcopy(lineage.get('input_source_ids')))
            title = 'Reconstruction residual RMS'
            definition = 'sqrt(mean(residual**2)) over finite supported state residuals at each processed pixel'
            interpretation = 'Corrected-state reconstruction mismatch; not reflectance, probability or physical validation'
        else:
            units, title = 'dimensionless', 'Valid spectral fraction'
            definition = 'finite propagated-mask-valid wavelength-grid entries / full output K; zero support is masked'
            interpretation = 'Output wavelength-grid support; not independent-band count, confidence or defect probability'
            details['denominator'] = k
        output = np.full((h, w), np.nan)
        valid = np.zeros((h, w), bool)
        used_counts = np.zeros((h, w), np.int32)
        chunk = min(chunk_pixels, max(1, 64 * 1024**2 // (8 * 6 * (k + (residual.shape[2] if residual is not None else 0)))))
        for start in range(0, prefix, chunk):
            indices = np.arange(start, min(start + chunk, prefix))
            rows, cols = indices // w, indices % w
            selection = (rows, cols, slice(None))
            good = np.isfinite(cube.data[selection]) & bands
            good &= cube.valid_mask[rows, cols, None] if cube.valid_mask.ndim == 2 else cube.valid_mask[selection]
            count = good.sum(axis=1)
            usable = count > 0
            if residual is None:
                values = count / k
            else:
                values = np.asarray(residual[selection], dtype=np.float64)
                finite = np.isfinite(values) & usable[:, None]
                count = finite.sum(axis=1)
                usable = count > 0
                scale = np.max(np.where(finite, np.abs(values), 0), axis=1)
                normalized = np.zeros_like(values)
                np.divide(values, scale[:, None], out=normalized, where=finite & (scale[:, None] > 0))
                mean_square = np.zeros(len(indices))
                np.divide((normalized * normalized).sum(axis=1), count, out=mean_square, where=usable)
                values = scale * np.sqrt(mean_square)
            usable &= np.isfinite(values)
            output[rows[usable], cols[usable]] = values[usable]
            valid[rows, cols] = usable
            used_counts[rows, cols] = count
        if residual_path is not None and _sha256(residual_path) != asset_hash:
            raise ValueError('Residual asset changed during diagnostic computation; map withheld')
        details.update(operation=kind, title=title, units=units, definition=definition, interpretation=interpretation,
            spatial_grid=deepcopy(grid), source_shape_hw=[h, w], axis='wavelength',
            acquisition_source=meta.get('acquisition_source', 'unknown'), data_source=meta.get('data_source', 'unknown'),
            source_completed=completed, source_partial=not completed, processed_pixels=prefix,
            total_count=h * w, valid_count=int(valid.sum()), invalid_processed_count=prefix - int(valid.sum()),
            unprocessed_count=h * w - prefix, used_counts=used_counts, calculation_dtype='float64')
        return {'data': output, 'image': output, 'valid_mask': valid, 'metadata': details}
    finally:
        if owned is not None:
            mapped = getattr(owned, '_mmap', None)
            if mapped is not None:
                mapped.close()
            elif hasattr(owned, 'close'):
                owned.close()
