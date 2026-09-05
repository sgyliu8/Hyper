# Changes

## 0.3.1 — live ROI correction, 2026-09-05

- Correct repeated density-axis scaling and let the display run between bounded
  native buffer polls; preserve acquisition errors and immutable buffer evidence.
- Fix Compare ROIs on live/stopped camera frames with nested immutable metadata;
  raw frame data and evidence remain protected.
- Show single-plane ROI means with visible markers and spatial SD error bars,
  alongside policy-matched intensity distributions using shared bins. A single
  plane does not produce an invented spectrum or a trivial L2 curve of ones.
- Match the figure examples with orange/blue/green curves, darker axes, readable
  legends, consistent dashed lines and translucent SD ribbons. Reserve usable
  chart height and distinguish excluded image pixels with a slate background.
- Export single-plane distribution counts, bin edges and densities with figures.

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

Long-duration/spectral hardware qualification and original-code licensing remain pending. Older engineering
history is in [the archived Phase 2 handoff](docs/dev/archive/PHASE2_HANDOFF.md).
