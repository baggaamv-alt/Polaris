"""Ground-truth world simulator + telemetry emitter + attack injectors (C01, T-01..T-08).

The world knows the truth. It emits *observations* (noisy, sometimes attacked) as envelopes.
Ground-truth labels go to TruthStore, which only pnt1.evaluation may read (never the twin).
"""
from __future__ import annotations

import math
import zlib
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from . import config
from .geo import bearing_deg, offset_point
from .network import Network, supply_per_day, warehouse_served_demand

INJECTORS = ("gps_spoof_teleport", "gps_spoof_drift", "speed_spike", "inventory_fake", "feed_corrupt",
             "payload_incomplete", "duplicate_replay", "entity_blackout", "mass_blackout",
             "coordinated_stop_spoof")
SCENARIO_EVENTS = ("real_blockage",)


@dataclass
class Vehicle:
    id: str
    fleet: str
    shuttle: bool
    route: list[str] = field(default_factory=list)
    rev: list[bool] = field(default_factory=list)
    leg: int = 0
    km_on_leg: float = 0.0
    cruise_kmh: float = 55.0
    speed_kmh: float = 0.0
    stop_until: float = 0.0
    dwell_until: float = 0.0
    sku: str = "SKU-A"
    load: int = 0
    fuel: float = 90.0
    shipment_id: str = ""
    dest: str = ""
    next_report: float = 0.0
    lat: float = 0.0
    lon: float = 0.0
    heading: float = 0.0


@dataclass
class Attack:
    id: str
    kind: str
    targets: list[str]
    params: dict
    start: float
    end: float
    state: dict = field(default_factory=dict)


class TruthStore:
    """Hidden ground truth. Only the evaluation module may import and read this."""

    def __init__(self) -> None:
        self.labels: dict[str, dict] = {}
        self.attack_log: list[dict] = []

    def label(self, event_id: str, is_attacked: bool, injector: str | None, source_id: str, true_value: dict) -> None:
        self.labels[event_id] = {"is_attacked": is_attacked, "injector": injector, "source_id": source_id,
                                 "true_value": true_value}
        if len(self.labels) > 400_000:
            for k in list(self.labels)[:100_000]:
                del self.labels[k]


class World:
    def __init__(self, net: Network, seed: int = config.WORLD_SEED):
        self.net = net
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.t = 0.0
        self.start = datetime.fromisoformat(config.SIM_START_ISO)
        self.truth = TruthStore()
        self.seq: dict[str, int] = {}
        self.blocks: dict[str, dict] = {}
        self.attacks: dict[str, Attack] = {}
        self.command_log: list[dict] = []
        self.closed_nodes: dict[str, float] = {}     # V2 live incidents: node -> sim time it reopens
        self.reroutes: list[dict] = []
        self.replay_buffer: dict[str, deque] = {}
        self.served = warehouse_served_demand(net)
        self.supply = supply_per_day(net)
        self.warehouses = [n.id for n in net.of_type("Warehouse")]
        self.inv: dict[tuple[str, str], float] = {}
        for w in self.warehouses:
            for s in config.SKUS:
                daily = self.served.get((w, s), 20.0)
                self.inv[(w, s)] = float(min(daily * self.rng.uniform(config.INIT_COVER_DAYS[0], config.INIT_COVER_DAYS[1]), net.nodes[w].capacity / 5))
        self.flow_in = {k: 0.0 for k in self.inv}
        self.flow_out = {k: 0.0 for k in self.inv}
        self.unmet: dict[tuple[str, str], float] = {k: 0.0 for k in self.inv}
        self.next_wh_report = {w: float(self.rng.uniform(0, config.WAREHOUSE_INTERVAL_S)) for w in self.warehouses}
        self.ports = [n.id for n in net.of_type("Port")]
        self.next_port_report = {p: float(self.rng.uniform(0, config.PORT_INTERVAL_S)) for p in self.ports}
        self.origins = [n.id for n in net.nodes.values() if n.type in ("Supplier", "Port", "Factory", "Warehouse")]
        self._route_cache: dict[tuple[str, str], list[str]] = {}
        self.vehicles: list[Vehicle] = []
        i = 0
        for fleet, count in config.N_VEHICLES.items():
            for k in range(count):
                i += 1
                v = Vehicle(id=f"truck-{fleet[-1]}-{k + 1:03d}", fleet=fleet,
                            shuttle=k < config.CORRIDOR_SHUTTLES_PER_FLEET,
                            cruise_kmh=float(self.rng.uniform(45, 68)))
                self._new_trip(v, initial=True)
                v.next_report = float(self.rng.uniform(0, config.GPS_INTERVAL_S))
                self.vehicles.append(v)
        self._vehicle_by_id = {v.id: v for v in self.vehicles}

    # ------------------------------------------------------------------ time
    def iso(self, t: float | None = None) -> str:
        return (self.start + timedelta(seconds=self.t if t is None else t)).isoformat()

    # ------------------------------------------------------------------ trips
    def _cover(self, w: str, s: str) -> float:
        daily = self.served.get((w, s), 0.0)
        return self.inv.get((w, s), 0.0) / daily if daily > 0 else 99.0

    def _route(self, src: str, dst: str) -> list[tuple[str, bool]]:
        key = (src, dst)
        if key not in self._route_cache:
            self._route_cache[key] = self.net.truck_route(src, dst)
        return self._route_cache[key]

    def _pick_job(self, v: Vehicle, src: str) -> tuple[str, str, int]:
        """Demand-aware dispatch: carry what is low to where it is low; otherwise drive empty to a producer."""
        net = self.net
        noise = lambda: float(self.rng.uniform(0, 1.0))  # noqa: E731
        if v.shuttle and not self._closed("W-VGA") and not self._closed("W-HYD"):
            dst = "W-VGA" if src == "W-HYD" else "W-HYD"
            if src in ("W-HYD", "W-VGA"):
                s = max(config.SKUS, key=lambda k: self._cover(src, k) - self._cover(dst, k) + noise())
                if self._cover(src, s) > 1.5:
                    return dst, s, int(min(config.TRUCK_CAPACITY, self.inv[(src, s)] * 0.25))
                return dst, s, 0
            return "W-HYD", "SKU-A", 0
        made_here = [s for (n, s) in self.supply if n == src]
        if made_here:
            # low cover first, but distance matters: 1 day of cover ~ 400 km of driving
            options = [(self._cover(w, s) + self._km(src, w) / 400.0 + noise(), w, s)
                       for s in made_here for w in self.warehouses if self._route(src, w) and not self._closed(w)]
            if options:
                _, w, s = min(options)
                return w, s, config.TRUCK_CAPACITY
        if net.nodes[src].type == "Warehouse":
            needy = sorted((self._cover(w, s) + noise(), w, s) for w in self.warehouses for s in config.SKUS
                           if w != src and self._cover(w, s) < 2.0 and self._cover(src, s) > 4.0 and self._route(src, w)
                           and not self._closed(w))
            if needy:
                _, w, s = needy[0]
                spare = self.inv[(src, s)] - 3.0 * self.served.get((src, s), 0.0)
                return w, s, int(max(0, min(config.TRUCK_CAPACITY, spare)))
        # empty leg: nearest producer of anything some warehouse is short of (cover < 3 days)
        needed = {s for w in self.warehouses for s in config.SKUS if self._cover(w, s) < 3.0} or set(config.SKUS)
        producers = sorted({n for (n, s) in self.supply if s in needed and n != src and self._route(src, n)
                            and not self._closed(n)})
        if not producers:
            producers = [n for n in self.origins if n != src and self._route(src, n)]
        p = min(producers, key=lambda n: self._km(src, n) * float(self.rng.uniform(0.8, 1.2)))
        return p, next(iter(needed)), 0

    def _closed(self, node: str) -> bool:
        return self.closed_nodes.get(node, -1.0) > self.t

    def _km(self, a: str, b: str) -> float:
        na, nb = self.net.nodes[a], self.net.nodes[b]
        return 111.0 * math.hypot(na.lat - nb.lat, (na.lon - nb.lon) * math.cos(math.radians(na.lat)))

    def _new_trip(self, v: Vehicle, initial: bool = False) -> None:
        net = self.net
        if initial or not v.dest:
            src = ("W-HYD" if self.rng.random() < 0.5 else "W-VGA") if v.shuttle else str(self.rng.choice(self.origins))
        else:
            src = v.dest
        dst, sku, take = self._pick_job(v, src)
        route = self._route(src, dst)
        if not route:
            dst, route, take = ("W-VGA", self._route("W-HYD", "W-VGA"), 0) if src == "W-HYD" else \
                (src, [], 0)
            if not route:
                src, dst, route = "W-HYD", "W-VGA", self._route("W-HYD", "W-VGA")
        v.route, v.rev = [lid for lid, _ in route], [r for _, r in route]
        v.leg, v.km_on_leg, v.dest = 0, 0.0, dst
        if take > 0 and net.nodes[src].type == "Warehouse":
            take = int(min(take, max(0.0, self.inv[(src, sku)] - 5)))
            self.inv[(src, sku)] -= take
            self.flow_out[(src, sku)] += take
        v.sku, v.load = sku, int(take)
        v.shipment_id = str(uuid.UUID(int=int(self.rng.integers(0, 2**63)) << 64 | int(self.rng.integers(0, 2**63))))
        if initial:
            total = sum(net.links[l].dist_km for l in v.route)
            pos = float(self.rng.uniform(0, total))
            for idx, lid in enumerate(v.route):
                d = net.links[lid].dist_km
                if pos <= d:
                    v.leg, v.km_on_leg = idx, pos
                    break
                pos -= d
        self._place(v)
        v._pending_shipment = True  # type: ignore[attr-defined]

    def _seg(self, v: Vehicle, leg: int) -> tuple[float, float, float, float]:
        s = self.net.links[v.route[leg]].seg
        return (s[2], s[3], s[0], s[1]) if v.rev and v.rev[leg] else s

    def _place(self, v: Vehicle) -> None:
        link = self.net.links[v.route[v.leg]]
        f = min(1.0, v.km_on_leg / max(link.dist_km, 1e-6))
        lat1, lon1, lat2, lon2 = self._seg(v, v.leg)
        v.lat, v.lon = lat1 + (lat2 - lat1) * f, lon1 + (lon2 - lon1) * f
        v.heading = bearing_deg(lat1, lon1, lat2, lon2)

    def _move(self, v: Vehicle, dt: float) -> None:
        if self.t < v.dwell_until:
            v.speed_kmh = 0.0
            return
        if getattr(v, "_arrived", False):
            v._arrived = False  # type: ignore[attr-defined]
            self._new_trip(v)
        if self.t < v.stop_until:
            v.speed_kmh = 0.0
            return
        if self.rng.random() < dt / (4 * 3600):
            v.stop_until = self.t + float(self.rng.uniform(15, 40)) * 60
            v.speed_kmh = 0.0
            return
        link = self.net.links[v.route[v.leg]]
        v.speed_kmh = max(5.0, v.cruise_kmh + float(self.rng.normal(0, 4)))
        advance = v.speed_kmh * dt / 3600.0
        blk = self.blocks.get(link.id)
        if blk:
            block_km = (1 - blk["frac"] if v.rev[v.leg] else blk["frac"]) * link.dist_km
            if v.km_on_leg <= block_km < v.km_on_leg + advance + 1e-9:
                v.km_on_leg = max(v.km_on_leg, block_km - float(self.rng.uniform(0.05, 1.2)))
                v.speed_kmh = 0.0
                self._place(v)
                return
            if abs(v.km_on_leg - block_km) < 1.5 and v.km_on_leg < block_km:
                v.speed_kmh = 0.0
                return
        v.km_on_leg += advance
        v.fuel = max(5.0, v.fuel - advance * 0.12 / 3.0)
        while v.km_on_leg >= link.dist_km:
            v.km_on_leg -= link.dist_km
            v.leg += 1
            if v.leg >= len(v.route):
                v.leg = len(v.route) - 1
                v.km_on_leg = link.dist_km
                self._deliver(v)
                break
            link = self.net.links[v.route[v.leg]]
        self._place(v)

    def _deliver(self, v: Vehicle) -> None:
        if (v.dest, v.sku) in self.inv:
            cap = self.net.nodes[v.dest].capacity
            total = sum(self.inv[(v.dest, s)] for s in config.SKUS)
            add = min(v.load, max(0.0, cap - total))
            self.inv[(v.dest, v.sku)] += add
            self.flow_in[(v.dest, v.sku)] += add
        v.load = 0
        if v.fuel < 30:
            v.fuel = 95.0
        v.dwell_until = self.t + float(self.rng.uniform(20, 40)) * 60
        v.speed_kmh = 0.0
        v._arrived = True  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ V2: operator-approved reroute
    def reroute_plan(self, vid: str, turnaround: bool) -> dict | None:
        """Where the truck can pivot and the road path from there to its destination avoiding `exclude`.

        If the truck's current leg is itself excluded it turns around at its current position (pivot = the node
        behind it); otherwise it completes the current leg (pivot = the node ahead)."""
        v = self._vehicle_by_id.get(vid)
        if v is None or not v.route:
            return None
        lid, rev = v.route[v.leg], v.rev[v.leg]
        link = self.net.links[lid]
        ahead, behind = (link.frm, link.to) if rev else (link.to, link.frm)
        turn = bool(turnaround)
        pivot = behind if turn else ahead
        done = v.km_on_leg / max(link.dist_km, 1e-6)
        return {"vehicle": vid, "dest": v.dest, "pivot": pivot, "turnaround": turn, "leg": [lid, rev],
                "lead_frac": done if turn else 1.0 - done, "remaining": list(zip(v.route[v.leg + 1:], v.rev[v.leg + 1:]))}

    def reroute_vehicle(self, vid: str, hops: list[tuple[str, bool]]) -> dict:
        """Apply a road path that starts at the truck's pivot node. Ground truth changes: the truck drives it."""
        v = self._vehicle_by_id.get(vid)
        if v is None or not v.route:
            raise ValueError("unknown or idle vehicle")
        lid, rev = v.route[v.leg], v.rev[v.leg]
        link = self.net.links[lid]
        ahead, behind = (link.frm, link.to) if rev else (link.to, link.frm)
        # validate continuity from a pivot
        def chain(start: str) -> str | None:
            cur = start
            for h_lid, h_rev in hops:
                l = self.net.links.get(h_lid)
                if l is None or l.mode != "road":
                    return None
                a, b = (l.to, l.frm) if h_rev else (l.frm, l.to)
                if a != cur:
                    return None
                cur = b
            return cur
        end_ahead, end_behind = chain(ahead), chain(behind)
        if end_ahead is not None:
            new_route = [(lid, rev)] + [(h, r) for h, r in hops]
            km = v.km_on_leg
            turn = False
        elif end_behind is not None:
            new_route = [(lid, not rev)] + [(h, r) for h, r in hops]
            km = link.dist_km - v.km_on_leg
            turn = True
        else:
            raise ValueError("path does not start at the truck's current link")
        end = end_ahead if end_ahead is not None else end_behind
        old = list(v.route)
        v.route, v.rev = [x[0] for x in new_route], [x[1] for x in new_route]
        v.leg, v.km_on_leg, v.dest = 0, km, end
        v.stop_until = min(v.stop_until, self.t)
        self._place(v)
        v._pending_shipment = True  # type: ignore[attr-defined]
        rec = {"t": self.t, "vehicle": vid, "old_route": old, "new_route": v.route, "turnaround": turn, "dest": end}
        self.reroutes.append(rec)
        return rec

    # ------------------------------------------------------------------ attacks
    def inject(self, kind: str, targets: list[str] | None = None, params: dict | None = None,
               duration_s: float | None = None) -> Attack:
        if kind not in INJECTORS and kind not in SCENARIO_EVENTS:
            raise ValueError(f"unknown injector {kind}")
        params = dict(params or {})
        targets = list(targets or [])
        default_dur = {"gps_spoof_teleport": 30, "speed_spike": 45, "gps_spoof_drift": 3600,
                       "coordinated_stop_spoof": 10800, "entity_blackout": 1800, "mass_blackout": 1200,
                       "inventory_fake": 3600, "feed_corrupt": 1800, "payload_incomplete": 1200,
                       "duplicate_replay": 60, "real_blockage": 2700}
        dur = float(duration_s or params.get("duration_s") or default_dur.get(kind, 600))
        if kind == "coordinated_stop_spoof":
            # Plausible fake queue: each spoofed truck keeps reporting normal driving toward one point on the
            # link, then reports a stop just behind it. Kinematically consistent, so per-reading trust stays
            # high - only the inference guard (quorum/corroboration/contradiction) can catch it.
            link_id = params.get("link", "L053")
            fleet = params.get("fleet", "FLEET-A")
            n = int(params.get("n", 8))
            link = self.net.links[link_id]
            on_link = [v for v in self.vehicles if v.fleet == fleet and v.route and v.route[v.leg] == link_id
                       and not v.rev[v.leg]
                       and self.t >= v.dwell_until]
            # pick the fake-queue point that the most compromised trucks can reach within ~120 km
            best, point_km = -1, link.dist_km / 2
            for cand in sorted(v.km_on_leg for v in on_link):
                pk = max(10.0, min(link.dist_km - 10.0, cand + 3.0))
                cnt = sum(1 for v in on_link if pk - 220.0 <= v.km_on_leg < pk)
                if cnt > best:
                    best, point_km = cnt, pk
            chosen = sorted([v for v in on_link if point_km - 220.0 <= v.km_on_leg < point_km],
                            key=lambda v: point_km - v.km_on_leg)[:n]
            targets = [v.id for v in chosen]
            params["fake"] = {v.id: {"km": v.km_on_leg, "stop_km": point_km - float(self.rng.uniform(0.05, 1.5)),
                                     "kmh": v.cruise_kmh} for v in chosen}
            params["link_id"] = link_id
        if kind == "mass_blackout":
            frac = float(params.get("fraction", 0.7))
            pool = [v.id for v in self.vehicles] + self.warehouses
            k = int(len(pool) * frac)
            targets = [str(x) for x in self.rng.choice(pool, size=k, replace=False)]
        if kind == "payload_incomplete" and not targets:
            targets = ["FLEET-C"]
        if kind == "duplicate_replay" and not targets:
            targets = ["FLEET-A"]
        if kind == "real_blockage":
            link = targets[0] if targets else params.get("link", "L053")
            targets = [link]
            self.blocks[link] = {"frac": float(params.get("frac", 0.5)), "until": self.t + dur}
        a = Attack(id=f"atk-{len(self.command_log) + 1:04d}", kind=kind, targets=targets, params=params,
                   start=self.t, end=self.t + dur)
        self.attacks[a.id] = a
        entry = {"t": self.t, "id": a.id, "kind": kind, "targets": targets,
                 "params": {k: v for k, v in params.items() if k not in ("fake",)}, "duration_s": dur}
        self.command_log.append(entry)
        self.truth.attack_log.append(entry)
        return a

    def stop_attacks(self) -> None:
        for a in self.attacks.values():
            a.end = min(a.end, self.t)
        for lid, b in self.blocks.items():
            b["until"] = min(b["until"], self.t)

    def active_attacks(self) -> list[Attack]:
        return [a for a in self.attacks.values() if a.start <= self.t < a.end]

    def _attacks_on(self, source_id: str, fleet: str | None = None) -> list[Attack]:
        return [a for a in self.active_attacks() if source_id in a.targets or (fleet and fleet in a.targets)]

    # ------------------------------------------------------------------ emission
    def _env(self, event_type: str, source_id: str, source_type: str, payload: dict, t: float | None = None) -> dict:
        s = self.seq.get(source_id, 0) + 1
        self.seq[source_id] = s
        return {"event_id": str(uuid.UUID(int=int(self.rng.integers(0, 2**63)) << 64 | int(self.rng.integers(0, 2**63)))),
                "event_type": event_type, "source_id": source_id, "source_type": source_type,
                "ts_event": self.iso(t), "seq": s, "payload": payload, "run_id": f"seed-{self.seed}"}

    def _vehicle_reading(self, v: Vehicle) -> list[dict]:
        attacks = self._attacks_on(v.id, v.fleet)
        if any(a.kind in ("entity_blackout", "mass_blackout") for a in attacks):
            return []
        noise_km = self.rng.normal(0, config.GPS_NOISE_M / 1000.0, 2)
        lat, lon = offset_point(v.lat, v.lon, 0.0, float(noise_km[0]))
        lat, lon = offset_point(lat, lon, 90.0, float(noise_km[1]))
        payload = {"lat": round(lat, 6), "lon": round(lon, 6),
                   "speed_kmh": round(max(0.0, v.speed_kmh + float(self.rng.normal(0, 1.0))) if v.speed_kmh > 0 else 0.0, 1),
                   "heading_deg": round(v.heading, 1), "load_units": int(v.load), "fuel_pct": round(v.fuel, 1),
                   "shipment_id": v.shipment_id}
        injector = None
        for a in attacks:
            if a.kind == "gps_spoof_teleport":
                payload["lat"], payload["lon"] = a.params.get("to", (15.0, 70.0))
                injector = a.kind
            elif a.kind == "gps_spoof_drift":
                off = 0.15 * (self.t - a.start) / 300.0
                la, lo = offset_point(payload["lat"], payload["lon"], (v.heading + 90) % 360, off)
                payload["lat"], payload["lon"] = round(la, 6), round(lo, 6)
                injector = a.kind
            elif a.kind == "speed_spike":
                payload["speed_kmh"] = round(float(self.rng.uniform(780, 812)), 1)
                injector = a.kind
            elif a.kind == "coordinated_stop_spoof" and v.id in a.params.get("fake", {}):
                f = a.params["fake"][v.id]
                link = self.net.links[a.params["link_id"]]
                last = f.get("t", a.start)
                f["t"] = self.t
                if f["km"] < f["stop_km"]:
                    f["km"] = min(f["stop_km"], f["km"] + f["kmh"] * (self.t - last) / 3600.0)
                    spd = f["kmh"] if f["km"] < f["stop_km"] else 0.0
                else:
                    spd = 0.0
                frac = f["km"] / link.dist_km
                la = link.seg[0] + (link.seg[2] - link.seg[0]) * frac
                lo = link.seg[1] + (link.seg[3] - link.seg[1]) * frac
                payload["lat"], payload["lon"] = round(la, 6), round(lo, 6)
                payload["speed_kmh"] = round(spd, 1)
                payload["heading_deg"] = round(bearing_deg(*link.seg), 1)
                injector = a.kind
            elif a.kind == "payload_incomplete" and self.rng.random() < float(a.params.get("fraction", 0.3)):
                drop = ["lat", "lon", "speed_kmh", "heading_deg", "fuel_pct"]
                for k in self.rng.choice(drop, size=int(self.rng.integers(1, 3)), replace=False):
                    payload.pop(str(k), None)
                injector = a.kind
        env = self._env("telemetry.vehicle", v.id, "vehicle", payload)
        self.truth.label(env["event_id"], injector is not None, injector, v.id,
                         {"lat": v.lat, "lon": v.lon, "speed_kmh": v.speed_kmh})
        out = [env]
        buf = self.replay_buffer.setdefault(v.fleet, deque(maxlen=4000))
        buf.append((self.t, env))
        return out

    def _replays(self) -> list[dict]:
        out = []
        for a in self.active_attacks():
            if a.kind != "duplicate_replay" or a.state.get("done"):
                continue
            a.state["done"] = True
            window = float(a.params.get("window_s", 600))
            for fleet in a.targets:
                old = [e for (t, e) in self.replay_buffer.get(fleet, []) if self.t - window <= t]
                for e in old[: int(a.params.get("max", 300))]:
                    out.append(dict(e))  # identical copy: same event_id (gateway dedupe)
                    fresh = dict(e)
                    fresh["event_id"] = str(uuid.UUID(int=int(self.rng.integers(0, 2**63))))
                    out.append(fresh)    # new id, old seq/ts: temporal check must catch it
                    self.truth.label(fresh["event_id"], True, "duplicate_replay", e["source_id"], {})
        return out

    def _warehouse_reading(self, w: str) -> list[dict]:
        attacks = self._attacks_on(w)
        if any(a.kind in ("entity_blackout", "mass_blackout") for a in attacks):
            return []
        levels, true_levels = [], {}
        injector = None
        for s in config.SKUS:
            q = self.inv[(w, s)]
            true_levels[s] = q
            rep = q * (1 + float(self.rng.normal(0, config.INVENTORY_NOISE_FRAC)))
            for a in attacks:
                if a.kind == "inventory_fake" and a.params.get("sku", "SKU-B") == s:
                    rep = q * (1 + float(a.params.get("pct", 0.4)))
                    injector = a.kind
            levels.append({"sku": s, "qty": int(round(max(0.0, rep)))})
        payload: dict = {"node_id": w, "levels": levels,
                         "inbound": {s: int(round(self.flow_in[(w, s)])) for s in config.SKUS},
                         "outbound": {s: int(round(self.flow_out[(w, s)])) for s in config.SKUS},
                         "power_status": "ok"}
        for a in attacks:
            if a.kind == "feed_corrupt":
                injector = a.kind
                mode = int(self.rng.integers(0, 3))
                if mode == 0:
                    payload["levels"] = [{"sku": l["sku"], "qty": str(l["qty"]) + "??"} for l in levels]
                elif mode == 1:
                    payload["levels"] = [{"sku": l["sku"], "qty": l["qty"] * 1000} for l in levels]
                else:
                    payload["levels"] = "\x00corrupt\x00"
        for s in config.SKUS:
            self.flow_in[(w, s)] = 0.0
            self.flow_out[(w, s)] = 0.0
        env = self._env("telemetry.warehouse", w, "warehouse", payload)
        self.truth.label(env["event_id"], injector is not None, injector, w, {"levels": true_levels})
        return [env]

    def _port_reading(self, p: str) -> list[dict]:
        env = self._env("telemetry.port", p, "port",
                        {"node_id": p, "port_congestion": round(float(self.rng.uniform(0.2, 0.5)), 2),
                         "port_status": "open"})
        self.truth.label(env["event_id"], False, None, p, {})
        return [env]

    def _shipment_event(self, v: Vehicle) -> dict:
        env = self._env("telemetry.shipment", f"dispatch-{v.fleet}", "shipment",
                        {"shipment_id": v.shipment_id, "vehicle_id": v.id, "route_links": v.route,
                         "cargo_type": "ambient", "priority": config.PRIORITY_CODE[config.SKU_PRIORITY.get(v.sku, "NORMAL")],
                         "status": "in_transit", "sku": v.sku, "dest": v.dest, "load_units": int(v.load)})
        self.truth.label(env["event_id"], False, None, env["source_id"], {})
        return env

    # ------------------------------------------------------------------ step
    def step(self, dt: float) -> list[dict]:
        """Advance truth by dt sim seconds (in GPS-interval substeps) and return emitted envelopes."""
        out: list[dict] = []
        remaining = dt
        while remaining > 1e-9:
            h = min(config.GPS_INTERVAL_S, remaining)
            remaining -= h
            self.t += h
            for lid in [l for l, b in self.blocks.items() if b["until"] <= self.t]:
                del self.blocks[lid]
            for n in [n for n, until in self.closed_nodes.items() if until <= self.t]:
                del self.closed_nodes[n]
            for v in self.vehicles:
                self._move(v, h)
                if getattr(v, "_pending_shipment", False):
                    v._pending_shipment = False  # type: ignore[attr-defined]
                    out.append(self._shipment_event(v))
                if self.t >= v.next_report:
                    v.next_report += config.GPS_INTERVAL_S
                    out.extend(self._vehicle_reading(v))
            for w in self.warehouses:
                for s in config.SKUS:
                    lam = self.served.get((w, s), 0.0) * h / 86400.0
                    d = float(self.rng.poisson(lam)) if lam > 0 else 0.0
                    served = min(d, self.inv[(w, s)])
                    self.inv[(w, s)] -= served
                    self.flow_out[(w, s)] += served
                    self.unmet[(w, s)] += d - served
                if self.t >= self.next_wh_report[w]:
                    self.next_wh_report[w] += config.WAREHOUSE_INTERVAL_S
                    out.extend(self._warehouse_reading(w))
            for p in self.ports:
                if self.t >= self.next_port_report[p]:
                    self.next_port_report[p] += config.PORT_INTERVAL_S
                    out.extend(self._port_reading(p))
            for a in self.active_attacks():
                if a.kind == "real_blockage" and not a.state.get("alerted"):
                    a.state["alerted"] = True
                    link = self.net.links[a.targets[0]]
                    env = self._env("signal.alert", "alert-feed", "alert",
                                    {"alert_id": a.id, "hazard": "other", "level": "red",
                                     "link_id": link.id, "corridor_id": link.corridor_id,
                                     "text": "Road blocked (scripted scenario)", "data_mode": "MOCK"})
                    self.truth.label(env["event_id"], False, None, "alert-feed", {})
                    out.append(env)
            out.extend(self._replays())
        return out

    # ------------------------------------------------------------------ truth views (eval only)
    def truth_vehicle(self, vid: str) -> Vehicle | None:
        return self._vehicle_by_id.get(vid)
