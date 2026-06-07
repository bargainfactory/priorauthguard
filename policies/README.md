# OPA / Rego policy bundle

This directory holds **per-tenant compliance overlays** that layer on top of
the platform's built-in rule packs.

## Wire shape

`OpaPolicyEngine` POSTs the JSON envelope below to:

```
${PAG_OPA_URL}/v1/data/pa_guard/tenants/<tenant_id>/findings
```

```json
{
  "input": {
    "request":  { /* full de-identified PARequest */ },
    "document": { /* full de-identified PADocument or null */ },
    "tenant_id": "acme"
  }
}
```

OPA must return either a JSON array of finding dicts or a `{ "findings": [...] }`
object. Each finding has the shape:

```json
{
  "rule_id":  "ACME-EXAMPLE-001",
  "severity": "info" | "warning" | "blocker",
  "message":  "Human-readable text"
}
```

## Privacy contract

The `input` payload is **always** the de-identified request + document; Safe
Harbor (and the Phase 1 NER overlay) have already run by the time the
ComplianceEngine fires. No PHI ever reaches an OPA policy.

## Local development

```bash
# Boot OPA pointed at this folder.
docker run -p 8181:8181 -v "$(pwd)/policies:/policies" \
    openpolicyagent/opa:latest run --server /policies

# Tell the backend to use it.
export PAG_OPA_URL=http://localhost:8181
uvicorn pa_guard.api.main:app --reload
```

When `PAG_OPA_URL` is unset (or the OPA server is unreachable), the engine
is a **no-op** — built-in rule packs always run unaffected.

## Adding a tenant

1. Copy `example.rego` to `<tenant_id>.rego`.
2. Rename the package from `pa_guard.tenants.acme` to
   `pa_guard.tenants.<tenant_id>`.
3. Reload the OPA server.

That's it — the next PA run for that tenant picks up the overlay.
