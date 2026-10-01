"""Evaluation (C12): scores the twin against the hidden truth. The ONLY twin-side module that reads truth.

Level 2 scope: per-injector detection metrics and position fidelity. Decision regret needs the oracle
optimizer run and is part of Level 3 (docs/07_ROADMAP.md T27).
"""
from __future__ import annotations

import math

from . import config
from .geo import haversine_km
from .trust import TrustEngine
from .twin import Twin
from .world import World

DETECTED_ACTIONS = {"quarantine", "hold", "replay_dropped", "incomplete", "apply_widened"}


def detection_report(world: World, trust: TrustEngine) -> dict:
    per: dict[str, dict] = {}
    clean = clean_fp = 0
    for eid, lab in world.truth.labels.items():
        v = trust.verdict_log.get(eid)
        if v is None:
            continue       # dropped as exact duplicate at the gateway, or not processed yet
        rho, cls, action = v
        if action == "none":
            continue
        if lab["is_attacked"]:
            d = per.setdefault(lab["injector"], {"attacked_readings": 0, "detected": 0})
            d["attacked_readings"] += 1
            if rho < config.TRUSTED_MIN or action in ("replay_dropped", "incomplete", "quarantine"):
                d["detected"] += 1
        else:
            clean += 1
            if rho < config.QUARANTINE_BELOW and action not in ("incomplete",):
                clean_fp += 1
    for k, d in per.items():
        d["reading_recall"] = round(d["detected"] / d["attacked_readings"], 3) if d["attacked_readings"] else None
    dup = world.truth.attack_log
    return {"per_injector": per, "clean_readings": clean,
            "false_positive_rate": round(clean_fp / clean, 5) if clean else None,
            "attacks_injected": len(dup),
            "note": "Measured on simulated data. Coordinated-stop and blackout attacks are scored by the "
                    "inference/mode layers, not per reading."}


def position_fidelity(world: World, twin: Twin, now: float) -> dict:
    errs = []
    for v in world.vehicles:
        b = twin.vehicles.get(v.id)
        if b is None or b.lat is None:
            continue
        errs.append(haversine_km(v.lat, v.lon, b.lat, b.lon))
    if not errs:
        return {"n": 0}
    errs.sort()
    return {"n": len(errs), "mean_km": round(sum(errs) / len(errs), 3),
            "p90_km": round(errs[int(0.9 * (len(errs) - 1))], 3), "max_km": round(errs[-1], 2)}


def inventory_fidelity(world: World, twin: Twin) -> dict:
    ape = []
    for (w, s), q in world.inv.items():
        b = twin.inventory.get((w, s))
        if b is None:
            continue
        ape.append(abs(b.verified - q) / max(q, 10.0))
    return {"n": len(ape), "mape_pct": round(100 * sum(ape) / len(ape), 2) if ape else None}
