# 06 — Tech Stack (finalised)

**Rule applied:** each layer gets one decision with a one- or two-sentence reason. A fallback is listed only when the choice is risky. Anything over-engineered for the timeline is flagged ⚠.

## 1. Decision table

| Layer | Decision | Justification | Fallback (only if risky) | Level |
|---|---|---|---|---|
| Frontend framework | **Next.js 15 (App Router) + TypeScript + Tailwind CSS** | Typed UI with fast iteration. The control room is client-heavy, so we use Next.js mainly as a React build and routing tool and not for SSR complexity. | — | L2 |
| Map rendering | **MapLibre GL JS + deck.gl** (ScatterplotLayer, PathLayer, ArcLayer, TripsLayer) | MapLibre needs no API token and works offline with a bundled style. deck.gl animates 100+ vehicles and cascade colouring on the GPU. | Plain MapLibre GeoJSON layers if deck.gl integration slips. | L2 |
| Charts | **Recharts** | Enough for trust-over-time, P50/P90 bands and drift charts. It is declarative and needs no custom D3. | — | L2 |
| UI state / data | **TanStack Query** for REST, a small **Zustand** store for live WebSocket state | Keeps server cache and live stream state separate. Both are small. | — | L2 |
| Backend API | **FastAPI (Python 3.12) + Pydantic v2** | Same language as OR-Tools, NumPy and scikit-learn. Pydantic models double as event-schema validators and generate OpenAPI. | — | L2 |
| Realtime to UI | **WebSocket** (FastAPI native) with a 1 Hz state-diff channel and an event channel | Needs to be bidirectional for sim-clock control and attack injection. Diffs keep the payload small. | SSE if a proxy blocks WS. | L2 |
| Event bus | **Redis Streams** (consumer groups) behind a `Bus` interface | One piece of infrastructure gives the bus, cache and pub/sub. Consumer groups give at-least-once delivery, and idempotency via `event_id` gives effective once. 5k–50k events/min is well within a single Redis. **Tradeoff vs Kafka/Redpanda:** no long retention or partition replay, which we cover by persisting raw events to a Timescale hypertable. Redpanda is the documented L4+ swap. | Redpanda (Kafka API), same interface. | L2 |
| Background jobs | **arq** (async Redis job queue) | Monte Carlo, benchmark runs and optimizer re-runs must not block API workers. arq reuses Redis and asyncio. | — | L2 |
| Database | **PostgreSQL 16 + PostGIS 3 + TimescaleDB** (`timescale/timescaledb-ha` image) | PostGIS handles road snapping and geofences. Timescale hypertables handle telemetry, trust history and metrics, with retention and compression. One engine, one backup. | `postgis/postgis` plus native range partitioning if the Timescale image causes problems. | L2 |
| ORM / migrations | **SQLAlchemy 2 (async) + Alembic** | Standard and typed, and migrations are needed for the L2 "DB schemas" criterion. | — | L2 |
| Graph | **NetworkX (MultiDiGraph) in memory**, persisted in Postgres `node`/`link` tables | 40 nodes and 92 links is tiny. NetworkX has articulation points, betweenness, min-cut and k-shortest paths out of the box. **Neo4j is not included**: it would add infrastructure without adding capability at this size. | — | L2 |
| Optimization | **Google OR-Tools**: GLOP (LP) for flow and reallocation, CP-SAT for fleet assignment (SHOULD) | Free, fast, and covers LP and MILP/CP. A 5 s time limit is supported natively. | k-shortest-path greedy heuristic (built in-house, always available). | L2 |
| Simulation / Monte Carlo | **NumPy** (vectorised discrete-time engine) | 200 runs × 72 steps × 40 nodes is about 0.6 M cell updates per SKU. Vectorised NumPy does this in seconds. **SimPy was rejected**: event-level process simulation is slower and not needed at a 1 h step. | — | L2 |
| ML | **scikit-learn**: IsolationForest (telemetry anomaly), LogisticRegression plus Platt scaling (disruption probability), HistGradientBoostingRegressor (lead-time multipliers, S) | Each model changes a decision: trust score, EV trigger, ETA. HistGradientBoosting avoids adding XGBoost or LightGBM as dependencies. ⚠ Nothing larger is justified. | — | L3 |
| Anomaly approach | **Rules first** (schema, physics, kinematic, road-network, route with CUSUM, temporal) **+ IsolationForest** as a low-weight statistical check | Rules are explainable and catch the hard attacks deterministically. The forest catches out-of-pattern combinations. It is weighted at 0.05 so it can never hide a hard fail on its own. | — | L2 rules / L3 IF |
| Geospatial checks | **Shapely 2 + PostGIS** (`ST_DWithin`, `ST_LineLocatePoint`); link geometry from an OSRM export pre-baked into seed data | Road-network match and cross-track deviation need line geometry. It is pre-computed, so there is no runtime OSRM dependency. | Straight-line link geometry (lower fidelity). | L2 |
| External signals | **httpx** with **tenacity** retries plus an on-disk replay cache | Handles Open-Meteo and GDACS timeouts well. Every live response is recorded for replay. | Recorded replay files (always shipped). | L3 |
| LLM | **Anthropic Claude API**, model `claude-sonnet-5-5`, via the `anthropic` Python SDK. Structured JSON goes in, and a prose narrative comes out, validated against a schema. | Used only for explanations (F-45). Numbers in the output are checked against the input JSON, and the narrative is rejected if a number does not match. | Deterministic Jinja2 template narrative. | L3 |
| AuthN / AuthZ | **JWT** (PyJWT, HS256, 15 min access token and 8 h refresh token) + **argon2id** (`argon2-cffi`) + role guard (Viewer / Operator / Admin) | Simple, stateless and enough for three roles. | — | L3 |
| Source authentication | **Per-source API keys**; **HMAC-SHA256** envelope signatures using Python stdlib `hmac` (F-97, COULD) | No extra library. Keys are rotated through the Admin API. | — | L3 (keys) / C (HMAC) |
| Transport security | **Caddy 2** reverse proxy with automatic Let's Encrypt TLS 1.2+, HSTS | Zero-config HTTPS on one VM. | — | L3 |
| Secrets | **Docker secrets / `.env` injected by GitHub Actions** from the repository's encrypted secrets. Nothing is committed. | Enough for one VM. ⚠ Vault is over-engineering here. | — | L3 |
| Rate limiting | **Redis token bucket** middleware (per source key on `/ingest`, per user on the API) | Uses the Redis we already run. | — | L3 |
| Containers | **Docker + Docker Compose** with profiles (`core`, `observability`, `offline`) | One file runs locally, in CI and on the VM. | — | L3/L4 |
| CI/CD | **GitHub Actions**: ruff + mypy + eslint → pytest (with Hypothesis fuzz) → Playwright smoke → build and push images to GHCR → SSH deploy (`docker compose pull && up -d`) | Free and native to the repo. | — | L3 |
| Cloud | **AWS EC2 t3.xlarge (4 vCPU, 16 GB), ap-south-1** | Low latency for the India presentation. Student credits usually cover it. One VM keeps cost at about ₹10–12k per month and can be switched off between sessions. | Render (Docker) if AWS access is blocked. | L3 |
| Cache | **Redis 7** (the same instance, logical DB 1) for twin snapshots, graph-analytics results and weather responses | The fragility audit and snapshot reads are the hot, cacheable paths. | — | L4 |
| Monitoring | **Prometheus + Grafana + Alertmanager**; `prometheus-fastapi-instrumentator`; custom counters (events/s, DLQ, trust anomalies, mode) | Standard stack with a ready-made Grafana dashboard. Alert rules show L4 "active monitoring". | — | L4 |
| Logging | **structlog** JSON logs with `trace_id` and `run_id`; Grafana Loki is COULD | Machine-readable logs for audit and debugging. ⚠ Loki only if time allows. | — | L3 |
| Testing | **pytest**, **Hypothesis** (property and fuzz tests for the F-98 crash-safety requirement), **Playwright** (UI smoke), **Locust** (L4 load), seeded **benchmark suite** (`make bench`) | Covers unit, fuzz, E2E, load and evaluation in one place. | — | L2–L4 |
| Orchestration | **Kubernetes manifests + HPA (COULD)**, tested on `kind` | ⚠ Only if time remains (F-75). Compose with `--scale ingest-worker=N` shows the scaling design. | — | L4 (C) |

## 2. Explicitly rejected

| Option | Why rejected |
|---|---|
| Kafka / Redpanda at L2 | ZooKeeper/KRaft setup, JVM memory use and operational cost for no benefit below about 100k events/min. It stays available behind the `Bus` interface. |
| Neo4j | The graph is 40 nodes. NetworkX does all the analytics in milliseconds. |
| SimPy | We do not need event-level process simulation at a 1 h step. NumPy vectorisation is 10–100× faster for Monte Carlo. |
| XGBoost / LightGBM | HistGradientBoosting gives about the same accuracy on small tabular data with no extra dependency. |
| Mapbox | Needs a token and has billing risk. MapLibre is a drop-in replacement. |
| Blockchain, a generic chatbot, a 3D twin | Non-goals (BRIEF §4.9). |

## 3. Module-to-process mapping (preview; details in `02_ARCHITECTURE.md` §3)

| Container | Python entrypoint | Modules |
|---|---|---|
| `api` | `pnt1.api.main` | api, twin (read), graph, sim (single run), opt, decision, explain, eval (read) |
| `ingest-worker` (scalable) | `pnt1.ingest.worker` | ingest consumer, trust, twin (write), inference |
| `signals-worker` | `pnt1.signals.worker` | signals, risk |
| `job-worker` (scalable) | `pnt1.jobs.worker` (arq) | sim (Monte Carlo), eval (benchmark), opt (re-runs) |
| `world-sim` | `pnt1.world.main` | world (ground truth + telemetry simulator + injectors + replay) |
| `gateway` | inside `api` at L2, split at L4 | ingest gateway (HTTP `/ingest/batch`) |
| `web` | Next.js | frontend |
| `postgres`, `redis`, `caddy`, `prometheus`, `grafana`, `alertmanager` | — | infrastructure |

## 4. Version pins (initial)

Python 3.12, FastAPI 0.11x, Pydantic 2.x, SQLAlchemy 2.0, OR-Tools 9.x, NumPy 2.x, scikit-learn 1.5+, NetworkX 3.x, Shapely 2.x, Node 22 LTS, Next.js 15, MapLibre GL 4.x, deck.gl 9.x, Postgres 16, Redis 7.2, Caddy 2.8. Exact versions will be pinned in `pyproject.toml` / `package-lock.json` at Level 2.
