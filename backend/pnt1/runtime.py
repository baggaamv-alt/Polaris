"""Runtime: wires world -> gateway -> bus -> trust -> twin -> modes -> inference, on a live sim clock."""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque

from . import config
from .audit import AuditLog
from .engine import Engine
from .inference import BlockageInference
from .ingest import Bus, Gateway
from .modes import ModeController
from .network import Network, warehouse_served_demand
from .trust import TrustEngine, Verdict
from .twin import Twin
from .world import World
from .costing import RoutePlanner
from .ops import Ops
from .planning import Disruption
from .resilience import Resilience
from .weather import WeatherFeed, level as weather_level


class Runtime:
    def __init__(self, seed: int = config.WORLD_SEED, audit_path: str | None = None):
        self.net = Network()
        self.world = World(self.net, seed)
        self.bus = Bus()
        self.gateway = Gateway(self.bus)
        self.twin = Twin(self.net)
        self.trust = TrustEngine(self.net, self.twin)
        self.modes = ModeController(self.twin, self.trust, len(self.world.warehouses), len(self.world.vehicles),
                                    len(self.world.ports))
        self.inference = BlockageInference(self.net, self.twin, self.trust)
        self.engine = Engine(self.net)
        self.audit = AuditLog(audit_path or ":memory:")
        self.lock = threading.RLock()
        self.speed = config.DEFAULT_CLOCK_SPEED
        self.paused = False
        self.alerts: deque[dict] = deque(maxlen=300)
        self._alert_id = 0
        self._last_alert: dict[str, float] = {}
        self._prev_cls: dict[str, str] = {}
        self.processing_errors = 0
        self.scenarios: dict[str, dict] = {}
        self.decisions: list[dict] = []
        self.active_plan: dict | None = None
        self.last_tick_ms = 0.0
        # V2
        self.ops = Ops(self.net, self.twin)
        self.planner = RoutePlanner(self.net)
        self.resilience = Resilience(self.net)
        self.weather = WeatherFeed(self.net)
        self.ops.weather = self.weather
        self.incidents: list[dict] = []
        self.recoveries: list[dict] = []
        self.tickets: list[dict] = []
        self._inc_id = 0
        self._res_next = 0.0
        self._flows_cache: dict | None = None
        self.trust.listeners.append(self._on_verdict)
        self.audit.append("system", "runtime", {"event": "start", "seed": seed, "network_version": self.net.version}, 0.0)

    # ------------------------------------------------------------------ alerts
    def alert(self, severity: str, kind: str, entity: str, text: str, data: dict | None = None) -> None:
        self._alert_id += 1
        self.alerts.appendleft({"id": self._alert_id, "t": self.world.t, "severity": severity, "kind": kind,
                                "entity": entity, "text": text, "data": data or {}})

    def _on_verdict(self, v: Verdict) -> None:
        prev = self._prev_cls.get(v.entity, "trusted")
        self._prev_cls[v.entity] = v.cls
        if v.cls == "quarantined" and prev != "quarantined":
            self.alert("critical", "trust.anomaly", v.entity, f"{v.entity} quarantined: {(v.reasons or ['low trust'])[0]}",
                       {"rho": round(v.rho, 3), "tau": round(v.tau, 3)})
            self.audit.append("quarantine", "trust-engine", {"entity": v.entity, "event_id": v.event_id,
                                                             "rho": round(v.rho, 3), "reasons": v.reasons[:4]}, v.t)
            return
        if prev == "quarantined" and v.cls != "quarantined":
            self.alert("info", "trust.recovered", v.entity, f"{v.entity} trust recovered ({v.cls})")
            return
        if v.action in ("apply_widened", "quarantine", "replay_dropped", "incomplete") or v.rho < config.TRUSTED_MIN:
            last = self._last_alert.get(v.entity, -1e9)
            if self.world.t - last >= 300:
                self._last_alert[v.entity] = self.world.t
                sev = "warning" if v.cls != "quarantined" else "critical"
                self.alert(sev, "trust.anomaly", v.entity, f"{v.entity}: {(v.reasons or [v.action])[0]}",
                           {"rho": round(v.rho, 3), "tau": round(v.tau, 3), "action": v.action})

    # ------------------------------------------------------------------ loop
    def tick(self, dt_sim: float) -> None:
        with self.lock:
            t0 = time.perf_counter()
            for env in self.world.step(dt_sim):
                self.gateway.ingest(env)
            for env in self.bus.drain():
                try:
                    self.trust.process(env, self.world.t)
                except Exception:  # noqa: BLE001 - one bad message must never stop the pipeline (F-98)
                    self.processing_errors += 1
            m = self.modes.tick(self.world.t)
            if m:
                sev = {"BLIND": "critical", "DEGRADED": "warning"}.get(m["to"], "info")
                self.alert(sev, "mode.changed", "network", f"Network mode {m['from']} -> {m['to']} ({m['reason']})", m)
                self.audit.append("mode_change", "mode-controller", m, self.world.t)
            for ev in self.inference.tick(self.world.t):
                if ev["status"] == "blocked_inferred":
                    self.alert("critical", "inference", ev["link_id"],
                               f"Road {ev['link_id']} BLOCKED (inferred, confidence {ev['confidence']:.2f}); corroborated", ev)
                elif ev["status"] == "suspected":
                    self.alert("warning", "inference", ev["link_id"],
                               f"Road {ev['link_id']} SUSPECTED blocked (confidence {ev['confidence']:.2f}); "
                               "no independent corroboration, human confirmation needed", ev)
                else:
                    self.alert("info", "inference", ev["link_id"], f"Road {ev['link_id']} cleared")
                if ev.get("coordinated_anomaly"):
                    self.alert("critical", "coordinated_anomaly", ev["link_id"],
                               f"Possible coordinated spoof on {ev['link_id']}: stopped trucks contradicted by "
                               "traffic moving through the same point", ev)
                self.audit.append("inference", "inference", {k: ev[k] for k in ("link_id", "status", "confidence")
                                                             if k in ev}, self.world.t)
            for inc in self.incidents:
                if inc["status"] == "scheduled" and inc["start_t"] <= self.world.t:
                    self._activate(inc)
                if inc["status"] == "active" and inc["end_t"] <= self.world.t:
                    inc["status"] = "expired"
                    self.alert("info", "incident.cleared", inc["target"], f"Incident cleared: {inc['label']}")
                    self.audit.append("incident", "runtime", {"id": inc["id"], "event": "expired", "target": inc["target"]}, self.world.t)
            if self.world.t >= self._res_next:
                self._res_next = self.world.t + config.RESILIENCE_EVERY_S
                self.resilience.compute(self)
            self.last_tick_ms = (time.perf_counter() - t0) * 1000

    async def run_forever(self) -> None:
        while True:
            start = time.perf_counter()
            if not self.paused:
                await asyncio.to_thread(self.tick, config.TICK_REAL_S * self.speed)
            await asyncio.sleep(max(0.0, config.TICK_REAL_S - (time.perf_counter() - start)))

    # ------------------------------------------------------------------ V2: incidents & disruption state
    def active_incidents(self) -> list[dict]:
        return [i for i in self.incidents if i["status"] == "active" and i["end_t"] > self.world.t]

    def closed_state(self) -> tuple[set[str], set[str], set[str], dict]:
        """(closed links incl. both directions, closed nodes, suspected links, per-link state for the route planner)."""
        now = self.world.t
        closed, suspected, nodes = set(), set(), set()
        for lid, st in self.twin.link_status.items():
            if st["status"] in ("blocked", "blocked_inferred", "closed"):
                closed.add(lid)
            elif st["status"] == "suspected":
                suspected.add(lid)
        for inc in self.active_incidents():
            closed.update(inc["links"])
            nodes.update(inc["nodes"])
        closed = self.planner.expand_closed(closed)
        suspected = self.planner.expand_closed(suspected) - closed
        # parallel roads/rails between the same two places as a closure share its exposure (same weather, same area)
        near = {frozenset((self.net.links[lid].frm, self.net.links[lid].to)) for lid in closed}
        state = {}
        for l in self.net.links.values():
            st = {"status": "closed" if l.id in closed else "suspected" if l.id in suspected else "open"}
            if self.twin.active_alert(l.id, now):
                st["alert"] = True
            if self.weather.available:
                sev, info = self.weather.link_sev(l.id)
                if sev >= 0.25:
                    st["wx"] = {"sev": sev, "level": weather_level(sev), "text": info.get("text", ""),
                                "risk": self.weather.risk_add(l.id), "tmult": self.weather.time_factor(l.id)}
            if st["status"] == "open" and frozenset((l.frm, l.to)) in near:
                st["near_incident"] = True
            state[l.id] = st
        return closed, nodes, suspected, state

    def block_points(self, closed: set[str], nodes: set[str]) -> dict[str, float]:
        """Where on each closed link the closure is (fraction measured from link.frm). Declared road incidents are
        at the declared point; facility closures sit at the facility end; inferred blockages at the median position
        of the stopped trucks the inference layer used."""
        from .ops import position_on_route
        bp: dict[str, float] = {}
        for inc in self.active_incidents():
            for lid in inc["links"]:
                l = self.net.links[lid]
                if inc["nodes"]:
                    bp[lid] = 1.0 if l.to in inc["nodes"] else 0.0
                else:
                    bp[lid] = inc.get("frac", 0.5)
        for lid, ev in self.inference.events.items():
            if lid not in closed or lid in bp:
                continue
            pts = [(self.twin.vehicles[v].lat, self.twin.vehicles[v].lon) for v in ev.get("vehicles", [])
                   if v in self.twin.vehicles and self.twin.vehicles[v].lat is not None]
            if not pts:
                continue
            lat = sorted(p[0] for p in pts)[len(pts) // 2]
            lon = sorted(p[1] for p in pts)[len(pts) // 2]
            l = self.net.links[lid]
            _, f, _ = position_on_route(self.net, [(lid, l.frm, l.to)], lat, lon)
            for twin_l in self.planner.expand_closed({lid}):
                tl = self.net.links[twin_l]
                bp.setdefault(twin_l, f if tl.frm == l.frm else 1.0 - f)
        return bp

    def _orders(self, loaded_only: bool = True) -> tuple[list[dict], set[str], set[str]]:
        closed, nodes, _, _ = self.closed_state()
        bp = self.block_points(closed, nodes)
        orders = self.ops.orders(self.world.t, lambda vid: (self.trust.entities[vid].cls if vid in self.trust.entities else "trusted"),
                                 closed, nodes, loaded_only, bp)
        return orders, closed, nodes

    def open_incident(self, kind: str, target: str, duration_h: float, note: str = "", start_in_h: float = 0.0) -> dict:
        """Declare a live incident, now or scheduled (e.g. a storm warning 6 h out). Road incidents become real
        blockages in the simulated world when they start (trucks stop and the inference layer must detect them);
        facility incidents stop dispatch to/from the node."""
        net, now = self.net, self.world.t
        links, nodes = set(), set()
        if kind in ("link_closure", "storm"):
            if target not in net.links:
                raise ValueError("target must be a link")
            links = self.planner.expand_closed(Disruption(kind, target, 0, duration_h).blocked_links(net))
            label = f"{'Storm' if kind == 'storm' else 'Road closure'} on {net.links[target].corridor_id}"
        elif kind in ("port_closure", "warehouse_failure", "supplier_failure"):
            want = {"port_closure": "Port", "warehouse_failure": "Warehouse", "supplier_failure": "Supplier"}[kind]
            if target not in net.nodes or net.nodes[target].type != want:
                raise ValueError(f"target must be a {want}")
            nodes = {target}
            links = {l.id for l in net.links.values() if target in (l.frm, l.to)}
            label = f"{kind.replace('_', ' ').capitalize()} at {target}"
        else:
            raise ValueError("unsupported live incident kind")
        start = now + max(0.0, start_in_h) * 3600
        with self.lock:
            self._inc_id += 1
            inc = {"id": f"inc-{self._inc_id:03d}", "kind": kind, "target": target, "label": label,
                   "links": sorted(links), "nodes": sorted(nodes), "start_t": start, "end_t": start + duration_h * 3600,
                   "duration_h": duration_h, "status": "scheduled", "frac": 0.5, "note": note, "attacks": [],
                   "data_mode": "SIMULATED", "source": "declared by operator"}
            self.incidents.append(inc)
            self.audit.append("incident", "operator", {k: inc[k] for k in ("id", "kind", "target", "label", "duration_h", "links", "nodes")}
                              | {"start_in_h": start_in_h}, now)
            if start_in_h > 0:
                self.alert("warning", "incident.scheduled", target, f"Warning: {label} expected in {start_in_h:g} h (~{duration_h:g} h, simulated)")
            else:
                self._activate(inc)
        return inc

    def _activate(self, inc: dict) -> None:
        net, now = self.net, self.world.t
        dur = max(60.0, inc["end_t"] - now)
        if inc["kind"] in ("link_closure", "storm"):
            for lid in sorted(l for l in inc["links"] if net.links[l].mode == "road"):
                inc["attacks"].append(self.world.inject("real_blockage", [lid], {"frac": inc["frac"]}, dur).id)
        for n in inc["nodes"]:
            self.world.closed_nodes[n] = inc["end_t"]
        inc["status"] = "active"
        self.alert("critical", "incident.opened", inc["target"], f"Incident: {inc['label']} (~{inc['duration_h']:g} h, simulated)")
        self._res_next = 0.0

    def scheduled_incidents(self) -> list[dict]:
        return [i for i in self.incidents if i["status"] == "scheduled"]

    def resolve_incident(self, iid: str) -> dict:
        with self.lock:
            inc = next((i for i in self.incidents if i["id"] == iid), None)
            if inc is None:
                raise KeyError(iid)
            if inc["status"] == "scheduled":
                inc["status"] = "cancelled"
                self.audit.append("incident", "operator", {"id": iid, "event": "cancelled"}, self.world.t)
            elif inc["status"] == "active":
                inc["status"], inc["end_t"] = "resolved", self.world.t
                for a in inc["attacks"]:
                    at = self.world.attacks.get(a)
                    if at:
                        at.end = min(at.end, self.world.t)
                        for lid in at.targets:
                            if lid in self.world.blocks:
                                self.world.blocks[lid]["until"] = self.world.t
                for n in inc["nodes"]:
                    self.world.closed_nodes.pop(n, None)
                self.alert("info", "incident.resolved", inc["target"], f"Incident resolved: {inc['label']}")
                self.audit.append("incident", "operator", {"id": iid, "event": "resolved"}, self.world.t)
                self._res_next = 0.0
            return inc

    def resolve_all(self) -> None:
        for i in list(self.active_incidents()) + self.scheduled_incidents():
            self.resolve_incident(i["id"])
        self.world.closed_nodes.clear()

    # ------------------------------------------------------------------ V2: self-healing reroutes
    def affected_trucks(self) -> list[dict]:
        """Trucks (twin belief) whose remaining route runs into a closed link or node."""
        with self.lock:
            orders, _, _ = self._orders(loaded_only=False)
        out = [dict(o, cause="closure") for o in orders if o["status"] == "AT_RISK"]
        ids = {o["vehicle"] for o in out}
        out += [dict(o, cause="weather") for o in orders if o["vehicle"] not in ids and o["weather_ahead"]
                and o["status"] in ("IN_TRANSIT", "DELAYED") and o["weather_delay_h"] >= 0.5 and o["leg"] < o["legs"] - 1]
        return out

    def weather_view(self) -> dict:
        """Hazards (real forecast) and the WEATHER -> ROAD RISK -> ETA -> INVENTORY -> NETWORK RISK -> RECOVERY chain."""
        wf = self.weather
        meta = wf.meta()
        if not wf.available:
            return {"meta": meta, "summary": None, "alerts": wf.alerts, "hazards": [], "chain": None, "cells": []}
        seen, hazards = set(), []
        for l in self.net.links.values():
            key = (l.corridor_id, l.mode)
            if key in seen:
                continue
            now_s, info = wf.link_sev(l.id)
            peak, at = wf.peak_hours(l.id, 48)
            top = max(now_s, peak)
            if top < 0.5:
                continue
            seen.add(key)
            hazards.append({"link": l.id, "corridor": l.corridor_id, "mode": l.mode, "from": l.frm, "to": l.to,
                            "sev_now": now_s, "level_now": weather_level(now_s), "peak_sev": peak, "peak_level": weather_level(peak),
                            "peak_in_h": at, "text": info.get("text", ""), "precip_mm_h": info.get("precip_mm_h"),
                            "gust_kmh": info.get("gust_kmh"), "time_factor": round(wf.time_factor(l.id, 0 if now_s >= peak else at), 2),
                            "risk_add": round(wf.risk_add(l.id, 0 if now_s >= peak else at), 2)})
        hazards.sort(key=lambda h: -max(h["sev_now"], h["peak_sev"]))
        with self.lock:
            orders, _, _ = self._orders()
        hit = sorted([o for o in orders if o["weather_delay_h"] >= 0.25], key=lambda o: -o["weather_delay_h"])
        res = self.resilience.last["components"].get("weather_exposure") if self.resilience.last else None
        chain = None
        if hazards:
            h = hazards[0]
            inv = (res or {}).get("facts", {}).get("inventory_risk", {})
            rec = None
            if hit:
                try:
                    r = self.recovery_options(hit[0]["vehicle"], None)
                    best = next((x for x in r.get("routes", []) if x["id"] == r.get("recommended")), None)
                    cur = r.get("current")
                    if best and cur:
                        rec = {"vehicle": hit[0]["vehicle"], "route": best["label"], "mode": best["mode_label"],
                               "time_h": round(best["time_h"], 1), "current_time_h": round(cur["time_h"], 1),
                               "cost": round(best["total_cost"]), "current_cost": round(cur["total_cost"]),
                               "better": best["time_h"] < cur["time_h"] - 0.25, "why": (r.get("why") or [""])[0]}
                except Exception:  # noqa: BLE001 - a missing option must not hide the rest of the chain
                    rec = None
            chain = {"hazard": h, "shipments": [{k: o[k] for k in ("vehicle", "id", "origin", "destination", "priority", "weather_delay_h", "delay_h")}
                                                for o in hit[:6]],
                     "shipments_total": len(hit), "delay_total_h": round(sum(o["weather_delay_h"] for o in hit), 1),
                     "inventory_risk": inv, "network": {"score": res["score"] if res else None,
                                                        "points_lost": round(res["weight"] * 100 * (1 - res["score"]), 1) if res else None,
                                                        "detail": res["detail"] if res else ""},
                     "recovery": rec}
        summ = wf.summary() or {}
        summ.update({"corridors_at_risk": len(hazards), "shipments_delayed": len(hit),
                     "delay_total_h": round(sum(o["weather_delay_h"] for o in hit), 1)})
        return {"meta": meta, "summary": summ, "alerts": wf.alerts, "hazards": hazards[:12], "chain": chain, "cells": wf.cells()}

    def recovery_options(self, vid: str, weights: dict | None, prev_weights: dict | None = None) -> dict:
        with self.lock:
            closed, nodes, _, state = self.closed_state()
            tv = self.twin.vehicles.get(vid)
            if tv is None or not tv.route or tv.lat is None:
                raise KeyError(vid)
            o = self.ops.order(tv, self.world.t, self.trust.entities[vid].cls if vid in self.trust.entities else "trusted",
                               closed, nodes, self.block_points(closed, nodes))
            if o is None:
                raise KeyError(vid)
            plan = self.world.reroute_plan(vid, o["turnaround_needed"])
        if o is None or plan is None:
            raise KeyError(vid)
        from .costing import Hop, route_metrics
        lid, rev = plan["leg"]
        l = self.net.links[lid]
        lead_rev = (not rev) if plan["turnaround"] else rev
        a, b = (l.to, l.frm) if lead_rev else (l.frm, l.to)
        lead = {"hop": Hop(lid, lead_rev, a, b, "road"), "frac": max(0.02, plan["lead_frac"])}
        units = max(1, o["units"] or config.TRUCK_CAPACITY)
        pr = o["priority"]
        if plan["pivot"] == plan["dest"]:
            return {"vehicle": vid, "order": o, "pivot": plan, "error": "truck is already on its last leg"}
        res = self.planner.plan(plan["pivot"], plan["dest"], units, weights, pr, state, closed, nodes, prev_weights,
                                road_only=True, lead=lead)
        cur_hops = [Hop(x, r, *( (self.net.links[x].to, self.net.links[x].frm) if r else (self.net.links[x].frm, self.net.links[x].to)), "road")
                    for x, r in plan["remaining"]]
        current = route_metrics(self.net, cur_hops, units, state, dict(lead, hop=Hop(lid, rev, *((l.to, l.frm) if rev else (l.frm, l.to)), "road"),
                                                                            frac=1.0 - (plan["lead_frac"] if plan["turnaround"] else 1.0 - plan["lead_frac"])))
        current["blocked"] = sorted({x for x, _ in plan["remaining"]} & closed | ({lid} & closed))
        res.update({"vehicle": vid, "order": o, "pivot": plan, "current": current})
        return res

    def approve_reroute(self, vid: str, hops: list[list], route_id: str, approver: str, note: str) -> dict:
        with self.lock:
            closed, nodes, _, _ = self.closed_state()
            bad = [h[0] for h in hops if h[0] in closed or self.net.links.get(h[0]) is None
                   or self.net.links[h[0]].frm in nodes or self.net.links[h[0]].to in nodes]
            if bad:
                raise ValueError(f"route uses closed links: {', '.join(bad)}")
            rec = self.world.reroute_vehicle(vid, [(str(h[0]), bool(h[1])) for h in hops])
            seq = self.audit.append("reroute_approved", approver, {"vehicle": vid, "route_id": route_id,
                                                                   "new_route": rec["new_route"], "old_route": rec["old_route"],
                                                                   "turnaround": rec["turnaround"], "note": note}, self.world.t)
            rec = dict(rec, audit_seq=seq, approver=approver, route_id=route_id)
            self.recoveries.append(rec)
            self.alert("info", "recovery.rerouted", vid, f"{vid} rerouted via {' → '.join(rec['new_route'][1:4])} (audit #{seq})")
            self._res_next = 0.0
            return rec

    def node_states(self, closed_nodes: set[str]) -> dict[str, str]:
        out = {}
        for n in self.net.nodes.values():
            if n.id in closed_nodes:
                out[n.id] = "critical"
                continue
            if n.type != "Warehouse":
                out[n.id] = "healthy"
                continue
            e = self.trust.entities.get(f"wh:{n.id}")
            if e is None or n.id not in self.twin.warehouse_t:
                out[n.id] = "unknown"
                continue
            worst = 9.0
            for s in config.SKUS:
                d = self.resilience.served.get((n.id, s), 0.0)
                b = self.twin.inventory.get((n.id, s))
                if d > 0 and b is not None:
                    worst = min(worst, b.verified / d)
            if e.cls == "quarantined" or worst < 0.25 * config.SAFETY_STOCK_DAYS:
                out[n.id] = "critical"
            elif e.cls == "estimated" or worst < config.SAFETY_STOCK_DAYS:
                out[n.id] = "warning"
            else:
                out[n.id] = "healthy"
        return out

    def ops_metrics(self, orders: list[dict], closed: set[str], nodes: set[str], node_state: dict) -> dict:
        now = self.world.t
        at_risk = [o for o in orders if o["status"] in ("AT_RISK", "STOPPED", "UNVERIFIED", "DELAYED")]
        vehicles = [v for v in self.twin.vehicles.values() if v.lat is not None]
        fresh = [v for v in vehicles if now - v.t <= 3 * config.GPS_INTERVAL_S]
        trusted_fresh = [v for v in fresh if (self.trust.entities.get(v.id) and self.trust.entities[v.id].cls == "trusted")]
        loaded_moving = [v for v in fresh if (v.load or 0) > 0 and v.speed_kmh >= config.INF_STOP_SPEED]
        wh = [k for k, v in node_state.items() if self.net.nodes[k].type == "Warehouse"]
        wh_ok = sum(1 for k in wh if node_state[k] == "healthy")
        open_links = [l for l in self.net.links.values() if l.id not in closed and l.frm not in nodes and l.to not in nodes]
        total_cap = sum(l.capacity_units_day for l in self.net.links.values())
        open_cap = sum(l.capacity_units_day for l in open_links)
        health = (wh_ok / len(wh) if wh else 1) / 3 + (len(open_links) / len(self.net.links)) / 3 +                  (len(trusted_fresh) / max(1, len(self.world.vehicles))) / 3
        inc = self.active_incidents()
        inferred = [lid for lid, st in self.twin.link_status.items() if st["status"] != "open"
                    and not any(lid in i["links"] for i in inc)]
        attacks = self.world.active_attacks()
        data_attacks = [a for a in attacks if a.kind != "real_blockage"]
        rec = self.resilience.last["components"]["recovery_time"]["facts"]["hours"] if self.resilience.last else 0.0
        below = self.resilience.last["components"]["inventory_buffer"]["facts"]["below_safety"] if self.resilience.last else []
        return {"network_health_pct": round(100 * health, 1),
                "active_disruptions": len(inc) + len(inferred) + len(data_attacks),
                "disruptions": {"incidents": len(inc), "inferred_links": len(inferred), "data_attacks": len(data_attacks)},
                "orders_total": len(orders), "orders_at_risk": len(at_risk),
                "critical_at_risk": sum(1 for o in at_risk if o["priority"] == "CRITICAL"),
                "inventory_at_risk_inr": round(sum(o["value_inr"] for o in at_risk)),
                "hub_skus_below_safety": len(below),
                "recovery_eta_h": round(rec, 1), "network_capacity_pct": round(100 * open_cap / total_cap, 1),
                "fleet_utilization_pct": round(100 * len(loaded_moving) / max(1, len(fresh)), 1),
                "trucks_reporting": len(fresh)}

    # ------------------------------------------------------------------ views
    def planning_inventory(self, raw: bool = False) -> dict:
        with self.lock:
            inv = self.twin.raw_inventory() if raw else self.twin.usable_inventory(self.trust.trust_of)
        served = warehouse_served_demand(self.net)
        for key, d in served.items():
            inv.setdefault(key, d * 2.0)     # warehouses not reported yet: assume 2 days of cover (flagged)
        return inv

    def kpis(self) -> dict:
        now = self.world.t
        anomalies = [s for (t, s) in self.trust.anomaly_times if now - t <= 300]
        ents = [e for e in self.trust.entities.values() if e.kind in ("vehicle", "warehouse_feed")]
        c = self.gateway.counts
        return {"events_per_min": round(self.gateway.events_per_min()),
                "valid_pct": round(100 * c["accepted"] / c["received"], 2) if c["received"] else 100.0,
                "invalid_pct": round(100 * c["dlq"] / c["received"], 2) if c["received"] else 0.0,
                "anomalies_5min": {"hard": anomalies.count("hard"), "soft": anomalies.count("soft")},
                "critical_alerts": sum(1 for a in self.alerts if a["severity"] == "critical" and now - a["t"] <= 1800),
                "quarantined_entities": sum(1 for e in ents if e.cls == "quarantined"),
                "estimated_entities": sum(1 for e in ents if e.cls == "estimated"),
                "dead_letter": c["dlq"], "duplicates_dropped": c["duplicate"],
                "freshness_pct": round(100 * self.modes.freshness, 1),
                "trusted_coverage_pct": round(100 * self.modes.coverage, 1),
                "mode": self.modes.mode, "processing_errors": self.processing_errors,
                "tick_ms": round(self.last_tick_ms, 1)}

    def snapshot(self) -> dict:
        with self.lock:
            now = self.world.t
            vehicles = []
            for v in self.twin.vehicles.values():
                if v.lat is None:
                    continue
                e = self.trust.entities.get(v.id)
                vehicles.append({"id": v.id, "fleet": v.fleet, "lat": round(v.lat, 5), "lon": round(v.lon, 5),
                                 "speed": round(v.speed_kmh), "heading": round(v.heading),
                                 "cls": e.cls if e else "trusted",
                                 "tau": round(e.tau, 3) if e else None,
                                 "unc_km": round(self.twin.position_uncertainty_km(v, now), 2),
                                 "age_s": round(now - v.t)})
            warehouses = {}
            for w in self.world.warehouses:
                e = self.trust.entities.get(f"wh:{w}")
                items = {s: self.twin.inventory.get((w, s)) for s in config.SKUS}
                warehouses[w] = {"cls": e.cls if e else "trusted", "tau": round(e.tau, 3) if e else None,
                                 "inv": {s: (round(b.verified) if b else None) for s, b in items.items()},
                                 "conf": {s: (b.conf_class if b else None) for s, b in items.items()},
                                 "age_s": round(now - self.twin.warehouse_t.get(w, -1e9)) if w in self.twin.warehouse_t else None}
            links = {k: v for k, v in self.twin.link_status.items() if v["status"] != "open"}
            orders, closed, cnodes = self._orders()
            for inc in self.active_incidents():
                for lid in inc["links"]:
                    links.setdefault(lid, {"status": "closed", "confidence": 1.0, "source": f"incident {inc['id']}"})
            nstate = self.node_states(cnodes)
            for v in vehicles:
                tv = self.twin.vehicles.get(v["id"])
                v["load"] = (tv.load or tv.cargo_units) if tv else 0
                v["sku"] = tv.sku if tv else ""
                v["pr"] = tv.priority if tv else 3
            return {"t": now, "sim_time": self.world.iso(), "speed": self.speed, "paused": self.paused,
                    "vehicles": vehicles, "warehouses": warehouses, "links": links, "kpis": self.kpis(),
                    "alerts": list(self.alerts)[:25], "active_attacks": [
                        {"id": a.id, "kind": a.kind, "targets": a.targets[:10], "ends_in_s": round(a.end - now)}
                        for a in self.world.active_attacks()],
                    "active_plan": self.active_plan,
                    # V2
                    "resilience": self.resilience.summary(), "ops": self.ops_metrics(orders, closed, cnodes, nstate),
                    "node_state": nstate, "incidents": [dict(i, remaining_h=round(max(0.0, i["end_t"] - now) / 3600, 2))
                                                        for i in self.active_incidents()],
                    "scheduled": [dict(i, starts_in_h=round(max(0.0, i["start_t"] - now) / 3600, 2)) for i in self.scheduled_incidents()],
                    "recoveries": self.recoveries[-10:],
                    "at_risk_orders": [{k: o[k] for k in ("id", "vehicle", "status", "priority", "sku", "destination", "blocked_ahead", "delay_h")}
                                       for o in orders if o["status"] in ("AT_RISK", "STOPPED", "UNVERIFIED", "DELAYED")][:12]}
