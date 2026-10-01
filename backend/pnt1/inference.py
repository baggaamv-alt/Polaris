"""Blockage inference from telemetry (C17, F-93) with the adversarial guard (F-94).

Only trusted readings count; the quorum is trust-weighted; BLOCKED_INFERRED needs independent
corroboration (a second fleet or an alert); contradicting traffic lowers confidence and flags reporters.
"""
from __future__ import annotations

import math

import numpy as np

from . import config
from .geo import haversine_km, segment_distances_km
from .network import Network
from .trust import TrustEngine
from .twin import Twin


class BlockageInference:
    def __init__(self, net: Network, twin: Twin, trust: TrustEngine):
        self.net, self.twin, self.trust = net, twin, trust
        self.events: dict[str, dict] = {}     # link_id -> active inferred event
        self.log: list[dict] = []
        self._nid = 0

    def _in_yard(self, lat: float, lon: float) -> bool:
        return any(haversine_km(lat, lon, n.lat, n.lon) <= config.INF_YARD_RADIUS_KM for n in self.net.nodes.values())

    def _link_of(self, v) -> str | None:
        """The road the truck is physically on (nearest road within 0.5 km), independent of its assigned route."""
        if v.lat is None:
            return None
        d = segment_distances_km(v.lat, v.lon, self.net.road_segs)
        i = int(np.argmin(d))
        if d[i] >= 0.5:
            return None
        return self._canonical(self.net.road_ids[i])

    def _canonical(self, lid: str) -> str:
        """One id per physical road: opposite-direction links with the same geometry and corridor share it."""
        if not hasattr(self, "_canon"):
            self._canon = {}
            for l in self.net.road_ids:
                a = self.net.links[l]
                key = (a.corridor_id, frozenset({(a.seg[0], a.seg[1]), (a.seg[2], a.seg[3])}))
                self._canon.setdefault(key, []).append(l)
            self._canon = {l: min(ls) for ls in self._canon.values() for l in ls}
        return self._canon.get(lid, lid)

    def tick(self, now: float) -> list[dict]:
        """Returns new/updated inference events (for alerts + audit)."""
        by_link: dict[str, list] = {}
        moving: dict[str, list] = {}
        for v in self.twin.vehicles.values():
            if v.lat is None or now - v.t > 300:
                continue
            e = self.trust.entities.get(v.id)
            if not e or e.tau < config.TRUSTED_MIN:
                continue
            lid = self._link_of(v)
            if lid is None:
                continue
            if self._in_yard(v.lat, v.lon):
                continue      # loading / unloading at a facility is a normal stop, not a blockage
            if v.stopped_since is not None and now - v.stopped_since >= config.INF_MIN_STOP_S:
                by_link.setdefault(lid, []).append((v, e.tau))
            elif v.speed_kmh > config.INF_MOVING_SPEED:
                moving.setdefault(lid, []).append((v, e.tau))
        out = []
        seen = set()
        for lid, members in by_link.items():
            if len(members) < config.INF_MIN_VEHICLES:
                continue
            lat_m = float(np.median([m[0].lat for m in members]))
            lon_m = float(np.median([m[0].lon for m in members]))
            cluster = [m for m in members if haversine_km(lat_m, lon_m, m[0].lat, m[0].lon) <= config.INF_RADIUS_KM]
            if len(cluster) < config.INF_MIN_VEHICLES:
                continue
            seen.add(lid)
            # contradiction only counts traffic moving *through* the claimed blockage point
            through = [m for m in moving.get(lid, [])
                       if haversine_km(lat_m, lon_m, m[0].lat, m[0].lon) <= config.INF_RADIUS_KM * 1.5]
            ev = self._evaluate(lid, cluster, through, now)
            prev = self.events.get(lid)
            if prev is None or prev["status"] != ev["status"] or abs(prev["confidence"] - ev["confidence"]) > 0.05:
                if prev:
                    ev["id"] = prev["id"]
                self.events[lid] = ev
                out.append(ev)
        for lid in [l for l in self.events if l not in seen]:
            ev = self.events.pop(lid)
            ev = dict(ev, status="open", resolved_at=now)
            self._set_link(lid, "open", 1.0)
            self.log.append(ev)
            out.append(ev)
        return out

    def _evaluate(self, lid: str, cluster: list, movers: list, now: float) -> dict:
        taus = sum(t for _, t in cluster)
        q = min(1.0, taus / config.INF_QUORUM)
        fleets = sorted({v.fleet for v, _ in cluster})
        indep = min(1.0, len(fleets) / config.INF_K_INDEPENDENT)
        alert = self.twin.active_alert(lid, now)
        corro = 0.9 if alert else 0.0
        mover_tau = sum(t for v, t in movers if v.id not in {c.id for c, _ in cluster})
        x = mover_tau / (mover_tau + taus) if (mover_tau + taus) > 0 else 0.0
        conf = q * (0.4 + 0.6 * max(indep, corro)) * (1 - x)
        corroborated = corro > 0 or indep >= 1.0
        if conf >= config.INF_CONF_BLOCK and corroborated:
            status = "blocked_inferred"
        elif conf >= config.INF_CONF_SUSPECT:
            status = "suspected"
        else:
            status = "open"
        flagged = x > config.INF_X_FLAG
        if flagged:
            for v, _ in cluster:
                self.trust.entity(v.id, "vehicle").context_flag_until = now + 900
        if status != "open":
            self._set_link(lid, status, conf)
        self._nid += 1
        ev = {"id": f"inf-{self._nid:04d}", "link_id": lid, "status": status, "confidence": round(conf, 3),
              "quorum": round(q, 3), "fleets": fleets, "independence": round(indep, 2),
              "corroboration": corro, "contradiction": round(x, 3), "n_vehicles": len(cluster),
              "vehicles": [v.id for v, _ in cluster], "alert": alert["text"] if alert else None,
              "alert_mode": alert["data_mode"] if alert else None, "needs_human": status == "suspected",
              "coordinated_anomaly": flagged, "t": now}
        self.log.append(ev)
        return ev

    def _set_link(self, lid: str, status: str, conf: float) -> None:
        self.twin.link_status[lid] = {"status": status, "confidence": round(conf, 3), "source": "inference"}
