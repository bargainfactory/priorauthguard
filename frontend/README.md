# PriorAuthGuard — Web (Phase 3)

Next.js 15 (App Router • TypeScript • Tailwind • shadcn-style primitives)
with a light + dark design system tuned for healthcare-grade trust.

## What's here

| Path | Purpose |
|---|---|
| [`src/app/page.tsx`](src/app/page.tsx) | ROI Dashboard — live aggregates + [`PrivacyFHEPanel`](src/components/privacy-fhe-panel.tsx) + per-agent perf table |
| [`src/app/intake/page.tsx`](src/app/intake/page.tsx) | Intake wizard wired to `POST /v1/pa` |
| [`src/app/pa/[rid]/page.tsx`](src/app/pa/%5Brid%5D/page.tsx) | PA run detail (document, audit, evidence, raw response) |
| [`src/app/voice/page.tsx`](src/app/voice/page.tsx) | Voice dictation → Safe Harbor de-id at the edge |
| [`src/app/meta-improver/page.tsx`](src/app/meta-improver/page.tsx) | Human-gated review of `MetaImproverAgent` proposals |
| [`src/app/zk/page.tsx`](src/app/zk/page.tsx) | Independent zk-STARK proof verifier |
| [`src/components/privacy-fhe-panel.tsx`](src/components/privacy-fhe-panel.tsx) | The reference trust-building component (Shield / CheckCircle iconography, FHE / zk-STARK / Safe-Harbor pillars, real-time metrics) |
| [`src/lib/api.ts`](src/lib/api.ts) | Typed fetch client mirroring the FastAPI surface |
| [`src/types/api.ts`](src/types/api.ts) | Pydantic model mirrors (keep aligned with `backend/pa_guard/core/models.py`) |

## Run it

```bash
cd frontend
pnpm install        # or npm install / yarn
pnpm dev            # http://localhost:3000

# In another shell:
cd ../backend
uvicorn pa_guard.api.main:app --reload
```

The Next dev server proxies `/api/*` to the FastAPI backend (configurable via
`NEXT_PUBLIC_BACKEND_URL`; defaults to `http://127.0.0.1:8080`).

## Design notes

- **One design system, dual themes.** All colors are CSS variables in
  `src/app/globals.css`; `dark` swaps the variable set, not the markup.
- **Trust palette.** Emerald (`trust-*`) accents on a neutral canvas — calm
  enough for clinical contexts, distinctive enough to read as a healthcare
  brand.
- **Trust-building visual cues.** Shield + CheckCircle iconography on every
  privacy / crypto surface; explicit "live" vs "fallback" vs "off" state on
  every pillar so we never overpromise (e.g. when FHE is enabled but no run
  has yet executed under it, the panel shows "Concrete ML enabled • plaintext
  baseline serving").
- **Accessibility.** Radix primitives for focus / aria, semantic landmarks,
  `tabular-nums` on every metric, `prefers-reduced-motion` honored via
  Tailwind utilities.

## Stack

- Next.js 15.0 (App Router, React 19 RC)
- TypeScript 5.6
- Tailwind CSS 3.4 + `tailwindcss-animate`
- Radix primitives (Slot, Label, Tabs, Progress, Separator)
- `next-themes` for the light/dark switch
- `lucide-react` for iconography
- `sonner` for toast notifications
