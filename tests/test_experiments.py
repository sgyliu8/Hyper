from copy import deepcopy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from hyperlab.experiments import matching_settings, summarize_sequence
from hyperlab.io import load_cube


def metadata():
    return {"shape": [2, 2, 3], "model": "synthetic camera", "serial": "synthetic-only",
            "pixel_format": "RGB8", "channel_labels": ["R", "G", "B"],
            "acquisition_source": "SYNTHETIC", "data_source": "SYNTHETIC", "valid": True,
            "readback_settings": {"PixelFormat": "RGB8", "ExposureTime": 1000, "Gain": 0,
                "ExposureAuto": "Off", "GainAuto": "Off", "BalanceWhiteAuto": "Off",
                "GammaEnable": False, "Gamma": 1, "LUTEnable": False, "BlackLevel": 0, "BlackLevelAuto": "Off"}}


def test_matching_uses_actual_identity_without_required_device_alias():
    first, second = metadata(), metadata()
    assert matching_settings([first, second])["status"] == "MATCH"
    second["serial"] = "different-synthetic-camera"
    result = matching_settings([first, second])
    assert result["status"] == "MISMATCH" and "serial" in result["mismatches"]


def test_unknown_value_never_becomes_match_and_absence_requires_evidence():
    first, second = metadata(), metadata()
    for item in (first, second):
        item["readback_settings"]["ExposureTime"] = "unknown"
        item["readback_settings"].pop("BlackLevel")
        item["capabilities"] = {"BlackLevel": {"supported": False}}
    result = matching_settings([first, second])
    assert result["status"] == "UNKNOWN"
    assert "ExposureTime" in result["unknown"]
    assert "BlackLevel" in result["unavailable"] and "BlackLevel" not in result["unknown"]


def test_per_frame_chunk_exposure_overrides_session_readback():
    first, second = metadata(), metadata()
    first["chunk_settings"] = {"ChunkExposureTime": 1000}
    second["chunk_settings"] = {"ChunkExposureTime": 2000}
    result = matching_settings([first, second])
    assert result["status"] == "MISMATCH" and "ExposureTime" in result["mismatches"]


def test_active_auto_needs_per_frame_evidence_and_unknown_cannot_hide_mismatch():
    records = [metadata() for _ in range(3)]
    for item in records:
        item["readback_settings"]["ExposureAuto"] = "Continuous"
    assert matching_settings(records)["status"] == "UNKNOWN"
    records[0]["readback_settings"]["ExposureTime"] = "unknown"
    records[2]["readback_settings"]["ExposureTime"] = 2000
    result = matching_settings(records)
    assert result["status"] == "MISMATCH"
    assert "ExposureTime" in result["mismatches"] and "ExposureTime" in result["unknown"]


def test_black_level_auto_same_continuous_is_not_frozen_match():
    first, second = metadata(), metadata()
    for item in (first, second):
        item['readback_settings']['BlackLevelAuto'] = 'Continuous'
    result = matching_settings([first, second])
    assert result['status'] == 'UNKNOWN'
    assert 'BlackLevelAuto: active without per-frame evidence' in result['unknown']
    second['readback_settings']['BlackLevelAuto'] = 'Off'
    result = matching_settings([first, second])
    assert result['status'] == 'MISMATCH' and 'BlackLevelAuto' in result['mismatches']


class SyntheticSequence:
    def __init__(self, frames, records=None):
        self.frames = frames
        self.frame_count = len(frames)
        self.records = records or [metadata() for _ in frames]
        self.metadata = {"data_level": "raw_sequence", "axis_order": "THWC", "axis_kind": "time",
                         "acquisition_source": "SYNTHETIC", "frames": self.records,
                         "completed": True, "partial": False}

    def frame(self, index):
        return SimpleNamespace(data=self.frames[index].copy(), metadata=deepcopy(self.records[index]),
                               identity=f"synthetic:{index}")


def test_temporal_color_mean_preserves_derived_level_and_finite_denominator(tmp_path):
    data = np.arange(24, dtype=float).reshape(2, 2, 2, 3)
    data[0, 0, 0, 0] = np.nan
    data[:, 0, 0, 1] = np.nan
    sequence = SyntheticSequence(data)
    directory = summarize_sequence(sequence, tmp_path / "mean")
    with load_cube(directory / "mean.npy") as mean:
        assert mean.metadata["data_level"] == "derived_frame"
        assert mean.metadata["channel_labels"] == ["R", "G", "B"]
        assert mean.wavelengths is None
        assert mean.data[0, 0, 0] == data[1, 0, 0, 0]
        assert not mean.valid_mask[0, 0, 1]
    receipt_text = (directory / "temporal.json").read_text()
    assert "NaN" not in receipt_text
    receipt = json.loads(receipt_text)
    assert receipt["settings_check"]["status"] == "MATCH"
    assert receipt["trend"][0]["mean_dn"] == np.nanmean(data[0])


def test_temporal_changed_exposure_rejects_pooling_without_partial_output(tmp_path):
    records = [metadata(), metadata()]
    records[1]["readback_settings"]["ExposureTime"] = 2000
    sequence = SyntheticSequence(np.ones((2, 2, 2, 3)), records)
    with pytest.raises(ValueError, match="mismatch.*ExposureTime"):
        summarize_sequence(sequence, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_unknown_first_frame_cannot_hide_later_setting_change(tmp_path):
    records = [metadata() for _ in range(3)]
    records[0]["readback_settings"]["ExposureTime"] = "unknown"
    records[2]["readback_settings"]["ExposureTime"] = 2000
    sequence = SyntheticSequence(np.ones((3, 2, 2, 3)), records)
    with pytest.raises(ValueError, match="mismatch.*ExposureTime"):
        summarize_sequence(sequence, tmp_path / "unknown-first")


def test_temporal_unknown_settings_remain_explicit_and_nonfinite_trend_is_null(tmp_path):
    records = [metadata(), metadata()]
    for item in records:
        item["readback_settings"].pop("BlackLevel")
    sequence = SyntheticSequence(np.full((2, 2, 2, 3), np.nan), records)
    directory = summarize_sequence(sequence, tmp_path / "unknown")
    receipt_text = (directory / "temporal.json").read_text()
    receipt = json.loads(receipt_text)
    assert "NaN" not in receipt_text
    assert receipt["mean_drift_dn"] is None
    assert receipt["settings_check"]["status"] == "UNKNOWN"
