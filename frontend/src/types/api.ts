/**
 * Mirrors the Pydantic models exposed by the FastAPI backend.
 *
 * Keep this file thin and aligned with `backend/pa_guard/core/models.py`. When
 * the backend ships a schema change, update here in the same PR.
 */

export type Severity = "info" | "warning" | "blocker";

export interface JurisdictionTag {
  jurisdiction:
    | "us-federal"
    | "us-state"
    | "ca-federal"
    | "ca-province"
    | "uk";
  state_code?: string | null;
  province_code?: string | null;
}

export interface ComplianceFinding {
  rule_id: string;
  severity: Severity;
  message: string;
}

export interface ComplianceAuditReport {
  audit_id: string;
  request_id: string;
  jurisdiction: JurisdictionTag;
  findings: ComplianceFinding[];
  blocking: boolean;
  audited_at: string;
}

export interface DeidentificationReport {
  deid_method: string;
  identifier_counts: Record<string, number>;
  content_hash: string;
  completed_at: string;
  notes: string[];
}

export interface SafeClinicalContext {
  pseudo_id: string;
  age_band: string;
  sex_at_birth?: string | null;
  zip3?: string | null;
  cleaned_text: string;
}

export interface PARequestMeta {
  request_id: string;
  created_at: string;
  jurisdiction: JurisdictionTag;
  payer_id: string;
  procedure_code: string;
  diagnosis_codes: string[];
  urgency: "routine" | "urgent" | "emergent";
}

export interface PARequest {
  meta: PARequestMeta;
  safe_context: SafeClinicalContext;
  deid_report: DeidentificationReport;
  status: string;
  sensitivity: string;
}

export interface PolicyEvidence {
  evidence_id: string;
  source: string;
  jurisdiction_tags: string[];
  payer_id?: string | null;
  excerpt: string;
  similarity: number;
  citation_url?: string | null;
}

export interface ClinicalCriterion {
  label: string;
  status: "met" | "not-met" | "unknown";
  rationale: string;
  evidence_ids: string[];
}

export interface PADocument {
  document_id: string;
  request_id: string;
  payer_id: string;
  procedure_code: string;
  diagnosis_codes: string[];
  medical_necessity_narrative: string;
  criteria: ClinicalCriterion[];
  citations: string[];
  generated_at: string;
}

export interface SubmissionReceipt {
  receipt_id: string;
  request_id: string;
  channel: string;
  payer_id: string;
  confirmation_code?: string | null;
  submitted_at: string;
  expected_response_seconds?: number | null;
}

export interface FHEInferenceResult {
  circuit_name: string;
  prediction: number | string;
  confidence?: number | null;
  latency_ms: number;
  plaintext_baseline_latency_ms?: number | null;
  fhe_executed: boolean;
  proof_id?: string | null;
}

export interface PARunResponse {
  status: string;
  pa_request: PARequest | null;
  evidence: PolicyEvidence[];
  document: PADocument | null;
  audit: ComplianceAuditReport | null;
  receipt: SubmissionReceipt | null;
  risk_score: FHEInferenceResult | null;
  proof_id: string | null;
  needs_human_approval: boolean;
  clarification_questions: string[];
}

export type SloStatus = "met" | "at-risk" | "breached";

export interface SloTargetReport {
  slo_id: string;
  description: string;
  target: number;
  actual: number;
  unit: string;
  direction: "lt" | "gt";
  status: SloStatus;
  error_budget_burn: number;
}

export interface SloSnapshot {
  window_seconds: number;
  sample_count: number;
  overall_status: SloStatus;
  reports: SloTargetReport[];
  computed_at: string;
}

export interface OutcomeAggregate {
  window_seconds: number;
  sample_count: number;
  by_agent_avg_latency_ms: Record<string, number>;
  by_agent_success_rate: Record<string, number>;
  denial_rate: number;
  appeal_success_rate: number;
  fhe_executed_share: number;
  avg_fhe_latency_ms: number | null;
  avg_voice_call_duration_seconds: number | null;
  raw_audio_left_device_share: number;
  computed_at: string;
}

export interface ImprovementProposal {
  proposal_id: string;
  category: "prompt" | "rag" | "workflow" | "script" | "rule" | "circuit";
  target: string;
  title: string;
  rationale: string;
  supporting_metrics: Record<string, number>;
  confidence: number;
  proposed_change: Record<string, string | number | string[]>;
  status: "proposed" | "approved" | "rejected" | "applied";
  created_at: string;
  approved_by?: string | null;
  approved_at?: string | null;
}

export interface ZkStarkProof {
  proof_id: string;
  model_commitment: string;
  input_hash: string;
  output_hash: string;
  proof_blob: string; // base64
  created_at: string;
}

export interface DictationResponse {
  cleaned_text: string;
  identifiers_redacted: number;
}

export interface ReadyzResponse {
  status: string;
  environment: string;
  fhe_enabled: boolean;
  fhe_circuits: string[];
  voice_on_device: boolean;
  voice_cloud: boolean;
  zkstark_enabled: boolean;
}
