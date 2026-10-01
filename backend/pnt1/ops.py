"""V2 operational views computed from the twin's *belief* (never from hidden truth):
orders / shipments, sensor fusion, vehicle health and trucks affected by disruptions.
"""
from __future__ import annotations

import math

import numpy as np

from . import config
from .geo import haversine_km, segment_distances_km
from .network import Network
from .weather import level as weather_level
from .twin import Twin, VehicleBelief

PRIORITY_NAME = {v: k for k, v in config.PRIORITY_CODE.items()}
STAGE_OF_TYPE = {"Supplier": "SUPPLIER", "Port": "SUPPLIER", "Factory": "MANUFACTURER", "Warehouse": "WAREHOUSE",
                 "CustomerCluster": "CUSTOMER"}


def orient(net: Network, route: list[str], dest: str) -> list[tuple[str, str, str]]:
    """Route link ids -> [(link, from, to)] in driving order, using the destination to fix direction."""
    out: list[tuple[str, str, str]] = []
    node = dest
    for lid in reversed(route):
        l = net.links[lid]
        if node == l.to:
            out.append((lid, l.frm, l.to))
            node = l.frm
        elif node == l.frm:
            out.append((lid, l.to, l.frm))
            node = l.to
        else:
            return [(x, net.links[x].frm, net.links[x].to) for x in route]    # cannot orient: assume as listed
    return out[::-1]


def position_on_route(net: Network, hops: list[tuple[str, str, str]], lat: float, lon: float) -> tuple[int, float, float]:
    """(leg index, fraction done along the leg in driving direction, off-route km)."""
    segs = []
    for lid, a, b in hops:
        na, nb = net.nodes[a], net.nodes[b]
        segs.append((na.lat, na.lon, nb.lat, nb.lon))
    d = segment_distances_km(lat, lon, np.array(segs, dtype=float))
    i = int(np.argmin(d))
    la1, lo1, la2, lo2 = segs[i]
    kx = 111.32 * math.cos(math.radians(lat))
    ax, ay, bx, by = (lo1 - lon) * kx, (la1 - lat) * 110.57, (lo2 - lon) * kx, (la2 - lat) * 110.57
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / L2)) if L2 > 0 else 0.0
    return i, t, float(d[i])


def in_yard(net: Network, lat: float, lon: float) -> str | None:
    for n in net.nodes.values():
        if haversine_km(lat, lon, n.lat, n.lon) <= config.INF_YARD_RADIUS_KM:
            return n.id
    return None


class Ops:
    def __init__(self, net: Network, twin: Twin):
        self.net, self.twin = net, twin
        self.weather = None
        self.served_by: dict[str, list[str]] = {}
        for l in net.links.values():
            if net.nodes[l.frm].type == "Warehouse" and net.nodes[l.to].type == "CustomerCluster":
                self.served_by.setdefault(l.frm, []).append(l.to)

    # ------------------------------------------------------------------------------------------ orders
    def order(self, v: VehicleBelief, now: float, trust_cls: str, closed_links: set[str], closed_nodes: set[str],
              block_points: dict[str, float] | None = None) -> dict | None:
        if v.lat is None or not v.route or not v.dest or v.dest not in self.net.nodes:
            return None
        units = v.load or v.cargo_units
        hops = orient(self.net, v.route, v.dest)
        leg, frac, off = position_on_route(self.net, hops, v.lat, v.lon)
        lens = [self.net.links[h[0]].dist_km for h in hops]
        times = [self.net.links[h[0]].base_time_h for h in hops]
        rem_km = lens[leg] * (1 - frac) + sum(lens[leg + 1:])
        rem_h = times[leg] * (1 - frac) + sum(times[leg + 1:])
        planned_h = sum(times)
        wx_delay, wx_ahead = 0.0, []
        wf = self.weather
        if wf is not None and wf.available:
            for i, (lid, a, b) in enumerate(hops[leg:], start=leg):
                left = (1 - frac) if i == leg else 1.0
                ahead_h = sum(times[leg:i]) * 1.0
                sev, info = wf.link_sev(lid, ahead_h)
                f = wf.time_factor(lid, ahead_h)
                if f > 1:
                    wx_delay += times[i] * left * (f - 1)
                if sev >= 0.5:
                    wx_ahead.append({"link": lid, "sev": sev, "level": weather_level(sev), "in_h": round(ahead_h, 1),
                                     "text": info.get("text", "")})
            rem_h += wx_delay
        origin = hops[0][1]
        eta_t = now + rem_h * 3600
        planned_eta = (v.dispatch_t + planned_h * 3600) if v.dispatch_t is not None else eta_t
        delay_h = max(0.0, (eta_t - planned_eta) / 3600)
        bp = block_points or {}
        blocked_ahead = []
        for i, (lid, a, b) in enumerate(hops[leg:]):
            if lid not in closed_links and b not in closed_nodes:
                continue
            if i == 0 and lid in bp:
                p = bp[lid] if a == self.net.links[lid].frm else 1.0 - bp[lid]
                if frac >= p - 0.005:
                    continue          # already past the closure point on this leg
            blocked_ahead.append(lid)
        turnaround = bool(blocked_ahead) and blocked_ahead[0] == hops[leg][0]
        yard = in_yard(self.net, v.lat, v.lon)
        stopped_min = (now - v.stopped_since) / 60 if v.stopped_since is not None else 0.0
        age = now - v.t
        if trust_cls == "quarantined" or age > 600:
            status = "UNVERIFIED"
        elif blocked_ahead:
            status = "AT_RISK"
        elif stopped_min > 10 and not yard:
            status = "STOPPED"
        elif delay_h > 0.5:
            status = "DELAYED"
        elif yard == v.dest:
            status = "ARRIVING"
        elif yard == origin and stopped_min > 0:
            status = "LOADING"
        else:
            status = "IN_TRANSIT"
        pr = PRIORITY_NAME.get(v.priority, "NORMAL")
        ot, dt = self.net.nodes[origin].type, self.net.nodes[v.dest].type
        kind = "transfer" if ot == "Warehouse" and dt == "Warehouse" else "inbound" if dt == "Warehouse" else "reposition"
        customers = self.served_by.get(v.dest, [])
        next_step = (f"Unload at {v.dest}; replenishes {v.sku} for {', '.join(customers) or 'the hub'}" if units
                     else f"Pick up at {v.dest}")
        if wx_ahead and status in ("IN_TRANSIT", "DELAYED"):
            w0 = wx_ahead[0]
            next_step = f"{w0['level'].title()} weather on {w0['link']} in ~{w0['in_h']:g} h (real forecast): expect +{wx_delay:.1f} h; consider an earlier reroute"
        if status == "AT_RISK":
            next_step = f"Route blocked at {blocked_ahead[0]}: reroute needs operator approval"
        return {"id": v.shipment_id[:8].upper() if v.shipment_id else v.id, "shipment_id": v.shipment_id,
                "vehicle": v.id, "fleet": v.fleet, "sku": v.sku, "sku_class": config.SKU_CLASS.get(v.sku, ""),
                "priority": pr, "units": units, "value_inr": units * config.UNIT_VALUE_INR.get(v.sku, 0.0),
                "origin": origin, "origin_type": ot, "destination": v.dest, "dest_type": dt, "kind": kind,
                "customers": customers, "lat": v.lat, "lon": v.lon, "speed": v.speed_kmh,
                "leg": leg, "legs": len(hops), "current_link": hops[leg][0], "route": [h[0] for h in hops],
                "route_nodes": [hops[0][1]] + [h[2] for h in hops],
                "weather_delay_h": round(wx_delay, 2), "weather_ahead": wx_ahead, "remaining_km": round(rem_km, 1), "remaining_h": round(rem_h, 2), "eta_t": eta_t,
                "planned_eta_t": planned_eta, "delay_h": round(delay_h, 2), "status": status,
                "blocked_ahead": blocked_ahead, "turnaround_needed": turnaround, "stopped_min": round(stopped_min), "reroutes": v.reroutes,
                "responsible": v.dest if status not in ("LOADING",) else origin, "next_step": next_step,
                "stage": "TRANSPORT", "origin_stage": STAGE_OF_TYPE.get(ot, "SUPPLIER"),
                "trust": trust_cls, "age_s": round(age), "data_mode": "SIMULATED"}

    def orders(self, now: float, cls_of, closed_links: set[str], closed_nodes: set[str], loaded_only: bool = True,
               block_points: dict[str, float] | None = None) -> list[dict]:
        out = []
        for v in self.twin.vehicles.values():
            if loaded_only and not (v.load or v.cargo_units):
                continue
            o = self.order(v, now, cls_of(v.id), closed_links, closed_nodes, block_points)
            if o:
                out.append(o)
        rank = {"AT_RISK": 0, "UNVERIFIED": 1, "STOPPED": 2, "DELAYED": 3}
        out.sort(key=lambda o: (rank.get(o["status"], 9), config.PRIORITY_CODE[o["priority"]], -o["delay_h"]))
        return out

    # ------------------------------------------------------------------------------------------ health
    def health(self, v: VehicleBelief, e, now: float) -> dict:
        reasons, parts = [], {}
        fuel = v.fuel
        if fuel is None:
            parts["fuel"] = None
        else:
            parts["fuel"] = 1.0 if fuel < 15 else max(0.0, (30 - fuel) / 15)
            if fuel < 30:
                reasons.append(f"fuel {fuel:.0f}%")
        rate = (e.anomalies / max(20, e.readings)) if e else 0.0
        parts["anomalies"] = min(1.0, rate * 8)
        if e and e.anomalies:
            reasons.append(f"{e.anomalies} anomalous readings of {e.readings}")
        kin = (e.checks or {}).get("kinematic", 1.0) if e else 1.0
        parts["movement"] = max(0.0, min(1.0, (0.9 - kin) / 0.6)) if kin < 0.9 else 0.0
        if kin < 0.9:
            reasons.append(f"abnormal movement (kinematic check {kin:.2f})")
        stop_min = (now - v.stopped_since) / 60 if v.stopped_since is not None else 0.0
        parts["stops"] = min(1.0, max(0.0, (stop_min - 45) / 120)) if not in_yard(self.net, v.lat, v.lon) else 0.0
        if parts["stops"] > 0:
            reasons.append(f"unplanned stop {stop_min:.0f} min")
        tau = e.tau if e else config.INITIAL_TRUST
        parts["trust"] = max(0.0, 1.0 - tau)
        w = {"fuel": 0.3, "anomalies": 0.25, "movement": 0.15, "stops": 0.15, "trust": 0.15}
        risk = sum(w[k] * (parts[k] or 0.0) for k in w)
        tier = "HIGH" if risk >= 0.45 else "ELEVATED" if risk >= 0.2 else "LOW"
        return {"vehicle": v.id, "risk": round(risk, 3), "tier": tier, "reasons": reasons, "parts": parts,
                "fuel_pct": fuel, "temperature": None,
                "unavailable": ["engine temperature (not in the telemetry feed)", "tyre pressure (not in feed)"],
                "method": "heuristic from available telemetry (fuel, anomaly rate, movement, stops, trust)"}

    # ------------------------------------------------------------------------------------------ sensor fusion
    def fusion(self, v: VehicleBelief, e, now: float, inference_events: dict, alerts_on) -> dict:
        checks = (e.checks if e else {}) or {}
        src = []

        def add(key, label, conf, detail, available=True):
            src.append({"key": key, "label": label, "available": available,
                        "confidence": round(conf, 3) if (available and conf is not None) else None, "detail": detail})
        quarantined = e is not None and e.cls == "quarantined"
        g = [checks[k] for k in ("physics", "kinematic") if k in checks]
        add("gps", "GPS position", (sum(g) / len(g)) if g else None,
            "physics + motion consistency of the reported fix" + (" · reading quarantined, last trusted fix used" if quarantined else ""),
            bool(g))
        t = [checks[k] for k in ("schema", "temporal") if k in checks]
        add("telemetry", "Fleet telemetry", (sum(t) / len(t)) if t else None, "message complete, fresh and in sequence", bool(t))
        r = [checks[k] for k in ("road", "route") if k in checks]
        add("road", "Road network", (sum(r) / len(r)) if r else None, "on a mapped road and on the assigned route", bool(r))
        # nearby trusted vehicles: do they tell the same story?
        me_stopped = v.speed_kmh < config.INF_STOP_SPEED
        agree = n = 0
        for o in self.twin.vehicles.values():
            if o.id == v.id or o.lat is None or now - o.t > 300:
                continue
            if haversine_km(v.lat, v.lon, o.lat, o.lon) > 3.0:
                continue
            n += 1
            agree += int((o.speed_kmh < config.INF_STOP_SPEED) == me_stopped)
        add("nearby", "Nearby vehicles", (agree / n) if n else None,
            f"{agree} of {n} trusted vehicles within 3 km agree ({'stopped' if me_stopped else 'moving'})" if n
            else "no other vehicle within 3 km", n > 0)
        wf = self.weather
        if wf is not None and wf.available and v.lat is not None:
            pid, dkm = wf.nearest(v.lat, v.lon)
            sev, info = wf.point_sev(pid)
            add("weather", "Weather", None,
                f"{wf.status()} · {info.get('text') or 'clear'}, rain {info.get('precip_mm_h', 0)} mm/h, gusts {info.get('gust_kmh', 0)} km/h "
                f"at the nearest grid point ({dkm:.0f} km) → {weather_level(sev).lower()}" + (" · slows trucks, raises delay risk" if sev >= 0.25 else ""))
        else:
            add("weather", "Weather", None, "unavailable: weather feed not reachable (nothing is invented)", False)
        if v.route:
            cus = e.cusum if e else 0.0
            add("history", "Route history", max(0.0, 1.0 - cus / config.CUSUM_H2), f"drift CUSUM {cus:.2f} (quarantine cap at {config.CUSUM_H2})")
        else:
            add("history", "Route history", None, "no assigned route yet", False)
        alerts = alerts_on(v)
        inf = next((ev for ev in inference_events.values() if v.id in ev.get("vehicles", [])), None)
        if alerts or inf:
            parts = []
            if alerts:
                parts.append(f"alert on {alerts[0]} (MOCK feed)")
            if inf:
                parts.append(f"inference: {inf['link_id']} {inf['status'].replace('_', ' ')} ({inf['confidence']:.2f})")
            add("observations", "Trusted observations", 0.9 if (alerts and me_stopped) or (inf and inf["status"] == "blocked_inferred") else 0.6,
                "; ".join(parts))
        else:
            add("observations", "Trusted observations", None, "no alerts or inferred events on this vehicle's road", False)
        W = {"gps": 0.25, "telemetry": 0.15, "road": 0.2, "nearby": 0.2, "history": 0.1, "observations": 0.1}
        av = [s for s in src if s["available"] and s["confidence"] is not None]
        wsum = sum(W[s["key"]] for s in av)
        conf = sum(W[s["key"]] * s["confidence"] for s in av) / wsum if wsum else 0.0
        yard = in_yard(self.net, v.lat, v.lon) if v.lat is not None else None
        stopped_min = (now - v.stopped_since) / 60 if v.stopped_since is not None else 0.0
        if quarantined:
            state, why = "POSITION UNVERIFIED", "latest readings failed the Trust Engine; showing the last trusted state"
            conf *= 0.5
        elif me_stopped and yard:
            state, why = "AT FACILITY", f"stopped inside the {yard} yard (loading / unloading)"
        elif me_stopped and stopped_min >= 10 and (inf or alerts or (n and agree / n >= 0.6)):
            state, why = "HELD BY ROAD DISRUPTION", "stopped on the road and independent signals agree"
        elif me_stopped and stopped_min >= 10:
            state, why = "UNEXPLAINED STOP", "stopped on the road with no corroborating signal"
            conf *= 0.8
        elif me_stopped:
            state, why = "STOPPED", "short stop"
        else:
            state, why = "MOVING", f"{v.speed_kmh:.0f} km/h on its assigned route"
            if wf is not None and wf.available and v.lat is not None and wf.point_sev(wf.nearest(v.lat, v.lon)[0])[0] >= 0.5:
                why += " · severe weather nearby (real forecast)"
        return {"vehicle": v.id, "sources": src, "fused_state": state, "confidence": round(conf, 3), "why": why,
                "tau": round(e.tau, 3) if e else None, "cls": e.cls if e else None,
                "method": "weighted fusion of the Trust Engine check scores, neighbour agreement and trusted observations; "
                          "unavailable sources are excluded, never invented"}
