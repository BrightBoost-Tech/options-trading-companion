'use client';

import { useState } from 'react';
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { createClientComponentClient } from '@supabase/auth-helpers-nextjs';
import { ShieldCheck, AlertTriangle, RefreshCcw } from 'lucide-react';

export function OptimizerWidget() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any>(null);
  const supabase = createClientComponentClient();

  const runAnalysis = async () => {
    setLoading(true);
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;

      const res = await fetch('http://127.0.0.1:8000/optimize/portfolio', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
           user_id: user.id,
           cash_balance: 10000,
           risk_tolerance: 0.5
        })
      });
      setData(await res.json());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="h-full border-t-4 border-t-blue-500">
      <CardHeader className="pb-2">
        <div className="flex justify-between items-center">
          <CardTitle>Portfolio Health</CardTitle>
          <Button variant="ghost" size="sm" onClick={runAnalysis} disabled={loading}>
            <RefreshCcw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {!data && (
          <div className="text-center py-6 text-sm text-muted-foreground">
            Run analysis to check for stop-losses, concentration risks, and hedging needs.
          </div>
        )}

        {data && data.adjustments.length === 0 && (
           <div className="flex flex-col items-center justify-center py-6 text-green-500 space-y-2">
             <ShieldCheck className="h-10 w-10" />
             <span className="font-bold">Portfolio Optimized</span>
             <span className="text-xs text-muted-foreground">No critical adjustments needed.</span>
           </div>
        )}

        {data && data.adjustments.length > 0 && (
          <div className="space-y-3">
            {data.adjustments.map((adj: any, i: number) => (
              <div key={i} className={`p-3 rounded-lg border flex justify-between items-center ${
                  adj.type === 'CRITICAL' ? 'bg-red-500/10 border-red-500/50' : 'bg-yellow-500/10 border-yellow-500/50'
              }`}>
                <div>
                   <div className="flex items-center gap-2">
                      <span className="font-bold">{adj.action} {adj.symbol}</span>
                      {adj.type === 'CRITICAL' && <AlertTriangle className="h-3 w-3 text-red-500"/>}
                   </div>
                   <div className="text-xs text-muted-foreground">{adj.reason}</div>
                </div>
                <Button size="sm" variant={adj.type === 'CRITICAL' ? "destructive" : "secondary"}>
                  Fix
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}