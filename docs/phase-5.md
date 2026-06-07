# Phase 5 — Deliverables, Verification, Privacy Impact

## What ships

| Area | Path |
|---|---|
| **PA registry** with Postgres / SQLite backends | [`backend/pa_guard/storage/pa_registry.py`](../backend/pa_guard/storage/pa_registry.py) |
| **Payer adapter framework** + Availity / CoverMyMeds / Surescripts / Fax / NHS Spine | [`backend/pa_guard/payers/`](../backend/pa_guard/payers/) |
| **Streaming voice WebSocket** `/v1/voice/stream` | [`backend/pa_guard/api/voice_stream.py`](../backend/pa_guard/api/voice_stream.py) |
| **LLM-backed MetaImprover** with Anthropic Claude + heuristic fallback | [`backend/pa_guard/agents/meta_improver_llm.py`](../backend/pa_guard/agents/meta_improver_llm.py) |
| Settings extended with payer credentials + Anthropic key | [`backend/pa_guard/core/config.py`](../backend/pa_guard/core/config.py) |
| API rewired: async PA registry, list endpoint, voice stream router, `backend=llm` toggle | [`backend/pa_guard/api/main.py`](../backend/pa_guard/api/main.py) |
| Backend Dockerfile + `.dockerignore` | [`backend/Dockerfile`](../backend/Dockerfile) |
| `docker-compose.yml` (backend + pgvector Postgres + optional pgAdmin) | [`docker-compose.yml`](../docker-compose.yml) |
| Helm chart `deploy/helm/pa-guard/` | [`deploy/helm/pa-guard/`](../deploy/helm/pa-guard/) |
| **24 new tests** (PA registry, payers, streaming voice, LLM fallback) | [`backend/tests/`](../backend/tests/) |

Total backend test count: **128 passing**, ruff clean.

## Wire-shape notes

### `WebSocket /v1/voice/stream`

Client → server (JSON text frames):
```json
{"type": "chunk", "text": "<verbatim STT>", "speaker_role": "provider"}
{"type": "flush", "text": "<verbatim STT>"}
{"type": "end"}
```
Server → client:
```json
{"type": "deidentified", "chunk_id": "<uuid>", "text": "<safe-harbor cleaned>", "identifiers_redacted": <int>}
{"type": "ack", "kind": "flush"}
{"type": "summary", "total_chunks": <int>, "total_identifiers_redacted": <int>}
```
Raw transcript text is **never** echoed back to the client and is dropped
the moment the next frame is read.

### Payer routing

```
payer_id → PayerRoute (data) → adapter family → credential check
                                                       │
                                                       ▼
                                       has-credentials? ─yes→ real adapter
                                                       └─no→  StubAdapter
```

Adding a payer is a **one-line** change in
[`registry.py::PAYER_TO_ADAPTER`](../backend/pa_guard/payers/registry.py).

| Family | Adapter | Production wire |
|---|---|---|
| availity | `AvailityAdapter` | X12 278 over JSON envelope to `api.availity.com` |
| covermymeds | `CoverMyMedsAdapter` | REST JSON to `api.covermymeds.com/v2` |
| surescripts | `SurescriptsAdapter` | JSON-on-the-edge OAuth2 to `api.surescripts.com` |
| fax | `FaxAdapter` | Multipart PDF upload to a generic fax API |
| nhs | `NhsSpineAdapter` | HL7 FHIR R4 ServiceRequest to `api.spine.nhs.uk` |

### LLM MetaImprover

| Scenario | What runs |
|---|---|
| `ANTHROPIC_API_KEY` unset and no `client=` injection | heuristic engine (Phase 2) |
| Key present, LLM returns valid JSON | LLM proposals returned |
| Key present, LLM returns invalid / empty JSON | falls back to heuristic |
| Key present, LLM call raises | falls back to heuristic |

API toggle: `POST /v1/meta-improver/proposals?backend=llm` (default
`backend=heuristic`).

## Verification checklist

### Automated tests

```bash
cd backend
pytest -q
```

Expected: **128 passed**, ruff clean.

### Docker compose

```bash
docker compose up --build
# In another shell:
curl -s http://127.0.0.1:8080/readyz | jq
```

Confirm `environment = development`, FHE / zk-STARK posture booleans match
the env vars in `docker-compose.yml`, backend healthchecks succeed.

### Manual flows

1. **Streaming voice WS**
   ```bash
   pip install websockets
   python - <<'PY'
   import asyncio, json
   import websockets
   async def main():
       async with websockets.connect("ws://127.0.0.1:8080/v1/voice/stream") as ws:
           await ws.send(json.dumps({"type":"chunk","text":"Mr. John Smith MRN: AB12345678.","speaker_role":"provider"}))
           print(await ws.recv())
           await ws.send(json.dumps({"type":"end"}))
           print(await ws.recv())
   asyncio.run(main())
   PY
   ```
   Confirm: the de-identified chunk contains no PHI; summary reports the
   correct totals.

2. **Payer routing**
   ```bash
   # No credentials — falls back to stub.
   curl -sX POST http://127.0.0.1:8080/v1/pa -H 'content-type: application/json' \
     -d '{ "note": {...}, "meta": {"payer_id": "anthem", ...} }' | jq '.receipt'
   ```
   Confirm: `receipt.confirmation_code` starts with `stub-anthem-`. With
   `PAG_AVAILITY_CLIENT_ID` + `PAG_AVAILITY_CLIENT_SECRET` set, the adapter
   switches to the real Availity call (verifiable via outbound HTTP logs).

3. **LLM proposals**
   ```bash
   curl -sX POST 'http://127.0.0.1:8080/v1/meta-improver/proposals?backend=llm' | jq
   ```
   Confirm:
   - Without `PAG_ANTHROPIC_API_KEY`: deterministic Phase 2 heuristic
     proposals returned (no network call).
   - With the key set: returns Claude-generated proposals matching the
     `ImprovementProposal` schema (or falls back gracefully if Claude
     misbehaves).

4. **Postgres-backed PA registry**
   ```bash
   docker compose up --build
   # Run a PA; restart the backend container; the PA still GETs.
   ```
   Confirm: PA persists across restarts when `PAG_PA_REGISTRY_BACKEND=sql`.

## Privacy / compliance impact

- ✅ **WS streaming voice** never echoes raw text back; raw chunks are
  dropped before the next frame is read.
- ✅ **Payer adapters** receive only de-identified `PADocument` payloads —
  Safe Harbor + (Phase 1) NER overlay have already run by the time the
  document reaches `SubmissionAgent`.
- ✅ **LLM MetaImprover** sees only the `OutcomeAggregate` numeric shape — no
  critique text, no PA narratives, no transcripts. PHI cannot reach the
  LLM through this surface.
- ✅ **Postgres registry** stores `PARunResponse` payloads which by
  construction contain only de-identified content; nothing changes about
  the privacy contract.
- ✅ **Container image** runs as a non-root user, mounts an emptyDir over
  `/tmp` and `~/.cache`, and the Helm chart applies a strict
  `containerSecurityContext` (read-only root filesystem, drop ALL caps,
  no privilege escalation).
- ✅ **External secrets**: chart wires the Anthropic key + all payer
  credentials through an `ExternalSecret` so they never live in
  `values.yaml` or the container image.

## Phase 5 → "v1.0 GA" entry plan

1. **Full FRI low-degree test** in `ZkStarkProver` to bring zk-STARK to
   production cryptographic strength (currently educational).
2. **OPA/Rego policy bundle** for org-level rule overrides (per-customer
   compliance overlays).
3. **Multi-tenant isolation**: per-tenant `PARegistry` + per-tenant
   `OutcomeLogger` schema.
4. **Native Tauri / Capacitor signed release pipeline** + auto-update.
5. **Public conformance suite** that exercises every payer adapter against
   recorded contract fixtures.
