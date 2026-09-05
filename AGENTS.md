# HyperLab working rules

Read [current handoff](docs/dev/HANDOFF.md), [architecture](docs/dev/ARCHITECTURE.md)
and [Phase 3 review](docs/dev/REVIEW_PHASE3.md). Check actual branch/HEAD/worktree
and preserve existing changes. User instructions and current phase scope supersede
historical handoffs.

Use small, relevant changes with reproducible regressions. UI and public guides
are English. Separate synthetic, replay, imaging and physical spectroscopy evidence.
Raw data are immutable; preserve failed/partial cases and complete denominators.

Phase 3 is non-disturbing: no new native camera sessions/benchmarks, resets,
disable/enable, power cycling, replugging, driver changes, firmware, EEPROM,
UserSets or guessed FP/serial commands. Normal offline app save/exit/restart is
allowed. Inventory is read-only and must not load a CTI or open any serial port.
Future normal acquisition requires a unique verified target and one camera owner.

Keep acquired data, calibration, identifiers, logs and vendor assets in ignored
local/ or the user's external workspace. Commit only reviewed source, tests,
redacted English docs and explicitly synthetic examples; stage exact paths.
Original-code license remains undecided. Draft PRs are allowed; no merge,
default-branch change, public release, force push or visibility change.

Run meaningful focused regressions, offline suite and installation/UI checks.
Record PASS/FAIL/NOT_TESTED separately from H0-H4. Do not equate offline success
or an OEM sensor frame with restored spectroscopy. Update docs/dev/HANDOFF.md.
