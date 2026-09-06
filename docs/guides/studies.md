# Studies and controlled observation workflows

Use **Analysis → Study…** to organize saved images or cubes from thermal-paint,
coating and material investigations. A Study is a local JSON manifest of original
observations and their completed ROI results. It does not require a database or
cloud account. The numerical methods are described in the
[materials and thermal-paint guide](../user/MATERIALS_AND_THERMAL_PAINT.md).

The experiment recipes below are collection plans. They do not report completed
material tests, prescribe treatment temperatures, or establish a calibrated
temperature or defect model.

## Add one observation with its analysis

1. In the main workbench, open a saved frame/cube. For a live image, use **Save
   current frame**, wait for the saved-file result, and reopen that file from
   **Recent saves**. A frozen display remains one observation; saving it again
   does not create another technical repeat.
2. If conditions are known, use **Specimen / thermal context…** and **Save new
   revision**. Enter the actual specimen and repeat IDs, material/batch, thermal
   record, illumination and geometry. Leave unavailable values blank. Annotation
   revisions are bound to that source: enter the same genuine specimen ID for
   another image of the same coupon, then save a revision for that new source.
3. Define the ROIs in **Analysis**. Choose their names, geometry and
   reference/target/exclude roles. Select the summary, pixel-inclusion policy and
   support, then choose **ROI summary** and **Run analysis**. Inspect **Results**
   and the completed-result source before continuing. Existing completed feature
   analyses can also be retained with their recipe.
4. Open **Study…**, enter a study name, and select **Optional links for the next
   observation** only when a treatment ID or comparison level is known. Click
   **Add current saved observation**. The dialog records the completed result;
   pending controls cannot redefine that result. A changed source requires a
   fresh analysis.
5. Inspect **Observations**, **ROI feature heatmap**, **Observation points**, and
   **Integrity and provenance**. Select an observation row to inspect its full
   source, annotation, ROI revisions and analysis record. Click **Save…** to
   persist the Study.

**Add saved files…** imports NPY, NPZ or ENVI-header sources without running an
analysis or loading guessed annotations. These rows show analysis **NOT_RUN** and
have no invented feature values. For rows that need specimen context and numeric
ROI features, complete steps 1–3 before adding the current observation. This
version does not edit an existing observation's saved annotation/analysis history
inside the Study dialog. Reimporting the same source or acquisition is refused.

**New** and **Open…** require the current changed Study to be saved first. Closing
the Study dialog retains its state in that workbench, but only **Save…** creates a
durable manifest for a later application launch.

## What the hierarchy records

The manifest links **Study → Specimen → Treatment → Acquisition session →
Observation → ROI revision → AnalysisRun** through IDs and recorded evidence.
Unknown links are nullable; creating an observation does not require invented
specimen or treatment fields.

| Record | Meaning and entry point |
|---|---|
| Study | Local name and manifest ID; one explicit collection or comparison question. |
| `specimen_id` | An actual physical specimen/coupon, entered in **Specimen / thermal context…**. Several photographs of one coupon retain one specimen ID. |
| `treatment_id` | An optional identifier for the actual thermal or other treatment record, entered under the Study's optional links. Temperature/dwell details remain in the annotation and referenced records. |
| `session_id` | The recorded acquisition session when available. A descriptive session label does not manufacture a new acquisition session. |
| `technical_repeat_id` | The saved annotation's **Replicate ID**, identifying a repeated observation of the same specimen under the declared conditions. The software does not infer an independent experimental unit from that ID. |
| Observation | One saved source identity, with original sample, metadata and related-file hashes. Camera origin remains separate from viewing a saved image. |
| ROI revision | Stable ROI ID/revision, raw coordinate frame, geometry, exclusions and selected support from the completed analysis. Legacy rectangles explicitly lack a declared stable ID. |
| AnalysisRun | The completed source-bound recipe, original mean/median feature values, units and used/total counts, plus an existing completed feature-result record when supplied. It is not physical acceptance. |

The optional comparison level is one of `within-session`, `reposition`,
`between-specimen`, or `between-session`. It records the intended comparison for
the observation. It does not prove that only that factor changed. Use the
annotation notes/reference IDs for the associated protocol and other known
conditions.

## Temperature and treatment meaning

Keep these fields together whenever a temperature value is supplied:

| Field | Required interpretation |
|---|---|
| Temperature value | The number actually supplied by the treatment record or measurement. Unknown is empty, not zero. |
| Temperature unit | `degC` or `K`. |
| Temperature meaning | `setpoint`, `independent_measurement`, or `owner_label`. These are different kinds of evidence. |
| Temperature reference ID | The original record or instrument/log reference. An independent-measurement declaration requires a reference ID. |
| Dwell time (s) | Time under the stated treatment protocol; separate from camera exposure time. |

A furnace setpoint is not silently converted into a measured coupon temperature.
An owner label remains an owner label. Predicted temperature is not an accepted
annotation meaning or a Study output. The annotation has one temperature tuple;
if both setpoint and independent specimen measurements exist, retain their
separate original records, reference them, and state which tuple is being shown.
Do not overwrite one meaning with another to simplify the plot.

Record coating/batch, substrate, illumination and geometry in their existing
fields. Put known atmosphere, coating thickness/preparation, cooling procedure,
elapsed time after treatment and other protocol details in **Notes** or referenced
local records. The Study does not infer these from image colour.

## Integrity, moving a workspace and duplicate imports

**Verify files** checks every declared source asset against its recorded byte
size and SHA-256. Depending on the format, this includes NPY/NPZ data, ENVI header
and binary, sidecar, validity mask, saved annotation, and external ROI/exclusion
masks. The original strict source fingerprint and annotation ID remain intact.
Selecting a row in **Integrity and provenance** shows each original path, current
declared location and check result.

Save the Study within the workspace being moved and copy the complete related
directory structure, including the Study manifest and associated files. Paths
are stored relative to the manifest where possible; different Windows drives may
require absolute locators. Open the moved manifest and inspect its new integrity
check. Opening an individual copied source as a new source can produce a different
strict identity because its location/loaded metadata changed; that does not
rewrite the identity of the original Study observation.

If paths changed independently, select the observation and use **Relocate
selected…**. Supply an explicit location for every recorded asset. Relocation is
accepted only when all expected assets match; the association is recorded and
must be saved. A missing file reports **MISSING**; changed bytes report
**MISMATCH**. There is no nearby-file substitution. A sidecar that was explicitly
absent is **EXPECTED_ABSENT** while still absent; newly added metadata is a change.

The same strict source or the same captured session/epoch/frame identity cannot
be added twice to increase the observation count. Distinct captured frame
identities are retained even if their arrays are identical, including black
arrays. Identical-array peers are disclosed; without acquisition evidence,
identical bytes alone cannot determine whether two files represent independent
physical observations. Missing files, ambiguous independence and failed checks
remain visible. A file **MATCH** establishes byte integrity at the declared
locations, not material identity, scene usability or calibration.

## Read the table and heatmap

The order selector rearranges rows by observation, material/batch, dwell, session,
or temperature meaning/value. It does not pool, average or filter observations.
Unknown advanced columns stay out of the initial table until relevant; their
values remain available in the selected observation's provenance. When a
temperature is present, its unit, meaning and reference remain visible together.

Each heatmap row is one observation's ROI. Repeat observations stay separate.
Columns distinguish the stored feature or wavelength, signal unit, mean/median,
quality policy and support. RGB features are categories, sensor/state indices
remain indices, and a wavelength column requires an actual wavelength axis.
Selecting three RGB channels does not create three calibrated spectral bands.

The cell contains its original numeric value. Hover for the used/total
denominator and colour bounds. Colours scale independently within each column;
equal colours in different columns do not imply equal physical amplitudes.
Unknown values are grey and remain unavailable, not zero. This display does not
pool rows with different units or support, predict temperature, or assign defect
probabilities. Spatial SD and quartile intervals in the main ROI figures describe
spatial dispersion, not confidence intervals on independent specimens.

The settings check compares all observations in the Study using the existing
chunk/readback evidence rules. Changing row order does not create a separate
within-group check.

| Settings status | What to do |
|---|---|
| **MATCH** | Recorded comparable fields agree. Inspect illumination, geometry, scene stability and reference applicability separately. |
| **MISMATCH** | Inspect the named fields, such as exposure or pixel format. Keep the original observations; distinguish the changed conditions and do not label the combined data as fixed-setting repeatability. |
| **UNKNOWN** | Some required evidence is unavailable or an automatic setting lacks adequate per-frame evidence. Descriptive observations remain usable with that limitation; same-setting qualification is unknown. |

Matching dimensions or settings does not register two images. Compare each
image's own ROI summary unless registration has been independently established.
The Study does not subtract unregistered pixels or report overlapping defect area.

## Plot original observations against temperature or dwell

In **Observation points**, choose one completed feature column, then select the
x axis: **Observation index**, **Declared temperature**, or **Dwell time**. Each
point is one original observation/ROI result with its existing mean or median;
there is no fitted curve, connecting line, interpolation, cross-observation
average, jitter or confidence interval. The observation index is insertion order,
not elapsed time. Colours and marker shapes identify ROI display names for
readability; sharing a name does not establish spatial registration or membership
in one statistical population.

For temperature, select one explicit unit/meaning combination. A single known
combination is selected visibly; multiple combinations require a choice. For
example, an independently measured `degC` series does not include `K` values,
furnace setpoints or owner labels. No automatic unit conversion or meaning
substitution occurs. An independent measurement retains its temperature reference
ID. Dwell uses the actual annotation's seconds; zero is a known value, and a blank
dwell is unavailable.

The caption reports plotted ROI points and unique observations against their
complete denominators. Missing features, unknown x values and incompatible
temperature scopes are omitted with separate reason counts. Observations with no
completed ROI result have their own count. Coincident points retain separate
records; hover to inspect observation, specimen, repeat, session, source and ROI
IDs/revisions, temperature evidence and used/total pixel counts. Several points
from one coupon do not imply several independent coupons.

Use **Export points + figure…** to create a new local bundle of SVG/PDF/PNG,
`series.csv`, `points.csv`, `plot.json`, the portable `study.json`, and a hashed
`study_export_manifest.json`. `points.csv` includes omitted records and their
reasons as well as exact plotted x/y values. The saved PlotSpec retains the full
Study snapshot, every original source fingerprint, annotation and ROI/analysis
context. All associated assets are verified before and after export. Missing or
changed assets prevent a COMPLETE export; files already written during a detected
change remain as partial evidence. Export uses the completed points shown when
the operation began, not later control changes.

## Normal/reference versus suspect: small diagnostic experiment

This initial experiment asks whether the observed contrast is repeatable at fixed
conditions and whether a small placement change can produce a comparable effect.
“Normal/reference” and “suspect” are declared sample/region roles; a suspect label
is not confirmed defect truth.

1. Identify the physical object or objects. Record the known material/coating,
   batch and reference/suspect label source. Keep one specimen ID if both areas
   belong to the same object. Describe the illumination, camera geometry and
   focus; document any unknown conditions.
2. In **Acquisition**, inspect the actual connected target and settings/readback.
   For a controlled acquisition, use **Manual measurement · fixed settings** and
   verify the resulting pixel format, exposure, gain and available processing
   evidence in **Session details**. Use settings appropriate to the current
   visible scene and supported device ranges. Check source signal, saturation and
   valid coverage; receiving a buffer alone does not establish scene usability.
3. With the object and illumination held fixed, save three distinct displayed
   frames for each required view. If one view contains both reference and suspect
   regions, this is **3 observations with 2 ROI results each**. If separate views
   are required, save three frames per view: **6 observations**. Wait for a new
   frame identity between saves. Retain incomplete or failed attempts separately.
4. For each saved observation, follow the add-and-analyse workflow above. Use the
   same declared summary/support/policy and meaningful reference/target regions;
   retain each image's raw ROI geometry. Record technical-repeat IDs and set the
   comparison level to `within-session` for this fixed-placement series.
5. Inspect **ROI summary**, **ROI pair comparison**, and an appropriate
   **Reference ROI RMSE map** or **Normalized difference map**. Select **Map ECDF /
   brush** or **Map histogram / brush** in **Right plot**, inspect the relevant
   ROI, and inspect selected contrast pixels in raw coordinates. Use **Line /
   strip profile** when a declared strip crosses the feature of interest. Keep
   the map's validity and used/total counts alongside the result. A sparse tail
   can matter even when the ROI median changes little.
6. Reposition one identified object slightly, or make one documented small angle
   change, then keep that new placement fixed and save three additional frames.
   Retain the same specimen/treatment ID, update the geometry note, and record
   `reposition`. This adds **3 observations**: 6 total for the one-view design or
   9 for the separate-view design above. The placement change is a nuisance
   control, not a newly declared material change.
7. Compare original amplitude, within-ROI map distributions, profiles and the
   repeated observations. Inspect the Study's setting differences and nuisance
   notes before attributing contrast to material or damage. Export completed
   recipes/tables/maps and save/verify the Study. Finish with normal acquisition
   stop/release when the imaging session is complete.

Normalized difference is `(A-B)/(A+B)`. Its small denominator guard is a numerical
validity condition. Without matched low-signal evidence or an explicit sourced
analyst threshold, low-signal qualification remains **UNKNOWN**. Enabling an
analyst threshold records its feature scope, source units and exclusion counts;
it does not create a sensor-noise/SNR model. Signed corrected inputs may yield
values outside `[-1,1]`, which remain part of the recorded result.

## Thermal-paint pilot: 3 conditions × 2 coupons × 2 sessions × 3 repeats

This is an example collection size for examining condition separation and
specimen/session variation. It is not a statistical-power justification or a
thermal-paint calibration acceptance test. Use actual prepared coupons and an
approved material/treatment protocol; the software supplies no numerical
treatment temperatures.

| Planned factor | Count and record |
|---|---|
| Treatment conditions | 3 actual conditions, such as the lower/middle/upper part of the chosen protocol. Retain each treatment's real record and temperature meaning. |
| Independently prepared coupons | 2 per condition: **6 physical coupons**. Distinct IDs must correspond to distinct specimens, not different ROI names. |
| Imaging sessions | 2 sessions observing all 6 coupons; retain the actual acquisition session IDs and known setup differences. |
| Technical repeats | 3 distinct saved observations per coupon per session at fixed placement/settings within that series. |
| Planned total | **36 saved observations**: 3 × 2 × 2 × 3. ROI pixels and multiple ROIs do not increase the six-coupon count. |

1. Before imaging, list the six actual specimen IDs, their material/batch and
   substrate, the three treatment IDs, and the available temperature/dwell
   records. Determine whether temperature means setpoint, independent measurement
   or owner label. Keep absent conditions unknown. If all coupons in a condition
   share one treatment run, record that shared run: two coupons do not imply two
   independent treatment runs.
2. Define the question and primary comparison before examining all results: for
   example, amplitude or a justified spectral interval under one documented
   dwell/atmosphere protocol. Choose acquisition format/settings, quality policy,
   ROI roles and a consistent analysis recipe. RGB is a useful separately labelled
   baseline. Physical spectral claims require measured wavelength/response
   evidence; the current fixed-state camera image is not sufficient by itself.
3. In session 1, image every coupon and save three distinct frames per coupon.
   Retain the actual acquisition order and times in the records. Use a recorded
   randomized or balanced order if the experimental design calls for it; do not
   change labels after viewing the outcome. Each fixed-placement triplet is a
   technical-repeat series, not three independently prepared specimens.
4. Reopen each saved observation, save its actual specimen/treatment/thermal
   context, run the selected ROI analysis, and add it to the Study. Link the
   treatment ID and intended comparison. Keep each coupon's specimen ID constant
   through its three repeats and through the second session. Record acquisition
   exposure and thermal dwell in their separate fields.
5. Repeat imaging of all six coupons in session 2 using a separate normal camera
   acquisition session and documented setup. Preserve the actual session ID and
   any settings, illumination or geometry changes. This produces the next 18
   observations; use `between-session` when that is the comparison being
   examined. A session difference is not automatically a change in thermal state.
6. Save and verify the Study. Order by material/batch, dwell, session or temperature
   meaning/value to inspect original rows and ROI feature heatmaps. Examine
   within-session technical variation, between-coupon differences within a
   condition, and the same coupon across sessions. In **Observation points**,
   inspect a selected feature against the compatible independently measured
   temperature records or known dwell times; use separately labelled setpoint or
   owner-label scopes only when those are the available records. Retain
   failed/partial/missing cases and report the achieved
   observation/coupon/session counts against the planned 36/6/2 counts.
7. Record which contrasts persist and which change with session or positioning,
   without claiming significance, calibrated temperature prediction or defect
   probability. A later predictive study needs a defined physical target,
   appropriate independent treatment/specimen replication, applicable
   measurements and an evaluation split that respects specimen/session/batch
   relationships. This pilot does not supply those conclusions automatically.

## Save a reviewable result

Keep the Study manifest and all linked raw, sidecar, mask and annotation assets.
Export the exact completed ROI/map result from the main **Export** menu when
numerical tables or publication figures are needed. Retain the source origin,
identity, ROI revisions, recipe, units, selected features and validity/used-count
denominators. A Study heatmap is descriptive; the main export preserves the
completed scientific result and figure semantics.

Report software/integrity checks, actual acquisition outcomes, scene usability,
reference qualification and application conclusions separately. A real camera
image proves an acquisition origin; it does not by itself establish known paint
treatment, material composition, a defect label, FP control, spectral
reconstruction, reflectance calibration or measurement uncertainty.
