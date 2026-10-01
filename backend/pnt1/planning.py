"""Optimizer (C10, F-40/F-41): time-expanded multi-commodity min-cost flow LP solved with OR-Tools GLOP.

Periods of PERIOD_H hours over HORIZON_H. Flows depart in period t and arrive in t + lead(l).
Level 2 simplifications (documented in docs/DECISIONS.md): no in-flight pipeline at t=0, lost sales
(no backlog) at customers, fleet capacity folded into link capacity.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from ortools.linear_solver import pywraplp

from . import config
from .network import Network, customer_demand_per_day, supply_per_day, warehouse_served_demand


@dataclass
class Disruption:
    """What is broken, when. Hours are relative to plan start."""
    kind: str                         # link_closure | port_closure | warehouse_failure | supplier_failure | demand_spike
    target: str
    start_h: float = 0.0
    duration_h: float = 24.0
    magnitude: float = 1.0            # supplier capacity loss fraction, or demand spike +fraction

    def blocked_links(self, net: Network) -> set[str]:
        if self.kind == "link_closure":
            base = net.links.get(self.target)
            if not base:
                return set()
            return {l.id for l in net.links.values() if l.corridor_id == base.corridor_id and l.mode == base.mode}
        if self.kind == "storm":
            # severe weather between two places closes every road/rail link between them (both directions)
            base = net.links.get(self.target)
            if not base:
                return set()
            ends = {base.frm, base.to}
            return {l.id for l in net.links.values() if {l.frm, l.to} == ends and l.mode in ("road", "rail")}
        if self.kind in ("port_closure", "warehouse_failure"):
            return {l.id for l in net.links.values() if self.target in (l.frm, l.to)}
        return set()

    def active(self, hour: float) -> bool:
        return self.start_h <= hour < self.start_h + self.duration_h


@dataclass
class PlanResult:
    name: str
    flows: dict[tuple[str, str, int], float]           # (link, sku, period) -> units
    status: str
    objective: float
    solve_s: float
    transport_cost: float
    notes: list[str] = field(default_factory=list)


def lead_periods(net: Network, lid: str) -> int:
    return max(1, math.ceil(net.links[lid].base_time_h / config.PERIOD_H))


def weights_from_priorities(pr: dict | None) -> dict | None:
    """V2: user priority shares over money/time/fuel/distance/carbon -> LP objective weights.

    Stockout and risk keep fixed weights (service is never traded away silently)."""
    if not pr:
        return None
    keys = ("money", "time", "fuel", "distance", "carbon")
    v = {k: max(0.0, float(pr.get(k, 0.0) or 0.0)) for k in keys}
    tot = sum(v.values()) or 1.0
    v = {k: x / tot for k, x in v.items()}
    sc = config.WEIGHT_SCALE
    return {"cost": sc * v["money"], "delay": sc * v["time"], "fuel": sc * v["fuel"], "dist": sc * v["distance"],
            "co2": sc * v["carbon"], "stockout": 1.0, "risk": 0.5}


def solve_plan(net: Network, init_inv: dict[tuple[str, str], float], disruptions: list[Disruption],
               preset: str = "balanced", name: str = "plan", upper_bounds: dict | None = None,
               risk_links: dict[str, float] | None = None, weights: dict | None = None) -> PlanResult:
    """upper_bounds: {(link, sku, t): ub} restricts some flows (used to build reroute / transfer strategies).

    V2: `weights` (from weights_from_priorities) overrides the preset; keys fuel/dist are optional extra terms."""
    t0 = time.time()
    w = dict(weights) if weights else dict(config.PRESETS[preset])
    fuel_w, dist_w = w.get("fuel", 0.0), w.get("dist", 0.0)
    fuel_unit = {}
    if fuel_w:
        from .costing import fuel_cost_per_unit
        fuel_unit = {lid: fuel_cost_per_unit(net, lid) for lid in net.links}
    T, P = config.N_PERIODS, config.PERIOD_H
    solver = pywraplp.Solver.CreateSolver("GLOP")
    solver.SetTimeLimit(int(config.SOLVER_TIME_LIMIT_S * 1000))
    inf = solver.infinity()
    skus = config.SKUS
    demand = customer_demand_per_day(net)
    supply = supply_per_day(net)
    served = warehouse_served_demand(net)
    risk_links = risk_links or {}

    def link_avail(lid: str, t: int) -> float:
        h = t * P + P / 2
        for d in disruptions:
            if lid in d.blocked_links(net) and d.active(h):
                return 0.0
        return 1.0

    def supply_avail(n: str, t: int) -> float:
        h = t * P + P / 2
        f = 1.0
        for d in disruptions:
            if d.active(h) and d.target == n:
                if d.kind == "supplier_failure":
                    f *= max(0.0, 1.0 - d.magnitude)
                elif d.kind in ("port_closure", "warehouse_failure"):
                    f = 0.0
        return f

    def demand_mult(c: str, t: int) -> float:
        h = t * P + P / 2
        m = 1.0
        for d in disruptions:
            if d.kind == "demand_spike" and d.active(h) and (d.target == c or d.target == "all"):
                m *= 1.0 + d.magnitude
        return m

    f = {}
    for l in net.links.values():
        for s in skus:
            for t in range(T):
                ub = inf
                if upper_bounds is not None and (l.id, s, t) in upper_bounds:
                    ub = upper_bounds[(l.id, s, t)]
                f[(l.id, s, t)] = solver.NumVar(0.0, ub, "")
    obj = solver.Objective()
    for (lid, s, t), var in f.items():
        l = net.links[lid]
        coeff = (w["cost"] * l.cost_per_unit + w["delay"] * l.base_time_h * config.DELAY_COST_PER_UNIT_H
                 + w["co2"] * l.co2_kg_per_unit * config.CO2_PRICE_PER_KG
                 + w["risk"] * risk_links.get(lid, 0.0) * config.UNIT_VALUE_INR[s] * 0.05
                 + fuel_w * fuel_unit.get(lid, 0.0) + dist_w * l.dist_km * config.DIST_PRICE_PER_UNIT_KM)
        obj.SetCoefficient(var, coeff)
    for l in net.links.values():
        for t in range(T):
            cap = l.capacity_units_day * P / 24.0 * link_avail(l.id, t)
            c = solver.Constraint(0.0, cap)
            for s in skus:
                c.SetCoefficient(f[(l.id, s, t)], 1.0)

    inbound: dict[str, list] = {}
    outbound: dict[str, list] = {}
    for l in net.links.values():
        inbound.setdefault(l.to, []).append(l.id)
        outbound.setdefault(l.frm, []).append(l.id)

    hvars: dict[tuple[str, str, int], object] = {}
    for n in net.nodes.values():
        for s in skus:
            if n.type == "CustomerCluster":
                # customer sites hold what was delivered; unmet demand u is lost (penalised)
                prev = None
                buf = demand.get((n.id, s), 0.0) * config.CUSTOMER_BUFFER_H / 24.0
                init_c = init_inv.get((n.id, s), buf)
                for t in range(T):
                    d = demand.get((n.id, s), 0.0) * P / 24.0 * demand_mult(n.id, t)
                    hc = solver.NumVar(0.0, inf, "")
                    u = solver.NumVar(0.0, inf, "")
                    obj.SetCoefficient(u, w["stockout"] * config.UNIT_VALUE_INR[s] * config.STOCKOUT_PENALTY_FACTOR)
                    rhs = (init_c if t == 0 else 0.0) - d
                    c = solver.Constraint(rhs, rhs)          # hc_t - hc_{t-1} - arrivals - u = -d (+init at t=0)
                    c.SetCoefficient(hc, 1.0)
                    c.SetCoefficient(u, -1.0)
                    if prev is not None:
                        c.SetCoefficient(prev, -1.0)
                    for lid in inbound.get(n.id, []):
                        tt = t - lead_periods(net, lid)
                        if tt >= 0:
                            c.SetCoefficient(f[(lid, s, tt)], -1.0)
                    prev = hc
                continue
            if n.type == "Supplier":
                for t in range(T):
                    cap = supply.get((n.id, s), 0.0) * P / 24.0 * supply_avail(n.id, t)
                    c = solver.Constraint(-inf, cap)
                    for lid in outbound.get(n.id, []):
                        c.SetCoefficient(f[(lid, s, t)], 1.0)
                continue
            # warehouses, ports, factories: inventory balance
            prev = None
            ss = served.get((n.id, s), 0.0) * config.SAFETY_STOCK_DAYS if n.type == "Warehouse" else 0.0
            for t in range(T):
                h = solver.NumVar(0.0, inf, "")
                y_cap = supply.get((n.id, s), 0.0) * P / 24.0 * supply_avail(n.id, t)
                y = solver.NumVar(0.0, y_cap, "") if y_cap > 0 else None
                # h_t - h_{t-1} - y - sum(arrivals) + sum(departures) = init (t=0)
                c = solver.Constraint(init_inv.get((n.id, s), 0.0) if t == 0 else 0.0,
                                      init_inv.get((n.id, s), 0.0) if t == 0 else 0.0)
                c.SetCoefficient(h, 1.0)
                if prev is not None:
                    c.SetCoefficient(prev, -1.0)
                if y is not None:
                    c.SetCoefficient(y, -1.0)
                for lid in inbound.get(n.id, []):
                    tt = t - lead_periods(net, lid)
                    if tt >= 0:
                        c.SetCoefficient(f[(lid, s, tt)], -1.0)
                for lid in outbound.get(n.id, []):
                    c.SetCoefficient(f[(lid, s, t)], 1.0)
                if ss > 0:
                    z = solver.NumVar(0.0, inf, "")
                    obj.SetCoefficient(z, config.SAFETY_SLACK_FRACTION * config.UNIT_VALUE_INR[s])
                    cs = solver.Constraint(ss, inf)
                    cs.SetCoefficient(h, 1.0)
                    cs.SetCoefficient(z, 1.0)
                prev = h
                hvars[(n.id, s, t)] = h
    for n in net.of_type("Warehouse"):
        for t in range(T):
            c = solver.Constraint(0.0, float(n.capacity))
            for s in skus:
                c.SetCoefficient(hvars[(n.id, s, t)], 1.0)
    obj.SetMinimization()
    status = solver.Solve()
    status_name = {pywraplp.Solver.OPTIMAL: "optimal", pywraplp.Solver.FEASIBLE: "feasible_timeout"}.get(status)
    if status_name is None:
        return PlanResult(name, {}, "infeasible_or_error", float("nan"), time.time() - t0, 0.0,
                          ["solver failed; caller should use heuristic fallback"])
    flows = {k: v.solution_value() for k, v in f.items() if v.solution_value() > 1e-6}
    tc = sum(q * net.links[k[0]].cost_per_unit for k, q in flows.items())
    return PlanResult(name, flows, status_name, obj.Value(), time.time() - t0, tc)
