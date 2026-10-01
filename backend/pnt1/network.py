"""Seed network: nodes, links, straight-line link geometry, and routing helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import numpy as np
import yaml

from . import config


@dataclass
class Node:
    id: str
    type: str
    name: str
    lat: float
    lon: float
    capacity: int
    primary_sku: str | None = None


@dataclass
class Link:
    id: str
    frm: str
    to: str
    mode: str
    dist_km: float
    base_time_h: float
    capacity_units_day: int
    cost_per_unit: float
    co2_kg_per_unit: float
    corridor_id: str
    seg: tuple[float, float, float, float] = field(default=(0, 0, 0, 0))


class Network:
    """Static topology. Geometry is a straight line between node coordinates (synthetic, documented)."""

    def __init__(self, path: Path = config.SEED_NETWORK):
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        self.version = raw.get("version", 1)
        self.nodes: dict[str, Node] = {}
        for n in raw["nodes"]:
            self.nodes[n["id"]] = Node(n["id"], n["type"], n["name"], float(n["lat"]), float(n["lon"]),
                                       int(n["capacity"]), n.get("primary_sku"))
        self.links: dict[str, Link] = {}
        for l in raw["links"]:
            a, b = self.nodes[l["from"]], self.nodes[l["to"]]
            self.links[l["id"]] = Link(l["id"], l["from"], l["to"], l["mode"], float(l["dist_km"]),
                                       float(l["base_time_h"]), int(l["capacity_units_day"]),
                                       float(l["cost_per_unit"]), float(l["co2_kg_per_unit"]),
                                       str(l["corridor_id"]), (a.lat, a.lon, b.lat, b.lon))
        self.graph = nx.MultiDiGraph()
        for n in self.nodes.values():
            self.graph.add_node(n.id, type=n.type)
        for l in self.links.values():
            self.graph.add_edge(l.frm, l.to, key=l.id, mode=l.mode, base_time_h=l.base_time_h)
        self.road_ids = [l.id for l in self.links.values() if l.mode == "road"]
        self.road_segs = np.array([self.links[i].seg for i in self.road_ids], dtype=float)

    def of_type(self, t: str) -> list[Node]:
        return [n for n in self.nodes.values() if n.type == t]

    def segs(self, link_ids: list[str]) -> np.ndarray:
        return np.array([self.links[i].seg for i in link_ids], dtype=float) if link_ids else np.empty((0, 4))

    def road_route(self, src: str, dst: str, exclude: set[str] | None = None) -> list[str]:
        """Fastest road route as a list of link ids, choosing the best of parallel links."""
        exclude = exclude or set()
        g = nx.DiGraph()
        for l in self.links.values():
            if l.mode != "road" or l.id in exclude:
                continue
            cur = g.get_edge_data(l.frm, l.to)
            if cur is None or l.base_time_h < cur["w"]:
                g.add_edge(l.frm, l.to, w=l.base_time_h, lid=l.id)
        try:
            path = nx.shortest_path(g, src, dst, weight="w")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []
        return [g[u][v]["lid"] for u, v in zip(path, path[1:])]

    def truck_route(self, src: str, dst: str, exclude: set[str] | None = None) -> list[tuple[str, bool]]:
        """Fastest road route for a truck. Roads are two-way: returns (link_id, reversed) hops.

        The seed links are directed supply flows (supplier -> warehouse); a physical road can be driven
        both ways, so trucks may traverse a road link in reverse.
        """
        g = nx.DiGraph()
        exclude = exclude or set()
        for l in self.links.values():
            if l.mode != "road" or l.id in exclude:
                continue
            for u, v, rev in ((l.frm, l.to, False), (l.to, l.frm, True)):
                cur = g.get_edge_data(u, v)
                if cur is None or l.base_time_h < cur["w"] or (l.base_time_h == cur["w"] and not rev):
                    g.add_edge(u, v, w=l.base_time_h, lid=l.id, rev=rev)
        try:
            path = nx.shortest_path(g, src, dst, weight="w")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []
        return [(g[u][v]["lid"], g[u][v]["rev"]) for u, v in zip(path, path[1:])]

    def to_geojson(self) -> dict:
        return {
            "nodes": [{"id": n.id, "type": n.type, "name": n.name, "lat": n.lat, "lon": n.lon,
                       "capacity": n.capacity} for n in self.nodes.values()],
            "links": [{"id": l.id, "from": l.frm, "to": l.to, "mode": l.mode, "corridor": l.corridor_id,
                       "base_time_h": l.base_time_h, "capacity": l.capacity_units_day,
                       "coords": [[l.seg[1], l.seg[0]], [l.seg[3], l.seg[2]]]} for l in self.links.values()],
        }


def customer_demand_per_day(net: Network) -> dict[tuple[str, str], float]:
    return {(c.id, s): config.BASE_DEMAND_PER_SKU_DAY * config.CUSTOMER_SIZE.get(c.id, 0.3)
            for c in net.of_type("CustomerCluster") for s in config.SKUS}


def warehouse_served_demand(net: Network) -> dict[tuple[str, str], float]:
    """Customer demand split equally across the warehouses that serve each customer."""
    dem = customer_demand_per_day(net)
    servers: dict[str, list[str]] = {}
    for l in net.links.values():
        if net.nodes[l.frm].type == "Warehouse" and net.nodes[l.to].type == "CustomerCluster":
            servers.setdefault(l.to, []).append(l.frm)
    out: dict[tuple[str, str], float] = {}
    for (c, s), d in dem.items():
        ws = servers.get(c, [])
        for w in ws:
            out[(w, s)] = out.get((w, s), 0.0) + d / len(ws)
    return out


def supply_per_day(net: Network) -> dict[tuple[str, str], float]:
    """Production / import capacity per node and SKU (units/day)."""
    sup: dict[tuple[str, str], float] = {}
    for n in net.nodes.values():
        if n.type == "Supplier" and n.primary_sku:
            sup[(n.id, n.primary_sku)] = float(n.capacity)
        elif n.type == "Port":
            for s, share in config.PORT_IMPORT_SKUS.items():
                sup[(n.id, s)] = n.capacity * share / 10.0
        elif n.type == "Factory":
            for s in config.FACTORY_OUTPUT_SKUS:
                sup[(n.id, s)] = n.capacity * config.FACTORY_OUTPUT_SHARE
    return sup
