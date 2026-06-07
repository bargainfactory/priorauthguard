"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { formatMs, formatPercent } from "@/lib/utils";
import type { OutcomeAggregate } from "@/types/api";

export function AgentPerfTable({
  aggregate,
}: {
  aggregate?: OutcomeAggregate | null;
}) {
  const rows = aggregate
    ? Object.keys(aggregate.by_agent_avg_latency_ms).map((agent) => ({
        agent,
        latency: aggregate.by_agent_avg_latency_ms[agent],
        success: aggregate.by_agent_success_rate[agent] ?? null,
      }))
    : [];
  rows.sort((a, b) => b.latency - a.latency);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Per-agent performance</CardTitle>
        <CardDescription>
          Average latency and success rate across the current window.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No agent activity yet. Submit a PA to populate this table.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Agent</TableHead>
                <TableHead className="text-right">Avg latency</TableHead>
                <TableHead className="text-right">Success rate</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.agent}>
                  <TableCell className="font-medium">{r.agent}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMs(r.latency)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {r.success === null ? (
                      "—"
                    ) : r.success >= 0.95 ? (
                      <Badge variant="success">{formatPercent(r.success)}</Badge>
                    ) : r.success >= 0.80 ? (
                      <Badge variant="warning">{formatPercent(r.success)}</Badge>
                    ) : (
                      <Badge variant="destructive">{formatPercent(r.success)}</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
