"""2.4: provider parsing, automatic fallback, saved readings, hazard alerts and diagnostics. No network is used."""
import json
import urllib.error

from pnt1 import weather_sources as src
from pnt1.network import Network
from pnt1.weather import WeatherFeed


def om_one(temp=30.0, rain=1.0, gust=30):
    return {"current": {"time": "2026-10-01T05:00", "temperature_2m": temp, "apparent_temperature": temp + 3, "relative_humidity_2m": 70,
                        "precipitation": rain, "weather_code": 3, "cloud_cover": 80, "pressure_msl": 1004, "wind_speed_10m": 14,
                        "wind_direction_10m": 200, "wind_gusts_10m": gust},
            "hourly": {"time": [f"2026-10-0{1 + h // 24}T{h % 24:02d}:00" for h in range(96)], "temperature_2m": [temp] * 96,
                       "relative_humidity_2m": [70] * 96, "precipitation": [rain] * 96, "precipitation_probability": [40] * 96,
                       "weather_code": [3] * 96, "wind_gusts_10m": [gust] * 96, "visibility": [20000] * 96}}


def metno_one():
    ts = []
    for h in range(0, 60):
        ts.append({"time": f"2026-10-01T{h % 24:02d}:00:00Z", "data": {"instant": {"details": {"air_temperature": 27.0, "wind_speed": 12.0,
                    "wind_speed_of_gust": 20.0, "relative_humidity": 85, "air_pressure_at_sea_level": 1001, "cloud_area_fraction": 90}},
                    "next_1_hours": {"summary": {"symbol_code": "heavyrainandthunder"}, "details": {"precipitation_amount": 9.0}}}})
    return {"properties": {"timeseries": ts}}


def test_openmeteo_parse_extras():
    p = src.parse_openmeteo(om_one())
    assert p["temp"] == 30.0 and p["extra"]["humidity"] == 70 and p["extra"]["pressure_hpa"] == 1004
    assert len(p["hourly"]) == 72 and p["vis"][0] == 20000 and p["pop"][0] == 40


def test_metno_parse_and_wmo_mapping():
    p = src.parse_metno(metno_one())
    assert p["now"][0] == 9.0 and round(p["now"][1]) == 72 and p["now"][2] == 99     # heavy rain and thunder, gust 20 m/s
    assert src.symbol_to_wmo("clearsky_day") == 0 and src.symbol_to_wmo("rain") == 63 and src.symbol_to_wmo("fog") == 45


def test_fallback_to_metno_when_openmeteo_fails():
    def fetch(url):
        if "open-meteo" in url:
            raise urllib.error.HTTPError(url, 500, "server error", {}, None)
        if "met.no" in url:
            return metno_one()
        raise OSError("not used")
    w = WeatherFeed(Network(), fetcher=fetch)
    assert w.refresh() and w.status() == "LIVE"
    assert w.provider == "MET Norway" and "Open-Meteo" in w.provider_errors
    assert w.node_sev("W-BOM") >= 0.6


def test_ssl_error_is_classified_with_a_fix():
    import ssl
    k, msg, hint = src.classify(urllib.error.URLError(ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")))
    assert k == "ssl" and "certifi" in hint
    assert src.classify(urllib.error.URLError(OSError("Tunnel connection failed: 403")))[0] == "proxy"


def test_alerts_parsed_and_one_failing_source_does_not_hide_others():
    usgs = {"features": [{"geometry": {"coordinates": [72.8, 19.0, 10]}, "properties": {"mag": 5.6, "place": "near Mumbai", "time": 1790000000000, "url": "u"}},
                         {"geometry": {"coordinates": [-120.0, 35.0, 10]}, "properties": {"mag": 6.1, "place": "California", "time": 1}}]}
    eonet = {"events": [{"title": "Cyclone X", "categories": [{"id": "severeStorms"}], "geometry": [{"type": "Point", "date": "2026-10-01T00:00:00Z", "coordinates": [85.0, 15.0]}], "sources": [{"url": "x"}]}]}

    def fetch(url):
        if "usgs" in url:
            return usgs
        if "eonet" in url:
            return eonet
        raise OSError("gdacs down")
    alerts, status = src.fetch_alerts(fetch)
    assert {a["source"] for a in alerts} == {"USGS", "NASA EONET"} and len(alerts) == 2          # California filtered out
    assert status["GDACS"]["ok"] is False and status["USGS"]["count"] == 1


def test_cache_survives_restart_and_is_stale(tmp_path, monkeypatch):
    path = tmp_path / "wx.json"
    monkeypatch.setenv("PNT1_WEATHER_CACHE", str(path))
    calls = {"n": 0}

    def fetch(url):
        calls["n"] += 1
        n = url.split("latitude=")[1].split("&")[0].count(",") + 1
        return [om_one(rain=12.0, gust=70)] * n
    w = WeatherFeed(Network(), fetcher=fetch)
    w.cache_path = str(path)
    assert w.refresh() and path.exists()
    w2 = WeatherFeed(Network(), fetcher=lambda u: (_ for _ in ()).throw(OSError("offline")))
    w2.cache_path = str(path)
    w2._load_cache()
    assert w2.available and w2.status() == "STALE" and w2.node_sev("W-BOM") >= 0.6


def test_point_detail_and_summary_fields():
    w = WeatherFeed(Network(), fetcher=lambda u: [om_one(rain=12.0, gust=70)] * (u.split("latitude=")[1].split("&")[0].count(",") + 1))
    assert w.refresh()
    d = w.point_detail("W-BOM")
    assert len(d["hourly"]) == 49 and d["now"]["humidity"] == 70 and d["hourly"][5]["temp"] == 30.0
    s = w.summary()
    assert s["humidity_mean"] == 70 and s["pressure_mean"] == 1004


def test_diagnose_reports_each_host():
    d = src.diagnose(lambda u: {} if "usgs" in u else (_ for _ in ()).throw(OSError("blocked")))
    names = {r["name"]: r["ok"] for r in d["results"]}
    assert names["USGS earthquakes"] is True and names["Open-Meteo forecast"] is False and "python" in d["environment"]
