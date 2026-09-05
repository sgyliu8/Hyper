# Hardware findings — 2026-09-05

The installed driver and earlier single-frame/occlusion evidence passed H1.
During Phase 2, a Tk baseline frame also succeeded, but three subsequent persistent
CameraSession benchmark attempts failed before streaming. The last could not read
the GenCP MaxDeviceResponseTime register; physical USB reconnection is pending.
Current persistent preview/recording is therefore BLOCKED, despite PnP code 0.
See [HANDOFF](HANDOFF.md) for current receipts. The historical results below do
not establish current link health. Chassis/cable identity, scanner protocol and
device-matched spectral calibration remain unresolved.

## Verified scope and current inventory

The user reports power and two instrument outputs connected to USB and Type-C
inputs. The chassis model/power/interface labels are not yet visible, and no
physical action has correlated the NXP interface with a particular cable. Connector
shape and the sensor model do not establish the complete HinaLea 4200/4200C variant.

Pre-installation baseline: `local/diagnostics/20260905T131703438/snapshot.json`.
Post-installation baseline: `local/diagnostics/20260905T132950698/snapshot.json`.
Earlier 13:15 snapshots were debugging output. All full IDs remain in private logs.

| Observation | Current result / interpretation |
|---|---|
| 14 present USB/camera/image/port nodes in initial inventory | PASS, PnP inventory |
| Parent VID164C/PID5533 reports `mvBlueFOX3-M2024C` | confirmed MATRIX VISION/Balluff imaging module |
| MI_00 compatible class EF/subclass05/protocol00 | confirmed USB3 Vision interface |
| MI_00 initially code 28; after installation code 0 | missing driver repaired |
| MI_00 now libusbK 3.0.7.0, `oem39.inf`, service `libusbK` | signed installed driver; catalog signer Microsoft Windows Hardware Compatibility Publisher |
| Parent usbccgp/usb.inf remains healthy | composite enumeration works |
| NXP LPC13xx VCOM, VID1FC9/PID0003, COM4 | Microsoft usbser healthy; command protocol and instrument/cable association unknown |
| UGREEN Camera 2K, VID0C45/PID636F | unrelated camera excluded from target selection |
| USB endpoint addresses and packet sizes | unknown; no raw descriptor tool used |
| Complete HinaLea chassis identity and cable association | IDENTITY_UNCONFIRMED |

The two candidate devices have different containers/host-port paths; this neither
proves nor excludes their membership in one instrument. No serial port was opened
for identification, and no firmware, power-reset or UserSet action was performed.

## Environment and existing assets

Windows 11 Pro 10.0.26200, x64; PowerShell 7.6.5, about 15.8 GiB physical memory,
about 112.7 GiB free on C: at the initial check. Python 3.11.9 x64 is isolated in
`.venv`. Python 3.13/3.14 also exist but were not selected.

MATLAB R2025a Update 1 was actually run in batch. Image Acquisition Toolbox 25.1 is
installed; `imaqhwinfo` returned no adaptors. R2023b is also installed. Private
log: `local/diagnostics/environment/matlab.log`. No hardware was opened by MATLAB.

Related Uninstall entries, named Program Files folders, current environment,
driver association and project/local were checked. The initial check found no installed HinaLea/TruScope, OEM runtime, pre-existing
GenTL CTI, matching OEM INF or device calibration within that scope. Balluff
Impact Acquire was subsequently installed as recorded below; the missing HinaLea
control/calibration assets remain unresolved. Desktop app inventory found no running controller.
This does not claim absence from unsearched personal backups or all disks.

## Static driver review retained as preparation evidence

Official source: Balluff Impact Acquire 3.7.2, 380,774,608-byte signed installer.
The original package Authenticode signature is valid for Balluff MV GmbH.
It is an x86 bootstrapper containing an x64 MSI: bootstrapper architecture is not
the payload architecture. Windows `expand.exe`, Python `msilib` read-only database
access and `olefile` were used for static cabinet extraction, never installer execution.

Private evidence under `local/downloads/`: `signature.json`, `hash.json`, MSI tables,
and `driver-review/readiness.json`, `signatures.json`, `catalog-dump.txt`.
Eight Windows 10+ x64 driver files, 2,169,423 bytes, were extracted into the original
relative driver layout. Driver INF version is 3.0.7.0 dated 2017-10-26; this differs
from runtime 3.7.2 and is not silently rewritten as a newer driver.

The INF matches `USB\CLASS_EF&SUBCLASS_05&PROT_00`, exactly present on MI_00.
An exact PID5533 entry is not required for this class match. Its PID5531 entry is
for bootloader mode and must not be applied as an identity/firmware instruction.
The catalog is signed by Microsoft Windows Hardware Compatibility Publisher;
the INF SHA256 equals its named signed-catalog entry; six SYS/DLL signatures are
valid. Kernel-policy signtool verification was NOT_RUN (tool not installed).

Result at that review stage: **PASS static driver candidate**; loading was then
NOT_TESTED. The subsequent approved installation and live producer loading are
recorded below. The installer disables unrelated GigE, PCIe, old USB2, LabVIEW
and virtual transports and requests no reboot.


## Approved installation and real single-frame results

The user authorized the reviewed driver installation. The guarded installer
completed with **exit code 0**, with **no reboot performed**. Private receipt:
`local/diagnostics/install-20260905T132833738.log.json`; detailed installer logs
are beside it. The post-installation snapshot confirms target code 0.

The x64 producer at
`C:\Program Files\Balluff\ImpactAcquire\bin\x64\mvGenTLProducer.cti`
passed the installed-location, architecture and Balluff Authenticode checks and
was actually loaded through Harvester 1.4.3. The exact privately derived target
reported model mvBlueFOX3-M2024C, vendor MATRIX VISION GmbH, U3V transport and
firmware 2.28.1323.0. No webcam index or simulated-device fallback was used.

| Session / private directory | Sensor settings and saved data | Execution result |
|---|---|---|
| `local/acquisitions/scene-ready-rgb/` | RGB8, 1936×1216, 20,000 us, gain 0; `uint8`, HWC = 1216×1936×3 color channels | PASS: complete buffer, raw transport bytes, NPY, preview, normal stop, device release and saved-array shape/dtype readback |
| `local/acquisitions/scene-ready-bayer12/` | BayerRG12, 1936×1216, 100,000 us, gain 0; `uint16`, HW = 1216×1936 sensor mosaic | PASS: complete buffer, raw transport bytes, NPY, preview, normal stop, device release and saved-array shape/dtype readback |
| Bayer session restoration | Exposure 20,000 us and PixelFormat RGB8 read back equal to original values; gain stayed 0 | PASS: temporary session settings restored |
| `local/acquisitions/occluded-bayer12/` | Same BayerRG12, 100,000 us, gain 0, uint16 HW 1216×1936; user confirmed full-lens occlusion | PASS: complete buffer, raw/NPY save, stop/release, reopen and settings restoration |
| Live optical path correlation | User confirmed prepared scene and then full-lens occlusion; matched Bayer settings | PASS H1 sensor-image acceptance; separate comparison receipt preserves this later judgement |

Each directory contains `transport_payload.bin`, `frame.npy`, `frame.npy.json`
and `preview.png`. Receipts preserve timestamps, pixel format, source LIVE,
`data_level=raw_frame`, null wavelengths and null calibration source. The Bayer
session read `TestPattern=Off`, `TestImageSelector=Off`, `PixelColorFilter=BayerRG`.
Its preview is a display stretch of the uninterpolated mosaic. RGB output is camera
color data and does not supply three spectral bands or a colorimetric calibration.
The separate comparison receipt `local/diagnostics/scene-validation.json` records
mean intensity **817.567 → 4.599 DN**, occluded/scene mean ratio **0.0056256**, at
matching settings. Device timestamps progressed from 2207053381000 to
2396412735500 ns; each separate acquisition session reported `frame_id=0`, so no
global frame-ID increment is claimed. Original frame receipts retain their initial
`scene_validation=NOT_TESTED`; the later user-confirmed comparison supplies H1
acceptance without rewriting those original acquisition records.

The scene-ready frame has **1.686% saturated pixels** at 4095 DN. Its saved values
remain unchanged; this frame is not accepted as a quantitative spectral/reflectance
measurement. The occluded frame's maximum is 2384 DN; no cause is inferred from that
single extreme value. No raw scan, wavelength reconstruction or reflectance cube
was acquired. H1 certifies this sensor-imaging path, not hyperspectral operation.

## Failure history and current acceptance

| Tried | Observed / preserved receipt | Resolution or remaining limit |
|---|---|---|
| Initial live properties and single-frame gate | code 28; `local/diagnostics/environment/acquire-driver-gate.txt` | Reviewed, approved installation resolved the missing imaging driver |
| Initial runtime/folder/INF search | no existing working OEM path in scoped locations | Official Balluff runtime subsequently installed; HinaLea assets still absent within search scope |
| MATLAB `imaqhwinfo` | no adaptors; environment MATLAB log | Python/GenTL supplied the working imaging path; MATLAB acquisition NOT_TESTED |
| First producer signature check through Windows PowerShell | inherited PowerShell 7 module path prevented the Windows PowerShell signature module from loading; `local/diagnostics/first-frame-attempt.txt` | Prefer installed `pwsh`; clear inherited module path for Windows PowerShell fallback. Actual producer signature then verified Valid |
| First payload mapping | RGB8 was initially unsupported; original payload and error receipt retained in `local/acquisitions/first-frame/` | Added explicit HWC color mapping; separate later RGB8 and Bayer sessions passed. Original failed receipt was not relabelled PASS |
| Static SDK/protocol and bounded public-source search | OEM imaging path found; no usable legacy scan API or unit-matched calibration located | Scanner/reconstruction remain blocked; detailed finite search scope and access failures in SOURCES.md |

**H0 PARTIAL**: bus/interface/driver inventory verified, complete chassis/cable
identity incomplete. **H1 PASS**: real normal sensor acquisition, local save,
stop/release, settings restoration and user-confirmed optical scene/occlusion
comparison passed. **H2 BLOCKED**: scan interface/recipe unknown. **H3 BLOCKED**:
wavelength/reconstruction calibration unknown. **H4 BLOCKED**: H3 unresolved and
matched measurement/reference acquisitions absent. H2–H4 hardware acquisition is
NOT_TESTED; raw-frame success is not spectral or metrological acceptance.
