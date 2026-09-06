"""Bounded installation smoke; always synthetic and never opens hardware."""
import json
from pathlib import Path
import time
from importlib.resources import files
from PySide6 import QtCore, QtWidgets
from .io import make_synthetic_cube, save_cube, load_cube
from .plots import COLORS, roi_plot, source_identity, export_figure_bundle
from .analysis import roi_statistics, roi_comparison, roi_pairwise, spectral_roi_features, normalized_difference, reference_rmse
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
    export_figure_bundle(spec,root/'figure',source_cube=cube)
    results = roi_comparison(cube,[(0,0,20,20),(25,20,45,40)],support='common')
    assert len(roi_pairwise(cube,results,['A','B'])['pairs']) == 1
    assert spectral_roi_features(cube,results,'derivative1')['metadata']['support'] == 'common'
    assert normalized_difference(cube,0,1)['data'].shape == cube.shape[:2]
    assert reference_rmse(cube,results[0]['mean'])['data'].shape == cube.shape[:2]
    from .analysis.regions import make_roi, resolve_roi, strip_profile
    from .analysis.distributions import map_roi_distributions, brush_map, spectral_interval_map
    region = make_roi(cube.shape[:2], {'type':'polygon','vertices':[[0,0],[20,0],[20,20],[0,20]],'holes':[]})
    assert resolve_roi(cube.shape,region)['selected_count'] == 400
    line = make_roi(cube.shape[:2], {'type':'strip','points':[[0,5],[20,5]],'width_px':2})
    assert strip_profile(cube,line)['curves']
    product = spectral_interval_map(cube)
    distributions = map_roi_distributions(product,[region])
    assert distributions['regions'][0]['counts']['used'] > 0
    selection = brush_map(product,region,[-1e30,1e30])
    assert selection['metadata']['counts']['selected'] == distributions['regions'][0]['counts']['used']
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = Workbench(path); window.show()
    deadline = time.monotonic()+15
    while (window.cube is None or window.task_busy) and time.monotonic()<deadline:
        app.processEvents(); time.sleep(.01)
    assert window.cube is not None and window.session is None, 'Offline UI load did not finish'
    window.analyze_rois()
    deadline = time.monotonic()+15
    while window.task_busy and time.monotonic()<deadline:
        app.processEvents(); time.sleep(.01)
    assert window.roi_results and not window.task_busy, window.message.text()
    from .ui.study_dialog import StudyDialog
    study = StudyDialog(window); study.add_current()
    deadline = time.monotonic()+15
    while window.task_busy and time.monotonic()<deadline:
        app.processEvents(); time.sleep(.01)
    assert len(study.study['observations']) == 1
    study.close()
    from .ui.annotation_dialog import AnnotationDialog
    from .ui.reference_dialog import ReferenceCorrectionDialog
    for dialog in (AnnotationDialog(window),ReferenceCorrectionDialog(window)):
        assert not dialog.isModal()
        dialog.close()
    window.timer.stop(); window.roi_timer.stop()
    window.close(); app.processEvents()
    assert (config_directory()/'settings.json').is_file()
    receipt = {'result':'PASS','mode':'OFFLINE_SYNTHETIC','cwd':str(Path.cwd()),
               'package':str(files('hyperlab')),'workspace':str(workspace()),
               'resource':'PASS','save_reopen':'PASS','figure':'PASS','ui_start_close':'PASS',
               'scientific_modules':'PASS','source_manifest':'PASS','context_reference_dialogs':'PASS',
               'region_distribution_interval_profile':'PASS','study_saved_observation':'PASS',
               'hardware':'NOT_TESTED','qt_platform':app.platformName(),
               'logical_dpi':app.primaryScreen().logicalDotsPerInch(),
               'device_pixel_ratio':app.primaryScreen().devicePixelRatio()}
    (root/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt,indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
