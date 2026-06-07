"""Domain models (Pydantic v2).

These are the **authoritative shapes** flowing between agents and across the
API boundary. They are deliberately strict (`extra="forbid"`) so silent schema
drift cannot smuggle PHI through new fields.

Conventions
-----------
* `*Raw` models may contain PHI and MUST NEVER cross the trust boundary into a
  non-privacy-aware agent or be logged.
* `*Safe` models are the de-identified counterparts and are safe for the
  general agent graph, vector stores, and (post-FHE) inference.
* All timestamps are timezone-aware UTC.
"""
from __future__ import annotations

import base64
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
)

from .config import Jurisdiction

# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------

class _StrictModel(BaseModel):
    """All domain models forbid unknown fields to prevent PHI leakage."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        str_strip_whitespace=True,
        populate_by_name=True,
        use_enum_values=True,
    )


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PAStatus(StrEnum):
    DRAFT = "draft"
    INTAKE = "intake"
    DEIDENTIFIED = "deidentified"
    RESEARCHING = "researching"
    DOCUMENT_READY = "document_ready"
    SUBMITTED = "submitted"
    AWAITING_PAYER = "awaiting_payer"
    APPROVED = "approved"
    DENIED = "denied"
    APPEALED = "appealed"
    CLOSED = "closed"


class DeidMethod(StrEnum):
    """Which de-identification standard was applied to the source content."""

    HIPAA_SAFE_HARBOR = "hipaa-safe-harbor"
    HIPAA_EXPERT_DETERMINATION = "hipaa-expert-determination"
    NONE = "none"  # internal-only; must never be the final state on PHI


class SensitivityTier(StrEnum):
    """Drives whether a sub-task should run plaintext, FHE, or local-only."""

    PUBLIC = "public"
    INTERNAL = "internal"
    PHI_DEIDENTIFIED = "phi-deidentified"
    PHI_RAW = "phi-raw"        # may only touch on-device or FHE paths


class VoiceChannel(StrEnum):
    ON_DEVICE_WHISPER = "on-device-whisper"
    CLOUD_DEEPGRAM = "cloud-deepgram"
    CLOUD_TWILIO = "cloud-twilio"
    CLOUD_VAPI = "cloud-vapi"
    CLOUD_BLAND = "cloud-bland"
    CLOUD_RETELL = "cloud-retell"


# ---------------------------------------------------------------------------
# Identifiers / metadata
# ---------------------------------------------------------------------------

# A pseudonymous patient handle that never contains PHI.
PatientPseudoId = Annotated[
    str,
    StringConstraints(pattern=r"^pid_[0-9a-f]{16,32}$"),
]


class JurisdictionTag(_StrictModel):
    """Pinpoints the regulatory context for a given request."""

    jurisdiction: Jurisdiction
    state_code: str | None = Field(
        default=None,
        description="US two-letter state code (e.g. 'CA') when jurisdiction = us-state.",
        min_length=2,
        max_length=2,
    )
    province_code: str | None = Field(
        default=None,
        description="Canadian two-letter province code when jurisdiction = ca-province.",
        min_length=2,
        max_length=2,
    )


# ---------------------------------------------------------------------------
# Raw intake (PHI-bearing — never crosses the de-id boundary)
# ---------------------------------------------------------------------------

class RawClinicalNote(_StrictModel):
    """Free-text clinical content that MAY contain the 18 Safe Harbor identifiers.

    Should be passed straight to `PrivacyGuardianAgent` and dropped from memory
    immediately afterwards.
    """

    note_id: UUID = Field(default_factory=uuid4)
    captured_at: datetime = Field(default_factory=_utcnow)
    source: Literal["dictation", "ehr", "fax", "manual"] = "manual"
    text: str
    # Optional structured demographics that often accompany free-text intake.
    patient_first_name: str | None = None
    patient_last_name: str | None = None
    patient_dob: date | None = None
    patient_mrn: str | None = None


# ---------------------------------------------------------------------------
# De-identified payloads (safe for the general agent graph)
# ---------------------------------------------------------------------------

class DeidentificationReport(_StrictModel):
    """Auditable summary of one de-identification pass.

    NOTE: must contain **no** PHI — only counts, methods, and content hashes.
    """

    deid_method: DeidMethod
    identifier_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Map of HIPAA Safe Harbor identifier name → number of redactions.",
    )
    content_hash: str = Field(
        description="BLAKE3 hash of the de-identified payload for tamper-evidence.",
    )
    completed_at: datetime = Field(default_factory=_utcnow)
    notes: list[str] = Field(default_factory=list)


class SafeClinicalContext(_StrictModel):
    """De-identified clinical context.

    Includes only generalized demographics that survive HIPAA Safe Harbor
    (e.g., age bucket, three-digit ZIP region when population > 20k).
    """

    pseudo_id: PatientPseudoId
    age_band: Literal[
        "0-17", "18-29", "30-44", "45-64", "65-74", "75-84", "85-plus"
    ]
    sex_at_birth: Literal["F", "M", "X", "U"] | None = None
    zip3: Annotated[str, StringConstraints(pattern=r"^[0-9]{3}$")] | None = None
    cleaned_text: str = Field(
        description="The clinical narrative with all 18 identifiers removed/generalized.",
    )


# ---------------------------------------------------------------------------
# Prior Authorization request lifecycle
# ---------------------------------------------------------------------------

class PARequestMeta(_StrictModel):
    """Routing / provenance metadata for a prior authorization request."""

    request_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=_utcnow)
    jurisdiction: JurisdictionTag
    payer_id: str = Field(description="Opaque payer identifier (no PHI).")
    procedure_code: str = Field(description="CPT/HCPCS/ICD-10 procedure code.")
    diagnosis_codes: list[str] = Field(default_factory=list)
    urgency: Literal["routine", "urgent", "emergent"] = "routine"


class PARequest(_StrictModel):
    """The pipeline-friendly prior-authorization request.

    Built from `RawClinicalNote` by `PrivacyGuardianAgent` and consumed by
    every downstream agent.
    """

    meta: PARequestMeta
    safe_context: SafeClinicalContext
    deid_report: DeidentificationReport
    status: PAStatus = PAStatus.DEIDENTIFIED
    sensitivity: SensitivityTier = SensitivityTier.PHI_DEIDENTIFIED


# ---------------------------------------------------------------------------
# FHE inference contracts
# ---------------------------------------------------------------------------

class FHEInferenceRequest(_StrictModel):
    """Input handed to `FHEInferenceService`.

    The plaintext features are *already* de-identified; they are encrypted
    client-side before the server-side circuit ever sees them.
    """

    circuit_name: str = Field(
        description="Identifier for the compiled FHE circuit to invoke.",
    )
    features: dict[str, float | int | str] = Field(
        description="Plaintext, de-identified features. Encrypted by the client.",
    )
    sensitivity: SensitivityTier = SensitivityTier.PHI_DEIDENTIFIED


class FHEInferenceResult(_StrictModel):
    """Output produced by an FHE circuit.

    Latency / accuracy fields feed the OutcomeLogger so `MetaImprover` can
    decide when to swap circuits or fall back to plaintext for non-PHI inputs.
    """

    circuit_name: str
    prediction: float | int | str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    latency_ms: float = Field(ge=0)
    plaintext_baseline_latency_ms: float | None = Field(default=None, ge=0)
    fhe_executed: bool = Field(
        description="True if the circuit ran under FHE; false if a stub/plaintext fallback was used.",
    )
    proof_id: UUID | None = Field(
        default=None,
        description="zk-STARK proof identifier, if a proof was generated for this result.",
    )


# ---------------------------------------------------------------------------
# zk-STARK proof contract
# ---------------------------------------------------------------------------

class ZkStarkProof(_StrictModel):
    """Verifiable proof binding (model commitment, input hash, output)."""

    proof_id: UUID = Field(default_factory=uuid4)
    model_commitment: str = Field(
        description="Hash committing to the model weights / circuit used.",
    )
    input_hash: str = Field(description="Hash of the encrypted (or de-id) input.")
    output_hash: str = Field(description="Hash of the public output.")
    # Bytes in Python; base64 on the JSON wire. Plain `bytes` would try to
    # UTF-8 decode the proof bytes in `mode="json"` and fail; `Base64Bytes`
    # would reject raw bytes on construction. The pair of (validator,
    # serializer) below threads the needle cleanly.
    proof_blob: bytes = Field(
        description="Raw proof payload. Verifier consumes this opaquely.",
    )
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("proof_blob", mode="before")
    @classmethod
    def _decode_b64_if_str(cls, v: object) -> bytes:
        if isinstance(v, bytes):
            return v
        if isinstance(v, str):
            return base64.b64decode(v)
        raise TypeError(f"proof_blob must be bytes or base64 str, got {type(v).__name__}")

    @field_serializer("proof_blob", when_used="json")
    def _encode_b64(self, v: bytes) -> str:
        return base64.b64encode(v).decode("ascii")


# ---------------------------------------------------------------------------
# Voice contracts
# ---------------------------------------------------------------------------

class VoiceTranscriptChunk(_StrictModel):
    """A single chunk of speech-to-text output, pre-de-identification.

    MUST be routed through `PrivacyGuardianAgent` before persistence.
    """

    chunk_id: UUID = Field(default_factory=uuid4)
    channel: VoiceChannel
    speaker_role: Literal["provider", "payer-agent", "patient", "unknown"] = "unknown"
    text: str
    started_at: datetime
    ended_at: datetime
    on_device: bool = Field(
        description="True iff audio never left the user's device.",
    )


class VoiceCallOutcome(_StrictModel):
    """Summary of an outbound payer call (always de-identified)."""

    call_id: UUID = Field(default_factory=uuid4)
    channel: VoiceChannel
    payer_id: str
    outcome: Literal[
        "approved",
        "denied",
        "more-info-requested",
        "transferred",
        "voicemail",
        "failed",
    ]
    duration_seconds: float = Field(ge=0)
    summary: str = Field(
        description="De-identified summary suitable for audit and self-critique.",
    )
    proof_id: UUID | None = None


# ---------------------------------------------------------------------------
# Policy research / RAG
# ---------------------------------------------------------------------------

class PolicyEvidence(_StrictModel):
    """A single piece of payer / clinical policy evidence returned by RAG."""

    evidence_id: UUID = Field(default_factory=uuid4)
    source: str = Field(description="e.g. 'CMS NCD 220.6', 'Anthem CG-MED-67'.")
    jurisdiction_tags: list[Jurisdiction] = Field(default_factory=list)
    payer_id: str | None = None
    excerpt: str
    similarity: float = Field(ge=0.0, le=1.0)
    citation_url: str | None = None


# ---------------------------------------------------------------------------
# Document generation
# ---------------------------------------------------------------------------

class ClinicalCriterionStatus(StrEnum):
    MET = "met"
    NOT_MET = "not-met"
    UNKNOWN = "unknown"


class ClinicalCriterion(_StrictModel):
    """Structured criterion the payer expects to see addressed."""

    label: str
    status: ClinicalCriterionStatus = ClinicalCriterionStatus.UNKNOWN
    rationale: str
    evidence_ids: list[UUID] = Field(default_factory=list)


class PADocument(_StrictModel):
    """De-identified Prior Authorization submission document."""

    document_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    payer_id: str
    procedure_code: str
    diagnosis_codes: list[str]
    medical_necessity_narrative: str
    criteria: list[ClinicalCriterion] = Field(default_factory=list)
    citations: list[UUID] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Submission / payer interaction
# ---------------------------------------------------------------------------

class SubmissionChannel(StrEnum):
    API = "payer-api"
    PORTAL = "payer-portal"
    FAX = "fax"
    VOICE = "voice"


class SubmissionReceipt(_StrictModel):
    receipt_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    channel: SubmissionChannel
    payer_id: str
    confirmation_code: str | None = None
    submitted_at: datetime = Field(default_factory=_utcnow)
    expected_response_seconds: int | None = Field(default=None, ge=0)


# ---------------------------------------------------------------------------
# Denial / appeal
# ---------------------------------------------------------------------------

class DenialReport(_StrictModel):
    denial_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    reason_codes: list[str] = Field(default_factory=list)
    summary: str
    appealable: bool = True
    detected_at: datetime = Field(default_factory=_utcnow)


class AppealDocument(_StrictModel):
    appeal_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    denial_id: UUID
    counter_arguments: list[str] = Field(default_factory=list)
    additional_evidence_ids: list[UUID] = Field(default_factory=list)
    narrative: str
    generated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Compliance audit
# ---------------------------------------------------------------------------

class ComplianceFinding(_StrictModel):
    rule_id: str
    severity: Literal["info", "warning", "blocker"]
    message: str


class ComplianceAuditReport(_StrictModel):
    audit_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    jurisdiction: JurisdictionTag
    findings: list[ComplianceFinding] = Field(default_factory=list)
    blocking: bool = False
    audited_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Intake clarification
# ---------------------------------------------------------------------------

class IntakeClarificationRequest(_StrictModel):
    """Returned by IntakeAgent when the supervisor needs a human (or upstream
    system) to fill a gap before the PA can proceed."""

    request_id: UUID
    missing_fields: list[str]
    questions: list[str]


# ---------------------------------------------------------------------------
# Meta-improvement
# ---------------------------------------------------------------------------

class ImprovementCategory(StrEnum):
    PROMPT = "prompt"
    RAG = "rag"
    WORKFLOW = "workflow"
    SCRIPT = "script"
    RULE = "rule"
    CIRCUIT = "circuit"


class ImprovementProposalStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


class ImprovementProposal(_StrictModel):
    """A concrete change suggested by `MetaImproverAgent`, gated on human approval."""

    proposal_id: UUID = Field(default_factory=uuid4)
    category: ImprovementCategory
    target: str = Field(description="Agent / circuit / RAG key the change applies to.")
    title: str
    rationale: str = Field(description="Why the system thinks this would help.")
    supporting_metrics: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    proposed_change: dict[str, str | float | int | list[str]] = Field(
        default_factory=dict,
        description="The actual config / prompt / rule patch the supervisor would apply on approval.",
    )
    status: ImprovementProposalStatus = ImprovementProposalStatus.PROPOSED
    created_at: datetime = Field(default_factory=_utcnow)
    approved_by: str | None = None
    approved_at: datetime | None = None


class OutcomeAggregate(_StrictModel):
    """Roll-up statistics computed by `OutcomeLogger.aggregate()`."""

    window_seconds: int = Field(ge=0, description="0 means all-time.")
    sample_count: int
    by_agent_avg_latency_ms: dict[str, float] = Field(default_factory=dict)
    by_agent_success_rate: dict[str, float] = Field(default_factory=dict)
    denial_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    appeal_success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    fhe_executed_share: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_fhe_latency_ms: float | None = None
    avg_voice_call_duration_seconds: float | None = None
    raw_audio_left_device_share: float = Field(default=0.0, ge=0.0, le=1.0)
    computed_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Self-critique / OutcomeLogger payloads
# ---------------------------------------------------------------------------

class AgentCritique(_StrictModel):
    """Structured self-critique emitted by every agent after a task."""

    agent_name: str
    request_id: UUID
    kpi: dict[str, float] = Field(
        description="Quantitative KPIs (e.g. latency_ms, tokens_used, confidence).",
    )
    what_worked: list[str] = Field(default_factory=list)
    what_failed: list[str] = Field(default_factory=list)
    suggested_improvements: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "AgentCritique",
    "AppealDocument",
    "ClinicalCriterion",
    "ClinicalCriterionStatus",
    "ComplianceAuditReport",
    "ComplianceFinding",
    "DeidMethod",
    "DeidentificationReport",
    "DenialReport",
    "FHEInferenceRequest",
    "FHEInferenceResult",
    "ImprovementCategory",
    "ImprovementProposal",
    "ImprovementProposalStatus",
    "IntakeClarificationRequest",
    "JurisdictionTag",
    "OutcomeAggregate",
    "PADocument",
    "PARequest",
    "PARequestMeta",
    "PAStatus",
    "PatientPseudoId",
    "PolicyEvidence",
    "RawClinicalNote",
    "SafeClinicalContext",
    "SensitivityTier",
    "SubmissionChannel",
    "SubmissionReceipt",
    "VoiceCallOutcome",
    "VoiceChannel",
    "VoiceTranscriptChunk",
    "ZkStarkProof",
]
