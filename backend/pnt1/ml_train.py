"""Train and evaluate the Isolation Forest for truck-telemetry anomalies.

    uv run python -m pnt1.ml_train

Protocol (no leakage):
  * train      : clean runs on seeds TRAIN_SEEDS (unsupervised - labels are never used to fit)
  * calibrate  : one more clean run, to set score thresholds from the clean-score distribution
  * evaluate   : unseen seeds with vehicle attacks injected; scored against hidden ground-truth labels
Outputs models/anomaly_iforest.joblib and models/anomaly_iforest.json (metrics + calibration).
"""
from __future__ import annotations

import json
import time
from collections import defaultdict

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score

from . import config
from .anomaly import FEATURES, META_PATH, MODEL_DIR, MODEL_PATH
from .ingest import Bus, Gateway
from .network import Network
from .trust import TrustEngine
from .twin import Twin
from .world import World

TRAIN_SEEDS = [101, 102, 103]
CALIB_SEED = 104
EVAL_SEEDS = [201, 202]
HOURS_TRAIN, HOURS_EVAL = 2.0, 2.0
WARMUP_S = 600
ATTACKS = ["gps_spoof_teleport", "gps_spoof_drift", "speed_spike"]
FLAG_QUANTILE = 0.005       # flag the lowest 0.5% of clean scores


def simulate(net: Network, seed: int, hours: float, attacks: bool) -> list[dict]:
    """Run the full pipeline (world -> gateway -> Trust Engine) and capture one row per vehicle reading."""
    w = World(net, seed=seed)
    bus = Bus()
    gw, twin = Gateway(bus), Twin(net)
    trust = TrustEngine(net, twin)
    trust.anomaly = None              # features must not depend on any model
    trust.collect = []
    rng = np.random.default_rng(seed)
    next_attack = WARMUP_S + 300
    steps = int(hours * 3600 / 15)
    for _ in range(steps):
        if attacks and w.t >= next_attack:
            kind = ATTACKS[int(rng.integers(0, len(ATTACKS)))]
            v = w.vehicles[int(rng.integers(0, len(w.vehicles)))]
            w.inject(kind, [v.id], duration_s={"gps_spoof_drift": 1800, "gps_spoof_teleport": 30, "speed_spike": 45}[kind])
            next_attack += 600
        for e in w.step(15):
            gw.ingest(e)
        for e in bus.drain():
            trust.process(e, w.t)
    rows = []
    for event_id, feats, rho, _ in trust.collect:
        lab = w.truth.labels.get(event_id)
        if lab is None:
            continue
        rows.append({"x": feats, "rho": rho, "attacked": bool(lab["is_attacked"]), "injector": lab["injector"],
                     "source": lab["source_id"]})
    return rows


def main() -> None:
    t0 = time.time()
    net = Network()
    print("simulating training runs (clean)...")
    train = [r for s in TRAIN_SEEDS for r in simulate(net, s, HOURS_TRAIN, False)]
    X = np.array([r["x"] for r in train])
    print(f"  {len(X):,} clean readings, {X.shape[1]} features")
    model = IsolationForest(n_estimators=300, max_samples=4096, contamination="auto", random_state=0, n_jobs=-1)
    model.fit(X)

    print("calibrating on a separate clean run...")
    cal = simulate(net, CALIB_SEED, HOURS_TRAIN, False)
    cs = model.decision_function(np.array([r["x"] for r in cal]))
    calibration = {"flag_below": float(np.quantile(cs, FLAG_QUANTILE)), "zero_below": float(np.quantile(cs, 0.0005)),
                   "one_above": float(np.quantile(cs, 0.05)), "flag_quantile": FLAG_QUANTILE}

    print("evaluating on unseen seeds with attacks...")
    ev = [r for s in EVAL_SEEDS for r in simulate(net, s, HOURS_EVAL, True)]
    Xe = np.array([r["x"] for r in ev])
    y = np.array([r["attacked"] for r in ev])
    se = model.decision_function(Xe)
    flag = se < calibration["flag_below"]
    rules = np.array([r["rho"] < config.TRUSTED_MIN for r in ev])
    clean = ~y
    per = {}
    for inj in ATTACKS:
        m = np.array([r["injector"] == inj for r in ev])
        if not m.any():
            continue
        per[inj] = {"attacked_readings": int(m.sum()), "model_recall": round(float(flag[m].mean()), 4),
                    "rules_recall": round(float(rules[m].mean()), 4),
                    "combined_recall": round(float((flag | rules)[m].mean()), 4),
                    "caught_by_model_only": int((flag & ~rules)[m].sum())}
    # drift: how early does each detector first fire within an attack episode (per source)?
    first = defaultdict(lambda: {"model": None, "rules": None, "n": 0})
    for i, r in enumerate(ev):
        if r["injector"] != "gps_spoof_drift":
            continue
        d = first[r["source"]]
        d["n"] += 1
        if flag[i] and d["model"] is None:
            d["model"] = d["n"]
        if rules[i] and d["rules"] is None:
            d["rules"] = d["n"]
    gap = lambda k: [v[k] for v in first.values() if v[k] is not None]  # noqa: E731
    drift = {"episodes": len(first), "median_readings_to_detect_model": float(np.median(gap("model"))) if gap("model") else None,
             "median_readings_to_detect_rules": float(np.median(gap("rules"))) if gap("rules") else None}
    metrics = {
        "eval_readings": int(len(ev)), "eval_attacked": int(y.sum()),
        "roc_auc": round(float(roc_auc_score(y, -se)), 4), "average_precision": round(float(average_precision_score(y, -se)), 4),
        "model_fpr_clean": round(float(flag[clean].mean()), 5), "rules_fpr_clean": round(float(rules[clean].mean()), 5),
        "combined_fpr_clean": round(float((flag | rules)[clean].mean()), 5),
        "per_injector": per, "drift_time_to_detect": drift,
    }
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    meta = {"model": "IsolationForest", "sklearn": sklearn.__version__, "features": FEATURES,
            "params": {"n_estimators": 300, "max_samples": 4096, "contamination": "auto", "random_state": 0},
            "train": {"seeds": TRAIN_SEEDS, "hours_each": HOURS_TRAIN, "readings": int(len(X)), "labels_used": False},
            "calibration": calibration, "calibration_seed": CALIB_SEED,
            "evaluation": {"seeds": EVAL_SEEDS, "hours_each": HOURS_EVAL, "attacks": ATTACKS, **metrics},
            "data": "simulated (PNT1 world simulator); not validated on real telemetry",
            "train_time_s": round(time.time() - t0, 1)}
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta["evaluation"], indent=2))
    print(f"saved {MODEL_PATH.name} and {META_PATH.name} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
