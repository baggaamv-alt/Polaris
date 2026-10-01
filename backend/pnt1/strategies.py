"""Strategy generation + expected-value decision (F-42, F-43, F-17).

Four futures: do nothing (baseline plan executed under the disruption), reroute (supply routes re-planned,
warehouse-to-warehouse transfers capped at baseline), transfer (only warehouse-to-warehouse flows re-planned),
hybrid (everything re-planned). Each is executed by the Monte Carlo engine with common random numbers.

EV rule (docs/02_ARCHITECTURE.md section 8):
  C_a  = E[cost | no disruption, plan] - E[cost | no disruption, baseline]   (paid even if nothing happens)
  L_x  = E[cost | disruption, plan] - E[cost | no disruption, plan]
  act iff p * (L0 - L1) > C_a ;  break-even p* = C_a / (L0 - L1)
"""
from __future__ import annotations

import time

import numpy as np

from . import config
from .engine import Engine, summarize
from .network import Network
from .planning import Disruption, solve_plan


def _is_transfer(net: Network, lid: str) -> bool:
    l = net.links[lid]
    return net.nodes[l.frm].type == "Warehouse" and net.nodes[l.to].type == "Warehouse"


def _caps_from(base_flows: dict, net: Network, keep_transfer: bool) -> dict:
    """Upper bounds: flows of the fixed category may not exceed the baseline plan."""
    ub = {}
    for l in net.links.values():
        if _is_transfer(net, l.id) == keep_transfer:
            for s in config.SKUS:
                for t in range(config.N_PERIODS):
                    ub[(l.id, s, t)] = base_flows.get((l.id, s, t), 0.0)
    return ub


def link_period_flows(net: Network, flows: dict) -> dict[str, list[float]]:
    """(link, sku, period) -> units  ==>  link -> [units per period] (V2: drives the 72-hour map timeline)."""
    out: dict[str, list[float]] = {}
    for (lid, _s, t), q in flows.items():
        out.setdefault(lid, [0.0] * config.N_PERIODS)[t] += q
    return {k: [round(x, 1) for x in v] for k, v in out.items() if sum(v) > 0.5}


def plan_diff(net: Network, base: dict, plan: dict) -> dict:
    """What the recommended plan changes vs the baseline: warehouse-to-warehouse transfers and rerouted links."""
    tot = lambda f: {lid: sum(q for (l, _s, _t), q in f.items() if l == lid) for lid in net.links}  # noqa: E731
    b, p = tot(base), tot(plan)
    transfers = []
    for lid in net.links:
        if _is_transfer(net, lid) and p[lid] - b[lid] > 0.5:
            l = net.links[lid]
            by_sku: dict[str, float] = {}
            first = None
            for (ll, s, t), q in plan.items():
                if ll == lid and q > 0.5:
                    by_sku[s] = by_sku.get(s, 0.0) + q
                    first = t if first is None else min(first, t)
            transfers.append({"link": lid, "from": l.frm, "to": l.to, "mode": l.mode, "units": round(p[lid] - b[lid], 1),
                              "by_sku": {k: round(v, 1) for k, v in by_sku.items()}, "start_h": (first or 0) * config.PERIOD_H,
                              "eta_h": round(l.base_time_h, 1), "cost_inr": round((p[lid] - b[lid]) * l.cost_per_unit)})
    changed = [{"link": lid, "baseline": round(b[lid], 1), "plan": round(p[lid], 1), "delta": round(p[lid] - b[lid], 1)}
               for lid in net.links if abs(p[lid] - b[lid]) > 5 and not _is_transfer(net, lid)]
    changed.sort(key=lambda x: -abs(x["delta"]))
    transfers.sort(key=lambda x: -x["units"])
    return {"transfers": transfers[:12], "rerouted_links": changed[:16]}


def _hist(values: np.ndarray, lo: float, hi: float, bins: int = 20) -> list[int]:
    if hi <= lo:
        hi = lo + 1.0
    return [int(x) for x in np.histogram(values, bins=bins, range=(lo, hi))[0]]


def evaluate_scenario(net: Network, engine: Engine, init_inv: dict, disruption: Disruption, probability: float,
                      preset: str = "balanced", seed: int = 11, runs: int = config.MC_RUNS,
                      weights: dict | None = None) -> dict:
    t0 = time.time()
    dis = [disruption]
    risk = {lid: probability for lid in disruption.blocked_links(net)}
    kw = {"weights": weights}
    base = solve_plan(net, init_inv, [], preset, "baseline", **kw)
    if base.status == "infeasible_or_error":
        return {"error": "baseline plan could not be solved"}
    plans = {"do_nothing": base}
    plans["reroute"] = solve_plan(net, init_inv, dis, preset, "reroute", _caps_from(base.flows, net, True), risk, **kw)
    plans["transfer"] = solve_plan(net, init_inv, dis, preset, "transfer", _caps_from(base.flows, net, False), risk, **kw)
    plans["hybrid"] = solve_plan(net, init_inv, dis, preset, "hybrid", None, risk, **kw)
    for k, p in plans.items():
        if p.status == "infeasible_or_error":
            plans[k] = base
            base.notes.append(f"{k}: solver failed, fell back to baseline plan")
    base_nodis = summarize(engine.run(base.flows, init_inv, [], runs, seed))
    out = {}
    raws = {}
    for k, p in plans.items():
        nod = summarize(engine.run(p.flows, init_inv, [], runs, seed))
        yes_raw = engine.run(p.flows, init_inv, dis, runs, seed)
        raws[k] = yes_raw
        yes = summarize(yes_raw)
        c_a = nod["cost_mean"] - base_nodis["cost_mean"] if k != "do_nothing" else 0.0
        loss = yes["cost_mean"] - nod["cost_mean"]
        out[k] = {"plan_status": p.status, "solve_s": round(p.solve_s, 2), "action_cost": c_a, "loss_if_disrupted": loss,
                  "if_disrupted": yes, "if_not": nod,
                  "expected_cost": base_nodis["cost_mean"] + c_a + probability * loss}
    L0 = out["do_nothing"]["loss_if_disrupted"]
    for k, v in out.items():
        if k == "do_nothing":
            v.update({"expected_loss_avoided": 0.0, "net_benefit": 0.0, "break_even_p": None})
            continue
        avoided = L0 - v["loss_if_disrupted"]
        v["expected_loss_avoided"] = probability * avoided
        v["net_benefit"] = probability * avoided - v["action_cost"]
        v["break_even_p"] = (max(0.0, v["action_cost"]) / avoided) if avoided > 1e-9 else None
    best = min(out, key=lambda k: out[k]["expected_cost"])
    e0 = out["do_nothing"]["expected_cost"]
    reason = "lowest expected cost across Monte Carlo futures"
    if best != "do_nothing" and (e0 - out[best]["expected_cost"]) < config.MIN_MEANINGFUL_SAVING * e0:
        reason = (f"{best} is only marginally cheaper (< {config.MIN_MEANINGFUL_SAVING:.1%}); "
                  "not worth changing the plan")
        best = "do_nothing"
    for k, v in out.items():
        v["dominates_baseline"] = k != "do_nothing" and v["action_cost"] < 0
    frames = {}
    for k in ("do_nothing", best):
        r = engine.run(plans[k].flows, init_inv, dis, deterministic=True, frames=True)
        frames[k] = {"frames": r["frames"], "first_stockout_h": r["first_stockout_h"],
                     "link_flows": link_period_flows(net, plans[k].flows)}
    # V2: Monte Carlo spread (same bins for both plans so they can be overlaid)
    lo = float(min(raws["do_nothing"]["total"].min(), raws[best]["total"].min()))
    hi = float(max(raws["do_nothing"]["total"].max(), raws[best]["total"].max()))
    mc = {"bins": 20, "cost_range": [lo, hi],
          "cost_hist": {k: _hist(raws[k]["total"], lo, hi) for k in {"do_nothing", best}},
          "service_hist": {k: _hist(raws[k]["service"], 0.0, 1.0) for k in {"do_nothing", best}}}
    return {"strategies": out, "recommended": best, "recommendation_reason": reason,
            "probability": probability, "preset": preset, "weights": weights,
            "runs": runs, "frames": frames, "blocked_links": sorted(disruption.blocked_links(net)),
            "monte_carlo": mc, "plan_diff": plan_diff(net, base.flows, plans[best].flows),
            "runtime_s": round(time.time() - t0, 2), "optimizer": "OR-Tools GLOP LP (time-expanded min-cost flow)",
            "notes": base.notes}


def raw_vs_trusted(net: Network, engine: Engine, trusted_inv: dict, raw_inv: dict, disruption: Disruption | None,
                   preset: str = "balanced", seed: int = 11) -> dict:
    """F-17: plan once from what the feeds claim, once from trusted inventory; execute both on trusted stock."""
    dis = [disruption] if disruption else []
    p_raw = solve_plan(net, raw_inv, dis, preset, "from_raw")
    p_tr = solve_plan(net, trusted_inv, dis, preset, "from_trusted")
    r_raw = summarize(engine.run(p_raw.flows, trusted_inv, dis, config.MC_RUNS, seed))
    r_tr = summarize(engine.run(p_tr.flows, trusted_inv, dis, config.MC_RUNS, seed))
    diffs = []
    for (n, s), q in raw_inv.items():
        tq = trusted_inv.get((n, s), 0.0)
        if abs(q - tq) > max(10.0, 0.05 * max(tq, 1.0)):
            diffs.append({"node": n, "sku": s, "claimed": round(q), "trusted": round(tq)})
    return {"from_raw": r_raw, "from_trusted": r_tr, "inventory_differences": diffs,
            "extra_cost_if_raw_trusted": r_raw["cost_mean"] - r_tr["cost_mean"]}
