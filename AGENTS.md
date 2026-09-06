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

Current follow-up (2026-09-05): the owner explicitly authorized a real camera/UI
test to fix Compare ROIs and improve plotting/display. The completed Phase 3
no-session restriction does not block this authorized normal imaging test.
Preserve its old receipts. Save the current frame, normally release the previous
owner, then use one verified session and record acquisition/cleanup outcomes.
Keep resets, driver/firmware changes, permanent writes and unknown FP commands
outside this scoped imaging/UI fix. Original-code licensing remains deferred.

Keep acquired data, calibration, identifiers, logs and vendor assets in ignored
local/ or the user's external workspace. Commit only reviewed source, tests,
redacted English docs and explicitly synthetic examples; stage exact paths.
Original-code license remains undecided. Draft PRs are allowed; no merge,
default-branch change, public release, force push or visibility change.

Run meaningful focused regressions, offline suite and installation/UI checks.
Record PASS/FAIL/NOT_TESTED separately from H0-H4. Do not equate offline success
or an OEM sensor frame with restored spectroscopy. Update docs/dev/HANDOFF.md.
