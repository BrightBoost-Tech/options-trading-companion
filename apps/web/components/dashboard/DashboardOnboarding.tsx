"use client";

import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface DashboardOnboardingProps {
  hasPositions: boolean;
  onSyncComplete?: () => void;
}

export default function DashboardOnboarding({
  hasPositions,
}: DashboardOnboardingProps) {
  if (hasPositions) {
    return null;
  }

  return (
    <div className="mb-8 rounded-xl border border-border bg-card/50 p-6 shadow-sm">
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-foreground mb-1">
            Start your trading companion
          </h2>
          <p className="text-sm text-muted-foreground max-w-lg">
            Positions are synced automatically from Alpaca. Check Settings to verify your broker connection.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link
            href="/settings"
            className={cn(buttonVariants({ variant: "default", className: "bg-blue-600 hover:bg-blue-500 text-white" }))}
          >
            <ShieldCheck className="w-4 h-4 mr-2" />
            Check Connection
          </Link>
        </div>
      </div>
    </div>
  );
}
