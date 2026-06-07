"use client";

import * as React from "react";
import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { TenantSwitcher } from "@/components/tenant-switcher";
import { ThemeSwitcher } from "@/components/theme-switcher";
import { getReadyz } from "@/lib/api";
import type { ReadyzResponse } from "@/types/api";

export function Topbar({ title, subtitle }: { title: string; subtitle?: string }) {
  const [ready, setReady] = useState<ReadyzResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getReadyz()
      .then((r) => !cancelled && setReady(r))
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <header className="sticky top-0 z-10 flex h-16 items-center justify-between gap-3 border-b bg-background/80 px-6 backdrop-blur">
      <div className="space-y-0.5">
        <h1 className="text-base font-semibold tracking-tight">{title}</h1>
        {subtitle ? (
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        ) : null}
      </div>
      <div className="flex items-center gap-3">
        {error ? (
          <Badge variant="destructive" className="gap-1">
            <CircleAlert className="size-3" /> Backend unreachable
          </Badge>
        ) : ready ? (
          <Badge variant="success" className="gap-1">
            <CheckCircle2 className="size-3" />
            {ready.environment}
          </Badge>
        ) : (
          <Badge variant="info">Loading…</Badge>
        )}
        <TenantSwitcher />
        <ThemeSwitcher />
      </div>
    </header>
  );
}
