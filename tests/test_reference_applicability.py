from copy import deepcopy
import json

import numpy as np
import pytest

from hyperlab.analysis import reflectance
from hyperlab.io import Cube, load_cube


def reference_inputs():
    """Roles and conditions are explicit synthetic evidence, never hardware facts."""
    inputs = []
    for role, value in zip(("sample", "white", "dark", "dark"), (30, 100, 10, 10)):
        context = {
            "instrument_id": "synthetic instrument", "response_calibration_id": "synthetic response",
            "temperature_condition_id": "synthetic thermal condition", "role": role,
            "evidence_kind": "declared", "evidence_source": "analytic test fixture",
        }
        if role == "dark":
            context.update(light_blocked=True, dark_method="synthetic zero-light input")
        else:
            context.update(illumination_id="synthetic light", geometry_id="synthetic geometry")
        inputs.append(Cube(np.full((1, 2, 2), value, np.uint16), {
            "data_level": "spectral_cube", "wavelengths": [500, 600], "wavelength_units": "nm",
            "wavelength_source": "synthetic test", "linear_intensity": True, "units": "DN",
            "settings": {"ExposureAuto": "Off", "GainAuto": "Off", "GammaEnable": False},
            "exposure": 10, "gain": 0, "processing_steps": [], "completed": True,
            "partial": False, "effective_bits": 12, "data_source": "SYNTHETIC", "synthetic": True,
            "measurement_context": context,
        }))
    return inputs


def preflight(inputs):
    from hyperlab.analysis.applicability import reference_applicability
    return reference_applicability(*inputs)


@pytest.mark.parametrize("field", ["instrument_id", "response_calibration_id",
                                   "temperature_condition_id", "illumination_id", "geometry_id"])
def test_rejects_incompatible_context_before_output(field, tmp_path):
    inputs = reference_inputs()
    inputs[1].metadata["measurement_context"][field] = "different synthetic condition"
    destination = tmp_path / "uncreated" / "reflectance.npy"
    with pytest.raises(ValueError, match="applicability.*mismatch"):
        with reflectance(*inputs, output_path=destination):
            pass
    assert not destination.parent.exists()


def test_rejects_empty_settings():
    inputs = reference_inputs()
    for cube in inputs:
        cube.metadata["settings"] = {}
    with pytest.raises(ValueError, match="applicability.*unknown"):
        reflectance(*inputs)


@pytest.mark.parametrize("value", [None, " ", "unknown", "UNAVAILABLE", "NOT_TESTED",
                                    {"readback": None}, {"nested": {"gain": np.nan}},
                                    {"nested": []}, {"nested": float("inf")}])
def test_unknown_settings_are_not_equal_evidence(value):
    inputs = reference_inputs()
    for cube in inputs:
        cube.metadata["settings"] = {"control": deepcopy(value)}
    report = preflight(inputs)
    assert report["status"] == "UNKNOWN"
    assert any(check["field"] == "settings" and check["status"] == "UNKNOWN"
               for check in report["checks"])
    json.dumps(report, allow_nan=False)


def test_mismatch_priority_retains_unknown_reasons():
    inputs = reference_inputs()
    inputs[1].metadata["measurement_context"]["geometry_id"] = "other"
    inputs[2].metadata["measurement_context"].pop("dark_method")
    report = preflight(inputs)
    assert report["status"] == "MISMATCH"
    assert {check["status"] for check in report["checks"]} == {"MATCH", "MISMATCH", "UNKNOWN"}
    assert any(check["role"] == "dark_sample" and check["field"] == "dark_method"
               and check["status"] == "UNKNOWN" for check in report["checks"])


@pytest.mark.parametrize("field,value", [("role", "sample"), ("light_blocked", False),
                                         ("light_blocked", "true"), ("dark_method", "")])
def test_dark_role_requires_blocked_light_and_known_method(field, value):
    inputs = reference_inputs()
    inputs[2].metadata["measurement_context"][field] = value
    assert preflight(inputs)["status"] != "MATCH"
    with pytest.raises(ValueError, match="applicability"):
        reflectance(*inputs)


def test_dark_light_and_geometry_are_not_illuminated_role_requirements():
    inputs = reference_inputs()
    inputs[2].metadata["measurement_context"].update(illumination_id="blocked", geometry_id="cap")
    inputs[3] = inputs[2]  # One compatible measured dark can serve both terms.
    before = [deepcopy(cube.metadata) for cube in inputs]
    report = preflight(inputs)
    assert report["status"] == "MATCH"
    assert all(check["status"] == "MATCH" for check in report["checks"])
    corrected = reflectance(*inputs)
    np.testing.assert_allclose(corrected.data, 2 / 9)
    assert corrected.metadata["reference_applicability"] == report
    assert [cube.metadata for cube in inputs] == before


def test_annotations_cannot_supply_missing_source_context_or_upgrade_it():
    inputs = reference_inputs()
    for cube in inputs:
        context = cube.metadata.pop("measurement_context")
        cube.metadata["experiment_annotations"] = {"measurement_context": context}
    assert preflight(inputs)["status"] == "UNKNOWN"
    with pytest.raises(ValueError, match="applicability"):
        reflectance(*inputs)
    inputs = reference_inputs()
    inputs[0].metadata["measurement_context"]["evidence_kind"] = "analyst_annotation"
    assert preflight(inputs)["status"] == "MISMATCH"
    with pytest.raises(ValueError, match="applicability"):
        reflectance(*inputs)


@pytest.mark.parametrize("field", ["instrument_id", "response_calibration_id", "temperature_condition_id",
                                   "role", "evidence_source", "evidence_kind"])
def test_required_source_context_is_not_invented_for_synthetic_inputs(field):
    inputs = reference_inputs()
    inputs[0].metadata["measurement_context"].pop(field)
    assert preflight(inputs)["status"] == "UNKNOWN"


def test_invalid_evidence_type_is_reported_without_upgrading_it():
    inputs = reference_inputs()
    inputs[0].metadata["measurement_context"]["evidence_kind"] = {"claimed": "documented"}
    assert preflight(inputs)["status"] == "MISMATCH"
    json.dumps(preflight(inputs), allow_nan=False)


def test_matching_processing_history_may_contain_an_empty_parameter_mapping():
    inputs = reference_inputs()
    for cube in inputs:
        cube.metadata["processing_steps"] = [{"operation": "synthetic linear transform", "parameters": {}}]
    assert preflight(inputs)["status"] == "MATCH"


@pytest.mark.parametrize("field,value", [("linear_intensity", False), ("completed", False),
                                         ("partial", True), ("wavelengths", [501, 600]),
                                         ("units", "radiance"), ("gain", 1)])
def test_preflight_includes_existing_numeric_domain_admission(field, value):
    inputs = reference_inputs()
    inputs[1].metadata[field] = value
    report = preflight(inputs)
    assert report["status"] == "MISMATCH"
    with pytest.raises(ValueError):
        reflectance(*inputs)


def test_success_preserves_raw_masks_signed_values_and_declared_evidence(tmp_path):
    inputs = reference_inputs()
    inputs[0].data[0] = [[5, 4095], [200, 30]]
    inputs[1].data[0] = [[100, 100], [10, 20]]
    arrays = [cube.data.copy() for cube in inputs]
    metadata = [deepcopy(cube.metadata) for cube in inputs]
    destination = tmp_path / "reflectance.npy"
    with reflectance(*inputs, output_path=destination, chunk_pixels=1) as result:
        np.testing.assert_array_equal(result.valid_mask, [[[True, False], [False, True]]])
        assert result.data[0, 0, 0] == pytest.approx(-5 / 90)
        assert result.data[0, 1, 1] == pytest.approx(2)
        assert result.metadata["reference_applicability"]["status"] == "MATCH"
        assert "not physical verification" in result.metadata["reference_applicability"]["interpretation"]
    with load_cube(destination) as reopened:
        evidence = reopened.metadata["reference_applicability"]["evidence"]
        assert evidence["sample"]["kind"] == "declared"
        assert evidence["sample"]["source"] == "analytic test fixture"
    for cube, array, meta in zip(inputs, arrays, metadata):
        np.testing.assert_array_equal(cube.data, array)
        assert cube.metadata == meta
