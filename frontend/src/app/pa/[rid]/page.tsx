"use client";

import { use, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  KeyRound,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Shell } from "@/components/layout/shell";
import { Skeleton } from "@/components/ui/skeleton";
import { getPA } from "@/lib/api";
import { formatMs } from "@/lib/utils";
import type { PARunResponse } from "@/types/api";

export default function PADetailPage({
  params,
}: {
  params: Promise<{ rid: string }>;
}) {
  const { rid } = use(params);
  const [data, setData] = useState<PARunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPA(rid)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [rid]);

  if (error) {
    return (
      <Shell title="PA Run">
        <Card>
          <CardContent className="p-6 text-sm text-destructive">{error}</CardContent>
        </Card>
      </Shell>
    );
  }
  if (!data) {
    return (
      <Shell title="PA Run">
        <Skeleton className="h-40" />
      </Shell>
    );
  }

  return (
    <Shell
      title="Prior Authorization Run"
      subtitle={`Request ${rid.slice(0, 8)}… • status: ${data.status}`}
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <SummaryCard
          icon={<ShieldCheck className="size-4 text-trust-600 dark:text-trust-300" />}
          label="De-identification"
          value={data.pa_request?.deid_report.deid_method ?? "—"}
          hint={`${Object.values(data.pa_request?.deid_report.identifier_counts ?? {})
            .reduce((a, b) => a + b, 0)} identifiers redacted`}
        />
        <SummaryCard
          icon={<KeyRound className="size-4 text-trust-600 dark:text-trust-300" />}
          label="zk-STARK proof"
          value={data.proof_id ? `${data.proof_id.slice(0, 8)}…` : "—"}
          hint="binds model + input + output"
        />
        <SummaryCard
          icon={<FileText className="size-4 text-trust-600 dark:text-trust-300" />}
          label="FHE risk score"
          value={
            data.risk_score
              ? typeof data.risk_score.prediction === "number"
                ? data.risk_score.prediction.toFixed(2)
                : String(data.risk_score.prediction)
              : "—"
          }
          hint={
            data.risk_score
              ? `${data.risk_score.fhe_executed ? "FHE" : "plaintext"} • ${formatMs(data.risk_score.latency_ms)}`
              : "—"
          }
        />
      </div>

      <Tabs defaultValue="document">
        <TabsList>
          <TabsTrigger value="document">Document</TabsTrigger>
          <TabsTrigger value="audit">
            Audit{" "}
            {data.audit?.blocking ? (
              <AlertTriangle className="ml-1 size-3.5 text-destructive" />
            ) : (
              <CheckCircle2 className="ml-1 size-3.5 text-trust-600 dark:text-trust-300" />
            )}
          </TabsTrigger>
          <TabsTrigger value="evidence">Evidence ({data.evidence.length})</TabsTrigger>
          <TabsTrigger value="raw">Raw response</TabsTrigger>
        </TabsList>

        <TabsContent value="document" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Medical-necessity narrative</CardTitle>
              <CardDescription>
                De-identified narrative the supervisor produced for the payer.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">
                {data.document?.medical_necessity_narrative ?? "—"}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Clinical criteria</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {data.document?.criteria.length ? (
                data.document.criteria.map((c, i) => (
                  <div key={i} className="rounded-md border p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{c.label}</span>
                      <Badge
                        variant={
                          c.status === "met"
                            ? "success"
                            : c.status === "not-met"
                            ? "destructive"
                            : "warning"
                        }
                      >
                        {c.status}
                      </Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {c.rationale}
                    </p>
                  </div>
                ))
              ) : (
                <p className="text-sm text-muted-foreground">
                  No criteria attached.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="audit" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Compliance audit</CardTitle>
              <CardDescription>
                {data.audit?.blocking
                  ? "Blocking findings present — submission paused until resolved."
                  : "No blocking findings."}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {data.audit?.findings.map((f) => (
                <div
                  key={f.rule_id}
                  className="flex items-start gap-3 rounded-md border p-3"
                >
                  <Badge
                    variant={
                      f.severity === "blocker"
                        ? "destructive"
                        : f.severity === "warning"
                        ? "warning"
                        : "info"
                    }
                  >
                    {f.rule_id}
                  </Badge>
                  <p className="text-sm">{f.message}</p>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="evidence" className="space-y-4">
          {data.evidence.map((e) => (
            <Card key={e.evidence_id}>
              <CardHeader>
                <CardTitle className="text-base">{e.source}</CardTitle>
                <CardDescription>
                  similarity {(e.similarity * 100).toFixed(0)}% •{" "}
                  {e.payer_id ?? "payer-agnostic"}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm">{e.excerpt}</p>
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="raw">
          <Card>
            <CardContent className="p-4">
              <pre className="overflow-auto rounded-md bg-muted/40 p-4 text-xs">
                {JSON.stringify(data, null, 2)}
              </pre>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <div>
        <Button asChild variant="outline">
          <Link href="/">← Back to dashboard</Link>
        </Button>
      </div>
    </Shell>
  );
}

function SummaryCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card className="surface-blur">
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs uppercase tracking-wide text-muted-foreground">
            {label}
          </span>
          {icon}
        </div>
        <div className="mt-1 truncate text-lg font-semibold tabular-nums">
          {value}
        </div>
        {hint ? <div className="text-xs text-muted-foreground">{hint}</div> : null}
      </CardContent>
    </Card>
  );
}
