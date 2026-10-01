# 10 — Risks and Scope

## 1. Risk register

Likelihood (L) and impact (I) are scored 1–3. Score = L × I. **Owner** is a role from `07_ROADMAP.md`.

| ID | Risk | L | I | Score | Mitigation | Trigger / early signal | Owner |
|---|---|---|---|---|---|---|---|
| R-01 | **Scope creep**: building breadth instead of the vertical slice | 3 | 3 | 9 | MoSCoW in the SRS; the "never cut" list in `07_ROADMAP.md` §5; every new idea needs a requirement ID and a cut-line position | L2 gate at risk on day 7 | ALL |
| R-02 | **External API downtime or rate limits** (Open-Meteo, GDACS, Claude) | 2 | 3 | 6 | Replay cache of every live response; `REPLAY` badge; tenacity retries; LLM → template fallback; offline compose profile | Connector error rate > 0 in CI smoke | BE |
| R-03 | **Unrealistic synthetic data** makes results meaningless | 2 | 3 | 6 | Realistic geography and base times (documented); noise and missing-data profiles; demand seasonality; parameters in YAML; say "synthetic" openly | Judges question realism; ETA MAE implausibly low | BE |
| R-04 | **Optimizer too slow** for a live presentation | 2 | 3 | 6 | LP rather than MILP for the core; 6 h buckets; 5 s time limit; heuristic fallback ≤ 1 s; `solver_status` shown | Solve > 3 s on the seed network | OPT |
| R-05 | **LLM hallucinates decisions or numbers** | 2 | 3 | 6 | LLM receives structured JSON only; never computes; numeric validator rejects any number not in the input; template fallback; `explanation_source` shown | Validator rejection rate > 10% | BE |
| R-06 | **False positives in anomaly detection** (quarantining good data) | 3 | 2 | 6 | Hard checks only for physics/network; soft checks weighted; IsolationForest weight 0.05; cooldown; FPR measured per scenario (target ≤ 2%); analyst "false positive" review feeds source reputation | FPR > 2% on clean benchmark runs | OPT |
| R-07 | **Cloud cost / credit limits** | 1 | 2 | 2 | Single VM (about ₹10–12k/month), stop outside evaluation windows, budget alarm, Render fallback | Billing alert at 50% | OPS |
| R-08 | **Team skill gaps** (OR-Tools, deck.gl, Timescale) | 2 | 2 | 4 | Spikes on day 3 (T12, T14); plain MapLibre as fallback; plain Postgres partitioning as fallback; pair on the critical path | Spike not working by end of day 3 | ALL |
| R-09 | **Presentation day network failure** | 2 | 3 | 6 | Offline compose profile (all REPLAY, template narrative); recorded recorded walkthrough; committed benchmark results | Venue Wi-Fi test fails | OPS |
| R-10 | **Claiming data capabilities we do not have** | 2 | 3 | 6 | Labelling policy (LIVE/REPLAY/MOCK) on every source, record and badge; NFR-20 test; walkthrough script honesty rules | Any UI string without a badge (TS-UI-10) | ALL |
| R-11 | **Monte Carlo runtime** blows the budget | 2 | 2 | 4 | Vectorised NumPy across runs; common random numbers; job worker; partial-run results with a confidence badge; reduce to 100 runs as a documented degrade | MC > 15 s on the presentation seed | BE |
| R-12 | **UI animation performance** on the map | 2 | 2 | 4 | deck.gl GPU layers; 1 Hz diffs with client interpolation; pre-computed cascade frames; limit trails; fall back to plain MapLibre layers | FPS < 30 on the presentation laptop | FE |
| R-13 | **Detector false positives on the Trust Engine** at scale (e.g. GPS noise in urban canyons, tunnels) | 2 | 2 | 4 | Hdop-aware tolerance; road-match threshold 0.3 km before any penalty; per-source reputation; the benchmark includes clean-run FPR | Clean-run quarantine events | OPT |
| R-14 | **Subtle drift spoof evades detection** | 3 | 2 | 6 | Route consistency + CUSUM; statistical check; benchmark BM-02 reports TTD honestly (about 35–40 min at the default rate); stated as a known limitation with tuning knobs | BM-02 DR < 80% | OPT |
| R-15 | **Overclaiming satellite data as an independent position source** | 2 | 3 | 6 | The check is named "Geospatial / road-network match"; EO flood mask labelled MOCK; presentation Q&A answer prepared; doc review in the L1 checklist | Any doc or UI text saying "satellite match" | ALL |
| R-16 | **Inferred-blockage false positives** (rest stops, toll queues, coordinated spoof) | 2 | 3 | 6 | Rest-stop and toll-plaza registry; T ≥ 15 min; trust-weighted quorum; independent corroboration required for BLOCKED_INFERRED; contradiction check; human confirmation for SUSPECTED; BM-10 must show 0 false reroutes | BM-10 fails | OPT |
| R-17 | **Truth leakage** into the twin (invalidates every metric) | 1 | 3 | 3 | Separate schema and DB role; envelope `additionalProperties: false`; import-linter bans on `pnt1.world`; TS-SEC-04, TS-WORLD-06 | A twin_rw query on truth succeeds | OPS |
| R-18 | **Calibration circularity** criticised by judges | 3 | 1 | 3 | State it up front (UI tooltip, eval page, Q&A); present it as internal consistency, with real-world calibration as future work | — | OPT |
| R-19 | **Redis single point of failure** (bus + cache + jobs) | 2 | 2 | 4 | AOF persistence; raw events also in Postgres for replay; restart policy; Redpanda swap documented | Redis restart loses the PEL | OPS |
| R-20 | **Security gaps** at L3 (default creds, exposed ports) | 2 | 3 | 6 | Security group allows only 443 plus SSH from the CI IP; no default passwords (generated at deploy); gitleaks; RBAC tests; presentation role switch only when `GUIDED_MODE` | Port scan shows 5432/6379 open | OPS |

## 2. Cut-lines
The order and impact are defined in `07_ROADMAP.md` §5: K8s → EO imagery → AIS → counterfactual replay → LLM explanations → extra scenarios → fleet/recovery/what-if → IsolationForest/context checks.

## 3. Non-goals (explicitly not built)
- Blockchain or any distributed ledger
- A generic chatbot or free-text LLM Q&A (the Copilot only narrates optimizer output)
- 15 dashboards (12 purposeful screens only)
- A 3D twin
- A mobile app
- Real IoT hardware or real carrier, WMS or ERP integrations
- A fancy landing page
- ML models that do not change a decision
- Kubernetes purely for show (COULD, only after everything else)
- Satellite-based vehicle positioning, or processing raw Sentinel imagery
- Autonomous execution of reroutes (human approval is always required; `auto_action_policy` off)

## 4. Known limitations (stated honestly)
1. Every network and telemetry figure is synthetic. Fidelity metrics measure the twin against a simulated world, not against real operations.
2. Probability calibration is internal to the simulated world (ASSUMPTIONS D-12).
3. The drift spoof is detected with a delay of tens of minutes at slow drift rates. It is a trade-off against false positives.
4. The optimizer uses aggregated 6 h buckets. Individual vehicle routing detail comes from the fleet assignment (SHOULD) or the heuristic.
5. A single region, a single VM at L3, and no multi-region high availability.
