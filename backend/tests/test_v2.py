"""V2 behaviour tests: cost engine, route planner, resilience index, self-healing reroute, fusion, scenario extras."""
from __future__ import annotations

import pytest

from pnt1 import config
from pnt1.costing import Hop, RoutePlanner, leg_cost, route_metrics
from pnt1.network import Network
from pnt1.planning import Disruption, solve_plan, weights_from_priorities
from pnt1.runtime import Runtime

NET = Network()
PL = RoutePlanner(NET)


@pytest.fixture(scope="module")
def warm_rt():
    rt = Runtime()
    for _ in range(40):
        rt.tick(15)
    return rt


# ------------------------------------------------------------------ cost engine
def test_road_cost_components_add_up():
    l = NET.links["L053"]
    c = leg_cost(NET, Hop("L053", False, l.frm, l.to, "road"), 40)
    assert c["total_cost"] == pytest.approx(c["energy_cost"] + c["tolls"] + c["operating"] + c["maintenance"])
    assert c["tolls"] > 0 and c["energy_unit"] == "L diesel" and c["trucks"] == 1
    assert leg_cost(NET, Hop("L053", False, l.frm, l.to, "road"), 41)["trucks"] == 2


def test_rail_has_no_tolls_and_terminal_handling_is_charged():
    l = NET.links["L071"]
    m = route_metrics(NET, [Hop("L071", False, l.frm, l.to, "rail")], 40)
    assert m["tolls"] == 0
    assert len(m["transfers"]) == 2 and m["handling"] > 0          # origin loading + destination unloading
    assert m["co2_kg"] == pytest.approx(l.co2_kg_per_unit * 40)    # same carbon factors as the LP


# ------------------------------------------------------------------ route planner
def test_weights_change_the_recommendation_with_an_explanation():
    money = PL.plan("W-HYD", "W-VGA", weights={"money": 1})
    carbon = PL.plan("W-HYD", "W-VGA", weights={"carbon": 1}, prev_weights={"money": 1})
    by = {r["id"]: r for r in carbon["routes"]}
    assert money["recommended"] != carbon["recommended"]
    assert "rail" in by[carbon["recommended"]]["modes"]
    assert carbon["change"]["changed"] and carbon["change"]["driver"] == "carbon"
    assert "CO₂" in carbon["change"]["text"]


def test_display_set_is_independent_of_weights():
    a = {r["id"] for r in PL.plan("P-JNP", "W-DEL", weights={"money": 1})["routes"]}
    b = {r["id"] for r in PL.plan("P-JNP", "W-DEL", weights={"time": 1})["routes"]}
    assert a == b and len(a) >= 3


def test_closed_road_is_avoided_in_both_directions():
    res = PL.plan("W-HYD", "W-VGA", closed_links={"L053"}, road_only=True)
    used = {h[0] for r in res["routes"] for h in r["hops"]}
    assert not used & {"L053", "L054"}


def test_critical_priority_deadline_rules_out_slow_routes():
    res = PL.plan("W-HYD", "W-VGA", closed_links={"L053"}, road_only=True, priority="CRITICAL")
    best = next(r for r in res["routes"] if r["id"] == res["recommended"])
    assert best["sla_ok"] and any(not r["sla_ok"] for r in res["routes"])


# ------------------------------------------------------------------ LP extension
def test_lp_default_path_unchanged_and_custom_weights_solve():
    inv = {}
    a = solve_plan(NET, inv, [], "balanced")
    b = solve_plan(NET, inv, [], "balanced", weights=None)
    assert a.objective == pytest.approx(b.objective)
    w = weights_from_priorities({"money": 0.4, "time": 0.25, "fuel": 0.15, "carbon": 0.1, "distance": 0.1})
    c = solve_plan(NET, inv, [Disruption("link_closure", "L053", 0, 24)], weights=w)
    assert c.status in ("optimal", "feasible_timeout")


def test_scenario_returns_monte_carlo_and_plan_diff(warm_rt):
    from pnt1.strategies import evaluate_scenario
    res = evaluate_scenario(NET, warm_rt.engine, warm_rt.planning_inventory(), Disruption("warehouse_failure", "W-VGA", 4, 24),
                            0.5, runs=60)
    assert res["runs"] == 60
    assert sum(res["monte_carlo"]["cost_hist"]["do_nothing"]) == 60
    assert "transfers" in res["plan_diff"] and "link_flows" in res["frames"]["do_nothing"]


# ------------------------------------------------------------------ resilience + incidents + reroute
def test_resilience_index_moves_with_incidents():
    rt = Runtime()
    for _ in range(40):
        rt.tick(15)
    base = rt.resilience.compute(rt)
    assert 0 <= base["index"] <= 100 and len(base["components"]) == 8
    inc = rt.open_incident("warehouse_failure", "W-VGA", 12)
    hit = rt.resilience.compute(rt)
    assert hit["index"] < base["index"]
    assert hit["components"]["warehouse_capacity"]["score"] < base["components"]["warehouse_capacity"]["score"]
    assert rt.resilience.changes and rt.resilience.changes[0]["drivers"]
    rt.resolve_incident(inc["id"])
    back = rt.resilience.compute(rt)
    assert back["components"]["warehouse_capacity"]["score"] == pytest.approx(base["components"]["warehouse_capacity"]["score"], abs=0.02)


def test_self_healing_reroute_moves_the_truck_off_the_closure():
    rt = Runtime()
    for _ in range(40):
        rt.tick(15)
    rt.open_incident("link_closure", "L053", 6)
    for _ in range(4):
        rt.tick(15)
    aff = rt.affected_trucks()
    assert aff
    vid = aff[0]["vehicle"]
    opts = rt.recovery_options(vid, {"time": 1})
    best = next(r for r in opts["routes"] if r["id"] == opts["recommended"])
    rec = rt.approve_reroute(vid, best["hops"], best["id"], "test", "")
    truth = rt.world.truth_vehicle(vid)
    assert not set(truth.route[1:]) & {"L053", "L054"}
    assert rt.audit.get(rec["audit_seq"])["entry_type"] == "reroute_approved"
    for _ in range(20):
        rt.tick(15)
    assert rt.trust.entities[vid].cls == "trusted"               # the reroute is real, so telemetry stays consistent
    assert vid not in {o["vehicle"] for o in rt.affected_trucks()}


def test_facility_incident_stops_dispatch_to_it():
    rt = Runtime()
    for _ in range(20):
        rt.tick(15)
    t0 = rt.world.t
    rt.open_incident("warehouse_failure", "W-VGA", 12)
    for _ in range(240):
        rt.tick(15)
    new_to_vga = [v for v in rt.twin.vehicles.values() if v.dispatch_t is not None and v.dispatch_t > t0 + 60
                  and v.dest == "W-VGA"]
    assert not new_to_vga
    assert rt.snapshot()["node_state"]["W-VGA"] == "critical"


def test_fusion_never_invents_weather(warm_rt):
    vid = next(iter(warm_rt.twin.vehicles))
    f = warm_rt.ops.fusion(warm_rt.twin.vehicles[vid], warm_rt.trust.entities.get(vid), warm_rt.world.t, {}, lambda v: [])
    w = next(s for s in f["sources"] if s["key"] == "weather")
    assert not w["available"] and w["confidence"] is None
    assert 0 <= f["confidence"] <= 1 and f["fused_state"]


def test_orders_come_from_belief_with_priority_from_sku(warm_rt):
    orders, _, _ = warm_rt._orders()
    assert orders
    for o in orders[:20]:
        assert o["priority"] == config.SKU_PRIORITY[o["sku"]]
        assert o["remaining_km"] >= 0 and o["destination"] in NET.nodes


def test_scheduled_incident_activates_later():
    rt = Runtime()
    inc = rt.open_incident("link_closure", "L053", 2, start_in_h=0.25)
    assert inc["status"] == "scheduled" and not rt.world.blocks
    for _ in range(70):               # 17.5 sim minutes
        rt.tick(15)
    assert inc["status"] == "active" and "L053" in rt.world.blocks
    assert rt.snapshot()["incidents"][0]["id"] == inc["id"]
