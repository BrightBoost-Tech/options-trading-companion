"use client";

import { useState, useEffect } from "react";
import { API_URL, TEST_USER_ID } from "@/lib/constants";
import { supabase } from "@/lib/supabase";

export interface StrategyMetadata {
  display_name: string;
  description: string;
  risk_profile: string; // 'conservative', 'moderate', 'aggressive', etc.
  typical_holding_period: string;
  entry_conditions?: string[];
  exit_conditions?: string[];
}

export function useStrategyRegistry() {
  const [registry, setRegistry] = useState<Record<string, StrategyMetadata>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadRegistry = async () => {
      try {
        setLoading(true);
        const { data: { session } } = await supabase.auth.getSession();
        const headers: Record<string, string> = {
          "Content-Type": "application/json",
        };
        if (session) {
          headers["Authorization"] = `Bearer ${session.access_token}`;
        } else {
          headers["X-Test-Mode-User"] = TEST_USER_ID;
        }

        const res = await fetch(`${API_URL}/strategies/metadata`, { headers });
        if (res.ok) {
          const data = await res.json();
          setRegistry(data.registry || {});
        } else {
            setError("Failed to fetch registry");
        }
      } catch (err: any) {
        setError(err.message || "Unknown error");
        console.error("Failed to load strategy metadata", err);
      } finally {
        setLoading(false);
      }
    };

    loadRegistry();
  }, []);

  const getMetadata = (key: string): StrategyMetadata | null => {
     if (!key) return null;

     // 1. Direct match
     if (registry[key]) return registry[key];

     // 2. Normalized match (lowercase, underscores)
     const norm = key.toLowerCase().replace(/[\s-]/g, "_");
     if (registry[norm]) return registry[norm];

     // 3. Partial / Fuzzy Fallback (e.g. "Iron Condor" -> "iron_condor")
     // Already handled by step 2 mostly.

     return null;
  };

  return { registry, loading, error, getMetadata };
}
