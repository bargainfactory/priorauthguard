"use client";

/**
 * PrivacyFHEPanel — the reference trust-building component.
 *
 * Surfaces the **privacy + cryptography posture** of the platform in a way
 * that is meaningful to clinicians, compliance reviewers, and engineers
 * simultaneously. Three pillars:
 *
 *   1. HIPAA Safe Harbor de-identification status.
 *   2. Zama Concrete ML FHE inference posture (QAT-INT8, plaintext baseline
 *      fallback, latency vs. baseline).
 *   3. zk-STARK proof generation status (model commitment, proof per run).
 *
 * Design notes
 * ------------
 * - Works equally well in light and dark mode via the design tokens in
 *   `globals.css` — no per-mode markup.
 * - Backdrop-blur surface + soft border to feel layered without being noisy.
 * - Shield / CheckCircle iconography signals trust without overpromising —
 *   states explicitly call out when a path is on a baseline vs. live.
 * - Real-time progress bars and metric chips populate from `OutcomeAggregate`
 *   when one is provided; without data it gracefully degrades to a status-only
 *   view.
 */

import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleEllipsis,
  Cpu,
  KeyRound,
  Lock,
  Microscope,
  Shield,
  ShieldCheck,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { cn, formatMs, formatPercent } from "@/lib/utils";
import type { OutcomeAggregate, ReadyzResponse } from "@/types/api";

interface PrivacyFHEPanelProps {
  /** Live readiness snapshot from `/readyz`. */
  ready?: ReadyzResponse | null;
  /** Aggregate metrics from `/v1/outcomes/aggregate`. */
  aggregate?: OutcomeAggregate | null;
  className?: string;
}

type Tone = "live" | "fallback" | "off" | "pending";

interface PillarStatus {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  caption: string;
  tone: Tone;
  detail?: string;
}

export function PrivacyFHEPanel({
  ready,
  aggregate,
  className,
}: PrivacyFHEPanelProps) {
  const pillars = derivePillars({ ready, aggregate });

  return (
    <Card
      className={cn(
        "relative overflow-hidden surface-blur trust-gradient",
        className,
      )}
    >
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div className="space-y-2">
          <CardTitle className="flex items-center gap-2 text-lg">
            <ShieldCheck className="size-5 text-trust-600 dark:text-trust-300" />
            Privacy & Cryptography
          </CardTitle>
          <CardDescription>
            Layered defenses — every PHI-bearing path is gated by HIPAA Safe
            Harbor, sensitive inference runs under FHE when enabled, and every
            key decision is attested by a zk-STARK proof.
          </CardDescription>
        </div>
        <PostureBadge tone={overallTone(pillars)} />
      </CardHeader>

      <CardContent className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-3">
          {pillars.map((p) => (
            <PillarTile key={p.title} pillar={p} />
          ))}
        </div>

        <Separator />

        <Metrics aggregate={aggregate} />
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Pillar resolution
// ---------------------------------------------------------------------------

function derivePillars({
  ready,
  aggregate,
}: {
  ready?: ReadyzResponse | null;
  aggregate?: OutcomeAggregate | null;
}): PillarStatus[] {
  const safeHarbor: PillarStatus = {
    icon: Shield,
    title: "HIPAA Safe Harbor",
    caption: "18 identifiers redacted • on-device de-id",
    tone: "live",
    detail: "Applied to every clinical note and voice transcript.",
  };

  const fheTone: Tone = !ready
    ? "pending"
    : ready.fhe_enabled
    ? aggregate && aggregate.fhe_executed_share > 0
      ? "live"
      : "fallback"
    : "fallback";
  const fheCaption = !ready
    ? "Awaiting readiness…"
    : ready.fhe_enabled
    ? aggregate && aggregate.fhe_executed_share > 0
      ? `Concrete ML • ${formatPercent(aggregate.fhe_executed_share)} of runs`
      : "Concrete ML enabled • plaintext baseline serving"
    : "Plaintext baseline • compile circuits to promote";

  const fhe: PillarStatus = {
    icon: Cpu,
    title: "FHE Inference",
    caption: fheCaption,
    tone: fheTone,
    detail: ready?.fhe_circuits?.length
      ? `Registered circuits: ${ready.fhe_circuits.join(", ")}`
      : undefined,
  };

  const zkTone: Tone = !ready
    ? "pending"
    : ready.zkstark_enabled
    ? "live"
    : "fallback";
  const zk: PillarStatus = {
    icon: KeyRound,
    title: "zk-STARK Proofs",
    caption: ready?.zkstark_enabled
      ? "Live prover • verifier wired"
      : "Deterministic proofs • verifier wired",
    tone: zkTone,
    detail:
      "Each submission binds (model_commitment, input_hash, output_hash) " +
      "to a Merkle + Fiat-Shamir proof.",
  };

  return [safeHarbor, fhe, zk];
}

function overallTone(pillars: PillarStatus[]): Tone {
  if (pillars.some((p) => p.tone === "off")) return "off";
  if (pillars.some((p) => p.tone === "pending")) return "pending";
  if (pillars.every((p) => p.tone === "live")) return "live";
  return "fallback";
}

// ---------------------------------------------------------------------------
// Pillar tile + posture badge
// ---------------------------------------------------------------------------

function PillarTile({ pillar }: { pillar: PillarStatus }) {
  const { icon: Icon } = pillar;
  return (
    <div
      className={cn(
        "rounded-lg border border-border/60 bg-card/60 p-4 backdrop-blur-sm",
        "transition-shadow hover:shadow-md",
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "flex size-9 shrink-0 items-center justify-center rounded-md",
            "bg-trust-100 text-trust-700 dark:bg-trust-900/70 dark:text-trust-200",
          )}
        >
          <Icon className="size-5" />
        </div>
        <div className="flex-1 space-y-1">
          <div className="flex items-center gap-2">
            <p className="font-medium leading-none">{pillar.title}</p>
            <ToneIcon tone={pillar.tone} />
          </div>
          <p className="text-xs text-muted-foreground">{pillar.caption}</p>
          {pillar.detail ? (
            <p className="pt-1 text-xs text-muted-foreground/80">
              {pillar.detail}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ToneIcon({ tone }: { tone: Tone }) {
  switch (tone) {
    case "live":
      return (
        <CheckCircle2 className="size-3.5 text-trust-600 dark:text-trust-300" />
      );
    case "fallback":
      return <AlertTriangle className="size-3.5 text-amber-600" />;
    case "off":
      return <Lock className="size-3.5 text-destructive" />;
    case "pending":
      return (
        <CircleEllipsis className="size-3.5 animate-pulse text-muted-foreground" />
      );
  }
}

function PostureBadge({ tone }: { tone: Tone }) {
  if (tone === "live")
    return <Badge variant="success">All systems verified</Badge>;
  if (tone === "fallback")
    return <Badge variant="warning">Baseline serving</Badge>;
  if (tone === "pending") return <Badge variant="info">Initializing…</Badge>;
  return <Badge variant="destructive">Crypto paths disabled</Badge>;
}

// ---------------------------------------------------------------------------
// Real-time metric strip
// ---------------------------------------------------------------------------

function Metrics({ aggregate }: { aggregate?: OutcomeAggregate | null }) {
  if (!aggregate) {
    return (
      <div className="text-xs text-muted-foreground">
        Submit a PA or run a voice session to populate live cryptography
        metrics.
      </div>
    );
  }

  const fhePct = Math.round(aggregate.fhe_executed_share * 100);
  const onDevicePct =
    Math.round((1 - aggregate.raw_audio_left_device_share) * 100);

  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <Metric
        label="FHE-executed share"
        value={formatPercent(aggregate.fhe_executed_share)}
        progress={fhePct}
        hint={`avg latency ${formatMs(aggregate.avg_fhe_latency_ms)}`}
        icon={Cpu}
      />
      <Metric
        label="On-device voice share"
        value={formatPercent(1 - aggregate.raw_audio_left_device_share)}
        progress={onDevicePct}
        hint={`${aggregate.sample_count} events in window`}
        icon={Shield}
      />
      <Metric
        label="Denial rate"
        value={formatPercent(aggregate.denial_rate)}
        progress={Math.round(aggregate.denial_rate * 100)}
        hint="lower is better"
        icon={Microscope}
        invertProgress
      />
    </div>
  );
}

function Metric({
  label,
  value,
  progress,
  hint,
  icon: Icon,
  invertProgress = false,
}: {
  label: string;
  value: string;
  progress: number;
  hint?: string;
  icon: React.ComponentType<{ className?: string }>;
  invertProgress?: boolean;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-border/60 bg-card/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">
          {label}
        </span>
        <Icon className="size-3.5 text-muted-foreground/80" />
      </div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-2xl font-semibold tabular-nums">{value}</span>
        {hint ? (
          <span className="text-[11px] text-muted-foreground">{hint}</span>
        ) : null}
      </div>
      <Progress
        value={progress}
        className={cn(invertProgress && "[&>div]:bg-amber-500")}
      />
    </div>
  );
}
