# SentinelOps — AI-Powered Self-Healing Microservices Platform

Predictive fault detection and autonomous remediation for Spring Boot microservices.
PBL project — Gracy Sonwan (2428010037), B.Tech CCE, Manipal University Jaipur. Mentor: Dr. Sunil Kumar Vasistha.

**Prototype status: about 75% complete.** All five layers run end-to-end on a local Docker Compose stack.
The remaining 25% is AWS deployment (ECS/Fargate, RDS, ECR, CloudWatch), live-traffic tuning and the demo video.

```
          load generator (10 orders/s)
                    |
                    v
   +-----------------------------------------+       Layer 1  Service layer
   |  order-service ---> inventory-service   |       (Spring Boot + PostgreSQL)
   |       |                                 |
   |       +--> payment-service (primary)    |
   |       +--> payment-standby  (failover)  |
   +-----------------------------------------+
     | every service embeds sentinel-chaos           Layer 2  Chaos layer
     | (latency creep, error burst, memory leak)
     v
   Actuator + Micrometer --> Prometheus (5 s)        Layer 3  Observability
                    |
                    v
   intelligence-service (FastAPI, Isolation Forest)  Layer 4  Intelligence
     learns normal -> scores every 5 s -> root cause -> forecast -> alert
                    |
                    v
   remediation-engine (Spring Boot)                  Layer 5  Remediation +
     reroute -> restart (Docker API) -> verify -> failback        visualisation
     control panel :8090        Grafana dashboard :3000
```

Diagrams: [`docs/architecture.png`](docs/architecture.png), [`docs/ai-pipeline.png`](docs/ai-pipeline.png), [`docs/remediation-sequence.png`](docs/remediation-sequence.png).

## What is implemented

| Layer | Component | Status |
|---|---|---|
| 1 Service | `order-service`, `payment-service` (primary + standby), `inventory-service` — Spring Boot 3.3, Java 17, JPA + PostgreSQL, REST | Done |
| 1 Containment | Resilience4j circuit breakers on Order → Payment/Inventory, automatic fallback to the standby payment instance | Done |
| 2 Chaos | `sentinel-chaos` library: gradual latency creep, growing error burst, heap memory leak, reset — REST API on every service | Done |
| 3 Observability | Actuator + Micrometer (latency histograms), Prometheus (5 s scrape), provisioned Grafana dashboard (21 panels) | Done |
| 4 Intelligence | FastAPI service: 7 health features from PromQL, per-service baseline learning, Isolation Forest scoring, root-cause hint, dependency-aware RCA, failure-time forecast, continuous re-training, model persistence | Done |
| 5 Remediation | Policy engine: reroute → restart container (Docker Engine API) → verify health → failback; cooldowns, dry-run mode, event history, Micrometer metrics | Done |
| 5 Visualisation | Control panel (inject faults, watch AI verdicts, remediation timeline, auto-remediation switch) + Grafana | Done |
| Evaluation | Offline evaluation on labelled synthetic traces (4 detectors, 4 fault types, ablation) + live experiment runner | Done |
| Cloud | AWS ECS/Fargate, ECR, RDS, CloudWatch deployment | **Remaining 25%** |

## Run it (Windows 11 + Docker Desktop)

### Step 1 — Prerequisites
1. Install **Docker Desktop** (WSL 2 backend) and start it.
2. In Docker Desktop → Settings → Resources, give it **at least 6 GB memory** (the stack runs 6 JVMs).
3. Make sure ports 3000, 5432, 8000, 8081–8084, 8090 and 9090 are free.

### Step 2 — Start the stack
Open PowerShell in this folder and run:
```powershell
docker compose up --build -d
```
The first build downloads Maven dependencies and images, so it takes 5–10 minutes. Later starts take under a minute.
Check that everything is up:
```powershell
docker compose ps
```
All services should show `running` (the Java ones `healthy`).

### Step 3 — Let the AI learn
Open the **control panel**: http://localhost:8090.
Each service card shows `LEARNING n/60`. The AI needs 60 samples × 5 s = **5 minutes** of normal traffic
(the load generator provides it). When every card says `MONITORING · Behaving normally`, you are ready.
The learned baselines are saved, so after a restart of the stack the AI starts monitoring immediately.

### Step 4 — Demo: chaos → prediction → self-healing
1. Open Grafana in a second window: http://localhost:3000 (dashboard "SentinelOps – Self-Healing Overview", login admin/admin to edit).
2. On the **payment-service** card click **Latency creep**. Latency now grows by 20 ms every second.
3. Within ~15–20 s the card turns red: *Anomaly confirmed · cause: latency*, with a forecast such as
   "p95_ms limit in ~70 s" — the failure has been **predicted before it happens**.
4. The remediation engine acts on its own; the timeline at the bottom shows:
   rerouted traffic to standby → restarted `sentinel-payment` → health check passed → failed back to primary.
5. Notice that orders kept succeeding the whole time (the topology bar shows `payment: standby` during recovery).
6. Repeat with **Error burst** on inventory-service and **Memory leak** on payment-service.
7. To show the difference, switch **Autonomous remediation** off, inject a fault, and watch the service
   degrade until it crosses the reactive limit (the AI still detects it — it just doesn't act).
   Click **Clear faults** (or **Heal now**) afterwards.

### Step 5 — Measure it (optional, for the report)
With the stack running and the AI in `MONITORING`:
```powershell
python experiments\run_scenarios.py --mode auto      # with self-healing
python experiments\run_scenarios.py --mode observe   # detection only (baseline)
```
Results (detection time, lead time, recovery time, user-facing error peak) are written to `experiments\results\`.

### Stop
```powershell
docker compose down          # keep data and learned models
docker compose down -v       # also delete database and learned models
```

## Tests and evaluation

```powershell
# Java unit tests (or right-click the test folders in IntelliJ -> Run Tests)
mvn test

# Python tests (features, detector, engine, API)
cd intelligence-service
pip install -r requirements.txt pytest
pytest

# Offline evaluation on synthetic traces (writes evaluation/results/results.json)
python -m evaluation.evaluate --seeds 20
```

## Running a service from IntelliJ (optional)
Start only the infrastructure with Docker (`docker compose up -d postgres prometheus grafana`), then run any
`*Application` class from IntelliJ. Without the Docker socket the remediation engine automatically switches
to **dry-run** mode: instead of restarting a container it clears the service's injected faults, and labels
the step `DRY-RUN` in the timeline.

## API reference

| Service | Endpoint | Purpose |
|---|---|---|
| order-service :8081 | `POST /orders` `{"productId":"P-100","quantity":2}` | place an order |
| | `GET /orders`, `GET /orders/{id}` | recent orders |
| | `GET/POST /admin/routing/payment?target=primary\|standby` | traffic switch used by remediation |
| payment-service :8082 (standby :8084) | `POST /payments`, `GET /payments` | process / list payments |
| inventory-service :8083 | `GET /inventory`, `POST /inventory/reserve` | catalogue / reserve stock |
| every service | `POST /chaos/latency?baseMs=0&rampMsPerSec=20` | latency creep |
| | `POST /chaos/errors?rate=0.05&rampPerSec=0.01` | growing error burst |
| | `POST /chaos/memory-leak?mbPerSec=1&maxMb=200` | heap leak |
| | `POST /chaos/reset`, `GET /chaos/status` | clear / inspect faults |
| | `GET /actuator/health`, `GET /actuator/prometheus` | health and metrics |
| intelligence-service :8000 | `GET /status`, `GET /alerts`, `GET /metrics` | AI verdicts, alert log, Prometheus metrics |
| | `POST /model/reset`, `POST /model/retrain/{service}` | relearn baselines |
| remediation-engine :8090 | `/` | control panel |
| | `POST /api/remediate` | alert intake (from the AI) |
| | `POST /api/remediate/{service}` | manual heal |
| | `GET /api/events`, `GET /api/overview` | remediation history, aggregated state |
| | `GET/POST /api/settings?autoRemediation=true\|false` | autonomous mode switch |

## Troubleshooting
- **A Java container keeps restarting** — usually not enough Docker memory; raise it to 6–8 GB.
- **Cards stay on `NO_DATA`** — Prometheus cannot scrape the service yet; check http://localhost:9090/targets.
- **Control panel says DRY-RUN while using Docker** — the Docker socket mount failed; make sure Docker Desktop
  uses the WSL 2 engine (Settings → General).
- **Port 5432 already in use** — another PostgreSQL is running; stop it or change `"5432:5432"` to `"5433:5432"`.
- **AI flags everything after you changed the load** — click relearn: `curl -X POST localhost:8000/model/reset`.

## Project structure
```
sentinelops/
├── pom.xml                      parent Maven build (Spring Boot 3.3.5, Java 17)
├── sentinel-chaos/              Layer 2 - fault-injection library
├── order-service/               Layer 1 - orders + Resilience4j circuit breakers + routing switch
├── payment-service/             Layer 1 - payments (primary and standby instances)
├── inventory-service/           Layer 1 - products and stock
├── remediation-engine/          Layer 5 - remediation policy, Docker API client, control panel
├── intelligence-service/        Layer 4 - FastAPI + Isolation Forest (Python 3.11)
│   ├── app/                     features, detector, engine, simulator, API
│   ├── evaluation/              offline evaluation
│   └── tests/                   pytest suite
├── observability/               Prometheus config, Grafana provisioning + dashboard
├── loadgen/                     steady order traffic
├── docs/                        architecture and flow diagrams
├── experiments/                 live chaos experiment runner
├── Dockerfile                   shared multi-stage build for the Java services
└── docker-compose.yml           the whole platform
```
