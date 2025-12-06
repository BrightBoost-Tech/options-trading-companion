import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface HoldingsTreemapProps {
  exposure: any; // { bySector: { Tech: 40, ... }, byStrategy: ... }
  loading?: boolean;
}

export default function HoldingsTreemap({ exposure, loading }: HoldingsTreemapProps) {
  if (loading) return <div className="h-48 bg-gray-100 animate-pulse rounded"></div>;
  if (!exposure?.bySector) return null;

  // Simple visual representation using flex bars for now (simulating a treemap/bar chart)
  // Sort sectors by percentage
  const sectors = Object.entries(exposure.bySector)
      .sort(([, a]: any, [, b]: any) => b - a)
      .filter(([, val]: any) => val > 0); // Hide zero exposure

  return (
    <Card className="shadow-sm border-gray-200">
        <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-500 uppercase tracking-wide">
                Sector Exposure
            </CardTitle>
        </CardHeader>
        <CardContent>
            <div className="space-y-3">
                {sectors.length === 0 ? (
                    <p className="text-sm text-gray-400 italic">No significant sector exposure.</p>
                ) : (
                    sectors.slice(0, 5).map(([sector, pct]: any) => (
                        <div key={sector}>
                            <div className="flex justify-between text-xs mb-1">
                                <span className="font-medium text-gray-700">{sector}</span>
                                <span className="text-gray-500">{pct.toFixed(1)}%</span>
                            </div>
                            <div className="w-full bg-gray-100 rounded-full h-1.5 overflow-hidden">
                                <div
                                    className="bg-indigo-500 h-1.5 rounded-full"
                                    style={{ width: `${Math.min(pct, 100)}%` }}
                                />
                            </div>
                        </div>
                    ))
                )}
            </div>

            {/* Strategy Tags (Mini Cloud) */}
            <div className="mt-4 pt-3 border-t border-gray-100 flex flex-wrap gap-2">
                {Object.entries(exposure?.byStrategy || {})
                    .filter(([, v]: any) => v > 1) // Only show > 1% strategies
                    .map(([strat, pct]: any) => (
                        <span key={strat} className="text-[10px] bg-gray-100 text-gray-600 px-2 py-1 rounded-full">
                            {strat}: {pct.toFixed(0)}%
                        </span>
                    ))
                }
            </div>
        </CardContent>
    </Card>
  );
}
