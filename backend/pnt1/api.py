"""HTTP + WebSocket API (C14). Level 2: no auth yet (JWT/RBAC is Level 3, docs/07_ROADMAP.md T31)."""
from __future__ import annotations

import asyncio
import contextlib
import math
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .evaluation import detection_report, inventory_fidelity, position_fidelity
from .graph import blast_radius, fragility
from .costing import assumptions as cost_assumptions
from .planning import Disruption, solve_plan, weights_from_priorities
from .strategies import link_period_flows
from .runtime import Runtime
from .strategies import evaluate_scenario, raw_vs_trusted
from .world import INJECTORS, SCENARIO_EVENTS

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
rt: Runtime | None = None


def clean(x: Any) -> Any:
    """Make numpy / NaN values JSON-safe."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.ndarray):
        return clean(x.tolist())
    return x


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global rt
    rt = Runtime(audit_path=str(config.DATA_DIR / "audit.sqlite3"))
    rt.weather.start()
    task = asyncio.create_task(rt.run_forever())
    yield
    task.cancel()


app = FastAPI(title="PNT1 Logistics Network Digital Twin", version="2.5.0", lifespan=lifespan)


def R() -> Runtime:
    assert rt is not None
    return rt


# ---------------------------------------------------------------- core views
@app.get("/api/network")
def network():
    return R().net.to_geojson()


@app.get("/api/state")
def state():
    return clean(R().snapshot())


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    try:
        while True:
            await sock.send_json(clean(R().snapshot()))
            await asyncio.sleep(1.0)
    except (WebSocketDisconnect, RuntimeError):
        return


class ClockIn(BaseModel):
    speed: float | None = Field(default=None, ge=1, le=600)
    paused: bool | None = None


@app.post("/api/clock")
def clock(body: ClockIn):
    r = R()
    if body.speed is not None:
        r.speed = body.speed
    if body.paused is not None:
        r.paused = body.paused
    return {"speed": r.speed, "paused": r.paused}


# ---------------------------------------------------------------- trust
@app.get("/api/trust/entities")
def trust_entities():
    return [{"id": e.id, "kind": e.kind, "tau": round(e.tau, 3), "cls": e.cls, "anomalies": e.anomalies}
            for e in R().trust.entities.values() if e.kind in ("vehicle", "warehouse_feed")]


@app.get("/api/trust/{entity_id}")
def trust_card(entity_id: str):
    r = R()
    e = r.trust.entities.get(entity_id)
    if e is None:
        raise HTTPException(404, "unknown entity")
    with r.lock:
        raw = next((q["raw"] for q in r.trust.quarantine if q["entity"] == entity_id), None)
        return clean({"id": e.id, "kind": e.kind, "tau": e.tau, "cls": e.cls, "checks": e.checks, "reasons": e.reasons,
                      "cusum": e.cusum, "history": list(e.history), "anomalies": e.anomalies, "readings": e.readings,
                      "last_quarantined_raw": raw, "last_anomaly": e.last_bad,
                      "weights": config.TRUST_WEIGHTS if e.kind == "vehicle" else config.FEED_WEIGHTS,
                      "inactive_checks": ["statistical"] if e.kind == "vehicle" and r.trust.anomaly is None else [],
                      "note": "Road-network match uses straight-line synthetic link geometry."})


@app.get("/api/quarantine")
def quarantine():
    return clean(list(R().trust.quarantine)[:100])


class ReviewIn(BaseModel):
    verdict: str = Field(pattern="^(confirmed_attack|false_positive)$")


@app.post("/api/quarantine/{qid}/review")
def review(qid: int, body: ReviewIn):
    r = R()
    for q in r.trust.quarantine:
        if q["id"] == qid:
            q["review"] = body.verdict
            r.audit.append("quarantine_review", "operator", {"quarantine_id": qid, "entity": q["entity"],
                                                             "verdict": body.verdict}, r.world.t)
            return q
    raise HTTPException(404, "not found")


# ---------------------------------------------------------------- attacks
ATTACK_HELP = {
    "gps_spoof_teleport": ("vehicle", "Truck suddenly reports a position in the sea"),
    "gps_spoof_drift": ("vehicle", "Truck position slowly drifts off its route (hard to catch)"),
    "speed_spike": ("vehicle", "Truck reports an impossible 780-812 km/h"),
    "inventory_fake": ("warehouse", "Warehouse reports +40% SKU-B stock that is not there"),
    "feed_corrupt": ("warehouse", "Warehouse feed sends garbled types / x1000 units"),
    "payload_incomplete": ("fleet", "30% of a fleet's messages lose fields"),
    "duplicate_replay": ("fleet", "Old messages from a fleet are re-sent"),
    "entity_blackout": ("vehicle_or_warehouse", "One source goes silent"),
    "mass_blackout": ("none", "70% of all sources go silent"),
    "coordinated_stop_spoof": ("link", "Several trucks of ONE fleet fake a queue on a road"),
    "real_blockage": ("link", "Scenario: the road really is blocked (trucks of all fleets stop; MOCK alert)"),
}


@app.get("/api/attacks/catalog")
def attack_catalog():
    r = R()
    return {"injectors": [{"kind": k, "target": ATTACK_HELP[k][0], "description": ATTACK_HELP[k][1]}
                          for k in list(INJECTORS) + list(SCENARIO_EVENTS)],
            "vehicles": sorted(v.id for v in r.world.vehicles), "warehouses": r.world.warehouses,
            "fleets": list(config.N_VEHICLES), "road_links": [l for l in r.net.road_ids]}


class AttackIn(BaseModel):
    kind: str
    targets: list[str] = []
    params: dict = {}
    duration_s: float | None = Field(default=None, gt=0, le=6 * 3600)


@app.post("/api/attacks")
def inject(body: AttackIn):
    r = R()
    if body.kind not in INJECTORS and body.kind not in SCENARIO_EVENTS:
        raise HTTPException(400, "unknown injector")
    with r.lock:
        params = dict(body.params)
        if body.kind == "coordinated_stop_spoof" and body.targets:
            params.setdefault("link", body.targets[0])
        a = r.world.inject(body.kind, body.targets, params, body.duration_s)
        r.alert("info", "attack.injected", ",".join(a.targets[:3]) or "network",
                f"injected {body.kind} on {', '.join(a.targets[:4]) or 'network'}")
        r.audit.append("attack_injected", "operator", {"id": a.id, "kind": a.kind, "targets": a.targets[:20],
                                                              "duration_s": a.end - a.start}, r.world.t)
        return {"id": a.id, "kind": a.kind, "targets": a.targets, "ends_at": a.end}


@app.post("/api/attacks/stop")
def stop_attacks():
    with R().lock:
        R().world.stop_attacks()
        R().resolve_all()
    return {"stopped": True}


# ---------------------------------------------------------------- graph
@app.get("/api/graph/fragility")
def graph_fragility():
    return fragility(R().net)


@app.get("/api/graph/blast/{node}")
def graph_blast(node: str):
    return blast_radius(R().net, node)


@app.get("/api/inference")
def inference():
    r = R()
    return clean({"active": list(r.inference.events.values()), "log": r.inference.log[-30:][::-1]})


# ---------------------------------------------------------------- scenarios & decisions
class ScenarioIn(BaseModel):
    kind: str = Field(pattern="^(storm|link_closure|port_closure|warehouse_failure|supplier_failure|demand_spike)$")
    target: str
    start_h: float = Field(default=6, ge=0, le=48)
    duration_h: float = Field(default=36, gt=0, le=72)
    magnitude: float = Field(default=0.6, ge=0, le=3)
    probability: float = Field(default=0.7, ge=0, le=1)
    preset: str = Field(default="balanced", pattern="^(cheapest|fastest|lowest_carbon|lowest_risk|balanced)$")
    # V2: user priorities over money / time / fuel / distance / carbon (shares); overrides the preset when given
    weights: dict[str, float] | None = None
    runs: int = Field(default=config.MC_RUNS, ge=config.MC_RUNS_MIN, le=config.MC_RUNS_MAX)


def _priority_weights(w: dict | None) -> dict | None:
    if not w:
        return None
    bad = set(w) - {"money", "time", "fuel", "distance", "carbon"}
    if bad or any((not isinstance(v, (int, float))) or v < 0 for v in w.values()) or sum(w.values()) <= 0:
        raise HTTPException(400, "weights: non-negative money/time/fuel/distance/carbon with a positive sum")
    return w


@app.post("/api/scenarios/run")
async def run_scenario(body: ScenarioIn):
    r = R()
    if body.target not in r.net.nodes and body.target not in r.net.links and body.target != "all":
        raise HTTPException(400, "unknown target")
    inv = r.planning_inventory()
    d = Disruption(body.kind, body.target, body.start_h, body.duration_h, body.magnitude)
    lpw = weights_from_priorities(_priority_weights(body.weights))
    res = await asyncio.to_thread(evaluate_scenario, r.net, r.engine, inv, d, body.probability, body.preset,
                                  11, body.runs, lpw)
    sid = f"scn-{uuid.uuid4().hex[:8]}"
    res = clean(res)
    res.update({"id": sid, "input": body.model_dump(), "sim_t": r.world.t})
    r.scenarios[sid] = {"result": res, "inventory": inv}
    rec = res["strategies"][res["recommended"]]
    r.audit.append("recommendation", "optimizer", {
        "scenario_id": sid, "input": body.model_dump(), "recommended": res["recommended"],
        "reason": res.get("recommendation_reason"), "expected_cost": rec["expected_cost"],
        "optimizer": res["optimizer"], "config_trust_weights": config.TRUST_WEIGHTS,
        "trust_snapshot": {k: round(v.tau, 3) for k, v in r.trust.entities.items() if k.startswith("wh:")}}, r.world.t)
    return res


@app.get("/api/scenarios/{sid}")
def get_scenario(sid: str):
    s = R().scenarios.get(sid)
    if not s:
        raise HTTPException(404, "not found")
    return s["result"]


class CompareIn(BaseModel):
    kind: str | None = None
    target: str | None = None
    start_h: float = 6
    duration_h: float = 36
    magnitude: float = 0.6


@app.post("/api/compare/raw-vs-trusted")
async def compare(body: CompareIn):
    r = R()
    d = Disruption(body.kind, body.target, body.start_h, body.duration_h, body.magnitude) \
        if body.kind and body.target else None
    trusted, raw = r.planning_inventory(), r.planning_inventory(raw=True)
    res = await asyncio.to_thread(raw_vs_trusted, r.net, r.engine, trusted, raw, d)
    return clean(res)


class DecisionIn(BaseModel):
    scenario_id: str
    strategy: str = Field(pattern="^(do_nothing|reroute|transfer|hybrid)$")
    action: str = Field(pattern="^(approve|reject)$")
    note: str = Field(default="", max_length=500)
    approver: str = Field(default="operator", max_length=64)


@app.post("/api/decisions")
def decide(body: DecisionIn):
    r = R()
    s = r.scenarios.get(body.scenario_id)
    if not s:
        raise HTTPException(404, "unknown scenario")
    st = s["result"]["strategies"][body.strategy]
    entry = {"scenario_id": body.scenario_id, "strategy": body.strategy, "action": body.action, "note": body.note,
             "approver": body.approver, "recommended": s["result"]["recommended"],
             "expected_cost": st["expected_cost"], "action_cost": st["action_cost"]}
    seq = r.audit.append("decision", body.approver, entry, r.world.t)
    entry["audit_seq"] = seq
    r.decisions.append(entry)
    if body.action == "approve":
        r.active_plan = {"scenario_id": body.scenario_id, "strategy": body.strategy, "approved_at": r.world.t,
                         "input": s["result"]["input"], "audit_seq": seq}
        r.alert("info", "decision.approved", body.strategy, f"Plan '{body.strategy}' approved (audit #{seq})")
    return entry


# ---------------------------------------------------------------- audit & evaluation
@app.get("/api/audit")
def audit(limit: int = 200, entry_type: str | None = None):
    return R().audit.list(limit, entry_type)


@app.get("/api/audit/verify")
def audit_verify():
    return R().audit.verify()


@app.post("/api/audit/{seq}/replay")
async def audit_replay(seq: int):
    r = R()
    e = r.audit.get(seq)
    if not e or e["entry_type"] != "recommendation":
        raise HTTPException(400, "only recommendation entries can be replayed")
    sid = e["body"]["scenario_id"]
    stored = r.scenarios.get(sid)
    if not stored:
        raise HTTPException(404, "scenario inputs not in memory (server restarted)")
    inp = stored["result"]["input"]
    d = Disruption(inp["kind"], inp["target"], inp["start_h"], inp["duration_h"], inp["magnitude"])
    res = await asyncio.to_thread(evaluate_scenario, r.net, r.engine, stored["inventory"], d, inp["probability"],
                                  inp["preset"], 11, inp.get("runs", config.MC_RUNS),
                                  weights_from_priorities(inp.get("weights")))
    same = res["recommended"] == e["body"]["recommended"]
    return clean({"original": e["body"]["recommended"], "replayed": res["recommended"], "identical": same,
                  "original_expected_cost": e["body"]["expected_cost"],
                  "replayed_expected_cost": res["strategies"][res["recommended"]]["expected_cost"]})


@app.get("/api/eval/detection")
def eval_detection():
    r = R()
    with r.lock:
        return clean(detection_report(r.world, r.trust))


@app.get("/api/eval/fidelity")
def eval_fidelity():
    r = R()
    with r.lock:
        return clean({"position": position_fidelity(r.world, r.twin, r.world.t),
                      "inventory": inventory_fidelity(r.world, r.twin),
                      "note": "Twin belief compared with the hidden simulated truth (evaluation only)."})


@app.get("/api/models")
def models():
    """Model cards for trained models (training protocol, calibration and held-out evaluation)."""
    a = R().trust.anomaly
    return {"anomaly": a.meta if a is not None else None}


@app.get("/api/dlq")
def dlq():
    return list(R().gateway.dlq)[-50:][::-1]


@app.post("/ingest/batch")
async def ingest_batch(batch: list[Any]):
    r = R()
    if len(batch) > 500:
        raise HTTPException(413, "max 500 envelopes per batch")
    with r.lock:
        results = [r.gateway.ingest(x) for x in batch]
    return {"accepted": results.count("accepted"), "duplicate": results.count("duplicate"), "dlq": results.count("dlq")}


# ================================================================ V2 endpoints
@app.get("/api/resilience")
def resilience():
    r = R()
    with r.lock:
        res = r.resilience.last or r.resilience.compute(r)
        return clean({"current": res, "history": list(r.resilience.history)[-360:],
                      "changes": list(r.resilience.changes),
                      "weights": {k: v["weight"] for k, v in res["components"].items()},
                      "bands": config.RESILIENCE_BANDS,
                      "method": "Nine components (eight when weather is unavailable) from the twin's live belief; see pnt1/resilience.py"})


class RoutePlanIn(BaseModel):
    origin: str
    destination: str
    units: float = Field(default=config.TRUCK_CAPACITY, gt=0, le=2000)
    weights: dict[str, float] | None = None
    prev_weights: dict[str, float] | None = None
    priority: str = Field(default="NORMAL", pattern="^(NORMAL|HIGH|CRITICAL)$")
    avoid_disruptions: bool = True
    what_if_closed: list[str] = Field(default=[], max_length=20)     # plan as if these links were closed


@app.post("/api/routes/plan")
def routes_plan(body: RoutePlanIn):
    r = R()
    _priority_weights(body.weights)
    if any(l not in r.net.links for l in body.what_if_closed):
        raise HTTPException(400, "unknown link in what_if_closed")
    with r.lock:
        closed, nodes, _, state = r.closed_state() if body.avoid_disruptions else (set(), set(), set(), {})
    closed = set(closed) | set(body.what_if_closed)
    res = r.planner.plan(body.origin, body.destination, body.units, body.weights, body.priority, state, closed, nodes,
                         body.prev_weights)
    if res.get("error") and not res.get("routes"):
        raise HTTPException(400, res["error"])
    return clean(res)


@app.get("/api/cost/assumptions")
def cost_model():
    return clean(cost_assumptions())


class IncidentIn(BaseModel):
    kind: str = Field(pattern="^(storm|link_closure|port_closure|warehouse_failure|supplier_failure)$")
    target: str
    duration_h: float = Field(default=6, gt=0, le=72)
    start_in_h: float = Field(default=0, ge=0, le=48)
    note: str = Field(default="", max_length=300)


@app.post("/api/incidents")
def open_incident(body: IncidentIn):
    try:
        return clean(R().open_incident(body.kind, body.target, body.duration_h, body.note, body.start_in_h))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/incidents")
def incidents():
    return clean(R().incidents[-50:][::-1])


@app.post("/api/incidents/{iid}/resolve")
def resolve_incident(iid: str):
    try:
        return clean(R().resolve_incident(iid))
    except KeyError as e:
        raise HTTPException(404, "unknown incident") from e


@app.get("/api/recovery/affected")
def recovery_affected():
    return clean(R().affected_trucks())


class RecoveryIn(BaseModel):
    vehicle_id: str
    weights: dict[str, float] | None = None
    prev_weights: dict[str, float] | None = None


@app.post("/api/recovery/options")
def recovery_options(body: RecoveryIn):
    _priority_weights(body.weights)
    try:
        return clean(R().recovery_options(body.vehicle_id, body.weights, body.prev_weights))
    except KeyError as e:
        raise HTTPException(404, "vehicle not found or has no active route") from e


class ApproveIn(BaseModel):
    vehicle_id: str
    route_id: str = Field(max_length=32)
    hops: list[tuple[str, bool]] = Field(min_length=1, max_length=40)
    approver: str = Field(default="operator", max_length=64)
    note: str = Field(default="", max_length=300)


@app.post("/api/recovery/approve")
def recovery_approve(body: ApproveIn):
    try:
        return clean(R().approve_reroute(body.vehicle_id, [list(h) for h in body.hops], body.route_id, body.approver, body.note))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/orders")
def orders(all: bool = False):
    r = R()
    with r.lock:
        o, _, _ = r._orders(loaded_only=not all)
    return clean(o)


@app.get("/api/fusion/{vehicle_id}")
def fusion(vehicle_id: str):
    r = R()
    with r.lock:
        v = r.twin.vehicles.get(vehicle_id)
        if v is None or v.lat is None:
            raise HTTPException(404, "vehicle has not reported yet")
        now = r.world.t

        def alerts_on(tv):
            return [lid for lid in (tv.route or []) if r.twin.active_alert(lid, now)]
        return clean(r.ops.fusion(v, r.trust.entities.get(vehicle_id), now, r.inference.events, alerts_on))


@app.get("/api/fleet/health")
def fleet_health():
    r = R()
    with r.lock:
        now = r.world.t
        out = [r.ops.health(v, r.trust.entities.get(v.id), now) for v in r.twin.vehicles.values() if v.lat is not None]
    out.sort(key=lambda x: -x["risk"])
    return clean(out)


@app.get("/api/flows/baseline")
async def baseline_flows():
    """LP baseline plan (balanced) from current trusted inventory: drives the ship / rail / cargo-flow animation.
    These are PLANNED flows from the optimizer, not tracked vessels or trains."""
    r = R()
    now = r.world.t
    c = r._flows_cache
    if c and now - c["t"] < 6 * 3600:
        return c["res"]
    inv = r.planning_inventory()
    with r.lock:
        closed, nodes, _, _ = r.closed_state()
    dis = [Disruption("link_closure", lid, 0, 72) for lid in sorted(closed)]
    plan = await asyncio.to_thread(solve_plan, r.net, inv, dis, "balanced", "live-baseline")
    per = link_period_flows(r.net, plan.flows)
    res = clean({"t": now, "status": plan.status, "per_link_per_day": {k: round(sum(v) / (config.HORIZON_H / 24), 1) for k, v in per.items()},
                 "data_mode": "PLANNED (LP)", "note": "Ships and trains animate optimizer-planned flows, not tracked assets."})
    r._flows_cache = {"t": now, "res": res}
    return res


class TicketIn(BaseModel):
    order_id: str = Field(max_length=40)
    category: str = Field(pattern="^(delay|damage|reroute|documentation|other)$")
    message: str = Field(min_length=3, max_length=600)
    contact: str = Field(default="operator", max_length=80)


@app.post("/api/support/tickets")
def create_ticket(body: TicketIn):
    r = R()
    with r.lock:
        tid = f"T-{len(r.tickets) + 1:04d}"
        t = {"id": tid, **body.model_dump(), "t": r.world.t, "status": "open"}
        t["audit_seq"] = r.audit.append("support_ticket", body.contact, t, r.world.t)
        r.tickets.append(t)
        r.alert("info", "support.ticket", body.order_id, f"Support ticket {tid} ({body.category}) for order {body.order_id}")
    return t


@app.get("/api/support/tickets")
def list_tickets():
    return R().tickets[-50:][::-1]


# ---------------------------------------------------------------- frontend
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")


# ---------------------------------------------------------------- V2.1: real weather, tile cache, cost inputs
@app.get("/api/weather")
def weather():
    return clean(R().weather_view())


@app.get("/api/weather/point/{pid}")
def weather_point(pid: str):
    d = R().weather.point_detail(pid)
    if d is None:
        raise HTTPException(404, "no weather data for this point")
    return clean(d)


@app.get("/api/weather/diagnostics")
async def weather_diagnostics():
    """Connectivity test against every weather and hazard host, with the exact failure reason and what to do about it."""
    return clean(await asyncio.to_thread(R().weather.diagnose))


@app.post("/api/weather/refresh")
def weather_refresh():
    w = R().weather
    ok = w.refresh()
    return clean({"ok": ok, "meta": w.meta()})


class CostIn(BaseModel):
    road_fuel_inr_per_l: float | None = Field(default=None, ge=40, le=200)
    road_km_per_l: float | None = Field(default=None, ge=1, le=8)
    road_toll_inr_per_km: float | None = Field(default=None, ge=0, le=30)
    road_crew_inr_per_h: float | None = Field(default=None, ge=50, le=1000)
    rail_inr_per_kwh: float | None = Field(default=None, ge=2, le=30)
    sea_fuel_inr_per_l: float | None = Field(default=None, ge=30, le=200)
    reset: bool = False


_COST_DEFAULTS: dict | None = None
_COST_KEYS = {"road_fuel_inr_per_l": ("road", "fuel_inr_per_l"), "road_km_per_l": ("road", "km_per_l"),
              "road_toll_inr_per_km": ("road", "toll_inr_per_km"), "road_crew_inr_per_h": ("road", "crew_inr_per_h"),
              "rail_inr_per_kwh": ("rail", "inr_per_kwh"), "sea_fuel_inr_per_l": ("sea", "fuel_inr_per_l")}


@app.post("/api/cost/assumptions")
def set_cost_model(body: CostIn):
    """Operator-edited planning inputs (still labelled as assumptions). They feed the real cost engine; audit-logged."""
    global _COST_DEFAULTS
    import copy
    r = R()
    if _COST_DEFAULTS is None:
        _COST_DEFAULTS = copy.deepcopy({m: config.COST_MODEL[m] for m in ("road", "rail", "sea")})
    changed = {}
    with r.lock:
        if body.reset:
            for m, d in _COST_DEFAULTS.items():
                config.COST_MODEL[m].update(d)
            changed = {"reset": True}
        else:
            for k, (m, f) in _COST_KEYS.items():
                v = getattr(body, k)
                if v is not None:
                    config.COST_MODEL[m][f] = float(v)
                    changed[k] = float(v)
        r.planner.clear_cache() if hasattr(r.planner, "clear_cache") else None
        r.audit.append("cost_assumptions", "operator", changed, r.world.t)
    return {"changed": changed, "assumptions": clean(cost_assumptions())}


TILE_UP = {"sat": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
           "dem": "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"}
TILE_DIR = config.DATA_DIR / "tile_cache"
_tile_job: dict = {"running": False, "done": 0, "total": 0, "failed": 0, "kind": None}


def _tile_fetch(layer: str, z: int, x: int, y: int) -> bytes | None:
    import os
    import urllib.request
    base = os.environ.get("PNT1_TILE_UPSTREAM")            # tests / air-gapped mirrors
    url = (base.rstrip("/") + f"/{layer}/{z}/{x}/{y}.png") if base else TILE_UP[layer].format(z=z, x=x, y=y)
    f = TILE_DIR / layer / str(z) / str(x) / f"{y}.tile"
    if f.exists():
        return f.read_bytes()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pnt1-digital-twin/2.5"})
        with urllib.request.urlopen(req, timeout=12) as resp:     # noqa: S310 - fixed hosts
            data = resp.read()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        return data
    except Exception:  # noqa: BLE001
        return None


@app.get("/tiles/{layer}/{z}/{x}/{y}")
def tile(layer: str, z: int, x: int, y: int):
    from fastapi.responses import Response
    if layer not in TILE_UP or not (0 <= z <= 17) or x < 0 or y < 0 or x >= 2 ** z or y >= 2 ** z:
        raise HTTPException(404, "no such tile")
    data = _tile_fetch(layer, z, x, y)
    if data is None:
        raise HTTPException(404, "tile unavailable (no internet and not cached)")
    mt = "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
    return Response(data, media_type=mt, headers={"Cache-Control": "public, max-age=604800"})


def _tiles_for(zmax_india: int, zmax_city: int) -> list[tuple[str, int, int, int]]:
    def xy(lat, lon, z):
        n = 2 ** z
        return (int((lon + 180) / 360 * n),
                int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n))
    out = set()
    for z in range(2, zmax_india + 1):
        x0, y0 = xy(37.5, 67.0, z)
        x1, y1 = xy(6.0, 98.0, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                out.add(("sat", z, x, y))
                if z <= 9:
                    out.add(("dem", z, x, y))
    r = R()
    for n in r.net.nodes.values():
        if n.type == "CustomerCluster":
            continue
        for z in range(zmax_india + 1, zmax_city + 1):
            cx, cy = xy(n.lat, n.lon, z)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    out.add(("sat", z, cx + dx, cy + dy))
                    if z <= 9:
                        out.add(("dem", z, cx + dx, cy + dy))
    return sorted(out)


class PrewarmIn(BaseModel):
    india_zoom: int = Field(default=7, ge=3, le=8)
    city_zoom: int = Field(default=11, ge=7, le=12)


@app.post("/api/tiles/prewarm")
def tiles_prewarm(body: PrewarmIn):
    import concurrent.futures
    import threading
    if _tile_job["running"]:
        return _tile_job
    todo = _tiles_for(body.india_zoom, max(body.city_zoom, body.india_zoom))
    _tile_job.update(running=True, done=0, total=len(todo), failed=0, kind="offline pack")

    def work():
        with concurrent.futures.ThreadPoolExecutor(8) as ex:
            for ok in ex.map(lambda t: _tile_fetch(*t) is not None, todo):
                _tile_job["done"] += 1
                _tile_job["failed"] += 0 if ok else 1
        _tile_job["running"] = False
    threading.Thread(target=work, daemon=True).start()
    return _tile_job


@app.get("/api/tiles/status")
def tiles_status():
    n = sum(1 for _ in TILE_DIR.rglob("*.tile")) if TILE_DIR.exists() else 0
    mb = sum(f.stat().st_size for f in TILE_DIR.rglob("*.tile")) / 1e6 if TILE_DIR.exists() else 0.0
    return {"cached_tiles": n, "cached_mb": round(mb, 1), "job": _tile_job}
