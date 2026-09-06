"""Recorded reference compatibility; never a physical calibration certificate."""
from collections.abc import Mapping
from numbers import Real

import numpy as np

from hyperlab.io.cube import wavelength_unit_scale


def _known(value):
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "unknown", "unavailable", "not_tested", "not tested", "not supplied"}
    if isinstance(value, Mapping):
        return bool(value) and all(isinstance(key, str) and _known(key) and _known(item)
                                   for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return bool(value) and all(_known(item) for item in value)
    return isinstance(value, (Real, np.bool_)) and bool(np.isfinite(value))


def _text(value):
    return isinstance(value, str) and _known(value)


def reference_applicability(sample, white, dark_sample, dark_white):
    """Inspect source measurement_context, not editable experiment annotations.

    Context requires instrument_id, response_calibration_id,
    temperature_condition_id, role, evidence_kind and evidence_source. Sample and
    white also require matching illumination_id/geometry_id. Dark sources require
    role='dark', light_blocked=True and dark_method. Evidence kind is declared,
    documented or experimentally_verified; it is retained, never upgraded.
    MATCH is compatibility of recorded claims, not independent verification.
    """
    roles = ("sample", "white", "dark_sample", "dark_white")
    cubes = (sample, white, dark_sample, dark_white)
    contexts = [cube.metadata.get("measurement_context") for cube in cubes]
    contexts = [value if isinstance(value, Mapping) else {} for value in contexts]
    checks = []

    def record(role, field, status, reason):
        checks.append({"role": role, "field": field, "status": status, "reason": reason})

    def require(role, field, value, predicate, reason):
        if not _known(value):
            record(role, field, "UNKNOWN", "Required source evidence is missing or unknown")
        else:
            valid = predicate(value)
            record(role, field, "MATCH" if valid else "MISMATCH", "Required evidence is present" if valid else reason)

    def compare(field, values, *, known=_known, selected_roles=roles):
        first = values[0]
        for role, value in zip(selected_roles, values):
            if not known(value) or not known(first):
                record(role, field, "UNKNOWN", "Required value or sample comparison evidence is unknown")
            elif value != first:
                record(role, field, "MISMATCH", "Does not match sample source evidence")
            else:
                record(role, field, "MATCH", "Matches sample source evidence")

    compare("shape", [list(cube.shape) for cube in cubes])
    compare("wavelengths", [None if cube.wavelengths is None else cube.wavelengths.tolist() for cube in cubes])
    for field in ("exposure", "gain", "units", "wavelength_units"):
        compare(field, [cube.metadata.get(field) for cube in cubes])
    compare("settings", [cube.metadata.get("settings") for cube in cubes],
            known=lambda value: isinstance(value, Mapping) and _known(value))
    # An empty processing history is a valid known history, unlike empty settings.
    compare("processing_steps", [cube.metadata.get("processing_steps") for cube in cubes],
            known=lambda value: isinstance(value, (list, tuple)))
    for field in ("instrument_id", "response_calibration_id", "temperature_condition_id"):
        compare(field, [context.get(field) for context in contexts], known=_text)
    for field in ("illumination_id", "geometry_id"):
        compare(field, [context.get(field) for context in contexts[:2]], known=_text,
                selected_roles=roles[:2])

    evidence = {}
    for role, cube, context in zip(roles, cubes, contexts):
        meta = cube.metadata
        require(role, "data_level", meta.get("data_level"), lambda value: value == "spectral_cube",
                "Reference correction requires a spectral cube")
        require(role, "linear_intensity", meta.get("linear_intensity"), lambda value: value is True,
                "Reference correction requires linear_intensity=true")
        require(role, "completed", meta.get("completed"), lambda value: value is True,
                "Reference correction requires completed inputs")
        require(role, "partial", meta.get("partial"), lambda value: value is False,
                "Reference correction requires non-partial inputs")
        require(role, "wavelength_source", meta.get("wavelength_source"), _text,
                "Wavelength source must be a nonempty source record")
        require(role, "wavelength_units", meta.get("wavelength_units"),
                lambda value: wavelength_unit_scale(value) is not None, "Wavelength units must be known length units")
        wave = cube.wavelengths
        ordered = wave is not None and (np.all(np.diff(wave) > 0) or np.all(np.diff(wave) < 0))
        record(role, "wavelength_order", "UNKNOWN" if wave is None else "MATCH" if ordered else "MISMATCH",
               "Requires unique ordered wavelength samples")
        expected_role = role if role in ("sample", "white") else "dark"
        require(role, "role", context.get("role"), lambda value: value == expected_role,
                f"Source role must be {expected_role}")
        require(role, "evidence_source", context.get("evidence_source"), _text,
                "Measurement context needs its source record")
        require(role, "evidence_kind", context.get("evidence_kind"),
                lambda value: isinstance(value, str) and value in {"declared", "documented", "experimentally_verified"},
                "Use source measurement evidence; analyst annotations cannot establish applicability")
        if expected_role == "dark":
            require(role, "light_blocked", context.get("light_blocked"), lambda value: value is True,
                    "A dark requires light_blocked=true")
            require(role, "dark_method", context.get("dark_method"), _text,
                    "A dark requires a documented blocked-light method")
        evidence[role] = {"kind": context.get("evidence_kind") if _text(context.get("evidence_kind")) else None,
                          "source": context.get("evidence_source") if _text(context.get("evidence_source")) else None}

    statuses = {check["status"] for check in checks}
    return {"schema_version": 1,
            "status": "MISMATCH" if "MISMATCH" in statuses else "UNKNOWN" if "UNKNOWN" in statuses else "MATCH",
            "checks": checks, "evidence": evidence,
            "interpretation": "Recorded source compatibility, not physical verification or a calibration certificate. "
                "Evidence levels remain source declarations; experiment annotations are not used. "
                "Numerical saturation, masks and denominator checks still apply."}
