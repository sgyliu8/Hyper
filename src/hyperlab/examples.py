"""Reproducible public examples; no device or privately captured data is used."""
from pathlib import Path
from .io import make_synthetic_cube
from .analysis import roi_statistics, pca, difference
from .plots import COLORS, roi_plot, map_plot, pca_diagnostics, export_figure_bundle, source_identity


def figure_examples(directory):
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=False)
    cube = make_synthetic_cube()
    h,w,_ = cube.shape
    rectangles = [(0,0,w//3,h),(w//3,0,2*w//3,h),(2*w//3,0,w,h)]
    source = source_identity(cube)
    source['units'] = cube.metadata['units']
    curves = roi_plot([roi_statistics(cube,r) for r in rectangles],
                      ['Region A','Region B','Region C'], COLORS[:3],source=source,normalized=True)
    result = pca(cube,3)
    specs = {'roi':curves, 'difference':map_plot(difference(cube,0,1),source=source),
             'pca_score':map_plot(result,source=source,component=1),
             'pca_variance':pca_diagnostics(result,cube)[0],
             'pca_loadings':pca_diagnostics(result,cube)[1]}
    return {name:str(export_figure_bundle(spec,directory/name)) for name,spec in specs.items()}
