import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Brain, ShieldCheck, AlertTriangle, Zap } from 'lucide-react';
import { fetchWithAuth } from '@/lib/api';

interface OptimizerInsightCardProps {
  traceId?: string; // Optional: specific run to explain
}

export default function OptimizerInsightCard({ traceId }: OptimizerInsightCardProps) {
  const [insight, setInsight] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadInsight();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [traceId]);

  const loadInsight = async () => {
    setLoading(true);
    try {
       // Assuming POST /optimizer/explain expects JSON body
       const res = await fetchWithAuth('/optimizer/explain', {
           method: 'POST',
           body: JSON.stringify({ run_id: traceId || 'latest' })
       });
       setInsight(res);
    } catch (e) {
       console.error("Optimizer Insight Error:", e);
    } finally {
       setLoading(false);
    }
  };

  if (loading && !insight) return <div className="h-48 bg-gray-100 animate-pulse rounded"></div>;
  if (!insight) return null;

  // Derive status color
  const statusColor = insight.status === 'OPTIMAL' ? 'text-green-600' :
                      insight.status === 'CONSTRAINED' ? 'text-yellow-600' : 'text-red-600';

  const StatusIcon = insight.status === 'OPTIMAL' ? ShieldCheck : AlertTriangle;

  return (
    <Card className="shadow-sm border-gray-200">
        <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-500 uppercase tracking-wide flex items-center justify-between">
                <span className="flex items-center gap-2"><Brain className="w-4 h-4" /> Optimizer AI</span>
                <span className={`text-xs font-bold flex items-center gap-1 ${statusColor}`}>
                    <StatusIcon className="w-3 h-3" /> {insight.status}
                </span>
            </CardTitle>
        </CardHeader>
        <CardContent>
            <div className="space-y-3">
                {/* Metrics Grid */}
                <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="bg-gray-50 p-2 rounded">
                        <p className="text-gray-400">Regime</p>
                        <p className="font-semibold text-gray-800 capitalize">{insight.regime_detected || 'Unknown'}</p>
                    </div>
                    <div className="bg-gray-50 p-2 rounded">
                        <p className="text-gray-400">Conviction Used</p>
                        <p className="font-semibold text-gray-800 flex items-center gap-1">
                             <Zap className="w-3 h-3 text-yellow-500" fill="currentColor" />
                             {(insight.conviction_used * 100).toFixed(0)}%
                        </p>
                    </div>
                </div>

                {/* Narrative / Constraints */}
                <div>
                    <p className="text-[10px] text-gray-400 uppercase tracking-wide mb-1">Active Constraints</p>
                    {insight.active_constraints && insight.active_constraints.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                            {insight.active_constraints.map((c: string, idx: number) => (
                                <span key={idx} className="text-[10px] bg-yellow-50 text-yellow-800 border border-yellow-100 px-2 py-1 rounded">
                                    {c}
                                </span>
                            ))}
                        </div>
                    ) : (
                        <p className="text-xs text-gray-500 italic">No active constraints limiting the solution.</p>
                    )}
                </div>

                {insight.trace_id && (
                    <div className="pt-2 border-t border-gray-50">
                        <p className="text-[10px] text-gray-300 font-mono truncate">ID: {insight.trace_id}</p>
                    </div>
                )}
            </div>
        </CardContent>
    </Card>
  );
}
