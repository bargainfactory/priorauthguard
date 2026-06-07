"use client";

import { useEffect, useState } from "react";
import { ArrowUpRight, Building2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { AgentPerfTable } from "@/components/agent-perf-table";
import { Shell } from "@/components/layout/shell";
import { PrivacyFHEPanel } from "@/components/privacy-fhe-panel";
import { RoiCards } from "@/components/roi-cards";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getAggregate, getReadyz } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import type { OutcomeAggregate, ReadyzResponse } from "@/types/api";

export default function DashboardPage() {
  const { tenantId } = useTenant();
  const [ready, setReady] = useState<ReadyzResponse | null>(null);
  const [aggregate, setAggregate] = useState<OutcomeAggregate | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [r, a] = await Promise.all([getReadyz(), getAggregate(0)]);
      setReady(r);
      setAggregate(a);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  // Re-fetch whenever the tenant changes — the aggregate is tenant-scoped.
  useEffect(() => {
    void refresh();
  }, [tenantId]);

  return (
    <Shell
      title="ROI Dashboard"
      subtitle="Pipeline health, privacy posture, and aggregate outcomes at a glance."
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <span>
            Live metrics from{" "}
            <code className="rounded bg-muted px-1.5 py-0.5">
              /v1/outcomes/aggregate
            </code>
          </span>
          <Badge variant="info" className="gap-1 font-mono">
            <Building2 className="size-3" />
            {tenantId}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
            <RefreshCw className="size-4" />
            Refresh
          </Button>
          <Button asChild size="sm">
            <Link href="/intake">
              New PA <ArrowUpRight className="size-4" />
            </Link>
          </Button>
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {loading && !aggregate ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : (
        <RoiCards aggregate={aggregate} />
      )}

      <PrivacyFHEPanel ready={ready} aggregate={aggregate} />

      <AgentPerfTable aggregate={aggregate} />
    </Shell>
  );
}
