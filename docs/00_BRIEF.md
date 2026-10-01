# PNT1 — Logistics Network Digital Twin
## Level 1 Brief for Claude Code: Idea, Architecture, and Planning

> **How to use this file:** Put it in the repo root (e.g. `/docs/00_BRIEF.md`) and start Claude Code with:
> *"Read `docs/00_BRIEF.md` fully. Produce every Level 1 deliverable listed in Section 1, in the exact file structure given. Ask me nothing unless something is blocking; record assumptions in `docs/ASSUMPTIONS.md` instead."*

---

## 0. Role and working rules for Claude Code

You are acting as a principal engineer and product architect writing the foundation documents for a hackathon project. Follow these rules:

1. **Do not write application code in Level 1.** Only documents, diagrams, wireframes, schemas and config stubs needed to describe the design.
2. **Everything must trace back to the source problem statement** (Section 2). Every requirement in the SRS carries an ID and a "Source" field (`PDF` for the original statement, `ENH` for enhancements from this brief).
3. **Be opinionated.** Choose one option for each technology decision and justify it in one or two sentences. Note the fallback only if the choice is risky.
4. **Scope discipline.** The project is judged on one polished vertical slice, not breadth. Mark every requirement `MUST`, `SHOULD` or `COULD`. The MUST set has to be buildable by a small team in a hackathon timeframe.
5. **Be honest about data.** Any external data source must be labelled `LIVE`, `REPLAY` (recorded sample streamed in), or `MOCK`. Do not claim capabilities we will not actually build.
6. **Diagrams as code.** Use Mermaid (`.md` files with fenced `mermaid` blocks) so they render in GitHub. Wireframes use ASCII or Mermaid plus an optional standalone HTML file.
7. **Numbers in examples must be computable.** No figure shown in a UI mock or example may be hardcoded in the final product. Document which module computes it.

---

## 1. Level 1 deliverables (what you must produce)

Create this structure:

```
docs/
  00_BRIEF.md                      (this file, unchanged)
  01_SRS.md                        Software Requirements Specification
  02_ARCHITECTURE.md               System architecture + component descriptions
  03_DATA_FLOW.md                  Data flow diagrams (Mermaid), incl. trust pipeline
  04_DATA_MODEL.md                 Graph schema, DB schema, event schemas
  05_UI_WIREFRAMES.md              Screen-by-screen wireframes
  06_TECH_STACK.md                 Finalized stack with justification table
  07_ROADMAP.md                    Phased plan mapped to Levels 1-4 + task breakdown
  08_EVALUATION_FRAMEWORK.md       Metrics, benchmark suite, ground-truth design
  09_WALKTHROUGH_SCRIPT.md                5-minute presentation storyboard
  10_RISKS_AND_SCOPE.md            Risk register, cut-lines, non-goals
  ASSUMPTIONS.md                   Every assumption you made
  diagrams/                        Optional: exported .mmd source files
```

Acceptance criteria for Level 1 as a whole are in Section 14.

---

## 2. Source problem statement (authoritative)

**Statement ID:** PNT1  **Theme:** Transportation and Logistics
**Title:** Logistics Network Digital Twin

**Problem:** Build a network-scale digital twin to simulate and optimize end-to-end logistics operations, covering suppliers, warehouses, transport links, and inventory under dynamic disruption scenarios.

**Description (condensed, no meaning lost):** Global supply chains are highly sensitive to disruptions, requiring real-time visibility and proactive contingency planning. Create a comprehensive digital twin that mirrors the physical logistics ecosystem: suppliers, warehouses, transportation networks, live inventory and order flows. The system must run scenario-based optimizations to simulate supply chain shocks (port closures, extreme weather, sudden demand spikes) and dynamically recommend optimal cargo rerouting or inventory reallocation. Under strict production constraints, the architecture must defend against adversarial edge cases (maliciously spoofed transit data, corrupted supplier feeds, cascading node failures) and use measurable evaluation frameworks to guarantee simulation fidelity and actionable business value.

**Five stated requirements (PDF):**

| ID | Requirement | Plain meaning |
|---|---|---|
| P1 | Multi-Component Architecture | High-throughput ingestion plus graph-based modelling, synchronizing live telemetry across suppliers, warehouses and transit nodes |
| P2 | Scenario-Based Optimization | Advanced simulation engine for complex what-if scenarios, proactive contingency planning, automated resolution recommendations |
| P3 | End-to-End Network Visibility | Continuous real-time mapping of orders, stock levels and transport links; high-fidelity virtual replica |
| P4 | Adversarial Resilience | Robust validation for spoofed GPS, incomplete API payloads, large-scale data blackouts, without crashing the simulation |
| P5 | Production-Ready Evaluation | Measurable auditing frameworks tracking simulation accuracy vs actual physical outcomes; reliable, cost-effective decisions at enterprise scale |

**Hackathon levels the project will be graded against:**

- **Level 1 — Idea, Architecture, Planning:** SRS, architecture and data flow diagrams, UI wireframes, finalized tech stack and roadmap. *(This brief produces these.)*
- **Level 2 — Core Functionality:** MVP: DB schemas, primary business logic, essential APIs, functional app where users complete core tasks.
- **Level 3 — Intelligence, Security, Real Deployment:** advanced algorithms/AI, authentication and encryption, automated CI/CD, cloud launch.
- **Level 4 — Scalability, Reliability, Enterprise Readiness:** containerization for auto-scaling (Docker/Kubernetes), caching and query optimization, active monitoring and alert dashboards.

---

## 3. Product vision and positioning

**One-line pitch (use verbatim in the SRS intro):**
> *"A logistics twin that sees trouble coming, knows which data to trust, and can prove how accurate it is."*

**Core loop: SEE → TRUST → PREDICT → RESPOND → PROVE**

| Stage | Question | Capability |
|---|---|---|
| SEE | What is happening now? | Live digital twin of the network (graph + state) |
| TRUST | Can we believe the data? | Validation, cross-source triangulation, trust scores, degradation modes |
| PREDICT | What happens next? | External-signal early warning, cascade simulation, risk scoring |
| RESPOND | What should we do? | Constraint-aware optimizer, multi-futures comparison, human approval |
| PROVE | How good were we? | Ground-truth fidelity metrics, decision regret, resilience benchmark |

**Differentiation thesis:** Most teams will build a dashboard + map + reroute. PDF requirements P4 (trust) and P5 (measurement) are the most under-built, so they are our center of gravity. The satellite/weather layer supplies a proactive hook ("act before failure").

**Positioning statement:** Not a logistics dashboard. A resilient digital replica that predicts, simulates and responds to disruptions before they propagate, with measurable proof.

---

## 4. Feature set (prioritized)

Legend: **M** = MUST (vertical slice), **S** = SHOULD (if time), **C** = COULD (stretch / pitch only).

### 4.1 Twin core (P1, P3)
| ID | Feature | Pri | Notes |
|---|---|---|---|
| F-01 | Network graph of suppliers, ports, warehouses, customers, vehicles; edges = transport links with capacity, time, cost, CO₂ | M | ~40 nodes synthetic, on a realistic India road/port layout |
| F-02 | Live state: inventory, orders, shipments, node health, link status | M | Updated from event stream |
| F-03 | Streaming ingestion pipeline with schema validation | M | Simulated events; architect as if Kafka/Redpanda, presentation may use a lighter broker |
| F-04 | Map view with live vehicles and node status colors | M | |
| F-05 | Data-freshness heatmap over the graph | S | Key to blackout presentation |

### 4.2 Trust and adversarial resilience (P4)
| ID | Feature | Pri | Notes |
|---|---|---|---|
| F-10 | Validation layer: schema checks, range checks, physical plausibility (impossible speed/jump), incomplete payload handling | M | |
| F-11 | **Per-entity trust score** that degrades gradually and recovers (not a binary flag) | M | Feeds optimizer |
| F-12 | **Cross-source triangulation:** verify claimed truck position against independent evidence (weather consistency, road-graph route plausibility, port gate scan events, AIS vs supplier ETA) | M (route + speed plausibility), S (weather, gate scan, AIS) | Honest note: GPS is the truck's own telemetry; we do not claim "satellite positioning" as a separate source |
| F-13 | Quarantine: suspicious telemetry is isolated; twin continues on last trusted state | M | |
| F-14 | **Graceful degradation modes:** `NORMAL → DEGRADED → BLIND → RECOVERY`; ETA uncertainty bands widen as data ages; reconcile on recovery | M | |
| F-15 | Ghost-inventory / inventory confidence: Verified / Estimated / Suspicious; optimizer discounts low-trust stock | S | |
| F-16 | Attack Center: buttons to inject GPS spoof, fake inventory, corrupted supplier API, missing telemetry, node failure, mass blackout | M | |
| F-17 | "Would-have-chosen-worse" presentation: run optimizer on raw (attacked) vs trusted data and show the decision difference | M | Strongest trust presentation moment |

### 4.3 Prediction and proactive layer (P2, ENH)
| ID | Feature | Pri | Notes |
|---|---|---|---|
| F-20 | Weather early warning: forecast rainfall/cyclone/flood risk per corridor → disruption probability | M | `LIVE` via Open-Meteo (free), optionally IMD/NASA POWER |
| F-21 | Disaster alerts ingestion (GDACS, NASA FIRMS) | S | `LIVE` |
| F-22 | AIS vessel tracking for port congestion / ETA | S | `REPLAY` (recorded sample streamed), real feeds are paid/rate-limited |
| F-23 | Earth-observation flood/blocked-port detection overlay | C | `MOCK`: pre-processed flood mask shown on map; state clearly it is pre-computed |
| F-24 | Climate-adjusted lead-time learning: per-corridor/season transit multipliers (e.g. monsoon on specific highways) learned from delay/weather pairs | S | Small ML, plugs into F-20 |
| F-25 | Future Risk Radar: per-node risk score with explainable drivers (inventory trend, delays, reliability, dependency count) | S | Explain *why*, not just a number |

### 4.4 Simulation (P2)
| ID | Feature | Pri | Notes |
|---|---|---|---|
| F-30 | Scenario Lab: port closure, warehouse failure, supplier failure, demand spike, extreme weather, fleet failure, fuel-cost shock | M | |
| F-31 | **Cascading failure simulator** with time axis T+0 → T+72h, animated on the graph | M | Signature feature |
| F-32 | Blast-radius view: click any node → direct/indirect affected nodes, orders at risk, revenue exposure, recovery time | M | |
| F-33 | Compound-failure analysis: show combined impact ≠ sum of individual impacts | S | |
| F-34 | **Monte Carlo robustness:** ~200 runs with randomized durations/demand → P50/P90 outcomes, plan robustness rating | M | NumPy, cheap |
| F-35 | Time scrubber over simulated futures | M | |

### 4.5 Optimization and decisions (P2)
| ID | Feature | Pri | Notes |
|---|---|---|---|
| F-40 | Constraint-aware optimizer (OR-Tools): truck/warehouse/road capacity, deadlines, safety stock, supplier availability | M | Cheapest route is rejected if it causes stockout |
| F-41 | Multi-objective: cost, delay, stockout penalty, risk, CO₂; user-selectable objective (Cheapest / Fastest / Lowest Carbon / Lowest Risk / Balanced) | M | |
| F-42 | **Multi-futures comparison table:** do nothing / reroute / inventory transfer / hybrid, side by side | M | |
| F-43 | **Expected-value trigger + break-even probability:** act if `P(disruption) × loss_avoided > cost_of_action`; show break-even P and current P | M | See Section 8.4 |
| F-44 | Human-in-the-loop: Approve / Modify, recalculation on changed priorities | M | |
| F-45 | Explanation panel: LLM narrates the optimizer's result (optimizer decides, LLM never computes routes) | S | Structured optimizer output is the LLM's only input |
| F-46 | Recovery planner: phases Survive → Balance → Recover → Rebalance with time-to-recovery | S | |
| F-47 | Alert triage: deduplication, severity ranking, "top 3 actions now" | S | |

### 4.6 Structural analytics (P1, ENH)
| ID | Feature | Pri | Notes |
|---|---|---|---|
| F-50 | Fragility audit before any disruption: articulation points, betweenness centrality, min-cut supplier→customer cluster; ranked report | M | NetworkX |
| F-51 | "What would improve resilience?" simulate adding a link or supplier and show the resilience-score change | S | |
| F-52 | Network Resilience Score with clickable, explainable sub-scores (recovery time, redundancy, inventory buffer, supplier diversity, transport diversity) | S | |

### 4.7 Evaluation and audit (P5)
| ID | Feature | Pri | Notes |
|---|---|---|---|
| F-60 | Hidden **ground-truth "physical world" simulator** separate from the twin; twin only sees noisy/attacked observations | M | Makes fidelity a real number |
| F-61 | Fidelity metrics: ETA MAE, inventory error, stockout-prediction precision/recall | M | |
| F-62 | **Decision regret:** cost of twin's plan vs plan optimal with perfect information | M | |
| F-63 | **Chaos/attack benchmark suite:** seeded, reproducible, ~10 scenarios scored on detection rate, false-positive rate, time-to-detect, decision quality vs oracle | M | Single "Resilience Benchmark" table |
| F-64 | Decision audit trail: every recommendation logged with inputs, trust scores, model/optimizer version, approver; replayable | M | |
| F-65 | Counterfactual replay ("what if we had reacted 6h earlier?") | C | |
| F-66 | Twin-vs-reality drift tracking over time | S | |

### 4.8 Platform (Levels 3 and 4)
| ID | Feature | Pri | Notes |
|---|---|---|---|
| F-70 | Authentication (JWT) with roles: Viewer, Operator, Admin | M (L3) | |
| F-71 | Encryption in transit (TLS) and secrets management; rate limiting on ingestion | M (L3) | |
| F-72 | Docker Compose, CI/CD (GitHub Actions), cloud deploy | M (L3) | |
| F-73 | Redis caching, query optimization, health checks, structured logs | M (L4) | |
| F-74 | Prometheus + Grafana monitoring with alert rules | S (L4) | |
| F-75 | Kubernetes manifests with HPA | C (L4) | Only if time remains; Docker Compose is sufficient to show scaling design |

### 4.9 Explicit non-goals
Blockchain, generic chatbot, 15 dashboards, 3D twin (unless cheap), mobile app, real IoT hardware, fancy landing page, ML models that do not change a decision, Kubernetes purely for show.

---

## 5. Satellite and external-signal layer (scope contract)

| Signal | Use | Mode | Free source |
|---|---|---|---|
| Weather forecast (rain, wind, cyclone) | Corridor disruption probability, lead-time adjustment | LIVE | Open-Meteo, IMD, NASA POWER |
| Disaster alerts (floods, cyclones, fires) | Early warning feed | LIVE | GDACS, NASA FIRMS |
| AIS vessel data | Port congestion, ship ETA vs supplier-reported ETA | REPLAY | Recorded sample stream |
| Earth-observation flood/port-damage imagery | Overlay of flooded roads / blocked ports | MOCK | Pre-processed mask (Sentinel-1/2 is real but heavy) |
| "Satellite GNSS positioning" | Do not present as separate source | n/a | Truck GPS is its own telemetry; the value is *cross-validating* it |

**Canonical proactive workflow (must be implemented end to end):**

1. Forecast shows extreme rainfall on a corridor (e.g. Hyderabad → Vijayawada) in ~8 hours.
2. System computes disruption probability (e.g. 71%).
3. Twin simulates **do nothing** vs **reroute now**, with Monte Carlo.
4. System outputs computed numbers: shipments affected, warehouses at stockout risk, expected loss, action cost, stockouts avoided, **expected** loss avoided (probability-weighted).
5. Recommendation: reroute now, with break-even probability shown.

All figures in this workflow are produced by the simulator. The example numbers (426 shipments, ₹9.5L, ₹42,000, +1.7h, ₹8.48L) are illustrative placeholders for wireframes only.

---

## 6. Users and use cases

**Personas**
- **Operations Controller (primary):** watches the network, approves recovery plans.
- **Supply Chain Planner:** runs stress tests and what-ifs ahead of time, reads the fragility report.
- **Security/Data Quality Analyst:** reviews quarantined data, trust scores, attack reports.
- **Executive/Judge (presentation viewer):** wants measurable business impact and proof of accuracy.

**Key use cases (write as full use-case specs in the SRS):**
UC-01 Monitor live network · UC-02 Receive proactive weather-driven warning · UC-03 Run a disruption scenario and view the cascade · UC-04 Compare strategies and approve a plan · UC-05 Detect and quarantine spoofed/corrupted data · UC-06 Operate through a blackout and recover · UC-07 Run a network stress test / fragility audit · UC-08 Review fidelity metrics and the resilience benchmark · UC-09 Audit a past decision.

---

## 7. Architecture (what to design and document)

### 7.1 Logical layers (design to this shape)

```
Dashboard / Control Room (map, cascade view, futures table, approve, benchmark)
        │
AI Explanation layer (LLM narrates structured optimizer output only)
        │
Decision layer: constraint optimizer + EV trigger + Monte Carlo
        │
Simulation engine: disruption scenarios, cascade propagation, compound effects
        │
Digital Twin engine: graph + live state + confidence layer + analytics
        │
Trust layer: validation → triangulation → trust score → quarantine → degradation mode
        │
Ingestion layer: event stream + external signal connectors
        │
Sources: supplier APIs, truck GPS/IoT, orders, inventory, weather, AIS, alerts
        │
[Separate] Ground-truth physical-world simulator + evaluation harness
```

### 7.2 Components to specify in `02_ARCHITECTURE.md`

For each: responsibility, inputs, outputs, key interfaces, scaling note, failure behavior.

1. **Synthetic world generator / ground-truth simulator** (hidden truth, emits noisy observations; also replays recorded AIS)
2. **Ingestion gateway** (validation, rate limiting, dead-letter handling)
3. **Stream/event bus**
4. **Trust & validation service** (plausibility, triangulation, trust-score state machine)
5. **Twin state service** (graph store + current state + confidence)
6. **Graph analytics service** (centrality, articulation points, min-cut, blast radius)
7. **External signal service** (weather/alerts connectors → corridor risk)
8. **Risk/prediction service** (disruption probability, lead-time multipliers, node risk)
9. **Simulation service** (cascade engine, Monte Carlo runner)
10. **Optimization service** (OR-Tools models, objective presets, EV trigger)
11. **Decision/audit service** (approval workflow, audit log, replay)
12. **Evaluation service** (fidelity metrics, regret, benchmark runner)
13. **Explanation service** (LLM wrapper with strict structured input)
14. **API gateway / backend** (REST + WebSocket/SSE, JWT auth)
15. **Frontend** (control room)
16. **Observability stack** (logs, metrics, health, alerts)

Recommend a **modular monolith** (clear module boundaries, one deployable) for the hackathon, with explicit notes on which modules split into services at Level 4. Justify this choice. Show how the same modules map to separate containers in the Docker Compose design.

### 7.3 Required diagrams (Mermaid) in `02_ARCHITECTURE.md` and `03_DATA_FLOW.md`

1. System context (C4 level 1)
2. Container/component diagram (C4 level 2)
3. **End-to-end data flow** (source → validation → trust → twin → simulation → optimizer → human → action → twin update → evaluation)
4. **Trust pipeline flow** including quarantine and fallback to last trusted state
5. **Degradation mode state machine** (`NORMAL/DEGRADED/BLIND/RECOVERY` with transition conditions)
6. **Cascade propagation sequence diagram** (port closure → shipments → warehouse inventory → production/customer orders)
7. **Proactive workflow sequence** (forecast → probability → simulate → EV decision → approval)
8. **Evaluation loop** (ground truth vs twin → metrics → benchmark)
9. Deployment diagram for Level 3 (cloud) and Level 4 (scaled)

---

## 8. Core algorithms and formulas (specify in SRS/Architecture)

### 8.1 Trust score
Per entity (truck, supplier feed, warehouse inventory feed), trust ∈ [0,1].
- Inputs: schema completeness, physical plausibility (implied speed vs limit, jump distance), route plausibility on road graph, consistency with independent signals (weather, gate scans, AIS), historical reliability of the source.
- Dynamics: multiplicative decay on anomalies, slow additive recovery on consistent data. Define thresholds: `≥0.8 trusted`, `0.5–0.8 estimated`, `<0.5 quarantined`.
- Consumers: twin state (which value to use), optimizer (discount low-trust inventory), UI (color coding).
Provide pseudocode and a worked numeric example.

### 8.2 Degradation modes
- `NORMAL`: data fresh and trusted.
- `DEGRADED`: some sources stale or low trust; widen uncertainty, prefer trusted sources.
- `BLIND`: large-scale blackout; run on last trusted state + forecasts + learned dynamics; uncertainty bands grow with data age.
- `RECOVERY`: data returns; reconcile, compare predicted vs actual, then return to NORMAL after a stability window.
Define entry/exit conditions as explicit thresholds (freshness %, trust coverage %).

### 8.3 Cascade simulation
Discrete-time (e.g. 1h step, 72h horizon) propagation on the graph: link/node failure → shipment delay → inbound reduction → inventory depletion vs safety stock → production/fulfilment at risk → order impact. Include demand, lead time and capacity effects and allow concurrent (compound) failures. Output: timeline of states, orders at risk, stockout times, cost, delay.

### 8.4 Expected-value trigger
```
Expected loss avoided  = P(disruption) × (loss_if_nothing − loss_if_action_under_disruption)
Net benefit            = Expected loss avoided − (cost_of_action × 1)   [+ residual cost if no disruption occurs]
Act if                 Net benefit > 0
Break-even probability = cost_of_action / (loss_if_nothing − loss_if_action_under_disruption)
```
Define the exact treatment of cost incurred when the disruption does not occur (action cost is paid regardless). Display break-even P vs current P and a regret metric. Document how a forecast is converted to a probability (calibration approach, even if simple) because judges will ask how 71% becomes rupees.

### 8.5 Optimizer formulation
Decision variables: flow per link per period, inventory transfers between warehouses, supplier activation, mode choice.
Minimize: `w1·cost + w2·delay + w3·stockout_penalty + w4·risk + w5·CO₂` (weights set by objective preset).
Subject to: link/vehicle capacity, warehouse capacity, safety stock, delivery deadlines, supplier availability, flow conservation, blocked nodes/links.
Low-trust inventory enters constraints at its **discounted** verified quantity. Specify model type (LP/MILP/min-cost-flow variant) and the solver time limit; define a fast fallback heuristic.

### 8.6 Monte Carlo
~200 runs sampling disruption duration, demand multiplier, transit delay. Report P50/P90 for cost, delay, orders at risk. Define **plan robustness** (e.g. fraction of runs with service level ≥ target). Seeded for reproducibility.

### 8.7 Structural fragility
Articulation points, betweenness centrality, supplier→customer-cluster min-cut, percent of downstream flow through each node. Resilience score = documented weighted combination of sub-scores (each explainable).

---

## 9. Data model (for `04_DATA_MODEL.md`)

Produce (a) a graph schema, (b) relational/time-series DB schema with DDL, (c) event/message schemas as JSON Schema, (d) an ER diagram in Mermaid.

**Graph:** nodes `Supplier, Port, Warehouse, Factory(optional), CustomerCluster, Vehicle`; edges `TransportLink(mode, capacity, base_time, cost, co2, status)`, `Supplies`, `Serves`.

**Key entities and attributes (minimum):**
- `Node(id, type, name, lat, lon, capacity, status, health)`
- `Link(id, from, to, mode, capacity, base_time_h, cost_per_unit, co2_per_unit, status, corridor_id)`
- `InventoryPosition(node_id, sku, qty_reported, qty_verified, safety_stock, confidence, updated_at)`
- `Order(id, customer_id, sku, qty, due_at, priority, status, value)`
- `Shipment(id, order_ids, vehicle_id, route_links, eta, eta_uncertainty, status)`
- `Telemetry(entity_id, ts, lat, lon, speed, payload_hash, source_id)`
- `TrustState(entity_id, trust, mode, last_trusted_state_ref, reasons[])`
- `ExternalSignal(id, type, corridor_id, ts, severity, probability, source, mode[LIVE/REPLAY/MOCK])`
- `Scenario(id, type, params, seed)`, `SimulationRun(id, scenario_id, results, p50, p90)`
- `Recommendation(id, strategies[], chosen, inputs_snapshot, trust_snapshot, optimizer_version, created_at)`
- `Decision(id, recommendation_id, approver, action, ts)`  ← audit trail
- `EvaluationResult(id, suite, metric, value, ts)`

**Event types:** `telemetry.vehicle`, `feed.supplier_inventory`, `order.created/updated`, `signal.weather`, `signal.alert`, `signal.ais`, `twin.state_changed`, `trust.anomaly`, `mode.changed`, `scenario.run`, `recommendation.created`, `decision.approved`.

Include a **seed network definition**: ~40 nodes across India (suppliers, Mundra/Chennai/Mumbai-type ports, warehouses in Hyderabad/Bengaluru/Pune-type hubs, customer clusters), with edges and realistic base times. Mark it synthetic.

---

## 10. UI wireframes (for `05_UI_WIREFRAMES.md`)

Produce an ASCII/Mermaid wireframe plus a short interaction spec for each screen. Also list the design tokens (status colors: green trusted/normal, yellow estimated/degraded, red suspicious/failed, blue simulated).

1. **Control Room (home):** map + graph overlay, node/link status, live vehicles, network mode badge (`NORMAL/DEGRADED/BLIND/RECOVERY`), top-3 actions panel, alert feed, freshness heatmap toggle.
2. **Early Warning:** corridor risk list, forecast overlay, probability, "simulate now" button.
3. **Scenario Lab:** scenario picker, parameters, compound-scenario builder, **Run** button.
4. **Cascade View:** animated graph + **time scrubber T+0…T+72h**, KPI ribbon (delay, cost, orders affected, inventory at risk).
5. **Strategies / Multi-Futures:** side-by-side table (do nothing / reroute / transfer / hybrid) with cost, delay, stockout risk, orders saved, P50/P90, robustness, break-even probability; objective selector; **Approve / Modify**.
6. **Why This Plan (Explanation panel):** constraint checks ✓/✕ and LLM narrative.
7. **Blast Radius / Node Detail:** dependency tree, exposure, trust history, inventory confidence breakdown.
8. **Attack Center & Trust Monitor:** inject-attack controls, quarantine queue, per-entity trust chart, raw-vs-trusted decision comparison.
9. **Fragility & Resilience Report:** ranked critical nodes, min-cut, resilience score with clickable sub-scores, "add link" what-if.
10. **Evaluation & Benchmark:** fidelity metrics, decision regret, Resilience Benchmark table, drift chart.
11. **Audit Trail:** decision log with replay.
12. **Login / Role switch** (minimal).

---

## 11. Tech stack (finalize in `06_TECH_STACK.md` with a justification table)

Start from this recommendation; confirm or change with a one-line reason, and flag anything that is over-engineered for the timeline.

| Layer | Proposed | Notes |
|---|---|---|
| Frontend | Next.js + TypeScript + Tailwind, MapLibre/Mapbox + deck.gl, Recharts | Map + animated cascade |
| Backend | FastAPI (Python) | Shares language with optimization/ML |
| Realtime to UI | WebSocket or SSE | |
| Database | PostgreSQL + PostGIS (+ TimescaleDB if cheap) | Geospatial + time series |
| Graph | NetworkX in-memory for analytics; Postgres for persistence | Neo4j is optional, justify if included |
| Optimization | Google OR-Tools | |
| ML | scikit-learn, XGBoost/LightGBM (lead-time, risk), Isolation Forest (anomaly) | Only where it changes a decision |
| Simulation/Monte Carlo | NumPy (+ SimPy optional) | |
| Streaming | Redpanda/Kafka **or** Redis Streams for the presentation | State the tradeoff |
| Cache | Redis | |
| LLM | Anthropic Claude API for explanations only | Structured JSON in, prose out |
| Auth/Security | JWT, bcrypt/argon2, TLS, input validation, rate limiting | |
| DevOps | Docker Compose, GitHub Actions CI/CD, cloud (pick one: AWS/GCP/Azure/Render/Fly) | |
| Monitoring | Prometheus + Grafana, structured logs | |
| Testing | pytest, Playwright (UI smoke), seeded benchmark suite | |

---

## 12. Roadmap (for `07_ROADMAP.md`)

Produce a phased plan with owners (role-based, since team size is unknown: assume 4 people: Backend/Sim, Optimization/ML, Frontend, DevOps/QA), dependencies, and a critical path. Include a Gantt-style Mermaid chart and a task table with estimates.

**Build order (vertical slice first):**
1. Synthetic network + hidden ground-truth simulator
2. Ingestion + validation + trust scores + degradation modes
3. Twin state + graph analytics (fragility, blast radius)
4. Weather early warning → disruption probability → cascade simulation
5. Optimizer with constraints + objective presets + Monte Carlo + EV trigger
6. Control-room UI (map, scrubber, futures table, approve, explanation)
7. Evaluation/benchmark page (fidelity, regret, resilience table)
8. Deploy: Docker Compose, CI, cloud, basic monitoring

**Map to hackathon levels:**
| Level | Focus | Exit criteria |
|---|---|---|
| 1 | Docs (this phase) | All Section 1 deliverables pass Section 14 |
| 2 | MVP vertical slice | Steps 1, 3, 4 (basic), 5 (basic), 6 (core) working locally with seed data |
| 3 | Intelligence, security, deployment | Trust layer, Monte Carlo, weather layer, JWT + TLS, CI/CD, live cloud URL |
| 4 | Scale and reliability | Containers, Redis caching, monitoring/alerts, load test results, optional K8s |

Define **cut-lines**: what is dropped first if time runs short (order: K8s → EO imagery → AIS → counterfactual replay → LLM explanations → extra scenarios).

---

## 13. Evaluation framework (for `08_EVALUATION_FRAMEWORK.md`)

- **Ground truth design:** separate hidden simulator producing true positions, inventory, demand and outcomes; twin receives noisy/attacked observations only.
- **Fidelity metrics:** ETA MAE/MAPE, inventory error (verified vs true), stockout prediction precision/recall and lead time, cascade-prediction accuracy vs ground truth.
- **Decision metrics:** decision regret vs perfect-information optimum, service level, cost, delay, CO₂, orders saved.
- **Security/resilience metrics:** detection rate, false-positive rate, time-to-detect, time-to-recover, degradation-mode correctness.
- **Benchmark suite (seeded, ≥10 scenarios):** GPS spoof, fake inventory, corrupted supplier feed, incomplete payloads, node blackout, mass blackout, port closure, demand spike, weather event, and one compound scenario. Output one Resilience Benchmark table.
- **Performance/scale metrics:** ingestion events/sec, p95 API latency, simulation and optimization runtime, target values per level.
- **Reproducibility:** fixed seeds, versioned scenarios, one command to run the full benchmark.

---

## 14. Acceptance criteria for Level 1

The Level 1 output is complete only if:

1. `01_SRS.md` follows IEEE-830-style structure (purpose, scope, definitions, overall description, functional requirements with IDs and MoSCoW priority and source tag, non-functional requirements with measurable targets, external interfaces, constraints, use cases, traceability matrix mapping **PDF requirements P1–P5 → requirement IDs → components → tests**).
2. Every PDF requirement (P1–P5) and every Level 1–4 requirement is traceable in the matrix with no orphan.
3. All nine diagrams in Section 7.3 exist and render as valid Mermaid.
4. Data model includes DDL, JSON schemas for events, and a seed-network definition.
5. Wireframes exist for all 12 screens with interaction notes and the status-color spec.
6. Tech stack table has one justified decision per layer and cites fallback only where risky.
7. Roadmap has a critical path, owners, estimates and explicit cut-lines.
8. Evaluation framework defines each metric with a formula and how it is computed.
9. Every external data source is labelled `LIVE`, `REPLAY` or `MOCK`.
10. `ASSUMPTIONS.md` lists all assumptions; `10_RISKS_AND_SCOPE.md` has at least 10 risks with mitigation.
11. Non-functional requirements include at least: ingestion throughput target, p95 API latency, simulation runtime budget, availability target, security (authN/Z, encryption), and graceful degradation under data loss.
12. No illustrative number in any wireframe is presented as a real result.

---

## 15. Walkthrough Script (expand in `09_WALKTHROUGH_SCRIPT.md`, ~5 minutes)

1. **Normal state:** network green, mode `NORMAL`, fragility report shows the most critical node.
2. **Early warning:** forecast flags a corridor; disruption probability shown; break-even vs current probability displayed.
3. **Cascade + futures:** simulate; scrub T+0→T+72h; four strategies compared with P50/P90.
4. **Attack:** inject spoofed GPS; it is quarantined, trust drops; show the optimizer *would have* chosen worse with the bad data.
5. **Blackout:** trigger mass data loss; mode goes `DEGRADED → BLIND`, uncertainty bands widen; data returns, `RECOVERY → NORMAL`.
6. **Approve:** operator approves the plan; twin updates; audit entry created.
7. **Proof:** evaluation page shows fidelity metrics, decision regret and the Resilience Benchmark table.

Write this as a storyboard with: what the presenter says, what is on screen, which backend modules fire, and a fallback if a live API fails (use recorded replay).

---

## 16. Risks to cover in `10_RISKS_AND_SCOPE.md` (minimum)

Scope creep · external API downtime/rate limits (mitigate with replay cache) · unrealistic synthetic data · optimizer runtime too slow for live presentation (time limit + heuristic fallback) · LLM hallucinating decisions (structured input, never computes) · false positives in anomaly detection · cloud cost/credit limits · team skill gaps · presentation day network failure (offline mode) · claiming data capabilities we do not have (labelling policy) · Monte Carlo runtime · UI animation performance on large graphs.

---

## 17. Final instruction to Claude Code

Produce all files in Section 1. Work in this order: `ASSUMPTIONS.md` (draft) → `06_TECH_STACK.md` → `04_DATA_MODEL.md` → `02_ARCHITECTURE.md` → `03_DATA_FLOW.md` → `01_SRS.md` → `08_EVALUATION_FRAMEWORK.md` → `05_UI_WIREFRAMES.md` → `07_ROADMAP.md` → `09_WALKTHROUGH_SCRIPT.md` → `10_RISKS_AND_SCOPE.md`. Finish by re-checking every item in Section 14 and append a short `docs/LEVEL1_CHECKLIST.md` showing pass/fail per item with file references.
