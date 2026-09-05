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
results. A normal native session in the first 0.3.1 candidate received 3,220
frames at about 20 fps with no device frame gaps or fetch timeouts. Frame 833
was frozen, compared and saved; a bounded recording accepted and wrote all 20
frames, with no rejection, overflow or explicit failure, and passed save/reopen.
Stop restored the original settings and Disconnect confirmed camera release.

This test also exposed density tick scaling on repeated redraw: pyqtgraph 0.14
can retain a 1000x scale while the label omits it after disabling SI prefixes.
The regression failed before the fix; each chart label now explicitly disables
all SI scaling ranges. The native saved plot numbers were unaffected.

Initial LIVE display was only about 1.3 fps despite 20 fps acquisition. A separate
bounded, normally released diagnostic compared Harvester native event waits of
1 and 5 ms; neither resolved the synchronous retry loop's contention. Replaying
the exact frame without acquisition took about 46 ms including offscreen paint,
whereas image selection during acquisition took about 259 ms. The adapter now
polls the public try_fetch API for at most 1 ms, yielding Python for 1 ms between
empty polls while retaining the overall fetch deadline and transport errors.
It retains one camera owner and returns/requeues each buffer exactly as before.
The chart reuses the image's validity selection instead of recomputing it.
Tests cover silence/deadline, later buffer delivery, transport failure and repeated
density redraw. The complete intermediate suite passed 228 tests in 21.40 s.

The intermediate 1 ms native wait candidate still displayed about 3 fps. A
second bounded diagnostic compared 1 ms and nonblocking native event checks in
one normally released session. The same image-selection workload improved from
47 to 91 processed frames per ten-second phase, with capture staying about 20 fps
and zero device gaps/timeouts. The final adapter uses zero for the native event
check, as specified by [GenTL 1.6, EventGetData, page 124](https://www.emva.org/wp-content/uploads/GenICam_GenTL_1_6.pdf),
and retains a finite Python deadline/yield. No device node or camera setting is
changed by that host polling policy. Diagnostic frame-processing rates exclude
Qt painting; final native UI rates are reported separately.

The e06345b native candidate acquired 2,512 real BayerRG12 frames at 1936 x 1216,
50,000 us exposure and gain 0. Across 80 eligible LIVE telemetry samples from
22:10:00.699 to 22:11:25.635 UTC, median capture was 19.96 fps and median display
was 7.84 fps (range 4.61–11.02). The first fixed candidate's 25 eligible samples
had a 1.32 fps display median. Recording/frozen samples are excluded. This is a
bounded interactive check, not a ten-minute benchmark or guaranteed frame rate.
The preview replacement counter includes in-flight mailbox replacement and is
not an exact count of uniquely lost images; device gaps and writer accounting
are reported independently.

That session had zero device frame gaps and zero fetch timeouts. All 20 accepted
recording frames were written, with zero failure, rejection or overflow, and
save/reopen passed. Normal Stop completed in about 0.61 s, restored the original
settings, and Disconnect reported camera_released true. Frame 1799 was frozen,
compared, saved and exported through the native English UI at Windows 125%.
Independent NumPy checks matched all three means and population SDs, all 64
shared histogram bins, density integrals and both ROI/figure CSV exports. The
raw file hash was unchanged. Exported PNG/PDF/SVG and source data remain private.

Final synthetic curve inspection also found that pyqtgraph PlotDataItem with
pen=None never populated its internal curve path; the intended SD fills were
empty. A regression reproduced an empty FillBetweenItem path. The renderer now
uses direct PlotCurveItem boundaries, which retain their data without drawing
an outline. The regression checks the filled region, its bounds and alpha. This
chart-only correction does not modify camera polling or numerical statistics.
The final full suite passed 229 tests in 40.77 s with QT_QPA_PLATFORM=offscreen.
The preceding accidentally native-platform test run finished 229 tests but also
printed a Windows 0x8001010d Qt event-loop diagnostic; its log is retained and is
not used as clean desktop acceptance. Desktop acceptance uses the native packaged
application separately from the offline test runner.

GammaEnable remains unsupported/unknown, so quantitative_eligible remains false.
These results validate sensor DN and the imaging/UI workflow; wavelength control,
device-matched reconstruction and calibrated reflectance remain unavailable.
The exact HinaLea body label and the second connection still lack confirmation.

## ROI camera candidate and installation evidence

Build source: e8091351aa7d7eb3e6d137b22750ce4fb6678f72, HyperLab 0.3.1.
The build verified all 30 frozen HyperLab modules against that archived source.
The subsequent handoff/screenshot commit does not change executable code.

| Artifact under local/distribution/roi-final-0.3.1 | Bytes | SHA-256 |
|---|---:|---|
| HyperLab-0.3.1-e8091351-win-x64.zip | 84,119,431 | e37ab9bd6343a5b96de2965b263a8460dff77cd1be80772572f3577f89cfd3f2 |
| wheel/hyperlab-0.3.1-py3-none-any.whl | 120,574 | 41d308d687d1de55065a9ad0783a62863faaf29e73f20ba2b6b758b3f7d8d969 |

The fresh extracted ZIP passed doctor and offline-smoke from an unrelated working
directory, with all 729 installation files unchanged and no vendor CTI/SYS bundled.
This is a same-host installation check, not a second clean PC or NTFS ACL test.
The native packaged application then showed the corrected SD regions, amplitude
and L2 plots at Windows 125%. README's new image uses only built-in synthetic data.

The final e809135 package also completed its own normal real-camera session:

| Final package check | Result |
|---|---|
| Connect/configure/start | PASS; BayerRG12, 1936 x 1216, 50 ms, gain 0 |
| Acquisition | PASS; 1,803 frames, zero device gaps, zero fetch timeouts |
| Bounded recording | PASS; 20 accepted, 20 written, zero failure/rejection/overflow; reopened as 20 x 1216 x 1936 uint16 |
| Actual frame 1261 | PASS; Freeze, Compare ROIs, Save, ROI CSV and figure bundle through the native UI |
| Numerical verification | PASS; three means/SDs, all shared histogram bins/densities and CSV values agree with independent NumPy; raw hash unchanged |
| Normal Stop/disconnect | PASS; Stop about 0.56 s; original settings restored; camera_released true |
| Delivered window | Open on the saved actual-frame comparison in REPLAY; camera normally released |

Its 54 eligible LIVE samples (22:30:43.232–22:31:40.158 UTC) had median capture
19.95 fps and display 8.30 fps (display range 4.49–10.30). This confirms the earlier
bounded responsiveness result; neither series constitutes long-duration acceptance.
The final actual PNG/PDF/SVG, raw frame, sequence, CSV, native screenshots and
delivery-data-verification.json are in the ignored local follow-up directory.

Source-head [push CI](https://github.com/sgyliu8/Hyper/actions/runs/33995833962)
and [PR CI](https://github.com/sgyliu8/Hyper/actions/runs/33995835657) completed
successfully, each with Linux offline and Windows independent-wheel jobs.
The local build receipt's hardware NOT_TESTED is build-time scope and remains
unchanged; real-session evidence is recorded separately.

Use the project-root Start-HyperLab.cmd with the existing project venv, or
desktop/HyperLab/Start-HyperLab.cmd inside the final local package. These launchers
avoid the PowerShell script execution-policy issue without changing Windows policy.

## Heatmap style completion

The owner also selected the PCA PC2 and ROI amplitude/L2 figure examples as
preferred styles. Numerical map exports already use RdBu_r, symmetric zero-centred
PCA/difference limits and a grey invalid mask. The native map now matches that
white background, dark labelled axes and colorbar, and grey invalid-pixel key.
A separate two-entry transparent/grey overlay preserves the numerical NaNs and
distinguishes masked pixels from valid zero. Repeated map labels disable hidden
SI tick scaling. No PCA algorithm, validity policy or camera operation changed.

The map regression checks signed limits, true zero versus invalid NaN, overlay
alpha/grey, legend color, repeated colorbar scaling and unchanged input data.
Native synthetic PC1/PC2 inspection confirms the style; synthetic PCA is not a
physical camera validation. Actual Bayer frame 1261 and the 1,803-frame imaging
receipt above remain the real acquisition evidence for the unchanged camera path.
The full revised offline suite passed 230 tests in 42.73 s; the strengthened
unchanged-input assertion also passed its focused check before the build.

## Real RGB scene follow-up

The owner requested real scenes in place of the displayed synthetic example.
The c4d6ad7 native package acquired RGB8 at 20 ms and 5 ms, saved both actual
frames, and compared frame 3321 with three named ROIs. Native amplitude/L2 plots
use R/G/B categories, and the difference map uses channels 0 minus 1 (R minus G).
RGB PCA remains unavailable under the existing scientific capability gate.

The 20 ms scene showed a localized saturated reflection. Initial 5 ms preview
had fewer saturated samples, but the scene/illumination subsequently changed;
this is a display check, not a controlled exposure-response experiment.

A native recording attempt retained the default 300-frame budget because the
typed limit had not taken effect before confirmation. Its writer queue overflowed:
64 frames were accepted and written, one was rejected, and the partial prefix was
preserved and reopened. This attempt is FAIL, not a 20-frame success. A separate
recording with a visually confirmed 20-frame limit completed and reopened 20/20,
with zero rejected/failed frames or overflow. Sustained full-rate RGB recording
is not qualified by this short sequence.

That failure exposed an incorrect device label: a recording error changed the
header to "Connection failed" while capture was still streaming. The UI now
classifies connection faults only for camera error-state events, while retaining
recording/snapshot errors and partial files visibly. Difference/ratio titles now
use evidenced channel names, including BGR order, and retain numerical indices
in provenance. The revised offline suite passed 234 tests in 49.40 s.
