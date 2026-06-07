/**
 * Typed API client for the PriorAuthGuard FastAPI backend.
 *
 * All requests go through `/api/*` which is proxied by Next.js to the
 * backend (see `next.config.mjs`). In production the proxy is replaced by
 * a same-origin deployment or an env-pinned absolute URL.
 */

import { getApiTenantId } from "@/lib/tenant";
import type {
  DictationResponse,
  ImprovementProposal,
  OutcomeAggregate,
  PARunResponse,
  ReadyzResponse,
  SloSnapshot,
  ZkStarkProof,
} from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

async function request<T>(
  path: string,
  init?: RequestInit & { signal?: AbortSignal },
): Promise<T> {
  const tenantId = getApiTenantId();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      // Scope every request to the current tenant. The backend rejects
      // requests where the header conflicts with the body's tenant_id.
      "X-Tenant-Id": tenantId,
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
    tenant_id?: string;
  };
}

export function runPA(body: RunPABody, signal?: AbortSignal) {
  // Inject the active tenant if the caller didn't set one — the backend
  // requires meta.tenant_id and X-Tenant-Id to match, so we keep them
  // aligned at the source.
  const tenantId = getApiTenantId();
  const merged: RunPABody = {
    ...body,
    meta: { ...body.meta, tenant_id: body.meta.tenant_id ?? tenantId },
  };
  return request<PARunResponse>("/v1/pa", {
    method: "POST",
    body: JSON.stringify(merged),
    signal,
  });
}

export function getPA(rid: string, signal?: AbortSignal) {
  return request<PARunResponse>(`/v1/pa/${rid}`, { signal });
}

export interface ListPAFilters {
  limit?: number;
  status?: string;
  urgency?: "routine" | "urgent" | "emergent";
  payer_id?: string;
}

export function listPA(filters: ListPAFilters = {}, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.status) params.set("status", filters.status);
  if (filters.urgency) params.set("urgency", filters.urgency);
  if (filters.payer_id) params.set("payer_id", filters.payer_id);
  const qs = params.toString();
  return request<PARunResponse[]>(`/v1/pa${qs ? `?${qs}` : ""}`, { signal });
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

export function getSloSnapshot(windowSeconds = 0, signal?: AbortSignal) {
  return request<SloSnapshot>(
    `/v1/slo/snapshot?window_seconds=${windowSeconds}`,
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
