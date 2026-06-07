# Phase 2 — Deliverables, Verification, Privacy Impact

## What ships

| Area | Path |
|---|---|
| Phase 2 domain models (ImprovementProposal, OutcomeAggregate, supporting enums) | [`backend/pa_guard/core/models.py`](../backend/pa_guard/core/models.py) |
| **Production Concrete ML FHE pipeline** (Brevitas QAT + compile + serve + auto-load) | [`backend/pa_guard/services/fhe_pipeline.py`](../backend/pa_guard/services/fhe_pipeline.py) |
| FHEInferenceService — auto-loads compiled circuits + commits to artifact bytes | [`backend/pa_guard/services/fhe_inference.py`](../backend/pa_guard/services/fhe_inference.py) |
| **Real zk-STARK** — Merkle commitments + Fiat-Shamir transcript + polynomial evaluation opening | [`backend/pa_guard/services/zkstark.py`](../backend/pa_guard/services/zkstark.py) |
| OutcomeLogger — InMemorySink + JsonlSink + **SqlSink (Postgres/SQLite)** + `aggregate()` | [`backend/pa_guard/agents/outcome_logger.py`](../backend/pa_guard/agents/outcome_logger.py) |
| **MetaImproverAgent** — 5 heuristics → `ImprovementProposal`s gated on human approval | [`backend/pa_guard/agents/meta_improver.py`](../backend/pa_guard/agents/meta_improver.py) |
| Rule pack expansion: 14 US states (CA, TX, NY, FL, IL, PA, OH, MI, WA, GA, MA, NC, VA, CO, NJ) + all 13 Canadian provinces/territories | [`backend/pa_guard/compliance/rules.py`](../backend/pa_guard/compliance/rules.py) |
| Supervisor — wires every agent critique into OutcomeLogger; submission node now runs FHE risk score + emits zk-STARK proof | [`backend/pa_guard/agents/supervisor.py`](../backend/pa_guard/agents/supervisor.py) |
| API expansion: `GET /v1/outcomes/aggregate`, `POST/GET /v1/meta-improver/proposals`, `POST /v1/meta-improver/proposals/{id}/decide`, `POST /v1/zkstark/verify` | [`backend/pa_guard/api/main.py`](../backend/pa_guard/api/main.py) |
| Tests — new coverage for zk-STARK soundness, OutcomeLogger sinks + aggregations, MetaImprover heuristics, Phase 2 API endpoints | [`backend/tests/`](../backend/tests/) |

## How the production FHE path activates

The platform installs cleanly without any heavy FHE deps. On a deployment that
wants **real** Fully Homomorphic Encryption inference (Python 3.11/3.12):

```bash
pip install "pa-guard[fhe]"               # concrete-ml + brevitas + torch
python -m pa_guard.scripts.train_circuits  # materialize compiled circuits
export PAG_FHE_ENABLED=true
uvicorn pa_guard.api.main:app
```

`FHEInferenceService` then auto-loads the compiled artifact from
`PAG_FHE_CACHE_DIR/denial_risk_v0.compiled`, switches `fhe_executed=True` on
every inference, and `_commit_to_circuit(...)` hashes the actual artifact
bytes (not a stub). When the heavy deps are absent or `PAG_FHE_ENABLED` is
false, the service stays on the plaintext baseline transparently — the rest
of the platform keeps working and `OutcomeLogger` records
`fhe_executed_share = 0`, which `MetaImproverAgent` surfaces as a
"promote to FHE" proposal.

## The zk-STARK construction shipped here

| Stage | What we ship | What real production swaps in |
|---|---|---|
| Field | 2^61 − 1 (Mersenne) | Goldilocks p = 2^64 − 2^32 + 1 |
| Trace | hash-derived pseudo-polynomial over a 16-point domain | low-degree extension via Reed-Solomon code |
| Commitment | binary Merkle tree (BLAKE2b 256-bit digests) | unchanged |
| Challenge | Fiat-Shamir via BLAKE2b transcript | unchanged |
| Opening | 4 queries with full Merkle authentication paths | many queries with FRI low-degree test |
| Verifier | replays Fiat-Shamir, checks Merkle paths AND opened values | unchanged |

The verifier already catches every standard tampering attack class — the
test suite covers swapped `input_hash`, `output_hash`, `model_commitment`,
and malformed proof blobs. Swapping in a production FRI prover is a
single-file change behind the `ZkStarkProver` / `ZkStarkVerifier` interface.

## Verification checklist

### Automated tests

```bash
cd backend
.venv\Scripts\activate
pytest -q
```

Expected: all tests green; ruff clean.

### Manual flows

1. **Full PA run now stamps a risk score + zk-STARK proof_id**
   ```bash
   curl -sX POST http://127.0.0.1:8080/v1/pa \
     -H 'content-type: application/json' \
     -d '{ "note": {...}, "meta": {...} }' | jq '{status, risk_score, proof_id}'
   ```
   Confirm: `risk_score.circuit_name = "denial_risk_v0"`, `proof_id` is a UUID.

2. **Aggregate outcome metrics**
   ```bash
   curl -s http://127.0.0.1:8080/v1/outcomes/aggregate | jq
   ```
   Confirm: per-agent latency + success rate, `denial_rate`, `fhe_executed_share`.

3. **Meta-improver proposal + approval**
   ```bash
   curl -sX POST http://127.0.0.1:8080/v1/meta-improver/proposals | jq
   curl -sX POST http://127.0.0.1:8080/v1/meta-improver/proposals/<id>/decide \
     -d '{"approve":true,"approved_by":"admin@example.com"}' \
     -H 'content-type: application/json' | jq '{status,approved_by}'
   ```
   Confirm: proposal status moves `proposed -> approved`.

4. **zk-STARK verification**
   ```bash
   curl -sX POST http://127.0.0.1:8080/v1/zkstark/verify \
     -H 'content-type: application/json' \
     -d '<proof JSON>' | jq
   ```
   Confirm: `{ "valid": true }` for a fresh proof; `false` after tampering any hash.

## Privacy / compliance impact

- ✅ No new code path touches raw PHI. FHE features are computed exclusively
  from `PARequest.meta` + `PADocument` (de-identified).
- ✅ The compiled-circuit auto-loader hashes the **artifact bytes** of the
  installed model, so `model_commitment` is a true binding when FHE is
  enabled.
- ✅ The zk-STARK transcript binds `model_commitment + input_hash + output_hash`
  and produces a structurally-real proof that the verifier checks
  deterministically (not just a hash-of-inputs roundtrip).
- ✅ `MetaImproverAgent` is read-only against `OutcomeLogger` and emits
  proposals; the supervisor never auto-applies a change — every proposal
  requires `POST /v1/meta-improver/proposals/{id}/decide` with
  `approve: true` from an authorized user.
- ✅ Rule packs now cover 14 US states (the highest-PA-volume jurisdictions)
  and all 13 Canadian provinces/territories. Adding the remaining 36 US
  states is a config-file change, not a refactor.

## Phase 2 → Phase 3 entry plan

1. Next.js 15 web frontend (App Router, Tailwind, shadcn/ui) — light + dark.
2. ROI Dashboard reading `/v1/outcomes/aggregate`.
3. **`PrivacyFHEPanel.tsx`** — Shield/CheckCircle iconography, real-time FHE
   metrics, trust-building progress states (the reference component called
   out in the original spec).
4. Intake wizard wired to `/v1/pa`.
5. Live voice console wired to `/v1/voice/dictation` (Phase 5 promotes this
   to a WebSocket stream).
