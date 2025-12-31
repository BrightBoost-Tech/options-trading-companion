import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchWithAuth } from "@/lib/api";
import { Loader2, ArrowUp, ArrowDown, Shield, Brain, Activity } from "lucide-react";

interface EvolutionMetrics {
  constraints_activated: string[];
  agents_increased_influence: string[];
  strategies_expanded: string[];
  strategies_reduced: string[];
}

export function SystemEvolutionPanel() {
  const [metrics, setMetrics] = useState<EvolutionMetrics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadMetrics() {
      try {
        const data = await fetchWithAuth("/analytics/evolution");
        if (data) {
          setMetrics(data);
        }
      } catch (err) {
        console.error("Failed to load evolution metrics", err);
      } finally {
        setLoading(false);
      }
    }

    loadMetrics();
  }, []);

  if (loading) {
    return (
      <Card>
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

  if (!metrics) return null;

  const hasChanges =
    metrics.constraints_activated.length > 0 ||
    metrics.agents_increased_influence.length > 0 ||
    metrics.strategies_expanded.length > 0 ||
    metrics.strategies_reduced.length > 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
            <div>
                <CardTitle>System Evolution</CardTitle>
                <CardDescription>What changed in the last 7 days?</CardDescription>
            </div>
            {!hasChanges && <Badge variant="outline">Stable</Badge>}
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {!hasChanges ? (
            <div className="text-center py-8 text-muted-foreground">
                <p>No major system changes detected.</p>
                <p className="text-xs mt-1">System running in stable configuration.</p>
            </div>
        ) : (
            <div className="grid gap-6 md:grid-cols-3">
            {/* 1. Constraints */}
            <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium text-amber-500">
                <Shield className="h-4 w-4" />
                <span>New Constraints</span>
                </div>
                {metrics.constraints_activated.length > 0 ? (
                <ul className="space-y-1">
                    {metrics.constraints_activated.map((c, i) => (
                    <li key={i} className="text-sm bg-amber-500/10 text-amber-600 dark:text-amber-400 px-2 py-1 rounded border border-amber-500/20">
                        {c}
                    </li>
                    ))}
                </ul>
                ) : (
                <p className="text-sm text-muted-foreground italic">No new constraints</p>
                )}
            </div>

            {/* 2. Agents */}
            <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium text-blue-500">
                <Brain className="h-4 w-4" />
                <span>Agents Influencing</span>
                </div>
                {metrics.agents_increased_influence.length > 0 ? (
                <ul className="space-y-1">
                    {metrics.agents_increased_influence.map((a, i) => (
                    <li key={i} className="text-sm bg-blue-500/10 text-blue-600 dark:text-blue-400 px-2 py-1 rounded border border-blue-500/20">
                        {a}
                    </li>
                    ))}
                </ul>
                ) : (
                <p className="text-sm text-muted-foreground italic">No agent updates</p>
                )}
            </div>

            {/* 3. Strategies */}
            <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium text-purple-500">
                <Activity className="h-4 w-4" />
                <span>Strategy Shift</span>
                </div>
                {(metrics.strategies_expanded.length > 0 || metrics.strategies_reduced.length > 0) ? (
                <div className="space-y-1">
                    {metrics.strategies_expanded.map((s, i) => (
                    <div key={`exp-${i}`} className="flex items-center gap-1 text-sm text-green-600 dark:text-green-400">
                        <ArrowUp className="h-3 w-3" />
                        <span>{s}</span>
                    </div>
                    ))}
                    {metrics.strategies_reduced.map((s, i) => (
                    <div key={`red-${i}`} className="flex items-center gap-1 text-sm text-red-600 dark:text-red-400">
                        <ArrowDown className="h-3 w-3" />
                        <span>{s}</span>
                    </div>
                    ))}
                </div>
                ) : (
                <p className="text-sm text-muted-foreground italic">Mix unchanged</p>
                )}
            </div>
            </div>
        )}
      </CardContent>
    </Card>
  );
}
