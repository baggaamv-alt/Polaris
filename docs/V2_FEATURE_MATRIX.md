# V2 feature matrix (audit of V1 before any change)

Legend: **Exists** = working in V1 · **UI** = needs a UI upgrade only · **BE** = needs a backend extension · **New** = not in V1.

| # | Feature | Exists | UI | BE | New | Where / what V2 does |
|---|---|:-:|:-:|:-:|:-:|---|
| 1 | Synthetic Indian network (40 nodes, 92 links), world simulator, 150 trucks | ✔ | | | | `network.py`, `world.py` — untouched logic |
| 2 | MapLibre globe with Esri World Imagery | ✔ | ✔ | | | Map becomes the persistent hero across pages; satellite + chart basemaps, relief, pitch, camera ladder |
| 3 | Truck telemetry + animated trucks | ✔ (1 s jumps) | ✔ | | | Smooth rAF interpolation between snapshots, trails, glow |
| 4 | Ships / rail movement | ✗ (only trucks are simulated) | | ✔ | | Ships/trains animate **LP-planned** sea/rail flows (`/api/flows/baseline`), labelled as planned, not tracked |
| 5 | Trust Engine (8 checks, quarantine, CUSUM) | ✔ | ✔ | | | Animated reading → checks → verdict → quarantine → last trusted state |
| 6 | Sensor fusion | partial (checks only) | ✔ | ✔ | | `fusion.py`: groups existing checks into sources + nearby-vehicle agreement + alerts; weather shown **unavailable** |
| 7 | Blockage inference (quorum, independence, contradiction) | ✔ | ✔ | | | "Resilience Engine" signal-convergence visual from real inference fields |
| 8 | Attack injection (10 injectors + real blockage) | ✔ | ✔ | | | Attack → detection → trust → quarantine → recovery storyline |
| 9 | Scenario lab: OR-Tools LP, 4 strategies, 200-run Monte Carlo, EV rule | ✔ | ✔ | ✔ | | Custom weights (money/time/fuel/distance/carbon), configurable runs, MC histogram, plan diffs |
| 10 | Cascade hour-by-hour frames | ✔ | ✔ | ✔ | | 72-h cinematic timeline on the main map, cascade milestones, per-period link flows |
| 11 | Fragility (critical nodes, betweenness, min cuts, blast radius) | ✔ | ✔ | | | "Supply Chain Doctor" findings that highlight the map |
| 12 | Evaluation vs hidden truth, model card | ✔ | ✔ | | | "Technical Proof" section |
| 13 | Audit trail, chain verify, decision replay | ✔ | ✔ | ✔ | | Replay now honours V2 inputs; "Time Machine" replay of audit + resilience history |
| 14 | Raw-vs-trusted decision comparison | ✔ | ✔ | | | Kept (shows the Trust Engine). No generic "AI vs no AI" |
| 15 | Supply Chain Resilience Index | ✗ | | | ✔ | `resilience.py`: 8 components from live state, history + "why it changed" |
| 16 | Operational metrics (orders/inventory at risk, recovery ETA, capacity, fleet utilisation) | ✗ | | | ✔ | `runtime.ops_metrics()` |
| 17 | Multimodal cost engine (truck / rail / ship) | ✗ (LP has per-unit tariff) | | | ✔ | `costing.py` bottom-up estimate with **simulated** assumptions; LP tariff shown for reference |
| 18 | Alternative route comparison + user priorities | ✗ | | | ✔ | k-path + forced-mode candidate generation, weighted scoring, explanation of why the winner changed |
| 19 | Shipment priority | data field (constant 2) | | ✔ | | Derived from SKU class (SKU-B pharma = CRITICAL). Route planner: SLA deadline + risk weight; LP: opt-in priority-weighted stockout penalty |
| 20 | Self-healing reroute of live trucks | ✗ | | | ✔ | Incident → affected trucks → options → operator approval → `World.reroute_vehicle` (truth) → twin |
| 21 | Live incidents (port/warehouse/supplier closure, storm) | only road blockage | | ✔ | | Incident registry; world stops dispatching to closed nodes |
| 22 | Business flow (orders, ETA, delay, next step) + support | ✗ | | | ✔ | `orders.py` from twin belief; support tickets written to the audit chain |
| 23 | Vehicle health | fuel in telemetry only | | ✔ | | Heuristic risk from fuel, anomalies, stops, trust; temperature **unavailable** |
| 24 | Driver assignment | ✗ (future scope in docs) | | | prototype | Clearly labelled prototype with synthetic roster; vehicle health used for compatibility |
| 25 | Weather | ✗ (roadmap) | | | | Storm scenario drives the causal chain; no live weather is claimed |
| 26 | Inventory reallocation | LP transfer strategy | ✔ | ✔ | | Surface W→W transfers of the recommended plan and animate them |
| 27 | Pixel-art system | ✔ | ✔ | | | Extended sprite set as the visual identity |
| 28 | Dark + light themes | ✗ | | | ✔ | Token-based, persisted, separately designed |
| 29 | Scroll story landing | partial | ✔ | | | Scroll-driven 10-stage narrative |

| Real weather (Open-Meteo) | no | no | no | weather.py, /api/weather, map overlay, Command Center card, Incident chain, fusion, index, self-healing |
| 3D satellite + terrain | partial | globe + imagery | no | tile proxy/cache, offline pack, 3D terrain |
| Editable cost inputs | no | read-only | no | POST /api/cost/assumptions |
