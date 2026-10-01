"""Core behaviour tests (docs/01_SRS.md section 6 IDs in brackets)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta

import pytest
from hypothesis import given, settings, strategies as st

from pnt1 import config
from pnt1.audit import AuditLog
from pnt1.graph import blast_radius, fragility
from pnt1.ingest import Bus, Envelope, Gateway
from pnt1.network import Network, warehouse_served_demand
from pnt1.planning import solve_plan
from pnt1.trust import TrustEngine
from pnt1.twin import START, Twin
from pnt1.world import World

NET = Network()


def env(vid: str, seq: int, t: float, lat: float, lon: float, speed: float, **extra) -> Envelope:
    payload = {"lat": lat, "lon": lon, "speed_kmh": speed, "heading_deg": 90.0, "load_units": 10, "fuel_pct": 80.0,
               "shipment_id": "s1", **extra}
    return Envelope(event_id=str(uuid.uuid4()), event_type="telemetry.vehicle", source_id=vid, source_type="vehicle",
                    ts_event=START + timedelta(seconds=t), seq=seq, payload=payload)


def on_link(link_id: str, frac: float) -> tuple[float, float]:
    a, b, c, d = NET.links[link_id].seg
    return a + (c - a) * frac, b + (d - b) * frac


def engine():
    twin = Twin(NET)
    return twin, TrustEngine(NET, twin)


def drive(trust, vid, n, start_t=0.0, start_seq=1, link="L053", f0=0.10):
    """n consistent readings 15 s apart at ~55 km/h along a link."""
    L = NET.links[link].dist_km
    t = start_t
    for i in range(n):
        f = f0 + (55.0 * (t / 3600.0)) / L
        lat, lon = on_link(link, f)
        trust.process(env(vid, start_seq + i, t, lat, lon, 55.0), t)
        t += 15.0
    return t, start_seq + n


def test_seed_network_shape():                       # TS-TWIN-01
    assert len(NET.nodes) == 40 and len(NET.links) == 92


def test_normal_truck_trusted():                     # TS-TRUST-01
    twin, trust = engine()
    drive(trust, "truck-A-001", 20)
    e = trust.entities["truck-A-001"]
    assert e.cls == "trusted" and e.tau >= 0.8


def test_teleport_hard_cap_and_quarantine():         # TS-TRUST-02 (worked example B)
    twin, trust = engine()
    t, seq = drive(trust, "truck-A-002", 10)
    v = trust.process(env("truck-A-002", seq, t, 15.0, 70.0, 62.0), t)
    assert v.hard and v.rho == pytest.approx(config.HARD_CAP)
    assert v.cls == "quarantined" and v.action == "quarantine"


def test_speed_spike_capped_even_if_average_looks_ok():   # worked example: avg alone would be 'estimated'
    twin, trust = engine()
    t, seq = drive(trust, "truck-A-003", 10)
    L = NET.links["L053"].dist_km
    lat, lon = on_link("L053", 0.10 + 55.0 * (t / 3600.0) / L)
    v = trust.process(env("truck-A-003", seq, t, lat, lon, 812.0), t)
    assert v.checks["physics"] == 0.0 and v.hard and v.rho <= config.HARD_CAP
    assert v.cls == "quarantined"


def test_quarantine_never_writes_twin():              # TS-TRUST-07
    twin, trust = engine()
    t, seq = drive(trust, "truck-A-004", 10)
    before = (twin.vehicles["truck-A-004"].lat, twin.vehicles["truck-A-004"].lon)
    writes = twin.writes
    trust.process(env("truck-A-004", seq, t, 15.0, 70.0, 62.0), t)
    assert twin.writes == writes
    assert (twin.vehicles["truck-A-004"].lat, twin.vehicles["truck-A-004"].lon) == before


def test_one_good_reading_does_not_restore_trust():  # TS-TRUST-06 (cooldown)
    twin, trust = engine()
    t, seq = drive(trust, "truck-A-005", 10)
    trust.process(env("truck-A-005", seq, t, 15.0, 70.0, 62.0), t)
    drive(trust, "truck-A-005", 3, start_t=t + 15, start_seq=seq + 1, f0=0.10 + 55.0 * (t / 3600.0) / NET.links["L053"].dist_km)
    assert trust.entities["truck-A-005"].cls == "quarantined"


def test_replayed_seq_is_dropped():                  # BM-07 behaviour
    twin, trust = engine()
    t, seq = drive(trust, "truck-A-006", 5)
    lat, lon = on_link("L053", 0.1)
    v = trust.process(env("truck-A-006", 2, t, lat, lon, 55.0), t)
    assert v.action == "replay_dropped"


def test_missing_required_field_is_graceful():       # F-10 incomplete payloads
    twin, trust = engine()
    t, seq = drive(trust, "truck-A-007", 5)
    e = env("truck-A-007", seq, t, 17.0, 78.5, 55.0)
    e.payload.pop("lat")
    v = trust.process(e, t)
    assert v.action == "incomplete" and trust.entities["truck-A-007"].cls != "quarantined"


@settings(max_examples=400, deadline=None)
@given(st.one_of(st.binary(max_size=2048), st.text(max_size=2048),
                 st.recursive(st.none() | st.booleans() | st.floats(allow_nan=True) | st.integers() | st.text(max_size=40),
                              lambda c: st.lists(c, max_size=5) | st.dictionaries(st.text(max_size=12), c, max_size=6),
                              max_leaves=30)))
def test_fuzz_gateway_and_trust_never_crash(raw):    # TS-FUZZ-01 (reduced budget in CI)
    bus = Bus()
    gw = Gateway(bus)
    twin, trust = engine()
    assert gw.ingest(raw) in ("accepted", "duplicate", "dlq")
    for e in bus.drain():
        trust.process(e, 0.0)


@settings(max_examples=300, deadline=None)
@given(st.dictionaries(st.sampled_from(["lat", "lon", "speed_kmh", "heading_deg", "levels", "qty", "node_id"]),
                       st.one_of(st.none(), st.floats(allow_nan=True, allow_infinity=True), st.text(max_size=8),
                                 st.integers(), st.lists(st.dictionaries(st.text(max_size=4), st.integers(), max_size=3), max_size=3)),
                       max_size=7),
       st.sampled_from(["telemetry.vehicle", "telemetry.warehouse"]))
def test_fuzz_mutated_payloads(payload, et):         # valid envelope, hostile payload
    twin, trust = engine()
    e = Envelope(event_id=str(uuid.uuid4()), event_type=et, source_id="W-HYD" if "warehouse" in et else "truck-B-001",
                 source_type="warehouse" if "warehouse" in et else "vehicle", ts_event=START, seq=1, payload=payload)
    trust.process(e, 0.0)


def test_vga_is_single_point_for_vtz():              # TS-GRAPH-01
    f = fragility(NET)
    vga = next(c for c in f["critical_nodes"] if c["node"] == "W-VGA")
    assert "C-VTZ" in vga["single_point_for"]
    assert "C-VTZ" in blast_radius(NET, "W-VGA")["customers_cut_off_if_failed"]


def test_lp_respects_link_capacity():                # TS-OPT-01
    init = {k: d * 3 for k, d in warehouse_served_demand(NET).items()}
    p = solve_plan(NET, init, [], "balanced")
    assert p.status == "optimal"
    per = {}
    for (lid, s, t), q in p.flows.items():
        per[(lid, t)] = per.get((lid, t), 0.0) + q
    for (lid, t), q in per.items():
        assert q <= NET.links[lid].capacity_units_day * config.PERIOD_H / 24.0 + 1e-6


def test_audit_chain_detects_tampering():            # TS-DEC-02
    a = AuditLog(":memory:")
    for i in range(5):
        a.append("decision", "tester", {"i": i}, float(i))
    assert a.verify()["ok"]
    a.db.execute("UPDATE audit_log SET body = ? WHERE seq = 3", (json.dumps({"i": 99}),))
    assert a.verify() == {"ok": False, "broken_at": 3, "entries": 5}


def test_world_is_deterministic():                   # TS-WORLD-04
    def digest():
        w = World(NET, seed=123)
        h = hashlib.sha256()
        for _ in range(20):
            for e in w.step(15):
                h.update(json.dumps(e, sort_keys=True).encode())
        return h.hexdigest()
    assert digest() == digest()


def test_labels_never_in_envelopes():                # TS-WORLD-06
    w = World(NET, seed=5)
    w.inject("speed_spike", [w.vehicles[0].id])
    for _ in range(8):
        for e in w.step(15):
            s = json.dumps(e)
            assert "is_attacked" not in s and "injector" not in s and "true_value" not in s
            Envelope.model_validate(e)
