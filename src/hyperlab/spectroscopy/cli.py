"""Offline spectral tools; these commands never infer a hardware controller."""
from pathlib import Path
import json

import numpy as np


def configure_parser(parser):
    commands = parser.add_subparsers(dest='spectroscopy_command', required=True)
    demo = commands.add_parser('demo', help='Run a clearly synthetic scan-to-reflectance example without hardware')
    demo.add_argument('--output', type=Path, required=True)
    inspect = commands.add_parser('inspect-response', help='Validate and summarize a response bundle')
    inspect.add_argument('path', type=Path)
    characterize = commands.add_parser('characterize', help='Fit measured Y = A H using known finite-band inputs')
    characterize.add_argument('--input', type=Path, required=True, help='NPZ: Y, H, wavelengths, region_map; optional validation_Y / validation_H')
    characterize.add_argument('--metadata', type=Path, required=True, help='Measurement context and correction ownership JSON')
    characterize.add_argument('--alpha', type=float, default=0)
    characterize.add_argument('--output', type=Path, required=True)
    reconstruct = commands.add_parser('reconstruct', help='Dark-correct and reconstruct one complete optical scan')
    for name in ('scan', 'dark', 'response', 'output'):
        reconstruct.add_argument('--'+name, type=Path, required=True)
    for name in ('process', 'ratio'):
        command = commands.add_parser(name, help='Saved scans to reference ratios' if name == 'process' else 'Ratio of already corrected linear spectra')
        for key in ('sample', 'white', 'output'):
            command.add_argument('--'+key, type=Path, required=True)
        for key in ('response', 'dark-sample', 'dark-white', 'reference-csv'):
            command.add_argument('--'+key, type=Path)
        command.add_argument('--minimum-denominator', type=float, default=1e-12)
    roi = commands.add_parser('roi', help='Export pixelwise spectral-product ROI mean, SD, robust statistics and counts')
    roi.add_argument('cube', type=Path)
    roi.add_argument('--roi', type=int, nargs=4, required=True, metavar=('X0','Y0','X1','Y1'))
    roi.add_argument('--output', type=Path, required=True)
    roi.add_argument('--support', choices=('per_band','common'), default='per_band')


def execute(args):
    from .response import load_response, save_response, characterize_response, reconstruct_scan
    from hyperlab.io import load_cube
    operation = args.spectroscopy_command
    if operation == 'demo':
        from .example import generate_example
        return generate_example(args.output)
    if operation == 'inspect-response':
        bundle = load_response(args.path)
        return {'kind': bundle['kind'], 'bundle_id': bundle['bundle_id'], 'response_shape': list(bundle['A'].shape),
                'supported_pixels': int(np.sum(bundle['region_map'] >= 0)), 'metadata': bundle['metadata'],
                'hardware_validation': 'NOT_TESTED by this file inspection'}
    if operation == 'characterize':
        metadata = json.loads(args.metadata.read_text(encoding='utf8'))
        with np.load(args.input, allow_pickle=False) as data:
            bundle = characterize_response(data['Y'], data['H'], wavelengths=data['wavelengths'],
                metadata=metadata, region_map=data['region_map'], alpha=args.alpha,
                weights=data['weights'] if 'weights' in data else None,
                wavelength_validity=data['wavelength_validity'] if 'wavelength_validity' in data else None,
                wavelength_units=metadata.get('wavelength_units', 'nm'),
                validation_Y=data['validation_Y'] if 'validation_Y' in data else None,
                validation_H=data['validation_H'] if 'validation_H' in data else None)
        return {'response': str(save_response(bundle, args.output)), 'characterization': bundle['metadata']['characterization']}
    if operation == 'reconstruct':
        with load_cube(args.scan) as scan, load_cube(args.dark) as dark:
            with reconstruct_scan(scan, dark, load_response(args.response), output_path=args.output) as product:
                return {'path': str(args.output.resolve()), 'shape': product.shape,
                        'units': product.metadata['units'], 'completed': product.metadata['completed']}
    if operation in ('process', 'ratio'):
        from .workflow import process_spectroscopy
        if operation == 'ratio' and any((args.response, args.dark_sample, args.dark_white)):
            raise ValueError('Ratio accepts already corrected signals and never subtracts another dark')
        return process_spectroscopy(args.sample, args.white, args.output, response_path=args.response,
            dark_sample_path=args.dark_sample, dark_white_path=args.dark_white, reference_csv=args.reference_csv,
            minimum_denominator=args.minimum_denominator)
    if operation == 'roi':
        from hyperlab.analysis import roi_statistics, export_roi_csv
        with load_cube(args.cube) as cube:
            if cube.wavelengths is None:
                raise ValueError('Spectral ROI export requires actual wavelengths; raw imaging remains available in Analysis')
            result = roi_statistics(cube, args.roi, policy='quantitative', support=args.support)
            export_roi_csv(result, args.output)
            return {'path': str(args.output.resolve()), 'wavelengths': result['wavelengths'],
                    'units': result['units'], 'mean': result['mean'], 'spatial_sd': result['std'], 'count': result['count']}
    raise ValueError('Unknown spectroscopy command')
