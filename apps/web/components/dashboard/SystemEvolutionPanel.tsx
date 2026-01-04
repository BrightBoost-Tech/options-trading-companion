import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchWithAuth } from "@/lib/api";
import { Loader2, ArrowUp, ArrowDown, Shield, Brain, Activity, AlertCircle, Zap } from "lucide-react";
import { QuantumTooltip } from "@/components/ui/QuantumTooltip";
import { parseCapabilitiesResponse, formatCapabilityName, CapabilityState } from "@/lib/capability-parser";

interface LineageDiff {
  window: string;
  current: any;
  previous: any;
  diff: {
    agent_shifts: Record<string, number>;
    strategy_changes: Record<string, number>;
    constraint_prevalence_shifts: Record<string, number>;
    added_constraints: string[];
    removed_constraints: string[];
  };
}

export function SystemEvolutionPanel() {
  const [data, setData] = useState<LineageDiff | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilityState[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        const [lineageData, capData] = await Promise.all([
            fetchWithAuth("/decisions/lineage?window=7d").catch(err => {
                console.warn("Lineage data fetch failed:", err);
                return null;
            }),
            fetchWithAuth("/capabilities").catch(err => {
                console.warn("Capability fetch failed:", err);
                return null;
            })
        ]);

        if (lineageData) {
          setData(lineageData);
        }

        // Parse capabilities using the helper
        const parsedCapabilities = parseCapabilitiesResponse(capData);
        setCapabilities(parsedCapabilities);

      } catch (err) {
        console.error("Failed to load evolution data", err);
        setError("Failed to load system evolution.");
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, []);

  if (loading) {
    return (
      <Card className="h-full">
        <CardHeader>
          <CardTitle>System Evolution</CardTitle>
          <CardDescription>What changed in the last 7 days?</CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  // If we have neither lineage data nor capabilities, show error
  if (error || (!data && capabilities.length === 0)) {
       return (
        <Card className="h-full border-dashed">
            <CardHeader>
                <CardTitle>System Evolution</CardTitle>
            </CardHeader>
            <CardContent className="text-center text-muted-foreground py-8">
                {error || "No data available."}
            </CardContent>
        </Card>
       );
  }

  // Fallback defaults if lineage data is missing but capabilities loaded
  const diff = data?.diff || {
    added_constraints: [],
    removed_constraints: [],
    constraint_prevalence_shifts: {},
    agent_shifts: {}
  };

  const notEnoughHistory = data?.previous?.sample_size === 0;

  const hasChanges =
    diff.added_constraints.length > 0 ||
    diff.removed_constraints.length > 0 ||
    Object.keys(diff.constraint_prevalence_shifts).length > 0 ||
    Object.keys(diff.agent_shifts).length > 0;

  // Filter significant prevalence shifts (> 10%)
  const significantShifts = Object.entries(diff.constraint_prevalence_shifts)
    .filter(([_, delta]) => Math.abs(delta) > 10)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 3);

  // Filter active capabilities
  const activeCapabilities = capabilities.filter(c => c.is_active);

  return (
    <Card className="h-full">
      <CardHeader>
        <div className="flex items-center justify-between">
            <div>
                <CardTitle className="flex items-center gap-2">
                    System Evolution
                    <QuantumTooltip content="Tracks changes in AI behavior, active constraints, and strategy selection over the last 7 days." />
                </CardTitle>
                <CardDescription>7-Day Change Log</CardDescription>
            </div>
            {!hasChanges && !notEnoughHistory && activeCapabilities.length === 0 && <Badge variant="outline" className="bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-300">Stable</Badge>}
            {notEnoughHistory && <Badge variant="outline" className="bg-yellow-50 text-yellow-700 dark:bg-yellow-900/20 dark:text-yellow-300">Building History</Badge>}
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Active Capabilities Section */}
        {activeCapabilities.length > 0 && (
            <div className="space-y-3 pb-4 border-b border-border">
                <div className="flex items-center gap-2 text-sm font-medium text-purple-600 dark:text-purple-400">
                    <Zap className="h-4 w-4" />
                    <span>Unlocked Capabilities</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {activeCapabilities.map((cap) => (
                        <div key={cap.capability} className="flex flex-col text-xs bg-purple-50 text-purple-700 dark:bg-purple-900/20 dark:text-purple-300 px-3 py-2 rounded border border-purple-200 dark:border-purple-800">
                            <span className="font-semibold">{formatCapabilityName(cap.capability)}</span>
                            {cap.reason && <span className="text-[10px] opacity-80 mt-1">{cap.reason}</span>}
                        </div>
                    ))}
                </div>
            </div>
        )}

        {notEnoughHistory && !activeCapabilities.length ? (
            <div className="text-center py-6 text-muted-foreground">
                <AlertCircle className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p>Not enough historical data to compute diffs yet.</p>
                <p className="text-xs mt-1">Check back next week.</p>
            </div>
        ) : !hasChanges && !activeCapabilities.length ? (
            <div className="text-center py-8 text-muted-foreground">
                <p>No active constraint or strategy changes detected.</p>
            </div>
        ) : (
            <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {/* 1. New Constraints */}
            <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium text-amber-600 dark:text-amber-400">
                    <Shield className="h-4 w-4" />
                    <span>New Constraints</span>
                </div>
                {diff.added_constraints.length > 0 ? (
                <ul className="space-y-2">
                    {diff.added_constraints.map((c, i) => (
                    <li key={i} className="text-xs bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300 px-2 py-1.5 rounded border border-amber-200 dark:border-amber-800 flex items-start gap-2 break-all">
                        <span className="mt-0.5 text-[10px] uppercase font-bold tracking-wider opacity-70">ADD</span>
                        {c}
                    </li>
                    ))}
                </ul>
                ) : (
                <p className="text-xs text-muted-foreground italic pl-6">None added</p>
                )}
            </div>

            {/* 2. Removed Constraints */}
            <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium text-slate-600 dark:text-slate-400">
                    <Shield className="h-4 w-4 opacity-50" />
                    <span>Constraints Removed</span>
                </div>
                {diff.removed_constraints.length > 0 ? (
                <ul className="space-y-2">
                    {diff.removed_constraints.map((c, i) => (
                    <li key={i} className="text-xs bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400 px-2 py-1.5 rounded border border-slate-200 dark:border-slate-700 flex items-start gap-2 break-all decoration-slate-400">
                         <span className="mt-0.5 text-[10px] uppercase font-bold tracking-wider opacity-70">REM</span>
                        <span className="line-through opacity-75">{c}</span>
                    </li>
                    ))}
                </ul>
                ) : (
                <p className="text-xs text-muted-foreground italic pl-6">None removed</p>
                )}
            </div>

            {/* 3. Prevalence Shifts */}
            <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium text-blue-600 dark:text-blue-400">
                    <Activity className="h-4 w-4" />
                    <span>Prevalence Shifts</span>
                </div>
                {significantShifts.length > 0 ? (
                <div className="space-y-2">
                    {significantShifts.map(([key, delta], i) => (
                    <div key={i} className="flex items-center justify-between text-xs p-2 rounded bg-blue-50 dark:bg-blue-900/10 border border-blue-100 dark:border-blue-900/30">
                        <span className="truncate max-w-[120px]" title={key}>{key.split(':')[0]}</span>
                        <div className={`flex items-center gap-1 font-mono font-medium ${delta > 0 ? 'text-green-600' : 'text-red-500'}`}>
                             {delta > 0 ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
                             {Math.abs(delta)}%
                        </div>
                    </div>
                    ))}
                </div>
                ) : (
                <p className="text-xs text-muted-foreground italic pl-6">No major shifts</p>
                )}
            </div>
            </div>
        )}
      </CardContent>
    </Card>
  );
}
