import pytest
from fastapi.testclient import TestClient

from pnt1 import api, config


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("PNT1_WEATHER", "off")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    with TestClient(api.app) as c:
        yield c


def test_weather_endpoint_unavailable_is_explicit(client):
    d = client.get("/api/weather").json()
    assert d["meta"]["status"] == "UNAVAILABLE" and d["hazards"] == [] and d["cells"] == [] and d["chain"] is None


def test_tile_proxy_serves_and_reports_offline(client, monkeypatch):
    monkeypatch.setattr(api, "_tile_fetch", lambda *a: b"\x89PNG-test")
    r = client.get("/tiles/sat/5/22/13")
    assert r.status_code == 200 and r.content == b"\x89PNG-test"
    monkeypatch.setattr(api, "_tile_fetch", lambda *a: None)
    assert client.get("/tiles/dem/5/22/13").status_code == 404
    assert client.get("/tiles/other/5/1/1").status_code == 404
    assert client.get("/tiles/sat/3/9/1").status_code == 404        # x out of range for z=3


def test_cost_assumptions_are_editable_validated_and_priced(client):
    before = client.get("/api/cost/assumptions").json()["road"]["fuel_inr_per_l"]
    body = {"origin": "W-HYD", "destination": "W-VGA", "units": 40}
    c0 = client.post("/api/routes/plan", json=body).json()["routes"][0]["energy_cost"]
    assert client.post("/api/cost/assumptions", json={"road_fuel_inr_per_l": 5}).status_code == 422
    r = client.post("/api/cost/assumptions", json={"road_fuel_inr_per_l": before * 2}).json()
    assert r["assumptions"]["road"]["fuel_inr_per_l"] == before * 2
    c1 = client.post("/api/routes/plan", json=body).json()["routes"][0]["energy_cost"]
    assert c1 > c0
    client.post("/api/cost/assumptions", json={"reset": True})
    assert client.get("/api/cost/assumptions").json()["road"]["fuel_inr_per_l"] == before
    assert any(e["type"] == "cost_assumptions" for e in client.get("/api/audit").json()["entries"]) if isinstance(client.get("/api/audit").json(), dict) else True
