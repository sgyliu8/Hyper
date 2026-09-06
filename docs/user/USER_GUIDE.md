# HyperLab user guide

## Start and identify the source

Open the app with Start-HyperLab.cmd or `python -m hyperlab app`. Startup and
file analysis do not open hardware. Camera state, the viewed observation and a
completed result have separate identities. A saved real capture is replay data;
it can be viewed while a camera is connected. Return to live resumes following
that session. Freeze holds only the display. Details retains full paths, clocks,
settings and result recipes for copying.

## Camera and saving

Use Connect camera, Start preview, Stop acquisition and Disconnect for one
supported camera owner. If multiple targets/runtimes are discovered, select the
intended one. Pending exposure/gain/format changes apply on next start; inspect
the actual readback. Per-frame settings require chunk evidence. Preview preserves
supported automatic processing; measurement mode attempts supported transient
processing changes and reports its actual qualification. Normal release restores
session settings. A native timeout is not proof of cancellation or release.

Save current frame stores the exact displayed raw frame and metadata, including
an older frozen frame; it does not fetch a replacement. Check the saved result
and reopen it from Recent saves before adding analysis to a Study or reference.
Capture, display, recorder admission and durable writing are distinct counts.
Mailbox replacement events may overlap displayed frames and are not USB loss.

A nearly black image can still be a valid received frame. Inspect raw values,
saturation/coverage and known illumination/target conditions. Unknown cause does
not qualify a dark reference. Bayer mosaic, CFA-cell display, camera RGB and
calibrated spectra have different meanings. CFA display requires delivered
pattern, offsets and orientation evidence; an unavailable transform must remain
labelled. Display stretching never creates measured signal or linearity evidence.

## Regions and the four panels

Use Analysis to define named rectangle, polygon, binary-mask or line/strip ROIs.
Give reference/target/exclude roles and select the reference explicitly. The
stable reference ID survives rename/reorder; verify changes after deletion.
Show controls visibility, Use controls statistical inclusion. Exclusions subtract
their union from each selected region. A profile can be inspected independently
of whether it participates in the material amplitude comparison.

Select mean/spatial SD or median/Q25–Q75, quality and common/per-band support.
Choose the method and Run analysis. Results and Export act on its completed,
source-bound result. Changing pending controls cannot rename or rebind an old
figure. A later live frame is a different observation.

- Source panel: original coordinate grid, ROI geometry, linked pixel readout.
- Map panel: selected features, formula/units and validity; grey is unavailable.
- Amplitude panel: each ROI's selected statistic and spatial dispersion.
- Right panel: ECDF/histogram and brush, line/strip profile, residual or L2 shape.

For an ECDF/histogram, choose Inspect ROI and an inclusive range, then Select map
range or drag the range selector. Selected/used/geometric counts refer to exact
raw pixels; the overview preserves sparse hits. Excluded/invalid pixels are not
zero. For a profile, choose a line/strip ROI and inspect per-bin used counts and
reasons. Empty bins stay gaps at their original pixel distances. Profile mean/SD
is separate from a median/quartile amplitude panel. No mm calibration is assumed.

## Spectral and derived operations

RGB feature selectors refer to stored colour categories, not wavelengths. A
documented external spectral cube can use actual wavelength smoothing, first/
second derivatives and interval maps. The inclusive first/last indices retain
their original feature mapping. Physical window span, maximum gap and available
response/FWHM evidence remain inspectable. Unsupported windows stay unavailable.
Continuum depth requires reflectance with supported shoulders. PCA scores,
loadings, variance and angle are descriptive, not defect probabilities.

## Study observations

Save/reopen a source, optionally save a source-bound Specimen / thermal context
revision, and complete its ROI analysis. Open Study and Add current saved
observation. Unknown fields can remain blank. Add saved files imports sources
with analysis NOT_RUN until a completed result is supplied. Save the Study JSON
to keep it across app restarts; closing its dialog alone is not a durable save.

Observations, feature heatmap and original points preserve separate source rows.
Select one compatible feature recipe before comparing. Mean/median, quality,
common feature population, units, preprocessing and known response/context
affect compatibility. UNKNOWN/MISMATCH rows remain viewable without silent pooling.
Group by recorded specimen/session; repeated photos are not independent specimens.
Reference-target contrasts are descriptive within the declared observation.
Connections across observations require an explicit pairing relation. Unknown
temperature/dwell points are omitted with counts, not fabricated or interpolated.

Verify files checks all recorded source/annotation/mask assets. Relocate selected
requires explicit locations and matching bytes; no nearby-file substitution.
Copy a workspace with its associated files and save the Study inside it when
possible. Missing and mismatched assets remain visible. Equal settings/dimensions
do not register images or justify pixelwise difference across observations.

## Recording, replay and output

Recording is bounded by declared frame/time/resource limits and needs a fresh
frame in the active stream epoch. Inspect the selected recording mode and its
memory/durability contract before starting. Accepted/captured is not durable.
Preserve partial directories and errors; only the confirmed manifest prefix is
readable. Never turn a short successful recording into sustained-rate qualification.

In Record, choose Continuous or RAM burst, the frame target and duration limit.
Continuous retains its per-checkpoint durability policy. RAM burst first holds a
bounded set of owned frames, attempts normal camera stop, then saves them in order.
Its preflight reports current memory/disk requirements; it does not guarantee
future OS resources. An infeasible target is disabled, never silently reduced.
During Acquiring or Persisting, acquired frames may still be volatile. Complete
requires the target's readable durable prefix; otherwise the result is Partial.
If saving fails, Retry uses a new directory and preserves the original failure.
Abandon requires an explicit confirmation and reports the unsaved count. Closing
waits for saving or keeps recovery available; a new recording cannot reuse retained
buffers. A failed release remains an error and prevents reopening that target in
the same process. A partial recording is not evidence of a stable sustained rate.

Open sequence.npy.json or its directory to inspect recorded frames. The interactive
trace contains visited unique samples; Plot all recorded ROI samples traverses
every persisted frame. Its time uses recorded receive clocks or explicit frame
indices, not redraw/playback times. Known settings changes prevent unqualified
pooled repeatability. Statistics describe signal changes without identifying cause.

Export display PNG, derived values/mask, ROI tables or Publication figure + data
as distinct outputs. Figure size uses mm/DPI; SVG/PDF preserve text where applicable.
Exports retain completed-source identity and never overwrite originals. Check
Data and methods for formulas, denominators, units and the full bundle contents.

For a separate copy, choose Export → Share copy · preview first. Review the
rendered copy before saving it to a new local directory. This removes or aliases
identifying metadata and preserves supported numerical definitions, values and
geometry. Unsupported custom definitions require the internal export. Removed
identities leave external compatibility UNKNOWN; a known mismatch remains a
mismatch. Values, images and grouping can still identify a sample, so the copy
is not anonymous. Nothing is uploaded, and the original export is unchanged.

[Installation](INSTALL.md) · [Data and methods](DATA_AND_METHODS.md) ·
[Troubleshooting](TROUBLESHOOTING.md)
