"""Builds a TEST fixture in Open-Meteo response format (storm over the Western Ghats / Mumbai-Pune corridor).
Used by tests and offline UI checks via PNT1_WEATHER=fixture:<file>. It is synthetic test data, shown as REPLAY."""
import json, math, sys
sys.path.insert(0, "..")
from pnt1.network import Network
from pnt1.weather import WeatherFeed

net = Network()
feed = WeatherFeed(net, mode="off")
out = []
for pid, (lat, lon) in feed.points.items():
    d = math.hypot((lat - 18.9) * 111, (lon - 73.3) * 105)       # km from the storm centre
    base = max(0.0, 1 - d / 260)
    hours = [f"2026-10-01T{h % 24:02d}:00" if h < 24 else f"2026-10-0{2 + h // 24 - 1}T{h % 24:02d}:00" for h in range(96)]
    rain = [round(22 * base * max(0.0, 1 - abs(h - 10) / 30), 1) for h in range(96)]
    gust = [round(25 + 80 * base * max(0.0, 1 - abs(h - 10) / 30)) for h in range(96)]
    code = [95 if r > 12 else 65 if r > 7 else 61 if r > 1 else 3 for r in rain]
    out.append({"current": {"time": hours[0], "temperature_2m": 28.0, "precipitation": rain[0], "wind_gusts_10m": gust[0], "weather_code": code[0]},
                "hourly": {"time": hours, "precipitation": rain, "wind_gusts_10m": gust, "weather_code": code}})
json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "weather_fixture.json", "w"))
