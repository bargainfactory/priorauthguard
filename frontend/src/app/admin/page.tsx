"use client";

/**
 * Admin → Tenants
 *
 * - Lists the tenants this browser session knows about.
 * - Lets the operator switch the active tenant, register new ones, and
 *   inspect what scoping their next API call will use.
 *
 * Backend authority: tenant provisioning happens server-side; this page is
 * a client-only convenience surface for ops users to slice the dashboard
 * by tenant without hand-editing the X-Tenant-Id header.
 */

import * as React from "react";
import { Building2, ShieldCheck, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Shell } from "@/components/layout/shell";
import { TENANT_ID_PATTERN, useTenant } from "@/lib/tenant";

export default function AdminTenantsPage() {
  const { tenantId, setTenantId, knownTenants, registerTenant } = useTenant();
  const [newId, setNewId] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  function onAdd(e: React.FormEvent) {
    e.preventDefault();
    const id = newId.trim();
    if (!TENANT_ID_PATTERN.test(id)) {
      setError("Tenant id must be 1–64 chars of [A-Za-z0-9_.-].");
      return;
    }
    registerTenant(id);
    setTenantId(id);
    setNewId("");
    setError(null);
  }

  return (
    <Shell
      title="Tenants"
      subtitle="Per-tenant isolation is enforced server-side; this page scopes the dashboard to the active tenant."
    >
      <Card className="surface-blur">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-trust-600 dark:text-trust-300" />
            Active tenant
          </CardTitle>
          <CardDescription>
            Every PA, audit, and meta-improver proposal you see below is filtered
            by this id via the <code>X-Tenant-Id</code> header.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-center gap-3">
          <Badge variant="success" className="gap-2 font-mono">
            <Building2 className="size-3" />
            {tenantId}
          </Badge>
          <Badge variant="outline" className="font-mono">
            X-Tenant-Id: {tenantId}
          </Badge>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Known tenants</CardTitle>
          <CardDescription>
            Tenants this browser has worked with. Backend provisioning is a
            separate operator concern.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {knownTenants.map((t) => (
            <div
              key={t}
              className="flex items-center justify-between rounded-md border px-3 py-2"
            >
              <span className="flex items-center gap-2 font-mono text-sm">
                <Building2 className="size-3.5 text-muted-foreground" />
                {t}
              </span>
              {t === tenantId ? (
                <Badge variant="success">active</Badge>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setTenantId(t)}
                >
                  Switch
                </Button>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="size-4" /> Register a new tenant
          </CardTitle>
          <CardDescription>
            Saves the id to <code>localStorage</code> so it appears in the
            topbar switcher next time.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onAdd} className="flex flex-col gap-3 sm:flex-row">
            <div className="flex-1 space-y-1">
              <Label htmlFor="tid">Tenant id</Label>
              <Input
                id="tid"
                placeholder="acme"
                value={newId}
                onChange={(e) => setNewId(e.target.value)}
              />
              {error ? (
                <p className="text-xs text-destructive">{error}</p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Must match <code>/^[A-Za-z0-9_.-]{"{"}1,64{"}"}$/</code>
                </p>
              )}
            </div>
            <div className="self-end">
              <Button type="submit">Register & switch</Button>
            </div>
          </form>

          <Separator className="my-6" />

          <div className="space-y-2 text-sm text-muted-foreground">
            <p>
              Provisioning a real tenant on the backend means inserting the
              id into your OPA policy bundle path
              (<code>pa_guard/tenants/&lt;id&gt;/findings</code>) and rotating
              the relevant payer + LLM secrets through External Secrets.
            </p>
            <p>
              Cross-tenant reads from this UI return <code>404</code> from the
              backend by design — tenants cannot enumerate each other.
            </p>
          </div>
        </CardContent>
      </Card>
    </Shell>
  );
}
