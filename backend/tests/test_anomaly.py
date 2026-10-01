"""Isolation Forest statistical check."""
from __future__ import annotations

import pytest

from pnt1.anomaly import META_PATH, MODEL_PATH, AnomalyModel, compute_features

HAS_MODEL = MODEL_PATH.exists() and META_PATH.exists()


def test_features_are_finite_and_complete():
    prev = {"t": 0.0, "speed": 55.0, "heading": 90.0, "x": 0.01}
    f = compute_features(prev, 56.0, 91.0, 15.0, 54.0, 0.02, 0.01)
    assert len(f) == 8 and all(v == v and abs(v) < 1e6 for v in f)
    assert compute_features(None, 0.0, 0.0, 0.0, None, 0.0, None)[0] == 0.0


def test_missing_model_is_harmless(monkeypatch, tmp_path):
    import pnt1.anomaly as a
    monkeypatch.setattr(a, "MODEL_PATH", tmp_path / "none.joblib")
    assert AnomalyModel.load() is None


def test_corrupt_model_is_harmless(monkeypatch, tmp_path):
    import pnt1.anomaly as a
    bad = tmp_path / "bad.joblib"
    bad.write_bytes(b"not a model")
    meta = tmp_path / "bad.json"
    meta.write_text("{}")
    monkeypatch.setattr(a, "MODEL_PATH", bad)
    monkeypatch.setattr(a, "META_PATH", meta)
    assert AnomalyModel.load() is None


@pytest.mark.skipif(not HAS_MODEL, reason="model not trained (run: uv run python -m pnt1.ml_train)")
def test_trained_model_separates_normal_from_impossible():
    m = AnomalyModel.load()
    assert m is not None
    prev = {"t": 0.0, "speed": 55.0, "heading": 90.0, "x": 0.01}
    normal = compute_features(prev, 56.0, 90.5, 15.0, 55.0, 0.02, 0.01)
    teleport = compute_features(prev, 60.0, 90.0, 15.0, 114000.0, 900.0, 950.0)
    spike = compute_features(prev, 812.0, 90.0, 15.0, 55.0, 0.02, 0.01)
    assert not m.flagged(m.score(normal))
    assert m.flagged(m.score(teleport)) and m.flagged(m.score(spike))
    for f in (normal, teleport, spike):
        assert 0.0 <= m.confidence(m.score(f)) <= 1.0


@pytest.mark.skipif(not HAS_MODEL, reason="model not trained")
def test_model_card_reports_held_out_evaluation():
    m = AnomalyModel.load()
    ev = m.meta["evaluation"]
    assert m.meta["train"]["labels_used"] is False
    assert set(ev["seeds"]).isdisjoint(m.meta["train"]["seeds"])
    assert 0.5 < ev["roc_auc"] <= 1.0
