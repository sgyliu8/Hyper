# Workbench user guide

## Source and task controls

The badge separates EMPTY, SYNTHETIC, REPLAY, LIVE, FROZEN and STALE. Acquisition
origin is retained when a saved measurement is replayed. Top-level Acquisition,
Analysis and Calibration tabs change the right panel; Settings collapses it.
Diagnostics contains detailed device evidence, setup/About and a preview of the
redacted support report. It is not necessary to enter a CTI path for normal use.

Opening the app never opens the camera. The normal prepared-hardware workflow is
Connect camera → Start preview → Stop acquisition → Disconnect. Runtime/device
selection is explicit if discovery has multiple candidates. That physical workflow
was not revalidated this phase. The following controls are implemented:

| Control | Meaning |
|---|---|
| Apply on next start | Temporary requested settings; check actual readback after start |
| Freeze display | Hold the displayed frame while acquisition continues |
| Save current frame | Save the explicitly displayed immutable frame, including an older frozen frame; identity is preserved |
| Record | Start only after the current stream epoch has a new frame; set finite frame/time and disk limits |
| Stop acquisition | Cooperatively stop the stream and restore session settings |
| Disconnect / normal close | Request cleanup; a timeout does not prove native cleanup |

Capture, display and write rates are separate. Preview drops, device frame gaps
and writer overflow have different meanings. Receive age excludes unknown
exposure/transport delay and is not end-to-end latency. Screen age refers to the
shown frame. A frozen or stale picture is not evidence of current acquisition.
A partial sequence remains partial with its failure reason and counts.

## Image and ROI work

Raw pixel coordinates are independent of zoom. Fit shows the field; 1:1 uses a
screen pixel view. Use the slider for wavelength/state or sequence frame index,
following its label. RGB is categorical; a Bayer plane is a raw sensor diagnostic.
CFA-cell colour preview is available only with evidenced delivered pattern and
orientation. Colour rendering is display-only, not colorimetric calibration.

Up to eight rectangles can be named, moved, resized, hidden and deleted (at least
one remains). Names/colours follow the image, curves and exports. Edit ROI bounds
uses half-open pixel bounds, x0/y0 included and x1/y1 excluded. ROI definitions
stay on the same source geometry. Computations debounce edits; obsolete results
are discarded. Analysis source/version is pinned, so a new LIVE frame cannot be
silently substituted into an old result.

Compare ROIs plots means and optional ±1 spatial SD. L2 normalization adds a
separate panel over common valid features; it does not overwrite raw amplitudes.
Bad bands remain gaps. A zero norm produces an unavailable shape curve. The
quality-count dialog and figure JSON retain sample denominators and exclusions.
There is no smoothing, derivative or significance test in this release.

## Maps and PCA

Choose input indices A/B, then Difference or Ratio. Difference uses a diverging
map centered at zero, Ratio at one. Low/invalid denominators stay masked. Angle
uses a sequential map with rad or deg; degree conversion changes the numeric
figure values and unit. Shared map limits are enabled by default for repeated
comparisons of the same operation/units; disable them to fit each new map.

PCA uses the documented common feature selection and mean centering. Choose PC
score, explained variance or loading curves. PC signs are arbitrary; variance
explained is not classification accuracy. Angle/SAM is not a defect probability.
Pixelwise A/B file comparisons require alignment evidence; the separate saved
file comparison is descriptive ROI/field statistics, not registration.

## Recording replay and exports

Open sequence.npy.json (or its sequence folder). The slider visits recorded
frames. ROI time trend uses recorded host receive time within a known clock
session or explicit recorded frame index. Playback speed does not create sample
times. Its interactive curve contains displayed/visited samples, bounded to 300
unique identities. Calibration → Plot all recorded ROI samples recomputes all
persisted frames; temporal statistics create mean, SD and drift outputs. These
describe stability and do not identify the cause of material change.

Image export writes a display PNG. Export derived values + mask writes numerical
data. Figure export writes annotated plots plus source data; see
[Scientific figures](SCIENTIFIC_FIGURES.md). All outputs use new names/directories,
leaving raw measurements unchanged. Recent saves can be reopened or relocated.
