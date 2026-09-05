# Changes

## 0.3.0 — research preview, 2026-09-05

- Correct time trends to use unique source frames and recorded clock coordinates.
- Require fresh stream epochs for recording/benchmark admission; preserve node
  communication errors and explicit recording loss accounting.
- Add multiple named ROIs, optional spatial SD and simultaneous raw/L2 curves,
  map colorbars/units, PC selection, explained variance and loadings.
- Add reproducible SVG/PDF/PNG figures with PlotSpec JSON and CSV/NPY source data.
- Package the Windows inventory resource; persist workspace, ROI/view state,
  references and device profiles independently of the current working directory.
- Add private reference import/export, Locate, redacted support reports, an
  independent wheel smoke and one Windows onedir ZIP build.

Hardware revalidation and original-code licensing remain pending. Older engineering
history is in [the archived Phase 2 handoff](docs/dev/archive/PHASE2_HANDOFF.md).
