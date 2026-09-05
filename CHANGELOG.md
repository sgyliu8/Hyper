# Changelog

## 0.2.0 — Phase 2 implementation, 2026-09-05

- Added the default English PySide6/pyqtgraph workbench; retained Tk only through
  explicit `app --legacy`. CMD and process-scoped PowerShell Bypass startup remain
  available without changing permanent execution policy.
- Added one-owner persistent CameraSession, finite preview fetch, bounded latest/
  command/writer/snapshot queues, exact displayed-frame saving, transient settings
  readback/restoration and independent cleanup receipts. GUI exposure/gain are enabled.
- Added bounded THW/THWC raw time recording with durable-prefix checkpoints,
  partial failure evidence, content reopen checks and explicit Windows mmap close.
  A time sequence never becomes an FP raw scan or wavelength cube.
- Added draggable ROI and raw-pixel precision controls, saved-frame comparison,
  ROI/quality/CFA analysis, numeric map exports, matching-reference records
  and temporal summaries. Fixed common-feature PCA/SAM, derived metadata, shared
  capability gates, ENVI interoperability, validity policy, precision and large
  output memory behavior; added independent numerical and lifecycle regressions.
- Added bounded controller asset/topology diagnostics and primary-source/physical
  data documentation. No verified matching FP protocol or reconstruction asset
  was found; NXP serial remains unopened and H2–H4 remain blocked.
- Preserved three actual persistent-session zero-frame failures: typed node-name exception,
  interrupted native all-node read, and subsequent GenCP register/open failure.
  Limited corrected diagnostics to cached names/types and reviewed feature values;
  real corrected export is pending and XML is NOT_EXPORTED.
- Current real preview/recording benchmark is BLOCKED pending USB reconnection.
  Historical H1 imaging PASS is retained separately. Offline, actual desktop,
  source and CI receipts are recorded in HANDOFF; no performance PASS is claimed.

## Startup fix — 2026-09-05

- Added a double-clickable CMD GUI launcher that works from Windows PowerShell
  with Restricted execution policy and returns the terminal immediately.
- Corrected startup/capture examples to avoid persistent policy changes and
  clarified the `.\.venv\Scripts\python.exe` path.

## 0.1.0 — 2026-09-05

- Identified the mvBlueFOX3-M2024C imaging module and separate unassociated NXP
  VCOM interface through live Windows PnP inventory.
- Downloaded and statically reviewed the official signed Balluff 3.7.2 package;
  installed it with recorded user approval, exit code 0 and no reboot. Target
  imaging-interface status changed from code 28 to code 0.
- Acquired real RGB8 and BayerRG12 1936×1216 sensor frames through the signed x64
  GenTL producer; saved original transport payloads, NPY data, receipts and previews
  locally, with normal stop/release and saved-array shape/dtype readback.
- Added bounded session pixel-format/exposure/gain options with device validation,
  readback and restoration; restored RGB8/20 ms after the BayerRG12/100 ms test.
- Corrected Windows PowerShell module-path signature-check failure and explicit
  RGB/BGR color-axis mapping; retained the original failed execution receipts.
- Added read-only inventory/comparison, immutable raw persistence, offline analysis,
  one desktop GUI and lightweight tests. RGB color axes do not become spectra;
  GUI exports ROI CSV, while derived analysis arrays remain an API capability.
- Passed H1 sensor-image acceptance with user-confirmed scene/full-lens occlusion
  at matching BayerRG12/100 ms/gain 0 settings; the mean changed 817.57 to 4.60 DN.
  Original frames and initial receipts remain unchanged; this does not validate spectra.
- Documented the bounded legacy protocol/calibration search, including inaccessible
  sources and rate limits. H0 remains PARTIAL for chassis/cable identity; H2–H4
  remain BLOCKED. No real wavelength reconstruction or reflectance is claimed.
