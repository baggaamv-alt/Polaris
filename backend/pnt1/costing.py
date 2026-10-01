"""Multimodal cost engine + alternative-route planner (V2).

Cost engine: a bottom-up, per-shipment estimate for truck, rail and ship legs:
    distance -> fuel/energy use -> fuel/energy cost -> tolls -> operating -> maintenance -> handling -> total
Every rate comes from config.COST_MODEL and is a SIMULATED planning assumption (not a live market price).
Carbon uses the network's per-unit CO2 factors, the same numbers the LP optimizer uses. The LP's per-unit
tariff (link.cost_per_unit x units) is reported alongside for reference.

Route planner: candidate paths are generated independently of the user's priorities (k shortest by time and by
cost on the road network, plus the best path forced through every open rail or sea link), then a fixed display
set is chosen (best per mode mix, fastest, cheapest, greenest). User weights over money / time / fuel / distance
/ carbon, the shipment priority and live link risk only change the *scoring*, so "why did the winner change?"
has a precise answer: the weighted-score contribution of each metric.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import networkx as nx

from . import config
from .network import Network

METRICS = ("money", "time", "fuel", "distance", "carbon")
METRIC_LABEL = {"money": "cost", "time": "time", "fuel": "fuel/energy cost", "distance": "distance", "carbon": "CO₂"}
METRIC_FIELD = {"money": "total_cost", "time": "time_h", "fuel": "energy_cost", "distance": "distance_km",
                "carbon": "co2_kg"}
RISK_WEIGHT = 0.3
CLOSED = ("blocked", "blocked_inferred", "closed")


@dataclass(frozen=True)
class Hop:
    lid: str
    rev: bool
    frm: str
    to: str
    mode: str


def normalise_weights(w: dict | None) -> dict:
    w = {m: max(0.0, float((w or {}).get(m, 0.0) or 0.0)) for m in METRICS}
    s = sum(w.values())
    if s <= 0:
        return {m: 1.0 / len(METRICS) for m in METRICS}
    return {m: v / s for m, v in w.items()}


def mode_label(modes: set[str]) -> str:
    names = [("sea", "Ship"), ("rail", "Rail"), ("road", "Truck")]
    parts = [n for m, n in names if m in modes]
    return "Truck only" if parts == ["Truck"] else " + ".join(parts)


# ----------------------------------------------------------------------------------------------- cost engine
def leg_cost(net: Network, hop: Hop, units: float, frac: float = 1.0) -> dict:
    """Bottom-up cost of one hop for `units` pallets. frac < 1 costs only part of the link (lead-in legs)."""
    l = net.links[hop.lid]
    km = l.dist_km * frac
    tonnes = units * config.PALLET_TONNES
    cm = config.COST_MODEL[l.mode]
    out = {"lid": l.id, "mode": l.mode, "from": hop.frm, "to": hop.to, "distance_km": km,
           "time_h": l.base_time_h * frac, "co2_kg": l.co2_kg_per_unit * units * frac,
           "lp_tariff": l.cost_per_unit * units * frac, "capacity": l.capacity_units_day,
           "tolls": 0.0, "handling": 0.0}
    if l.mode == "road":
        trucks = max(1, math.ceil(units / cm["truck_units"]))
        litres = km / cm["km_per_l"] * trucks
        out.update(trucks=trucks, energy_qty=litres, energy_unit="L diesel",
                   energy_cost=litres * cm["fuel_inr_per_l"], tolls=km * cm["toll_inr_per_km"] * trucks,
                   operating=(km * cm["operating_inr_per_km"] + out["time_h"] * cm["crew_inr_per_h"]) * trucks,
                   maintenance=km * cm["maintenance_inr_per_km"] * trucks)
    elif l.mode == "rail":
        kwh = km * tonnes * cm["kwh_per_tkm"]
        out.update(energy_qty=kwh, energy_unit="kWh", energy_cost=kwh * cm["inr_per_kwh"],
                   operating=km * tonnes * cm["operating_inr_per_tkm"],
                   maintenance=km * tonnes * cm["maintenance_inr_per_tkm"])
    else:
        litres = km * tonnes * cm["fuel_l_per_tkm"]
        out.update(energy_qty=litres, energy_unit="L marine fuel", energy_cost=litres * cm["fuel_inr_per_l"],
                   operating=km * tonnes * cm["operating_inr_per_tkm"],
                   maintenance=km * tonnes * cm["maintenance_inr_per_tkm"])
    out["total_cost"] = out["energy_cost"] + out["tolls"] + out["operating"] + out["maintenance"]
    return out


def fuel_cost_per_unit(net: Network, lid: str) -> float:
    """Fuel/energy INR per pallet on a link (used by the LP when the fuel weight is set)."""
    l = net.links[lid]
    c = leg_cost(net, Hop(lid, False, l.frm, l.to, l.mode), config.TRUCK_CAPACITY)
    return c["energy_cost"] / config.TRUCK_CAPACITY


def link_risk(net: Network, lid: str, link_state: dict) -> tuple[float, str | None]:
    """Risk that this link delays the shipment (0..1) and the reason, from live link state."""
    l = net.links[lid]
    base = min(0.2, config.MODE_BASE_RISK[l.mode] * l.dist_km / 500.0)
    st = link_state.get(lid) or {}
    wx = st.get("wx")
    if wx and wx["risk"] > 0 and st.get("status") != "suspected" and not st.get("alert"):
        return max(base, wx["risk"]), f"{wx['level'].lower()} weather ({wx['text'] or 'rain / wind'}; real forecast)"
    if st.get("status") == "suspected":
        return max(base, 0.5), "suspected blockage (inferred)"
    if st.get("alert"):
        return max(base, 0.4), "active alert (MOCK feed)"
    if st.get("near_incident"):
        return max(base, 0.25), "parallel to a closed link (same corridor area)"
    return base, None


def route_metrics(net: Network, hops: list[Hop], units: float, link_state: dict | None = None,
                  lead: dict | None = None) -> dict:
    link_state = link_state or {}
    legs = [leg_cost(net, h, units) for h in hops]
    if lead:
        legs.insert(0, dict(leg_cost(net, lead["hop"], units, lead["frac"]), lead=True))
    tonnes = units * config.PALLET_TONNES
    handling, handling_h, transfers = 0.0, 0.0, []
    def transfer(at: str, m1: str, m2: str, note: str) -> None:
        nonlocal handling, handling_h
        per_t, h = config.COST_MODEL["transfer"][(m1, m2)]
        handling += per_t * tonnes
        handling_h += h
        transfers.append({"at": at, "from_mode": m1, "to_mode": m2, "inr": per_t * tonnes, "hours": h, "note": note})
    if legs and legs[0]["mode"] != "road":        # loading at the origin terminal (first mile by truck)
        transfer(legs[0]["from"], "road", legs[0]["mode"], "origin terminal loading")
    for a, b in zip(legs, legs[1:]):
        if a["mode"] != b["mode"]:
            transfer(a["to"], a["mode"], b["mode"], "mode change")
    if legs and legs[-1]["mode"] != "road":       # unloading at the destination terminal (last mile by truck)
        transfer(legs[-1]["to"], legs[-1]["mode"], "road", "destination terminal unloading")
    s = lambda k: sum(x[k] for x in legs)  # noqa: E731
    risk_keep, exposure_km, reasons = 1.0, 0.0, []
    for h in hops:
        r, why = link_risk(net, h.lid, link_state)
        risk_keep *= 1.0 - r
        if why:
            exposure_km += net.links[h.lid].dist_km
            reasons.append(f"{h.lid}: {why}")
    wx_delay = 0.0
    for h, leg in zip(hops, legs[1 if lead else 0:]):
        w = link_state.get(h.lid, {}).get("wx")
        if w and w["tmult"] > 1:
            wx_delay += leg["time_h"] * (w["tmult"] - 1)
    if wx_delay:
        reasons.append(f"weather adds ~{wx_delay:.1f} h (real forecast)")
    dist = s("distance_km")
    energy_by_unit: dict[str, float] = {}
    for x in legs:
        energy_by_unit[x["energy_unit"]] = energy_by_unit.get(x["energy_unit"], 0.0) + x["energy_qty"]
    total = s("total_cost") + handling
    coords = []
    for h in hops:
        seg = net.links[h.lid].seg
        a, b = ([seg[1], seg[0]], [seg[3], seg[2]])
        a, b = (b, a) if h.rev else (a, b)
        if not coords:
            coords.append(a)
        coords.append(b)
    modes = {h.mode for h in hops} | ({lead["hop"].mode} if lead else set())
    return {"distance_km": dist, "time_h": s("time_h") + handling_h + wx_delay, "weather_delay_h": wx_delay, "energy_cost": s("energy_cost"),
            "energy": [{"unit": k, "qty": v} for k, v in energy_by_unit.items()],
            "tolls": s("tolls"), "operating": s("operating"), "maintenance": s("maintenance"),
            "handling": handling, "total_cost": total, "co2_kg": s("co2_kg"), "lp_tariff": s("lp_tariff"),
            "capacity_units_day": min(x["capacity"] for x in legs) if legs else 0,
            "risk": 1.0 - risk_keep, "exposure": exposure_km / dist if dist else 0.0, "risk_reasons": reasons,
            "legs": legs, "transfers": transfers, "modes": sorted(modes), "mode_label": mode_label(modes),
            "coords": coords, "cost_per_unit": total / units if units else 0.0,
            "nodes": [hops[0].frm] + [h.to for h in hops] if hops else []}


# ----------------------------------------------------------------------------------------------- planner
def physical_key(net: Network, lid: str) -> tuple:
    l = net.links[lid]
    return (l.corridor_id, l.mode, frozenset({l.frm, l.to}))


class RoutePlanner:
    def __init__(self, net: Network):
        self.net = net
        self._phys: dict[tuple, list[str]] = {}
        for l in net.links.values():
            self._phys.setdefault(physical_key(net, l.id), []).append(l.id)

    def expand_closed(self, closed_links: set[str]) -> set[str]:
        """A blocked road is blocked in both directions: close every link sharing its physical geometry."""
        out = set()
        for lid in closed_links:
            if lid in self.net.links:
                out.update(self._phys[physical_key(self.net, lid)])
        return out

    def _graph(self, closed: set[str], closed_nodes: set[str], road_only: bool, units: float) -> nx.DiGraph:
        """Expanded graph (facility -> link-hop -> facility) with ONE edge per physical road and direction:
        a road's reverse traversal is added only when no twin link already runs that way, so k-shortest
        paths are physically different routes rather than the same road under two link ids."""
        g = nx.DiGraph()
        seen: set[tuple] = set()

        def add(l, u: str, v: str, rev: bool) -> None:
            key = (l.corridor_id, l.mode, u, v)
            if key in seen:
                return
            seen.add(key)
            hn = f"{l.id}>{int(rev)}"
            hop = Hop(l.id, rev, u, v, l.mode)
            g.add_edge(u, hn, time=l.base_time_h, cost=leg_cost(self.net, hop, units)["total_cost"], hop=hop)
            g.add_edge(hn, v, time=0.0, cost=0.0)
        usable = [l for l in self.net.links.values() if l.id not in closed and l.frm not in closed_nodes
                  and l.to not in closed_nodes and (l.mode == "road" or not road_only)]
        for l in usable:
            add(l, l.frm, l.to, False)
        for l in usable:
            if l.mode == "road":
                add(l, l.to, l.frm, True)
        return g

    @staticmethod
    def _hops(g: nx.DiGraph, path: list[str]) -> list[Hop]:
        return [g[u][v]["hop"] for u, v in zip(path, path[1:]) if "hop" in g[u][v]]

    def candidates(self, origin: str, dest: str, closed: set[str], closed_nodes: set[str], units: float,
                   road_only: bool = False, k: int = 8) -> list[list[Hop]]:
        net = self.net
        # suppliers and customer clusters are endpoints, not transit points
        no_transit = {n.id for n in net.nodes.values() if n.type in ("Supplier", "CustomerCluster")} - {origin, dest}
        g = self._graph(closed, closed_nodes | no_transit, road_only, units)
        if origin not in g or dest not in g:
            return []
        found: dict[tuple, list[Hop]] = {}

        def add(hops: list[Hop]) -> None:
            nodes = [hops[0].frm] + [h.to for h in hops] if hops else []
            if hops and len(nodes) == len(set(nodes)):
                # one entry per physical path: a road driven "in reverse" is the same road as its twin link
                key = tuple((net.links[h.lid].corridor_id, h.mode, h.frm, h.to) for h in hops)
                cur = found.get(key)
                if cur is None or sum(x.rev for x in hops) < sum(x.rev for x in cur):
                    found[key] = hops

        for w in ("time", "cost"):
            try:
                for i, p in enumerate(nx.shortest_simple_paths(g, origin, dest, weight=w)):
                    add(self._hops(g, p))
                    if i + 1 >= k:
                        break
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass
        if not road_only:
            for l in self.net.links.values():
                if l.mode == "road" or l.id in closed or l.frm in closed_nodes or l.to in closed_nodes:
                    continue
                try:
                    p1 = nx.shortest_path(g, origin, l.frm, weight="cost") if l.frm != origin else [origin]
                    p2 = nx.shortest_path(g, l.to, dest, weight="cost") if l.to != dest else [dest]
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue
                add(self._hops(g, p1) + [Hop(l.id, False, l.frm, l.to, l.mode)] + self._hops(g, p2))
        return list(found.values())

    # ---------------------------------------------------------------------------------------------
    def plan(self, origin: str, dest: str, units: float = config.TRUCK_CAPACITY, weights: dict | None = None,
             priority: str = "NORMAL", link_state: dict | None = None, closed_links: set[str] | None = None,
             closed_nodes: set[str] | None = None, prev_weights: dict | None = None, road_only: bool = False,
             lead: dict | None = None, max_routes: int = 5) -> dict:
        net = self.net
        if origin not in net.nodes or dest not in net.nodes:
            return {"error": "unknown origin or destination"}
        if origin == dest:
            return {"error": "origin and destination are the same"}
        priority = priority if priority in config.PRIORITY_CODE else "NORMAL"
        closed = self.expand_closed(closed_links or set())
        cn = set(closed_nodes or set()) - {origin, dest}
        cands = self.candidates(origin, dest, closed, cn, units, road_only)
        if not cands:
            return {"error": "no open route between these facilities", "origin": origin, "destination": dest,
                    "closed_links": sorted(closed), "routes": []}
        mets = [route_metrics(net, h, units, link_state, lead) for h in cands]
        for m, h in zip(mets, cands):
            m["hops"] = [[x.lid, x.rev] for x in h]
            m["id"] = "r-" + hashlib.sha1("|".join(f"{x.lid}{int(x.rev)}" for x in h).encode()).hexdigest()[:8]
        pool = [m for m in mets if m["time_h"] <= 5 * min(x["time_h"] for x in mets)]
        # weight-independent display set: best balanced per mode mix + fastest + cheapest + greenest
        bal = self._scores(pool, normalise_weights(None), priority)
        chosen: list[dict] = []

        def take(m: dict) -> None:
            if m not in chosen and len(chosen) < max_routes:
                chosen.append(m)
        for key in ("time_h", "total_cost", "co2_kg"):
            take(min(pool, key=lambda m: m[key]))
        by_mix: dict[str, dict] = {}
        for m in sorted(pool, key=lambda m: bal[m["id"]]):
            by_mix.setdefault(m["mode_label"], m)
        for m in by_mix.values():
            take(m)
        links_of = {m["id"]: {h[0] for h in m["hops"]} for m in pool}

        def overlap(m: dict) -> float:            # max Jaccard similarity to anything already chosen
            a = links_of[m["id"]]
            return max((len(a & links_of[c["id"]]) / len(a | links_of[c["id"]]) for c in chosen), default=0.0)
        rest = sorted((m for m in pool if m not in chosen), key=lambda m: bal[m["id"]])
        while rest and len(chosen) < max_routes:
            m = min(rest, key=lambda m: bal[m["id"]] * (1.0 + 1.5 * overlap(m)))
            take(m)
            rest.remove(m)
        chosen.sort(key=lambda m: (m["time_h"], m["total_cost"]))
        for i, m in enumerate(chosen):
            m["label"] = chr(ord("A") + i)
        w = normalise_weights(weights)
        res = self._rank(chosen, w, priority)
        out = {"origin": origin, "destination": dest, "units": units, "priority": priority, "weights": w,
               "routes": chosen, "recommended": res["best"], "sla_hours": res["deadline"],
               "closed_links": sorted(closed), "closed_nodes": sorted(cn), "road_only": road_only,
               "why": self._why(chosen, res, w), "assumptions": assumptions(),
               "data_mode": "SIMULATED"}
        if prev_weights is not None:
            pw = normalise_weights(prev_weights)
            prev = self._rank(chosen, pw, priority)
            out["previous"] = {"weights": pw, "recommended": prev["best"]}
            out["change"] = self._change(chosen, prev, res, pw, w)
        return out

    def _norms(self, routes: list[dict]) -> dict[str, dict[str, float]]:
        mins = {m: max(1e-9, min(r[METRIC_FIELD[m]] for r in routes)) for m in METRICS}
        return {r["id"]: {m: r[METRIC_FIELD[m]] / mins[m] for m in METRICS} for r in routes}

    def _scores(self, routes: list[dict], w: dict, priority: str) -> dict[str, float]:
        n = self._norms(routes)
        rm = config.PRIORITY_RISK_MULT[priority]
        return {r["id"]: sum(w[m] * n[r["id"]][m] for m in METRICS) + RISK_WEIGHT * rm * r["risk"] for r in routes}

    def _rank(self, routes: list[dict], w: dict, priority: str) -> dict:
        sc = self._scores(routes, w, priority)
        n = self._norms(routes)
        f = config.PRIORITY_DEADLINE_FACTOR[priority]
        deadline = f * min(r["time_h"] for r in routes) if f else None
        rm = config.PRIORITY_RISK_MULT[priority]
        for r in routes:
            r["score"] = round(sc[r["id"]], 4)
            r["sla_ok"] = deadline is None or r["time_h"] <= deadline + 1e-9
            r["contrib"] = {m: round(w[m] * n[r["id"]][m], 4) for m in METRICS}
            r["contrib"]["risk"] = round(RISK_WEIGHT * rm * r["risk"], 4)
        ok = [r for r in routes if r["sla_ok"]] or routes
        best = min(ok, key=lambda r: sc[r["id"]])
        return {"best": best["id"], "scores": sc, "norms": n, "deadline": deadline}

    @staticmethod
    def _fmt(m: str, v: float) -> str:
        if m in ("money", "fuel"):
            return f"₹{v:,.0f}"
        if m == "time":
            return f"{v:.1f} h"
        if m == "distance":
            return f"{v:,.0f} km"
        return f"{v:,.0f} kg"

    def _why(self, routes: list[dict], res: dict, w: dict) -> list[str]:
        by = {r["id"]: r for r in routes}
        best = by[res["best"]]
        others = sorted((r for r in routes if r["id"] != best["id"]), key=lambda r: res["scores"][r["id"]])
        lines = []
        if res["deadline"] is not None:
            late = [r["label"] for r in routes if not r["sla_ok"]]
            lines.append(f"Priority deadline {res['deadline']:.1f} h" + (f" rules out route {', '.join(late)}" if late else ""))
        if others:
            ru = others[0]
            adv = []
            for m in sorted(METRICS, key=lambda m: -w[m]):
                a, b = best[METRIC_FIELD[m]], ru[METRIC_FIELD[m]]
                if b > 0 and a < b * 0.995:
                    adv.append(f"{(1 - a / b) * 100:.0f}% lower {METRIC_LABEL[m]}")
            dis = []
            for m in sorted(METRICS, key=lambda m: -w[m]):
                a, b = best[METRIC_FIELD[m]], ru[METRIC_FIELD[m]]
                if b > 0 and a > b * 1.005:
                    dis.append(f"{self._fmt(m, a - b)} more {METRIC_LABEL[m]}" if m != "time" else f"{a - b:.1f} h slower")
            top = max(METRICS, key=lambda m: w[m])
            lines.append(f"Route {best['label']} ({best['mode_label']}) beats runner-up {ru['label']} on your weighting"
                         f" (heaviest: {METRIC_LABEL[top]} {w[top]:.0%})"
                         + (f": {', '.join(adv[:3])}" if adv else "")
                         + (f"; trade-off: {', '.join(dis[:2])}" if dis else ""))
            if best["risk"] < ru["risk"] - 0.05:
                lines.append(f"Lower disruption risk ({best['risk']:.0%} vs {ru['risk']:.0%})")
        if best["risk_reasons"]:
            lines.append("Risk on this route: " + "; ".join(best["risk_reasons"][:2]))
        return lines

    def _change(self, routes: list[dict], prev: dict, cur: dict, pw: dict, w: dict) -> dict:
        by = {r["id"]: r for r in routes}
        if prev["best"] == cur["best"]:
            return {"changed": False, "text": f"Route {by[cur['best']]['label']} is still preferred."}
        old, new = by[prev["best"]], by[cur["best"]]
        n = cur["norms"]
        # which metric's change in weight moved the scores most in favour of the new route
        swing = {m: (w[m] - pw[m]) * (n[old["id"]][m] - n[new["id"]][m]) for m in METRICS}
        m = max(swing, key=swing.get)
        a, b = new[METRIC_FIELD[m]], old[METRIC_FIELD[m]]
        diff = (1 - a / b) * 100 if b else 0.0
        direction = "more" if w[m] > pw[m] else "less"
        text = (f"Route {new['label']} became preferable because {METRIC_LABEL[m]} was weighted {direction} heavily "
                f"({pw[m]:.0%} → {w[m]:.0%}): it has {abs(diff):.0f}% {'lower' if diff > 0 else 'higher'} "
                f"{METRIC_LABEL[m]} than route {old['label']}.")
        return {"changed": True, "from": old["id"], "to": new["id"], "driver": m, "text": text,
                "swing": {k: round(v, 4) for k, v in swing.items()}}


def assumptions() -> dict:
    cm = config.COST_MODEL
    return {"label": "SIMULATED planning assumptions — not live market prices",
            "road": {k: v for k, v in cm["road"].items()}, "rail": dict(cm["rail"]), "sea": dict(cm["sea"]),
            "transfer": [{"from": a, "to": b, "inr_per_tonne": c, "hours": h} for (a, b), (c, h) in cm["transfer"].items()],
            "pallet_tonnes": config.PALLET_TONNES,
            "carbon": "per-unit CO2 factors of the network model (same as the LP optimizer)"}
