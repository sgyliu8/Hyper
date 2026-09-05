# 0.3.1 live ROI and display follow-up

Baseline: 9d81a85ea3f8b7b97b359149c3ba66ab34361970, 2026-09-05.
The owner explicitly requested a real camera/UI test and styling matching
docs/assets/roi-synthetic.png. UI/public docs stay English; original-code license
and public release remain deferred. No reset, driver/permanent write or unknown
FP/serial command is part of this fix.

## Reproduced error and cause

The existing Windows ZIP showed a real stopped BayerRG12 frame and
`TypeError: Frame evidence is immutable` after Compare ROIs. The exact displayed
frame was saved. Normal Disconnect/close completed and the original session log
reports `camera_released: true`, all cleanup steps successful and no error.

`Cube` copies the top metadata dictionary, retaining the recursively frozen
nested camera evidence. ROI statistics call deepcopy for provenance; Python's
default dictionary reconstruction attempted mutation of a FrozenDict and raised.
Synthetic examples use plain dictionaries, so the previous demonstration missed
this live-frame contract. Rehydrating the saved real frame as a Frame reproduced
the same traceback. FrozenDict now implements safe shallow/deep copy by sharing
its recursively immutable JSON tree; no original evidence protection is removed.

Four regressions failed before the fix: live Bayer metadata, live RGB metadata,
single-plane categorical presentation and background UI comparison. The first
UI test attempt accidentally stopped the timer that delivers background results;
that fixture was corrected before the retained four-failure reproduction.
The corrected complete suite passed 225 tests in 22.77 seconds with offscreen Qt.
The same saved real frame now produces both ROI results without an exception.

## Display and scientific meaning

Single-plane images now show named ROI means with visible markers and spatial
SD error bars. The second panel uses 64 shared intensity bins and all valid ROI
pixels under the chosen quality policy. Counts and bin edges are preserved;
nonempty probability densities integrate to one. Empty regions remain missing.
No single-value L2 curve or artificial wavelength axis is drawn. Multiple RGB
channels and evidenced spectral data keep their actual categorical/wavelength
axes and optional L2 shape comparison.

Qt charts use the figure example's orange/blue/green palette, stronger axes and
labels, matching solid/dashed lines, readable legends, translucent SD ribbons,
and sufficient bottom-panel height. Slate image background distinguishes excluded
transparent pixels from valid black pixels. All changes affect display or derived
statistics; the raw array remains read-only and unchanged.

The Matplotlib figure renderer consumes the same numbers, adding single-point
error bars and distribution panels. `distributions.csv` records bin boundaries,
centres, counts and density; `plot.json` retains the source and quality policy.
Tests verify valid/saturated/ignored/empty cases and export equality. API choices
were checked against the installed stack and official pyqtgraph 0.14.0
[ErrorBarItem](https://pyqtgraph.readthedocs.io/en/pyqtgraph-0.14.0/api_reference/graphicsItems/errorbaritem.html)
and [LegendItem](https://pyqtgraph.readthedocs.io/en/pyqtgraph-0.14.0/api_reference/graphicsItems/legenditem.html)
documentation, accessed 2026-09-05.

## Delivery evidence

Private evidence is under local/diagnostics/roi-live-fix-20260905. It includes the
before desktop image, original saved frame, user settings backup, original normal
session-close receipt, failing regressions, saved-frame traceback and corrected
results. New camera-session and final package results are recorded after the
exact-code build and actual test; offline results do not substitute for them.
