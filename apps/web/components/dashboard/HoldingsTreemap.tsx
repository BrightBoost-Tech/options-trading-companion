import React, { useMemo, memo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface HoldingsTreemapProps {
  exposure: any; // { bySector: { Tech: 40, ... }, byStrategy: ... }
  loading?: boolean;
}

function HoldingsTreemap({ exposure, loading }: HoldingsTreemapProps) {
  // Memoize sectors calculation
  const sectors = useMemo(() => {
    if (loading || !exposure?.bySector) return [];

    return Object.entries(exposure.bySector)
      .sort(([, a]: any, [, b]: any) => b - a)
      .filter(([, val]: any) => val > 0); // Hide zero exposure
  }, [exposure?.bySector, loading]);

  // Memoize strategy tags calculation
  const strategies = useMemo(() => {
     if (loading || !exposure?.byStrategy) return [];

     return Object.entries(exposure.byStrategy)
        .filter(([, v]: any) => v > 1); // Only show > 1% strategies
  }, [exposure?.byStrategy, loading]);

  if (loading) return <div className="h-48 bg-muted animate-pulse rounded"></div>;
  if (!exposure?.bySector) return null;

  return (
    <Card className="shadow-sm border-border">
        <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
                Sector Exposure
            </CardTitle>
        </CardHeader>
        <CardContent>
            <div className="space-y-3">
                {sectors.length === 0 ? (
                    <p className="text-sm text-muted-foreground italic">No significant sector exposure.</p>
                ) : (
                    sectors.slice(0, 5).map(([sector, pct]: any) => (
                        <div key={sector}>
                            <div className="flex justify-between text-xs mb-1">
                                <span className="font-medium text-foreground">{sector}</span>
                                <span className="text-muted-foreground">{pct.toFixed(1)}%</span>
                            </div>
                            <div className="w-full bg-muted rounded-full h-1.5 overflow-hidden">
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
            <div className="mt-4 pt-3 border-t border-border flex flex-wrap gap-2">
                {strategies.map(([strat, pct]: any) => (
                        <span key={strat} className="text-[10px] bg-muted text-muted-foreground px-2 py-1 rounded-full">
                            {strat}: {pct.toFixed(0)}%
                        </span>
                    ))
                }
            </div>
        </CardContent>
    </Card>
  );
}

export default memo(HoldingsTreemap);
