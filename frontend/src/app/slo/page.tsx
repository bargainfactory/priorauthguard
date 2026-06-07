"use client";

/**
 * /slo — Service Level Objectives.
 *
 * Reads from `GET /v1/slo/snapshot` (which derives the snapshot from the
 * OutcomeLogger aggregate). Each SLO is rendered as a card with the
 * target, the actual value, and a horizontal budget-burn bar.
 */

import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";
import { toast } from "sonner";
import { Shell } from "@/components/layout/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { getSloSnapshot } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import { cn, formatMs, formatPercent } from "@/lib/utils";
import type { SloSnapshot, SloStatus, SloTargetReport } from "@/types/api";

export default function SloPage() {
  const { tenantId } = useTenant();
  const [snapshot, setSnapshot] = React.useState<SloSnapshot | null>(null);
  const [loading, setLoading] = React.useState(true);

  async function refresh() {
    setLoading(true);
    try {
      const next = await getSloSnapshot();
      setSnapshot(next);
    } catch (e) {
      toast.error("Failed to load SLOs", { description: String(e) });
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => {
    void refresh();
  }, [tenantId]);

  const overall = snapshot?.overall_status ?? "met";

  return (
    <Shell
      title="Service Level Objectives"
      subtitle={`Tenant ${tenantId} — snapshot computed from ${snapshot?.sample_count ?? 0} samples.`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <OverallBadge status={overall} />
        <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
          <RefreshCw className="size-4" />
          Refresh
        </Button>
      </div>

      {loading && !snapshot ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-44" />
          ))}
        </div>
      ) : !snapshot || snapshot.reports.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 p-12 text-center">
            <Gauge className="size-6 text-trust-600 dark:text-trust-300" />
            <p className="font-medium">No SLO data yet</p>
            <p className="text-sm text-muted-foreground">
              Submit a PA so the outcome aggregate fills out.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {snapshot.reports.map((r) => (
            <SloCard key={r.slo_id} report={r} />
          ))}
        </div>
      )}
    </Shell>
  );
}

function OverallBadge({ status }: { status: SloStatus }) {
  if (status === "breached") {
    return (
      <Badge variant="destructive" className="gap-2">
        <AlertTriangle className="size-3" /> Breached SLO present
      </Badge>
    );
  }
  if (status === "at-risk") {
    return (
      <Badge variant="warning" className="gap-2">
        <TriangleAlert className="size-3" /> At-risk SLOs
      </Badge>
    );
  }
  return (
    <Badge variant="success" className="gap-2">
      <CheckCircle2 className="size-3" /> All SLOs met
    </Badge>
  );
}

function SloCard({ report }: { report: SloTargetReport }) {
  const burnPct = Math.round(Math.min(1, report.error_budget_burn) * 100);
  const overBudget = report.error_budget_burn >= 1.0;
  return (
    <Card className={cn("surface-blur", overBudget && "border-destructive/50")}>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="text-base">{report.slo_id}</CardTitle>
            <CardDescription>{report.description}</CardDescription>
          </div>
          <SloStatusChip status={report.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <div className="text-xs uppercase text-muted-foreground">Target</div>
            <div className="font-mono">
              {report.direction === "lt" ? "≤ " : "≥ "}
              {formatMetric(report.target, report.unit)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted-foreground">Actual</div>
            <div className="font-mono">{formatMetric(report.actual, report.unit)}</div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>Error-budget burn</span>
            <span>{(report.error_budget_burn * 100).toFixed(0)}%</span>
          </div>
          <Progress
            value={burnPct}
            className={cn(
              overBudget && "[&>div]:bg-destructive",
              !overBudget && report.status === "at-risk" && "[&>div]:bg-amber-500",
            )}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function SloStatusChip({ status }: { status: SloStatus }) {
  if (status === "met") return <Badge variant="success">met</Badge>;
  if (status === "at-risk") return <Badge variant="warning">at risk</Badge>;
  return <Badge variant="destructive">breached</Badge>;
}

function formatMetric(value: number, unit: string): string {
  if (unit === "ratio") return formatPercent(value, 1);
  if (unit === "ms") return formatMs(value);
  return value.toString();
}
