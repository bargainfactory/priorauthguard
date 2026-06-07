"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  AudioLines,
  Building2,
  Gauge,
  KeyRound,
  ListChecks,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard", icon: Gauge },
  { href: "/pa", label: "PA runs", icon: ListChecks },
  { href: "/intake", label: "New PA", icon: Stethoscope },
  { href: "/voice", label: "Voice", icon: AudioLines },
  { href: "/slo", label: "SLOs", icon: TrendingUp },
  { href: "/meta-improver", label: "Meta-Improver", icon: Sparkles },
  { href: "/zk", label: "zk-STARK", icon: KeyRound },
  { href: "/admin", label: "Tenants", icon: Building2 },
] as const;

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="hidden h-screen w-64 shrink-0 border-r bg-card/40 backdrop-blur-md md:flex md:flex-col">
      <div className="flex items-center gap-2 px-6 py-5">
        <ShieldCheck className="size-5 text-trust-600 dark:text-trust-300" />
        <span className="font-semibold tracking-tight">PriorAuthGuard</span>
      </div>
      <nav className="flex-1 space-y-1 px-3">
        {NAV.map((item) => {
          const Icon = item.icon;
          const active =
            item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="size-4" />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
      <div className="border-t px-6 py-4 text-xs text-muted-foreground">
        Privacy-first PA platform • v0.3
      </div>
    </aside>
  );
}
