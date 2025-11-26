'use client';

import { useState } from 'react';
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { createClientComponentClient } from '@supabase/auth-helpers-nextjs';

// Define the shape of the suggestion coming from our new Heuristic Backend
interface TradeSuggestion {
  symbol: string;
  strategy: string;
  alpha_score: number;
  status: 'recommended' | 'rejected' | 'blocked';
  rejection_reason?: string;
  greeks?: {
    delta: number;
    theta: number;
  };
  prob_profit?: number;
}

interface Position {
  symbol: string;
  current_value: number;
  current_quantity: number;
  current_price: number;
}

interface OptimizerWidgetProps {
  positions: Position[];
}

export function OptimizerWidget({ positions }: OptimizerWidgetProps) {
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<TradeSuggestion[]>([]);
  const supabase = createClientComponentClient();

  const runOptimization = async () => {
    setLoading(true);
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error("Not authenticated");

      // 1. Fetch Request Body Data
      const cashPosition = positions.find(p => p.symbol === 'CUR:USD');
      const cash_balance = cashPosition ? cashPosition.current_quantity : 0;

      const requestBody = {
        user_id: user.id,
        positions: positions.filter(p => p.symbol !== 'CUR:USD').map(p => ({
          symbol: p.symbol,
          current_value: p.current_value,
          current_quantity: p.current_quantity,
          current_price: p.current_price
        })),
        cash_balance: cash_balance,
        risk_aversion: 0.5, // Default risk_aversion
        skew_preference: 0.2 // Default skew_preference
      };

      // 2. Call Backend
      const res = await fetch('http://127.0.0.1:8000/optimize/portfolio', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
           user_id: user.id,
           cash_balance: 10000, // Hardcoded for safety, replace with prop later
           risk_tolerance: 0.5
        })
      });

      if (!res.ok) {
        const err = await res.json();
        console.error("Optimizer Error:", err);
        alert(`Optimization Failed: ${JSON.stringify(err.detail)}`);
        return;
      }

      const data = await res.json();
      setSuggestions(data.optimized_portfolio);

    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex justify-between items-center">
          AI Portfolio Optimizer
          <Button size="sm" onClick={runOptimization} disabled={loading}>
            {loading ? "Running Quantum Solver..." : "Optimize Now"}
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 max-h-[400px] overflow-y-auto">
        {suggestions.length === 0 && !loading && (
          <p className="text-muted-foreground text-sm">Run optimization to generate trade ideas based on current market skews.</p>
        )}

        {suggestions.map((trade, idx) => (
          <div
            key={idx}
            className={`p-3 border rounded-lg flex justify-between items-center ${
              trade.status === 'rejected' ? 'bg-secondary/20 opacity-60' : 'bg-secondary/50 border-green-500/30'
            }`}
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold">{trade.symbol}</span>
                <span className="text-xs font-mono text-muted-foreground uppercase">{trade.strategy}</span>
                {trade.status === 'rejected' && (
                  <Badge variant="destructive" className="text-[10px] h-5">
                    {trade.rejection_reason}
                  </Badge>
                )}
              </div>
              {trade.status === 'recommended' && (
                <div className="text-xs text-muted-foreground mt-1 flex gap-3">
                  <span>Score: <span className="text-green-400 font-bold">{trade.alpha_score}</span></span>
                  <span>Win%: {(trade.prob_profit || 0.50) * 100}%</span>
                </div>
              )}
            </div>

            {trade.status === 'recommended' && (
               <Button size="sm" variant="outline" className="h-8 text-xs">Review</Button>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
