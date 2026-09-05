# Verification and acceptance — Phase 3

The current acceptance matrix is [REVIEW_PHASE3](REVIEW_PHASE3.md); exact build,
installation and hosted CI evidence is in [RELEASE_PLAN](RELEASE_PLAN.md).
Hardware H0-H4 is tracked separately in [HANDOFF](HANDOFF.md). The historical
[Phase 2 test_plan](archive/PHASE2_TEST_PLAN.md) is preserved and is not current authority.

## Local developer checks

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q
```

Tests never load a producer or open serial. Frozen/installed-package smoke is
`python -m hyperlab.offline_smoke` (or `HyperLab.exe offline-smoke`) with a new,
explicit `HYPERLAB_WORKSPACE` and `HYPERLAB_CONFIG_DIR`. The smoke creates a
synthetic array, reopens it, exports a numerical figure, shows/closes Qt and checks
packaged resources/config. It must run outside the checkout after non-editable
installation. The Windows CI job installs a wheel into an independent venv;
Linux CI retains the complete lightweight offline suite.

New regression families: stream epoch and stale template; optional node absence
versus transport errors; original failure through cleanup; deterministic recorder
admission/finalization; unique-frame source time; HW/HWK validity and sentinel;
ROI/source version pinning; map semantic centers/units; PCA selected features;
figure CSV/NPY/JSON identity; state and reference relocation; malicious archive
paths/external masks; CWD-independent resource/config; redacted report whitelist.

Physical performance, Stop/record, ten-minute stability, USB recovery and new
firmware-specific node access are NOT_TESTED THIS PHASE. The benchmark CLI requires
`--hardware`; the isolated diagnostic API also requires explicit hardware mode
and confirmed release of the existing owner. Importing modules is not acquisition.
