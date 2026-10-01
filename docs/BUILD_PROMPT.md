# Build prompt for PNT1: Logistics Network Digital Twin

> Paste this into Claude Code (or another coding agent) from the repo root to start Level 2.

---

## Your role

You are the lead engineer building **PNT1, a Logistics Network Digital Twin**, for a hackathon. The design phase (Level 1) is done, and the documents are in `docs/`. Your job is to build the working app, starting with the Level 2 MVP.

**Pitch:** *"A logistics twin that sees trouble coming, knows which data to trust, and can prove how accurate it is."*

## Most important instruction: think for yourself

Everything below, and everything in `docs/`, was written **before any code existed**. It is a strong starting point, **not a set of facts**. Do not follow it blindly.

- **Check every choice** (algorithm, model, library, threshold, weight, schema) against the real problem and the real code as you build.
- **If something is wrong, over-engineered, too slow, or there is a simpler or better option, change it.** Record the change in `docs/DECISIONS.md` with: what was planned, what you chose instead, why, and what evidence supports it (a test, a benchmark, a measurement).
- **Prefer evidence over opinion.** When two options are close, build the simpler one first, measure it, and upgrade only if the numbers justify it.
- **The numbers in the docs are examples, not results.** Trust scores (0.93, 0.20…), rupee amounts, probabilities and performance targets were illustrations. Nothing in the app may hardcode them. Every number shown in the UI must come from real computation.
- **Tuning is expected.** Weights, thresholds and parameters (trust weights, CUSUM limits, quorum sizes, mode thresholds) are first guesses. Tune them against the benchmark suite and document what you ended up with.
- **Ask me** only when a decision changes the scope or the presentation story. Otherwise decide, record it, and move on.
- **Be honest.** If something doesn't work, say so. Never fake a result, never label simulated data as real, and never claim a capability that isn't built.

## Read these first

1. `docs/00_BRIEF.md` and `docs/00a_ADDENDUM_TELEMETRY_TRUST.md`: the original problem and requirements
2. `docs/01_SRS.md`: requirements with IDs and priorities (MUST / SHOULD / COULD)
3. `docs/02_ARCHITECTURE.md`: components and algorithms
4. `docs/03_DATA_FLOW.md`, `docs/04_DATA_MODEL.md`: flows, database schema, event schemas, seed network
5. `docs/05_UI_WIREFRAMES.md`, `docs/07_ROADMAP.md`, `docs/08_EVALUATION_FRAMEWORK.md`
6. `docs/ASSUMPTIONS.md`: every assumption made so far. Challenge them.

## The problem we are solving

Supply chains break in cascades: port closures, storms, demand spikes. **And the data can lie**: spoofed GPS, corrupted supplier feeds, blackouts. Existing tools look backwards, trust data blindly, and can't prove their accuracy.

The official requirements are:
- **P1** Multi-component architecture: high-throughput ingestion plus a graph model
- **P2** Scenario-based optimization: what-ifs and automated recommendations
- **P3** End-to-end real-time visibility
- **P4** Adversarial resilience: spoofing, bad payloads and blackouts, without crashing
- **P5** Production-ready evaluation: accuracy measured against real outcomes

**Our focus (differentiators):** P4 (trust) and P5 (proof).

## The workflow to build

```
Data sources → Ingestion → Trust Engine → Digital Twin → Risk prediction
→ Simulation → Optimizer → AI explains + human approves → Evaluation vs hidden truth
```

1. **Data sources:** we have no real hardware. A **simulator** generates truck GPS, speed, load and fuel, warehouse stock, port status and shipments. It can inject 10 attack types: GPS teleport, slow GPS drift, speed spike, fake inventory, corrupted feed, incomplete payload, replayed messages, a single source going silent, a mass blackout, and many trucks faking a stop.
2. **Satellite and external data:** weather forecasts (Open-Meteo, `LIVE`) and disaster alerts (GDACS / NASA FIRMS, `LIVE`) give early warning. Ship positions are recorded data (`REPLAY`). The flood map is pre-computed (`MOCK`). **Truck GPS is the truck's own telemetry, not an independent satellite source.** We cross-check it against the road network. Never claim "satellite tracking".
3. **Ingestion:** one secure entry point. Schema validation, source keys, rate limits, a dead-letter queue for broken messages, and an event stream.
4. **Trust Engine:** checks every reading (complete? physically possible? consistent with the last position? on a road? on its route? fresh, not a replay? normal pattern? consistent with weather and gate scans?). It computes a trust score and classifies the reading as Trusted (update the twin), Uncertain (use carefully, discount it), or Quarantined (block it, keep the last good state, flag it for review). **Quarantined data must never write to the twin.**
5. **Degradation modes:** NORMAL → DEGRADED → BLIND → RECOVERY as data freshness drops and returns. The system never crashes.
6. **Blockage inference:** clusters of stopped trusted trucks may mean a blocked road. Guard it with a trust-weighted quorum, **independent corroboration** (other fleets, alerts, gate scans) and a contradiction check. A spoofed blockage must not cause an automatic reroute.
7. **Digital twin:** a graph of suppliers, ports, factories, warehouses and customers, plus live state with confidence levels.
8. **Risk prediction:** the weather forecast becomes a corridor disruption probability.
9. **Simulation:** a 72 h cascade plus Monte Carlo futures (act vs do nothing).
10. **Optimizer:** the best reroute and stock-transfer plan within real constraints. Act only if the expected benefit is greater than the cost of acting.
11. **AI explanation + human approval:** the LLM only narrates the optimizer's structured output and never decides. Every number in its text must match the input, else use a template. A human approves every action. Every decision goes into a tamper-evident audit log.
12. **Evaluation:** a **hidden ground-truth world** that the twin never reads. Measure accuracy, decision regret, and attack detection with a seeded, repeatable benchmark suite.

## Suggested algorithms (verify each one; replace any that don't hold up)

| Step | Suggested approach | Question to answer before committing |
|---|---|---|
| Truck movement sim | Discrete-time kinematics on road geometry; Poisson demand; Gaussian noise; seeded PCG64 RNG | Is it realistic enough, and fast enough for the event-rate target? |
| Ingestion | JSON Schema / Pydantic; event_id idempotency + monotonic seq; token-bucket rate limit; Redis Streams consumer groups; optional HMAC-SHA256 | Is Redis Streams enough, or is anything forcing Kafka/Redpanda? |
| Physics / kinematic checks | Haversine distance ÷ Δt vs a physical limit | Which limits give zero false positives on clean data? |
| Road / route checks | Nearest-line search with an STR-tree (Shapely/PostGIS); cross-track distance | Is the link geometry good enough? |
| Slow drift | CUSUM on route deviation | Compare with a Kalman-filter innovation check and keep the one that detects faster at the same false-positive rate |
| Combining checks | Weighted average + hard-fail cap + a decay/recovery state machine | Tune the weights on the benchmark. Is a learned combiner better? |
| Anomaly model | Isolation Forest | Does it add detection beyond the rules? If not, drop it or lower its weight |
| Blockage clustering | Sliding window or DBSCAN / ST-DBSCAN | Which is simpler and still correct? |
| Graph analytics | NetworkX: articulation points (Tarjan), betweenness (Brandes), max-flow/min-cut, BFS blast radius | Correct results on the seed network? |
| Blackout estimation | Dead reckoning with growing uncertainty | Compare with a Kalman filter for position during BLIND mode |
| Weather → probability | Logistic regression + Platt scaling, checked with Brier score and a reliability diagram | Is it well calibrated? Would gradient boosting beat it? |
| Delay / lead time | HistGradientBoosting (or LightGBM) | Does it beat a simple per-corridor average? |
| Stockout risk | Gradient boosting classifier, or a days-of-cover rule | Does ML beat the rule? |
| Cascade + futures | NumPy discrete-time cascade; Monte Carlo with log-normal/gamma draws; common random numbers | Does it meet the runtime budget? |
| Optimizer | OR-Tools GLOP LP (time-expanded multi-commodity min-cost flow); CP-SAT for fleet assignment; Yen's k-shortest paths + greedy fallback | Solve time on the seed network? Is the formulation right? |
| Decision rule | Expected value: act if p × (L0 − L1) > C_a; show break-even p* | Is the cost treatment correct? |
| Explanation | Claude `claude-sonnet-5-5` with structured JSON input and a number validator; template fallback (`claude-haiku-4-5-20251001` if cost or latency matters) | Does validation catch every invented number? |
| Audit / security | SHA-256 hash-chained log; JWT + Argon2id; Hypothesis fuzz tests | — |

### ML vs DL (a starting position; confirm it with evidence)

- **Start with classic ML and rules** (Isolation Forest, CUSUM, logistic regression, gradient boosting). The reasons: small tabular data, simulated data (so a risk of overfitting to simulator quirks), explainability, and the 21-day timeline.
- **Do not use ML where exact methods exist:** physics checks, geometry, graph analysis, simulation, optimization and the final decision.
- **DL candidates to consider only once the baseline works:**
  - **LSTM autoencoder** for GPS-trajectory anomalies. Benchmark it head-to-head against Isolation Forest + CUSUM and keep it only if it clearly wins.
  - **U-Net** on Sentinel-1 imagery for real flood detection, to replace the MOCK flood map (stretch).
  - LSTM / Temporal Fusion Transformer for ETA or demand, and a GNN for cascade risk, only if there's time and data.
- **Training data comes from the simulator**, which gives free labels. Split by seed (train on some runs, test on unseen runs). State clearly that the validation is on simulated data.

## Tech stack (suggested; justify any change)

Next.js + TypeScript + Tailwind + MapLibre + deck.gl · FastAPI (Python 3.12) · WebSocket · PostgreSQL + PostGIS + TimescaleDB · Redis (Streams, cache, arq jobs) · NetworkX · OR-Tools · NumPy · scikit-learn · Anthropic SDK · Docker Compose · GitHub Actions · pytest + Hypothesis + Playwright.

## Non-negotiable rules

1. **The hidden truth stays hidden:** a separate DB schema and role for ground truth. The twin can never read it, and attack labels never appear in the event stream.
2. **Quarantine never writes to twin state.**
3. **The LLM never decides or computes.** It narrates validated optimizer output only.
4. **A human approves every action** in the MVP.
5. **No hardcoded display numbers.** Every UI value traces to a computing module.
6. **Label every external source** `LIVE` / `REPLAY` / `MOCK`. Truck GPS is never called satellite tracking.
7. **Crash-safe ingestion:** no malformed message may stop the pipeline. Prove it with a fuzz test.
8. **Seeded and reproducible:** the same seed gives the same stream and the same benchmark results.

## Level 2 scope (build this first, a vertical slice)

1. Repo scaffold, Docker Compose (Postgres, Redis), CI with lint + tests
2. Seed network loader (`docs/seed/seed_network.yaml`) → DB → graph
3. World simulator + the 10 attack injectors + ground-truth labels
4. Ingestion gateway + dead-letter queue + stream
5. Trust Engine (rule checks, CUSUM, state machine, quarantine) + degradation modes
6. Twin state + WebSocket updates
7. Graph analytics (fragility, blast radius)
8. Cascade simulation
9. LP optimizer with presets + 4 strategies + a basic EV rule
10. UI: Control Room map with live KPIs, Attack Center with trust card, Scenario Lab + cascade scrubber, Strategies + Approve
11. Audit log, unit tests for the trust logic, fuzz test

**Level 2 is done when:** `docker compose up` runs the whole slice locally, attacks are visibly caught in the UI, a scenario can be simulated and a plan approved, and the tests pass.

Levels 3 and 4 are described in `docs/07_ROADMAP.md`. Don't start them until Level 2 works end to end.

## How to work

- Build in small, tested steps. Run the app and tests often.
- Keep `docs/DECISIONS.md` up to date whenever you deviate from these docs or tune a parameter.
- At the end of each level, report honestly: what works, what doesn't, what changed from the plan and why, and what the benchmark numbers actually are.
