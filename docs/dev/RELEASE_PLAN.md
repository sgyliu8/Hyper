# Release candidate and installation evidence

The newer **0.3.1** local candidate and actual camera/UI follow-up are documented
in [ROI_LIVE_FIX](ROI_LIVE_FIX.md). The 0.3.0 artifacts and checks below remain
historical. Original-code licensing and public binary release remain pending.

Candidate: HyperLab 0.3.0, branch `feature/scientific-workbench-portable-v3`, based
on `2d9083533a2e367e6543748f97753da02b1a0713`. The actual repository default is
`recovery/hinalea-local`. Do not describe a default clone as the new workbench.

Original-code licensing is **PENDING OWNER DECISION**. A local test build and a
Draft PR do not authorize a public binary release. No default branch change,
merge, tag, visibility change or GitHub Release is part of this phase.

## Reproducible local build

From the clean exact candidate commit on Windows x64/Python 3.11:

```powershell
.\.venv\Scripts\python.exe -m pip install build pyinstaller
.\.venv\Scripts\python.exe packaging/build_windows.py --output local/distribution/phase3
```

The builder checks clean Git status, archives the exact commit, builds a wheel,
creates one onedir desktop ZIP, retains dependency notices and refuses vendor CTI/
driver assets. Its output must be a new directory. BUILD.json and build-receipt.json
record source SHA, versions, sizes and selected artifact hashes. The build is a
reproducible procedure; byte-identical output is not promised across toolchains.

## Acceptance matrix

| Check | Required scope / evidence |
|---|---|
| Source offline suite | Meaningful original coverage plus F1-F7/plot/persistence regressions |
| Exact-commit wheel | Independent empty venv, non-editable install, unrelated CWD, doctor/demo/read/export/UI/resource smoke |
| Windows onedir ZIP | Same-host extracted package, no installation-tree output, synthetic UI/figure smoke |
| Missing camera/runtime | Offline startup does not import/open the backend; synthetic discovery fixtures cover distinct missing/multiple states |
| Ordinary account / read-only install | Record actual account/elevation and enforcement method; do not equate a folder attribute with an ACL proof |
| GUI DPI | Real current 125% Windows display; simulated other scale checks identified separately |
| New Windows PC / clean VM | NOT_TESTED; same-machine fresh venv is not this check |
| Real driver install / LIVE benchmark | DEFERRED / NOT_TESTED THIS PHASE |
| Original-code license / full binary redistribution review | BLOCKED pending owner decision and final dependency/source obligations |

## Maintainer release sequence

Review the Draft PR and final exact-head CI. Select an original-code license after
ownership review; verify Qt/module/GenICam redistribution, corresponding source,
notices and artifact contents. On explicit approval, perform normal merge/default
entry decisions, rebuild from the actual chosen release ref and rerun clean
installation acceptance. Publish a versioned release only after those steps.
Installation instructions already select the candidate branch explicitly.

## Measured candidate results, 2026-09-05 UTC

The selected wheel and Windows ZIP were built from clean source commit
`a64bbd9aa825ef02a3a9707366ae9ac76cd1a536`. Later closeout edits are documentation
and the reviewed synthetic desktop screenshot only; they do not change the code
inside these artifacts. No public download or GitHub Release was created.

| Artifact under local/distribution/phase3-release | Bytes | SHA-256 |
|---|---:|---|
| HyperLab-0.3.0-a64bbd9a-win-x64.zip | 84,111,849 | b3273e103905ea56507f4383a3c1d130d0dab241532748cfb1da027484c980cc |
| wheel/hyperlab-0.3.0-py3-none-any.whl | 118,317 | 438cba1f41ff83d9849eb723e63074f7ab2201808e38b82ee7a1e33fb4fef5be |

The build receipt records Python 3.11.9, PyInstaller 6.22.2, NumPy 2.4.6,
Matplotlib 3.11.1, PySide6 6.10.3 and pyqtgraph 0.14.0. Thirty HyperLab modules
were verified as collected from the archived source. The ZIP excludes CTI/SYS,
private data, calibration and development records; dependency notices are retained.

| Executed acceptance | Result and limits |
|---|---|
| Final source suite | PASS: 219 tests, 18.17 s, offscreen Qt; retained XML/log in local/diagnostics/phase3/release-verified-tests.* |
| Exact wheel, empty independent venv | PASS: non-editable wheel hash/import provenance, unrelated CWD, empty config, doctor, demo, NPY read, numeric export, five figure bundles, packaged PowerShell inventory and native Windows Qt start/close |
| Fresh explicit-branch clone | PASS: cloned source a64bbd9, ran the documented Python 3.11 venv and normal pip install commands, then the same eight offline checks from an unrelated CWD. Imported the non-editable package from that clone's new venv |
| Camera packages absent | PASS for offline startup: Harvester and GenICam are actually absent from the independent wheel environment; no camera producer is opened. Missing-device/driver/multiple-candidate conditions also have separate synthetic tests |
| Extracted final Windows ZIP | PASS: doctor and synthetic save/reopen/figure/UI smoke; 729 installation files unchanged by size/mtime/name comparison; native Qt Windows platform |
| Ordinary token | PASS on this development host without elevation; this is not a separately created Windows user account |
| Python installation write guard | PASS: denied canary and zero unexpected installation writes while offline smoke ran. Python audit-hook enforcement only; native-code writes and NTFS ACL enforcement NOT_TESTED |
| Native English UI | PASS: synthetic load, ROI comparison, separate amplitude/L2 plots, save/close; final installed-wheel screenshot at 125% in docs/assets/workbench-synthetic-native.jpg. Earlier native rename/PC2/export/reference/restart evidence remains local |
| Other DPI layouts | PASS geometry checks at simulated 100/125/150/200%; these are Qt offscreen renders, not physical display changes |
| Scientific exports | PASS: five synthetic figure types plus one native-dialog export; all six PDFs have selectable text, SVG text nodes retained, CSV/NPY numbers checked against shared PlotSpec. Spatial SD is pixel dispersion, not confidence intervals |
| Second clean Windows PC/VM | NOT_TESTED. Same-host fresh environments do not establish this qualification |
| Hardware benchmark/driver install/H2-H4 | DEFERRED or BLOCKED separately; no acquisition result is inferred from software checks |
| Original-code/public binary licensing | BLOCKED at owner's request; no original LICENSE, release, tag, merge or default-branch change |

Private receipts/logs are retained under local/diagnostics/phase3 and independent
temporary installation roots. local/diagnostics/phase3-final-delivery.json records exact local paths,
the final documentation HEAD, artifact source SHA and terminal CI results.

The artifact source passed both
[push CI](https://github.com/sgyliu8/Hyper/actions/runs/33990896093) and
[PR CI](https://github.com/sgyliu8/Hyper/actions/runs/33990898918), including Linux
offline tests and the Windows independent-wheel job. Review remains
[Draft PR #1](https://github.com/sgyliu8/Hyper/pull/1), targeting the unchanged
`recovery/hinalea-local` default. The final documentation commit's checks are
tracked on that PR and in the final local receipt; older CI is not substituted
for its exact-head status.

## Retained failed attempts and bounded corrections

An earlier license-text download failed; the build now uses the official Qt
v6.10.3 source-tag license texts. A later frozen build failed to load QtCore:
static PE import/export comparison identified an incompatible ICU DLL collected
from another tool's PATH. The build now uses a process-scoped isolated PATH and
rejects foreign binary origins; no system PATH or Windows DLL was changed.
The next offline smoke exposed an eager legacy Tk import. The default package
entry now imports Qt directly, with a regression that blocks all Tk imports.
SVG and PDF renderer modules are explicitly collected. Only the final artifact
above passed both doctor and full frozen offline smoke; older builds are not the
delivery candidate.

There was one unplanned native Open during earlier desktop QA. It failed at
ExposureTime.GetInc(), before start/fetch, and its trigger and device-release
status remain unconfirmed. No native retry was made. The continuous-float fix
was verified offline against the installed GenApi 1.6 wrapper and regressions;
the final UI check used the camera-package-free environment. See the full
[incident timeline and H0-H4 matrix](HANDOFF.md). No new frames, streaming test,
reset, replug, power cycle, driver change or FP/serial command occurred.
