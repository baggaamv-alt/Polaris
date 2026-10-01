"""Weather and hazard data sources (2.4). Everything here talks to public, key-free web services and returns plain
Python structures; nothing is invented. Used by weather.WeatherFeed.

Weather (per point, hourly for about three days)
  1. Open-Meteo forecast API   https://open-meteo.com  (temperature, rain, gusts, wind, humidity, pressure, cloud, visibility, WMO code)
  2. MET Norway Locationforecast https://api.met.no   (automatic fallback when Open-Meteo fails for a chunk of points)
  3. Open-Meteo Marine API     (wave height at ports; optional, never blocks the main feed)
Hazard alerts (region: South Asia)
  USGS earthquakes (M4.5+), NASA EONET open natural events (storms, floods, volcanoes, landslides), GDACS disasters.

Network behaviour: retries with back-off, honours HTTP 429, verifies TLS with the system store and falls back to the
certifi bundle (fixes "CERTIFICATE_VERIFY_FAILED" on Windows / uv-managed Python). Set PNT1_WEATHER_INSECURE_SSL=1 only
as a last resort on a network that re-signs HTTPS traffic.
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

UA = "vigilax-pnt1/2.4 (logistics resilience research project; contact: vigilax@example.org)"
OM_FORECAST = "https://api.open-meteo.com/v1/forecast"
OM_MARINE = "https://marine-api.open-meteo.com/v1/marine"
METNO = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
USGS = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
EONET = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=10&category=severeStorms,floods,volcanoes,landslides"
GDACS = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP"
REGION = {"lat0": 0.0, "lat1": 40.0, "lon0": 60.0, "lon1": 100.0}          # South Asia

OM_CUR = "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,cloud_cover,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
OM_HOUR = "temperature_2m,relative_humidity_2m,precipitation,precipitation_probability,weather_code,wind_gusts_10m,visibility"
OM_CUR_MIN = "temperature_2m,precipitation,wind_gusts_10m,weather_code"
OM_HOUR_MIN = "precipitation,wind_gusts_10m,weather_code"


# ------------------------------------------------------------------------------------------------ HTTP
def _contexts() -> list[ssl.SSLContext | None]:
    out: list[ssl.SSLContext | None] = [None]
    try:
        import certifi  # type: ignore
        out.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:  # noqa: BLE001
        pass
    if os.environ.get("PNT1_WEATHER_INSECURE_SSL") == "1":
        out.append(ssl._create_unverified_context())  # noqa: S323 - explicit opt-in for re-signing proxies
    return out


class FetchError(Exception):
    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind, self.status = kind, status


def classify(e: BaseException) -> tuple[str, str, str]:
    """(kind, short message, what to do) for a network failure."""
    if isinstance(e, FetchError):
        kind, msg = e.kind, str(e)
    elif isinstance(e, urllib.error.HTTPError):
        kind, msg = f"http_{e.code}", f"HTTP {e.code} {e.reason}"
    else:
        reason = getattr(e, "reason", e)
        if isinstance(reason, ssl.SSLError) or "CERTIFICATE" in str(reason).upper():
            kind, msg = "ssl", f"TLS certificate check failed ({str(reason)[:80]})"
        elif isinstance(reason, socket.gaierror) or "getaddrinfo" in str(reason) or "Name or service" in str(reason):
            kind, msg = "dns", "DNS lookup failed (no internet or blocked)"
        elif isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason):
            kind, msg = "timeout", "request timed out"
        elif "403" in str(reason) or "Tunnel" in str(reason) or "proxy" in str(reason).lower():
            kind, msg = "proxy", f"blocked by a proxy or firewall ({str(reason)[:80]})"
        else:
            kind, msg = "other", f"{type(e).__name__}: {str(reason)[:100]}"
    hint = {
        "ssl": "Install certifi (`uv add certifi`) or set PNT1_WEATHER_INSECURE_SSL=1 if a proxy re-signs HTTPS.",
        "dns": "Check the internet connection, DNS and VPN. The weather hosts must be reachable from the machine running the server.",
        "timeout": "The connection is slow or filtered. The feed retries automatically.",
        "proxy": "Allow api.open-meteo.com, api.met.no and the hazard hosts through the proxy/firewall, or set HTTPS_PROXY.",
        "http_429": "Rate limited by the provider. The feed backs off and retries; the next provider is used meanwhile.",
    }.get(kind, "See the error text; the feed retries automatically.")
    return kind, msg, hint


def _rewrite(url: str) -> str:
    """PNT1_WEATHER_MIRROR=http://host:port sends every request to a local mirror at /<original-host>/<path> (offline labs, tests)."""
    base = os.environ.get("PNT1_WEATHER_MIRROR")
    if not base:
        return url
    u = urllib.parse.urlparse(url)
    return f"{base.rstrip('/')}/{u.netloc}{u.path}" + (f"?{u.query}" if u.query else "")


def http_json(url: str, timeout: float = 30.0, retries: int = 3, headers: dict | None = None) -> list | dict:
    url = _rewrite(url)
    hdr = {"User-Agent": UA, "Accept": "application/json"}
    hdr.update(headers or {})
    last: BaseException | None = None
    for attempt in range(retries):
        for ctx in _contexts():
            try:
                req = urllib.request.Request(url, headers=hdr)
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:   # noqa: S310 - fixed https hosts
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 429:
                    time.sleep(min(20.0, float(e.headers.get("Retry-After", 2 + attempt * 3))))
                    break
                if 400 <= e.code < 500:
                    raise
                break
            except (ssl.SSLError, urllib.error.URLError, OSError) as e:
                last = e
                if "CERTIFICATE" in str(e).upper() or isinstance(getattr(e, "reason", None), ssl.SSLError):
                    continue          # try the next TLS context
                break
        time.sleep(0.6 * (attempt + 1))
    assert last is not None
    raise last


# ------------------------------------------------------------------------------------------------ WMO mapping for MET Norway
def symbol_to_wmo(sym: str | None) -> int:
    s = (sym or "").split("_")[0].lower()
    thunder = "thunder" in s
    heavy = s.startswith("heavy")
    if thunder:
        return 99 if heavy else 95
    if s in ("clearsky",):
        return 0
    if s == "fair":
        return 1
    if s == "partlycloudy":
        return 2
    if s == "cloudy":
        return 3
    if "fog" in s:
        return 45
    if "snow" in s:
        return 75 if heavy else 73 if "light" not in s else 71
    if "sleet" in s:
        return 67 if heavy else 66
    if "rain" in s or "shower" in s:
        if "shower" in s:
            return 82 if heavy else 80
        return 65 if heavy else 61 if s.startswith("light") else 63
    return 3


# ------------------------------------------------------------------------------------------------ Open-Meteo forecast
def _num(v, default=0.0):
    return default if v is None else v


def parse_openmeteo(r: dict, hours: int = 72) -> dict:
    cur = r.get("current") or {}
    h = r.get("hourly") or {}
    times = h.get("time") or []
    start = 0
    ct = cur.get("time")
    if ct and times:
        hour = ct[:13]
        start = next((i for i, t in enumerate(times) if t[:13] >= hour), 0)

    def col(name):
        return h.get(name) or []

    pr, gu, co, te, vi, rh, pp = (col(k) for k in ("precipitation", "wind_gusts_10m", "weather_code", "temperature_2m",
                                                   "visibility", "relative_humidity_2m", "precipitation_probability"))
    n = min(len(pr), len(gu), len(co))
    idx = range(start, min(n, start + hours))
    hourly = [(_num(pr[i]), _num(gu[i]), int(_num(co[i]))) for i in idx]

    def at(a, i, default=None):
        return a[i] if i < len(a) and a[i] is not None else default

    temps = [at(te, i) for i in idx]
    if not hourly and cur:                      # current-only response: nothing to forecast from
        pass
    now = (_num(cur.get("precipitation")), _num(cur.get("wind_gusts_10m")), int(_num(cur.get("weather_code"))))
    if not cur and hourly:
        now = hourly[0]
    extra = {"apparent_c": cur.get("apparent_temperature"), "humidity": cur.get("relative_humidity_2m", at(rh, start)),
             "pressure_hpa": cur.get("pressure_msl"), "cloud_pct": cur.get("cloud_cover"), "wind_kmh": cur.get("wind_speed_10m"),
             "wind_dir": cur.get("wind_direction_10m"), "visibility_m": at(vi, start)}
    return {"now": now, "temp": cur.get("temperature_2m", at(te, start)), "hourly": hourly, "temps": temps,
            "vis": [at(vi, i) for i in idx], "hum": [at(rh, i) for i in idx], "pop": [at(pp, i) for i in idx],
            "extra": {k: v for k, v in extra.items() if v is not None}}


def fetch_openmeteo(points: list[tuple[str, float, float]], fetcher: Callable[[str], list | dict], hours: int = 72) -> dict[str, dict]:
    """points: [(id, lat, lon)]. Returns {id: parsed}. Raises if the request fails."""
    def one(cur, hour):
        q = {"latitude": ",".join(f"{p[1]:.3f}" for p in points), "longitude": ",".join(f"{p[2]:.3f}" for p in points),
             "current": cur, "hourly": hour, "forecast_days": 4, "timezone": "UTC", "wind_speed_unit": "kmh"}
        return fetcher(OM_FORECAST + "?" + urllib.parse.urlencode(q, safe=","))
    try:
        res = one(OM_CUR, OM_HOUR)
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise
        res = one(OM_CUR_MIN, OM_HOUR_MIN)      # a variable was rejected: use the core set
    res = res if isinstance(res, list) else [res]
    if isinstance(res[0], dict) and res[0].get("error"):
        raise FetchError("http_400", str(res[0].get("reason", "error from Open-Meteo")))
    if len(res) != len(points):
        raise FetchError("other", f"Open-Meteo returned {len(res)} locations for {len(points)} requested")
    return {p[0]: parse_openmeteo(r, hours) for p, r in zip(points, res)}


# ------------------------------------------------------------------------------------------------ MET Norway
def parse_metno(r: dict, hours: int = 72) -> dict:
    ts = (r.get("properties") or {}).get("timeseries") or []
    if not ts:
        raise FetchError("other", "MET Norway returned no time series")
    rows = []
    for e in ts:
        d = (e.get("data") or {})
        ins = (d.get("instant") or {}).get("details") or {}
        n1 = d.get("next_1_hours") or d.get("next_6_hours") or {}
        span = 1 if d.get("next_1_hours") else 6
        pa = ((n1.get("details") or {}).get("precipitation_amount"))
        sym = (n1.get("summary") or {}).get("symbol_code")
        rows.append((e["time"], ins, (pa or 0.0) / span, sym, span))
    hourly, temps, vis, hum = [], [], [], []
    for t, ins, rate, sym, span in rows:
        ws = ins.get("wind_speed", 0.0) * 3.6
        gust = ins.get("wind_speed_of_gust")
        gust = gust * 3.6 if gust is not None else ws * 1.5
        for _ in range(span):
            hourly.append((rate, gust, symbol_to_wmo(sym)))
            temps.append(ins.get("air_temperature"))
            fog = ins.get("fog_area_fraction")
            vis.append(200.0 if fog is not None and fog > 80 else None)
            hum.append(ins.get("relative_humidity"))
    hourly, temps, vis, hum = hourly[:hours], temps[:hours], vis[:hours], hum[:hours]
    ins0 = rows[0][1]
    extra = {"humidity": ins0.get("relative_humidity"), "pressure_hpa": ins0.get("air_pressure_at_sea_level"),
             "cloud_pct": ins0.get("cloud_area_fraction"), "wind_kmh": (ins0.get("wind_speed") or 0) * 3.6 if ins0.get("wind_speed") is not None else None,
             "wind_dir": ins0.get("wind_from_direction")}
    return {"now": hourly[0], "temp": temps[0], "hourly": hourly, "temps": temps, "vis": vis, "hum": hum, "pop": [None] * len(hourly),
            "extra": {k: v for k, v in extra.items() if v is not None}}


def fetch_metno(points: list[tuple[str, float, float]], fetcher: Callable[[str], list | dict], hours: int = 72) -> dict[str, dict]:
    def one(p):
        time.sleep(0.03)
        return p[0], parse_metno(fetcher(f"{METNO}?lat={p[1]:.4f}&lon={p[2]:.4f}"), hours)
    with ThreadPoolExecutor(max_workers=6) as ex:
        return dict(ex.map(one, points))


# ------------------------------------------------------------------------------------------------ marine (ports)
def fetch_marine(points: list[tuple[str, float, float]], fetcher: Callable[[str], list | dict], hours: int = 72) -> dict[str, dict]:
    if not points:
        return {}
    q = {"latitude": ",".join(f"{p[1]:.3f}" for p in points), "longitude": ",".join(f"{p[2]:.3f}" for p in points),
         "current": "wave_height,wave_period", "hourly": "wave_height", "forecast_days": 4, "timezone": "UTC"}
    res = fetcher(OM_MARINE + "?" + urllib.parse.urlencode(q, safe=","))
    res = res if isinstance(res, list) else [res]
    out = {}
    for p, r in zip(points, res):
        h = (r.get("hourly") or {}).get("wave_height") or []
        now = (r.get("current") or {}).get("wave_height")
        if now is None and not any(v is not None for v in h):
            continue                                    # inland / no marine grid cell
        ct = (r.get("current") or {}).get("time")
        times = (r.get("hourly") or {}).get("time") or []
        start = next((i for i, t in enumerate(times) if ct and t[:13] >= ct[:13]), 0)
        out[p[0]] = {"now": now if now is not None else h[start], "hourly": [v or 0.0 for v in h[start:start + hours]],
                     "period": (r.get("current") or {}).get("wave_period")}
    return out


# ------------------------------------------------------------------------------------------------ hazard alerts
def _in_region(lat, lon) -> bool:
    return lat is not None and lon is not None and REGION["lat0"] <= lat <= REGION["lat1"] and REGION["lon0"] <= lon <= REGION["lon1"]


def parse_usgs(d: dict) -> list[dict]:
    out = []
    for f in d.get("features", []):
        lon, lat = (f.get("geometry") or {}).get("coordinates", [None, None])[:2]
        p = f.get("properties") or {}
        if not _in_region(lat, lon) or p.get("mag") is None:
            continue
        m = p["mag"]
        out.append({"source": "USGS", "type": "earthquake", "title": f"M{m:.1f} earthquake · {p.get('place', '')}", "lat": lat, "lon": lon,
                    "sev": 0.8 if m >= 6 else 0.55 if m >= 5.5 else 0.3, "radius_km": 150 if m >= 6 else 80, "time": (p.get("time") or 0) / 1000,
                    "url": p.get("url")})
    return out


def parse_eonet(d: dict) -> list[dict]:
    out = []
    for e in d.get("events", []):
        geo = (e.get("geometry") or [])
        g = next((x for x in reversed(geo) if x.get("type") == "Point"), None)
        if not g:
            continue
        lon, lat = g["coordinates"][:2]
        if not _in_region(lat, lon):
            continue
        cat = ((e.get("categories") or [{}])[0].get("id") or "event")
        out.append({"source": "NASA EONET", "type": {"severeStorms": "storm", "floods": "flood", "volcanoes": "volcano", "landslides": "landslide"}.get(cat, cat),
                    "title": e.get("title", "natural event"), "lat": lat, "lon": lon, "sev": 0.5 if cat in ("severeStorms", "floods") else 0.35,
                    "radius_km": 300 if cat == "severeStorms" else 120, "time": _iso(g.get("date")), "url": (e.get("sources") or [{}])[0].get("url") or e.get("link")})
    return out


def parse_gdacs(d: dict) -> list[dict]:
    out = []
    for f in d.get("features", []):
        p = f.get("properties") or {}
        geo = f.get("geometry") or {}
        if geo.get("type") == "Point":
            lon, lat = geo["coordinates"][:2]
        else:
            continue
        if not _in_region(lat, lon):
            continue
        lvl = str(p.get("alertlevel", "")).lower()
        et = {"TC": "cyclone", "FL": "flood", "EQ": "earthquake", "VO": "volcano", "DR": "drought", "WF": "wildfire"}.get(p.get("eventtype"), str(p.get("eventtype", "event")).lower())
        out.append({"source": "GDACS", "type": et, "title": f"{p.get('name') or p.get('eventname') or et} ({lvl or 'alert'} alert)", "lat": lat, "lon": lon,
                    "sev": {"red": 0.9, "orange": 0.6}.get(lvl, 0.3), "radius_km": 400 if et == "cyclone" else 150, "time": _iso(p.get("fromdate")),
                    "url": ((p.get("url") or {}).get("details") if isinstance(p.get("url"), dict) else p.get("url"))})
    return out


def _iso(s) -> float | None:
    if not s:
        return None
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except Exception:  # noqa: BLE001
        return None


ALERT_SOURCES = [("USGS", USGS, parse_usgs), ("NASA EONET", EONET, parse_eonet), ("GDACS", GDACS, parse_gdacs)]


def fetch_alerts(fetcher: Callable[[str], list | dict]) -> tuple[list[dict], dict]:
    """Returns (alerts, status per source). One failing source never hides the others."""
    alerts, status = [], {}
    for name, url, parse in ALERT_SOURCES:
        t0 = time.time()
        try:
            got = parse(fetcher(url))
            alerts += got
            status[name] = {"ok": True, "count": len(got), "ms": round((time.time() - t0) * 1000)}
        except Exception as e:  # noqa: BLE001
            k, m, h = classify(e)
            status[name] = {"ok": False, "kind": k, "error": m, "hint": h}
    alerts.sort(key=lambda a: -a["sev"])
    return alerts, status


# ------------------------------------------------------------------------------------------------ diagnostics
def diagnose(fetcher: Callable[[str], list | dict] | None = None) -> dict:
    f = fetcher or (lambda u: http_json(u, timeout=8.0, retries=1))
    tests = [("Open-Meteo forecast", OM_FORECAST + "?latitude=17.4&longitude=78.5&current=temperature_2m&timezone=UTC"),
             ("Open-Meteo marine", OM_MARINE + "?latitude=15&longitude=72&current=wave_height"),
             ("MET Norway", METNO.replace("/complete", "/compact") + "?lat=17.4&lon=78.5"),
             ("USGS earthquakes", USGS), ("NASA EONET", EONET), ("GDACS", GDACS)]
    out = []
    for name, url in tests:
        t0 = time.time()
        try:
            f(url)
            out.append({"name": name, "host": urllib.parse.urlparse(url).netloc, "ok": True, "ms": round((time.time() - t0) * 1000)})
        except Exception as e:  # noqa: BLE001
            k, m, h = classify(e)
            out.append({"name": name, "host": urllib.parse.urlparse(url).netloc, "ok": False, "kind": k, "error": m, "hint": h})
    try:
        import certifi  # type: ignore
        cert = certifi.where()
    except Exception:  # noqa: BLE001
        cert = None
    return {"results": out, "environment": {"python": sys.version.split()[0], "openssl": ssl.OPENSSL_VERSION, "certifi": bool(cert),
            "proxy_env": sorted(k for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy") if os.environ.get(k)),
            "insecure_ssl": os.environ.get("PNT1_WEATHER_INSECURE_SSL") == "1"}}
