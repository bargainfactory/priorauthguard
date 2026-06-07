# PriorAuthGuard

> Privacy-first, self-recursive **Healthcare Prior Authorization Agent Platform** for the US (50 states + DC), Canada (federal + provincial), and the UK.

PriorAuthGuard is a production-grade autonomous multi-agent system that takes a clinical intake to a payer-ready prior authorization (PA), submits it, handles denials/appeals, and learns from every outcome — while keeping protected health information (PHI) cryptographically protected end-to-end.

## Pillars

1. **Privacy by construction** — HIPAA Safe Harbor de-identification is applied *before* any model sees the data; high-sensitivity sub-tasks run under **Zama Concrete ML** Fully Homomorphic Encryption (FHE) with **Quantization-Aware Training** (QAT, Brevitas, INT8). Every key decision is accompanied by a **zk-STARK** verifiable proof.
2. **Hybrid voice** — On-device Whisper for clinical dictation (raw audio never leaves the device) + cloud stack (Deepgram + ElevenLabs + Twilio/Vapi/Bland/Retell) for outbound payer calls — every transcript is de-identified at the edge.
3. **Self-recursive** — Every agent self-critiques; the `MetaImproverAgent` proposes prompt/RAG/workflow upgrades under a human approval gate.
4. **Cross-platform** — Next.js 15 web, Tauri desktop, Capacitor/Expo mobile — one design system, dual themes.
5. **Measurable ROI** — Time-to-approval, denial-rate, hours-saved, FHE latency vs. plaintext baseline are first-class metrics.

## Phase status

| Phase | Scope | Status |
|------:|-------|--------|
| **0** | Scaffolding • core models • PrivacyGuardian (Safe Harbor) • FHEInferenceService skeleton • VoiceService + VoiceOrchestrator skeleton | ✅ in this commit |
| 1 | Full agent graph • self-critique • RAG • compliance engine • full VoiceOrchestrator | planned |
| 2 | Full QAT/Brevitas FHE • zk-STARK proofs • MetaImprover • OutcomeLogger with FHE/voice metrics | planned |
| 3 | Web frontend (light/dark) • ROI Dashboard • `PrivacyFHEPanel.tsx` | planned |
| 4 | Tauri + Capacitor + native on-device Whisper | planned |
| 5 | Integrations • advanced voice • full self-improvement loop • polish • deploy | planned |

## Repository layout

```
priorauthguard/
├── backend/                  # FastAPI + LangGraph + Pydantic v2
│   ├── pa_guard/
│   │   ├── core/             # config, models, logging
│   │   ├── agents/           # supervisor + specialized agents
│   │   ├── services/         # FHE, voice, de-identification
│   │   ├── compliance/       # Safe Harbor, jurisdiction rules
│   │   └── api/              # FastAPI app
│   └── tests/
├── frontend/                 # Next.js 15 (Phase 3)
├── docs/                     # architecture & phase notes
└── .github/workflows/        # CI
```

## Quick start (backend)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate    # or .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
uvicorn pa_guard.api.main:app --reload
```

## Privacy guarantees (Phase 0)

- ✅ HIPAA **Safe Harbor** removal of all 18 identifiers, applied **before** any downstream processing.
- ✅ Every de-identification operation logs `deid_method`, identifier counts removed, and a content hash for audit.
- 🟡 FHE inference path is wired as a **stub** (`FHEInferenceService`) following the Concrete ML compile-and-serve pattern; full QAT + Brevitas circuits land in Phase 2.
- 🟡 zk-STARK proofs are wired as a stub (`ZkStarkProver`); production prover lands in Phase 2.
- ✅ Voice path enforces de-identification on every transcript chunk before persistence.

## License

To be selected before public release (likely Apache-2.0). Until then, all rights reserved.
