"use client";

import { useState } from "react";
import { CheckCircle2, KeyRound, ShieldCheck, XCircle } from "lucide-react";
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
import { verifyProof } from "@/lib/api";

export default function ZkVerifyPage() {
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ valid: boolean } | null>(null);

  async function onVerify(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      const proof = JSON.parse(input);
      const r = await verifyProof(proof);
      setResult(r);
      if (r.valid) toast.success("Proof verified");
      else toast.error("Proof invalid");
    } catch (err) {
      toast.error("Verification failed", { description: String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell
      title="zk-STARK Verify"
      subtitle="Paste a proof object emitted by the backend prover to independently verify it."
    >
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="size-4" /> Proof JSON
            </CardTitle>
            <CardDescription>
              The full <code>ZkStarkProof</code> from the backend. The{" "}
              <code>proof_blob</code> field is base64-encoded.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onVerify} className="space-y-3">
              <Textarea
                rows={14}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={JSON.stringify(
                  {
                    proof_id: "00000000-0000-0000-0000-000000000000",
                    model_commitment: "denial_risk_v0",
                    input_hash: "<blake3 hex>",
                    output_hash: "<blake3 hex>",
                    proof_blob: "<base64>",
                    created_at: "2026-01-01T00:00:00Z",
                  },
                  null,
                  2,
                )}
                className="font-mono text-xs"
              />
              <Button type="submit" disabled={busy || !input.trim()}>
                {busy ? "Verifying…" : "Verify proof"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card className="surface-blur">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-trust-600 dark:text-trust-300" />
              Verifier result
            </CardTitle>
            <CardDescription>
              Replays the Fiat-Shamir transcript and checks every Merkle
              authentication path.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {result ? (
              result.valid ? (
                <div className="flex flex-col items-center gap-3 py-6">
                  <CheckCircle2 className="size-10 text-trust-600 dark:text-trust-300" />
                  <Badge variant="success">VALID</Badge>
                  <p className="max-w-sm text-center text-sm text-muted-foreground">
                    The proof binds the model commitment, input hash, and output
                    hash correctly. Every query position matched and every
                    Merkle path verified.
                  </p>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3 py-6">
                  <XCircle className="size-10 text-destructive" />
                  <Badge variant="destructive">INVALID</Badge>
                  <p className="max-w-sm text-center text-sm text-muted-foreground">
                    The verifier rejected this proof. Common causes: tampered{" "}
                    <code>input_hash</code>, <code>output_hash</code>, or{" "}
                    <code>model_commitment</code>; corrupted{" "}
                    <code>proof_blob</code>; replayed proof from a different
                    statement.
                  </p>
                </div>
              )
            ) : (
              <p className="text-sm text-muted-foreground">
                Paste a proof on the left and click Verify.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </Shell>
  );
}
