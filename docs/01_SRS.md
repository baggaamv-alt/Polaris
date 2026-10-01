# 01 — Software Requirements Specification (SRS)

**Project:** PNT1 — Logistics Network Digital Twin · **Theme:** Transportation and Logistics
**Structure:** IEEE-830 style · **Version:** 1.0 (Level 1) · **Date:** 2026-10-01

---

## 1. Introduction

### 1.1 Purpose
This SRS defines the functional and non-functional requirements of PNT1, a network-scale digital twin that simulates and optimizes end-to-end logistics operations under dynamic disruptions and adversarial data. Its readers are the build team (for Levels 2–4) and the judges (for traceability and scope).

### 1.2 Scope
> *"A logistics twin that sees trouble coming, knows which data to trust, and can prove how accurate it is."*

PNT1 mirrors a **synthetic** Indian logistics network: 40 nodes, 92 links and about 120 vehicles. It ingests streaming telemetry and external signals, decides how much to trust each data point, maintains a live twin, predicts disruptions from weather and alerts, simulates cascading failures, recommends constraint-aware reroutes and inventory transfers for a human to approve, and measures its own fidelity against a hidden ground-truth world.

The core loop is **SEE → TRUST → PREDICT → RESPOND → PROVE**. The project is judged on one polished vertical slice, so every requirement carries a MoSCoW priority.

**In scope:** synthetic world and telemetry simulator; ingestion; Trust Engine; twin; graph analytics; weather/alert early warning; cascade and Monte Carlo simulation; optimizer; human approval; audit; evaluation and benchmark; auth; deployment; monitoring.
**Out of scope (non-goals):** blockchain, a generic chatbot, 15 dashboards, a 3D twin, a mobile app, real IoT hardware, a fancy landing page, ML that does not change a decision, and Kubernetes purely for show. Also out: real carrier integrations and real payment or ERP systems.

### 1.3 Definitions, acronyms, abbreviations

| Term | Definition |
|---|---|
| Twin | The system's *belief* about the network state (C05). |
| Ground truth / world | The hidden simulator state (C01) that the twin never reads. |
| Observation | A reading emitted by the world with noise and possibly an attack. |
| Reading trust ρ | Trust of a single reading ∈ [0,1] after checks and the hard-fail cap. |
| Entity trust τ | Stateful trust of a source entity (truck, feed) ∈ [0,1]. |
| Trusted / Estimated / Quarantined | τ ≥ 0.80 / 0.50–0.80 / < 0.50. |
| Mode | Network degradation mode: NORMAL, DEGRADED, BLIND, RECOVERY. |
| F, C | Fresh-source %, trusted-coverage %. |
| EV trigger | Expected-value act/don't-act rule (§3.6). |
| p* | Break-even disruption probability. |
| P50 / P90 | Median / 90th percentile over Monte Carlo runs. |
| Regret | Realised cost of the chosen plan minus the cost of the perfect-information plan. |
| LIVE / REPLAY / MOCK | Data-mode labels: live external feed / recorded sample streamed in / pre-computed or fabricated stand-in. |
| DLQ | Dead-letter queue. |
| MoSCoW | M = MUST, S = SHOULD, C = COULD. |
| Source tag | `PDF` = original problem statement; `ENH` = enhancement from the brief or addendum. |
| Cx | Component ID in `02_ARCHITECTURE.md` §4. |
| TS-x / BM-x | Test ID / benchmark scenario ID (§6, `08_EVALUATION_FRAMEWORK.md`). |

### 1.4 References
`00_BRIEF.md`, `00a_ADDENDUM_TELEMETRY_TRUST.md`, `02_ARCHITECTURE.md`, `03_DATA_FLOW.md`, `04_DATA_MODEL.md`, `05_UI_WIREFRAMES.md`, `06_TECH_STACK.md`, `07_ROADMAP.md`, `08_EVALUATION_FRAMEWORK.md`, `ASSUMPTIONS.md`. IEEE Std 830-1998.

### 1.5 Overview
§2 describes the product as a whole. §3 lists the specific requirements (interfaces, functional requirements, algorithmic specifications, NFRs, constraints). §4 gives the use cases. §5 is the traceability matrix. §6 is the test catalogue.

---

## 2. Overall description

### 2.1 Product perspective
PNT1 is a standalone system: a modular monolith with separate process roles (`02_ARCHITECTURE.md` §1). Its only external dependencies are Open-Meteo, GDACS/FIRMS and the Claude API, and each has an offline fallback. The world simulator stands in for real fleets, WMS and supplier systems, and uses the same ingestion interface a real integration would use.

### 2.2 Product functions (core loop)

| Stage | Question | Functions |
|---|---|---|
| SEE | What is happening now? | Live twin (graph + state), map, live telemetry KPIs, freshness heatmap |
| TRUST | Can we believe the data? | Validation, triangulation, trust scores, quarantine, degradation modes, Attack Center |
| PREDICT | What happens next? | Weather/alert early warning, disruption probability, cascade simulation, risk radar, blockage inference |
| RESPOND | What should we do? | Constraint optimizer, objective presets, multi-futures table, EV trigger, approve/modify, Copilot explanation |
| PROVE | How good were we? | Ground-truth fidelity, decision regret, Resilience Benchmark, audit trail with replay |

### 2.3 User classes

| Persona | Role (RBAC) | Main use cases |
|---|---|---|
| Operations Controller (primary) | Operator | UC-01, UC-02, UC-04, UC-06, UC-10 |
| Supply Chain Planner | Operator | UC-03, UC-07 |
| Security / Data Quality Analyst | Operator | UC-05, UC-06 |
| Executive / Judge | Viewer (Admin for truth views in presentation) | UC-08, UC-09 |
| Administrator | Admin | users, source keys, benchmark runs |

### 2.4 Operating environment
Server: Linux containers (Docker Compose) on one AWS EC2 VM (L3) or several (L4). Client: current Chrome, Edge or Firefox at 1440×900 or larger. A laptop is also supported for the offline presentation.

### 2.5 Design and implementation constraints
Hackathon timeline of 21 days and a team of 4 (ASSUMPTIONS A-01/02). Free or open-source dependencies only, apart from the cloud VM and the Claude API. No real IoT hardware. All data is synthetic or clearly labelled. The optimizer decides, and the LLM only narrates.

### 2.6 Assumptions and dependencies
See `ASSUMPTIONS.md`. The main ones are: synthetic network (B-01), 60× sim clock (B-06), three independent fleets (B-07), Open-Meteo availability with replay fallback (C-01), and the honesty note on calibration (D-12).

### 2.7 Data-source labelling policy

| Source | Mode | Fallback |
|---|---|---|
| Vehicle, warehouse, shipment and port telemetry | Synthetic (world simulator) | — |
| Supplier feeds, orders | Synthetic (world simulator) | — |
| Weather forecast (Open-Meteo) | `LIVE` | `REPLAY` (recorded responses) |
| Disaster alerts (GDACS, FIRMS) | `LIVE` | `REPLAY` |
| AIS vessel positions | `REPLAY` | — |
| EO flood / port-damage mask | `MOCK` | — |
| "Satellite positioning" | **Not a source.** Truck GPS is the truck's own telemetry and is cross-validated through the "Geospatial / road-network match" check | — |

---

## 3. Specific requirements

### 3.1 External interface requirements

**3.1.1 User interfaces:** 12 screens (`05_UI_WIREFRAMES.md`): Control Room, Early Warning, Scenario Lab, Cascade View, Strategies, Why This Plan, Node Detail / Blast Radius, Attack Center & Trust Monitor, Fragility Report, Evaluation & Benchmark, Audit Trail, Login. Status colours: green = trusted/normal, yellow = estimated/degraded, red = suspicious/failed, blue = simulated. Each colour is paired with an icon so the UI is colour-blind safe.

**3.1.2 Software interfaces:**

| Interface | Direction | Protocol | Contract |
|---|---|---|---|
| Ingestion API | in | HTTPS `POST /ingest/batch` | envelope JSON Schema (`04_DATA_MODEL.md` §6.1), per-source key, optional HMAC |
| Open-Meteo Forecast API | out | HTTPS GET | hourly `precipitation`, `wind_gusts_10m`, `weather_code` |
| GDACS / FIRMS | out | HTTPS GET (RSS / GeoJSON / CSV) | alert geometry + level |
| Claude API | out | HTTPS (Anthropic SDK) | structured JSON in, text out; 4 s timeout |
| REST + WebSocket API | out to UI | HTTPS / WSS | OpenAPI 3.1 generated by FastAPI |
| Prometheus | out | HTTP `/metrics` | Prometheus text format |

**3.1.3 Communications:** TLS 1.2+ for all external traffic. Internal traffic stays on the Docker network. WebSocket carries 1 Hz state diffs and events.

**3.1.4 Hardware:** none. No physical IoT devices are used.

### 3.2 Functional requirements

Columns: **ID · Requirement ("The system shall…") · Pri · Source · Component(s) · Verified by**. Priorities follow BRIEF §4 and ADD §9. Where they were resolved differently, the change is noted in `ASSUMPTIONS.md` §F.

#### 3.2.1 Twin core (P1, P3)

| ID | Requirement | Pri | Src | Comp | Test |
|---|---|---|---|---|---|
| F-01 | Model a network graph of Suppliers, Ports, Warehouses, Factories, CustomerClusters and Vehicles. Edges are TransportLinks with mode, capacity, time, cost, CO₂ and status. Load it from the seed definition (40 nodes, 92 links, synthetic India layout). | M | PDF P1/P3 | C05, C06 | TS-TWIN-01 |
| F-02 | Maintain live state (inventory per node and SKU, orders, shipments with ETA bands, node health, link status) updated from the event stream, and publish diffs to the UI at ≥ 1 Hz. | M | PDF P3 | C05, C14 | TS-TWIN-02, TS-PERF-03 |
| F-03 | Ingest streaming events through a gateway with envelope schema validation, per-source authentication, rate limiting and a dead-letter queue, onto an event bus with consumer groups. | M | PDF P1 | C02, C03 | TS-ING-01..04 |
| F-04 | Show a map with the graph overlay, live vehicles and node/link status colours. | M | PDF P3 | C15 | TS-UI-01 |
| F-05 | Show a data-freshness heatmap over the graph (per-source age vs threshold). | S | ENH | C04, C15 | TS-UI-06 |

#### 3.2.2 Telemetry simulator (ADD §3, P1/P4/P5)

| ID | Requirement | Pri | Src | Comp | Test |
|---|---|---|---|---|---|
| T-01 | Generate per-vehicle GPS/speed streams that follow road-link geometry, with speed profiles, stops and traffic variation. | M | ENH | C01 | TS-WORLD-01 |
| T-02 | Generate warehouse inventory feeds from true stock movements with configurable measurement noise and missing-update probability. | M | ENH | C01 | TS-WORLD-02 |
| T-03 | Generate shipment and port telemetry consistent with vehicles and network status. | M | ENH | C01 | TS-WORLD-03 |
| T-04 | Sustain ≥ 5,000 events/min in the presentation configuration, scalable to the NFR-01 load target. | M | ENH | C01 | TS-PERF-01 |
| T-05 | Be seeded and deterministic: the same run ID, seed and command log reproduce an identical stream (hash-equal). | M | ENH | C01 | TS-WORLD-04 |
| T-06 | Provide 10 attack injectors callable from the Attack Center and the benchmark harness: `gps_spoof_teleport`, `gps_spoof_drift`, `speed_spike`, `inventory_fake`, `feed_corrupt`, `payload_incomplete`, `duplicate_replay`, `entity_blackout`, `mass_blackout`, `coordinated_stop_spoof`. | M | ENH | C01, C14 | BM-01..BM-10 |
| T-07 | Provide a replay mode that streams a recorded file (AIS, offline presentation). | S | ENH | C01, C07 | TS-WORLD-05 |
| T-08 | Attach a hidden ground-truth label (`is_attacked`, `injector`, `true_value`) to every observation. Store it only in the `truth` schema, never in the stream. | M | ENH | C01, C12 | TS-SEC-04, TS-WORLD-06 |

#### 3.2.3 Trust and adversarial resilience (P4)

| ID | Requirement | Pri | Src | Comp | Test |
|---|---|---|---|---|---|
| F-10 | Validate every reading: schema, ranges, physical plausibility (implied speed, jump distance), and incomplete-payload handling. | M | PDF P4 | C04 | TS-TRUST-05, BM-03, BM-06 |
| F-11 | Maintain a per-entity trust score in [0,1] that decays gradually on anomalies and recovers slowly after a cooldown. It is not a binary flag. | M | PDF P4 | C04 | TS-TRUST-06 |
| F-12a | Cross-validate truck positions against the road graph and route plausibility, and speed against kinematics. | M | PDF P4 | C04 | BM-01, BM-02, BM-03 |
| F-12b | Cross-validate against weather/alert context and port gate-scan events. | S | ENH | C04, C07 | TS-TRUST-09 |
| F-12c | Cross-validate AIS vessel positions against supplier-reported ETA. | C | ENH | C04, C07 | TS-TRUST-10 |
| F-13 | Quarantine suspicious telemetry. The twin continues on the last trusted state, and quarantined readings never write to twin state. | M | PDF P4 | C04, C05 | TS-TRUST-07 |
| F-14 | Operate in degradation modes NORMAL → DEGRADED → BLIND → RECOVERY with the thresholds in §3.4. ETA and position uncertainty widen with data age, and state reconciles on recovery. | M | PDF P4 | C04, C05 | BM-08, BM-09, TS-TWIN-04 |
| F-15 | Show inventory confidence as Verified / Estimated / Suspicious per node and SKU. | S | ENH | C05, C15 | TS-UI-07 |
| F-16 | Provide an Attack Center to inject every T-06 injector, plus node failure. | M | PDF P4 | C14, C15, C01 | TS-UI-04 |
| F-17 | Run the optimizer on raw (attacked) and on trusted data for the same scenario, and show the decision and cost difference. | M | PDF P4 | C10, C14 | TS-OPT-06 |
| F-90 | Publish a telemetry catalog with a JSON Schema and validation range for every signal (`04_DATA_MODEL.md` §5). | M | ENH | C02, C04 | TS-ING-05 |
| F-91 | Implement the Trust Engine: the 8 check families, weighted aggregation, the hard-fail cap (ρ ≤ 0.20 when P, K or N < 0.20), CUSUM drift override, the entity state machine with cooldown, the thresholds 0.80/0.50, and the optimizer discount d(τ). | M | ENH (P4) | C04, C10 | TS-TRUST-01..06 |
| F-92 | Show a trust card per entity with per-check confidence, aggregate score, class, failed-check reasons and trust-over-time. Checks based on mocked data are labelled `MOCK`. | M | ENH | C15, C14 | TS-UI-05 |
| F-93 | Detect spatial-temporal clusters (≥ N trusted vehicles within R km on the same link, speed < 5 km/h, for ≥ T min) and infer the link status with a confidence value. | M | ENH (P2/P3) | C17 | BM-15, TS-INF-01 |
| F-94 | Guard inference with a trust-weighted quorum, independent corroboration (weather/alert, gate scans, or ≥ 2 fleets) before BLOCKED_INFERRED, and SUSPECTED plus human confirmation otherwise. Flag the reporters when there is contradicting traffic. | M | ENH (P4) | C17 | BM-10, TS-INF-02 |
| F-95 | Show a live telemetry panel whose KPIs are all computed from the stream: events/min, % valid/invalid, anomalies by severity, critical events, quarantined entities, DLQ count, freshness %, mode. Each KPI links to a drill-down. | M | ENH (P3) | C04, C14, C15 | TS-UI-02, TS-TWIN-05 |
| F-96 | Detect duplicates and replays using `event_id` and monotonic `seq` per source. | S | ENH (P4) | C02, C04 | BM-07 |
| F-97 | Optionally verify HMAC-SHA256 envelope signatures per source. | C | ENH (P4) | C02 | TS-SEC-06 |
| F-98 | Be crash-safe: no single malformed or adversarial message may stop ingestion or trust processing. Verified by fuzz testing. | M | PDF P4 | C02, C04 | TS-FUZZ-01 |

#### 3.2.4 Prediction and proactive layer (P2, ENH)

| ID | Requirement | Pri | Src | Comp | Test |
|---|---|---|---|---|---|
| F-20 | Ingest weather forecasts per corridor (Open-Meteo, `LIVE` with `REPLAY` fallback) and compute the corridor disruption probability with the calibrated model in §3.6. | M | PDF P2 | C07, C08 | TS-RISK-01, BM-13 |
| F-21 | Ingest disaster alerts (GDACS, NASA FIRMS; `LIVE`). | S | ENH | C07 | TS-SIG-02 |
| F-22 | Ingest AIS vessel positions (`REPLAY`) for port congestion and vessel ETA. | S | ENH | C07 | TS-SIG-03 |
| F-23 | Overlay a pre-processed EO flood mask on the map, clearly labelled `MOCK`. | C | ENH | C07, C15 | TS-UI-10 |
| F-24 | Learn climate-adjusted lead-time multipliers per corridor and season from delay/weather pairs. | S | ENH | C08 | TS-RISK-03 |
| F-25 | Show a Future Risk Radar: a per-node risk score with explainable drivers (inventory trend, delays, reliability, dependency count). | S | ENH | C08, C15 | TS-RISK-04 |

#### 3.2.5 Simulation (P2)

| ID | Requirement | Pri | Src | Comp | Test |
|---|---|---|---|---|---|
| F-30 | Provide a Scenario Lab with port closure, warehouse failure, supplier failure, demand spike, extreme weather, fleet failure and fuel-cost shock, each parameterised and seeded. | M | PDF P2 | C09, C15 | TS-SIM-01 |
| F-31 | Simulate cascading failures in discrete time (1 h step, T+0 → T+72 h) and animate them on the graph. | M | PDF P2 | C09, C15 | TS-SIM-02, BM-11 |
| F-32 | Show the blast radius for any node: direct and indirect affected nodes, orders at risk, revenue exposure, recovery time. | M | PDF P2/P3 | C06, C09 | TS-GRAPH-03 |
| F-33 | Analyse compound failures and report the interaction term (combined − sum of individual impacts). | S | ENH | C09 | TS-SIM-04, BM-14 |
| F-34 | Run Monte Carlo robustness analysis (200 seeded runs, common random numbers across strategies) and report P50/P90 and the plan robustness rating. | M | PDF P2 | C09 | TS-SIM-03 |
| F-35 | Provide a time scrubber over simulated futures. | M | PDF P2 | C15 | TS-UI-03 |

#### 3.2.6 Optimization and decisions (P2)

| ID | Requirement | Pri | Src | Comp | Test |
|---|---|---|---|---|---|
| F-40 | Optimize under constraints: link/vehicle capacity, warehouse capacity, safety stock, deadlines, supplier availability, flow conservation, blocked links. Reject plans that cause avoidable stockouts. Use trust-discounted inventory. | M | PDF P2 | C10 | TS-OPT-01, TS-OPT-02 |
| F-41 | Optimize multiple objectives (cost, delay, stockout penalty, risk, CO₂) with presets Cheapest / Fastest / Lowest Carbon / Lowest Risk / Balanced. | M | PDF P2 | C10 | TS-OPT-03 |
| F-42 | Present a multi-futures comparison (do nothing / reroute / transfer / hybrid) with cost, delay, stockout risk, orders saved, P50/P90, robustness and break-even p. | M | PDF P2 | C10, C15 | TS-UI-08 |
| F-43 | Apply the expected-value trigger (§3.6) and display the break-even p* against the current p. | M | PDF P2 | C10 | TS-OPT-04 |
| F-44 | Require human approval before any action. Support Approve / Modify (objective, constraints, excluded links) and recalculate. | M | PDF P2 | C11, C15 | TS-DEC-01 |
| F-45 | Generate an LLM explanation from structured optimizer output only. Every number must be validated against the input, with a template fallback. | S | ENH | C13 | TS-EXP-01, TS-EXP-02 |
| F-46 | Provide a recovery planner with phases Survive → Balance → Recover → Rebalance and time-to-recovery. | S | ENH | C10, C09 | TS-OPT-07 |
| F-47 | Triage alerts: deduplicate, rank by severity × exposure, and show "top 3 actions now". | S | ENH | C11, C15 | TS-DEC-03 |
| F-80 | Assign vehicles to shipments and re-assign them on reroute, respecting capacity, trusted position and remaining driver hours. | S | ENH | C10 | TS-OPT-08 |
| F-81 | Enforce the driver-hours limit (≤ 11 h driving) and warn when a reroute would exceed it. | S | ENH | C10 | TS-OPT-09 |
| F-82 | Detect fleet shortage during cascades (demand spike plus vehicle unavailability) and feed it into the cascade simulator. | C | ENH | C09, C10 | TS-SIM-05 |

#### 3.2.7 Structural analytics (P1, ENH)

| ID | Requirement | Pri | Src | Comp | Test |
|---|---|---|---|---|---|
| F-50 | Produce a fragility audit before any disruption: articulation points (global and per customer cluster), flow-weighted betweenness, supplier→customer min-cut, downstream flow share, as a ranked report. | M | ENH (P1) | C06 | TS-GRAPH-01, TS-GRAPH-02 |
| F-51 | Simulate "what would improve resilience?" (add a link or supplier) and show the change in resilience score. | S | ENH | C06 | TS-GRAPH-04 |
| F-52 | Compute a Network Resilience Score (0–100) with clickable, explainable sub-scores. | S | ENH | C06, C15 | TS-GRAPH-05 |

#### 3.2.8 Evaluation and audit (P5)

| ID | Requirement | Pri | Src | Comp | Test |
|---|---|---|---|---|---|
| F-60 | Run a hidden ground-truth world separate from the twin. The twin sees only noisy or attacked observations. | M | PDF P5 | C01 | TS-SEC-04 |
| F-61 | Compute fidelity metrics: ETA MAE/MAPE, inventory error, stockout-prediction precision/recall and lead time, cascade accuracy. | M | PDF P5 | C12 | TS-EVAL-01 |
| F-62 | Compute decision regret against the perfect-information optimum. | M | PDF P5 | C12, C10 | TS-EVAL-02 |
| F-63 | Provide a seeded, reproducible chaos/attack benchmark (≥ 10 scenarios; 15 defined) scored on detection rate, FPR, time-to-detect, decision quality vs oracle, in one Resilience Benchmark table, runnable with one command. | M | PDF P5 | C12 | BM-01..BM-15, TS-EVAL-03 |
| F-64 | Log every recommendation and decision with inputs, trust snapshot, optimizer and config version and approver in a hash-chained audit log that can be replayed. | M | PDF P5 | C11 | TS-DEC-02, TS-DEC-04 |
| F-65 | Counterfactual replay ("what if we had reacted 6 h earlier?"). | C | ENH | C11, C09 | TS-DEC-05 |
| F-66 | Track twin-vs-reality drift over time. | S | ENH | C12 | TS-EVAL-04 |

#### 3.2.9 Platform (Levels 3–4)

| ID | Requirement | Pri | Src | Comp | Test |
|---|---|---|---|---|---|
| F-70 | Authenticate users with JWT and roles Viewer / Operator / Admin, enforced on every endpoint. | M (L3) | PDF L3 | C14 | TS-SEC-01, TS-SEC-02 |
| F-71 | Encrypt all external traffic with TLS, keep secrets out of the repo, and rate-limit ingestion and the API. | M (L3) | PDF L3 | C14, C02, infra | TS-SEC-03, TS-SEC-05 |
| F-72 | Containerise with Docker Compose. Run CI/CD with GitHub Actions (lint, test, fuzz, build, deploy). Deploy to the cloud at a live HTTPS URL. | M (L3) | PDF L3 | infra | TS-OPS-01, TS-OPS-02 |
| F-73 | Use Redis caching for snapshots and analytics, query optimisation (indexes, hypertables, compression), health checks and structured logs. | M (L4) | PDF L4 | C05, C06, C14 | TS-PERF-04, TS-OPS-03 |
| F-74 | Provide Prometheus + Grafana dashboards and Alertmanager rules. | **M (L4)** | PDF L4 | C16 | TS-OPS-04 |
| F-75 | Provide Kubernetes manifests with HPA. | C (L4) | ENH | infra | TS-OPS-05 |

> F-74 is raised from S (BRIEF) to **M at L4** because the Level 4 criterion explicitly requires "active monitoring and alert dashboards" (ASSUMPTIONS F-09).

#### 3.2.10 Level (grading) requirements

| ID | Level requirement | Satisfied by |
|---|---|---|
| HL1-1 | SRS | `01_SRS.md` |
| HL1-2 | Architecture and data flow diagrams | `02_ARCHITECTURE.md`, `03_DATA_FLOW.md` |
| HL1-3 | UI wireframes | `05_UI_WIREFRAMES.md` |
| HL1-4 | Finalised tech stack | `06_TECH_STACK.md` |
| HL1-5 | Roadmap | `07_ROADMAP.md` |
| HL2-1 | DB schemas | `04_DATA_MODEL.md` DDL → Alembic migrations; F-01, F-02 |
| HL2-2 | Primary business logic | F-10, F-11, F-13, F-30, F-31, F-40, F-41, F-91 |
| HL2-3 | Essential APIs | C14 endpoint set (`02_ARCHITECTURE.md` §4 C14), F-03 |
| HL2-4 | Functional app where users complete core tasks | UC-01, UC-03, UC-04 end-to-end; F-04, F-42, F-44 |
| HL3-1 | Advanced algorithms / AI | F-34 Monte Carlo, F-20 calibrated risk, F-91 IsolationForest, F-24 lead-time model, F-45 LLM explanation, F-93/F-94 inference |
| HL3-2 | Authentication and encryption | F-70, F-71, F-97 |
| HL3-3 | Automated CI/CD | F-72 |
| HL3-4 | Real cloud launch | F-72 (live URL) |
| HL4-1 | Containerisation for auto-scaling | F-72, F-75, NFR-22 |
| HL4-2 | Caching and query optimisation | F-73, NFR-03 |
| HL4-3 | Active monitoring and alert dashboards | F-74, NFR-19 |

### 3.3 Trust score specification (F-11, F-91)
Normative detail is in `02_ARCHITECTURE.md` §5. Summary:
- Check families and weights: S 0.10, P 0.20 (hard), K 0.20 (hard), N 0.15 (hard), R 0.15, T 0.10, A 0.05 (S), C 0.05 (S). Weights are renormalised over the active checks.
- Reading trust: `ρ = min(0.20, avg)` if any hard check is < 0.20, else `avg`. CUSUM caps: ρ ≤ 0.70 at S ≥ 1.5 and ρ ≤ 0.45 at S ≥ 3.0.
- Entity update: hard anomaly `τ ← min(0.5τ, ρ)`; soft anomaly `τ ← τ(1 − (0.8 − ρ))`; recovery only after 5 good readings and 10 sim-min, at most +0.02 per reading.
- Classes: Trusted ≥ 0.80 (update twin), Estimated 0.50–0.80 (update with widened uncertainty; optimizer discount d = τ), Quarantined < 0.50 (no twin write; last trusted state kept; d = 0).
- Every verdict carries `checks{}` and `reasons[]`.
- Worked examples: normal 0.93, teleport 0.20, speed spike (avg 0.53 → capped 0.20), drift (Estimated at 35 min, Quarantined at 40 min), coordinated stop (inference conf 0.51 → SUSPECTED). See `02_ARCHITECTURE.md` §5.5.

**Quarantine actions (ADD §4.5):** (1) reject from twin, keep the last trusted position, grow the uncertainty radius; (2) emit `trust.anomaly`; (3) mark dependent ETAs degraded; (4) re-run the optimizer only if decision inputs changed; (5) write audit; (6) surface in the Trust Monitor and alert feed via triage.

### 3.4 Degradation modes (F-14)
Freshness thresholds: vehicle 90 s, warehouse 3 min, port 15 min, weather 90 min (3 × the expected interval).
NORMAL (F ≥ 90% and C ≥ 85%) · DEGRADED (50 ≤ F < 90 or C < 85) · BLIND (F < 50) · RECOVERY (F ≥ 90 and C ≥ 85 after DEGRADED or BLIND → NORMAL after 10 sim-min stable). Hysteresis is 60 sim-s. Uncertainty growth: position `r = 0.05 km + 45 km/h × age`; ETA `σ = √(0.25² + (0.5·age_h)²)` h.

### 3.5 Cascade simulation (F-31, F-33)
Discrete time, 1 h step, 72 h horizon. Propagation: link/node failure → shipment delay → inbound reduction → inventory depletion against safety stock → production/fulfilment at risk → order impact. Includes demand, lead-time and capacity effects, and concurrent (compound) disruptions. Outputs: hourly frames, orders at risk, stockout times, cost, delay, CO₂. Specification: `02_ARCHITECTURE.md` §6.

### 3.6 Expected-value trigger and probability (F-20, F-43)
`E[nothing] = p·L₀`; `E[act] = C_a + p·L₁` (the action cost is paid whether or not the disruption occurs); expected loss avoided = `p(L₀ − L₁)`; net = `p(L₀ − L₁) − C_a`; act iff net > 0; `p* = C_a / (L₀ − L₁)`. L₀ and L₁ are Monte Carlo conditional means. The probability comes from a logistic model on corridor features (6 h precipitation, gust, share of points above the IMD very-heavy band, alert level). The initial coefficients are an IMD-band prior, Platt-scaled against ground-truth labels and reported with a reliability diagram and Brier score. The UI tooltip states that this calibration is internal (world model), not real-world (ASSUMPTIONS D-12). Specification: `02_ARCHITECTURE.md` §8.

### 3.7 Optimizer and Monte Carlo (F-34, F-40, F-41)
LP time-expanded multi-commodity min-cost flow (GLOP), 12 × 6 h periods, 5 SKUs, objective `w1·cost + w2·delay + w3·stockout + w4·risk + w5·CO₂` (preset table in `02_ARCHITECTURE.md` §7). Time limit 5 s, heuristic fallback ≤ 1 s, `solver_status` always reported. Monte Carlo: 200 seeded runs, common random numbers, P50/P90, robustness = share of runs with service level ≥ 95% (High ≥ 0.90, Medium 0.70–0.90, Low < 0.70).

### 3.8 Structural fragility (F-50–F-52)
Articulation points, flow-weighted betweenness, min-cut, downstream share, blast radius. Resilience = 25·Recovery + 25·Redundancy + 20·Buffer + 15·SupplierDiversity + 15·TransportDiversity (`02_ARCHITECTURE.md` §9).

### 3.9 Non-functional requirements (measurable)

| ID | Category | Requirement / target | Level | Verified by |
|---|---|---|---|---|
| NFR-01 | **Ingestion throughput** | ≥ 5,000 events/min sustained for 30 min with 0 unaccounted events (L2/L3). ≥ 50,000 events/min for 10 min with bus lag ≤ 5 s (L4). | L2–L4 | TS-PERF-01, TS-PERF-05 |
| NFR-02 | Ingest-to-twin latency | p95 ≤ 2 s from `ts_ingested` to twin update at 5k/min. | L3 | TS-PERF-02 |
| NFR-03 | **API p95 latency** | Read endpoints p95 ≤ 300 ms at 20 concurrent users (L3). Cached reads p95 ≤ 150 ms at 100 concurrent users (L4). Synchronous writes p95 ≤ 500 ms. | L3/L4 | TS-PERF-04 |
| NFR-04 | UI push latency | State change → rendered on the Control Room p95 ≤ 1.5 s. | L3 | TS-PERF-03 |
| NFR-05 | **Simulation runtime budget** | Single 72 h cascade ≤ 2 s. Monte Carlo 200 runs × 4 strategies ≤ 15 s (L3) and ≤ 8 s (L4). | L2–L4 | TS-PERF-06 |
| NFR-06 | Optimizer runtime | Solver time limit 5 s. Fallback heuristic ≤ 1 s. End-to-end recommendation (sim + MC + opt) ≤ 30 s. | L2/L3 | TS-PERF-07 |
| NFR-07 | **Availability** | ≥ 99.0% monthly uptime for the public URL during the L3 evaluation window (1-min external probe). ≥ 99.5% target at L4. Container restart policy with RTO ≤ 5 min. RPO ≤ 24 h (nightly dump) plus Redis AOF. | L3/L4 | TS-OPS-06 |
| NFR-08 | **Graceful degradation under data loss** | With up to 80% of sources silent for 30 sim-min: no process crash, UI stays responsive, simulation and optimization still run (on trusted state), mode reaches BLIND within 90 sim-s of F < 50, and returns to NORMAL ≤ stability window + 60 s after restoration. | L2/L3 | BM-09, TS-TWIN-04 |
| NFR-09 | Crash safety | A fuzz run of 100,000 malformed or mutated messages gives 0 worker crashes, and accepted + DLQ + duplicate-dropped = sent (100% accounted). | L2 | TS-FUZZ-01 |
| NFR-10 | **Security: authN/Z** | 100% of non-health endpoints require a valid JWT. RBAC is tested per role for every mutating endpoint. argon2id password hashing. Access token TTL 15 min. Login rate limit 5/min per IP. | L3 | TS-SEC-01, TS-SEC-02 |
| NFR-11 | **Security: encryption** | TLS 1.2+ with HSTS on all external endpoints (SSL Labs grade ≥ A). The DB and Redis are not exposed publicly. Secrets are never committed (gitleaks in CI). Source HMAC optional (F-97). | L3 | TS-SEC-03, TS-SEC-05 |
| NFR-12 | Rate limiting | A per-source limit of 6,000 events/min (configurable). Excess returns 429. A flooding source does not raise other sources' p95 latency by more than 20%. | L3 | TS-SEC-07 |
| NFR-13 | Reproducibility | The same seed and command log give an identical event-stream hash and benchmark metrics within ±0 (deterministic parts) or ±1% (wall-clock-timed parts). | L2 | TS-WORLD-04, TS-EVAL-03 |
| NFR-14 | Detection quality | Detection rate ≥ 95% for hard attacks (teleport, speed spike, feed_corrupt, payload_incomplete, duplicate_replay). ≥ 80% for drift within 45 sim-min. Reading-level FPR ≤ 2% on clean runs. 0 false automatic reroutes under coordinated_stop_spoof. | L3 | BM-01..BM-10 |
| NFR-15 | Twin fidelity | In NORMAL mode: ETA MAE ≤ 45 min, inventory MAPE ≤ 5%, stockout-prediction recall ≥ 0.80 with ≥ 6 h lead. | L3 | TS-EVAL-01 |
| NFR-16 | Cost | Cloud ≤ ₹12,000/month. LLM ≤ ₹500 for the presentation week (cache explanations per recommendation). | L3 | TS-OPS-07 |
| NFR-17 | Usability | Every presentation beat is reachable in ≤ 3 clicks from the Control Room. Status is shown by colour plus icon. WCAG AA contrast for text. | L2/L3 | TS-UI-09 |
| NFR-18 | Maintainability | Module boundaries enforced by import-linter in CI. Line coverage ≥ 70% for `trust`, `sim` and `opt`. | L2 | TS-OPS-01 |
| NFR-19 | Observability | Every process exposes `/metrics` and `/healthz`. ≥ 5 alert rules (stream lag, DLQ rate, BLIND mode, API p95, solver fallback rate). | L4 | TS-OPS-04 |
| NFR-20 | Data honesty | 100% of external-signal records and UI badges carry `LIVE`/`REPLAY`/`MOCK`. No UI string says "satellite positioning" for trucks. | L2 | TS-UI-10, TS-SIG-04 |
| NFR-21 | Explainability | 100% of recommendations include constraint checks and reasons. 100% of LLM narratives pass numeric validation, or the template fallback is used. | L3 | TS-EXP-01 |
| NFR-22 | Scalability | Going from 1 to 2 ingest-workers gives ≥ 1.6× throughput. Stateless API replicas scale linearly up to 4. | L4 | TS-PERF-05 |

### 3.10 Other constraints
- Every number shown in the UI is computed by a named module. Illustrative numbers appear only in the docs and wireframes, marked `‹…›`.
- The LLM never computes numbers or routes (F-45, C13 guardrails).
- Executing actions always requires human approval in the MVP. `auto_action_policy` = off.

---

## 4. Use cases

Format: **Actor · Preconditions · Trigger · Main flow · Alternatives / exceptions · Postconditions · Requirements**.

### UC-01 Monitor live network
- **Actor:** Operations Controller. **Pre:** logged in (Viewer+); world-sim running.
- **Trigger:** opens the Control Room.
- **Main:** 1. The map shows nodes and links by status, and live vehicles. 2. The mode badge shows NORMAL. 3. The Live Telemetry panel shows computed KPIs. 4. The alert feed and "top 3 actions" update. 5. The user clicks a node → Node Detail (UC-07/F-32).
- **Alt:** 2a. The mode is DEGRADED or BLIND → banner, freshness heatmap auto-on. 3a. The WS drops → "LIVE LINK LOST" banner with the last state greyed out and automatic reconnect.
- **Post:** none (read-only). **Req:** F-01, F-02, F-04, F-05, F-95, F-47, NFR-04.

### UC-02 Receive a proactive weather-driven warning
- **Actor:** Operations Controller. **Pre:** weather connector active (LIVE or REPLAY); flows planned on the corridor.
- **Trigger:** C08 computes p ≥ 0.2 for a corridor carrying active flow (e.g. HYD-VGA, about 8 h ahead).
- **Main:** 1. An alert appears with corridor, p, lead time and drivers. 2. The user opens Early Warning and sees the forecast overlay and p vs p*. 3. The user clicks "Simulate now" → Monte Carlo runs for do-nothing / reroute / transfer / hybrid. 4. The Strategies screen shows computed L₀, L₁, C_a, expected loss avoided and p* (UC-04).
- **Alt:** 1a. Open-Meteo is down → REPLAY badge. 3a. MC overruns its budget → partial runs with a reduced-confidence badge.
- **Post:** a recommendation is created (`recommendation.created`). **Req:** F-20, F-21, F-34, F-42, F-43, NFR-05.

### UC-03 Run a disruption scenario and view the cascade
- **Actor:** Supply Chain Planner. **Pre:** Operator role.
- **Trigger:** opens the Scenario Lab.
- **Main:** 1. Picks a scenario type (e.g. port closure P-CHE, 48 h) and parameters. 2. Optionally adds a second scenario (compound). 3. Clicks Run. 4. The Cascade View animates T+0…T+72 with the KPI ribbon. 5. The user scrubs the time axis. 6. The user opens Strategies.
- **Alt:** 2a. Compound → the interaction term is shown (F-33). 3a. Invalid parameters → inline validation.
- **Post:** `sim.scenario` and `sim.simulation_run` are stored. **Req:** F-30, F-31, F-33, F-35, NFR-05.

### UC-04 Compare strategies and approve a plan
- **Actor:** Operations Controller. **Pre:** a recommendation exists (from UC-02, UC-03 or UC-10).
- **Main:** 1. The futures table shows 4 strategies with metrics, P50/P90 and robustness. 2. The user changes the objective preset → recalculation. 3. The user opens "Why this plan" (constraint checks + narrative). 4. The user clicks Approve. 5. The twin applies the plan, the world dispatcher executes it, and an audit entry is written.
- **Alt:** 4a. Modify: exclude a link or change deadlines → re-optimise → return to 1. 4b. Reject with a reason → audit only. 3a. LLM unavailable → template narrative.
- **Post:** `decision.decision` and `audit_log` are stored and `decision.approved` is emitted. **Req:** F-40–F-45, F-64, F-80, F-81.

### UC-05 Detect and quarantine spoofed or corrupted data
- **Actor:** Security / Data Quality Analyst (presentation: presenter via the Attack Center). **Pre:** Operator role; guided mode enabled for injection.
- **Trigger:** an injector runs (e.g. `speed_spike` on truck-A-017), or real anomalous data arrives.
- **Main:** 1. The Trust Engine scores the reading (e.g. 812 km/h → P hard fail → ρ 0.20). 2. The entity becomes Quarantined and the last trusted position is kept. 3. `trust.anomaly` appears in the alert feed and the Trust Monitor with reasons. 4. The trust card shows per-check confidences and the trust drop. 5. If decision inputs changed, the optimizer re-runs and a before/after view is shown. 6. The analyst reviews the quarantine item → confirmed_attack / false_positive.
- **Alt:** 1a. Subtle drift → Estimated first, then Quarantined when CUSUM passes h₂. 1b. Incomplete payload → last trusted value is used and the field is marked stale; no quarantine unless τ < 0.5. 5a. Raw-vs-trusted comparison requested (F-17).
- **Post:** `quarantine_item`, `trust_history` and an audit entry are stored. **Req:** F-10–F-13, F-16, F-17, F-91, F-92, F-96, T-06.

### UC-06 Operate through a blackout and recover
- **Actor:** Operations Controller. **Pre:** NORMAL mode.
- **Trigger:** `mass_blackout` (e.g. 70% of sources silent) or `entity_blackout`.
- **Main:** 1. F drops → DEGRADED → BLIND (banner). 2. The twin dead-reckons and the uncertainty bands widen on map and ETAs. 3. The optimizer only uses Trusted inventory. 4. Sources return → DEGRADED → RECOVERY: predicted and reported state are reconciled and the error is recorded. 5. After 10 stable sim-minutes → NORMAL.
- **Alt:** 4a. Sources flap → back to DEGRADED (hysteresis prevents oscillation faster than 60 s).
- **Post:** `network_mode_history` and a blind-period fidelity record are stored. **Req:** F-14, F-05, NFR-08.

### UC-07 Run a network stress test / fragility audit
- **Actor:** Supply Chain Planner. **Pre:** Operator role.
- **Main:** 1. Opens the Fragility Report. 2. Sees ranked critical nodes (articulation points, betweenness, min-cut). 3. Clicks the resilience sub-scores for their contributors. 4. Runs "add link" what-if → sees the score delta. 5. Clicks a node → Blast Radius.
- **Post:** none, or a saved what-if. **Req:** F-32, F-50, F-51, F-52.

### UC-08 Review fidelity metrics and the Resilience Benchmark
- **Actor:** Executive / Judge. **Pre:** Viewer role (truth-based detail views need Admin).
- **Main:** 1. Opens Evaluation. 2. Sees fidelity metrics (ETA MAE, inventory error, stockout P/R), decision regret, and the Resilience Benchmark table. 3. Opens the drift chart. 4. (Admin) Clicks "Run benchmark" → the job runs all 15 scenarios with fixed seeds.
- **Post:** `eval.benchmark_run` and results are stored. **Req:** F-61, F-62, F-63, F-66, NFR-13.

### UC-09 Audit a past decision
- **Actor:** Executive / Admin. **Main:** 1. Opens Audit Trail. 2. Filters by date or type. 3. Opens an entry: inputs, trust snapshot, versions, approver. 4. Clicks Replay → the optimizer re-runs on the stored snapshot and shows the diff (expected: identical). 5. Verifies chain integrity.
- **Alt:** 4a. The config version has changed since → both results are shown and the difference is explained.
- **Req:** F-64, F-65.

### UC-10 Inferred road blockage from telemetry (ADD)
- **Actor:** system (automatic) plus Operations Controller. **Pre:** trusted vehicles on a link.
- **Trigger:** ≥ N trusted vehicles are stopped within R km for ≥ T min.
- **Main:** 1. C17 detects the cluster. 2. It computes quorum, independence, corroboration and contradiction → conf. 3. If conf ≥ 0.75 and corroborated → the link becomes BLOCKED_INFERRED → cascade + optimizer run automatically → recommendation with evidence → the operator approves (UC-04).
- **Alt:** 3a. Not corroborated or 0.40 ≤ conf < 0.75 → SUSPECTED, the operator is asked to confirm, routing is unchanged. 3b. Contradicting traffic X > 0.2 → reporters are flagged and a coordinated_anomaly alert is raised (coordinated spoof). 3c. Rest stop or toll plaza and no context → ignored.
- **Post:** `inferred_event` and audit are stored. **Req:** F-93, F-94, F-44, BM-10, BM-15.

---

## 5. Traceability matrix

### 5.1 PDF requirements → requirement IDs → components → tests

| PDF req | Requirement IDs | Components | Tests / benchmarks |
|---|---|---|---|
| **P1** Multi-component architecture (high-throughput ingestion, graph modelling, synchronised telemetry) | F-01, F-02, F-03, F-50, F-90, F-95, T-01, T-02, T-03, T-04, NFR-01, NFR-02, NFR-22 | C01, C02, C03, C04, C05, C06 | TS-TWIN-01/02, TS-ING-01..05, TS-WORLD-01..03, TS-GRAPH-01/02, TS-PERF-01/02/05 |
| **P2** Scenario-based optimization (what-if, contingency, automated recommendations) | F-20, F-21, F-22, F-24, F-25, F-30, F-31, F-32, F-33, F-34, F-35, F-40, F-41, F-42, F-43, F-44, F-45, F-46, F-47, F-80, F-81, F-82, F-93, NFR-05, NFR-06 | C07, C08, C09, C10, C11, C13, C17 | TS-RISK-01..04, TS-SIM-01..05, TS-OPT-01..09, TS-DEC-01/03, TS-EXP-01/02, TS-INF-01, BM-11..BM-15 |
| **P3** End-to-end network visibility (orders, stock, links; high-fidelity replica) | F-01, F-02, F-04, F-05, F-15, F-32, F-35, F-95, T-03, NFR-04, NFR-15 | C05, C06, C14, C15 | TS-TWIN-01/02/05, TS-UI-01/02/03/06/07, TS-GRAPH-03, TS-EVAL-01 |
| **P4** Adversarial resilience (spoofed GPS, incomplete payloads, blackouts, no crash) | F-10, F-11, F-12a/b/c, F-13, F-14, F-16, F-17, F-91, F-92, F-94, F-96, F-97, F-98, T-06, NFR-08, NFR-09, NFR-12, NFR-14 | C01, C02, C04, C05, C10, C17 | TS-TRUST-01..10, TS-FUZZ-01, TS-INF-02, TS-OPT-06, BM-01..BM-10 |
| **P5** Production-ready evaluation (accuracy vs physical outcomes; reliable, cost-effective decisions at scale) | F-60, F-61, F-62, F-63, F-64, F-65, F-66, T-05, T-08, NFR-13, NFR-15, NFR-16, NFR-21 | C01, C11, C12 | TS-EVAL-01..04, TS-DEC-02/04/05, TS-WORLD-04/06, TS-SEC-04, BM-01..BM-15 |

### 5.2 Level requirements → requirement IDs → components → tests

| Level req | Requirement IDs | Components | Tests |
|---|---|---|---|
| HL1-1..5 | docs | — | `LEVEL1_CHECKLIST.md` |
| HL2-1 DB schemas | F-01, F-02, F-64 | C05, C11 | TS-TWIN-01, TS-OPS-01 (migrations apply) |
| HL2-2 Business logic | F-10, F-11, F-13, F-30, F-31, F-40, F-41, F-91 | C04, C09, C10 | TS-TRUST-01..07, TS-SIM-01/02, TS-OPT-01..03 |
| HL2-3 Essential APIs | F-03, C14 endpoint set | C02, C14 | TS-ING-01, TS-API-01 |
| HL2-4 Functional app | F-04, F-42, F-44, UC-01/03/04 | C14, C15 | TS-UI-01, TS-UI-03, TS-UI-08, TS-DEC-01 |
| HL3-1 Advanced algorithms / AI | F-20, F-24, F-34, F-45, F-91, F-93, F-94 | C04, C08, C09, C13, C17 | TS-RISK-01/03, TS-SIM-03, TS-EXP-01, TS-INF-01/02 |
| HL3-2 Auth + encryption | F-70, F-71, F-97, NFR-10, NFR-11 | C14, C02 | TS-SEC-01/02/03/05/06 |
| HL3-3 CI/CD | F-72 | infra | TS-OPS-01, TS-OPS-02 |
| HL3-4 Cloud launch | F-72, NFR-07 | infra | TS-OPS-02, TS-OPS-06 |
| HL4-1 Containers / auto-scaling | F-72, F-75, NFR-22 | infra | TS-PERF-05, TS-OPS-05 |
| HL4-2 Caching / query optimisation | F-73, NFR-03 | C05, C06, C14 | TS-PERF-04, TS-OPS-03 |
| HL4-3 Monitoring / alerts | F-74, NFR-19 | C16 | TS-OPS-04 |

### 5.3 Orphan check
Every F-, T- and NFR- ID in §3 appears in §5.1 or §5.2:
- F-01..05, F-10..17, F-20..25, F-30..35, F-40..47, F-50..52, F-60..66, F-70..75, F-80..82, F-90..98 and T-01..08 are all present.
- NFR-01..22 are all present: 01/02/22 → P1; 05/06 → P2; 04/15 → P3; 08/09/12/14 → P4; 13/15/16/21 → P5; 03/07/10/11/19 → Level 3/4 (HL3-2, HL3-4, HL4-2, HL4-3); 17/18/20 → HL2-4, HL2-1 and P5 honesty respectively.
- Every requirement lists a component and a test in its own row.

---

## 6. Test catalogue (IDs referenced above)

| ID | Test | Type |
|---|---|---|
| TS-ING-01 | Valid batch accepted, persisted, published | integration |
| TS-ING-02 | Oversize / unknown type / bad JSON → DLQ with correct error_class | unit |
| TS-ING-03 | Invalid source key → 401. Rate limit → 429 | integration |
| TS-ING-04 | Bus down → 503 + Retry-After. No loss after recovery | integration |
| TS-ING-05 | Every catalog signal has a schema. Out-of-range values are rejected or scored per schema | unit |
| TS-API-01 | OpenAPI contract test for all C14 endpoints | contract |
| TS-WORLD-01..03 | Vehicles stay on geometry. Inventory feed equals true flows ± noise. Shipment/port consistency | unit |
| TS-WORLD-04 | Same seed + command log → identical stream hash | property |
| TS-WORLD-05 | Replay file streams at the configured speed | integration |
| TS-WORLD-06 | Labels are never present in envelopes | property |
| TS-TRUST-01..04 | Worked examples A–D reproduce the documented values (to 3 decimals) | unit |
| TS-TRUST-05 | Each check family's confidence function at its boundaries | unit |
| TS-TRUST-06 | State machine: cooldown enforced; one good reading does not restore trust | unit |
| TS-TRUST-07 | Quarantined reading produces zero writes to twin tables | integration |
| TS-TRUST-08 | Missing optional field → stale field, last trusted value, reduced S | unit |
| TS-TRUST-09 | Weather/gate-scan context check (S) | unit |
| TS-TRUST-10 | AIS vs supplier ETA check (C) | unit |
| TS-FUZZ-01 | Hypothesis fuzz: 100k mutated envelopes → no crash, full accounting | fuzz |
| TS-TWIN-01 | Seed network loads with 40 nodes and 92 links | unit |
| TS-TWIN-02 | Reading → state diff → WS message | integration |
| TS-TWIN-04 | Mode transitions follow thresholds + hysteresis | unit |
| TS-TWIN-05 | KPI panel values equal a recomputation from the raw stream | integration |
| TS-INF-01 | Real blockage (BM-15) → BLOCKED_INFERRED | scenario |
| TS-INF-02 | Coordinated spoof (BM-10) → SUSPECTED, no reroute | scenario |
| TS-GRAPH-01..05 | Articulation points (W-VGA for C-VTZ), betweenness, blast radius, what-if delta, resilience sub-scores | unit |
| TS-SIG-02..04 | Alerts parsed. AIS replay. data_mode present on 100% of rows | unit |
| TS-RISK-01 | Probability monotone in precipitation. Calibration reliability report produced | unit |
| TS-RISK-03/04 | Lead-time model improves ETA MAE over the base. Risk drivers sum to the score | eval |
| TS-SIM-01..05 | Each scenario type. Cascade frames. MC P50/P90 and robustness. Compound interaction. Fleet shortage | unit |
| TS-OPT-01 | All constraints satisfied in the returned plan | unit |
| TS-OPT-02 | Cheapest-but-stockout plan rejected. Trust discount applied | unit |
| TS-OPT-03 | Presets change the chosen plan on a crafted case | unit |
| TS-OPT-04 | EV math: example gives ₹6.02L avoided, p* 4.95% | unit |
| TS-OPT-05 | Time limit → feasible_timeout or heuristic_fallback status | unit |
| TS-OPT-06 | Raw-vs-trusted comparison shows a plan difference in BM-04 | scenario |
| TS-OPT-07..09 | Recovery phases. Fleet assignment. Driver-hours warning | unit |
| TS-DEC-01 | Approve / modify / reject flows | E2E |
| TS-DEC-02 | Audit hash chain verifies. Tampering detected | unit |
| TS-DEC-03 | Alert triage dedup and top-3 | unit |
| TS-DEC-04 | Replay reproduces the stored recommendation | integration |
| TS-DEC-05 | Counterfactual 6 h-earlier replay | scenario |
| TS-EXP-01 | Narrative containing a number absent from the input → rejected → template | unit |
| TS-EXP-02 | LLM timeout → template within 4 s | unit |
| TS-EVAL-01..04 | Fidelity metrics. Regret. Full benchmark reproducible. Drift series | eval |
| TS-SEC-01/02 | JWT required. RBAC matrix | integration |
| TS-SEC-03 | TLS/HSTS headers, no plaintext port | ops |
| TS-SEC-04 | twin_rw cannot read the truth schema | integration |
| TS-SEC-05 | gitleaks clean | CI |
| TS-SEC-06 | HMAC verify pass/fail | unit |
| TS-SEC-07 | Flooding source isolated by rate limit | load |
| TS-PERF-01..07 | Throughput, latency, UI push, API p95, scale-out, sim runtime, opt runtime | load / bench |
| TS-OPS-01..07 | CI pipeline green. Deploy. Cache and indexes (EXPLAIN). Alerts fire. K8s manifests apply on kind. Uptime probe. Cost report | ops |
| TS-UI-01..10 | Playwright smoke per screen (map, KPIs, scrubber, attack center, trust card, heatmap, inventory confidence, futures, 3-click flows, MOCK/REPLAY badges) | E2E |
| BM-01..BM-15 | Benchmark scenarios (`08_EVALUATION_FRAMEWORK.md` §5) | benchmark |
