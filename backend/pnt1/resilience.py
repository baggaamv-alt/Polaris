"""Supply Chain Resilience Index (V2).

"How healthy and resilient is the whole network right now?" answered as one 0-100 score built from eight
components, each computed from the twin's live belief (trusted inventory, link status, trust, freshness,
declared incidents). Nothing here reads the hidden truth. Weights are in config.RESILIENCE_WEIGHTS.
"""
from __future__ import annotations

import math
from collections import deque

import networkx as nx

from . import config
from .graph import SOURCE_TYPES
from .network import Network, supply_per_day, warehouse_served_demand
from .ops import in_yard

LABELS = {"route_redundancy": "Route redundancy", "supplier_dependency": "Supplier dependency",
          "warehouse_capacity": "Warehouse capacity", "recovery_time": "Recovery time",
          "disruption_exposure": "Disruption exposure", "inventory_buffer": "Inventory buffer",
          "fleet_flexibility": "Fleet flexibility", "data_reliability": "Data reliability",
          "weather_exposure": "Weather exposure"}


def band(x: float) -> str:
    for lo, name in config.RESILIENCE_BANDS:
        if x >= lo:
            return name
    return "CRITICAL"


class Resilience:
    def __init__(self, net: Network):
        self.net = net
        self.sources = [n.id for n in net.nodes.values() if n.type in SOURCE_TYPES]
        self.customers = [n.id for n in net.of_type("CustomerCluster")]
        self.warehouses = [n.id for n in net.of_type("Warehouse")]
        self.served = warehouse_served_demand(net)
        self.supply = supply_per_day(net)
        self.total_cap = sum(l.capacity_units_day for l in net.links.values())
        self.serving: dict[str, list[str]] = {}
        for l in net.links.values():
            if net.nodes[l.to].type == "CustomerCluster":
                self.serving.setdefault(l.to, []).append(l.frm)
        self._cut_cache: dict[tuple, dict] = {}
        self.base_cut = self._cuts(frozenset(), frozenset(), frozenset())
        self.history: deque[dict] = deque(maxlen=720)
        self.changes: deque[dict] = deque(maxlen=20)
        self.last: dict | None = None
        self._anchor: dict | None = None

    # ------------------------------------------------------------------------------------------ graph pieces
    def _graph(self, closed: frozenset, closed_nodes: frozenset, suspected: frozenset) -> nx.DiGraph:
        g = nx.DiGraph()
        g.add_nodes_from(n for n in self.net.nodes if n not in closed_nodes)
        for l in self.net.links.values():
            if l.id in closed or l.frm in closed_nodes or l.to in closed_nodes:
                continue
            cap = l.capacity_units_day * (0.5 if l.id in suspected else 1.0)
            if g.has_edge(l.frm, l.to):
                g[l.frm][l.to]["capacity"] += cap
            else:
                g.add_edge(l.frm, l.to, capacity=cap)
        return g

    def _cuts(self, closed: frozenset, closed_nodes: frozenset, suspected: frozenset) -> dict:
        key = (closed, closed_nodes, suspected)
        if key in self._cut_cache:
            return self._cut_cache[key]
        g = self._graph(closed, closed_nodes, suspected)
        g.add_node("__SRC__")
        for s in self.sources:
            if s in g:
                g.add_edge("__SRC__", s, capacity=10**9)
        out = {}
        for c in self.customers:
            if c not in g:
                out[c] = {"cut": 0.0, "paths": 0}
                continue
            try:
                val = nx.maximum_flow_value(g, "__SRC__", c, capacity="capacity")
            except nx.NetworkXError:
                val = 0.0
            open_servers = [w for w in self.serving.get(c, []) if w in g and g.has_edge(w, c)
                            and any(nx.has_path(g, s, w) for s in self.sources if s in g)]
            out[c] = {"cut": float(val), "paths": len(open_servers)}
        if len(self._cut_cache) > 64:
            self._cut_cache.clear()
        self._cut_cache[key] = out
        return out

    # ------------------------------------------------------------------------------------------ compute
    def compute(self, rt) -> dict:
        now = rt.world.t
        closed_links, closed_nodes, suspected, _ = rt.closed_state()
        net, twin = self.net, rt.twin
        comp: dict[str, dict] = {}

        # 1. route redundancy: capacity through each customer's min cut vs baseline, and 2+ open serving hubs
        cuts = self._cuts(frozenset(closed_links), frozenset(closed_nodes), frozenset(suspected))
        ratios = [min(1.0, cuts[c]["cut"] / self.base_cut[c]["cut"]) if self.base_cut[c]["cut"] > 0 else 1.0
                  for c in self.customers]
        multi = sum(1 for c in self.customers if cuts[c]["paths"] >= 2)
        single = [c for c in self.customers if cuts[c]["paths"] <= 1]
        score = 0.5 * (sum(ratios) / len(ratios)) + 0.5 * (multi / len(self.customers))
        n_closed = len({net.links[l].corridor_id for l in closed_links})
        comp["route_redundancy"] = {"score": score, "detail": (f"{n_closed} corridor{'s' if n_closed != 1 else ''} closed · " if n_closed else "")
                                    + f"{len(single)} of {len(self.customers)} customer clusters depend on a single open hub",
                                    "facts": {"single_hub_customers": single, "closed_corridors": n_closed}}

        # 2. supplier dependency: effective number of available sources per SKU (1 / HHI of capacity)
        g_open = self._graph(frozenset(closed_links), frozenset(closed_nodes), frozenset())
        reach_wh = lambda s: s in g_open and any(w in g_open and nx.has_path(g_open, s, w) for w in self.warehouses)  # noqa: E731
        per_sku, weak = {}, []
        for sku in config.SKUS:
            caps = {n: c for (n, s), c in self.supply.items() if s == sku and n not in closed_nodes and reach_wh(n)}
            tot = sum(caps.values())
            hhi = sum((c / tot) ** 2 for c in caps.values()) if tot else 1.0
            n_eff = (1.0 / hhi) if tot else 0.0
            per_sku[sku] = {"sources": sorted(caps), "effective": round(n_eff, 2)}
            if n_eff < 1.5:
                weak.append(f"{sku} ({config.SKU_CLASS[sku]}) {'has no available source' if not caps else 'single-sourced from ' + ', '.join(sorted(caps))}")
        score = sum(min(1.0, v["effective"] / 3.0) for v in per_sku.values()) / len(per_sku)
        comp["supplier_dependency"] = {"score": score, "detail": "; ".join(weak) or "every SKU has 2+ available sources",
                                       "facts": {"per_sku": per_sku}}

        # 3. warehouse capacity: hubs available (not closed, still reachable) and not saturated
        wsum = wtot = 0.0
        off, peak = [], 0.0
        for w in self.warehouses:
            cap = net.nodes[w].capacity
            wtot += cap
            inbound_open = any(l.to == w and l.id not in closed_links for l in net.links.values())
            if w in closed_nodes or not inbound_open:
                off.append(w)
                continue
            stock = sum((twin.inventory.get((w, s)).verified if twin.inventory.get((w, s)) else 0.0) for s in config.SKUS)
            util = stock / cap
            peak = max(peak, util)
            wsum += cap * (1.0 if util <= 0.85 else max(0.0, (1 - util) / 0.15))
        comp["warehouse_capacity"] = {"score": wsum / wtot if wtot else 1.0,
                                      "detail": (f"{', '.join(off)} offline · " if off else f"all {len(self.warehouses)} hubs available · ")
                                      + f"peak utilisation {peak:.0%}", "facts": {"offline": off, "peak_util": peak}}

        # 4. recovery time: longest expected time to clear an open incident (declared estimate or alert expiry)
        pending = []
        for inc in rt.active_incidents():
            pending.append((max(0.0, inc["end_t"] - now) / 3600, f"{inc['label']} (declared estimate)"))
        for lid, st in twin.link_status.items():
            if st["status"] != "open" and not any(lid in i["links"] for i in rt.active_incidents()):
                a = twin.active_alert(lid, now)
                hrs = max(0.0, (a["until"] - now) / 3600) if a else 3.0
                pending.append((hrs, f"{lid} {st['status'].replace('_', ' ')} ({'alert expiry, MOCK' if a else 'default 3 h estimate'})"))
        hours = max((h for h, _ in pending), default=0.0)
        plan_ok = rt.active_plan is not None and any(rt.active_plan.get("approved_at", -1) >= i["start_t"] for i in rt.active_incidents())
        reroutes = sum(1 for r in rt.recoveries if r["t"] >= now - 6 * 3600)
        eff = hours * (0.6 if plan_ok else 1.0) * (0.85 if reroutes else 1.0)
        worst = max(pending, key=lambda x: x[0])[1] if pending else None
        comp["recovery_time"] = {"score": math.exp(-eff / 24.0),
                                 "detail": (f"~{hours:.1f} h to clear {worst}" + (" · recovery plan approved" if plan_ok else "")
                                            + (f" · {reroutes} truck{'s' if reroutes != 1 else ''} rerouted" if reroutes else ""))
                                 if pending else "no open incidents",
                                 "facts": {"hours": hours, "plan_approved": plan_ok, "reroutes": reroutes}}

        # 5. disruption exposure: loaded shipments whose route touches a closed link/node + closed link capacity
        orders, _, _ = rt._orders()
        loaded = len(orders)
        hit = sum(1 for o in orders if o["status"] == "AT_RISK")
        cap_closed = sum(l.capacity_units_day for l in net.links.values()
                         if l.id in closed_links or l.frm in closed_nodes or l.to in closed_nodes)
        share, cshare = (hit / loaded if loaded else 0.0), cap_closed / self.total_cap
        score = 1.0 - 0.6 * min(1.0, 1.5 * share) - 0.4 * min(1.0, 4 * cshare)
        comp["disruption_exposure"] = {"score": max(0.0, score),
                                       "detail": f"{hit} of {loaded} loaded shipments routed through a disruption · {cshare:.0%} of link capacity closed",
                                       "facts": {"shipments_hit": hit, "loaded": loaded, "capacity_closed": cshare}}

        # 6. inventory buffer: trusted days of cover vs 2x safety stock
        inv = twin.usable_inventory(rt.trust.trust_of)
        cov, low = [], []
        for (w, s), d in self.served.items():
            if d <= 0:
                continue
            q = 0.0 if w in closed_nodes else inv.get((w, s), d * 2.0)
            c = q / d
            cov.append(min(1.0, c / (2 * config.SAFETY_STOCK_DAYS)))
            if c < config.SAFETY_STOCK_DAYS:
                low.append(f"{w} {s}")
        comp["inventory_buffer"] = {"score": sum(cov) / len(cov) if cov else 1.0,
                                    "detail": f"{len(low)} of {len(cov)} hub-SKUs below {config.SAFETY_STOCK_DAYS:.0f} days of safety stock",
                                    "facts": {"below_safety": low}}

        # 7. fleet flexibility: trucks fresh, trusted, fuelled, not stuck, not routed into a closure
        exp = len(rt.world.vehicles)
        avail = 0
        reasons = {"silent": 0, "quarantined": 0, "stuck": 0, "low fuel": 0, "blocked route": 0}
        for v in twin.vehicles.values():
            e = rt.trust.entities.get(v.id)
            if v.lat is None or now - v.t > 3 * config.GPS_INTERVAL_S:
                reasons["silent"] += 1
            elif e and e.cls == "quarantined":
                reasons["quarantined"] += 1
            elif v.stopped_since is not None and now - v.stopped_since > 900 and not in_yard(net, v.lat, v.lon):
                reasons["stuck"] += 1
            elif v.fuel is not None and v.fuel < 15:
                reasons["low fuel"] += 1
            elif v.route and any(l in closed_links for l in v.route):
                reasons["blocked route"] += 1
            else:
                avail += 1
        reasons["silent"] += max(0, exp - len(twin.vehicles))
        worst_r = [f"{n} {k}" for k, n in sorted(reasons.items(), key=lambda x: -x[1]) if n][:3]
        comp["fleet_flexibility"] = {"score": avail / exp if exp else 1.0,
                                     "detail": f"{avail} of {exp} trucks free to take work" + (f" · {', '.join(worst_r)}" if worst_r else ""),
                                     "facts": reasons}

        # 8. data reliability: sources reporting on time and entities trusted
        f, c = rt.modes.freshness, rt.modes.coverage
        comp["data_reliability"] = {"score": 0.5 * f + 0.5 * c,
                                    "detail": f"{f:.0%} of sources on time · {c:.0%} of entities trusted · mode {rt.modes.mode}",
                                    "facts": {"freshness": f, "coverage": c, "mode": rt.modes.mode}}

        # 9. weather exposure (real forecast): loaded shipments with severe weather ahead, link capacity under severe weather,
        #    hubs whose inbound delay would eat their safety cover. Excluded (weights renormalised) when weather is unavailable.
        wf = rt.weather
        if wf.available:
            sev_links = [l for l in net.links.values() if wf.link_sev(l.id)[0] >= 0.5]
            cap_share = sum(l.capacity_units_day for l in sev_links) / self.total_cap
            exposed = [o for o in orders if o.get("weather_ahead")]
            eshare = len(exposed) / loaded if loaded else 0.0
            risky = {}
            for o in orders:
                if o.get("weather_delay_h", 0) >= 0.5 and o["dest_type"] == "Warehouse":
                    d = self.served.get((o["destination"], o["sku"]), 0.0)
                    q = inv.get((o["destination"], o["sku"]), d * 2.0)
                    cover_h = (q / d * 24) if d > 0 else 1e9
                    if cover_h - o["remaining_h"] - o["weather_delay_h"] < config.SAFETY_STOCK_DAYS * 24:
                        risky[f"{o['destination']} {o['sku']}"] = round(o["weather_delay_h"], 1)
            score = 1.0 - 0.45 * min(1.0, 2 * eshare) - 0.35 * min(1.0, 4 * cap_share) - 0.2 * min(1.0, len(risky) / 4)
            comp["weather_exposure"] = {"score": max(0.0, score), "detail": (
                f"{wf.status()} · {len(exposed)} of {loaded} loaded shipments have severe weather ahead · {cap_share:.0%} of link capacity under severe weather"
                + (f" · inbound delay threatens {', '.join(list(risky)[:3])}" if risky else "")),
                "facts": {"shipments_exposed": len(exposed), "capacity_severe": cap_share, "inventory_risk": risky,
                          "status": wf.status()}}
        W = dict(config.RESILIENCE_WEIGHTS)
        if "weather_exposure" not in comp:
            W.pop("weather_exposure")
            tot = sum(W.values())
            W = {k: w / tot for k, w in W.items()}
        for k, v in comp.items():
            v["score"] = round(max(0.0, min(1.0, v["score"])), 4)
            v["weight"] = W[k]
            v["points"] = round(100 * W[k] * v["score"], 2)
            v["label"] = LABELS[k]
        index = round(sum(v["points"] for v in comp.values()), 1)
        res = {"t": now, "index": index, "band": band(index), "components": comp}
        self._record(res)
        return res

    def _record(self, res: dict) -> None:
        pts = {k: v["points"] for k, v in res["components"].items()}
        self.history.append({"t": res["t"], "index": res["index"], "points": pts})
        if self._anchor is None:
            self._anchor = {"t": res["t"], "index": res["index"], "points": pts}
        elif abs(res["index"] - self._anchor["index"]) >= 1.0:
            drivers = []
            for k, p in pts.items():
                d = p - self._anchor["points"].get(k, p)
                if abs(d) >= 0.05:
                    drivers.append({"component": k, "label": LABELS[k], "delta": round(d, 1),
                                    "text": f"{LABELS[k]} {'improved' if d > 0 else 'decreased'} ({d:+.1f} pts): "
                                            f"{res['components'][k]['detail']}"})
            drivers.sort(key=lambda x: abs(x["delta"]), reverse=True)
            drivers = drivers[:5]
            self.changes.appendleft({"t": res["t"], "from": self._anchor["index"], "to": res["index"],
                                     "from_band": band(self._anchor["index"]), "to_band": res["band"], "drivers": drivers})
            self._anchor = {"t": res["t"], "index": res["index"], "points": pts}
        self.last = res

    def summary(self) -> dict | None:
        if not self.last:
            return None
        return {"index": self.last["index"], "band": self.last["band"], "t": self.last["t"],
                "components": {k: {"score": v["score"], "points": v["points"], "weight": v["weight"],
                                   "label": v["label"], "detail": v["detail"]} for k, v in self.last["components"].items()},
                "last_change": self.changes[0] if self.changes else None}
