"""Real weather (2.4): Open-Meteo (MET Norway fallback, marine waves at ports, hazard alerts) current conditions + 72 h forecast at every facility and at the midpoint of
every road / rail link, fetched server-side, cached, and turned into a 0..1 severity.

Honesty rules
- status LIVE only when a fetch succeeded recently; STALE when the last good data is older than 3x the refresh
  interval; UNAVAILABLE when nothing was ever fetched (then every effect is neutral: nothing is invented).
- PNT1_WEATHER=off disables it; PNT1_WEATHER=fixture:<file.json> replays a recorded Open-Meteo response and is
  labelled REPLAY, never LIVE.
- The network is synthetic; the weather is the real-world weather at each facility's coordinates. Sim hour +h
  maps to forecast hour +h counted from the real "now".
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable

from . import weather_sources as src
from .geo import haversine_km
from .network import Network

API = "https://api.open-meteo.com/v1/forecast"
CHUNK = 20
HOURS = 72
CODE_TEXT = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog", 51: "light drizzle",
             53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 80: "rain showers",
             81: "heavy showers", 82: "violent showers", 95: "thunderstorm", 96: "thunderstorm, hail", 99: "severe thunderstorm, hail"}


def severity(precip_mm_h: float, gust_kmh: float, code: int, vis_m: float | None = None, wave_m: float | None = None) -> float:
    """0 calm .. 1 extreme, from rain rate, wind gusts and the WMO weather code."""
    def ramp(x, pts):
        if x <= pts[0][0]:
            return pts[0][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x <= x1:
                return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        return pts[-1][1]
    s = max(ramp(precip_mm_h or 0.0, [(0, 0), (2.5, 0.3), (7.6, 0.6), (20, 1.0)]),
            ramp(gust_kmh or 0.0, [(0, 0), (40, 0.05), (60, 0.3), (90, 0.7), (120, 1.0)]))
    if vis_m is not None:
        s = max(s, ramp(-vis_m, [(-100000, 0), (-5000, 0.05), (-1000, 0.3), (-200, 0.6)]) if vis_m < 5000 else 0.0)
    if wave_m is not None:
        s = max(s, ramp(wave_m, [(0, 0), (2, 0.1), (3.5, 0.45), (5, 0.75), (7, 1.0)]))
    code = int(code or 0)
    if code in (95,):
        s = max(s, 0.6)
    elif code in (96, 99):
        s = max(s, 0.8)
    elif code in (45, 48):
        s = max(s, 0.25)
    elif 71 <= code <= 77 or code in (85, 86):
        s = max(s, 0.5)
    return round(min(1.0, s), 3)


def level(s: float) -> str:
    return "EXTREME" if s >= 0.75 else "SEVERE" if s >= 0.5 else "MODERATE" if s >= 0.25 else "CALM"


_http = src.http_json


class WeatherFeed:
    def __init__(self, net: Network, ttl_s: float = 900.0, fetcher: Callable[[str], list | dict] | None = None,
                 mode: str | None = None):
        self.net = net
        self.ttl = ttl_s
        mode = mode if mode is not None else os.environ.get("PNT1_WEATHER", "live")
        self.fixture = mode.split(":", 1)[1] if mode.startswith("fixture:") else None
        self.enabled = mode != "off"
        self.fetcher = fetcher or _http
        self.points: dict[str, tuple[float, float]] = {}
        for n in net.nodes.values():
            self.points[n.id] = (n.lat, n.lon)
        self.mid: dict[str, str] = {}
        seen: dict[tuple, str] = {}
        for l in net.links.values():
            if l.mode == "sea":
                continue
            key = (l.corridor_id, l.mode)
            if key not in seen:
                a, b = net.nodes[l.frm], net.nodes[l.to]
                pid = f"mid:{l.id}"
                self.points[pid] = ((a.lat + b.lat) / 2, (a.lon + b.lon) / 2)
                seen[key] = pid
            self.mid[l.id] = seen[key]
        self.data: dict[str, dict] = {}
        self.fetched_at: float | None = None
        self.error: str | None = None
        self.source = "Open-Meteo" if not self.fixture else "replay file (not live)"
        self.provider = "Open-Meteo" if not self.fixture else "replay file"
        self.provider_errors: dict[str, dict] = {}
        self.marine: dict[str, dict] = {}
        self.alerts: list[dict] = []
        self.alert_status: dict[str, dict] = {}
        self.alerts_at: float | None = None
        self.attempts = 0
        self.last_attempt: float | None = None
        self.cache_path = None if (self.fixture or not self.enabled or fetcher is not None) else os.environ.get("PNT1_WEATHER_CACHE", str(Path(__file__).resolve().parent.parent / "data" / "weather_cache.json"))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._load_cache()

    # ------------------------------------------------------------------------------------------ fetching
    def start(self) -> None:
        if not self.enabled:
            self.error = "disabled (PNT1_WEATHER=off)"
            return
        threading.Thread(target=self._loop, daemon=True, name="weather").start()

    def _loop(self) -> None:
        wait = 30.0
        while not self._stop.is_set():
            ok = self.refresh()
            wait = self.ttl if ok else min(300.0, wait * 1.6 if wait >= 60 else 60.0)
            self._stop.wait(wait)

    # ------------------------------------------------------------------------------------------ cache (real readings survive a restart)
    def _load_cache(self) -> None:
        if not self.cache_path or not os.path.exists(self.cache_path):
            return
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                c = json.load(f)
            if time.time() - c["fetched_at"] > 12 * 3600 or not c.get("data"):
                return
            for v in c["data"].values():
                v["now"] = tuple(v["now"])
                v["hourly"] = [tuple(x) for x in v["hourly"]]
            ok = set(self.points) <= set(c["data"])
            if ok:
                self.data, self.fetched_at = c["data"], c["fetched_at"]
                self.provider = c.get("provider", self.provider)
                self.marine = c.get("marine", {})
                self.error = "restarted: showing the last saved reading until a new fetch succeeds"
        except Exception:  # noqa: BLE001 - a bad cache file must never stop the twin
            pass

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"fetched_at": self.fetched_at, "provider": self.provider, "data": self.data, "marine": self.marine}, f)
            os.replace(tmp, self.cache_path)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------------------------------ fetching
    def _fetch_chunk(self, part: list[str]) -> tuple[dict, str]:
        pts = [(p, self.points[p][0], self.points[p][1]) for p in part]
        errs = {}
        for name, fn in (("Open-Meteo", src.fetch_openmeteo), ("MET Norway", src.fetch_metno)):
            try:
                got = fn(pts, self.fetcher, HOURS)
                if len(got) == len(pts):
                    if errs:
                        self.provider_errors.update(errs)
                    return got, name
                errs[name] = {"kind": "other", "error": f"returned {len(got)} of {len(pts)} points"}
            except Exception as e:  # noqa: BLE001
                k, m, h = src.classify(e)
                errs[name] = {"kind": k, "error": m, "hint": h}
        self.provider_errors.update(errs)
        raise RuntimeError("; ".join(f"{n}: {e['error']}" for n, e in errs.items()))

    def refresh(self) -> bool:
        if not self.enabled:
            return False
        self.attempts += 1
        self.last_attempt = time.time()
        ids = list(self.points)
        ok = False
        try:
            if self.fixture:
                with open(self.fixture, encoding="utf-8") as f:
                    raw = json.load(f)
                results = raw if isinstance(raw, list) else [raw]
                # a recorded response may cover fewer points: repeat the nearest by order
                results = [results[i % len(results)] for i in range(len(ids))]
                new = {pid: self._parse(r) for pid, r in zip(ids, results)}
                used = {"replay file"}
            else:
                self.provider_errors = {}
                new, used = {}, set()
                for i in range(0, len(ids), CHUNK):
                    got, name = self._fetch_chunk(ids[i:i + CHUNK])
                    new.update(got)
                    used.add(name)
                    time.sleep(0.15)
            if not new:
                raise ValueError("empty response")
            with self._lock:
                self.data, self.fetched_at, self.error = new, time.time(), None
                self.provider = " + ".join(sorted(used))
            ok = True
            self._refresh_marine()
            self._save_cache()
        except Exception as e:  # noqa: BLE001 - never let weather break the twin
            self.error = f"{type(e).__name__}: {str(e)[:220]}"
        self._refresh_alerts()
        return ok

    def _refresh_marine(self) -> None:
        if self.fixture:
            return
        ports = [(n.id, n.lat, n.lon) for n in self.net.nodes.values() if n.type == "Port"]
        try:
            self.marine = src.fetch_marine(ports, self.fetcher, HOURS)
        except Exception as e:  # noqa: BLE001 - marine is optional
            self.provider_errors["Open-Meteo marine"] = dict(zip(("kind", "error", "hint"), src.classify(e)))

    def _refresh_alerts(self) -> None:
        if self.fixture:
            return
        if self.alerts_at and time.time() - self.alerts_at < 600 and self.alerts:
            return
        alerts, status = src.fetch_alerts(self.fetcher)
        if alerts or any(v["ok"] for v in status.values()):
            for a in alerts:
                near = []
                for n in self.net.nodes.values():
                    d = haversine_km(a["lat"], a["lon"], n.lat, n.lon)
                    if d <= a["radius_km"] + 100:
                        near.append({"id": n.id, "km": round(d)})
                a["near"] = sorted(near, key=lambda x: x["km"])[:6]
            self.alerts, self.alerts_at = alerts, time.time()
        self.alert_status = status

    def diagnose(self) -> dict:
        d = src.diagnose(self.fetcher if self.fetcher is not src.http_json else None)
        d["mode"] = "fixture" if self.fixture else "off" if not self.enabled else "live"
        d["status"] = self.status()
        d["last_error"] = self.error
        d["attempts"] = self.attempts
        return d

    @staticmethod
    def _parse(r: dict) -> dict:
        return src.parse_openmeteo(r, HOURS)

    # ------------------------------------------------------------------------------------------ network summary
    def summary(self, horizon: int = 48, step: int = 3) -> dict | None:
        """Network-wide headline numbers and a worst-severity forecast timeline, all from the fetched data."""
        if not self.available:
            return None
        nodes = [p for p in self.points if p in self.net.nodes and p in self.data]
        if not nodes:
            return None
        temps = [(self.data[p]["temp"], p) for p in nodes if self.data[p].get("temp") is not None]
        def top(key):
            best = (0.0, None)
            for p in nodes:
                v = self.data[p]["now"][key]
                if v > best[0]:
                    best = (v, p)
            return best
        pr, pr_at = top(0)
        gu, gu_at = top(1)
        sevs = {p: self.point_sev(p)[0] for p in nodes}
        worst_at = max(sevs, key=sevs.get)
        timeline = []
        for h in range(0, horizon + 1, step):
            ss = [(self.point_sev(p, h)[0], p) for p in nodes]
            w = max(ss)
            hp = max(self.point_sev(p, h)[1].get("precip_mm_h", 0.0) for p in nodes)
            timeline.append({"h": h, "sev": round(w[0], 3), "at": w[1], "level": level(w[0]), "affected": sum(1 for x, _ in ss if x >= 0.25), "precip_mm_h": round(hp, 1)})
        ext = [(self.data[p].get("extra") or {}) for p in nodes]
        def avg(k):
            v = [e[k] for e in ext if e.get(k) is not None]
            return round(sum(v) / len(v), 1) if v else None
        vis = [e["visibility_m"] for e in ext if e.get("visibility_m") is not None]
        waves = [(m["now"], p) for p, m in self.marine.items() if m.get("now") is not None]
        return {"humidity_mean": avg("humidity"), "pressure_mean": avg("pressure_hpa"), "wind_mean_kmh": avg("wind_kmh"),
                "visibility_min_m": round(min(vis)) if vis else None, "wave_max_m": round(max(waves)[0], 1) if waves else None, "wave_at": max(waves)[1] if waves else None,
                "temp_mean": round(sum(t for t, _ in temps) / len(temps), 1) if temps else None,
                "temp_min": min(temps)[0] if temps else None, "temp_min_at": min(temps)[1] if temps else None,
                "temp_max": max(temps)[0] if temps else None, "temp_max_at": max(temps)[1] if temps else None,
                "precip_max_mm_h": round(pr, 1), "precip_at": pr_at, "gust_max_kmh": round(gu), "gust_at": gu_at,
                "sev_worst": round(sevs[worst_at], 3), "level_worst": level(sevs[worst_at]), "worst_at": worst_at,
                "nodes_affected": sum(1 for v in sevs.values() if v >= 0.25), "nodes_total": len(nodes),
                "timeline": timeline, "horizon_h": horizon}

    # ------------------------------------------------------------------------------------------ status
    def status(self) -> str:
        if not self.enabled or self.fetched_at is None:
            return "UNAVAILABLE"
        if self.fixture:
            return "REPLAY"
        # the last good reading is kept and shown; it is STALE as soon as a refresh fails or it gets old
        return "LIVE" if (not self.error and time.time() - self.fetched_at <= 3 * self.ttl) else "STALE"

    @property
    def available(self) -> bool:
        return self.fetched_at is not None and self.enabled

    # ------------------------------------------------------------------------------------------ severity
    def _skip(self) -> int:
        """Whole hours since the data was fetched: sim hour +h maps to forecast hour +h counted from the fetch."""
        if self.fixture or self.fetched_at is None:
            return 0
        return max(0, int((time.time() - self.fetched_at) // 3600))

    def point_sev(self, pid: str, h: float = 0.0) -> tuple[float, dict]:
        d = self.data.get(pid)
        if not d:
            return 0.0, {}
        idx = int(h) + self._skip()
        hourly = d["hourly"]
        if idx <= 0 or not hourly:
            p, g, c = d["now"]
            i = 0
            vis = (d.get("extra") or {}).get("visibility_m")
            if vis is None and d.get("vis"):
                vis = d["vis"][0]
        else:
            i = min(len(hourly) - 1, idx)
            p, g, c = hourly[i]
            vis = d["vis"][i] if d.get("vis") and i < len(d["vis"]) else None
        mar = self.marine.get(pid)
        wave = None
        if mar:
            wave = mar["now"] if idx <= 0 or not mar["hourly"] else mar["hourly"][min(len(mar["hourly"]) - 1, idx)]
        info = {"precip_mm_h": round(p, 1), "gust_kmh": round(g), "code": int(c), "text": CODE_TEXT.get(int(c), "")}
        if wave is not None:
            info["wave_m"] = round(wave, 1)
        if vis is not None:
            info["visibility_m"] = round(vis)
        return severity(p, g, c, vis, wave), info

    def nearest(self, lat: float, lon: float) -> tuple[str, float]:
        from .geo import haversine_km
        best = min(self.points, key=lambda p: haversine_km(lat, lon, *self.points[p]))
        return best, haversine_km(lat, lon, *self.points[best])

    def node_sev(self, nid: str, h: float = 0.0) -> float:
        return self.point_sev(nid, h)[0] if self.available else 0.0

    def link_sev(self, lid: str, h: float = 0.0) -> tuple[float, dict]:
        """Weather severity on a link: the worst of its midpoint (road / rail) and its two ends; sea links use ports."""
        if not self.available:
            return 0.0, {}
        l = self.net.links[lid]
        cands = [self.point_sev(l.frm, h), self.point_sev(l.to, h)]
        if lid in self.mid:
            cands.append(self.point_sev(self.mid[lid], h))
        s, info = max(cands, key=lambda x: x[0])
        return s, info

    def peak_hours(self, lid: str, horizon: int = 48) -> tuple[float, int]:
        best, at = 0.0, 0
        for h in range(0, horizon, 3):
            s = self.link_sev(lid, h)[0]
            if s > best:
                best, at = s, h
        return best, at

    def time_factor(self, lid: str, h: float = 0.0) -> float:
        """Multiplier on travel time (>= 1)."""
        s = self.link_sev(lid, h)[0]
        m = self.net.links[lid].mode
        k = {"road": 0.4, "rail": 0.2, "sea": 0.4}[m]
        return 1.0 + k * s if s >= 0.25 else 1.0

    def risk_add(self, lid: str, h: float = 0.0) -> float:
        s = self.link_sev(lid, h)[0]
        if s < 0.25:
            return 0.0
        return s * {"road": 0.5, "rail": 0.3, "sea": 0.5}[self.net.links[lid].mode]

    # ------------------------------------------------------------------------------------------ views
    def meta(self) -> dict:
        st = self.status()
        return {"status": st, "source": self.source, "fetched_at": self.fetched_at,
                "age_min": round((time.time() - self.fetched_at) / 60, 1) if self.fetched_at else None,
                "error": self.error, "provider": self.provider, "provider_errors": self.provider_errors, "attempts": self.attempts,
                "last_attempt_age_s": round(time.time() - self.last_attempt) if self.last_attempt else None,
                "alerts": len(self.alerts), "alert_status": self.alert_status, "marine_points": len(self.marine), "fetched_label": time.strftime("%H:%M UTC", time.gmtime(self.fetched_at)) if self.fetched_at else None, "points": len(self.points), "refresh_min": round(self.ttl / 60),
                "note": ("Real-world weather at each facility's coordinates, applied to the synthetic network. "
                         if st in ("LIVE", "STALE") else
                         "Weather replayed from a file (recorded file, for testing and offline use), not live. " if st == "REPLAY" else
                         "No weather data: every weather effect is neutral. ")
                        + "Sim hour +h is read as forecast hour +h from now."}

    def _temp(self, pid: str, h: float = 0.0):
        d = self.data.get(pid) or {}
        idx = int(h) + self._skip()
        t = d.get("temps") or []
        if idx > 0 and t:
            v = t[min(len(t) - 1, idx)]
            if v is not None:
                return v
        return d.get("temp")

    def point_detail(self, pid: str, hours: int = 48) -> dict | None:
        """Hour-by-hour forecast at one facility or corridor midpoint (everything comes from the fetched data)."""
        if pid not in self.data:
            return None
        d = self.data[pid]
        lat, lon = self.points[pid]
        rows = []
        for h in range(0, hours + 1):
            s, info = self.point_sev(pid, h)
            idx = h + self._skip()
            pop = (d.get("pop") or [])
            hum = (d.get("hum") or [])
            rows.append({"h": h, "sev": s, "level": level(s), "temp": self._temp(pid, h), **info,
                         "humidity": hum[min(len(hum) - 1, idx)] if hum else None, "pop": pop[min(len(pop) - 1, idx)] if pop else None})
        s0, _ = self.point_sev(pid)
        return {"id": pid, "lat": lat, "lon": lon, "kind": "node" if pid in self.net.nodes else "corridor",
                "name": self.net.nodes[pid].name if pid in self.net.nodes else None, "now": {**(d.get("extra") or {}), "temp": self._temp(pid), "sev": s0, "level": level(s0)},
                "hourly": rows, "provider": self.provider}

    def cells(self) -> list[dict]:
        out = []
        if not self.available:
            return out
        for pid, (lat, lon) in self.points.items():
            s, info = self.point_sev(pid)
            fs = max((self.point_sev(pid, h)[0] for h in range(3, 48, 3)), default=0.0)
            out.append({"id": pid, "lat": lat, "lon": lon, "sev": s, "level": level(s), "peak48": round(fs, 3), "temp": self._temp(pid), **{k: v for k, v in (self.data[pid].get("extra") or {}).items()}, **info,
                        "kind": "node" if pid in self.net.nodes else "corridor"})
        return out
