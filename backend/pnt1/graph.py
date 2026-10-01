"""Graph analytics (C06, F-32, F-50): fragility audit and blast radius on the seed network."""
from __future__ import annotations

import networkx as nx

from .network import Network

SOURCE_TYPES = ("Supplier", "Port", "Factory")


def _simple(net: Network, exclude_nodes: set[str] | None = None) -> nx.DiGraph:
    g = nx.DiGraph()
    ex = exclude_nodes or set()
    for n in net.nodes:
        if n not in ex:
            g.add_node(n)
    for l in net.links.values():
        if l.frm in ex or l.to in ex:
            continue
        cap = g[l.frm][l.to]["capacity"] + l.capacity_units_day if g.has_edge(l.frm, l.to) else l.capacity_units_day
        g.add_edge(l.frm, l.to, capacity=cap)
    return g


def fragility(net: Network) -> dict:
    g = _simple(net)
    sources = [n.id for n in net.nodes.values() if n.type in SOURCE_TYPES]
    customers = [n.id for n in net.of_type("CustomerCluster")]
    hubs = [n.id for n in net.nodes.values() if n.type in ("Warehouse", "Port", "Factory")]
    global_ap = sorted(nx.articulation_points(g.to_undirected()))
    # per-customer critical nodes: removing the node disconnects every source from that customer
    critical_for: dict[str, list[str]] = {}
    for h in hubs:
        gh = _simple(net, {h})
        cut = []
        for c in customers:
            if not any(s in gh and nx.has_path(gh, s, c) for s in sources if s != h):
                cut.append(c)
        if cut:
            critical_for[h] = cut
    bc = nx.betweenness_centrality(g, normalized=True)
    ranked = sorted(hubs, key=lambda n: (-len(critical_for.get(n, [])), -bc.get(n, 0.0)))
    report = []
    for n in ranked:
        why = []
        if critical_for.get(n):
            why.append(f"only path to {', '.join(critical_for[n])}")
        if n in global_ap:
            why.append("articulation point")
        why.append(f"betweenness {bc.get(n, 0):.2f}")
        report.append({"node": n, "name": net.nodes[n].name, "single_point_for": critical_for.get(n, []),
                       "articulation_point": n in global_ap, "betweenness": round(bc.get(n, 0.0), 3),
                       "why": "; ".join(why)})
    # min-cut from all sources to each customer
    mincuts = []
    gs = g.copy()
    gs.add_node("__SRC__")
    for s in sources:
        gs.add_edge("__SRC__", s, capacity=10**9)
    for c in customers:
        val, (reach, _) = nx.minimum_cut(gs, "__SRC__", c, capacity="capacity")
        cut_edges = [(u, v) for u in reach for v in gs.successors(u) if v not in reach]
        mincuts.append({"customer": c, "min_cut_capacity_per_day": int(val),
                        "cut_edges": [f"{u}->{v}" for u, v in cut_edges if u != "__SRC__"][:6]})
    mincuts.sort(key=lambda m: m["min_cut_capacity_per_day"])
    return {"critical_nodes": report[:10], "articulation_points": global_ap, "weakest_min_cuts": mincuts[:5]}


def blast_radius(net: Network, node: str) -> dict:
    g = _simple(net)
    if node not in g:
        return {"error": "unknown node"}
    direct = sorted(g.successors(node))
    desc = nx.descendants(g, node)
    indirect = sorted(desc - set(direct))
    sources = [n.id for n in net.nodes.values() if n.type in SOURCE_TYPES and n.id != node]
    gh = _simple(net, {node})
    cut_off = sorted(c.id for c in net.of_type("CustomerCluster")
                     if not any(nx.has_path(gh, s, c.id) for s in sources if s in gh))
    return {"node": node, "direct": direct, "indirect": indirect,
            "customers_in_reach": sorted(d for d in desc if net.nodes[d].type == "CustomerCluster"),
            "customers_cut_off_if_failed": cut_off}
