"use client";

import { useState } from "react";
import { Mic, ShieldCheck } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { transcribeDictation } from "@/lib/api";
import type { DictationResponse } from "@/types/api";

export default function VoicePage() {
  const [input, setInput] = useState(
    "Mr. John Smith MRN: AB12345678 follow-up visit. " +
      "Patient reports chronic radicular pain.",
  );
  const [result, setResult] = useState<DictationResponse | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await transcribeDictation({ text: input });
      setResult(r);
      toast.success("Transcript de-identified", {
        description: `${r.identifiers_redacted} identifier(s) redacted`,
      });
    } catch (err) {
      toast.error("Dictation failed", { description: String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell
      title="Voice Dictation"
      subtitle="On-device Whisper transcript → Safe Harbor de-identification at the boundary."
    >
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Mic className="size-4" /> Raw transcript
            </CardTitle>
            <CardDescription>
              In Phase 5 this becomes a live audio stream — for now, paste the
              on-device transcript.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <form onSubmit={onSubmit} className="space-y-3">
              <Textarea
                rows={10}
                value={input}
                onChange={(e) => setInput(e.target.value)}
              />
              <Button type="submit" disabled={busy}>
                {busy ? "De-identifying…" : "De-identify"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-trust-600 dark:text-trust-300" />
              De-identified transcript
            </CardTitle>
            <CardDescription>
              Safe for downstream agents and persistence.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {result ? (
              <>
                <div className="mb-3 flex items-center gap-2">
                  <Badge variant="success">
                    {result.identifiers_redacted} identifiers redacted
                  </Badge>
                </div>
                <Separator className="mb-3" />
                <p className="whitespace-pre-wrap text-sm leading-relaxed">
                  {result.cleaned_text}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Submit a transcript to see the redacted version here.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </Shell>
  );
}
