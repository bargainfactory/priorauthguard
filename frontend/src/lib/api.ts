/**
 * Typed API client for the PriorAuthGuard FastAPI backend.
 *
 * All requests go through `/api/*` which is proxied by Next.js to the
 * backend (see `next.config.mjs`). In production the proxy is replaced by
 * a same-origin deployment or an env-pinned absolute URL.
 */

import type {
  DictationResponse,
  ImprovementProposal,
  OutcomeAggregate,
  PARunResponse,
  ReadyzResponse,
  ZkStarkProof,
} from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

async function request<T>(
  path: string,
  init?: RequestInit & { signal?: AbortSignal },
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...init?.headers,
    },
    // The browser must not cache PA data — this is operational, not static.
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`API ${res.status} ${path}: ${detail}`);
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Meta
// ---------------------------------------------------------------------------

export function getReadyz(signal?: AbortSignal) {
  return request<ReadyzResponse>("/readyz", { signal });
}

// ---------------------------------------------------------------------------
// PA lifecycle
// ---------------------------------------------------------------------------

export interface RunPABody {
  note: {
    source?: "dictation" | "ehr" | "fax" | "manual";
    text: string;
    patient_first_name?: string;
    patient_last_name?: string;
    patient_dob?: string;
    patient_mrn?: string;
  };
  meta: {
    jurisdiction: {
      jurisdiction:
        | "us-federal"
        | "us-state"
        | "ca-federal"
        | "ca-province"
        | "uk";
      state_code?: string;
      province_code?: string;
    };
    payer_id: string;
    procedure_code: string;
    diagnosis_codes: string[];
    urgency: "routine" | "urgent" | "emergent";
  };
}

export function runPA(body: RunPABody, signal?: AbortSignal) {
  return request<PARunResponse>("/v1/pa", {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });
}

export function getPA(rid: string, signal?: AbortSignal) {
  return request<PARunResponse>(`/v1/pa/${rid}`, { signal });
}

// ---------------------------------------------------------------------------
// Voice
// ---------------------------------------------------------------------------

export function transcribeDictation(
  body: { text: string; speaker_role?: string },
  signal?: AbortSignal,
) {
  return request<DictationResponse>("/v1/voice/dictation", {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });
}

// ---------------------------------------------------------------------------
// Outcomes
// ---------------------------------------------------------------------------

export function getAggregate(windowSeconds = 0, signal?: AbortSignal) {
  return request<OutcomeAggregate>(
    `/v1/outcomes/aggregate?window_seconds=${windowSeconds}`,
    { signal },
  );
}

// ---------------------------------------------------------------------------
// MetaImprover
// ---------------------------------------------------------------------------

export function generateProposals(windowSeconds = 0, signal?: AbortSignal) {
  return request<ImprovementProposal[]>(
    `/v1/meta-improver/proposals?window_seconds=${windowSeconds}`,
    { method: "POST", signal },
  );
}

export function listProposals(signal?: AbortSignal) {
  return request<ImprovementProposal[]>("/v1/meta-improver/proposals", { signal });
}

export function decideProposal(
  proposalId: string,
  approve: boolean,
  approvedBy: string,
  signal?: AbortSignal,
) {
  return request<ImprovementProposal>(
    `/v1/meta-improver/proposals/${proposalId}/decide`,
    {
      method: "POST",
      body: JSON.stringify({ approve, approved_by: approvedBy }),
      signal,
    },
  );
}

// ---------------------------------------------------------------------------
// zk-STARK
// ---------------------------------------------------------------------------

export function verifyProof(proof: ZkStarkProof, signal?: AbortSignal) {
  return request<{ valid: boolean }>("/v1/zkstark/verify", {
    method: "POST",
    body: JSON.stringify(proof),
    signal,
  });
}
