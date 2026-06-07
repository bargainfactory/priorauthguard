"use client";

/**
 * Tenant context — the single source of truth for the current X-Tenant-Id.
 *
 * Persisted to localStorage so a refresh keeps the user in the same tenant.
 * `useTenant()` returns `{ tenantId, setTenantId, knownTenants, registerTenant }`
 * and is consumed by `lib/api.ts` (header injection), the topbar
 * `TenantSwitcher`, the admin page, and every dashboard widget that
 * scopes data per tenant.
 */

import * as React from "react";

export type TenantId = string;

interface TenantContextValue {
  tenantId: TenantId;
  setTenantId: (id: TenantId) => void;
  knownTenants: TenantId[];
  registerTenant: (id: TenantId) => void;
}

const STORAGE_KEY = "pa-guard:tenant-id";
const KNOWN_KEY = "pa-guard:known-tenants";
const DEFAULT_TENANT: TenantId = "default";
const TENANT_ID_PATTERN = /^[a-zA-Z0-9_.-]{1,64}$/;

const TenantContext = React.createContext<TenantContextValue | null>(null);

export function TenantProvider({ children }: { children: React.ReactNode }) {
  const [tenantId, setTenantState] = React.useState<TenantId>(DEFAULT_TENANT);
  const [knownTenants, setKnownTenants] = React.useState<TenantId[]>([DEFAULT_TENANT]);

  // Hydrate from localStorage on mount.
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved && TENANT_ID_PATTERN.test(saved)) {
      setTenantState(saved);
    }
    const knownRaw = window.localStorage.getItem(KNOWN_KEY);
    if (knownRaw) {
      try {
        const parsed: unknown = JSON.parse(knownRaw);
        if (Array.isArray(parsed) && parsed.every((t) => typeof t === "string")) {
          setKnownTenants(Array.from(new Set([DEFAULT_TENANT, ...parsed])));
        }
      } catch {
        // ignore — fall back to default.
      }
    }
  }, []);

  const setTenantId = React.useCallback((id: TenantId) => {
    if (!TENANT_ID_PATTERN.test(id)) {
      throw new Error(
        `Tenant id must match /^[a-zA-Z0-9_.-]{1,64}$/, got ${JSON.stringify(id)}`,
      );
    }
    setTenantState(id);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, id);
    }
    setApiTenantId(id);
  }, []);

  const registerTenant = React.useCallback((id: TenantId) => {
    if (!TENANT_ID_PATTERN.test(id)) return;
    setKnownTenants((prev) => {
      if (prev.includes(id)) return prev;
      const next = [...prev, id];
      if (typeof window !== "undefined") {
        window.localStorage.setItem(KNOWN_KEY, JSON.stringify(next));
      }
      return next;
    });
  }, []);

  React.useEffect(() => {
    setApiTenantId(tenantId);
  }, [tenantId]);

  const value = React.useMemo<TenantContextValue>(
    () => ({ tenantId, setTenantId, knownTenants, registerTenant }),
    [tenantId, setTenantId, knownTenants, registerTenant],
  );

  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>;
}

export function useTenant(): TenantContextValue {
  const ctx = React.useContext(TenantContext);
  if (!ctx) {
    throw new Error("useTenant must be used inside <TenantProvider>");
  }
  return ctx;
}

// ---------------------------------------------------------------------------
// API client bridge.
//
// `lib/api.ts` consults `getApiTenantId()` on every request so call sites
// don't need to thread the tenant through every fetch.
// ---------------------------------------------------------------------------

let currentTenantId: TenantId = DEFAULT_TENANT;

export function setApiTenantId(id: TenantId) {
  currentTenantId = id;
}

export function getApiTenantId(): TenantId {
  return currentTenantId;
}

export { DEFAULT_TENANT, TENANT_ID_PATTERN };
