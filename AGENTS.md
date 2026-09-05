# HyperLab working rules

Read this file and HANDOFF.md at the start of every task. Check Git state and
the current physical/driver state; historical notes are not live device evidence.
Update HANDOFF.md and relevant findings/tests when work changes the recovery state.

Use the smallest implementation that solves the observed problem. Preserve user
work. State assumptions and distinguish confirmed, inferred, unknown and failed.

Inventory is read-only: no streaming, serial open/DTR/RTS, CTI/DLL loading, driver
changes, USB writes, reset or exposure changes. Acquisition is a separate explicit
operation with a uniquely identified target and a documented normal API.
Do not replace/uninstall drivers, install kernel drivers, flash firmware, alter
EEPROM/UserSets/permanent calibration, reset to defaults, or guess FP commands.
Driver installation requires separate owner approval under the original intake.
Never scan or fuzz the NXP serial control lead. USB IDs do not establish protocol.

Report H0-H4 separately from software. No synthetic/replay fallback for LIVE.
Keep missing wavelengths null; scan states are not automatically nanometres.
Never claim restored spectroscopy from an OEM camera frame or offline tests.
Raw measurements are immutable. Preserve failed/partial frames and denominator.

Keep real data, calibration, full identifiers, logs, downloads, binaries and licenses
in ignored local/. Use .venv; do not change default Python. No full-disk searches.
Only public source, redacted docs, tests and synthetic generators may be committed.
Stage exact reviewed paths. No force-push, visibility changes or automatic merge.

Run offline tests after implementation. Hardware validation is opt-in, separated
from CI, and must be marked NOT_TESTED when not executed. GUI evidence must be real.
