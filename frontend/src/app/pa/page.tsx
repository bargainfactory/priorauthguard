"use client";

/**
 * /pa — recent PA runs for the active tenant.
 *
 * Filters: status, urgency, payer.
 * Click any row to drill into /pa/[rid].
 */

import * as React from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ChevronRight,
  RefreshCw,
  ShieldCheck,
  Stethoscope,
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { listPA, type ListPAFilters } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import { formatMs } from "@/lib/utils";
import type { PARunResponse } from "@/types/api";

const STATUS_OPTIONS = [
  "",
  "submitted",
  "approved",
  "denied",
  "appealed",
  "awaiting_payer",
  "document_ready",
];

const URGENCY_OPTIONS = ["", "routine", "urgent", "emergent"] as const;

export default function PAListPage() {
  const { tenantId } = useTenant();
  const [rows, setRows] = React.useState<PARunResponse[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [filters, setFilters] = React.useState<ListPAFilters>({ limit: 50 });

  async function refresh() {
    setLoading(true);
    try {
      const next = await listPA(filters);
      setRows(next);
    } catch (e) {
      toast.error("Failed to load PAs", { description: String(e) });
    } finally {
      setLoading(false);
    }
  }

  // Refetch whenever tenant or filters change.
  React.useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, filters.status, filters.urgency, filters.payer_id, filters.limit]);

  return (
    <Shell
      title="Prior Authorizations"
      subtitle={`Recent runs for tenant ${tenantId}. Cross-tenant rows are invisible by design.`}
    >
      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
          <CardDescription>
            All filters are server-side; <code>X-Tenant-Id</code> is injected
            automatically by the API client.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-4">
            <div className="space-y-1">
              <Label htmlFor="status">Status</Label>
              <select
                id="status"
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-sm"
                value={filters.status ?? ""}
                onChange={(e) =>
                  setFilters((f) => ({ ...f, status: e.target.value || undefined }))
                }
              >
                {STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {s || "any"}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="urgency">Urgency</Label>
              <select
                id="urgency"
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-sm"
                value={filters.urgency ?? ""}
                onChange={(e) =>
                  setFilters((f) => ({
                    ...f,
                    urgency: (e.target.value || undefined) as
                      | "routine"
                      | "urgent"
                      | "emergent"
                      | undefined,
                  }))
                }
              >
                {URGENCY_OPTIONS.map((u) => (
                  <option key={u} value={u}>
                    {u || "any"}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="payer">Payer id</Label>
              <Input
                id="payer"
                placeholder="anthem"
                value={filters.payer_id ?? ""}
                onChange={(e) =>
                  setFilters((f) => ({
                    ...f,
                    payer_id: e.target.value.trim() || undefined,
                  }))
                }
              />
            </div>
            <div className="flex items-end">
              <Button variant="outline" onClick={refresh} disabled={loading} size="sm">
                <RefreshCw className="size-4" /> Refresh
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Stethoscope className="size-4 text-trust-600 dark:text-trust-300" />
            Recent runs
          </CardTitle>
          <CardDescription>
            Showing {rows.length} of up to {filters.limit ?? 50}.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          ) : rows.length === 0 ? (
            <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
              No PAs match these filters yet.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Status</TableHead>
                  <TableHead>Payer</TableHead>
                  <TableHead>Procedure</TableHead>
                  <TableHead>Urgency</TableHead>
                  <TableHead>Risk</TableHead>
                  <TableHead>Audit</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <PARow key={r.pa_request?.meta.request_id ?? Math.random()} row={r} />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </Shell>
  );
}

function PARow({ row }: { row: PARunResponse }) {
  const rid = row.pa_request?.meta.request_id;
  const status = row.status;
  const payer = row.pa_request?.meta.payer_id ?? "—";
  const procedure = row.pa_request?.meta.procedure_code ?? "—";
  const urgency = row.pa_request?.meta.urgency ?? "—";
  const risk =
    row.risk_score && typeof row.risk_score.prediction === "number"
      ? row.risk_score.prediction.toFixed(2)
      : "—";
  const auditBlocking = row.audit?.blocking ?? false;
  const findingsCount = row.audit?.findings.length ?? 0;

  return (
    <TableRow>
      <TableCell>
        <Badge
          variant={
            status === "approved"
              ? "success"
              : status === "denied"
              ? "destructive"
              : status === "submitted"
              ? "info"
              : "warning"
          }
        >
          {status}
        </Badge>
      </TableCell>
      <TableCell className="font-mono text-xs">{payer}</TableCell>
      <TableCell className="font-mono text-xs">{procedure}</TableCell>
      <TableCell>
        <Badge variant={urgency === "routine" ? "outline" : "warning"}>{urgency}</Badge>
      </TableCell>
      <TableCell className="font-mono text-xs">
        {row.risk_score?.fhe_executed ? (
          <span title={`FHE • ${formatMs(row.risk_score.latency_ms)}`}>
            <ShieldCheck className="mr-1 inline size-3 text-trust-600 dark:text-trust-300" />
            {risk}
          </span>
        ) : (
          risk
        )}
      </TableCell>
      <TableCell>
        {auditBlocking ? (
          <Badge variant="destructive" className="gap-1">
            <AlertTriangle className="size-3" /> {findingsCount}
          </Badge>
        ) : (
          <Badge variant="info">{findingsCount}</Badge>
        )}
      </TableCell>
      <TableCell className="text-right">
        {rid ? (
          <Button asChild variant="ghost" size="sm">
            <Link href={`/pa/${rid}`}>
              Open <ChevronRight className="size-4" />
            </Link>
          </Button>
        ) : null}
      </TableCell>
    </TableRow>
  );
}
