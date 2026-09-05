# First ten minutes

1. Follow [Install](INSTALL.md). Start the app; it opens offline.
2. Choose Analysis and **Load synthetic example** at the bottom of its panel,
   or start with `python -m hyperlab demo`. The badge reads SYNTHETIC.
3. Drag the image to pan, wheel to zoom, and use Fit / 1:1. The bottom slider
   selects an explicitly labelled wavelength, scan state or recorded time frame.
4. Use Add ROI, edit its name and drag its rectangle. **Edit ROI bounds…** accepts
   raw pixel coordinates. Show hides a curve and its region; × removes a region.
5. Select the quality policy, then Compare ROIs. Enable L2 normalized shape to
   compare spectral shape alongside the original amplitude. The ribbon is one
   spatial SD, not a confidence interval.
6. Run PCA, choose PC1/PC2/PC3, and inspect PCA variance / PCA loadings. Run Index
   A − B, Index A / B or Angle from ROI A only when enabled for the data.
7. Choose Figure export, select chart/map, title, size and DPI. A new result
   directory contains SVG/PDF/PNG plus PlotSpec JSON and CSV/NPY.
8. Choose Workspace, save/reopen a data copy, register a reference in Calibration,
   and close the app normally. Reopen it to restore workspace, ROI/view state,
   reference list and recent files. Missing files can be located explicitly.

Demo values are generated, not acquired. For existing files use Open data… with
NPY/NPZ + sidecar, ENVI header/data or a HyperLab sequence sidecar. Full details:
[User guide](USER_GUIDE.md), [figure semantics](SCIENTIFIC_FIGURES.md),
[data/reference handling](DATA_AND_CALIBRATION.md).
