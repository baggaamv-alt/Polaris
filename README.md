# VIGILAX · PNT1 Logistics Network Digital Twin — 2.5


## 2.5: content cleanup

Copy-only release on top of 2.4. Page headers are now just the page name; descriptive paragraphs, repeated sub-labels, helper text and long empty-state explanations were removed or shortened across every page, the weather panel, the story and the map overlays. No layout, styling or functionality changed.

## 2.4: weather that works, and tells you why when it does not

Weather-only release.

- **Provider chain**: Open-Meteo forecast (temperature, apparent temperature, humidity, rain and probability, cloud, pressure, wind, gusts, visibility), automatic per-chunk fallback to MET Norway Locationforecast, plus Open-Meteo Marine wave height at ports.
- **Regional hazard alerts** (USGS M4.5+ earthquakes, NASA EONET storms/floods/volcanoes/landslides, GDACS events) with the nearest facilities listed. Informational only; they do not change severity math.
- **Network robustness**: retries with back-off, 429 Retry-After, TLS via system store then certifi, slower retry loop on failure, and a disk cache (`backend/data/weather_cache.json`) so the last real reading survives a restart (shown as STALE with its age).
- **Test connection**: the weather strip has a "Why? Test connection" button (`GET /api/weather/diagnostics`) that checks each host and reports the error kind (TLS, DNS, timeout, proxy, HTTP) with a fix hint.
- **Facility forecast**: click a facility in the weather panel for a 48 h chart (`GET /api/weather/point/{id}`).
- Env: `PNT1_WEATHER=off|fixture:<file>`, `PNT1_WEATHER_CACHE`, `PNT1_WEATHER_INSECURE_SSL=1` (last resort for broken corporate TLS), `PNT1_WEATHER_MIRROR=http://host:port` (offline labs).
- Hosts needed: api.open-meteo.com, marine-api.open-meteo.com, api.met.no, earthquake.usgs.gov, eonet.gsfc.nasa.gov, www.gdacs.org.
- Run tests with `uv run python -m pytest -q`.

## 2.3: weather-first command platform

- **Persistent weather strip** in the app shell on every page (including the story): LIVE / STALE / UNAVAILABLE state, temperature, peak rain, gusts, worst severity and where, facilities and corridors affected, a 48-hour severity timeline, last-updated age, refresh, and a details panel with the forecast, worst facilities and corridors at risk. All values come from `/api/weather` (Open-Meteo through the backend); the client never invents a weather number.
- **Truthful failure handling**: if a refresh fails the last good reading stays visible and is marked STALE with its time; if weather was never received the strip says UNAVAILABLE and weather is left out of the resilience score, route risk and ETAs.
- **Command Center order**: weather situation (situation, what it affects, consequence), resilience, operations, at-risk shipments, active incidents, telemetry.
- **Resilience** is a score with a banded scale, a segmented weighted bar, "what changed" drivers and components ranked weakest first; no radial dial.
- **Incident Simulator** and **AI Recovery** each carry a causal line (incident, network impact, weather and resilience, cascade, forecast, recovery; current route, alternatives, trade-offs, recommendation, approval, recovery) that lights up as the state progresses.
- **Business Flow**: a connected process line and a Support & Contact drawer (order context, category, message, tickets with status and audit sequence and hash) backed by `/api/support/tickets` and the audit log.
- Backend additions: `summary` (temperature, peak rain and gusts, worst facility, affected counts, 48 h timeline) in `/api/weather`, `temp` per cell, `STALE` as soon as a refresh fails.
- Tests: `cd backend && uv run python -m pytest -q` (46 pass, 2 skip unless the optional anomaly model is trained).

## 2.2 — product redesign (UI only; all data and behaviour unchanged)

- New design system: warm parchment light theme (default) and charcoal dark theme, Inter-only type, hairline rules, flat panels, no glow, gradients or neon. Sections are ruled rows and tables, not stacked cards.
- One SVG icon set for the interface. Pixel art is used only as a consistent illustration language for logistics entities (truck, plane, ship, train, container, package, warehouse, port, factory, supplier, pin, warning): map markers, finding and incident rows, empty and loading states, landing scene.
- Editorial landing page, restrained map (no halos or glow layers), muted semantic colours for charts and routes.
- Honesty labels (SIMULATED / MOCK / PLANNED / STATIC / REPLAY) are unchanged.

A live logistics command center for a synthetic Indian network (40 facilities, 92 road/rail/sea links, 150 trucks).
It checks every incoming reading before believing it, detects and forecasts disruptions, recommends a recovery for a
person to approve, moves the trucks, and proves its own accuracy against a hidden simulated truth.

**SEE → TRUST → DETECT → PREDICT → SIMULATE → OPTIMIZE → RECOVER → PROVE**

V2 keeps every V1 algorithm (Trust Engine, blockage inference, OR-Tools LP, Monte Carlo, cascade, fragility,
hidden-truth evaluation, hash-chained audit) and adds the command-center experience on top. The audit of V1 and
what changed is in [`docs/V2_FEATURE_MATRIX.md`](docs/V2_FEATURE_MATRIX.md); design decisions in
[`docs/DECISIONS.md`](docs/DECISIONS.md) (V2 section at the end).

## Run it

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync
uv run uvicorn pnt1.api:app --port 8000
```

Open http://localhost:8000. MapLibre, the coastline and the fonts are vendored in `frontend/vendor/`, so the twin
runs offline. **Internet is needed once, from the machine running the server**, for two things:

* **Real weather** – the server fetches Open-Meteo (current + 72 h forecast) for every facility and corridor every
  15 min. Unreachable → the UI says *unavailable* and every weather effect is neutral (nothing is invented).
  Environment: `PNT1_WEATHER=off` disables it; `PNT1_WEATHER=fixture:<file>` replays a file and is labelled REPLAY.
* **3D satellite globe** – Esri World Imagery (a **static** basemap) and AWS terrain tiles are fetched *through the
  server* (`/tiles/...`) and cached on disk (`backend/data/tile_cache`). Open **☰ Layers → Offline → Save offline
  imagery pack** once while online (India at zoom 2–7, every facility at zoom 8–11) and the 3D map then works with no
  internet. 3D terrain switches on only after real elevation tiles have loaded; otherwise the chart basemap is shown.

## Test it

```bash
cd backend
uv run pytest -q          # 20 V1 + 14 V2 + 10 V2.1 tests (test_weather.py, test_v21_api.py); 2 model tests skip unless the optional anomaly model is trained
```

## The product (six views over one persistent 3D globe)

| View | What it answers | Built on |
|---|---|---|
| **Story** (`#/`) | Scroll narrative: network → telemetry → trust → disruption → cascade → alternatives → AI → approval → recovery → Resilience Index | live API data, real planner output |
| **Command Center** | *Is the network healthy right now?* Supply Chain Resilience Index (8 live components, animated, “why did the score change?”), operational metrics, Telemetry → Trust → Twin pipeline, at-risk shipments, events | `resilience.py`, `runtime.ops_metrics` |
| **Digital Twin** | Select any truck or hub: Trust Engine verdict (🟢 TRUSTED / 🟡 UNCERTAIN / 🔴 SUSPICIOUS) with the check pipeline, quarantine path to the last trusted state, **sensor fusion** (most likely current state), vehicle health; camera ladder India → region → city → facility → vehicle | `trust.py`, `ops.fusion`, `ops.health` |
| **Incident Simulator** | Inject a live incident (road closure, storm, port / hub / supplier outage — now or scheduled) or a data attack; Resilience Engine signal convergence; 72-hour forecast (4 LP strategies × Monte Carlo) with cascade, weather chain, reallocation and a cinematic timeline on the map; approve / reject | `runtime.open_incident`, `inference.py`, `strategies.py`, `engine.py` |
| **AI Recovery** | Route intelligence: real alternative routes (truck / rail + truck / ship + truck) drawn on the map, user priorities (money · time · fuel · distance · carbon) with an explanation of why the winner changed, multimodal cost engine waterfall. Self-healing: disruption → alternatives → comparison → **operator approval** → the truck physically reroutes in the simulated world | `costing.py`, `World.reroute_vehicle` |
| **Business Flow** | Supplier → manufacturer → warehouse → transport → distribution → customer; every shipment's origin, position, destination, status, ETA, delay, owner and next step; support tickets (audit-logged); driver-assignment **prototype** | `ops.py` |
| **Resilience & Proof** | Supply Chain Doctor (findings that light up the map), technical proof vs hidden truth (position / inventory fidelity, detection recall, false-positive rate, trust accuracy), Monte Carlo evidence, time machine, audit chain verify + decision replay | `graph.py`, `evaluation.py`, `audit.py` |

Dark (command center) and light (logistics platform) themes are separately designed and persisted.
Animations respect `prefers-reduced-motion`.

## Layout

```
backend/pnt1/   world (simulator, attacks, V2 reroute + facility closures), ingest, trust, twin, modes, inference,
                planning (LP, V2 priority weights), engine (Monte Carlo), strategies, graph, audit, evaluation,
                costing (V2 cost engine + route planner), resilience (V2), ops (V2 orders / fusion / health),
                runtime, api
backend/tests/  test_core.py, test_anomaly.py (V1), test_v2.py (V2)
frontend/       index.html, style.css, sprites.js (pixel-art identity), app.js (core), map.js (3D twin),
                pages/*.js (one file per view), boot.js, vendor/ (MapLibre, coastline, fonts)
docs/           Level 1 design documents, DECISIONS.md, V2_FEATURE_MATRIX.md
```

## Data honesty

| Label | Meaning |
|---|---|
| **SIMULATED** | fleet, warehouses, orders, telemetry, incidents, costs (planning assumptions you can edit in AI Recovery → Assumptions; not market prices) |
| **MOCK** | road alerts from the scripted alert feed |
| **PLANNED** | ships and trains on the map animate optimizer-planned sea / rail flows, not tracked vessels |
| **LIVE / REPLAY / UNAVAILABLE** | real weather feed state (Open-Meteo) |
| **STATIC** | satellite imagery is Esri World Imagery, a static basemap — never live satellite intelligence |
| **REPLAY** | the time machine and decision replay |
| **PROTOTYPE** | driver assignment (synthetic roster, illustrative duty limit — future scope) |

Truck GPS is the truck's own telemetry, cross-checked by the Trust Engine. Weather is **real** (Open-Meteo, labelled
LIVE, or REPLAY / UNAVAILABLE) applied to the synthetic network; the *Severe storm* incident is still a simulated
scenario. Weather flows into sensor fusion, route risk and ETA, the Resilience Index (9th component, weights
renormalised when unavailable), the Weather impact chain (weather → road risk → ETA → inventory → network risk →
recovery option) and self-healing (trucks heading into severe weather are offered reroutes). Resilience Index, metrics and evaluation
numbers are computed from the running system, never hardcoded. Savings are measured in simulation only.
