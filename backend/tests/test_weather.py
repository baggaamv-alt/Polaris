from pathlib import Path

from pnt1.network import Network
from pnt1.runtime import Runtime
from pnt1.weather import WeatherFeed, level, severity

FIX = str(Path(__file__).parent / "fixtures" / "weather_fixture.json")


def test_severity_and_levels():
    assert severity(0, 10, 0) < 0.1
    assert severity(9, 20, 65) >= 0.6
    assert severity(0, 100, 0) >= 0.7
    assert severity(0, 0, 99) >= 0.8
    assert level(0.1) == "CALM" and level(0.55) == "SEVERE" and level(0.9) == "EXTREME"


def test_unavailable_is_neutral():
    w = WeatherFeed(Network(), fetcher=lambda u: (_ for _ in ()).throw(OSError("blocked")))
    assert w.refresh() is False
    assert w.status() == "UNAVAILABLE" and w.error
    assert w.link_sev("L003") == (0.0, {}) and w.cells() == []


def test_off_mode():
    w = WeatherFeed(Network(), mode="off")
    assert w.refresh() is False and w.status() == "UNAVAILABLE"


def test_live_parse_with_injected_fetcher():
    def fetch(url):
        n = url.split("latitude=")[1].split("&")[0].count(",") + 1
        one = {"current": {"time": "2026-10-01T05:00", "precipitation": 12.0, "wind_gusts_10m": 70, "weather_code": 95},
               "hourly": {"time": [f"2026-10-01T{h:02d}:00" for h in range(24)], "precipitation": [1.0] * 24,
                          "wind_gusts_10m": [30] * 24, "weather_code": [3] * 24}}
        return [one] * n
    w = WeatherFeed(Network(), fetcher=fetch)
    assert w.refresh() and w.status() == "LIVE"
    assert w.node_sev("W-BOM") >= 0.6
    assert w.node_sev("W-BOM", 6) < 0.3                      # forecast hour 6: calmer
    assert len(w.data["W-BOM"]["hourly"]) == 19              # starts at the current hour (05:00)


def test_fixture_replay_is_labelled_replay_not_live():
    w = WeatherFeed(Network(), mode=f"fixture:{FIX}")
    assert w.refresh() and w.status() == "REPLAY"
    assert "not live" in w.meta()["note"].lower()


def test_weather_flows_into_risk_eta_resilience_and_fusion(monkeypatch):
    monkeypatch.setenv("PNT1_WEATHER", f"fixture:{FIX}")
    rt = Runtime()
    for _ in range(40):
        rt.tick(30.0)
    assert rt.weather.refresh()
    _, _, _, state = rt.closed_state()
    wx = [s["wx"] for s in state.values() if "wx" in s]
    assert wx and all(w["risk"] > 0 and w["tmult"] > 1 for w in wx)
    res = rt.resilience.compute(rt)
    assert "weather_exposure" in res["components"]
    assert abs(sum(c["weight"] for c in res["components"].values()) - 1.0) < 0.01
    orders, _, _ = rt._orders()
    assert any(o["weather_delay_h"] > 0 for o in orders)
    view = rt.weather_view()
    assert view["meta"]["status"] == "REPLAY" and view["hazards"] and view["chain"]
    v = next(iter(rt.twin.vehicles.values()))
    fu = rt.ops.fusion(v, rt.trust.entities.get(v.id), rt.world.t, {}, lambda t: [])
    w = next(s for s in fu["sources"] if s["key"] == "weather")
    assert w["available"] and "REPLAY" in w["detail"]


def test_without_weather_index_uses_eight_components(monkeypatch):
    monkeypatch.setenv("PNT1_WEATHER", "off")
    rt = Runtime()
    rt.tick(30.0)
    res = rt.resilience.compute(rt)
    assert "weather_exposure" not in res["components"]
    assert abs(sum(c["weight"] for c in res["components"].values()) - 1.0) < 0.01
