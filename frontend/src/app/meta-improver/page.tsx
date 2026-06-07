"use client";

import { useEffect, useState } from "react";
import { Check, RefreshCw, Sparkles, X } from "lucide-react";
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
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  decideProposal,
  generateProposals,
  listProposals,
} from "@/lib/api";
import { formatPercent } from "@/lib/utils";
import type { ImprovementProposal } from "@/types/api";

export default function MetaImproverPage() {
  const [proposals, setProposals] = useState<ImprovementProposal[]>([]);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      const list = await listProposals();
      setProposals(list);
    } catch (e) {
      toast.error("Failed to load proposals", { description: String(e) });
    } finally {
      setLoading(false);
    }
  }

  async function regenerate() {
    setLoading(true);
    try {
      await generateProposals(0);
      await refresh();
      toast.success("Proposals regenerated");
    } catch (e) {
      toast.error("Failed to regenerate", { description: String(e) });
    } finally {
      setLoading(false);
    }
  }

  async function decide(id: string, approve: boolean) {
    try {
      await decideProposal(
        id,
        approve,
        "current-user@example.com", // Phase 5 wires real auth identity here.
      );
      toast.success(approve ? "Proposal approved" : "Proposal rejected");
      await refresh();
    } catch (e) {
      toast.error("Decision failed", { description: String(e) });
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <Shell
      title="Meta-Improver"
      subtitle="Self-recursive improvement proposals — human approval required before any change is applied."
    >
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          The agent reads aggregate outcomes and suggests concrete changes.
        </p>
        <Button size="sm" onClick={regenerate} disabled={loading}>
          <RefreshCw className="size-4" />
          Regenerate from current aggregate
        </Button>
      </div>

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : proposals.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 p-12 text-center">
            <Sparkles className="size-6 text-trust-600 dark:text-trust-300" />
            <p className="font-medium">No proposals</p>
            <p className="text-sm text-muted-foreground">
              The pipeline is currently healthy — there are no actionable signals
              to surface.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {proposals.map((p) => (
            <Card key={p.proposal_id}>
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-1">
                    <CardTitle className="flex items-center gap-2 text-base">
                      <Sparkles className="size-4 text-trust-600 dark:text-trust-300" />
                      {p.title}
                    </CardTitle>
                    <CardDescription>
                      Target: <code>{p.target}</code> • Category:{" "}
                      <code>{p.category}</code>
                    </CardDescription>
                  </div>
                  <Badge
                    variant={
                      p.status === "approved"
                        ? "success"
                        : p.status === "rejected"
                        ? "destructive"
                        : p.status === "applied"
                        ? "info"
                        : "warning"
                    }
                  >
                    {p.status}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm">{p.rationale}</p>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">
                    confidence {formatPercent(p.confidence)}
                  </Badge>
                  {Object.entries(p.supporting_metrics).map(([k, v]) => (
                    <Badge key={k} variant="outline">
                      {k}: {typeof v === "number" ? v.toFixed(2) : String(v)}
                    </Badge>
                  ))}
                </div>
                <Separator />
                <details className="rounded-md bg-muted/40 p-3 text-xs">
                  <summary className="cursor-pointer font-medium">
                    Proposed change
                  </summary>
                  <pre className="mt-2 overflow-auto">
                    {JSON.stringify(p.proposed_change, null, 2)}
                  </pre>
                </details>

                {p.status === "proposed" ? (
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      onClick={() => decide(p.proposal_id, true)}
                    >
                      <Check className="size-4" /> Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => decide(p.proposal_id, false)}
                    >
                      <X className="size-4" /> Reject
                    </Button>
                  </div>
                ) : p.status === "approved" ? (
                  <p className="text-xs text-muted-foreground">
                    Approved by <strong>{p.approved_by}</strong> on{" "}
                    {p.approved_at?.slice(0, 19).replace("T", " ")}.
                  </p>
                ) : null}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </Shell>
  );
}
