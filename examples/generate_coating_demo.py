"""Generate the README's synthetic coating-panel illustration; no camera access."""
import argparse

import numpy as np

from hyperlab.io import Cube, save_cube


def coating_demo():
    rng = np.random.default_rng(42)
    h, w = 192, 288
    wave = np.linspace(450, 900, 61)
    y, x = np.mgrid[:h, :w]
    base = 380 + 850 * np.exp(-((wave - 670) / 115) ** 2)
    spectra = [base,
               0.82 * base + 320 * np.exp(-((wave - 790) / 48) ** 2),
               1.08 * base - 230 * np.exp(-((wave - 610) / 45) ** 2)]
    data = np.full((h, w, len(wave)), 180.0)
    # Three illustrative coupons with gradual spatial variation and a narrow stripe.
    for i, spectrum in enumerate(spectra):
        left = 18 + i * 90
        panel = (x >= left) & (x < left + 72) & (y >= 22) & (y < 172)
        texture = 1 + 0.035 * np.sin(y / 8) + rng.normal(0, 0.018, (h, w))
        texture += 0.10 * (y / h - 0.5)
        data[panel] = texture[panel, None] * spectrum + 80
    stripe = (x >= 139) & (x < 143) & (y >= 90) & (y < 155)
    data[stripe] *= 0.55
    data += rng.normal(0, 4, data.shape)
    valid = np.ones((h, w), dtype=bool)
    valid[:2, :2] = False
    metadata = {
        'synthetic': True, 'data_source': 'SYNTHETIC', 'data_level': 'spectral_cube',
        'units': 'DN', 'linear_intensity': True, 'wavelengths': wave.tolist(),
        'wavelength_units': 'nm', 'wavelength_source': 'synthetic analytic design',
        'completed': True, 'partial': False, 'effective_bits': 12,
        'saturation_value': 4095, 'processing_steps': [],
        'description': 'Illustrative panels and stripe, not measured coatings or defect ground truth',
    }
    return Cube(np.round(data).astype(np.uint16), metadata, valid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', help='New .npy or .npz path; existing data are not overwritten')
    args = parser.parse_args()
    save_cube(coating_demo(), args.output)
    print(f'SYNTHETIC illustration only; no material or hardware validation: {args.output}')


if __name__ == '__main__':
    main()
