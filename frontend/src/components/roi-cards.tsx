"use client";

import { Clock, TrendingDown, TrendingUp, Users } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn, formatMs, formatPercent } from "@/lib/utils";
import type { OutcomeAggregate } from "@/types/api";

interface RoiCardsProps {
  aggregate?: OutcomeAggregate | null;
  className?: string;
}

export function RoiCards({ aggregate, className }: RoiCardsProps) {
  const avgLatency = aggregate
    ? mean(Object.values(aggregate.by_agent_avg_latency_ms))
    : null;
  const avgSuccess = aggregate
    ? mean(Object.values(aggregate.by_agent_success_rate))
    : null;

  const cards = [
    {
      label: "Average pipeline latency",
      value: formatMs(avgLatency),
      hint: aggregate
        ? `${Object.keys(aggregate.by_agent_avg_latency_ms).length} agents observed`
        : "—",
      icon: Clock,
      good: avgLatency !== null && avgLatency < 1000,
    },
    {
      label: "Aggregate denial rate",
      value: aggregate ? formatPercent(aggregate.denial_rate) : "—",
      hint: "lower is better",
      icon: TrendingDown,
      good: aggregate ? aggregate.denial_rate < 0.20 : true,
    },
    {
      label: "Average agent success",
      value: avgSuccess !== null ? formatPercent(avgSuccess) : "—",
      hint: aggregate ? `${aggregate.sample_count} events in window` : "—",
      icon: TrendingUp,
      good: avgSuccess !== null && avgSuccess > 0.95,
    },
    {
      label: "Samples in window",
      value: aggregate ? aggregate.sample_count.toLocaleString() : "—",
      hint: aggregate
        ? aggregate.window_seconds
          ? `${aggregate.window_seconds}s window`
          : "all-time"
        : "—",
      icon: Users,
      good: true,
    },
  ];

  return (
    <div className={cn("grid gap-4 sm:grid-cols-2 lg:grid-cols-4", className)}>
      {cards.map((c) => {
        const Icon = c.icon;
        return (
          <Card key={c.label} className="surface-blur">
            <CardContent className="p-5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {c.label}
                </span>
                <Icon
                  className={cn(
                    "size-4",
                    c.good ? "text-trust-600 dark:text-trust-300" : "text-amber-600",
                  )}
                />
              </div>
              <div className="mt-3 text-3xl font-semibold tabular-nums">
                {c.value}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">{c.hint}</div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

function mean(values: number[]): number | null {
  if (!values.length) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}
