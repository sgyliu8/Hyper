# Hardware and driver setup

Offline mode is fully independent of camera availability. Image acquisition is an
experimental Windows x64 pathway. Spectroscopy requires additional control and
calibration assets that have not been recovered.

| System-known interface | Physical cable mapping |
|---|---|
| mvBlueFOX3-M2024C imaging module → USB3 Vision OS driver → Balluff runtime/CTI → Harvester → HyperLab | Exact connector on the enclosing HinaLea body is not yet independently mapped |
| NXP LPC13xx VCOM controller clue | Association with the body and control protocol remain unknown; no serial port is opened |

USB-A and USB-C name connector shapes. They do not establish image, FP control
or power functions. The enclosing 4200/4200C variant label is unconfirmed.

## First installation on a prepared research PC

1. Install HyperLab offline and verify the synthetic example.
2. Obtain Impact Acquire from the official Balluff download area linked in the
   [USB3 Vision troubleshooting guide](https://assets.balluff.com/documents/DRF_957356_AA_000/Troubleshooting_Windows_USB3VisionDeviceIsNotShownOrCannotBeUsed.html).
   The established runtime for this project is **3.7.2**. Verify the download's
   publisher signature and x64 architecture. Administrator approval is required
   for the OS driver installation; HyperLab does not silently install it.
3. Install the optional acquisition dependency with `python -m pip install ".[camera]"`
   from the checked-out candidate, or use an evaluation package that includes it.
4. When hardware testing is authorized, Connect enumerates necessary PnP entries
   and known runtime directories, registry, `GENICAM_GENTL64_PATH` and saved profile.
   It does not recursively search installed file trees. Choose among multiple
   supported device/runtime candidates. The selected producer is checked for
   architecture, vendor location and signature before loading.
5. Start preview only after connection succeeds. Verify format/exposure/gain
   readback and new-frame identity before saving or recording.

A prepared, supported PC can have a short daily Connect → Preview workflow. A
previously unprepared PC does not acquire driver/runtime/calibration support just
by plugging in USB. Newer vendor documentation does not prove this firmware
supports every node. Existing active automatic controls that cannot be frozen
must leave quantitative eligibility unqualified even when preview works.

**Phase 3 scope:** no new physical acquisition benchmark, driver reinstall,
reset, power cycle, disable/enable or cable replug. Existing LIVE observation is
separate from sustained acceptance. The user reported recovery; historical failed
opens do not establish a proven cable fault. See the development handoff for the
preserved incident timeline and the future explicitly authorized test sequence.
