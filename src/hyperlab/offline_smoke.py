"""Bounded installation smoke; always synthetic and never opens hardware."""
import json
from pathlib import Path
import time
from importlib.resources import files
from PySide6 import QtCore, QtWidgets
from .io import make_synthetic_cube, save_cube, load_cube
from .plots import COLORS, roi_plot, source_identity, export_figure_bundle
from .analysis import roi_statistics
from .paths import workspace, config_directory
from .ui.workbench import Workbench


def main():
    root = workspace()/'installation-smoke'
    root.mkdir(parents=True,exist_ok=False)
    cube = make_synthetic_cube()
    path = root/'synthetic.npy'
    save_cube(cube,path)
    with load_cube(path) as reopened:
        assert reopened.shape == cube.shape
    assert files('hyperlab.resources').joinpath('Probe-Devices.ps1').is_file()
    spec = roi_plot([roi_statistics(cube,(0,0,20,20))],['Region A'],COLORS[:1],source=source_identity(cube))
    export_figure_bundle(spec,root/'figure')
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = Workbench(path); window.show()
    deadline = time.monotonic()+15
    while (window.cube is None or window.task_busy) and time.monotonic()<deadline:
        app.processEvents(); time.sleep(.01)
    assert window.cube is not None and window.session is None, 'Offline UI load did not finish'
    window.timer.stop(); window.roi_timer.stop()
    window.close(); app.processEvents()
    assert (config_directory()/'settings.json').is_file()
    receipt = {'result':'PASS','mode':'OFFLINE_SYNTHETIC','cwd':str(Path.cwd()),
               'package':str(files('hyperlab')),'workspace':str(workspace()),
               'resource':'PASS','save_reopen':'PASS','figure':'PASS','ui_start_close':'PASS',
               'hardware':'NOT_TESTED','qt_platform':app.platformName(),
               'logical_dpi':app.primaryScreen().logicalDotsPerInch(),
               'device_pixel_ratio':app.primaryScreen().devicePixelRatio()}
    (root/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt,indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
