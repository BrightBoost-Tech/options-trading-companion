import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Activity, AlertTriangle, TrendingUp, TrendingDown, DollarSign, Layers } from 'lucide-react';

interface RiskSummaryCardProps {
  summary: any;
  exposure: any;
  greeks: any;
  loading?: boolean;
}

export default function RiskSummaryCard({ summary, exposure, greeks, loading }: RiskSummaryCardProps) {
  if (loading) {
      return <div className="animate-pulse h-48 bg-gray-100 rounded-lg"></div>;
  }

  // Helpers
  const formatMoney = (val: number) => `$${(val || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const formatNum = (val: number) => (val || 0).toFixed(2);

  return (
    <Card className="shadow-sm border-gray-200">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-gray-500 uppercase tracking-wide flex items-center gap-2">
            <Activity className="w-4 h-4" /> Portfolio Risk
        </CardTitle>
      </CardHeader>
      <CardContent>
         <div className="grid grid-cols-2 gap-4">
            {/* Top Row: Net Liq & Beta Delta */}
            <div>
               <p className="text-xs text-gray-400">Net Liquidation</p>
               <p className="text-xl font-bold text-gray-900">{formatMoney(summary?.netLiquidation)}</p>
            </div>
            <div>
               <p className="text-xs text-gray-400">Beta-w Delta</p>
               <p className="text-xl font-bold text-indigo-600">{formatNum(summary?.betaSpy)}</p>
            </div>

            {/* Greeks Grid */}
            <div className="col-span-2 grid grid-cols-4 gap-2 bg-gray-50 p-2 rounded text-center">
                <div>
                    <p className="text-[10px] text-gray-500 uppercase">Delta</p>
                    <p className="font-semibold text-sm">{formatNum(greeks?.portfolioDelta)}</p>
                </div>
                <div>
                    <p className="text-[10px] text-gray-500 uppercase">Gamma</p>
                    <p className="font-semibold text-sm">{formatNum(greeks?.portfolioGamma)}</p>
                </div>
                <div>
                    <p className="text-[10px] text-gray-500 uppercase">Theta</p>
                    <p className={`font-semibold text-sm ${greeks?.portfolioTheta > 0 ? 'text-green-600' : 'text-red-500'}`}>
                        {formatNum(greeks?.portfolioTheta)}
                    </p>
                </div>
                <div>
                    <p className="text-[10px] text-gray-500 uppercase">Vega</p>
                    <p className="font-semibold text-sm">{formatNum(greeks?.portfolioVega)}</p>
                </div>
            </div>
         </div>
      </CardContent>
    </Card>
  );
}
