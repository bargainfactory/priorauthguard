# PriorAuthGuard — Architecture

## 1. High-level view

```mermaid
flowchart TB
    subgraph Clients["Clients (Cross-Platform)"]
        Web["Next.js 15 Web<br/>(shadcn/ui • Light + Dark)"]
        Desk["Tauri Desktop"]
        Mob["Capacitor / Expo Mobile<br/>(on-device Whisper)"]
    end

    subgraph API["FastAPI Gateway"]
        REST[REST + SSE]
        WS[WebSocket / Voice Stream]
    end

    subgraph Supervisor["LangGraph Supervisor"]
        SUP{{Supervisor + Router}}
    end

    subgraph Agents["Specialized Agents (self-critique enabled)"]
        IN[IntakeAgent]
        PG[PrivacyGuardianAgent<br/>★ early de-id ★]
        PR[PolicyResearcherAgent<br/>RAG + jurisdiction]
        DG[DocumentGeneratorAgent]
        SUB[SubmissionAgent]
        VO[VoiceOrchestratorAgent<br/>★ hybrid ★]
        DA[DenialAppealAgent]
        CA[ComplianceAuditorAgent]
        OL[OutcomeLogger]
        MI[MetaImproverAgent<br/>human-gated]
    end

    subgraph Privacy["Privacy + Crypto Layer"]
        SH[Safe Harbor<br/>18 Identifiers]
        FHE[FHEInferenceService<br/>Concrete ML 1.9+<br/>QAT + Brevitas INT8]
        ZK[zk-STARK Prover/Verifier]
        WH[On-device Whisper<br/>quantized]
    end

    subgraph Voice["Voice Stack"]
        DEEP[Deepgram STT]
        ELE[ElevenLabs TTS]
        TW[Twilio / Vapi / Bland / Retell]
    end

    subgraph Data["Data Layer"]
        PG_DB[(Postgres + pgvector)]
        AUD[(Audit Log<br/>append-only)]
        BLOB[(Encrypted Object Store)]
    end

    Web --> REST
    Desk --> REST
    Mob --> WS
    Mob -.local mic.-> WH

    REST --> SUP
    WS --> VO

    SUP --> IN --> PG
    PG --> PR --> DG --> SUB
    SUB --> VO
    VO --> DA
    DA --> CA
    CA --> OL
    OL --> MI
    MI -.proposes.-> SUP

    PG --> SH
    PG --> FHE
    FHE --> ZK
    VO --> WH
    VO --> DEEP & ELE & TW
    VO --> PG

    PR --> PG_DB
    OL --> AUD
    SUB --> BLOB
    DG --> BLOB

    classDef privacy fill:#10b981,stroke:#047857,color:#fff
    class PG,SH,FHE,ZK,WH privacy
```

## 2. Trust boundaries

| Boundary | What crosses | Enforced by |
|---|---|---|
| Client → API | De-identified payloads only (for non-voice). Voice goes over a separate WS channel. | API contract (`RawClinicalNote` is permitted only at `/v1/intake`; PrivacyGuardian runs immediately). |
| API → Agent graph | `PARequest` (de-identified). | `PrivacyGuardianAgent.run(...)` is the only producer. |
| Agent → FHEInferenceService | `FHEInferenceRequest` with `SensitivityTier != PHI_RAW`. | `FHEInferenceService._validate_sensitivity`. |
| FHE → Plaintext baseline | Plaintext baselines never see PHI; only features derived from `SafeClinicalContext`. | Convention + tests. |
| Voice → Storage | De-identified transcript chunks only. | `VoiceOrchestratorAgent` always routes through `PrivacyGuardianAgent.deidentify_transcript`. |

## 3. Sequence: clinical-note intake (Phase 0)

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as FastAPI
    participant PG as PrivacyGuardianAgent
    participant SH as SafeHarborEngine

    C->>API: POST /v1/intake {RawClinicalNote, PARequestMeta}
    API->>PG: run(IntakePayload)
    PG->>SH: deidentify_text(note.text)
    SH-->>PG: cleaned_text + identifier_counts
    PG-->>API: PARequest (SafeClinicalContext + DeidentificationReport)
    API-->>C: PARequest (NO PHI)
    note over PG: Raw note dropped from memory<br/>before response is built
```

## 4. Sequence: hybrid voice — inbound dictation (Phase 0)

```mermaid
sequenceDiagram
    autonumber
    participant App as Mobile / Desktop
    participant Whisper as On-device Whisper
    participant VS as VoiceService
    participant VO as VoiceOrchestratorAgent
    participant PG as PrivacyGuardianAgent
    participant FHE as FHEInferenceService
    participant ZK as ZkStarkProver

    App->>Whisper: audio chunks (local)
    Whisper-->>App: text chunks (local)
    App->>VS: transcribe_on_device(text-bearing audio frames)
    VS-->>VO: VoiceTranscriptChunk[]
    loop per chunk
        VO->>PG: deidentify_transcript(chunk)
        PG-->>VO: TranscriptResult (cleaned + report)
    end
    VO->>FHE: infer(denial_risk_v0)
    FHE-->>VO: FHEInferenceResult (baseline in Phase 0)
    VO->>ZK: prove(model, input_hash, output_hash)
    ZK-->>VO: ZkStarkProof
    VO-->>App: VoiceRunReport (no raw audio)
```

## 5. FHE inference pattern (Concrete ML)

Phase 2 lands the real circuits; Phase 0 ships the interface and bookkeeping.

```
QAT (Brevitas, INT8) ─► PyTorch fp32 export ─► concrete.ml.compile_torch_model
                                                       │
                                                       ▼
                              CompiledModel  ◄─── circuit optimizations
                                       │            (graph rewrite, const fold,
                                       │             operator fusion)
                                       ▼
Client.gen_keys() ─► encrypt(features) ─► server.run(ct) ─► client.decrypt(ct')
                                                                       │
                                                                       ▼
                                                       ZkStarkProver.prove(...)
```

Targets (per the 2025–2026 healthcare FHE benchmarks referenced in the spec):
- Latency: sub-second to low single-digit seconds for tabular QAT-INT8 models.
- Throughput: 64–80 tokens/sec achievable on LoRA-quantized LLMs.
- Bit-width: 6–8 bits; default 8 (`PAG_FHE_QUANT_BITS=8`).

## 6. Jurisdiction routing

| Jurisdiction | `Jurisdiction` enum | Narrowed by |
|---|---|---|
| US (federal) | `us-federal` | – |
| US (state) | `us-state` | `state_code` |
| Canada (federal) | `ca-federal` | – |
| Canada (province) | `ca-province` | `province_code` |
| United Kingdom | `uk` | – |

`PolicyResearcherAgent` (Phase 1) keys its RAG retrieval on the
`JurisdictionTag` so payer rules and consent frameworks (HIPAA / PIPEDA /
provincial / UK GDPR + DPA 2018 + NHS DSPT) are applied correctly.
