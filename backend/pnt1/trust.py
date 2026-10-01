"""Data Trust Engine (C04, F-10..F-14, F-91): per-reading checks -> reading trust rho -> entity trust tau.

Design: docs/02_ARCHITECTURE.md section 5. Parameters in config.py are first guesses to be tuned.
Statistical (IsolationForest) check is not active at Level 2; weights renormalise over active checks.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from . import config
from .geo import haversine_km, segment_distances_km
from .ingest import Envelope
from .network import Network
from .twin import Twin, sim_seconds
from .anomaly import AnomalyModel, compute_features

REQUIRED_VEHICLE = ("lat", "lon", "speed_kmh")
OPTIONAL_VEHICLE = ("heading_deg", "load_units", "fuel_pct", "shipment_id")


@dataclass
class EntityTrust:
    id: str
    kind: str
    tau: float = config.INITIAL_TRUST
    cls: str = "trusted"
    good: int = 0
    last_anomaly_t: float | None = None
    last_seq: int = -1
    last_fix: tuple[float, float, float] | None = None     # lat, lon, t of last accepted reading
    cusum: float = 0.0
    route_version: int = -1
    checks: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    context_flag_until: float = -1.0
    history: deque = field(default_factory=lambda: deque(maxlen=240))
    ledger: dict = field(default_factory=dict)          # warehouse feeds: flow-reconciled stock per SKU
    last_bad: dict | None = None
    prev: dict | None = None                             # last accepted reading, for statistical features                         # the most recent anomalous reading (for the trust card)
    anomalies: int = 0
    readings: int = 0


@dataclass
class Verdict:
    entity: str
    event_id: str
    event_type: str
    rho: float
    tau: float
    cls: str
    action: str                   # apply | apply_widened | quarantine | hold | incomplete | replay_dropped | none
    checks: dict
    reasons: list[str]
    hard: bool
    t: float
    raw: dict


def classify(tau: float) -> str:
    if tau >= config.TRUSTED_MIN:
        return "trusted"
    if tau >= config.QUARANTINE_BELOW:
        return "estimated"
    return "quarantined"


def aggregate(checks: dict[str, float], weights: dict[str, float]) -> tuple[float, bool]:
    active = {k: v for k, v in checks.items() if k in weights}
    wsum = sum(weights[k] for k in active)
    avg = sum(weights[k] * active[k] for k in active) / wsum if wsum > 0 else 0.0
    hard = any(active.get(k, 1.0) < config.HARD_FAIL_BELOW for k in config.HARD_CHECKS)
    return avg, hard


def update_entity(e: EntityTrust, rho: float, t: float) -> None:
    """Multiplicative decay on anomalies, slow additive recovery after a cooldown."""
    e.readings += 1
    if rho < config.QUARANTINE_BELOW:
        e.tau = min(0.5 * e.tau, rho)
        e.good, e.last_anomaly_t = 0, t
        e.anomalies += 1
    elif rho < config.TRUSTED_MIN:
        e.tau = e.tau * (1 - (config.TRUSTED_MIN - rho))
        e.good, e.last_anomaly_t = 0, t
        e.anomalies += 1
    else:
        e.good += 1
        cooled = e.last_anomaly_t is None or (t - e.last_anomaly_t) >= config.COOLDOWN_SIM_S
        if e.good >= config.COOLDOWN_READINGS and cooled:
            e.tau = e.tau + min(config.RECOVERY_STEP, max(0.0, 0.2 * (rho - e.tau)))
    e.tau = float(min(1.0, max(0.0, e.tau)))
    e.cls = classify(e.tau)


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class TrustEngine:
    def __init__(self, net: Network, twin: Twin):
        self.net, self.twin = net, twin
        self.entities: dict[str, EntityTrust] = {}
        self.quarantine: deque[dict] = deque(maxlen=2000)
        self.verdict_log: dict[str, tuple[float, str, str]] = {}     # event_id -> (rho, cls, action)
        self.anomaly_times: deque[tuple[float, str]] = deque(maxlen=20000)
        self.listeners: list = []
        self._qid = 0
        self.anomaly = AnomalyModel.load()                # None if no trained model is present
        self.collect: list | None = None                 # training harness: capture (event_id, features, rho)

    def entity(self, eid: str, kind: str) -> EntityTrust:
        e = self.entities.get(eid)
        if e is None:
            e = self.entities[eid] = EntityTrust(id=eid, kind=kind)
        return e

    def trust_of(self, eid: str) -> float:
        e = self.entities.get(eid)
        return e.tau if e else config.INITIAL_TRUST

    # ------------------------------------------------------------------ entry point
    def process(self, env: Envelope, now: float) -> Verdict:
        t = sim_seconds(env.ts_event)
        if env.event_type == "telemetry.vehicle":
            v = self._vehicle(env, t, now)
        elif env.event_type == "telemetry.warehouse":
            v = self._warehouse(env, t, now)
        else:
            v = self._passthrough(env, t)
        self.verdict_log[env.event_id] = (v.rho, v.cls, v.action)
        if len(self.verdict_log) > 400_000:
            for k in list(self.verdict_log)[:100_000]:
                del self.verdict_log[k]
        if v.rho < config.TRUSTED_MIN and v.action not in ("none",):
            self.anomaly_times.append((now, "hard" if v.hard or v.rho < config.QUARANTINE_BELOW else "soft"))
        for fn in self.listeners:
            fn(v)
        return v

    # ------------------------------------------------------------------ vehicles
    def _vehicle(self, env: Envelope, t: float, now: float) -> Verdict:
        e = self.entity(env.source_id, "vehicle")
        p = env.payload
        reasons: list[str] = []
        checks: dict[str, float] = {}

        # temporal integrity first: an out-of-order / replayed seq is dropped outright
        if env.seq <= e.last_seq:
            e.tau *= 0.98
            e.cls = classify(e.tau)
            return self._done(e, env, t, 0.0, "replay_dropped", {"temporal": 0.0},
                              [f"temporal: seq {env.seq} <= last {e.last_seq} (replay/out-of-order)"], False)
        e.last_seq = env.seq

        missing_req = [k for k in REQUIRED_VEHICLE if not _num(p.get(k))]
        if missing_req:
            e.tau *= 0.97
            e.cls = classify(e.tau)
            return self._done(e, env, t, 0.0, "incomplete", {"schema": 0.0},
                              [f"schema: missing/invalid required {', '.join(missing_req)}; last trusted value kept"], False)
        missing_opt = [k for k in OPTIONAL_VEHICLE if k not in p]
        checks["schema"] = max(0.3, 1.0 - 0.1 * len(missing_opt))
        if missing_opt:
            reasons.append(f"schema: missing optional {', '.join(missing_opt)} (stale fields)")

        lat, lon, spd = float(p["lat"]), float(p["lon"]), float(p["speed_kmh"])
        la0, la1, lo0, lo1 = config.INDIA_BBOX
        if not (la0 <= lat <= la1 and lo0 <= lon <= lo1):
            checks["physics"] = 0.0
            reasons.append("physics: position outside India bounding box")
        elif spd > config.SPEED_HARD_CAP_KMH:
            checks["physics"] = 0.0
            reasons.append(f"physics: speed {spd:.0f} km/h > hard cap {config.SPEED_HARD_CAP_KMH:.0f}")
        elif spd > config.SPEED_OK_KMH:
            checks["physics"] = 1.0 - (spd - config.SPEED_OK_KMH) / (config.SPEED_HARD_CAP_KMH - config.SPEED_OK_KMH)
            reasons.append(f"physics: speed {spd:.0f} km/h above truck limit")
        else:
            checks["physics"] = 1.0

        implied = None
        x = None
        if e.last_fix is not None and t > e.last_fix[2]:
            dt = t - e.last_fix[2]
            dist = haversine_km(e.last_fix[0], e.last_fix[1], lat, lon)
            implied = dist / max(dt, 1.0) * 3600.0
            if implied <= config.IMPLIED_OK_KMH:
                k = 1.0
            elif implied >= config.IMPLIED_ZERO_KMH:
                k = 0.0
            else:
                k = 1.0 - (implied - config.IMPLIED_OK_KMH) / (config.IMPLIED_ZERO_KMH - config.IMPLIED_OK_KMH)
            if dt >= 10 and abs(implied - spd) > 25 and implied < config.IMPLIED_ZERO_KMH:
                k *= 0.8
                reasons.append(f"kinematic: implied {implied:.0f} km/h vs reported {spd:.0f} km/h")
            if k < 0.5:
                reasons.append(f"kinematic: implied speed {implied:,.0f} km/h from last trusted fix")
            checks["kinematic"] = k
        else:
            checks["kinematic"] = 1.0

        d_road = float(np.min(segment_distances_km(lat, lon, self.net.road_segs)))
        checks["road"] = math.exp(-max(0.0, d_road - config.ROAD_TOLERANCE_KM) / config.ROAD_DECAY_KM)
        if checks["road"] < 0.8:
            reasons.append(f"road-network match: {d_road:.1f} km from nearest road")

        tv = self.twin.vehicle(env.source_id)
        if tv.route:
            if tv.route_version != e.route_version:
                e.route_version, e.cusum = tv.route_version, 0.0
            x = float(np.min(segment_distances_km(lat, lon, self.net.segs(tv.route))))
            checks["route"] = math.exp(-x / config.ROUTE_DECAY_KM)
            dt_c = (t - e.last_fix[2]) if e.last_fix else config.GPS_INTERVAL_S
            e.cusum = max(0.0, e.cusum + (x - config.CUSUM_K_KM) * max(0.0, dt_c) / 300.0)
            if x > 0.3:
                reasons.append(f"route: {x:.2f} km off assigned route")

        if (now - t) > config.STALE_EVENT_S:
            checks["temporal"] = 0.5
            reasons.append(f"temporal: event {now - t:.0f}s old")
        elif (t - now) > 120:
            checks["temporal"] = 0.5
            reasons.append("temporal: timestamp in the future")
        else:
            checks["temporal"] = 1.0

        if now < e.context_flag_until:
            checks["context"] = 0.2
            reasons.append("context: contradicted by independent vehicles on the same link")
        elif tv.route and spd > 30:
            for lid in tv.route:
                if self.twin.active_alert(lid, now):
                    d = float(np.min(segment_distances_km(lat, lon, self.net.segs([lid]))))
                    if d < 0.5:
                        checks["context"] = 0.2
                        reasons.append(f"context: moving normally through alerted link {lid} (alert is MOCK)")
                        break

        heading = float(p.get("heading_deg", 0.0)) if _num(p.get("heading_deg")) else 0.0
        feats = compute_features(e.prev, spd, heading, t, implied, d_road, x)
        a_score = None
        if self.anomaly is not None:
            a_score = self.anomaly.score(feats)
            checks["statistical"] = self.anomaly.confidence(a_score)
            if self.anomaly.flagged(a_score):
                reasons.append(f"statistical: out-of-pattern telemetry (anomaly score {a_score:.3f})")

        avg, hard = aggregate(checks, config.TRUST_WEIGHTS)
        rho = min(config.HARD_CAP, avg) if hard else avg
        if a_score is not None and config.ANOMALY_SOFT_CAP and self.anomaly.flagged(a_score):
            rho = min(rho, config.ANOMALY_SOFT_CAP)
        if e.cusum >= config.CUSUM_H2:
            rho = min(rho, config.CUSUM_HARD_CAP)
            reasons.append(f"route: persistent drift (CUSUM {e.cusum:.1f} >= {config.CUSUM_H2})")
        elif e.cusum >= config.CUSUM_H1:
            rho = min(rho, config.CUSUM_SOFT_CAP)
            reasons.append(f"route: drift building (CUSUM {e.cusum:.1f} >= {config.CUSUM_H1})")
        if hard:
            reasons.insert(0, "hard-fail cap applied (physics/kinematic/road check failed)")

        update_entity(e, rho, t)
        if e.cls == "quarantined":
            action = "quarantine" if rho < config.TRUSTED_MIN else "hold"
        else:
            action = "apply" if e.cls == "trusted" else "apply_widened"
            e.last_fix = (lat, lon, t)
            e.prev = {"t": t, "speed": spd, "heading": heading, "x": x}
            self.twin.apply_vehicle(env.source_id, t, p, widened=(e.cls != "trusted"))
        tv.last_seen_t = t
        if self.collect is not None:
            self.collect.append((env.event_id, feats, rho, a_score))
        return self._done(e, env, t, rho, action, checks, reasons, hard)

    # ------------------------------------------------------------------ warehouse feeds
    def _warehouse(self, env: Envelope, t: float, now: float) -> Verdict:
        node = str(env.payload.get("node_id", env.source_id))
        e = self.entity(f"wh:{node}", "warehouse_feed")
        p = env.payload
        if env.seq <= e.last_seq:
            e.tau *= 0.98
            e.cls = classify(e.tau)
            return self._done(e, env, t, 0.0, "replay_dropped", {"temporal": 0.0},
                              [f"temporal: seq {env.seq} <= last {e.last_seq}"], False)
        e.last_seq = env.seq
        levels_raw = p.get("levels")
        if levels_raw is None:
            e.tau *= 0.97
            e.cls = classify(e.tau)
            return self._done(e, env, t, 0.0, "incomplete", {"schema": 0.0},
                              ["schema: levels missing; last trusted inventory kept"], False)
        checks: dict[str, float] = {"temporal": 1.0}
        reasons: list[str] = []
        levels: dict[str, int] = {}
        ok_types = isinstance(levels_raw, list) and all(
            isinstance(l, dict) and l.get("sku") in config.SKUS and isinstance(l.get("qty"), int)
            and not isinstance(l.get("qty"), bool) for l in levels_raw)
        if not ok_types:
            checks.update({"schema": 0.0, "physics": 0.0})
            reasons.append("schema: corrupted levels (wrong types / garbled values)")
        else:
            levels = {l["sku"]: int(l["qty"]) for l in levels_raw}
            checks["schema"] = 1.0 if len(levels) == len(config.SKUS) else 0.7
            cap = self.net.nodes[node].capacity if node in self.net.nodes else 10**9
            if any(q < 0 or q > cap for q in levels.values()) or sum(levels.values()) > cap:
                checks["physics"] = 0.0
                reasons.append(f"physics: stock exceeds capacity {cap:,}")
            else:
                checks["physics"] = 1.0
        inbound = p.get("inbound", {}) if isinstance(p.get("inbound"), dict) else {}
        outbound = p.get("outbound", {}) if isinstance(p.get("outbound"), dict) else {}
        expected: dict[str, float] = {}
        rec = 1.0
        for s in config.SKUS:
            flow = float(inbound.get(s, 0) or 0) - float(outbound.get(s, 0) or 0) if \
                _num(inbound.get(s, 0) or 0) and _num(outbound.get(s, 0) or 0) else 0.0
            if s not in e.ledger:
                expected[s] = float(levels.get(s, 0))
                continue
            expected[s] = max(0.0, e.ledger[s] + flow)
            if s in levels:
                diff = abs(levels[s] - expected[s])
                tol = max(5.0, 0.02 * expected[s])
                span = max(20.0, 0.20 * expected[s])
                c = 1.0 if diff <= tol else max(0.0, 1.0 - (diff - tol) / span)
                if c < 0.8:
                    reasons.append(f"reconcile: {s} reported {levels[s]:,} vs flow-expected {expected[s]:,.0f}")
                rec = min(rec, c)
        if levels:
            checks["reconcile"] = rec
        avg, _ = aggregate(checks, config.FEED_WEIGHTS)
        hard = checks.get("physics", 1.0) < config.HARD_FAIL_BELOW
        rho = min(config.HARD_CAP, avg) if hard else avg
        if hard:
            reasons.insert(0, "hard-fail cap applied")
        update_entity(e, rho, t)
        # the engine's private flow ledger always advances (it is not twin state)
        count_ok = e.cls == "trusted" and rho >= config.TRUSTED_MIN
        for s in config.SKUS:
            if s in levels and (count_ok or s not in e.ledger):
                e.ledger[s] = float(levels[s])
            elif s in expected:
                e.ledger[s] = expected[s]
        if levels and e.cls != "quarantined":
            self.twin.apply_inventory(node, t, levels, {s: e.ledger[s] for s in levels}, e.tau,
                                      "verified" if count_ok else "estimated")
        action = {"trusted": "apply", "estimated": "apply_widened"}.get(e.cls, "quarantine")
        if e.cls == "quarantined" and rho >= config.TRUSTED_MIN:
            action = "hold"
        return self._done(e, env, t, rho, action, checks, reasons, hard)

    # ------------------------------------------------------------------ other event types
    def _passthrough(self, env: Envelope, t: float) -> Verdict:
        e = self.entity(env.source_id, env.source_type)
        p = env.payload
        if env.event_type == "telemetry.shipment":
            self.twin.apply_shipment(p, t)
        elif env.event_type == "telemetry.port":
            self.twin.apply_port(str(p.get("node_id", env.source_id)), t, p)
        elif env.event_type == "signal.alert":
            self.twin.apply_alert(t, p)
        return self._done(e, env, t, 1.0, "none", {}, [], False)

    def _done(self, e: EntityTrust, env: Envelope, t: float, rho: float, action: str, checks: dict,
              reasons: list[str], hard: bool) -> Verdict:
        e.checks, e.reasons = checks, reasons
        e.history.append((t, round(rho, 3), round(e.tau, 3), e.cls))
        if action != "none" and (rho < config.TRUSTED_MIN or action in ("replay_dropped", "incomplete")):
            e.last_bad = {"t": t, "rho": round(rho, 3), "tau_after": round(e.tau, 3), "checks": checks,
                          "reasons": reasons, "action": action, "raw": env.payload, "hard": hard}
        if action == "quarantine":
            self._qid += 1
            self.quarantine.appendleft({"id": self._qid, "entity": e.id, "event_id": env.event_id, "t": t,
                                        "rho": round(rho, 3), "tau": round(e.tau, 3), "reasons": reasons,
                                        "raw": env.payload, "review": "open"})
        return Verdict(e.id, env.event_id, env.event_type, rho, e.tau, e.cls, action, checks, reasons, hard, t,
                       env.payload)
