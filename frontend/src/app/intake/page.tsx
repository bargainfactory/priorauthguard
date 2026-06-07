"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Send, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Shell } from "@/components/layout/shell";
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
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { runPA } from "@/lib/api";

const JURISDICTIONS = [
  { value: "us-federal", label: "US (federal)" },
  { value: "us-state", label: "US (state)" },
  { value: "ca-federal", label: "Canada (federal)" },
  { value: "ca-province", label: "Canada (province)" },
  { value: "uk", label: "United Kingdom" },
];

export default function IntakePage() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);

  const [jurisdiction, setJurisdiction] = useState("us-state");
  const [stateCode, setStateCode] = useState("CA");
  const [provinceCode, setProvinceCode] = useState("ON");
  const [payerId, setPayerId] = useState("anthem");
  const [procedureCode, setProcedureCode] = useState("64483");
  const [diagnosisCodes, setDiagnosisCodes] = useState("M54.16");
  const [urgency, setUrgency] = useState<"routine" | "urgent" | "emergent">(
    "routine",
  );
  const [text, setText] = useState(
    "Patient presents with chronic lumbar radicular pain. " +
      "Failed conservative therapy of 6 weeks PT + NSAIDs. " +
      "Imaging confirms radiculopathy.",
  );

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const result = await runPA({
        note: { source: "manual", text },
        meta: {
          jurisdiction: {
            jurisdiction: jurisdiction as
              | "us-federal"
              | "us-state"
              | "ca-federal"
              | "ca-province"
              | "uk",
            state_code: jurisdiction === "us-state" ? stateCode : undefined,
            province_code:
              jurisdiction === "ca-province" ? provinceCode : undefined,
          },
          payer_id: payerId,
          procedure_code: procedureCode,
          diagnosis_codes: diagnosisCodes
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          urgency,
        },
      });
      const rid = result.pa_request?.meta.request_id;
      if (rid) {
        toast.success("PA submitted", {
          description: `Status: ${result.status}`,
        });
        router.push(`/pa/${rid}`);
      } else if (result.clarification_questions.length) {
        toast.warning("Clarification required", {
          description: result.clarification_questions[0],
        });
      }
    } catch (err) {
      toast.error("Submission failed", { description: String(err) });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Shell
      title="New Prior Authorization"
      subtitle="Free-text clinical content is de-identified at the boundary — the rest of the pipeline only sees safe content."
    >
      <form onSubmit={onSubmit} className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Clinical context</CardTitle>
            <CardDescription>
              Free-text narrative. Names, MRNs, phone numbers, and dates are
              automatically redacted by{" "}
              <Badge variant="info" className="ml-1">
                <ShieldCheck className="mr-1 size-3" /> Safe Harbor
              </Badge>
              .
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="text">Clinical narrative</Label>
              <Textarea
                id="text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={10}
              />
            </div>

            <Separator />

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="procedure">Procedure code (CPT/HCPCS)</Label>
                <Input
                  id="procedure"
                  value={procedureCode}
                  onChange={(e) => setProcedureCode(e.target.value)}
                  placeholder="64483"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="diagnoses">Diagnosis codes (comma-separated ICD-10)</Label>
                <Input
                  id="diagnoses"
                  value={diagnosisCodes}
                  onChange={(e) => setDiagnosisCodes(e.target.value)}
                  placeholder="M54.16"
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Routing</CardTitle>
              <CardDescription>
                Drives the jurisdiction-specific compliance pack and the
                payer-aware RAG filter.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="jur">Jurisdiction</Label>
                <select
                  id="jur"
                  className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-sm"
                  value={jurisdiction}
                  onChange={(e) => setJurisdiction(e.target.value)}
                >
                  {JURISDICTIONS.map((j) => (
                    <option key={j.value} value={j.value}>
                      {j.label}
                    </option>
                  ))}
                </select>
              </div>
              {jurisdiction === "us-state" ? (
                <div className="space-y-2">
                  <Label htmlFor="st">State code</Label>
                  <Input
                    id="st"
                    value={stateCode}
                    onChange={(e) => setStateCode(e.target.value.toUpperCase())}
                    maxLength={2}
                  />
                </div>
              ) : null}
              {jurisdiction === "ca-province" ? (
                <div className="space-y-2">
                  <Label htmlFor="pr">Province code</Label>
                  <Input
                    id="pr"
                    value={provinceCode}
                    onChange={(e) => setProvinceCode(e.target.value.toUpperCase())}
                    maxLength={2}
                  />
                </div>
              ) : null}
              <div className="space-y-2">
                <Label htmlFor="payer">Payer ID</Label>
                <Input
                  id="payer"
                  value={payerId}
                  onChange={(e) => setPayerId(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="urg">Urgency</Label>
                <select
                  id="urg"
                  className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-sm"
                  value={urgency}
                  onChange={(e) =>
                    setUrgency(e.target.value as "routine" | "urgent" | "emergent")
                  }
                >
                  <option value="routine">Routine</option>
                  <option value="urgent">Urgent</option>
                  <option value="emergent">Emergent</option>
                </select>
              </div>
            </CardContent>
          </Card>

          <Button type="submit" className="w-full" disabled={submitting} size="lg">
            {submitting ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Running pipeline…
              </>
            ) : (
              <>
                <Send className="size-4" />
                Run PA pipeline
              </>
            )}
          </Button>
        </div>
      </form>
    </Shell>
  );
}
