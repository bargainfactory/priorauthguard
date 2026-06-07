# Phase 3 — Deliverables, Verification, Privacy Impact

## What ships

| Area | Path |
|---|---|
| Next.js 15 scaffolding (App Router, TS 5.6, Tailwind 3.4, ESLint 9) | [`frontend/`](../frontend/) |
| Design system — CSS variables, light + dark, emerald trust palette | [`frontend/src/app/globals.css`](../frontend/src/app/globals.css) |
| Shadcn-style primitives (Button, Card, Badge, Input, Textarea, Label, Progress, Separator, Tabs, Table, Skeleton) | [`frontend/src/components/ui/`](../frontend/src/components/ui/) |
| App shell (Sidebar + Topbar + ThemeProvider + ThemeSwitcher) | [`frontend/src/components/layout/`](../frontend/src/components/layout/) |
| **`PrivacyFHEPanel.tsx`** — the reference trust-building component | [`frontend/src/components/privacy-fhe-panel.tsx`](../frontend/src/components/privacy-fhe-panel.tsx) |
| ROI Dashboard (live `/v1/outcomes/aggregate`, per-agent table, posture panel) | [`frontend/src/app/page.tsx`](../frontend/src/app/page.tsx) |
| Intake wizard wired to `POST /v1/pa` | [`frontend/src/app/intake/page.tsx`](../frontend/src/app/intake/page.tsx) |
| PA detail view (document / audit / evidence / raw tabs) | [`frontend/src/app/pa/[rid]/page.tsx`](../frontend/src/app/pa/%5Brid%5D/page.tsx) |
| Voice dictation console | [`frontend/src/app/voice/page.tsx`](../frontend/src/app/voice/page.tsx) |
| Meta-Improver review (approve / reject proposals) | [`frontend/src/app/meta-improver/page.tsx`](../frontend/src/app/meta-improver/page.tsx) |
| Independent zk-STARK proof verifier | [`frontend/src/app/zk/page.tsx`](../frontend/src/app/zk/page.tsx) |
| Typed API client + Pydantic model mirrors | [`frontend/src/lib/api.ts`](../frontend/src/lib/api.ts), [`frontend/src/types/api.ts`](../frontend/src/types/api.ts) |

## `PrivacyFHEPanel.tsx` — the reference component

Three pillars rendered in a single backdrop-blur card with the emerald-on-neutral
trust palette:

1. **HIPAA Safe Harbor** — always live (Shield icon, "18 identifiers redacted • on-device de-id").
2. **FHE Inference** — explicit state machine:
   - `pending` while `/readyz` loads.
   - `live` when `fhe_enabled=true` AND aggregate `fhe_executed_share > 0`.
   - `fallback` when `fhe_enabled=true` but the circuit hasn't yet been
     materialized (plaintext baseline serving).
   - `off` when `fhe_enabled=false`.
3. **zk-STARK Proofs** — live when `zkstark_enabled=true`, deterministic-fallback
   otherwise. Always emits a proof per run; the verifier is wired regardless.

Live metrics strip on the bottom: FHE-executed share, on-device voice share,
denial rate — each as a value chip + progress bar. Gracefully degrades when
no aggregate is available.

## Verification checklist

### Build + run locally

```bash
# Backend
cd backend
.venv\Scripts\activate
uvicorn pa_guard.api.main:app --reload

# Frontend
cd ../frontend
pnpm install            # or npm install
pnpm dev
# open http://localhost:3000
```

### Manual flows

1. **Dashboard light/dark roundtrip**
   - Open `/`. Verify dashboard renders with skeleton, then live metrics.
   - Click the moon/sun icon in the topbar — verify both modes look polished.
   - PrivacyFHEPanel pillars show the correct state given the backend's
     `/readyz` and `/v1/outcomes/aggregate`.

2. **Intake → PA detail**
   - Click "New PA". Fill the wizard. Submit.
   - You land on `/pa/<rid>` showing tabs Document / Audit / Evidence / Raw.
   - The PA summary cards include `proof_id` and FHE risk score.

3. **Voice dictation**
   - Open `/voice`. Paste a transcript containing PHI (name, MRN). Submit.
   - The de-identified pane shows the cleaned version with a count of
     identifiers redacted.

4. **Meta-Improver**
   - Open `/meta-improver`. Click "Regenerate from current aggregate".
   - If the system is healthy, an empty-state with a Sparkles icon shows.
   - Otherwise, approve/reject proposals; verify the badge updates.

5. **zk-STARK Verify**
   - Open `/zk`. Paste a proof JSON the backend emitted (e.g. via
     `POST /v1/zkstark/verify` after `prove(...)` in a Python shell).
   - Verify the "VALID" / "INVALID" surface with the right copy.
   - Tamper with `input_hash`; verify the verifier rejects.

## Privacy / compliance impact

- ✅ No PHI is rendered by any page. The Intake wizard accepts free text, but
  the response from `/v1/pa` is already de-identified by the backend; the PA
  detail view only ever shows `safe_context.cleaned_text`.
- ✅ The Voice page treats every input as PHI-bearing and only renders the
  server's de-identified output.
- ✅ The Meta-Improver page never displays raw critique payloads — only the
  proposals derived from them (proposals carry counts and rates, never text).
- ✅ The zk-STARK verifier round-trips a serialized proof object; the
  `proof_blob` is base64 over JSON (matching the backend's serializer pair).

## Phase 3 → Phase 4 entry plan

1. **Tauri desktop** wrapper around the Next.js app for clinician workstations
   that prefer a native deployment.
2. **Capacitor / Expo mobile** companion for inbound dictation — uses native
   mic + on-device Whisper (faster-whisper / whisper.cpp) so raw audio never
   leaves the device.
3. The frontend already proxies `/api/*` via env-pinned URL — both Tauri and
   Capacitor can target the same FastAPI deployment without code changes.
