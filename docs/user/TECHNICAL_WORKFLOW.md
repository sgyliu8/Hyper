# ROI contrast and repeat observations

HyperLab keeps the raw image, computed map, ROI amplitude and selected task plot
in one workbench. The white/orange/blue/teal figure style is shared with exports.
Acquired files, ROI definitions and derived results have separate identities.

## Start with an identified observation

1. In **Acquisition**, connect the verified device and start preview, or use
   **Open data** for a saved observation. A single application owns the camera.
2. Check **Camera**, **Viewing**, **Viewed data** and **Chart** separately.
   Opening a saved image can leave acquisition running. **Return to live**
   returns to that existing session. Freeze affects the display, not acquisition.
3. Save the frame you intend to compare. Inspect **View quality / ROI counts**
   for exact, pinned quantiles, quality denominators and readiness.

Frame receipt, scene usefulness for a stated task, and reference qualification
are different evidence. Unknown illumination, specimen identity or reference
conditions remain unknown. An almost-black capture is not automatically a dark
reference. RGB/Bayer channels and repeated frames do not establish a wavelength
scan, reflectance, temperature history or defect probability.

Live overview sampling is explicitly labelled beside the axis. Its statistics
describe sampled raw values from that same frame. **1:1** requests full detail;
raw-pixel cursor reads, ROI computation, maps and data exports use full values.
Mailbox replacement events in **Session details** can overlap displayed frames;
they are not device frame loss. Host stage durations are not calibrated
exposure-to-screen latency.

## Define the reference and target

**Analysis → Add ROI** creates a rectangle, polygon or line/strip. **Import binary
mask** accepts an exactly matching raw HW binary array/image, with its byte and
logical-mask hashes recorded. **Edit** changes the role, raw bounds, vertices,
polygon holes or strip width, and can reorder regions.

- **Show** controls geometry/curve visibility. **Use** controls calculation
  inclusion. Hiding a region does not remove it from the common feature set.
- Reference, target and exclude are explicit roles. Included exclusions subtract
  their union from every target/reference; overlapping exclusions count once.
- The reference selector stores a stable ROI ID. Rename/reorder preserve it.
  Removing or excluding the selected reference requires an explicit selection.
- IDs and revisions persist when saving the workspace. Loading a different raw
  shape creates new coordinate definitions; geometry is never inferred by zoom.
  Starting preview or switching RGB/Bayer with the same raw dimensions retains
  those definitions. Check their placement in the current scene; matching pixel
  dimensions do not prove image registration.

Pixel centres are at `(x+0.5, y+0.5)`. Rectangles and polygons use a half-open
membership rule; holes are removed. Strips select pixel centres within half the
declared width of their path, including round caps. Width/distance are pixels;
no physical length or area follows without geometric calibration. Empty geometry
has zero counts and unavailable summaries.

Quality totals describe geometry membership, not its bounding box. Per-feature
quality, analyst exclusions, selected features and common-pixel support remain
separate count categories. Spatial SD and IQR describe pixel dispersion, not
uncertainty of a specimen mean or independent repeats.

## Inspect a map and its spatial tail

Choose **Reference ROI RMSE map**, **Normalized difference map**, difference,
ratio, PCA or an applicable spectral operation, then **Run analysis**. Results
pin the actual observation, selected reference and ROI revisions. A later control
choice does not relabel an already computed result.

The left plot retains source ROI amplitude. **Right plot** selects exact map
ECDF/histogram, a raw line/strip profile, reference residual or L2 shape. A profile
uses the selected strip, exact raw pixel centres and cross-strip bins; empty bins
remain unavailable. It performs no signal interpolation.
Range controls appear for ECDF/histogram tasks. Switching to a profile, residual
or shape clears the active spatial brush; previously exported selections retain
their original receipt.

For a map distribution, choose **Inspect ROI**, type the inclusive lower/upper
range or drag the shaded region, and use **Select map range**. Pink points mark
the selected raw pixel coordinates. Counts retain selected, eligible and complete
ROI denominators. Selection is called **selected contrast pixels**, never defect
truth. The exact binary mask and coordinate/value table accompany the right-plot
figure export. Sparse pixels remain selectable even when a display overview
would skip them.

Do not exchange aggregation order: pixel pairs `(9,1)` and `(1,1)` have mean
pixel normalized difference `0.4`, while normalized difference of their channel
means is `2/3`. A 1000-pixel population with 995 values at 100 and five at 200 has
mean 100.5 but median, Q25, Q75 and P99 at 100 and MAD zero. Those summaries do
not establish absence of a small spatial tail; the exact ECDF and brush retain it.

The numerical minimum denominator only guards division. The optional analyst
signal threshold tests `abs(A)+abs(B)` in source units, requires a stated reason
and records its exclusion mask/counts. Without signal evidence, qualification is
UNKNOWN. Signed input can produce normalized differences outside `[-1,1]`.

**Plot and view options** offers channel points with asymmetric whiskers, while
retaining the connected style by default. Robust 1–99% colour limits affect only
display and report the clipped count. Full map values, statistics, tails and
brush membership remain unchanged. Shared limits retain their own clipping
counts for each map.

## Use measured spectral coordinates

Spectral derivatives and interval features require documented, positive, ordered
wavelengths with recognized units and source evidence. On an ROI amplitude plot,
select an interval-map method and drag the wavelength region to compute the map
from the selected original bands. The same selection is available through the
first/last stored-feature controls. Integral maps use the actual wavelength
spacing; interval means divide that integral by the actual wavelength span.

Local polynomial output records each window's original indices, span, maximum
adjacent separation and bandpass evidence. A declared maximum gap or source gap
interval rejects crossing windows; no default physical gap threshold is invented.
Integral and continuum features follow the same support rule. Smoothing does not
create measured spectral resolution.

## Save an observation comparison

Use **Specimen / thermal context** for genuine source-bound specimen, treatment,
repeat and temperature records. Blank values remain unknown. After completing
ROI analysis, **Study → Add current saved observation** links that observation,
ROI revision and analysis. See the [Study guide and two experiment SOPs](../guides/studies.md)
for within-session repeats, repositioning and a planned thermal-paint pilot.

**Export** retains numeric data, PlotSpec, source fingerprints and recipes with
the figures. The Study verifies every required asset and supports explicit,
hash-checked relocation. Copying a saved observation does not create an
independent specimen. Repositioned images are compared descriptively; no
unregistered pixel subtraction, pooled pixel p-values or confidence intervals
are reported.

## Bounded recording on the current Windows host

Inspect **Last recording** after every run. The latest 300-frame high-rate test
retained a verified 176-frame partial prefix and one rejected writer frame;
durable storage synchronization remains a measured limit. Earlier 96/300 and
112/300 failures remain recorded. A short successful run establishes only its
own frame count. Capture FPS, displayed frames, writer acceptance and device
gaps have separate denominators. Do not infer complete recording from preview
smoothness or remove flush/checkpoint guarantees to hide the limitation.
