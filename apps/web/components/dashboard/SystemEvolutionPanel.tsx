import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchWithAuth } from "@/lib/api";
import { Loader2, ArrowUp, ArrowDown, Minus, Shield, Brain, TrendingUp } from "lucide-react";

interface EvolutionData {
  period_start: string;
  period_end: string;
  new_constraints: string[];
  agent_influence: Array<{
    name: string;
    change: number;
    current: number;
    previous: number;
  }>;
  strategy_shifts: Array<{
    name: string;
    change: number;
    current: number;
    previous: number;
  }>;
}

export function SystemEvolutionPanel() {
  const [data, setData] = useState<EvolutionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        const result = await fetchWithAuth("/analytics/evolution");
        if (result) {
          setData(result);
        }
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
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="text-lg">System Evolution</CardTitle>
        </CardHeader>
        <CardContent className="flex justify-center py-6">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (error || !data) {
    return null; // Hide if error or no data
  }

  const hasActivity = data.new_constraints.length > 0 || data.agent_influence.length > 0 || data.strategy_shifts.length > 0;

  if (!hasActivity) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="text-lg">System Evolution (Last 7 Days)</CardTitle>
          <CardDescription>No significant changes or new activations detected.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card className="w-full">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-primary" />
            What changed in the last 7 days?
        </CardTitle>
        <CardDescription>
          Tracking adaptive system behavior and strategy shifts.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 md:grid-cols-3">

        {/* Section 1: New Constraints */}
        <div className="space-y-3">
          <h4 className="text-sm font-medium flex items-center gap-2 text-muted-foreground">
            <Shield className="h-4 w-4" /> New Constraints
          </h4>
          {data.new_constraints.length > 0 ? (
            <ul className="space-y-2">
              {data.new_constraints.map((c, i) => (
                <li key={i} className="text-sm border-l-2 border-primary pl-2 py-0.5">
                  {c}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground italic">No new guardrails activated.</p>
          )}
        </div>

        {/* Section 2: Agent Influence */}
        <div className="space-y-3">
          <h4 className="text-sm font-medium flex items-center gap-2 text-muted-foreground">
            <Brain className="h-4 w-4" /> Agent Influence
          </h4>
          {data.agent_influence.length > 0 ? (
            <div className="space-y-2">
              {data.agent_influence.slice(0, 5).map((agent, i) => (
                <div key={i} className="flex items-center justify-between text-sm">
                  <span className="truncate max-w-[120px]" title={agent.name}>
                    {formatAgentName(agent.name)}
                  </span>
                  <div className="flex items-center gap-1">
                    <span className="text-xs text-muted-foreground">
                        {agent.current} signals
                    </span>
                    {agent.change > 0 ? (
                        <Badge variant="outline" className="text-green-500 border-green-200 bg-green-50/10 px-1 py-0 h-5">
                            <ArrowUp className="h-3 w-3 mr-0.5" />
                        </Badge>
                    ) : agent.change < 0 ? (
                        <Badge variant="outline" className="text-red-500 border-red-200 bg-red-50/10 px-1 py-0 h-5">
                            <ArrowDown className="h-3 w-3 mr-0.5" />
                        </Badge>
                    ) : (
                        <Badge variant="outline" className="text-muted-foreground px-1 py-0 h-5">
                            <Minus className="h-3 w-3" />
                        </Badge>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground italic">Stable agent configuration.</p>
          )}
        </div>

        {/* Section 3: Strategy Shifts */}
        <div className="space-y-3">
          <h4 className="text-sm font-medium flex items-center gap-2 text-muted-foreground">
            <TrendingUp className="h-4 w-4" /> Strategy Shifts
          </h4>
          {data.strategy_shifts.length > 0 ? (
            <div className="space-y-2">
              {data.strategy_shifts.slice(0, 5).map((strat, i) => (
                <div key={i} className="flex items-center justify-between text-sm">
                  <span className="truncate max-w-[120px]" title={strat.name}>
                    {formatStrategyName(strat.name)}
                  </span>
                   <div className="flex items-center gap-1">
                     <span className="text-xs text-muted-foreground">
                        {strat.current} orders
                    </span>
                    {strat.change > 0 ? (
                        <Badge variant="outline" className="text-green-500 border-green-200 bg-green-50/10 px-1 py-0 h-5">
                            <ArrowUp className="h-3 w-3 mr-0.5" />
                        </Badge>
                    ) : strat.change < 0 ? (
                        <Badge variant="outline" className="text-red-500 border-red-200 bg-red-50/10 px-1 py-0 h-5">
                            <ArrowDown className="h-3 w-3 mr-0.5" />
                        </Badge>
                    ) : (
                        <Badge variant="outline" className="text-muted-foreground px-1 py-0 h-5">
                             <Minus className="h-3 w-3" />
                        </Badge>
                    )}
                   </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground italic">No significant strategy shifts.</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function formatAgentName(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());
}

function formatStrategyName(name: string): string {
    return name.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());
}
