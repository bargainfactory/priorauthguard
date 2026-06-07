# Phase 1 — Deliverables, Verification, Privacy Impact

## What ships

| Area | Path |
|---|---|
| Domain model extensions (PolicyEvidence, PADocument, SubmissionReceipt, DenialReport, AppealDocument, ComplianceAuditReport, ClinicalCriterion) | [`backend/pa_guard/core/models.py`](../backend/pa_guard/core/models.py) |
| Jurisdiction registry — US (50 + DC + federal), Canada (federal + 13 provinces/territories), UK (4 nations) | [`backend/pa_guard/compliance/jurisdictions.py`](../backend/pa_guard/compliance/jurisdictions.py) |
| Rule packs (universal + US federal + US-state slice + Canada federal + Canada province slice + UK) | [`backend/pa_guard/compliance/rules.py`](../backend/pa_guard/compliance/rules.py) |
| ComplianceEngine | [`backend/pa_guard/compliance/engine.py`](../backend/pa_guard/compliance/engine.py) |
| Learned NER overlay (heuristic backend in Phase 1; protocol ready for spaCy/Presidio) | [`backend/pa_guard/compliance/ner_overlay.py`](../backend/pa_guard/compliance/ner_overlay.py) |
| Jurisdiction-aware RAG (HashEmbedder + InMemoryIndex + seed corpus) | [`backend/pa_guard/services/rag.py`](../backend/pa_guard/services/rag.py) |
| Real cloud voice adapters (Deepgram, ElevenLabs, Twilio) behind API-key gates | [`backend/pa_guard/services/voice_adapters.py`](../backend/pa_guard/services/voice_adapters.py) |
| IntakeAgent | [`backend/pa_guard/agents/intake.py`](../backend/pa_guard/agents/intake.py) |
| PolicyResearcherAgent | [`backend/pa_guard/agents/policy_researcher.py`](../backend/pa_guard/agents/policy_researcher.py) |
| DocumentGeneratorAgent | [`backend/pa_guard/agents/document_generator.py`](../backend/pa_guard/agents/document_generator.py) |
| ComplianceAuditorAgent | [`backend/pa_guard/agents/compliance_auditor.py`](../backend/pa_guard/agents/compliance_auditor.py) |
| SubmissionAgent (multi-channel: API/portal/fax/voice + adapter protocol) | [`backend/pa_guard/agents/submission.py`](../backend/pa_guard/agents/submission.py) |
| DenialAppealAgent | [`backend/pa_guard/agents/denial_appeal.py`](../backend/pa_guard/agents/denial_appeal.py) |
| OutcomeLogger (InMemorySink + JsonlSink) | [`backend/pa_guard/agents/outcome_logger.py`](../backend/pa_guard/agents/outcome_logger.py) |
| LangGraph supervisor + state + human approval gates | [`backend/pa_guard/agents/supervisor.py`](../backend/pa_guard/agents/supervisor.py) |
| API expansion: `/v1/pa`, `/v1/pa/{rid}`, `/v1/pa/{rid}/appeal`, `/v1/voice/dictation` | [`backend/pa_guard/api/main.py`](../backend/pa_guard/api/main.py) |
| Tests — 44 new (jurisdictions, compliance engine, RAG, NER, every Phase 1 agent, supervisor end-to-end, expanded API) | [`backend/tests/`](../backend/tests/) |

## Pipeline (LangGraph)

```
intake ──► privacy_guardian ──► policy_research ──► document_gen
   │              │                                       │
   │              │                                       ▼
   │              │                              compliance_audit
   │              │                                  │      │
   │              │                          (blocking?)   (ok)
   │              │                                  │      │
   │              ▼                                  ▼      ▼
   │       (clarification)                     human_gate  submission
   │             │                                  │         │
   │             │                            (approved?)     ▼
   │             │                                  │   outcome_logger
   │             │                                  ▼         │
   │             ▼                              outcome_logger │
   │       outcome_logger ──► END                              │
   │                                                          ▼
   │                                           denial? ─► denial_appeal
   │                                                          │
   │                                                          ▼
   │                                                    outcome_logger
   │                                                          │
   │                                                          ▼
   │                                                         END
```

## Verification checklist

### Automated tests

```bash
cd backend
.venv\Scripts\activate          # or source .venv/bin/activate
pytest -q
```

Expected: **76 tests pass**, ruff clean.

### Manual flows

1. **Full PA lifecycle via API**
   ```bash
   uvicorn pa_guard.api.main:app --reload
   curl -sX POST http://127.0.0.1:8080/v1/pa \
     -H 'content-type: application/json' \
     -d '{
       "note": {
         "source": "manual",
         "text": "Mr. John Smith MRN: AB12345678 with chronic lumbar radicular pain. Failed conservative therapy of 6 weeks PT + NSAIDs. Imaging confirms radiculopathy.",
         "patient_first_name": "John", "patient_last_name": "Smith", "patient_mrn": "AB12345678"
       },
       "meta": {
         "jurisdiction": {"jurisdiction": "us-state", "state_code": "CA"},
         "payer_id": "anthem",
         "procedure_code": "64483",
         "diagnosis_codes": ["M54.16"],
         "urgency": "routine"
       }
     }'
   ```
   Confirm: `status=submitted`, audit findings include `US-CA-001` (CA gold-card info), document narrative cites Anthem CG-MED-67 evidence, no PHI in any field.

2. **Clarification short-circuit**
   ```bash
   curl -sX POST http://127.0.0.1:8080/v1/pa \
     -H 'content-type: application/json' \
     -d '{
       "note": {"source":"manual","text":""},
       "meta": {
         "jurisdiction":{"jurisdiction":"us-federal"},
         "payer_id":"cms-medicare","procedure_code":"","diagnosis_codes":[],"urgency":"routine"
       }
     }'
   ```
   Confirm: `clarification_questions` populated; `document`, `audit`, `receipt` all null.

3. **Appeal subflow**
   ```bash
   # Run a PA, capture rid + document + evidence, then:
   curl -sX POST http://127.0.0.1:8080/v1/pa/<rid>/appeal \
     -H 'content-type: application/json' \
     -d '{
       "denial": {"request_id":"<rid>","reason_codes":["MN-1"],"summary":"Insufficient documentation","appealable":true},
       "document": <document>,
       "evidence": <evidence>
     }'
   ```
   Confirm: `counter_arguments` populated, `narrative` references the denial id.

4. **Dictation de-identification**
   ```bash
   curl -sX POST http://127.0.0.1:8080/v1/voice/dictation \
     -H 'content-type: application/json' \
     -d '{"text":"Mr. John Smith MRN: AB12345678 follow-up.","speaker_role":"provider"}'
   ```
   Confirm: response holds `cleaned_text` with name + MRN redacted and `identifiers_redacted >= 2`.

## Privacy / compliance impact

- ✅ Every agent in the new graph is downstream of `PrivacyGuardian`. No new code path touches raw PHI.
- ✅ The RAG corpus contains **no** PHI — only public payer/clinical policy excerpts.
- ✅ The ComplianceEngine surfaces info findings for HIPAA (US), PIPEDA (Canada federal), Law-25 (Quebec), and UK-GDPR + DPA 2018 + NHS DSPT (UK).
- ✅ Cloud voice adapters refuse to construct unless the corresponding API key is present in settings; default services still use the offline stubs.
- ✅ NER overlay redacts long-tail names while a clinical whitelist preserves diagnostic phrases (e.g. "Coronary Artery Disease").

## Jurisdictional matrix (selected)

| Jurisdiction | Rule pack | Privacy frameworks surfaced |
|---|---|---|
| US federal | `US_FEDERAL_RULES` (CMS-0057-F) | HIPAA |
| US-CA | + `US-CA-001` (SB 999 gold-card) | HIPAA |
| US-TX | + `US-TX-001` (HB 3459 gold-card) | HIPAA |
| US-NY | + `US-NY-001` (S.3400-A) | HIPAA |
| Canada federal | `CA_FEDERAL_RULES` (PIPEDA) | PIPEDA |
| Canada-QC | + `CA-QC-001` (Law-25) | Law-25 |
| Canada-ON | + `CA-ON-001` (PHIPA) | PHIPA |
| Canada-BC | + `CA-BC-001` (PIPA + PHIA) | PIPA-BC |
| UK | `UK_RULES` (UK-GDPR Art. 9(2)(h), NHS DSPT) | UK-GDPR, DPA 2018, NHS DSPT |

## Phase 1 → Phase 2 entry plan

1. Full QAT/Brevitas FHE circuits (replace `denial_risk_v0` plaintext baseline).
2. Real zk-STARK prover (replace the SHA3-based stub).
3. `MetaImproverAgent` — analyzes aggregated critiques in `OutcomeLogger` and proposes graph / prompt / RAG upgrades behind a human approval gate.
4. `OutcomeLogger` Postgres sink + dashboard-ready aggregate queries.
5. Per-state / per-province rule pack expansion to full coverage (currently representative slices for CA/TX/NY/QC/ON/BC).
