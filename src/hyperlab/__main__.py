import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import sys


def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=False,
                     default=lambda item: item.tolist() if hasattr(item, 'tolist') else str(item)))


def run_directory(kind):
    from .paths import workspace
    return workspace() / kind / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def main(argv=None):
    parser = argparse.ArgumentParser(description="HyperLab: instrument evidence and explicit offline analysis")
    parser.add_argument('--workspace', type=Path, help='Writable data directory, saved for later CLI/GUI launches')
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Python/runtime presence; does not load camera libraries")
    probe = commands.add_parser("probe", help="Read-only Windows inventory")
    probe.add_argument("--inventory", action="store_true")
    probe.add_argument("--standard-interfaces", action="store_true", help="Static classification only; no CTI loading")
    probe.add_argument("--snapshot", type=Path, help="Use a saved private snapshot instead of running a new probe")
    probe.add_argument("--output", type=Path)
    compare = commands.add_parser("compare-probes")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    acquire = commands.add_parser("acquire", help="Explicit normal single-frame session; never a probe")
    acquire.add_argument("--device", required=True, help="Exact PnP instance ID from local snapshot")
    acquire.add_argument("--cti", type=Path, help="Reviewed installed Balluff x64 producer")
    acquire.add_argument("--single-frame", action="store_true")
    acquire.add_argument("--recipe", help="Rejected until a real scan protocol/recipe is verified")
    acquire.add_argument("--output", type=Path)
    acquire.add_argument("--pixel-format", choices=("RGB8", "BGR8", "BayerRG12"))
    acquire.add_argument("--exposure-us", type=float, help="Session exposure; validate device range and restore afterwards")
    acquire.add_argument("--gain", type=float, help="Session gain in device units; validate range and restore afterwards")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("path", type=Path)
    inspect.add_argument("--axis-order", help="Explicit NPY/NPZ mapping, e.g. HWK or KHW")
    analyze = commands.add_parser("analyze", help="Offline numeric analysis with shared semantic/quality gates")
    analyze.add_argument("path", type=Path)
    analyze.add_argument("operation", choices=("capabilities", "roi", "quality", "cfa", "pca", "angle", "difference", "ratio"))
    analyze.add_argument("--axis-order")
    analyze.add_argument("--roi", type=int, nargs=4, metavar=('X0','Y0','X1','Y1'))
    analyze.add_argument("--bands", type=int, nargs='+')
    analyze.add_argument("--policy", choices=("diagnostic", "quantitative"), default="diagnostic")
    analyze.add_argument("--output", type=Path)
    app = commands.add_parser("app")
    app.add_argument("path", nargs="?", type=Path)
    app.add_argument("--legacy", action="store_true", help="Explicit temporary Tk fallback")
    app.add_argument("--benchmark-log", type=Path, help="Local GUI telemetry JSONL; preview pixels are not recorded")
    demo = commands.add_parser("demo")
    demo.add_argument("--output", type=Path)
    demo.add_argument("--no-gui", action="store_true")
    figure = commands.add_parser('figure-demo', help='Generate reproducible synthetic scientific figure bundles; no hardware')
    figure.add_argument('--output', type=Path, required=True, help='New output directory')
    args = parser.parse_args(argv)
    try:
        if args.workspace:
            import os
            from .paths import select_workspace
            os.environ['HYPERLAB_WORKSPACE'] = str(select_workspace(args.workspace))
        if args.command == "doctor":
            from importlib.metadata import version, PackageNotFoundError
            dependencies = {}
            for name in ("numpy", "matplotlib", "Pillow", "PySide6", "pyqtgraph", "harvesters", "genicam"):
                try:
                    dependencies[name] = version(name)
                except PackageNotFoundError:
                    dependencies[name] = "NOT_INSTALLED"
            from .paths import workspace, config_directory
            from importlib.resources import files
            emit({"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
                  'workspace':str(workspace()), 'config_directory':str(config_directory()),
                  'packaged_probe_present':files('hyperlab.resources').joinpath('Probe-Devices.ps1').is_file(),
                  "architecture": platform.machine(), "dependencies": dependencies,
                  "matlab_executable": shutil.which("matlab"), "hardware_validation": "NOT_TESTED",
                  "note": "Library presence does not establish driver or camera readiness"})
        elif args.command == "probe":
            from hyperlab.probe import run_inventory, load_snapshot, standard_interfaces, candidates
            path = args.snapshot or run_inventory(args.output)
            data = load_snapshot(path)
            emit({"snapshot": str(path), "mode": "READ_ONLY_STATIC",
                  "results": standard_interfaces(data) if args.standard_interfaces else candidates(data)})
        elif args.command == "compare-probes":
            from hyperlab.probe import diff, load_snapshot
            emit(diff(load_snapshot(args.before), load_snapshot(args.after)))
        elif args.command == "acquire":
            if args.recipe:
                raise ValueError("BLOCKED: HinaLea scan protocol, state units/ranges and reconstruction are unverified; no scan command sent")
            if not args.single_frame:
                raise ValueError("Specify --single-frame; no verified real scan recipe exists")
            from hyperlab.probe import run_inventory, load_snapshot, select_device
            snapshot = load_snapshot(run_inventory())
            device = select_device(snapshot, args.device)
            if device.get("vid", "").upper() != "164C" or device.get("pid", "").upper() != "5533" or "MI_00" not in device["instance_id"].upper():
                raise ValueError("Select the investigated USB3 Vision imaging interface, not the serial or composite parent")
            if device.get("problem_code") != 0:
                raise RuntimeError(f"BLOCKED: target Windows problem code {device.get('problem_code')}; driver must be repaired before acquisition")
            if args.cti is None:
                raise ValueError("Explicit --cti is required; use the reviewed installed x64 producer")
            parent = next((d for d in snapshot["devices"] if d["instance_id"].casefold() == str(device.get("parent", "")).casefold()), None)
            if parent is None or "mvBlueFOX3" not in parent.get("bus_reported_description", ""):
                raise RuntimeError("PnP parent identity is unconfirmed")
            serial = parent["instance_id"].rsplit("\\", 1)[-1]
            from hyperlab.adapters.gentl import capture_single
            result = capture_single(args.cti, serial, args.output or run_directory("acquisitions"),
                                    pixel_format=args.pixel_format, exposure_us=args.exposure_us, gain=args.gain)
            emit({"raw_frame": result, "scene_validation": "NOT_TESTED", "spectroscopy": "NOT_TESTED"})
        elif args.command == "inspect":
            from hyperlab.io import load_cube
            cube = load_cube(args.path, axis_order=args.axis_order)
            emit({"shape": cube.shape, "dtype": str(cube.data.dtype),
                  "logical_bytes": int(cube.data.size * cube.data.dtype.itemsize), "metadata": cube.metadata})
        elif args.command == "analyze":
            from hyperlab.io import load_cube
            from hyperlab.analysis import (capabilities, roi_statistics, quality_summary, cfa_statistics,
                pca, spectral_angle, difference, ratio, export_roi_csv, export_product)
            with load_cube(args.path, axis_order=args.axis_order) as cube:
                rect = tuple(args.roi) if args.roi else (0, 0, cube.shape[1], cube.shape[0])
                if args.operation == "capabilities":
                    emit(capabilities(cube))
                elif args.operation in ("roi", "quality", "cfa"):
                    function = {"roi":roi_statistics, "quality":quality_summary, "cfa":cfa_statistics}[args.operation]
                    result = function(cube, rect, policy=args.policy)
                    if args.operation == "roi" and args.output:
                        export_roi_csv(result, args.output)
                    emit(result)
                else:
                    if args.output is None:
                        raise ValueError("Numeric map analysis requires --output (.npy or .hdr)")
                    if args.operation == "pca":
                        result = pca(cube, min(3, len(args.bands or capabilities(cube)['feature_indices'])),
                                     bands=args.bands, policy=args.policy)
                    elif args.operation == "angle":
                        reference = roi_statistics(cube, rect, policy=args.policy)['mean']
                        result = spectral_angle(cube, reference, bands=args.bands, policy=args.policy)
                    else:
                        if args.bands is None or len(args.bands) != 2:
                            raise ValueError("Difference/ratio require exactly two --bands indices")
                        result = (difference if args.operation == "difference" else ratio)(cube, *args.bands, policy=args.policy)
                    export_product(result, args.output, source_cube=cube)
                    emit({'output':str(args.output), 'metadata':result['metadata']})
        elif args.command == "app":
            if args.legacy:
                from hyperlab.ui.app import launch
                launch(args.path)
            else:
                from hyperlab.ui.workbench import launch
                launch(args.path, benchmark_log=args.benchmark_log)
        elif args.command == 'figure-demo':
            from hyperlab.examples import figure_examples
            emit({'data_source':'SYNTHETIC','bundles':figure_examples(args.output),'hardware_validation':'NOT_TESTED'})
        elif args.command == "demo":
            from hyperlab.io import make_synthetic_cube, save_cube
            output = args.output or run_directory("synthetic") / "demo.npy"
            output.parent.mkdir(parents=True, exist_ok=True)
            save_cube(make_synthetic_cube(), output)
            emit({"data_source": "SYNTHETIC", "path": output.resolve(), "hardware_validation": "NOT_TESTED"})
            if not args.no_gui:
                from hyperlab.ui.workbench import launch
                launch(output)
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
