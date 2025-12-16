"use client";

import { useState, useEffect } from "react";
import { fetchWithAuthTimeout } from "@/lib/api";

export interface PlaidStatus {
  is_connected: boolean;
  institution_name?: string | null;
  last_sync?: string | null;
  account_count?: number | null;
}

// Module-level cache to persist across re-renders
let cachedStatus: PlaidStatus | null = null;
let cachedStatusTimestamp = 0;
const CACHE_TTL = 30000; // 30 seconds

export function usePlaidStatus() {
  const [status, setStatus] = useState<PlaidStatus | null>(cachedStatus);
  const [loading, setLoading] = useState(!cachedStatus);
  const [error, setError] = useState<string | null>(null);

  const checkStatus = async () => {
    // Check cache validity first
    const now = Date.now();
    if (cachedStatus && (now - cachedStatusTimestamp < CACHE_TTL)) {
      setStatus(cachedStatus);
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      // Use timeout wrapper to prevent long blocking (4s cap)
      const data = await fetchWithAuthTimeout<any>("/plaid/status", 4000);

      const normalized: PlaidStatus = {
        is_connected: data.connected ?? data.is_connected ?? false,
        institution_name: data.institution ?? data.institution_name ?? null,
        last_sync: data.last_sync ?? null,
        account_count: data.account_count ?? null,
      };

      // Update cache
      cachedStatus = normalized;
      cachedStatusTimestamp = Date.now();

      setStatus(normalized);
    } catch (err) {
      console.error("Failed to fetch Plaid status (timeout or error):", err);
      setError("Failed to fetch Plaid status");
      // Fallback to disconnected state on error/timeout so UI doesn't hang
      const fallback: PlaidStatus = {
        is_connected: false,
        institution_name: null,
        last_sync: null,
        account_count: null
      };
      setStatus(fallback);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void checkStatus();
  }, []);

  return {
    status,
    loading,
    error,
    refreshStatus: checkStatus,
  };
}
