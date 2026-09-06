# Troubleshooting

| Message / symptom | Action |
|---|---|
| PowerShell scripts disabled | Use Start-HyperLab.cmd or the process-scoped command in Install; do not change machine policy |
| No camera | Continue offline; when hardware work is authorized check the intended supported device presence |
| Driver missing / Windows problem code | Consult official signed vendor driver guidance; no automatic reinstall |
| Runtime missing or unverified | Check official x64 runtime installation; do not load arbitrary CTI files |
| Python acquisition package missing | Install the candidate's camera extra into the environment being used |
| Communication fault / GenCP / AccessDenied | Save the local phase/error receipt. Do not infer a cable diagnosis or repeatedly reopen a failed native path |
| Hardware deferred | Offline analysis is available; no hardware qualification is implied by offline checks |
| FP protocol unavailable | Imaging runtime cannot supply missing state control or spectral reconstruction |
| Workspace not writable | Choose a writable directory in the startup chooser or with --workspace before the command |
| MISSING recent/reference file | Use Locate; a reference digest mismatch requires new registration |
| No valid samples / disabled analysis | Inspect masks, ignore values, bad bands, saturation and feature count; never replace unknown values with fake data |
| Shape curve unavailable | Check common valid features and nonzero norm; raw amplitudes remain available |
| Partial recording | Preserve the directory and failure reason; inspect admitted/copied/durable/unpersisted counts and the readable prefix |

`python -m hyperlab doctor` reports package versions, architecture and actual
workspace/configuration paths without loading camera libraries. `probe --inventory`
is read-only Windows PnP/registry/runtime enumeration. It cannot certify native
open or streaming. Use Diagnostics → Preview redacted support report to inspect
what can be shared. Nothing is uploaded automatically.

A Future timeout is not native-call cancellation. Camera open/configure/stop/
destroy phase records have enter/exit/deadline status. Extended node diagnostics
are explicitly isolated from first-frame acquisition; forcibly ending their owned
helper does not prove device release and is not permission to retry. No thread
is force-killed to claim successful cleanup.


If a profile is unavailable, choose an actual line/strip ROI; empty/excluded bins
remain gaps. If a displayed transformation is unavailable, inspect its required
metadata and effective raw fallback. Do not guess CFA orientation or wavelengths.
Different Study analysis signatures remain separate; inspect the original support
features, quality, units and response/context instead of renaming columns to pool them.
