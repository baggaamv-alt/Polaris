# 08 — Evaluation Framework

**Goal (PDF P5):** measure how well the twin matches reality, how good its decisions are, and how well it resists attacks, using numbers that are computed, reproducible and hard to game.

Everything on this page is computed by **C12 Evaluation** (`pnt1.eval`), which is the only twin-side component with read access to the hidden `truth` schema. The per-metric "Computed by" column names the function.

---

## 1. Principles

1. **Hidden truth.** The twin sees only observations. The evaluator compares twin belief with truth after the fact.
2. **Labels, not guesses.** Every observation has a hidden label (`is_attacked`, `injector`, `true_value`; T-08). Detection metrics are computed against labels, not against the twin's own opinion.
3. **Oracle baseline.** Decision quality is measured against a perfect-information optimizer that is given the true state and true future disruptions.
4. **Seeded and versioned.** Each benchmark scenario is `(scenario_id, version, seed, command_log)`. One command runs everything.
5. **Report the honest caveats** next to the metric (for example the calibration circularity, §3.5).

---

## 2. Ground-truth design (F-60, T-08)

| Element | Truth (world, C01) | Twin sees |
|---|---|---|
| Vehicle position/speed | Exact kinematics on link geometry at 1 s resolution | GPS fixes every 5–30 s with N(0, 15 m) noise, 1% dropped, and injected attacks |
| Inventory | Exact units per node and SKU from simulated flows | Feed every 1 min with ±1% noise, 2% missing updates, and injected fake values |
| Demand/orders | True Poisson demand | Order events (these are accurate; orders are not attacked in the MVP) |
| Link/port status | True status incl. disruptions (weather-driven, scripted) | Port status events, weather forecasts, telemetry patterns |
| Disruption occurrence | Sampled from the world's weather→disruption model or a script | Forecasts (LIVE or REPLAY) and inferred events |
| Outcomes | Actual delivery times, stockouts and cost per order | Nothing (evaluation only) |

Storage: the `truth.*` tables (`04_DATA_MODEL.md` §4). Access: role `eval_ro` only.

---

## 3. Fidelity metrics (F-61)

Notation: `x̂` = twin belief, `x` = truth, over the evaluation set 𝒮.

| Metric | Formula | Computed by | Target (NFR-15) |
|---|---|---|---|
| **ETA MAE** | `(1/|𝒮|) Σ |ETÂ_i − arrival_i|` over delivered shipments, with the ETA taken at a fixed look-ahead (T−6 h and T−2 h, reported separately) | `eval.fidelity.eta_mae` | ≤ 45 min (NORMAL) |
| **ETA MAPE** | `(100/|𝒮|) Σ |ETÂ_i − arrival_i| / (arrival_i − t_pred_i)` | `eval.fidelity.eta_mape` | ≤ 15% |
| **ETA band coverage** | share of shipments whose true arrival falls inside the ±1.645σ band (a 90% band) | `eval.fidelity.eta_coverage` | 85–95% (well calibrated) |
| **Inventory MAPE** | `(100/|𝒮|) Σ_{n,s,t} |q̂_verified − q_true| / max(q_true, 10)`, sampled every 10 sim-min | `eval.fidelity.inventory_mape` | ≤ 5% (NORMAL) |
| **Ghost-inventory rate** | share of (n,s,t) with `q_reported − q_true > 10%` that the twin did **not** mark Estimated/Suspicious | `eval.fidelity.ghost_rate` | ≤ 10% |
| **Stockout precision / recall** | A prediction is positive if the twin forecasts a stockout of (n,s) within the next 24 h. TP = a true stockout occurs within 24 h. P = TP/(TP+FP), R = TP/(TP+FN) | `eval.fidelity.stockout_pr` | R ≥ 0.80, P ≥ 0.60 |
| **Stockout lead time** | median of (true stockout time − first correct prediction time) over TPs | `eval.fidelity.stockout_lead` | ≥ 6 h |
| **Cascade accuracy** | For a scenario, compare the simulated cascade (run at T+0 from the twin snapshot) with the truth over 72 h. (a) Jaccard of affected-node sets, (b) MAE of stockout times per affected (n,s), (c) relative error of orders at risk | `eval.fidelity.cascade` | Jaccard ≥ 0.75, orders-at-risk error ≤ 20% |
| **Blind-period error** | position error (km) and inventory MAPE of dead-reckoned state during BLIND, measured at RECOVERY reconciliation | `eval.fidelity.blind_error` | reported, no target |

### 3.5 Probability calibration (F-20)
- **Brier score** `BS = (1/N) Σ (p_i − o_i)²`, where o_i = 1 if the corridor was closed or degraded by ≥ 50% within 12 h in truth.
- **Reliability diagram** with 10 bins, and **ECE** `= Σ_b (n_b/N) |mean(p)_b − mean(o)_b|`.
- **Caveat (shown next to the chart):** the truth world generates disruptions from its own weather→disruption model, so calibration shows *internal consistency*, not real-world accuracy (ASSUMPTIONS D-12).
- Computed by `eval.calibration`.

### 3.6 Drift tracking (F-66)
A rolling 1 h window of ETA MAE, inventory MAPE and trusted-coverage C is stored as a time series (`eval.evaluation_result` with `suite='drift'`) and charted on the Evaluation page and in Grafana. If ETA MAE rises above 1.5× its 24 h baseline, a `twin_drift` alert fires.

---

## 4. Decision metrics (F-62)

| Metric | Formula | Computed by |
|---|---|---|
| **Decision regret (₹)** | `Regret = Cost_truth(plan_twin) − Cost_truth(plan_oracle)`, where both plans are executed in the truth world with the same random draws, and `plan_oracle` = the optimizer run on the true state and true future disruptions. Reported absolute and relative (`/ Cost_truth(plan_oracle)`) | `eval.decision.regret` |
| **Regret vs do-nothing** | `Cost_truth(do_nothing) − Cost_truth(plan_twin)` (value added) | `eval.decision.value_added` |
| **Service level** | units delivered on time / units demanded in the horizon | `eval.decision.service_level` |
| **Cost, delay, CO₂** | Σ realised cost (₹), Σ order-hours late, Σ kg CO₂ in the truth world | `eval.decision.kpis` |
| **Orders saved** | orders on time under the plan − orders on time under do-nothing | `eval.decision.orders_saved` |
| **EV realised vs predicted** | Compare the predicted expected loss avoided `p(L₀ − L₁)` with the realised loss difference, averaged over many seeded runs of the same scenario. It should agree within the MC P10–P90 band | `eval.decision.ev_check` |
| **Trust value-add** | `Cost_truth(plan_from_raw) − Cost_truth(plan_from_trusted)` for attack scenarios (the F-17 comparison, scored against truth) | `eval.decision.trust_value` |
| **False reroute rate** | share of scenarios where an **automatic** BLOCKED_INFERRED or an approved-by-default plan rerouted around a link that was open in truth | `eval.decision.false_reroute` |

---

## 5. Security / resilience metrics and the benchmark suite (F-63)

### 5.1 Metric definitions

| Metric | Formula | Computed by |
|---|---|---|
| **Detection rate (entity-level)** | A true incident is an (entity, attack window) pair labelled attacked. Detected = the entity reached Estimated or Quarantined (per the scenario's expected class) during the window + 5 min. DR = detected / true incidents | `eval.security.detection_rate` |
| **Reading-level recall** | share of attacked readings with ρ < 0.5 (hard attacks) or ρ < 0.8 (soft attacks) | `eval.security.reading_recall` |
| **False-positive rate** | readings from **non-attacked** entities classed Quarantined / all non-attacked readings. Also entity-level: share of clean entities that were ever quarantined | `eval.security.fpr` |
| **Time-to-detect (TTD)** | median of (first detection ts − attack start ts) over detected incidents | `eval.security.ttd` |
| **Time-to-recover (TTR)** | for blackout scenarios, time from source restoration to mode = NORMAL. For entity attacks, time from attack end to τ ≥ 0.8 | `eval.security.ttr` |
| **Mode correctness** | share of sim-minutes where the twin's mode equals the "oracle mode", computed from true F and C using the same thresholds | `eval.security.mode_accuracy` |
| **Decision quality vs oracle** | regret (§4) in the scenario, relative to the oracle | `eval.decision.regret` |
| **Crash count** | worker restarts plus unhandled exceptions during the scenario (must be 0) | `eval.ops.crashes` |

### 5.2 Benchmark scenarios (seeded; ≥ 10 required, 15 defined)

All run on the seed network, 120 vehicles, 6 h of sim time (except where noted), seed = `20261001 + scenario number`.

| ID | Scenario | Injector / disruption and params | Expected system behaviour | Primary metrics |
|---|---|---|---|---|
| BM-01 | GPS spoof: teleport | `gps_spoof_teleport` on 5 trucks, 1 jump each, into sea/out-of-reach | Quarantined on the first spoofed reading. Last trusted position kept | DR, TTD (target < 1 reading), FPR |
| BM-02 | GPS spoof: drift | `gps_spoof_drift` on 5 trucks, 0.15 km/5 min | Estimated then Quarantined via CUSUM | DR within 45 min (≥ 80%), TTD |
| BM-03 | Speed spike | `speed_spike` 780–812 km/h on 10 trucks | Hard fail on P → Quarantined | DR (≥ 95%), FPR |
| BM-04 | Fake inventory | `inventory_fake` +40% at W-HYD SKU-B | Flow reconciliation fails → Estimated/Suspicious. Optimizer discounts it. The raw plan would under-ship to W-HYD | DR, ghost rate, trust value-add |
| BM-05 | Corrupted supplier feed | `feed_corrupt` on S03 (type swaps, units ×1000) | Schema/range fail → feed Quarantined. Supplier availability is taken from the last trusted value | DR, crash count = 0 |
| BM-06 | Incomplete payloads | `payload_incomplete` 30% of messages from FLEET-C | Stale fields, reduced S. No crash. Quarantine only when τ < 0.5 | Crash count, FPR (should not quarantine en masse) |
| BM-07 | Duplicate / replay | `duplicate_replay` of 10 min of old messages | Dropped as duplicates or out-of-order. Source reputation lowered | Reading recall = 100%, twin state unchanged |
| BM-08 | Node blackout | `entity_blackout` of W-VGA feed + 10 trucks for 60 min | DEGRADED if F < 90. Uncertainty widens for affected entities | Mode correctness, blind error, TTR |
| BM-09 | Mass blackout | `mass_blackout` 70% of sources for 20 min | DEGRADED → BLIND → RECOVERY → NORMAL. No crash | Mode correctness, TTR, blind error, crash count |
| BM-10 | Coordinated stop spoof | `coordinated_stop_spoof` 8 FLEET-A trucks on L053 for 20 min, clear weather, FLEET-B/C traffic flowing | SUSPECTED (not blocked), no automatic reroute, coordinated_anomaly alert | **False reroute = 0**, alert raised |
| BM-11 | Port closure | P-CHE closed 48 h, 72 h horizon | Cascade predicted. Strategies generated. Hybrid preferred | Cascade accuracy, regret, service level |
| BM-12 | Demand spike | +60% SKU-B at C-HYD, C-VGA, C-BLR for 36 h | Transfers from W-BLR/W-CHE. Stockout avoided at W-HYD | Stockout P/R, regret, orders saved |
| BM-13 | Weather event (proactive) | Scripted heavy rain on HYD-VGA NH65 at T+8 h (truth closes L053/54 for 18 h with probability 0.7) | p computed. EV trigger → reroute via Khammam/rail before closure | Brier, EV realised vs predicted, regret |
| BM-14 | Compound | BM-11 + BM-12 + BM-01 at the same time | Interaction term > 0 reported. Attacks quarantined during the cascade. No crash | Regret, DR, interaction term |
| BM-15 | Real blockage (true positive for inference) | Truth blocks L061 (NH16S) with an accident. 6 trucks from 3 fleets stop, GDACS-like alert (REPLAY) | BLOCKED_INFERRED within T + 1 min. Reroute recommended | Inference TTD, regret |

### 5.3 Resilience Benchmark table (output format)

`make bench` writes `bench/results/<git_sha>/resilience_benchmark.md` and `.json`, and loads them into `eval.evaluation_result`. The UI renders the same table. Column meanings: DR = detection rate, FPR = false-positive rate (reading-level), TTD = median time-to-detect, TTR = time-to-recover, Regret = % over oracle, Mode acc = mode correctness, Crash = crash count, Pass = all scenario targets met.

| ID | Scenario | DR | FPR | TTD | TTR | Regret | Mode acc | Crash | Pass |
|---|---|---|---|---|---|---|---|---|---|
| BM-01 | GPS teleport | ‹computed› | ‹computed› | ‹computed› | ‹computed› | ‹computed› | ‹computed› | ‹computed› | ‹✓/✕› |
| … | … | … | … | … | … | … | … | … | … |
| **Σ** | **Overall** | mean | mean | median | median | mean | mean | sum | n/15 |

*No values are shown here on purpose. Values only come from runs.*

### 5.4 Per-injector detection matrix (ADD §10)

The same run also produces a matrix of **injector × {DR, reading recall, FPR, TTD}** for all 10 injectors in T-06, so weak spots stay visible (for example: drift TTD is expected to be much longer than teleport TTD).

### 5.5 Pass criteria (from NFR-14)
DR ≥ 95% for BM-01, 03, 05, 06, 07. DR ≥ 80% within 45 min for BM-02. FPR ≤ 2% on clean readings in every scenario. False reroute = 0 in BM-10. Crash = 0 everywhere. BM-09 reaches BLIND and then NORMAL.

---

## 6. Performance and scale metrics

| Metric | Definition | L2 target | L3 target | L4 target | How measured |
|---|---|---|---|---|---|
| Ingestion throughput | accepted events/min sustained, with 0 unaccounted | 5,000 | 5,000 (30 min) | 50,000 (10 min, lag ≤ 5 s) | world-sim load mode + counters (TS-PERF-01/05) |
| Ingest→twin latency | p95(`twin_applied_ts − ts_ingested`) | ≤ 3 s | ≤ 2 s | ≤ 2 s at 50k/min | histogram metric |
| API p95 latency | reads, at N concurrent users | ≤ 500 ms (5 users) | ≤ 300 ms (20) | ≤ 150 ms cached (100) | Locust |
| UI push latency | state change → rendered | ≤ 2 s | ≤ 1.5 s | ≤ 1.5 s | Playwright timing hook |
| Cascade runtime | single 72 h run | ≤ 2 s | ≤ 2 s | ≤ 1 s | pytest-benchmark |
| Monte Carlo runtime | 200 runs × 4 strategies | ≤ 30 s | ≤ 15 s | ≤ 8 s | pytest-benchmark |
| Optimizer runtime | GLOP solve / heuristic | ≤ 5 s / ≤ 1 s | same | same | solver stats |
| Scale-out efficiency | throughput(2 workers) / throughput(1) | — | — | ≥ 1.6× | load test |
| Availability | external 1-min probe success | — | ≥ 99.0% | ≥ 99.5% | uptime probe |

## 7. Crash-safety metric (F-98, NFR-09)
`TS-FUZZ-01`: Hypothesis generates 100,000 envelopes by mutating valid ones (bit flips, type swaps, truncation, huge strings, NaN/Inf, deep nesting, unicode, missing fields, extra fields) plus raw random bytes.
- **Pass:** 0 worker crashes, and `accepted + dlq + duplicate_dropped == sent`.
- It runs in CI on every PR with a reduced 10k budget, and nightly at the full budget.

## 8. Reproducibility
- `make bench` = `docker compose -f compose.bench.yml run --rm bench python -m pnt1.eval.bench --suite all --seed-base 20261001`.
- Scenario definitions are versioned in `bench/scenarios/BM-XX.yaml`. The results record `git_sha`, config hash, seed and the command-log hash.
- Deterministic metrics must match exactly on re-run. Timing metrics must be within ±10% on the same hardware.

## 9. Reporting
- **Evaluation page (UI):** fidelity cards, decision regret, the Resilience Benchmark table, the per-injector matrix, the calibration chart with its caveat, and the drift chart.
- **Grafana:** live fidelity drift, detection counters, performance.
- **Artifacts:** `bench/results/<sha>/` is committed for the final submission so judges can inspect the raw numbers.
