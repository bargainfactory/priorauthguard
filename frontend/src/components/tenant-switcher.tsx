"use client";

import * as React from "react";
import { Building2, Check, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { TENANT_ID_PATTERN, useTenant } from "@/lib/tenant";

/**
 * Compact tenant switcher for the topbar.
 *
 * Click → dropdown of known tenants + an inline "add tenant" form.
 * Selecting a tenant updates the global context, persists to localStorage,
 * and immediately scopes every subsequent API request (via the
 * `getApiTenantId()` bridge in `lib/api.ts`).
 */

export function TenantSwitcher({ className }: { className?: string }) {
  const { tenantId, setTenantId, knownTenants, registerTenant } = useTenant();
  const [open, setOpen] = React.useState(false);
  const [newId, setNewId] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  // Close on outside click.
  React.useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", onDocClick);
      return () => document.removeEventListener("mousedown", onDocClick);
    }
  }, [open]);

  function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = newId.trim();
    if (!TENANT_ID_PATTERN.test(trimmed)) {
      setError("Tenant id must be 1–64 chars of [A-Za-z0-9_.-].");
      return;
    }
    registerTenant(trimmed);
    setTenantId(trimmed);
    setNewId("");
    setError(null);
    setOpen(false);
  }

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <Button
        variant="outline"
        size="sm"
        className="gap-2"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Building2 className="size-3.5" />
        <span className="hidden sm:inline">tenant:</span>
        <code className="font-mono text-xs">{tenantId}</code>
      </Button>
      {open ? (
        <div
          role="listbox"
          className={cn(
            "absolute right-0 z-20 mt-2 w-72 rounded-lg border bg-popover p-2 shadow-lg",
            "surface-blur",
          )}
        >
          <p className="px-2 pb-2 text-xs font-medium text-muted-foreground">
            Switch tenant
          </p>
          <ul className="space-y-1">
            {knownTenants.map((t) => (
              <li key={t}>
                <button
                  type="button"
                  className={cn(
                    "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm",
                    "hover:bg-accent hover:text-accent-foreground",
                    t === tenantId && "bg-accent/60 text-accent-foreground",
                  )}
                  onClick={() => {
                    setTenantId(t);
                    setOpen(false);
                  }}
                >
                  <span className="flex items-center gap-2">
                    <Building2 className="size-3.5 text-muted-foreground" />
                    <code className="font-mono text-xs">{t}</code>
                  </span>
                  {t === tenantId ? (
                    <Check className="size-3.5 text-trust-600 dark:text-trust-300" />
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
          <form onSubmit={handleAdd} className="mt-2 space-y-1 border-t pt-2">
            <Label htmlFor="new-tenant" className="px-2 text-xs">
              Add tenant
            </Label>
            <div className="flex items-center gap-1 px-2">
              <Input
                id="new-tenant"
                placeholder="acme"
                value={newId}
                onChange={(e) => setNewId(e.target.value)}
                className="h-8"
              />
              <Button type="submit" size="icon" variant="ghost" className="h-8 w-8">
                <Plus className="size-4" />
              </Button>
            </div>
            {error ? (
              <p className="px-2 text-xs text-destructive">{error}</p>
            ) : (
              <p className="px-2 text-[11px] text-muted-foreground">
                Backend operators provision tenants; this UI keeps them visible
                across sessions.
              </p>
            )}
          </form>
          <div className="mt-2 flex items-center justify-between border-t px-2 pt-2 text-[11px] text-muted-foreground">
            <span>Header:</span>
            <Badge variant="info" className="font-mono">
              X-Tenant-Id: {tenantId}
            </Badge>
          </div>
        </div>
      ) : null}
    </div>
  );
}
