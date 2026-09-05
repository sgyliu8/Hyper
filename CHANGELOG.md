# Changelog

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
