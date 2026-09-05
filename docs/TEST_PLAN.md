# Acceptance and evidence

Software tests are independent of hardware. The normal suite does not install
drivers, import/load a producer, open a port, fetch hardware or download datasets.
Run `.venv\Scripts\python.exe -m pytest -q` from the checkout.

Coverage: probe empty/invalid snapshots, exact identity selection, static interface
classification and comparison; axes/metadata/mask round-trip; ENVI BSQ/BIL/BIP,
endian/offset, missing wavelengths; ROI/composite/difference/ratio, bounded PCA,
SAM zero vectors; float dark subtraction, settings mismatch, saturation and low
denominators; streaming partial scans, ordered prefix, stop/disconnect/no overwrite;
CLI rejection of unready/wrong devices and unverified recipes.

The local Tk smoke exercises real widgets/callbacks and background completion.
Desktop Computer Use separately observes the normal launched window and invokes
offline controls. GUI evidence does not count as H1. Hardware controls remain
disabled where actual driver/protocol evidence is absent.

| Gate | Evidence required |
|---|---|
| H0 | physical model/ports/power and live PnP relationship recorded |
| H1 | exact target, real frame+bytes+metadata saved/reopened, scene change, normal release |
| H2 | supported recipe, per-state fresh frame association, full/partial, stop validated |
| H3 | source-backed real wavelength vector/reconstruction; external validation stated |
| H4 | matched references/settings, invalid masks and repeatability; accuracy not assumed |

Each is reported PASS/PARTIAL/BLOCKED/NOT_TESTED. A blocked gate is not a failed
physical experiment, and offline PASS does not upgrade any hardware gate. Hosted
CI is a separate status: a workflow being written is not a successful remote run.
See HANDOFF for the current actual test count, GUI and Git receipts.
