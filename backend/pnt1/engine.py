"""Cascade + Monte Carlo execution engine (C09, F-31/F-34).

Executes a plan hour by hour across R runs at once (vectorised on the run axis):
inbound blocked -> warehouse stock runs down -> it cannot ship -> customers go unserved.
Randomness per run: disruption duration (log-normal), demand multiplier (log-normal), transit delay (gamma).
Common random numbers: pass the same seed to compare strategies fairly.
"""
from __future__ import annotations

import math

import numpy as np

from . import config
from .network import Network, customer_demand_per_day, supply_per_day, warehouse_served_demand
from .planning import Disruption


class Engine:
    def __init__(self, net: Network):
        self.net = net
        self.nodes = list(net.nodes)
        self.nix = {n: i for i, n in enumerate(self.nodes)}
        self.skus = config.SKUS
        S, N = len(self.skus), len(self.nodes)
        self.demand = np.zeros((N, S))
        for (c, s), d in customer_demand_per_day(net).items():
            self.demand[self.nix[c], self.skus.index(s)] = d / 24.0
        self.supply = np.zeros((N, S))
        for (n, s), d in supply_per_day(net).items():
            self.supply[self.nix[n], self.skus.index(s)] = d / 24.0
        self.ss = np.zeros((N, S))
        for (w, s), d in warehouse_served_demand(net).items():
            self.ss[self.nix[w], self.skus.index(s)] = d * config.SAFETY_STOCK_DAYS
        self.value = np.array([config.UNIT_VALUE_INR[s] for s in self.skus])
        self.links = list(net.links.values())
        self.wh_idx = [self.nix[n.id] for n in net.of_type("Warehouse")]
        self.cust_idx = [self.nix[n.id] for n in net.of_type("CustomerCluster")]

    def run(self, flows: dict, init_inv: dict, disruptions: list[Disruption], runs: int = config.MC_RUNS,
            seed: int = 7, deterministic: bool = False, frames: bool = False) -> dict:
        net, H, P = self.net, config.HORIZON_H, config.PERIOD_H
        R, N, S = (1 if deterministic else runs), len(self.nodes), len(self.skus)
        rng = np.random.default_rng(seed)
        L = len(self.links)
        if deterministic:
            dur_mult = np.ones(R)
            dem_mult = np.ones(R)
            delay_mult = np.ones((R, L))
        else:
            dur_mult = rng.lognormal(0.0, config.MC_DURATION_SIGMA, R)
            dem_mult = rng.lognormal(0.0, config.MC_DEMAND_SIGMA, R)
            delay_mult = 1.0 + rng.gamma(4.0, config.MC_DELAY_THETA, (R, L))
        lead_h = np.maximum(1, np.rint(np.array([l.base_time_h for l in self.links])[None, :] * delay_mult)).astype(int)
        max_lead = int(lead_h.max()) + 2
        inv = np.zeros((R, N, S))
        inv[:, self.cust_idx] = self.demand[self.cust_idx][None] * config.CUSTOMER_BUFFER_H
        for (n, s), q in init_inv.items():
            if n in self.nix:
                inv[:, self.nix[n], self.skus.index(s)] = q
        arr = np.zeros((R, H + max_lead, N, S))
        blocked_sets = [d.blocked_links(net) for d in disruptions]
        per_link = {}
        for (lid, s, t), q in flows.items():
            per_link.setdefault(lid, np.zeros((config.N_PERIODS, S)))[t, self.skus.index(s)] += q
        active = [(li, l, per_link[l.id]) for li, l in enumerate(self.links) if l.id in per_link]
        transport = np.zeros(R)
        co2 = np.zeros(R)
        unmet = np.zeros((R, S))
        demand_total = np.zeros(R)
        rr = np.arange(R)
        out_frames = []
        first_stockout: dict[str, int] = {}

        def window(d: Disruption, h: int) -> np.ndarray:
            return (d.start_h <= h) & (h < d.start_h + d.duration_h * dur_mult)

        for h in range(H):
            # production (suppliers, ports, factories), reduced during failures
            prod_f = np.ones((R, N))
            dmult = np.ones((R, N))
            for d in disruptions:
                if d.target in self.nix:
                    w = window(d, h)
                    if d.kind == "supplier_failure":
                        prod_f[w, self.nix[d.target]] *= max(0.0, 1.0 - d.magnitude)
                    elif d.kind in ("port_closure", "warehouse_failure"):
                        prod_f[w, self.nix[d.target]] = 0.0
                if d.kind == "demand_spike":
                    w = window(d, h)
                    tgt = self.cust_idx if d.target == "all" else ([self.nix[d.target]] if d.target in self.nix else [])
                    for c in tgt:
                        dmult[w, c] *= 1.0 + d.magnitude
            inv += self.supply[None] * prod_f[:, :, None]
            inv += arr[:, h]
            # customers consume
            dem = self.demand[None] * dem_mult[:, None, None] * dmult[:, :, None]
            dem_c = dem[:, self.cust_idx]
            have = inv[:, self.cust_idx]
            served = np.minimum(have, dem_c)
            inv[:, self.cust_idx] = have - served
            unmet += (dem_c - served).sum(axis=1)
            demand_total += dem_c.sum(axis=(1, 2))
            # shipments
            p = h // P
            for li, l, fl in active:
                want = fl[p] / P
                if not want.any():
                    continue
                o, dst = self.nix[l.frm], self.nix[l.to]
                ok = np.ones(R, dtype=bool)
                for d, bs in zip(disruptions, blocked_sets):
                    if l.id in bs:
                        ok &= ~window(d, h)
                ship = np.minimum(want[None, :], inv[:, o]) * ok[:, None]
                inv[:, o] -= ship
                ah = np.minimum(h + lead_h[:, li], H + max_lead - 1)
                arr[rr, ah, dst] += ship
                q = ship.sum(axis=1)
                transport += q * l.cost_per_unit
                co2 += q * l.co2_kg_per_unit
            if frames:
                wh = {}
                for wi in self.wh_idx:
                    nid = self.nodes[wi]
                    stock = inv[0, wi]
                    ssv = self.ss[wi]
                    ratio = float(np.min(np.where(ssv > 0, stock / np.maximum(ssv, 1e-9), 9.0)))
                    if ratio <= 0.01 and nid not in first_stockout:
                        first_stockout[nid] = h
                    wh[nid] = {"inv": round(float(stock.sum())), "ratio": round(min(ratio, 9.0), 2)}
                blocked_now = sorted({lid for d, bs in zip(disruptions, blocked_sets) if window(d, h)[0] for lid in bs})
                out_frames.append({"h": h, "wh": wh, "unmet_cum": round(float(unmet[0].sum()), 1),
                                   "blocked": blocked_now})
        stockout_cost = (unmet * self.value[None] * config.STOCKOUT_PENALTY_FACTOR).sum(axis=1)
        total = transport + stockout_cost
        service = 1.0 - unmet.sum(axis=1) / np.maximum(demand_total, 1e-9)
        res = {"transport": transport, "stockout_cost": stockout_cost, "total": total,
               "unmet_units": unmet.sum(axis=1), "service": service, "co2": co2, "unmet_sku": unmet}
        if frames:
            res["frames"] = out_frames
            res["first_stockout_h"] = first_stockout
        return res


def summarize(r: dict) -> dict:
    t = r["total"]
    return {"cost_mean": float(np.mean(t)), "cost_p50": float(np.percentile(t, 50)),
            "cost_p90": float(np.percentile(t, 90)), "transport_mean": float(np.mean(r["transport"])),
            "stockout_cost_mean": float(np.mean(r["stockout_cost"])),
            "unmet_units_mean": float(np.mean(r["unmet_units"])),
            "service_mean": float(np.mean(r["service"])), "co2_kg_mean": float(np.mean(r["co2"])),
            "robustness": float(np.mean(r["service"] >= 0.95)),
            # V2: spread of outcomes across the Monte Carlo futures
            "cost_std": float(np.std(t)), "cost_p10": float(np.percentile(t, 10)),
            "service_p10": float(np.percentile(r["service"], 10)),
            "unmet_by_sku_mean": {s: float(v) for s, v in zip(config.SKUS, np.mean(r["unmet_sku"], axis=0))}
            if "unmet_sku" in r else {}}
