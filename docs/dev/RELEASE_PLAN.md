# Release candidate and installation evidence

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

Final measured results and artifact/PR links are appended below after execution.
