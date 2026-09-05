# Recovery continuation and physical acceptance

Completed on 2026-09-05: approved Balluff 3.7.2 installation, exit 0/no reboot,
post-install code 0, signed x64 producer loading, real RGB8 and BayerRG12 frames,
raw persistence, normal stop/release, reopened shape/dtype checks and restoration
of temporary session settings. The user then confirmed a prepared scene and full
lens occlusion; matching BayerRG12/100 ms/gain 0 frames passed the optical-path
comparison. **H1 PASS applies to sensor images only.** See HARDWARE_FINDINGS.md
and its private receipts. Driver approval and H1 acceptance are no longer pending.

1. Complete the remaining physical identity evidence: chassis labels when
   accessible and association of the second NXP interface with a cable/instrument. Use only a known normal connection procedure for any
   user-performed cable comparison. Do not reset power or identify COM4 by writing.
2. Preserve the completed H1 evidence in `local/diagnostics/scene-validation.json`
   and the original scene-ready/occluded acquisitions. Their distinct device
   timestamps and matched settings accompany the user's physical confirmations.
   Reusable commands are in README.md. Further raw-image captures do not resolve
   the remaining scanner or spectral-calibration dependencies.
3. Recover a documented HinaLea scan entry point from an authorized original
   TruScope/HinaLeaApp installation with headers/examples/configuration or a known
   functioning control installation. The NXP VCOM identity supplies neither baud
   and line settings nor commands. No auto-open, DTR/RTS change or command guessing.
4. Verify command semantics (wavelength, state, gap or complete recipe), known units,
   ranges, returned state, settling, trigger and fresh-frame association. Run only
   an evidenced complete sequence; preserve order, missing frames, stop and partial
   data. RGB/Bayer imaging controls cannot stand in for the FP scanner.
5. Recover this unit's wavelength mapping/reconstruction/calibration. A 4250 paper's
   450/299 sequence is not a recipe for this instrument. Without mapping retain
   raw_scan. A dark/white pair cannot supply missing wavelength semantics.
6. If a separately measured calibration becomes necessary, external wavelength
   validation needs known emission lines or a characterized monochromator over the
   accepted range, repeatable illumination, exposure control, dark acquisitions and
   held-out wavelengths. An unknown FP response requires measured per-state spectral
   response and justified inversion. Validate error, resolution and drift before
   claiming reconstructed wavelength accuracy or recovered factory performance.
7. Only then obtain matched sample/dark/white acquisitions and, if available,
   traceable reference reflectance spectra. Check repeatability, saturation and poor
   denominators; retain geometry, angle and specular limitations.

The immediate hardware dependency is an authorized compatible controller runtime/API
and unit-matched calibration, potentially from original delivery media or an existing
laboratory backup. The final bounded public search found relevant SDK/patent/paper
leads but no usable legacy protocol or calibration asset; see SOURCES.md for exact
scope and the GitHub rate-limit failure. A bare COM port, a newer-model SDK claim,
or a switch to MATLAB does not supply the missing assets.
