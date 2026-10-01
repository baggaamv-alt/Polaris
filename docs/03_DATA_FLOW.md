# 03 — Data Flow

Diagram index (BRIEF §7.3 numbering): **#3** End-to-end data flow (§1) · **#4** Trust pipeline with quarantine (§3) · **#5** Degradation mode state machine (§5) · **#6** Cascade propagation sequence (§8) · **#7** Proactive weather workflow sequence (§9) · **#8** Evaluation loop (§10). Addendum diagrams: authoritative end-to-end flow (§2), event-driven decision chain (§6), blockage inference sequence with adversarial guard (§7). Extra flows: raw-vs-trusted comparison (§4), blackout and recovery (§11).

Component IDs (C01–C17) refer to `02_ARCHITECTURE.md` §4.

---

## 1. Diagram #3: End-to-end data flow

Source → validation → trust → twin → simulation → optimizer → human → action → twin update → evaluation.

```mermaid
flowchart LR
    S1[Telemetry simulator C01<br/>vehicles, warehouses,<br/>shipments, ports] --> G
    S2[Supplier feeds C01] --> G
    S3[Orders C01] --> G
    S4[Weather LIVE / alerts LIVE<br/>AIS REPLAY / EO MOCK<br/>via C07] --> G

    G[Ingestion gateway C02<br/>auth, envelope schema,<br/>size, rate limit, dedupe] -->|valid envelope| B[(Event bus C03<br/>ev.raw)]
    G -->|malformed| DLQ[(Dead-letter queue)]
    B --> V[Validation checks C04<br/>schema, physics, kinematic,<br/>road-network, route, temporal]
    V --> T[Trust scoring C04<br/>reading rho, entity tau,<br/>class + reasons]
    T -->|trusted| TW[Twin state C05]
    T -->|estimated: widen bands| TW
    T -->|quarantined| QQ[(Quarantine + audit)]
    TW --> INF[Event inference C17]
    INF -->|link status + confidence| TW
    TW --> RISK[Risk C08<br/>disruption probability]
    TW --> SIM[Simulation C09<br/>cascade + Monte Carlo]
    RISK --> SIM
    SIM --> OPT[Optimizer C10<br/>strategies + EV trigger]
    OPT --> EXP[Copilot C13<br/>narrative only]
    EXP --> HUM{Operator<br/>approve / modify}
    OPT --> HUM
    HUM -->|modify| OPT
    HUM -->|approve| ACT[Decision C11<br/>audit + outbox]
    ACT -->|apply plan| TW
    ACT -->|dispatch commands| S1
    TW -.->|belief| EV[Evaluation C12]
    QQ -.->|detections| EV
    ACT -.->|decisions| EV
    GT[(Ground truth<br/>truth schema)] -.->|hidden truth + labels| EV
    EV --> BM[Fidelity, regret,<br/>Resilience Benchmark]
```

---

## 2. Authoritative end-to-end flow (ADD §7), repeated here as required

**Legend:** EO flood mask `MOCK`; disaster feeds `LIVE` (fallback `REPLAY`); weather `LIVE` (fallback `REPLAY`); AIS `REPLAY`; telemetry synthetic from the ground-truth world.

```mermaid
flowchart TD
    subgraph SRC[Sources]
        SAT[Earth-observation / disaster feeds - LIVE or MOCK]
        WX[Weather forecasts - LIVE]
        TEL[Telemetry simulator - vehicles, warehouses, shipments, ports]
        AIS[AIS vessel data - REPLAY]
    end

    SAT --> ING
    WX --> ING
    TEL --> ING
    AIS --> ING

    ING[Stream Ingestion<br/>Gateway + event bus<br/>rate limit, dead-letter]
    ING --> TRUST[Trust Engine<br/>validation + anomaly detection<br/>trust score + quarantine]
    TRUST -->|trusted or estimated data| TWIN[Digital Twin<br/>graph + state engine + confidence layer]
    TRUST -.->|quarantined| Q[Quarantine queue + audit log]

    TWIN --> PRED[Prediction<br/>disruption probability, node risk, lead-time]
    TWIN --> SIM[Simulation<br/>cascade, compound, Monte Carlo]
    TWIN --> GRAPH[Graph analytics<br/>blast radius, fragility, min-cut]

    PRED --> OPT
    SIM --> OPT
    GRAPH --> OPT

    OPT[Optimization<br/>constraints + objectives + EV trigger]
    OPT --> ROUTE[Routing]
    OPT --> INV[Inventory reallocation]
    OPT --> FLEET[Fleet assignment]

    ROUTE --> COP
    INV --> COP
    FLEET --> COP

    COP[AI Copilot<br/>explains structured optimizer output only]
    COP --> HUMAN[Human decision<br/>approve / modify]
    HUMAN -->|approved action| TWIN
    HUMAN --> AUDIT[Decision audit trail]

    GT[Ground-truth world simulator] -.->|hidden truth| EVAL[Evaluation service<br/>fidelity, regret, benchmark]
    TWIN -.-> EVAL
    TRUST -.-> EVAL
    OPT -.-> EVAL
    GT --> TEL
```

Notes: the Copilot sees only structured optimizer output and trust evidence. The quarantine path never writes to twin state. Truth and labels reach only the evaluation service. Routing and inventory are the MUST optimizer outputs, and fleet is SHOULD/COULD.

---

## 3. Diagram #4: Trust pipeline, including quarantine and fallback to last trusted state

```mermaid
flowchart TD
    IN[Envelope from ev.raw] --> DUP{Duplicate event_id<br/>or seq not increasing?}
    DUP -->|yes| DROP[Drop + count replay<br/>temporal c_T = 0<br/>source reputation down]
    DUP -->|no| SCH[Schema / structure check<br/>missing fields: use last trusted value,<br/>mark field stale]
    SCH --> PHY[Range / physics check<br/>HARD]
    PHY --> KIN[Kinematic check vs last trusted fix<br/>HARD]
    KIN --> NET[Geospatial / road-network match<br/>HARD]
    NET --> RTE[Route consistency + CUSUM drift]
    RTE --> TMP[Temporal integrity]
    TMP --> STA[Statistical anomaly<br/>IsolationForest - SHOULD]
    STA --> CTX[Independent context<br/>weather, alerts, gate scans,<br/>EO mask labelled MOCK - SHOULD]
    CTX --> AGG[Aggregate: avg = sum w c / sum w]
    AGG --> HARD{Any hard check < 0.20?}
    HARD -->|yes| CAP[rho = min 0.20, avg]
    HARD -->|no| NCAP[rho = avg<br/>apply CUSUM caps]
    CAP --> SM[Entity state machine<br/>decay / cooldown / slow recovery]
    NCAP --> SM
    SM --> CLS{Entity trust tau}
    CLS -->|tau >= 0.80 Trusted| UPD[Update twin normally]
    CLS -->|0.50 to 0.80 Estimated| UPDW[Update twin with widened<br/>uncertainty, optimizer discount]
    CLS -->|tau < 0.50 Quarantined| QUA[Quarantine reading<br/>NO twin write]
    QUA --> KEEP[Keep last trusted state<br/>grow uncertainty radius with age]
    QUA --> EVT[Emit trust.anomaly<br/>entity, reasons, confidences]
    QUA --> ETA[Mark dependent shipment ETA degraded,<br/>widen band]
    QUA --> AUD[(Audit entry)]
    QUA --> REV[Trust Monitor + alert feed<br/>via triage]
    EVT --> CHG{Decision inputs changed?<br/>affected shipment on a planned route<br/>or inventory used in active plan}
    CHG -->|yes| RERUN[Optimizer re-run<br/>before/after comparison]
    CHG -->|no| NOOP[No re-run<br/>avoid alert storm]
    UPD --> HIST[(trust_history)]
    UPDW --> HIST
    QUA --> HIST
```

**Incomplete payloads and blackouts (ADD §4.7):** a missing optional field lowers S and the last trusted value is used. A missing required field gives S = 0: the reading is still scored and its fields are not applied. Unparseable messages never reach this pipeline because the gateway sends them to the DLQ. No path in this diagram raises an exception past the worker loop (F-98).

---

## 4. Raw vs trusted comparison flow (F-17, ADD §4.6)

```mermaid
sequenceDiagram
    autonumber
    participant OP as Operator (Attack Center)
    participant API as API C14
    participant TW as Twin C05
    participant Q as Quarantine store
    participant OPZ as Optimizer C10
    participant SIM as Simulation C09
    OP->>API: POST /compare/raw-vs-trusted {scenario_id}
    API->>TW: snapshot(trusted) at version v
    API->>Q: quarantined readings since attack start
    API->>API: build snapshot(raw) = trusted snapshot with quarantined readings applied
    par Trusted run
        API->>OPZ: optimize(snapshot trusted, preset)
        OPZ-->>API: plan_T
    and Raw run
        API->>OPZ: optimize(snapshot raw, preset)
        OPZ-->>API: plan_R
    end
    API->>SIM: evaluate plan_T and plan_R under the same trusted snapshot + Monte Carlo (common random numbers)
    SIM-->>API: cost, delay, stockouts for both
    API-->>OP: side-by-side diff: routes changed, cost delta, orders lost
    Note over API,SIM: Level 3: plans are also scored against ground truth by C12 (Admin view)
```

---

## 5. Diagram #5: Degradation mode state machine

F = fresh-source %, C = trusted-coverage %. Each transition requires its condition to hold for 60 sim-seconds.

```mermaid
stateDiagram-v2
    [*] --> NORMAL
    NORMAL --> DEGRADED: F < 90% or C < 85%
    NORMAL --> BLIND: F < 50%
    DEGRADED --> BLIND: F < 50%
    DEGRADED --> RECOVERY: F >= 90% and C >= 85%
    BLIND --> DEGRADED: F >= 50%
    RECOVERY --> NORMAL: stable 10 sim-min and reconciliation done
    RECOVERY --> DEGRADED: F < 90% or C < 85%
    RECOVERY --> BLIND: F < 50%

    NORMAL: fresh and trusted data
    DEGRADED: prefer trusted sources, widen uncertainty
    BLIND: last trusted state + forecasts + dead reckoning, bands grow with age
    RECOVERY: reconcile predicted vs reported, record error, shrink bands
```

---

## 6. Event-driven decision chain (ADD §5.1)

```mermaid
flowchart LR
    E1[Telemetry event] --> E2[Validation +<br/>trust scoring C04]
    E2 --> E3[Pattern detection C17<br/>spatial-temporal cluster]
    E3 --> E4[Cause inference C17<br/>weather, alerts, rest stops,<br/>toll plazas, gate scans]
    E4 --> E5[Twin state update C05<br/>link status + confidence]
    E5 --> E6[Risk prediction C08]
    E6 --> E7[Scenario simulation C09]
    E7 --> E8[Optimization C10]
    E8 --> E9[Recommendation C11<br/>human approves]
    E3 -.->|guard: trust-weighted quorum| E3
    E4 -.->|guard: independent corroboration<br/>else SUSPECTED| E5
```

Inference and simulation run automatically. **Execution always needs human approval** in the MVP. The `auto_action_policy` config key exists but defaults to `off`. It is documented only as a future extension (ADD §5.4).

---

## 7. Blockage inference sequence with adversarial guard (ADD §5.2–5.3, F-93, F-94)

### 7.1 Parameters (configurable, defaults)

| Param | Default | Meaning |
|---|---|---|
| N | 4 | Minimum number of trusted vehicles in the cluster |
| R | 2 km | Cluster radius, on the same link |
| T | 15 sim-min | Minimum stop duration |
| v_stop | 5 km/h | Stop speed threshold |
| τ_min | 0.80 | Only readings from Trusted entities count |
| Q | 3.2 | Trust-weighted quorum (Σ τ needed for q = 1) |
| k_ind | 2 | Independent sources (fleets) needed to count as independent confirmation |
| X_max | 0.20 | Contradiction ratio above which the reporters are flagged |
| conf_block | 0.75 | Confidence needed for BLOCKED_INFERRED |
| conf_suspect | 0.40 | Confidence needed for SUSPECTED |

### 7.2 Algorithm

```
cluster  = trusted readings (tau >= 0.80) on link l within R, speed < v_stop, for >= T
if |cluster| < N: return
if cluster overlaps a registered rest stop / toll plaza AND stop duration < 45 min AND no context: return  # benign cause
q  = min(1, Σ tau_i / Q)
I  = min(1, distinct_fleets(cluster) / k_ind)
E  = max(weather_severity_on_corridor >= 0.6 ? 0.8 : 0,
         alert_intersects_link ? 0.9 : 0,
         gate_scan_halt_at_downstream_node ? 0.9 : 0)
X  = Σ tau(trusted vehicles traversing l at > 30 km/h in window) / (that + Σ tau_i)
conf = q * (0.4 + 0.6 * max(I, E)) * (1 - X)
if conf >= 0.75 and (E > 0 or I >= 1):   status = BLOCKED_INFERRED  -> auto simulate + optimize
elif conf >= 0.40:                        status = SUSPECTED         -> ask human to confirm; no routing change
else:                                     status = OPEN (logged)
if X > 0.20: flag cluster reporters (context c_C = 0.2) + raise coordinated_anomaly alert
```

### 7.3 Sequence

```mermaid
sequenceDiagram
    autonumber
    participant V as Trucks on L053 (FLEET-A)
    participant O as Other trucks (FLEET-B, C)
    participant TR as Trust Engine C04
    participant INF as Inference C17
    participant CTX as Signals C07 / C08
    participant TW as Twin C05
    participant SIM as Simulation C09
    participant OPZ as Optimizer C10
    participant OPR as Operator
    V->>TR: speed about 0 readings
    TR->>INF: trusted readings only (tau >= 0.80)
    O->>TR: normal-speed readings on same link
    TR->>INF: trusted readings
    INF->>INF: cluster check N, R, T met
    INF->>INF: quorum q = min(1, sum tau / Q)
    INF->>CTX: weather, alerts, gate scans for L053
    CTX-->>INF: corroboration E, rest-stop registry
    INF->>INF: independence I, contradiction X, conf
    alt conf >= 0.75 and corroborated
        INF->>TW: link L053 = BLOCKED_INFERRED (conf)
        TW->>SIM: trigger cascade + Monte Carlo
        SIM->>OPZ: impacts
        OPZ->>OPR: recommendation with evidence
        OPR-->>OPZ: approve / modify
    else 0.40 <= conf < 0.75 or no corroboration
        INF->>TW: link L053 = SUSPECTED (conf), routing unchanged
        INF->>OPR: confirm blockage? evidence shown
    else conf < 0.40
        INF->>INF: log only
    end
    opt X > 0.20
        INF->>TR: lower context check for cluster reporters
        INF->>OPR: coordinated_anomaly alert to Security Analyst
    end
```

Worked numbers for a coordinated spoof (conf 0.51, SUSPECTED, no auto reroute) and a real blockage (conf 1.0, BLOCKED_INFERRED) are in `02_ARCHITECTURE.md` §5.5 D.

---

## 8. Diagram #6: Cascade propagation sequence (port closure)

```mermaid
sequenceDiagram
    autonumber
    participant SC as Scenario Lab
    participant SIM as Cascade engine C09
    participant PORT as P-CHE port
    participant SHP as Shipments / vessels
    participant WH as Warehouses W-CHE, W-BLR
    participant FAC as Factory F-SRI
    participant CUS as Customers C-CHE, C-BLR, C-KOC
    participant UI as Cascade View
    SC->>SIM: port_closure(P-CHE, 48h), seed
    SIM->>PORT: T+0 cap = 0 on L022, L023, L029, L030
    PORT->>SHP: inbound vessels queue, congestion rises
    SHP->>WH: T+2..T+12 expected inbound units missing
    WH->>WH: inventory depletes vs safety stock
    WH->>FAC: T+10 SKU-C components short at F-SRI (via W-CHE)
    FAC->>WH: T+14 F-SRI output reduced, finished goods short
    WH->>CUS: T+18 first stockout at W-CHE SKU-C
    CUS->>CUS: orders at risk rise, late penalties accrue
    SIM->>UI: frame per hour T+0..T+72 (inventory, backlog, link util, cost)
    SIM->>UI: KPI ribbon: delay, cost, orders affected, inventory at risk
    Note over SIM,UI: hours shown are illustrative, engine computes actual timings
```

---

## 9. Diagram #7: Proactive weather workflow (BRIEF §5 canonical workflow)

```mermaid
sequenceDiagram
    autonumber
    participant OM as Open-Meteo (LIVE)
    participant SIGW as Signals C07
    participant RISK as Risk C08
    participant SIM as Simulation C09 (MC 200)
    participant OPZ as Optimizer C10
    participant COP as Copilot C13
    participant UI as Early Warning / Strategies
    participant OPR as Operator
    participant DEC as Decision C11
    SIGW->>OM: hourly forecast for HYD-VGA sample points
    alt API fails
        SIGW->>SIGW: fall back to cached REPLAY, label REPLAY
    end
    OM-->>SIGW: precip, gusts, codes
    SIGW->>RISK: signal.weather (corridor features)
    RISK->>RISK: p = sigmoid(features), calibrated
    RISK->>UI: corridor risk, p, drivers, lead time about 8h
    RISK->>SIM: trigger (p >= 0.2 and active flow on corridor)
    SIM->>SIM: do nothing vs reroute vs transfer vs hybrid, common random numbers
    SIM-->>OPZ: L0, L1, P50 / P90, robustness
    OPZ->>OPZ: C_a per strategy, EV: expected avoided = p (L0 - L1), net, p*
    OPZ-->>COP: structured output JSON
    COP-->>UI: narrative (numbers validated against JSON)
    OPZ-->>UI: futures table + break-even p* vs current p
    OPR->>UI: Approve (or Modify objective / constraints)
    UI->>DEC: POST /decisions
    DEC->>DEC: audit entry (inputs + trust snapshot + versions)
    DEC-->>UI: twin updated, shipments rerouted
```

---

## 10. Diagram #8: Evaluation loop

```mermaid
flowchart LR
    subgraph HIDDEN[Hidden - truth schema]
        GT[Ground-truth world C01<br/>true positions, inventory,<br/>demand, outcomes]
        LB[Observation labels<br/>is_attacked, injector, true_value]
    end
    GT -->|noisy / attacked observations| ING[Ingestion + Trust C02/C04]
    ING --> TW[Twin belief C05]
    TW --> PLAN[Recommendations and decisions C10/C11]
    PLAN -->|executed plans| GT

    GT -.-> EV[Evaluation C12]
    LB -.-> EV
    TW -.-> EV
    ING -.->|quarantine + detections| EV
    PLAN -.-> EV
    ORC[Oracle optimizer<br/>perfect information] -.-> EV
    GT -.-> ORC

    EV --> M1[Fidelity: ETA MAE/MAPE,<br/>inventory error, stockout P/R,<br/>cascade accuracy]
    EV --> M2[Decision: regret vs oracle,<br/>service level, cost, CO2]
    EV --> M3[Security: detection rate, FPR,<br/>time-to-detect, time-to-recover,<br/>mode correctness]
    EV --> M4[Performance: events/s, p95 latency,<br/>sim and solver runtime]
    M1 --> BT[Resilience Benchmark table<br/>seeded, reproducible]
    M2 --> BT
    M3 --> BT
    M4 --> BT
    BT --> UI[Evaluation page + Grafana]
    BT --> DR[Drift over time]
```

---

## 11. Blackout and recovery flow (UC-06)

```mermaid
sequenceDiagram
    autonumber
    participant AC as Attack Center
    participant W as World C01
    participant TR as Trust + Mode C04
    participant TW as Twin C05
    participant UI as Control Room
    AC->>W: inject mass_blackout(70% sources, 20 sim-min)
    W--xTR: 70% of sources silent
    TR->>TR: F falls: 100 -> 85 -> 30
    TR->>UI: mode.changed NORMAL -> DEGRADED (F < 90)
    TR->>UI: mode.changed DEGRADED -> BLIND (F < 50)
    TW->>TW: dead-reckon along routes, bands grow with age
    TW->>UI: freshness heatmap, widened ETA bands
    W->>TR: sources resume
    TR->>UI: BLIND -> DEGRADED (F >= 50) -> RECOVERY (F >= 90, C >= 85)
    TW->>TW: reconcile predicted vs reported, record blind-period error
    TR->>UI: RECOVERY -> NORMAL after 10 sim-min stable
```
