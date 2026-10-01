# DECISIONS.md: changes from the Level 1 plan

Each entry records what was planned, what was built instead, why, and the evidence. Planned values came from `docs/02_ARCHITECTURE.md` and `docs/ASSUMPTIONS.md`.

## Platform

| # | Planned | Built (Level 2) | Why | Evidence / follow-up |
|---|---|---|---|---|
| D-01 | Redis Streams bus, Postgres + PostGIS + Timescale | In-process `Bus` (same publish/drain shape) and SQLite for the audit log. All other state lives in memory | Docker was installed but not running on the dev laptop. The swap sits behind an interface | Level 3: Redis/Postgres adapters and Docker Compose |
| D-02 | Next.js + deck.gl front end | Static HTML/CSS/JS served by FastAPI, with MapLibre for the map | No build step, and one person can change the UI quickly. MapLibre symbol layers are enough for 150 trucks | Revisit if the UI grows beyond the 7 screens |
| D-03 | Mapbox/CARTO-style basemap | Esri World Light Gray Canvas tiles | CARTO now requires an API key (the tiles showed a watermark) | Tiles need internet. An offline presentation needs a cached tile set |
| D-04 | JWT/RBAC at L3 | No auth yet | Per the roadmap (T31) | Level 3 |

## World simulator

| # | Planned | Built | Why | Evidence |
|---|---|---|---|---|
| D-05 | Random truck trips | **Demand-aware dispatch**: carry what is low to where it is low, drive empty to the nearest producer of anything needed | Random trips drained some warehouses to zero, which distorted every scenario | A 48 h run went from falling cover to stable total stock (11,266 → 10,981 units over 24 h) |
| D-06 | Directed links used for truck routing | **Two-way road routing for trucks** (`Network.truck_route`); the planning graph stays directed | Suppliers have only outgoing links, so trucks could never drive to them | Supplier, port and factory pickups now occur (0 before, 95 in 24 h after) |
| D-07 | 120 trucks, 20 pallets, 120 units/SKU/day base demand | 150 trucks, 40 pallets, 90 units/SKU/day | A sustainable network at the presentation clock speed | Same 48 h run as D-05 |
| D-08 | Warehouses start with 4–9 days of cover | 2.5–4.5 days (`INIT_COVER_DAYS`) | With 6+ days of stock, no 72 h disruption had any effect. 2.5–4.5 days is typical of a lean network | The planning smoke test showed L = 0 for every closure at 6 days |
| D-09 | Coordinated-stop spoof freezes positions | The spoof drives compromised trucks plausibly to one point on the link (at least 10 km from any facility), then reports a stop | Frozen positions spread along 325 km never formed a cluster. A real attacker must fake a queue | The spoof now yields SUSPECTED only, never blocked (see D-13) |

## Trust Engine

| # | Planned | Built | Why | Evidence |
|---|---|---|---|---|
| D-10 | Statistical check (IsolationForest) at weight 0.05 | Not active. Weights renormalise | Roadmap T25 is Level 3. The rule checks already catch the hard attacks | Level 2 detection run: speed spike, teleport, fake inventory, corrupt feed and replay all at 100% reading recall |
| D-11 | Replayed / out-of-order `seq` lowers the temporal score | **Dropped outright** (`replay_dropped`) | Scored as a low temporal check, a replay still averaged to Trusted (0.89) and moved the truck backwards | Unit test `test_replayed_seq_is_dropped` |
| D-12 | Warehouse reconciliation against the last reported count | Reconciliation against an **engine-private flow ledger** that keeps advancing while the feed is quarantined | Against the last report, a persistent fake count passes after its first reading. Keeping the ledger in the twin would break "quarantine never writes to the twin" | `test_quarantine_never_writes_twin`; fake inventory is detected on every reading |
| D-13 | Blockage inference on each truck's assigned-route link | Nearest **physical** road, with both directions of a road merged into one ID, plus a **facility-yard exclusion** (3 km) | Loading at yards produced a false BLOCKED on L053 with no attack. Clustering by assigned route split one queue across L053/L054 | After the fix: fake queue → SUSPECTED (max confidence 0.70, coordinated anomaly flagged); real blockage → BLOCKED_INFERRED (1.0), cleared after it lifted |
| D-14 | Optimizer discount d = 0 for quarantined feeds | Quarantined feed → flow-reconciled stock × 0.5 | Zero stock for a whole warehouse makes the planner route around a facility that still physically holds goods | First guess; tune in Level 3 benchmark |

## Planning and simulation

| # | Planned | Built | Why | Evidence |
|---|---|---|---|---|
| D-15 | Lost sales at customers each period | Customers hold a stock balance with a 12 h starting buffer, in **both** the LP and the engine | The LP and the engine disagreed, so baseline service was 88% with no disruption | Deterministic baseline service is now 99.6% |
| D-16 | Safety-stock slack penalty ₹200/unit | 10% of unit value per unit-period | ₹200 was cheaper than shipping, so the optimizer let stock run down | Same run as D-15 |
| D-17 | Monte Carlo demand σ 0.15, transit delay +20% | σ 0.08 (72 h aggregate), delay +10% (Gamma(4, 0.025)) | ±15% for a whole city over 3 days swamped every strategy difference with noise | Service under MC rose from 94% to about 95%. All three values are configurable |
| D-18 | Recommend the lowest expected cost | Recommend acting only if expected cost falls by more than 0.5% vs doing nothing | Recommendations flipped on differences under 1%, which were artefacts of 6 h aggregation | `recommendation_reason` explains the choice in the UI |
| D-19 | Heuristic fallback (Yen k-shortest) when the LP fails | Fall back to the baseline plan and flag it | The LP has solved every case so far (in under 1 s). The heuristic is deferred | Level 3 if solver failures ever appear |
| D-20 | Link closure only | Added a **storm** disruption that closes every road and rail link between two places | A single-corridor closure never bit because the network reroutes via parallel links. A storm is the realistic weather event | Even a full HYD–VGA storm causes little loss: W-VGA is also fed from Visakhapatnam, Chennai and Kolkata. Documented as real redundancy |

### Known limitations (honest)
- Small negative "action costs" can appear: the LP plans in 6 h buckets while the engine executes hourly. The UI labels these "cheaper than the current plan anyway" instead of hiding them.
- The first genuine reading after a spoof ends snaps back from the fake track and is (correctly) flagged. Evaluation currently counts it as a false positive, because its ground-truth label is "clean".
- Everything is measured on simulated data.

## Design (UI redesign)

| # | Decision | Why |
|---|---|---|
| D-21 | Replaced the dark neon theme with a paper, ink and navy system. Colour carries only state (trusted, estimated, quarantined, simulated) | Readability, and to match shipping-documentation and aviation-chart conventions rather than a sci-fi HUD |
| D-22 | A custom pixel-art set (`frontend/sprites.js`): one 16-px grid, 1-px ink outline, flat fills, a 10-colour palette. It is used only for logistics entities (map trucks, facilities), scenario tiles, empty and loading states, and the landing lane | A signature identity without pixelating the interface. The UI type, controls, tables and charts stay modern |
| D-23 | No airplane sprite on the map | The network has no air freight. Drawing planes would show a capability the product does not model |

## V2 (final): command-center experience on top of the V1 engine

Rule for V2: reuse or extend working V1 code; add backend only where V2 genuinely needed something new. No "AI vs no AI" comparison (the raw-vs-trusted comparison stays because it shows the Trust Engine).

| # | Decision | Why | Evidence |
|---|---|---|---|
| V2-01 | One persistent MapLibre globe shared by every page (re-used V1 globe + Esri imagery) instead of one map per page | The map is the hero; one WebGL context keeps interaction smooth | `frontend/map.js` |
| V2-02 | Map layers initialise on `style.load`, not `load` | `load` waits for every basemap tile and never fires when imagery is blocked/offline; the twin must work without it | offline test run; chips show "Imagery unreachable · chart shown" |
| V2-03 | MapLibre, coastline and fonts vendored in `frontend/vendor/` | Presentation robustness offline and behind firewalls | — |
| V2-04 | Hub labels are HTML markers; no text layers | No glyph server dependency | — |
| V2-05 | Supply Chain Resilience Index = 8 weighted components from twin belief (`resilience.py`); history + change drivers | The score must move with the network and explain itself; never hardcoded | `test_resilience_index_moves_with_incidents` |
| V2-06 | Multimodal cost engine is a bottom-up per-shipment estimate with labelled SIMULATED rates; carbon uses the LP's per-unit factors; the LP tariff is shown alongside | Judges can follow distance → fuel → tolls → operating → maintenance → handling → total without invented market prices | `test_road_cost_components_add_up`, `test_rail_has_no_tolls_and_terminal_handling_is_charged` |
| V2-07 | Route planner: weight-independent candidate set (k-shortest by time and cost + best path forced through every rail/sea link, one graph edge per physical road direction, suppliers/customers not used as transit, diversity by Jaccard overlap); user weights only change scoring | "Why did the winner change?" has a precise answer (weighted score swing per metric) | `test_weights_change_the_recommendation_with_an_explanation`, `test_display_set_is_independent_of_weights` |
| V2-08 | User priorities also drive the LP (`weights_from_priorities`: money/time/fuel/distance/carbon → cost/delay/fuel/dist/co2 terms); presets unchanged | Same slider semantics for route- and network-level optimisation; V1 behaviour identical when no weights are passed | `test_lp_default_path_unchanged_and_custom_weights_solve` |
| V2-09 | Shipment priority derived from SKU class (SKU-B pharma = CRITICAL, SKU-C electronics = HIGH). Used in the route planner (SLA deadline factor + risk weight) and shown everywhere | Materially changes recommendations (rules out slow detours) | `test_critical_priority_deadline_rules_out_slow_routes` |
| V2-10 | A priority-weighted stockout penalty in the LP was tried and **removed** | It did not change any scenario outcome measurably (unmet by SKU identical); a cosmetic feature would mislead | scan of W-VGA / P-CHE / S02 scenarios |
| V2-11 | Self-healing reroute changes ground truth (`World.reroute_vehicle`) only after operator approval; the twin learns the new route from the normal shipment event | The recovery is real, telemetry stays consistent, trust stays high | `test_self_healing_reroute_moves_the_truck_off_the_closure` |
| V2-12 | Which trucks need rerouting uses the closure *point* (declared incident point, facility end, or median of the stopped cluster) and the truck's position on its route | Trucks already past a blockage must not be turned around | runtime `block_points` |
| V2-13 | Live incidents can be scheduled (a storm warning N hours out) | With zero lead time the EV rule correctly recommends "do nothing" for most closures; lead time lets the optimizer pre-position (e.g. hub failure W-VGA, +6 h: reroute, expected cost ₹3.44 Cr → ₹2.22 Cr, service 92.2% → 96.0% in one run) | `test_scheduled_incident_activates_later` |
| V2-14 | Sensor fusion groups the existing Trust Engine checks into sources and adds neighbour agreement and trusted observations; weather is shown **unavailable** | Fusion without inventing readings | `test_fusion_never_invents_weather` |
| V2-15 | Vehicle health is a heuristic from fuel, anomaly rate, motion consistency, unplanned stops and trust; temperature/tyres shown unavailable | Telemetry has no engine sensors | `ops.health` |
| V2-16 | Ships and trains animate optimizer-planned sea/rail flows (`/api/flows/baseline`), labelled PLANNED | Only trucks are simulated; planned flows are honest movement | map chips |
| V2-17 | Alternative routes are drawn as arcs with per-route bend | Synthetic links are straight lines; parallel alternatives would overlap. Display only | `map.js curve()` |
| V2-18 | Driver assignment kept as a clearly labelled prototype with a synthetic roster | The backend has no driver / duty-hour data (future scope in the roadmap) | Business Flow page |
| V2-19 | Monte Carlo runs configurable (50–500, default 200) plus spread statistics and histograms | Present uncertainty honestly; no "1,000 runs" claim | `summarize()` |

### Known limitations (V2)
- Road network geometry is still straight-line synthetic; alternative-route arcs are a display device.
- The world only simulates trucks. Rail and sea appear as planned flows and as options in the route planner.
- The cost engine's rates are planning assumptions; the LP keeps its own per-unit tariff (both are shown).
- Inference needs ~15 sim-minutes of stopped trucks before it calls a blockage (by design, V1 thresholds).


## V2.1 — weather, 3D satellite, connected caveats
- **V2.1-01 Real weather is fetched server-side** (Open-Meteo, no key), cached, refreshed every 15 min, never blocking the sim loop. Status LIVE / STALE / REPLAY / UNAVAILABLE; when unavailable all effects are neutral and the Resilience Index drops the weather component and renormalises. No synthetic fallback is ever shown as live.
- **V2.1-02 Sim hour +h reads forecast hour +h from real now.** The network and clock are synthetic, the weather is real at each facility's coordinates; this is stated in the UI.
- **V2.1-03 Weather effects**: severity 0..1 from rain rate, gusts and WMO code. Road/rail/sea travel time x(1+k·sev) with k 0.4/0.2/0.4 from sev >= 0.25; route risk + sev·(0.5/0.3/0.5). These feed the same planner, ETA, fusion and index used for closures.
- **V2.1-04 Weather-exposed trucks enter self-healing** (cause "weather") only when delay >= 0.5 h and they are not on their last leg; the recovery engine is unchanged.
- **V2.1-05 Tile proxy + disk cache** (`/tiles/{sat|dem}/z/x/y`) makes the satellite globe and terrain work behind CORS/hotlink limits and offline after one pack download. `PNT1_TILE_UPSTREAM` overrides the upstream (tests, air-gapped mirrors).
- **V2.1-06 3D terrain only after elevation tiles load** so an offline or failed DEM never tilts the map over a void.
- **V2.1-07 Cost inputs are editable but still labelled assumptions**; changes are validated, audit-logged and re-price every route. They are process-wide, not persisted across restarts.
- **Still not done, by design**: ships and trains are LP-planned flows (no AIS / rail tracking key); driver assignment remains a labelled prototype; priority is not in the network LP (it had no measurable effect; removed rather than faked).


## 2.3: weather as a first-class, always-visible source
- Weather lives in the app shell, not on one page, so the operator never loses it while navigating.
- A failed refresh keeps the last good reading and marks it STALE; a feed that never succeeded is UNAVAILABLE and contributes nothing (no assumed calm).
- The resilience score is shown as a scale plus ranked components instead of a radial dial, so the reason for a change reads directly.
- Support & Contact is an action in the Business Flow header that opens a drawer on the existing tickets API.
