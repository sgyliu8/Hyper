"""Run from an installed checkout: python examples/generate_synthetic.py NEW_OUTPUT.npy."""

import argparse

from hyperlab.io import make_synthetic_cube, save_cube


def main():
    parser = argparse.ArgumentParser(description="Generate a clearly labeled SYNTHETIC cube")
    parser.add_argument("output")
    args = parser.parse_args()
    save_cube(make_synthetic_cube(), args.output)
    print(f"SYNTHETIC only; no camera access: {args.output}")


if __name__ == "__main__":
    main()
