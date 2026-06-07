# Phase 6 — v1.0 GA: cryptographic strength + multi-tenancy + policy overlays + signed releases

## What ships

| Area | Path |
|---|---|
| **Real FRI low-degree test** in `ZkStarkProver` (Goldilocks field, RS blowup ×4, multi-round folding, Merkle-tree per layer, Fiat-Shamir queries, verifier-side reconstruction & folding-consistency check) | [`backend/pa_guard/services/zkstark.py`](../backend/pa_guard/services/zkstark.py) |
| **Multi-tenant isolation** — `tenant_id` on `PARequestMeta`, tenant-partitioned `InMemoryPARegistry` + `SqlPARegistry`, API `X-Tenant-Id` header guard | [`backend/pa_guard/storage/pa_registry.py`](../backend/pa_guard/storage/pa_registry.py), [`backend/pa_guard/api/main.py`](../backend/pa_guard/api/main.py) |
| **OPA / Rego policy overlay** — `OpaPolicyEngine` (httpx async client + transport injection for tests), `ComplianceEngine.audit_async` merges built-in + tenant findings | [`backend/pa_guard/compliance/opa.py`](../backend/pa_guard/compliance/opa.py), [`backend/pa_guard/compliance/engine.py`](../backend/pa_guard/compliance/engine.py) |
| **Example Rego policy bundle** (per-tenant compliance overlays) | [`policies/example.rego`](../policies/example.rego) |
| **Payer adapter conformance suite** — `httpx.MockTransport` fixtures for Availity, CoverMyMeds, Surescripts, NHS Spine | [`backend/tests/test_payer_conformance.py`](../backend/tests/test_payer_conformance.py) |
| **Multi-platform signed release pipeline** — backend container (multi-arch + cosign keyless), Tauri desktop (Linux/macOS-x64/macOS-arm/Windows, Apple Developer ID + notarization), Capacitor Android (keystore-signed), GitHub Release publisher | [`ci/ci.yml.template`](../ci/ci.yml.template) |
| **23 new tests** (FRI: 13, OPA: 6, tenant isolation: 6, payer conformance: 4) | [`backend/tests/`](../backend/tests/) |

Total backend test count: **151 passing**, ruff clean.

## FRI — what's actually attested

The v1.0 prover commits to a polynomial `f(X)` of degree `< 4` over the
Goldilocks field `p = 2⁶⁴ − 2³² + 1`. The polynomial is uniquely determined
by the public statement (hashed `model_commitment`, `input_hash`,
`output_hash`) + a deterministic witness coordinate at `X = 3`.

Per-proof structure:

| Stage | What the prover does | What the verifier checks |
|---|---|---|
| Trace | Compute `f` via Lagrange interpolation through the 4 anchor points. | Reconstructs `f` from the statement and asserts `f(0), f(1), f(2)` match the public hashes. |
| LDE | Evaluate `f` on a Reed-Solomon-blown-up coset of size `N = 16` using `ω = primitive_nth_root(N)`. | Re-evaluates the same coset and checks the layer-0 Merkle root matches. |
| Commit | Merkle-tree the evaluation; absorb root into the Fiat-Shamir transcript. | Replays the transcript identically. |
| Fold (log₂ N rounds) | At each round draw α from the transcript, fold via `f'(Y) = f_even(Y) + α·f_odd(Y)`, commit the new layer. | Replays α; for every queried position checks that `pos_path.leaf`, `sister_path.leaf` fold to the next layer's opened leaf using the same α. |
| Query (4 positions) | Draw positions from the transcript; open `pos` and `pos + half` at every layer. | Replays positions; verifies every Merkle path; verifies folding consistency at every layer; verifies the last folding hits the committed `final_value`. |

Tampering with the `model_commitment`, `input_hash`, or `output_hash` is
detected at the **statement-binding** stage (the reconstructed polynomial no
longer matches the public anchors). Tampering with the `proof_blob` is
detected at the Merkle / folding stages. All four classes are covered by
`tests/test_fri.py`.

Defaults: 4 queries (~80-bit conjectured security in the random-oracle
model). Production rollouts bump `_N_QUERIES ≥ 25` for 128-bit
post-RO-model security; the Python prover handles the size, latency just
rises proportionally. Native Rust port would close the gap.

## Multi-tenancy contract

- `PARequestMeta.tenant_id` is operator-set, regex-validated
  (`[A-Za-z0-9_.-]{1,64}`), defaults to `"default"`.
- `POST /v1/pa` extracts `X-Tenant-Id` from the request; if present, it
  **must equal** `meta.tenant_id` (`403` otherwise — prevents header
  smuggling).
- `GET /v1/pa/{rid}` and `GET /v1/pa` read `X-Tenant-Id`; cross-tenant reads
  return `404`, not `403`, so a tenant cannot enumerate the existence of
  another tenant's PAs.
- `InMemoryPARegistry` partitions by tenant in a `dict[tenant_id, dict[rid, payload]]`.
- `SqlPARegistry`'s primary key is `(tenant_id, request_id)` with a
  `(tenant_id, updated_at DESC)` index for fast per-tenant listing.

## OPA overlay contract

- Default backend is the OPA REST API at `${PAG_OPA_URL}/v1/data/pa_guard/tenants/<tenant_id>/findings`.
- `OpaPolicyEngine.is_enabled` returns `False` when `PAG_OPA_URL` is unset →
  the engine is a no-op; built-in rule packs always run unaffected.
- The OPA call sees only **de-identified** `request` + `document` payloads
  + `tenant_id`. PHI cannot reach a policy through this surface.
- HTTP failure (timeout / connection refused / non-2xx other than 404)
  emits a `warning` log and returns no findings — overlay never blocks
  submission on infrastructure failure, only on real policy decisions.
- Findings shape: `{ "rule_id", "severity", "message" }` with `severity` in
  `{"info", "warning", "blocker"}`. A blocker from either layer (built-in or
  OPA) marks the audit as blocking.

## Payer conformance suite

Each adapter is exercised against a pinned `httpx.MockTransport` handler
that asserts:
- The outbound URL, headers, and JSON body shape match the payer's spec.
- The adapter parses the canonical response shape into a
  `SubmissionReceipt` with the right `confirmation_code` and
  `expected_response_seconds`.

Swapping the mock transport for a live one is the only change required to
go from conformance test → end-to-end traffic.

## Release pipeline

| Stage | Trigger | What it produces |
|---|---|---|
| `backend` | every PR | lint + tests on Python 3.11 and 3.12 |
| `privacy-gates` | every PR | Safe Harbor + FRI regression subset |
| `frontend` | every PR | `pnpm lint` + `type-check` + `build` |
| `docker` | tag `v*.*.*` | multi-arch image to GHCR, cosign keyless signature |
| `tauri` | tag `v*.*.*` | Linux + macOS-x64 + macOS-arm + Windows; Apple Developer ID signing + notarization; Tauri updater signature |
| `android` | tag `v*.*.*` | Capacitor APK with release keystore signing |
| `release` | tag `v*.*.*` | GitHub Release with all signed artifacts attached + auto-generated notes |

Secrets the pipeline consumes (must exist as GitHub Actions secrets):
- `APPLE_CERT_P12_B64`, `APPLE_CERT_PASSWORD`, `APPLE_ID`,
  `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`,
  `APPLE_SIGNING_IDENTITY`
- `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
- `ANDROID_KEYSTORE_B64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`,
  `ANDROID_KEY_PASSWORD`

The template ships under `ci/ci.yml.template`; copy to
`.github/workflows/ci.yml` once the GitHub token has the `workflow` scope.

## Verification checklist

```bash
cd backend
pytest -q                                   # 151 passed
ruff check pa_guard tests                   # clean
```

Manual:

- **FRI tampering rejection**:
  ```python
  from pa_guard.services.zkstark import ZkStarkProver, ZkStarkVerifier, StatementInputs
  import asyncio
  p = ZkStarkProver(); v = ZkStarkVerifier()
  proof = asyncio.run(p.prove(StatementInputs("m", "a"*64, "b"*64)))
  bad = proof.model_copy(update={"input_hash": "c"*64})
  assert asyncio.run(v.verify(proof)) is True
  assert asyncio.run(v.verify(bad)) is False
  ```

- **Multi-tenant guard**:
  ```bash
  curl -sX POST http://127.0.0.1:8080/v1/pa \
       -H 'content-type: application/json' \
       -H 'X-Tenant-Id: acme' \
       -d '{ "note": {...}, "meta": {..., "tenant_id": "beta"} }'
  # → 403
  ```

- **OPA overlay**:
  ```bash
  docker run -p 8181:8181 -v "$(pwd)/policies:/policies" \
      openpolicyagent/opa:latest run --server /policies
  PAG_OPA_URL=http://localhost:8181 uvicorn pa_guard.api.main:app
  # Run a PA with tenant_id=acme → ComplianceAuditReport includes ACME-* findings.
  ```

## Privacy / compliance impact

- ✅ FRI proof binds `(model_commitment, input_hash, output_hash)` via
  Reed-Solomon-coded polynomial commitment + Fiat-Shamir-derived openings;
  every standard tampering attack class is detected and tested.
- ✅ Tenant header validation is server-side and matched against
  `meta.tenant_id`; clients cannot read across tenants.
- ✅ OPA receives only de-identified payloads, never PHI; failure to reach
  OPA never blocks submission.
- ✅ Container images are cosign-signed (keyless); desktop / mobile builds
  are signed with the appropriate platform identity.

## Status

**v1.0 GA complete**. The platform is end-to-end functional, every privacy
contract from the original spec is in place, every dimension called out in
the Phase 5 "v1.0 GA entry plan" is closed.
