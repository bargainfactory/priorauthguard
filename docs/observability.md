# Observability — OpenTelemetry

## What's wired

When `PAG_OTEL_ENABLED=true` and the optional `[otel]` extras are
installed, the backend emits OTLP traces to
`PAG_OTEL_EXPORTER_OTLP_ENDPOINT` (defaults to `http://localhost:4317`).

Auto-instrumented surfaces:

- **FastAPI** — every request becomes a span; cross-service trace
  propagation via standard W3C headers.
- **SQLAlchemy** — `pa_runs` reads/writes appear as child spans of the
  request that triggered them.
- **httpx** — payer adapter calls (Availity / CoverMyMeds / Surescripts /
  NHS Spine / OPA) appear as child spans with the URL + status code as
  attributes.

Custom spans:

- `agent.<AgentName>` — every `BaseAgent.run` is its own span. Attributes
  include `pa_guard.agent.name`, `pa_guard.request_id`, and every KPI from
  the agent's auto-generated `AgentCritique` (`pa_guard.kpi.latency_ms`,
  `pa_guard.kpi.success`, plus any agent-specific KPI).

## Install + enable

```bash
cd backend
pip install -e ".[otel]"
export PAG_OTEL_ENABLED=true
export PAG_OTEL_SERVICE_NAME=pa-guard
export PAG_OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
export PAG_OTEL_TRACES_SAMPLE_RATE=0.10        # 10% in prod
uvicorn pa_guard.api.main:app
```

A reasonable local collector for development:

```bash
docker run -p 4317:4317 -p 4318:4318 \
    otel/opentelemetry-collector:latest --config /etc/otelcol/config.yaml
```

## Privacy contract

Span attributes contain **only**:

- Service / agent names.
- Numeric KPIs (latency, success, identifiers redacted, FHE-executed,
  Whisper duration, etc.).
- UUIDs (request id, document id, proof id).
- Codes (CPT / ICD-10 / payer id / tenant id).

PHI is **never** attached to a span. The critique payload's narrative
fields (`what_worked`, `what_failed`, `suggested_improvements`) are
explicitly excluded from the span emit — they live in the OutcomeLogger
where they're operationally needed, not in distributed traces where they
would multiply the surface area.

## Sampling

ParentBased(TraceIdRatioBased) — child spans inherit the parent's sampling
decision so a single PA produces a fully connected trace whether sampled
in or out. Tune via `PAG_OTEL_TRACES_SAMPLE_RATE` (0.0–1.0, default 1.0).

## Disabling

Unset `PAG_OTEL_ENABLED` (or set it to `false`). The SDK is never
imported, every code path stays a no-op, and no overhead is added to the
hot loops. The frontend has no observability code — the FastAPI handler
that serves its requests does.
