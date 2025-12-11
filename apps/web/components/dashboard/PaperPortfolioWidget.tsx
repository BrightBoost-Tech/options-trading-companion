"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { API_URL, TEST_USER_ID } from "@/lib/constants";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { DollarSign, Layers } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface PaperPortfolioState {
  portfolio: {
    id: string;
    cash_balance: number;
    net_liq: number;
  } | null;
  positions: {
    symbol: string;
    quantity: number;
    unrealized_pl: number;
    strategy_key?: string;
  }[];
  stats: {
    total_unrealized_pl: number;
    open_positions_count: number;
  };
}

export default function PaperPortfolioWidget() {
  const [data, setData] = useState<PaperPortfolioState | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchPortfolio = async () => {
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

      const res = await fetch(`${API_URL}/paper/portfolio`, { headers });
      if (res.ok) {
        const json = await res.json();
        setData(json);
      } else {
        // e.g. 404 if no portfolio yet
        setData(null);
      }
    } catch (err) {
      console.error("Failed to fetch paper portfolio", err);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPortfolio();
  }, []);

  if (loading) {
    return (
      <Card className="h-full bg-neutral-900 border-neutral-800 text-neutral-100 animate-pulse">
        <CardHeader>
          <CardTitle className="text-neutral-400">Paper Portfolio</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-4 w-24 bg-neutral-800 rounded mb-4" />
          <div className="h-4 w-32 bg-neutral-800 rounded" />
        </CardContent>
      </Card>
    );
  }

  // "No portfolio yet" state
  if (!data?.portfolio) {
    return (
      <Card className="h-full bg-neutral-50/50 border-neutral-200">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold text-neutral-700 flex items-center gap-2">
            <Layers className="w-4 h-4 text-purple-600" />
            Paper Portfolio
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-neutral-500">
            No paper trades yet. Use the "Paper Trade" button on suggestions to start practicing.
          </p>
        </CardContent>
      </Card>
    );
  }

  const { portfolio, positions, stats } = data;
  const topPositions = [...positions]
    .sort((a, b) => Math.abs(b.unrealized_pl) - Math.abs(a.unrealized_pl))
    .slice(0, 3);

  return (
    <Card className="h-full bg-gradient-to-br from-neutral-900 to-neutral-800 border-neutral-700 text-white shadow-md">
      <CardHeader className="pb-3 border-b border-neutral-700/50">
        <CardTitle className="text-sm font-semibold flex items-center gap-2">
          <Layers className="w-4 h-4 text-purple-400" />
          Paper Portfolio
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-4 space-y-4">
        {/* Top Stats Row */}
        <div className="flex justify-between items-end">
          <div>
            <p className="text-[10px] text-neutral-400 uppercase tracking-wide">Net Liq</p>
            <p className="text-xl font-bold font-mono text-emerald-400">
              ${portfolio.net_liq.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            </p>
          </div>
          <div className="text-right">
             <p className="text-[10px] text-neutral-400 uppercase tracking-wide">Cash</p>
             <p className="text-sm font-medium text-neutral-200">
               ${portfolio.cash_balance.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
             </p>
          </div>
        </div>

        {/* Positions Summary */}
        <div>
          <div className="flex justify-between items-center mb-2">
             <span className="text-xs text-neutral-400">Open Positions ({stats.open_positions_count})</span>
             <Badge variant="outline" className={`text-xs border-0 ${stats.total_unrealized_pl >= 0 ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}`}>
                {stats.total_unrealized_pl >= 0 ? '+' : ''}${stats.total_unrealized_pl.toFixed(2)}
             </Badge>
          </div>
          <div className="space-y-2">
            {topPositions.length === 0 && (
                <p className="text-xs text-neutral-500 italic">No open positions.</p>
            )}
            {topPositions.map((p, idx) => (
              <div key={idx} className="flex justify-between items-center text-xs p-1.5 rounded bg-white/5 border border-white/5">
                 <div className="flex flex-col">
                    <span className="font-semibold text-neutral-200">{p.symbol}</span>
                    <span className="text-[10px] text-neutral-500">{p.quantity} contracts</span>
                 </div>
                 <span className={`font-mono ${p.unrealized_pl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {p.unrealized_pl >= 0 ? '+' : ''}{p.unrealized_pl.toFixed(2)}
                 </span>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
