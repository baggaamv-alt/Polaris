"""Statistical anomaly check (Trust Engine check family 'statistical'): an Isolation Forest over live
per-reading features of truck telemetry.

Trained unsupervised on clean simulator data only (labels are never used for fitting); evaluated against
hidden ground-truth labels on unseen seeds. See pnt1/ml_train.py and models/anomaly_iforest.json.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
MODEL_PATH = MODEL_DIR / "anomaly_iforest.joblib"
META_PATH = MODEL_DIR / "anomaly_iforest.json"

FEATURES = [
    "speed_kmh",            # reported speed
    "log_implied_kmh",      # log1p(distance from last accepted fix / dt)
    "log_speed_gap",        # log1p(|implied - reported|)
    "accel_kmh_per_min",    # change in reported speed per minute
    "heading_change_deg",   # |heading change| (only when moving)
    "log_road_km",          # log1p(distance to nearest road)
    "log_route_km",         # log1p(cross-track distance from assigned route)
    "route_growth_km_min",  # change in route deviation per minute
]


def compute_features(prev: dict | None, spd: float, heading: float, t: float, implied: float | None,
                     d_road: float, x_route: float | None) -> list[float]:
    """prev = {'t', 'speed', 'heading', 'x'} from the entity's last accepted reading (or None)."""
    if prev is None or t <= prev["t"]:
        dt_min = 0.25
        accel = 0.0
        dhead = 0.0
        growth = 0.0
    else:
        dt_min = max(0.05, (t - prev["t"]) / 60.0)
        accel = (spd - prev["speed"]) / dt_min
        dh = abs(heading - prev["heading"]) % 360.0
        dhead = min(dh, 360.0 - dh) if spd > 10 and prev["speed"] > 10 else 0.0
        growth = ((x_route or 0.0) - (prev["x"] or 0.0)) / dt_min
    imp = implied if implied is not None else spd
    return [float(spd), math.log1p(max(0.0, imp)), math.log1p(abs(imp - spd)), float(np.clip(accel, -500, 500)),
            float(dhead), math.log1p(max(0.0, d_road)), math.log1p(max(0.0, x_route or 0.0)), float(np.clip(growth, -50, 50))]


class AnomalyModel:
    """Loads the trained forest and maps its decision score to a confidence in [0, 1]."""

    def __init__(self, model, meta: dict):
        self.model = model
        self.meta = meta
        self.q_flag = meta["calibration"]["flag_below"]      # score at the chosen clean-data quantile
        self.q_zero = meta["calibration"]["zero_below"]
        self.q_one = meta["calibration"]["one_above"]

    @classmethod
    def load(cls) -> "AnomalyModel | None":
        if not (MODEL_PATH.exists() and META_PATH.exists()):
            return None
        try:
            import joblib
            return cls(joblib.load(MODEL_PATH), json.loads(META_PATH.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 - a broken model file must never stop the trust pipeline
            return None

    def score(self, feats: list[float]) -> float:
        return float(self.model.decision_function(np.asarray([feats]))[0])

    def confidence(self, s: float) -> float:
        if s >= self.q_one:
            return 1.0
        if s <= self.q_zero:
            return 0.0
        return (s - self.q_zero) / (self.q_one - self.q_zero)

    def flagged(self, s: float) -> bool:
        return s < self.q_flag
