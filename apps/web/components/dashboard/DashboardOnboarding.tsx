"use client";

import Link from "next/link";
import { ShieldCheck, LineChart } from "lucide-react";
import { usePlaidStatus } from "@/hooks/usePlaidStatus";
import SyncHoldingsButton from "@/components/SyncHoldingsButton";

interface DashboardOnboardingProps {
  hasPositions: boolean; // server-side info from snapshot
}

export default function DashboardOnboarding({ hasPositions }: DashboardOnboardingProps) {
  const { status, loading } = usePlaidStatus();

  const isConnected = !!status?.is_connected;

  // If we have positions and are connected, we don’t need this banner.
  if (!loading && isConnected && hasPositions) {
    return null;
  }

  return (
    <div className="mb-8 rounded-xl border border-neutral-800 bg-neutral-900/50 p-6 shadow-sm">
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        {/* Left side: context text */}
        <div>
          <h2 className="text-xl font-semibold text-white mb-1">
            {loading
              ? "Checking account status..."
              : !isConnected
                ? "Start your trading companion"
                : "Account connected — now sync your holdings"}
          </h2>
          <p className="text-sm text-neutral-400 max-w-lg">
            {!isConnected
              ? "To generate quantum-backed insights and manage risk, please connect your brokerage account using secure, read-only Plaid access."
              : "We need to fetch your latest positions so the optimizer and suggestions can use real holdings instead of placeholders."}
          </p>
        </div>

        {/* Right side: actions */}
        <div className="flex items-center gap-3">
          {loading ? (
            <div className="h-10 w-32 bg-neutral-800 animate-pulse rounded-lg" />
          ) : !isConnected ? (
            // STATE 1: Not connected → go to Settings
            <Link
              href="/settings"
              className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              <ShieldCheck className="w-4 h-4" />
              Connect Brokerage
            </Link>
          ) : (
            // STATE 2: Connected but no positions → emphasize Sync
            <div className="flex flex-col items-end">
              <SyncHoldingsButton className="bg-green-600 hover:bg-green-500 text-white" />
              <span className="text-xs text-neutral-500 mt-1">
                Fetches from {status?.institution_name || "your broker"} in read-only mode.
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Optional trust footer for not-connected state */}
      {!isConnected && !loading && (
        <div className="mt-4 pt-4 border-t border-neutral-800 flex flex-wrap gap-4 text-xs text-neutral-500">
          <span className="flex items-center gap-1">
            <ShieldCheck className="w-3 h-3" />
            Read-only access (no trading from this app)
          </span>
          <span className="flex items-center gap-1">
            <LineChart className="w-3 h-3" />
            Bank-level encryption via Plaid
          </span>
        </div>
      )}
    </div>
  );
}
