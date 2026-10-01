# ASSUMPTIONS.md — PNT1 Logistics Network Digital Twin

Every assumption made while writing the Level 1 documents is listed here, with the reason and what changes if it turns out wrong. The briefs asked me to record assumptions instead of asking questions, so nothing here was confirmed by the team.

**Sources:** `00_BRIEF.md` (main brief, "BRIEF") and `00a_ADDENDUM_TELEMETRY_TRUST.md` ("ADD"). Where they conflict, ADD wins for telemetry, trust scoring and the ingestion-to-decision flow (ADD header).

---

## A. Team, timeline, process

| ID | Assumption | Why | If wrong |
|---|---|---|---|
| A-01 | Team of 4: **BE** (Backend/Simulation), **OPT** (Optimization/ML), **FE** (Frontend), **OPS** (DevOps/QA). | BRIEF §12 says to assume this. | Re-balance the roadmap owner column; the critical path stays the same. |
| A-02 | Calendar: Level 1 = days 1–2, Level 2 = days 3–9, Level 3 = days 10–16, Level 4 = days 17–21 (21 working days in total), starting **2026-10-01**. | Hackathon dates were not given. The Gantt chart needs absolute dates. | Scale the Gantt chart. Keep the order and the cut-lines. |
| A-03 | About 8 focused hours per person per day during the hackathon, so roughly 32 person-hours per team-day: 56 h per person in L2 and L3, 40 h in L4. | Hackathon intensity. The L2 load (46–54 h per role) fits, and L3/L4 keep 8–20 h of slack. | If the real figure is closer to 6 h/day, apply the cut-lines in `07_ROADMAP.md` §5 from item 5 onwards during L3. |
| A-04 | One mono-repo: `backend/` (Python), `frontend/` (Next.js), `infra/`, `docs/`. | This is the simplest option for a small team and for CI. | None. |
| A-05 | The docs folder is the Level 1 deliverable. Folder `codestorm/` is the repo root. | The working directory was empty. | None. |

## B. Domain and data

| ID | Assumption | Why | If wrong |
|---|---|---|---|
| B-01 | The whole network is **synthetic**: 40 fixed nodes (8 suppliers, 5 ports, 2 factories, 10 warehouses, 15 customer clusters) and 92 directed links. About **120 vehicles** are dynamic entities and are not counted as graph nodes. | BRIEF F-01 asks for about 40 nodes. Vehicles move, so they are modelled as entities on links. | The graph size is a config value. Only performance targets would change. |
| B-02 | Five SKU families: SKU-A packaged food, SKU-B pharma, SKU-C electronics, SKU-D auto parts, SKU-E consumer goods. Quantities are counted in **pallet-equivalent units**. | Five families keep the optimizer small but still multi-commodity. | More SKUs increase optimizer size linearly. |
| B-03 | Road distance = haversine × 1.30. Rail ×1.25, sea ×1.35. Average speeds: road 45 km/h, rail 35 km/h, coastal sea 25 km/h. Handling time: road 0.5 h, rail 4 h, sea 12 h. | These are reasonable averages for Indian freight. They are marked synthetic. | Edit `docs/seed/seed_network.yaml`. |
| B-04 | Cost per pallet-km: road ₹2.25, rail ₹1.20, sea ₹0.60. CO₂ per pallet-km: road 0.031 kg, rail 0.011 kg, sea 0.008 kg (assumes 0.5 t per pallet and about 62/22/16 g per t-km). | Rough public averages. Only the relative sizes matter for the optimizer. | Only absolute ₹ values change. The decision logic does not. |
| B-05 | Currency is INR. Lakh (L) = 100,000. | Indian network. | None. |
| B-06 | The simulated clock runs at **60×** real time in presentations (1 sim-minute per real second). It is configurable from 1× to 600×. | This lets a 72 h cascade and an 8 h forecast lead fit into a 5-minute presentation. | None. |
| B-07 | Three **independent fleet operators** (FLEET-A, FLEET-B, FLEET-C) each have their own ingestion credentials and `source_id` namespace. Port gate-scan events come from a separate simulated port-community source. | ADD §5.3 requires corroboration from "vehicles from independent fleets/sources". | If only one fleet is modelled, the quorum guard can only rely on weather, alerts and gate scans. |
| B-08 | Order value averages ₹20,000 per pallet, varying by SKU (pharma is highest). Stockout penalty = 1.5 × lost order value. Late-delivery penalty = 2% of order value per hour late, capped at 50%. | Needed to turn the simulation into rupees. These are documented cost parameters, not facts. | Cost parameters are config. The EV logic is unchanged. |

## C. External signals (labelling per BRIEF §5)

| ID | Assumption | Mode |
|---|---|---|
| C-01 | Open-Meteo Forecast API (free, no key). We use hourly `precipitation`, `wind_gusts_10m` and `weather_code`, sampled at 3–6 points along each corridor. Responses are cached for 30 minutes. The last good response is stored as a replay fixture. | `LIVE` (fallback `REPLAY`) |
| C-02 | GDACS RSS/GeoJSON alerts are polled every 15 minutes. NASA FIRMS is a SHOULD. | `LIVE` (fallback `REPLAY`) |
| C-03 | AIS data is a recorded sample: a synthetic-but-realistic CSV of about 30 vessels over 72 h near the five ports, streamed by the replay tool. We do **not** claim a live AIS feed. | `REPLAY` |
| C-04 | The Earth-observation flood mask is a pre-computed GeoJSON polygon set for the Krishna-delta region. It is shown only as an overlay and as one context check. | `MOCK` |
| C-05 | Truck GPS is the truck's own telemetry. It is never called "satellite positioning" or treated as an independent source. The independent check is named **"Geospatial / road-network match"** (ADD §4.3). | n/a |
| C-06 | In the presentation, weather used to *drive the ground-truth world* comes either from a live forecast (when available) or from a scripted scenario. This choice is recorded per run. | Stated per run |

## D. Algorithms and parameters (defaults; all configurable)

| ID | Assumption / default | Where defined |
|---|---|---|
| D-01 | Trust check weights: Schema 0.10, Range/physics 0.20, Kinematic 0.20, Road-network 0.15, Route 0.15, Temporal 0.10, Statistical 0.05, Context 0.05. If a SHOULD check is not implemented yet, the weights are renormalised over the checks that are active. | `01_SRS.md` §3.3, `02_ARCHITECTURE.md` §5 |
| D-02 | A hard check "fails" when its confidence is below 0.20. On a hard fail, reading trust is capped at **0.20**. ADD says "e.g. ≤ 0.25", and 0.20 satisfies that. | same |
| D-03 | Entity trust thresholds are ≥0.80 Trusted, 0.50–0.80 Estimated, <0.50 Quarantined. BRIEF and ADD agree on these. | same |
| D-04 | Entity trust dynamics: on a hard anomaly τ ← min(0.5·τ, ρ). On a soft anomaly τ ← τ·(1 − (0.8 − ρ)). Recovery happens only after a cooldown of 5 consecutive good readings **and** ≥ 10 sim-minutes, then by at most +0.02 per reading. | same |
| D-05 | Drift detection uses a one-sided CUSUM on cross-track deviation (allowance k = 0.2 km, soft alarm h₁ = 1.5 km, hard alarm h₂ = 3.0 km). It is part of the Route-consistency family. | `02_ARCHITECTURE.md` §5.4 |
| D-06 | Freshness: a source counts as fresh if its last trusted reading is no older than 3× its expected interval (vehicle 90 s, warehouse 3 min, port 15 min, weather 90 min). | `01_SRS.md` §3.4 |
| D-07 | Mode thresholds are based on F (fresh-source %) and C (trusted-coverage %). NORMAL: F ≥ 90 and C ≥ 85. DEGRADED: F < 90 or C < 85. BLIND: F < 50. RECOVERY: F ≥ 90 and C ≥ 85 after DEGRADED or BLIND; the twin returns to NORMAL after a 10 sim-minute stability window. Each transition requires the condition to hold for 60 sim-seconds (hysteresis). | same |
| D-08 | Blockage inference defaults: N = 4 vehicles, R = 2 km, T = 15 sim-minutes, speed < 5 km/h. The trust-weighted quorum Q is 3.2 (Σ τ over readings with τ ≥ 0.8). | `03_DATA_FLOW.md` §7 |
| D-09 | Cascade: 1 h step, 72 h horizon. Optimizer: 12 buckets of 6 h. Monte Carlo: 200 runs, seed from run id. | `02_ARCHITECTURE.md` §6 |
| D-10 | Optimizer: LP time-expanded multi-commodity min-cost flow in OR-Tools GLOP. A 5 s time limit applies. The fallback heuristic is k-shortest paths (k = 3) with greedy capacity allocation. Fleet assignment (SHOULD) uses CP-SAT. | `02_ARCHITECTURE.md` §7 |
| D-11 | Disruption probability = logistic model on corridor weather features, with hand-set initial coefficients based on IMD rainfall categories and Platt-scaled against ground-truth labels. The calibration is partly circular (see D-12). | `01_SRS.md` §3.6 |
| D-12 | **Honesty note:** the ground-truth world uses its own weather→disruption model, so calibrating against it only shows internal consistency, not real-world accuracy. We report this openly. Real-world calibration against historical Indian highway closures is listed as future work. | `08_EVALUATION_FRAMEWORK.md` §3.5 |
| D-13 | Plan robustness = fraction of Monte Carlo runs with service level ≥ 95%. Rating: High ≥ 0.90, Medium 0.70–0.90, Low < 0.70. | `01_SRS.md` §3.7 |

## E. Technology and platform

| ID | Assumption | Why |
|---|---|---|
| E-01 | **Redis Streams** is the event bus for Levels 2–4, behind a `Bus` interface, so Redpanda can be swapped in later. Raw events are also persisted to a Timescale hypertable for replay. | One piece of infrastructure covers bus, cache and pub/sub. Kafka is heavy for a 4-person hackathon. |
| E-02 | Postgres 16 with PostGIS and TimescaleDB, via the `timescale/timescaledb-ha` image (it includes PostGIS). Fallback: `postgis/postgis` with native partitioning. | One database for geospatial and time-series data. |
| E-03 | Cloud: **one AWS EC2 VM (t3.xlarge, ap-south-1 Mumbai)** running Docker Compose, with Caddy for automatic TLS. The fallback is Render. | Cheapest route to a live HTTPS URL. Compose works the same locally and in the cloud. |
| E-04 | The LLM is the Anthropic Claude API, model `claude-sonnet-5-5`, used only for explanations. If there is no API key or the call fails, a deterministic template narrative is used. | BRIEF F-45. It is cost-effective for short narratives. |
| E-05 | A domain for TLS (for example a free subdomain or `sslip.io`) is available by Level 3. | Needed for Let's Encrypt. |
| E-06 | Presentation laptops have Docker Desktop, so a fully offline presentation is possible with `docker compose --profile offline up`. | Covers risk R-09 (presentation day network failure). |

## F. Conflicts between the brief and the addendum, and how they were resolved

| ID | Conflict | Resolution |
|---|---|---|
| F-01 | BRIEF F-12 marks AIS cross-checking as S. ADD §4.2 marks it as C. | **ADD wins:** AIS vs supplier-ETA cross-check = COULD. AIS *ingestion* for port congestion (F-22) stays SHOULD. |
| F-02 | BRIEF F-03 says "architect as if Kafka/Redpanda". ADD §7 says the bus is decided in `06_TECH_STACK.md`. | Redis Streams behind a `Bus` interface. The upgrade path to Redpanda is documented. |
| F-03 | BRIEF §8.1 defines trust dynamics loosely. ADD §4.4 adds the hard-fail cap, cooldown and reasons list. | ADD wins. The trust spec is D-01 to D-05. |
| F-04 | The illustrative numbers in BRIEF §5 (426 shipments, ₹9.5L, ₹42,000, +1.7h, ₹8.48L) do not say which is which. | They are read as: loss if nothing = ₹9.50L, loss if action (under disruption) = ₹1.02L, loss avoided = ₹8.48L, action cost = ₹42,000, extra delay = +1.7 h. This set is used consistently in the wireframes: with P = 0.71, expected loss avoided = ₹6.02L and break-even P = 4.95%. All of them are marked illustrative. |
| F-05 | BRIEF §7.1 has no Fleet or Copilot stage. ADD §7 adds both. | ADD's flow is the authoritative end-to-end diagram. "AI Explanation layer" and "AI Copilot" are the same component (C13). |
| F-06 | BRIEF F-15 (ghost inventory) is S, but ADD §4.4 requires an optimizer discount for Estimated data (M). | The discount on Estimated / low-trust inventory is **M** (part of F-40/F-91). The three-level Verified/Estimated/Suspicious *UI breakdown* (F-15) stays S. |
| F-07 | BRIEF UC list stops at UC-09. ADD adds UC-10 (inferred blockage). | UC-10 added. |
| F-08 | BRIEF says "trust card" only indirectly. ADD F-92 makes it M. | The trust card is in the Node Detail and Trust Monitor wireframes. |
| F-09 | BRIEF marks F-74 (Prometheus + Grafana + alerts) as S (L4), but the Level 4 grading criterion requires "active monitoring and alert dashboards". | F-74 raised to **M at L4**. Kubernetes (F-75) stays C. |
| F-10 | BRIEF F-12 has a single priority "M (route + speed), S (weather, gate scan, AIS)". | Split into F-12a (M), F-12b (S) and F-12c (C, per F-01 above) so each part has one priority. |

## G. Out of scope for Level 1

- No application code was written. The only config stub is `docs/seed/seed_network.yaml`, which is a design artifact describing the synthetic network.
- The optional standalone HTML wireframe (BRIEF rule 6) was **not** produced. The ASCII wireframes are the deliverable.
