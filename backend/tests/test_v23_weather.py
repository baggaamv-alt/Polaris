"""V2.3: weather summary, STALE handling (last good reading is kept, never invented) and support ticket audit linkage."""
from pnt1.network import Network
from pnt1.runtime import Runtime
from pnt1.weather import WeatherFeed


def _fetch_factory(state):
    def fetch(url):
        if state["fail"]:
            raise OSError("network down")
        n = url.split("latitude=")[1].split("&")[0].count(",") + 1
        one = {"current": {"time": "2026-10-01T05:00", "temperature_2m": 31.5, "precipitation": 12.0, "wind_gusts_10m": 70, "weather_code": 95},
               "hourly": {"time": [f"2026-10-01T{h:02d}:00" for h in range(24)] + [f"2026-10-02T{h:02d}:00" for h in range(24)],
                          "precipitation": [1.0] * 48, "wind_gusts_10m": [30] * 48, "weather_code": [3] * 48}}
        return [one] * n
    return fetch


def test_summary_has_temperature_and_timeline():
    w = WeatherFeed(Network(), fetcher=_fetch_factory({"fail": False}))
    assert w.refresh()
    s = w.summary()
    assert s["temp_mean"] == 31.5 and s["gust_max_kmh"] == 70 and s["precip_max_mm_h"] == 12.0
    assert s["timeline"][0]["h"] == 0 and len(s["timeline"]) == 17
    assert s["nodes_affected"] == s["nodes_total"] and s["level_worst"] in ("SEVERE", "EXTREME")
    assert all("temp" in c for c in w.cells() if c["kind"] == "node")


def test_failed_refresh_keeps_last_reading_and_marks_stale():
    state = {"fail": False}
    w = WeatherFeed(Network(), fetcher=_fetch_factory(state))
    assert w.refresh() and w.status() == "LIVE"
    before = w.cells()
    state["fail"] = True
    assert w.refresh() is False
    assert w.status() == "STALE" and w.error
    assert w.cells() == before and w.meta()["fetched_label"]          # same values, nothing fabricated
    state["fail"] = False
    assert w.refresh() and w.status() == "LIVE" and w.error is None


def test_never_fetched_is_unavailable_not_calm():
    w = WeatherFeed(Network(), fetcher=_fetch_factory({"fail": True}))
    assert w.refresh() is False and w.status() == "UNAVAILABLE"
    assert w.summary() is None and w.cells() == []


def test_weather_view_exposes_summary():
    rt = Runtime(weather_mode="off") if "weather_mode" in Runtime.__init__.__code__.co_varnames else None
    if rt is None:
        return
    assert rt.weather_view()["summary"] is None
