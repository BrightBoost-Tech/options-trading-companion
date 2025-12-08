"use client";

import { useState, useEffect } from "react";
import { fetchWithAuth } from "@/lib/api";

export interface PlaidStatus {
  is_connected: boolean;
  institution_name?: string | null;
  last_sync?: string | null;
  account_count?: number | null;
}

export function usePlaidStatus() {
  const [status, setStatus] = useState<PlaidStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const checkStatus = async () => {
    try {
      setLoading(true);
      setError(null);
      // Uses our existing backend endpoint via fetchWithAuth
      const data = await fetchWithAuth<any>("/plaid/status");

      // Normalize response
      // Backend returns: { connected: boolean, institution?: string, last_sync?: string, ... }
      const normalized: PlaidStatus = {
        is_connected: data.connected ?? data.is_connected ?? false,
        institution_name: data.institution ?? data.institution_name ?? null,
        last_sync: data.last_sync ?? null,
        account_count: data.account_count ?? null,
      };
      setStatus(normalized);
    } catch (err) {
      console.error("Failed to fetch Plaid status:", err);
      setError("Failed to fetch Plaid status");
      // fall back to a safe “disconnected” shape
      setStatus({ is_connected: false, institution_name: null, last_sync: null, account_count: null });
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
