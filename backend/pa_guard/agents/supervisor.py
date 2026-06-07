"""LangGraph supervisor — wires every agent into the PA lifecycle graph.

Graph shape (Phase 1)::

    intake ──► privacy_guardian ──► policy_research ──► document_gen
       │              │                                       │
       │              │                                       ▼
       │              │                              compliance_audit
       │              │                                  │      │
       │              │                          (blocking?)   (ok)
       │              │                                  │      │
       │              ▼                                  ▼      ▼
       │       (clarification)                     human_gate  submission
       │                                                          │
       │                                                          ▼
       │                                                  outcome_logger
       │                                                          │
       │                                                          ▼
       │                                                   denial_check
       │                                                     /     \\
       │                                                  denied   approved
       │                                                    │         │
       │                                                    ▼         ▼
       │                                              denial_appeal   END
       │                                                    │
       │                                                    ▼
       │                                              outcome_logger
       │                                                    │
       └────────────────────────────────────────────────────►END

The graph uses LangGraph's `StateGraph` for explicit, deterministic routing;
human-approval gates are implemented as conditional edges that pause when
`state["needs_human_approval"]` is true.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from ..compliance.engine import ComplianceEngine
from ..core.logging import get_logger
from ..core.models import (
    AppealDocument,
    ComplianceAuditReport,
    DenialReport,
    FHEInferenceRequest,
    FHEInferenceResult,
    IntakeClarificationRequest,
    PADocument,
    PARequest,
    PARequestMeta,
    PAStatus,
    PolicyEvidence,
    RawClinicalNote,
    SubmissionChannel,
    SubmissionReceipt,
)
from ..services.fhe_inference import FHEInferenceService
from ..services.zkstark import StatementInputs, ZkStarkProver
from .compliance_auditor import AuditInput, ComplianceAuditorAgent
from .denial_appeal import AppealInput, DenialAppealAgent
from .document_generator import DocumentGenerationInput, DocumentGeneratorAgent
from .intake import IntakeAgent, IntakeInput
from .outcome_logger import OutcomeLogger
from .policy_researcher import PolicyResearcherAgent
from .privacy_guardian import IntakePayload, PrivacyGuardianAgent
from .submission import SubmissionAgent, SubmissionInput

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class PAState(TypedDict, total=False):
    raw_note: RawClinicalNote
    raw_meta: PARequestMeta
    pa_request: PARequest
    clarification: IntakeClarificationRequest | None
    evidence: list[PolicyEvidence]
    document: PADocument
    audit: ComplianceAuditReport
    receipt: SubmissionReceipt
    denial: DenialReport | None
    appeal: AppealDocument | None
    status: str           # PAStatus value
    needs_human_approval: bool
    human_approved: bool
    errors: list[str]
    risk_score: FHEInferenceResult | None     # Phase 2: FHE denial-risk score
    proof_id: str | None                       # Phase 2: zk-STARK proof for the run


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

@dataclass
class SupervisorConfig:
    """Tunable knobs the supervisor consults when routing."""

    require_human_approval_on_blocking_audit: bool = True
    preferred_submission_channel: SubmissionChannel = SubmissionChannel.API


@dataclass
class PASupervisor:
    """Holds the assembled LangGraph + every wired agent.

    Use `.build()` to get a compiled graph, then call `.run(...)` for a
    high-level convenience wrapper.
    """

    privacy_guardian: PrivacyGuardianAgent = field(default_factory=PrivacyGuardianAgent)
    intake: IntakeAgent = field(default_factory=IntakeAgent)
    policy_researcher: PolicyResearcherAgent = field(default_factory=PolicyResearcherAgent)
    document_generator: DocumentGeneratorAgent = field(default_factory=DocumentGeneratorAgent)
    auditor: ComplianceAuditorAgent = field(
        default_factory=lambda: ComplianceAuditorAgent(ComplianceEngine())
    )
    submission: SubmissionAgent = field(default_factory=SubmissionAgent)
    denial_appeal: DenialAppealAgent = field(default_factory=DenialAppealAgent)
    outcome_logger: OutcomeLogger = field(default_factory=OutcomeLogger)
    fhe: FHEInferenceService = field(default_factory=FHEInferenceService)
    prover: ZkStarkProver = field(default_factory=ZkStarkProver)
    config: SupervisorConfig = field(default_factory=SupervisorConfig)

    def __post_init__(self) -> None:
        self._log = get_logger("PASupervisor")
        # Wire every agent's self-critiques into the OutcomeLogger so the
        # MetaImproverAgent can aggregate them later.
        for agent in (
            self.privacy_guardian,
            self.intake,
            self.policy_researcher,
            self.document_generator,
            self.auditor,
            self.submission,
            self.denial_appeal,
        ):
            agent.attach_critique_sink(self.outcome_logger.log_critique)

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def build(self) -> Any:
        graph = StateGraph(PAState)

        graph.add_node("intake", self._node_intake)
        graph.add_node("privacy_guardian", self._node_privacy)
        graph.add_node("policy_research", self._node_policy_research)
        graph.add_node("document_gen", self._node_document_gen)
        graph.add_node("compliance_audit", self._node_audit)
        graph.add_node("human_gate", self._node_human_gate)
        graph.add_node("submission", self._node_submission)
        graph.add_node("denial_appeal", self._node_appeal)
        graph.add_node("outcome_log", self._node_outcome_log)

        graph.set_entry_point("intake")
        graph.add_conditional_edges("intake", self._route_after_intake)
        graph.add_edge("privacy_guardian", "policy_research")
        graph.add_edge("policy_research", "document_gen")
        graph.add_edge("document_gen", "compliance_audit")
        graph.add_conditional_edges("compliance_audit", self._route_after_audit)
        graph.add_conditional_edges("human_gate", self._route_after_human_gate)
        graph.add_edge("submission", "outcome_log")
        graph.add_conditional_edges("outcome_log", self._route_after_log)
        graph.add_edge("denial_appeal", "outcome_log")

        return graph.compile()

    # ------------------------------------------------------------------
    # Convenience wrapper
    # ------------------------------------------------------------------

    async def run(
        self,
        *,
        note: RawClinicalNote,
        meta: PARequestMeta,
    ) -> PAState:
        compiled = self.build()
        initial: PAState = {
            "raw_note": note,
            "raw_meta": meta,
            "status": PAStatus.INTAKE.value,
            "needs_human_approval": False,
            "human_approved": False,
            "errors": [],
        }
        return await compiled.ainvoke(initial)

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def _node_intake(self, state: PAState) -> PAState:
        report = await self.intake.run(
            request_id=state["raw_meta"].request_id,
            payload=IntakeInput(note=state["raw_note"], meta=state["raw_meta"]),
        )
        return {**state, "clarification": report.clarification}

    async def _node_privacy(self, state: PAState) -> PAState:
        request = await self.privacy_guardian.run(
            request_id=state["raw_meta"].request_id,
            payload=IntakePayload(note=state["raw_note"], meta=state["raw_meta"]),
        )
        return {**state, "pa_request": request, "status": PAStatus.DEIDENTIFIED.value}

    async def _node_policy_research(self, state: PAState) -> PAState:
        out = await self.policy_researcher.run(
            request_id=state["pa_request"].meta.request_id,
            payload=state["pa_request"],
        )
        return {**state, "evidence": out.evidence, "status": PAStatus.RESEARCHING.value}

    async def _node_document_gen(self, state: PAState) -> PAState:
        doc = await self.document_generator.run(
            request_id=state["pa_request"].meta.request_id,
            payload=DocumentGenerationInput(
                request=state["pa_request"],
                evidence=state["evidence"],
            ),
        )
        return {**state, "document": doc, "status": PAStatus.DOCUMENT_READY.value}

    async def _node_audit(self, state: PAState) -> PAState:
        audit = await self.auditor.run(
            request_id=state["pa_request"].meta.request_id,
            payload=AuditInput(request=state["pa_request"], document=state["document"]),
        )
        needs_gate = (
            audit.blocking and self.config.require_human_approval_on_blocking_audit
        )
        return {**state, "audit": audit, "needs_human_approval": needs_gate}

    async def _node_human_gate(self, state: PAState) -> PAState:
        # In Phase 1 the gate is a no-op pass-through; the production deployment
        # plugs in a webhook / UI approval flow here. The route function then
        # consults `state["human_approved"]`.
        return state

    async def _node_submission(self, state: PAState) -> PAState:
        # FHE risk score on de-identified pipeline features before submission.
        urgency = state["raw_meta"].urgency
        fhe_req = FHEInferenceRequest(
            circuit_name="denial_risk_v0",
            features={
                "urgency": urgency,
                "prior_denials": 0.0,
                "missing_docs_count": float(
                    sum(
                        1 for c in state["document"].criteria
                        if str(c.status).endswith("unknown")
                    )
                ),
            },
        )
        risk = await self.fhe.infer(fhe_req)
        await self.outcome_logger.log_fhe(risk)

        # zk-STARK proof binding (model_commitment, input_hash, document_hash).
        from blake3 import blake3

        input_hash = blake3(
            (
                state["pa_request"].safe_context.cleaned_text
                + "|"
                + str(state["pa_request"].meta.request_id)
            ).encode()
        ).hexdigest()
        output_hash = blake3(
            (
                str(state["document"].document_id)
                + "|"
                + state["document"].medical_necessity_narrative
            ).encode()
        ).hexdigest()
        proof = await self.prover.prove(
            StatementInputs(
                model_commitment="denial_risk_v0",
                input_hash=input_hash,
                output_hash=output_hash,
            )
        )

        receipt = await self.submission.run(
            request_id=state["pa_request"].meta.request_id,
            payload=SubmissionInput(
                document=state["document"],
                preferred_channel=self.config.preferred_submission_channel,
            ),
        )
        await self.outcome_logger.log_submission(receipt)
        return {
            **state,
            "receipt": receipt,
            "risk_score": risk,
            "proof_id": str(proof.proof_id),
            "status": PAStatus.SUBMITTED.value,
        }

    async def _node_appeal(self, state: PAState) -> PAState:
        denial = state["denial"]
        assert denial is not None, "appeal node requires a denial in state"
        appeal = await self.denial_appeal.run(
            request_id=state["document"].request_id,
            payload=AppealInput(
                denial=denial,
                document=state["document"],
                evidence=state["evidence"],
            ),
        )
        return {**state, "appeal": appeal, "status": PAStatus.APPEALED.value}

    async def _node_outcome_log(self, state: PAState) -> PAState:
        if "audit" in state:
            await self.outcome_logger.log_audit(state["audit"])
        if state.get("denial"):
            await self.outcome_logger.log_denial(state["denial"])
        return state

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------

    @staticmethod
    def _route_after_intake(state: PAState) -> Literal["privacy_guardian", "outcome_log"]:
        if state.get("clarification"):
            # Need clarification — short-circuit to outcome log and END.
            return "outcome_log"
        return "privacy_guardian"

    def _route_after_audit(self, state: PAState) -> Literal["human_gate", "submission"]:
        if state.get("needs_human_approval"):
            return "human_gate"
        return "submission"

    @staticmethod
    def _route_after_human_gate(
        state: PAState,
    ) -> Literal["submission", "outcome_log"]:
        if state.get("human_approved"):
            return "submission"
        # Without approval, log the audit and end.
        return "outcome_log"

    @staticmethod
    def _route_after_log(state: PAState) -> Literal["denial_appeal", "__end__"]:
        if state.get("denial") and state.get("appeal") is None:
            return "denial_appeal"
        return END


__all__ = ["PAState", "PASupervisor", "SupervisorConfig"]
