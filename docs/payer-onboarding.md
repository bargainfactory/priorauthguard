# Payer onboarding — sandbox to production

The platform supports a uniform path for every payer adapter:

1. **Configure sandbox credentials + base URL.**
2. **Run the smoke-test script** to confirm authentication + wire shape.
3. **Flip `PAG_PAYER_SANDBOX_MODE=false`** and rotate to production secrets.

## Per-payer settings

| Adapter | Settings | Notes |
|---|---|---|
| Availity | `PAG_AVAILITY_CLIENT_ID`, `PAG_AVAILITY_CLIENT_SECRET`, `PAG_AVAILITY_BASE_URL` (default `https://api.availity.com`) | Sandbox: `https://apis-sandbox.availity.com`. Onboard via [Availity Developer Portal](https://developer.availity.com/) — request the **HIPAA** scope on the OAuth2 client. |
| CoverMyMeds | `PAG_COVERMYMEDS_API_KEY`, `PAG_COVERMYMEDS_BASE_URL` (default `https://api.covermymeds.com`) | Sandbox: `https://api-stage.covermymeds.com`. The bearer key is single-tenant; rotate via the partner dashboard. |
| Surescripts | `PAG_SURESCRIPTS_CLIENT_ID`, `PAG_SURESCRIPTS_CLIENT_SECRET`, `PAG_SURESCRIPTS_BASE_URL` (default `https://api.surescripts.com`) | Sandbox: `https://uat.api.surescripts.com`. OAuth2 client-credentials; scope `prior_authorization`. |
| NHS Spine | `PAG_NHS_SPINE_API_KEY`, `PAG_NHS_SPINE_BASE_URL` (default `https://api.spine.nhs.uk`) | Sandbox: `https://api.service.nhs.uk` (NHS Digital Sandbox). Requires DSP Toolkit completion before production access. |
| Fax | `PAG_FAX_API_URL`, `PAG_FAX_API_KEY`, `PAG_FAX_FROM_NUMBER`, `PAG_FAX_TO_NUMBER` | Provider-agnostic (Phaxio / Documo). Test against the provider's test number. |

## The smoke-test script

```bash
# .env.sandbox
PAG_PAYER_SANDBOX_MODE=true
PAG_AVAILITY_CLIENT_ID=...
PAG_AVAILITY_CLIENT_SECRET=...
PAG_AVAILITY_BASE_URL=https://apis-sandbox.availity.com
PAG_COVERMYMEDS_API_KEY=...
PAG_COVERMYMEDS_BASE_URL=https://api-stage.covermymeds.com
PAG_SURESCRIPTS_CLIENT_ID=...
PAG_SURESCRIPTS_CLIENT_SECRET=...
PAG_SURESCRIPTS_BASE_URL=https://uat.api.surescripts.com
PAG_NHS_SPINE_API_KEY=...
PAG_NHS_SPINE_BASE_URL=https://api.service.nhs.uk
```

```bash
cd backend
set -a; source .env.sandbox; set +a
python -m pa_guard.scripts.payer_smoke_test
# → exits 0 if every configured adapter returned a 2xx; 1 if any failed.

# Narrow to one payer while debugging:
python -m pa_guard.scripts.payer_smoke_test --only availity
```

The script:

- Builds a **synthetic, de-identified** PA document (no PHI ever leaves the
  script).
- Constructs the adapter with the exact same settings the running server
  would use.
- Logs the success/failure of each ping, plus the sandbox flag and base URL
  for each call.

## Promoting to production

1. Rotate secrets in your secret store (Vault / AWS SM / External Secrets).
2. Remove the `PAG_*_BASE_URL` overrides — adapters fall back to the
   hard-coded production URLs.
3. Set `PAG_PAYER_SANDBOX_MODE=false` (or unset it).
4. Re-run the smoke test once more against production with a low-volume
   test PA before going live.

## Privacy notes

- Adapters log `sandbox=<bool>` and `base_url=<url>` on every call so the
  ops team can audit which environment any historical receipt came from.
- The smoke test uses synthetic `PADocument`s; no PHI is involved at any
  stage.
- The settings names (`*_BASE_URL`) are intentionally named so they cannot
  collide with any of the existing PHI-bearing fields, and the URLs
  themselves are non-secret (URLs alone are fine to log).
