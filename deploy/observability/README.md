# Observability stack

A self-contained OTel pipeline you can boot locally to watch the
backend's traces + SLO metrics in real time.

```
backend (FastAPI + OTel SDK)
       │
       │  OTLP/gRPC :4317                 /metrics
       ▼                                     ▲
  OTel Collector ───► Tempo (traces)         │
        │                                    │
        └────► Prometheus (metrics) ◄────────┘
                       │
                       ▼
                    Grafana
        http://localhost:3001/d/pa-guard-slo
```

## Boot it

```bash
# From repo root:
docker compose --profile observability up -d
```

Then point the backend at the collector:

```bash
export PAG_OTEL_ENABLED=true
export PAG_OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export PAG_OTEL_TRACES_SAMPLE_RATE=1.0
pip install -e "backend[otel]"
uvicorn pa_guard.api.main:app
```

Submit a PA via `curl` (or the web UI). Within ~30 s:

- **Tempo** stores the request's full span tree
  (`agent.IntakeAgent`, `agent.PolicyResearcherAgent`, ..., `httpx`
  client spans).
- **Prometheus** pulls `/metrics` from the backend and the collector's
  remote-write endpoint, exposing every metric prefixed with
  `pa_guard_`.
- **Grafana** loads the `PriorAuthGuard / SLO` dashboard with overall
  status, per-SLO table, per-agent latency / success-rate time series,
  and the error-budget burn over time.

## Privacy

The OTel pipeline never carries PHI:

- Backend spans carry only KPIs + UUIDs + codes
  (see [`docs/observability.md`](../../docs/observability.md)).
- The collector's `attributes/strip_pii` processor drops any attribute
  whose name suggests free text (`pa_guard.kpi.narrative`,
  `pa_guard.what_failed`) as a defense-in-depth measure.
- `/metrics` is computed from numeric aggregates in `OutcomeLogger`; no
  identifier or label is ever derived from PHI.

## Components

| Container | Image | Port |
|---|---|---|
| otel | `otel/opentelemetry-collector-contrib:0.114.0` | 4317 (gRPC), 4318 (HTTP), 8888 (self-metrics) |
| tempo | `grafana/tempo:2.6.0` | 3200 |
| prometheus | `prom/prometheus:v3.0.0` | 9090 |
| grafana | `grafana/grafana:11.3.0` | 3001 (host) → 3000 (container) |

## Provisioning

- `grafana/provisioning/datasources/datasources.yaml` registers
  Prometheus + Tempo as Grafana datasources.
- `grafana/provisioning/dashboards/dashboards.yaml` mounts the
  `PriorAuthGuard` dashboard folder.
- `grafana/dashboards/slo.json` is the SLO dashboard — overall stat,
  denial rate, FHE-coverage, per-SLO table, per-agent latency / success
  series, error-budget burn timeseries.

No manual click-ops required — `grafana` starts with the dashboard
already imported.

## Production posture

Production deployments swap each piece for the managed equivalent:

- Collector → managed OTel collector (ADOT / GCP Ops Agent / vendor).
- Tempo → Grafana Cloud Tempo / vendor traces backend.
- Prometheus → Mimir / Thanos / vendor metrics backend.
- Grafana → Grafana Cloud or self-hosted with SSO.

The backend instrumentation never changes — it always speaks OTLP and
exposes `/metrics`.
