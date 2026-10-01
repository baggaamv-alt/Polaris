"""Digital twin state (C05): the system's *belief*. Only trusted/estimated readings are applied here."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import config
from .network import Network

START = datetime.fromisoformat(config.SIM_START_ISO)


def sim_seconds(ts: datetime) -> float:
    return (ts - START).total_seconds()


def fleet_of(vehicle_id: str) -> str:
    parts = vehicle_id.split("-")
    return f"FLEET-{parts[1]}" if len(parts) >= 3 else "FLEET-?"


@dataclass
class VehicleBelief:
    id: str
    fleet: str
    lat: float | None = None
    lon: float | None = None
    t: float = -1e9               # sim time of last applied (trusted/estimated) reading
    speed_kmh: float = 0.0
    heading: float = 0.0
    load: int = 0
    shipment_id: str = ""
    route: list[str] = field(default_factory=list)
    route_version: int = 0
    stopped_since: float | None = None
    last_seen_t: float = -1e9      # last reading of any kind (for freshness we use t)
    widened: bool = False
    # V2: shipment context (from dispatch events) and extra telemetry fields
    fuel: float | None = None
    sku: str = ""
    dest: str = ""
    priority: int = 3
    cargo_units: int = 0
    dispatch_t: float | None = None
    reroutes: int = 0


@dataclass
class InventoryBelief:
    reported: int = 0
    verified: float = 0.0
    confidence: float = 1.0
    conf_class: str = "verified"
    t: float = -1e9


class Twin:
    def __init__(self, net: Network):
        self.net = net
        self.vehicles: dict[str, VehicleBelief] = {}
        self.inventory: dict[tuple[str, str], InventoryBelief] = {}
        self.warehouse_t: dict[str, float] = {}
        self.port_t: dict[str, float] = {}
        self.port_status: dict[str, dict] = {}
        self.link_status: dict[str, dict] = {lid: {"status": "open", "confidence": 1.0, "source": ""}
                                              for lid in net.links}
        self.alerts_by_link: dict[str, dict] = {}
        self.writes = 0   # count of state writes (tests use this to prove quarantine never writes)

    # ---------------------------------------------------------------- vehicles
    def vehicle(self, vid: str) -> VehicleBelief:
        v = self.vehicles.get(vid)
        if v is None:
            v = self.vehicles[vid] = VehicleBelief(id=vid, fleet=fleet_of(vid))
        return v

    def apply_vehicle(self, vid: str, t: float, p: dict, widened: bool) -> None:
        v = self.vehicle(vid)
        v.lat, v.lon, v.t = float(p["lat"]), float(p["lon"]), t
        v.speed_kmh = float(p["speed_kmh"])
        v.heading = float(p.get("heading_deg", v.heading) or 0.0)
        v.load = int(p.get("load_units", v.load) or 0)
        v.shipment_id = str(p.get("shipment_id", v.shipment_id) or "")
        f = p.get("fuel_pct")
        if isinstance(f, (int, float)) and not isinstance(f, bool):
            v.fuel = float(f)
        v.widened = widened
        if v.speed_kmh < config.INF_STOP_SPEED:
            if v.stopped_since is None:
                v.stopped_since = t
        else:
            v.stopped_since = None
        self.writes += 1

    def apply_shipment(self, p: dict, t: float | None = None) -> None:
        vid = str(p.get("vehicle_id", ""))
        route = [r for r in p.get("route_links", []) if r in self.net.links] if isinstance(p.get("route_links"), list) else []
        if not vid or not route:
            return
        v = self.vehicle(vid)
        sid = str(p.get("shipment_id", ""))
        if sid == v.shipment_id and v.dispatch_t is not None:
            v.reroutes += 1                      # same shipment, new route: an approved reroute
        else:
            v.dispatch_t = t
            v.reroutes = 0
        v.route, v.shipment_id = route, sid
        v.sku = str(p.get("sku", "") or "")
        v.dest = str(p.get("dest", "") or "")
        pr = p.get("priority", 3)
        v.priority = int(pr) if isinstance(pr, int) and not isinstance(pr, bool) else 3
        lu = p.get("load_units")
        if isinstance(lu, int) and not isinstance(lu, bool):
            v.cargo_units = lu
        v.route_version += 1
        self.writes += 1

    def position_uncertainty_km(self, v: VehicleBelief, now: float) -> float:
        if v.lat is None:
            return 0.0
        age_h = max(0.0, now - v.t) / 3600.0
        return 0.05 + 45.0 * age_h

    # ---------------------------------------------------------------- warehouses
    def apply_inventory(self, node: str, t: float, levels: dict[str, int], verified: dict[str, float],
                        confidence: float, conf_class: str) -> None:
        for s, q in levels.items():
            b = self.inventory.setdefault((node, s), InventoryBelief())
            b.reported, b.verified, b.confidence, b.conf_class, b.t = int(q), float(verified[s]), confidence, conf_class, t
        self.warehouse_t[node] = t
        self.writes += 1

    def apply_port(self, node: str, t: float, p: dict) -> None:
        self.port_t[node] = t
        self.port_status[node] = {"status": p.get("port_status", "open"), "congestion": p.get("port_congestion")}
        self.writes += 1

    def apply_alert(self, t: float, p: dict) -> None:
        lid = p.get("link_id")
        if lid in self.net.links:
            self.alerts_by_link[lid] = {"t": t, "level": p.get("level"), "text": p.get("text"),
                                        "data_mode": p.get("data_mode", "MOCK"), "until": t + 3 * 3600}
        self.writes += 1

    def active_alert(self, lid: str, now: float) -> dict | None:
        a = self.alerts_by_link.get(lid)
        return a if a and a["until"] > now else None

    def usable_inventory(self, trust_of) -> dict[tuple[str, str], float]:
        """Trust-discounted inventory for the optimizer.

        `verified` is already flow-reconciled (it ignores counts from untrusted readings). On top of that:
        trusted feed -> full value; estimated -> x tau; quarantined -> x 0.5 (flow-only estimate, no
        confirming count). The 0.5 is a first guess, see docs/DECISIONS.md.
        """
        out = {}
        for (n, s), b in self.inventory.items():
            tau = trust_of(f"wh:{n}")
            if tau >= config.TRUSTED_MIN:
                d = 1.0
            elif tau >= config.QUARANTINE_BELOW:
                d = tau
            else:
                d = 0.5
            out[(n, s)] = b.verified * d
        return out

    def raw_inventory(self) -> dict[tuple[str, str], float]:
        """What the feeds *claim* (used only for the raw-vs-trusted comparison)."""
        return {k: float(b.reported) for k, b in self.inventory.items()}
