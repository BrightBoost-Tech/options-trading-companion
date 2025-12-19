'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { fetchWithAuth } from '@/lib/api';
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { RefreshCw } from 'lucide-react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

export default function ObservabilityPage() {
  const [attribution, setAttribution] = useState<any[]>([]);
  const [leakage, setLeakage] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  // Filters
  const [windowFilter, setWindowFilter] = useState<string>('all');
  const [strategyFilter, setStrategyFilter] = useState<string>('all');
  const [regimeFilter, setRegimeFilter] = useState<string>('all');
  const [modelVersionFilter, setModelVersionFilter] = useState<string>('all');

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const [attrData, leakData] = await Promise.all([
          fetchWithAuth('/observability/trade_attribution?limit=100'),
          fetchWithAuth('/observability/ev_leakage?limit=50')
        ]);

        if (Array.isArray(attrData)) setAttribution(attrData);
        if (Array.isArray(leakData)) setLeakage(leakData);
      } catch (e) {
        console.error("Failed to load observability data", e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const filteredAttribution = attribution.filter(row => {
    if (windowFilter !== 'all' && row.window !== windowFilter) return false;
    if (strategyFilter !== 'all' && row.strategy !== strategyFilter) return false;
    if (regimeFilter !== 'all' && row.regime !== regimeFilter) return false;
    if (modelVersionFilter !== 'all' && row.model_version !== modelVersionFilter) return false;
    return true;
  });

  const uniqueWindows = Array.from(new Set(attribution.map(r => r.window))).filter(Boolean);
  const uniqueStrategies = Array.from(new Set(attribution.map(r => r.strategy))).filter(Boolean);
  const uniqueRegimes = Array.from(new Set(attribution.map(r => r.regime))).filter(Boolean);
  const uniqueModelVersions = Array.from(new Set(attribution.map(r => r.model_version))).filter(Boolean);

  return (
    <div className="container py-8 space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">System Observability</h1>
          <p className="text-muted-foreground">V3 Performance & Attribution Metrics</p>
        </div>
      </div>

      <Tabs defaultValue="attribution" className="space-y-4">
        <TabsList>
          <TabsTrigger value="attribution">Trade Attribution</TabsTrigger>
          <TabsTrigger value="leakage">EV Leakage</TabsTrigger>
        </TabsList>

        <TabsContent value="attribution" className="space-y-4">
           <Card>
             <CardHeader className="flex flex-row items-center justify-between">
               <div>
                  <CardTitle>Recent Attribution</CardTitle>
                  <CardDescription>Latest trade outcomes linked to decision context.</CardDescription>
               </div>
               <div className="flex flex-wrap gap-2">
                 <Select value={windowFilter} onValueChange={setWindowFilter}>
                    <SelectTrigger className="w-[150px]">
                      <SelectValue placeholder="Window" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Windows</SelectItem>
                      {uniqueWindows.map(w => <SelectItem key={w} value={w}>{w}</SelectItem>)}
                    </SelectContent>
                  </Select>

                  <Select value={strategyFilter} onValueChange={setStrategyFilter}>
                    <SelectTrigger className="w-[150px]">
                      <SelectValue placeholder="Strategy" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Strategies</SelectItem>
                      {uniqueStrategies.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                    </SelectContent>
                  </Select>

                  <Select value={regimeFilter} onValueChange={setRegimeFilter}>
                    <SelectTrigger className="w-[150px]">
                      <SelectValue placeholder="Regime" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Regimes</SelectItem>
                      {uniqueRegimes.map(r => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                    </SelectContent>
                  </Select>

                   <Select value={modelVersionFilter} onValueChange={setModelVersionFilter}>
                    <SelectTrigger className="w-[150px]">
                      <SelectValue placeholder="Model Ver." />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Versions</SelectItem>
                      {uniqueModelVersions.map(v => <SelectItem key={v} value={v}>{v}</SelectItem>)}
                    </SelectContent>
                  </Select>
               </div>
             </CardHeader>
             <CardContent>
               <div className="relative w-full overflow-auto">
                 <table className="w-full caption-bottom text-sm text-left">
                    <thead>
                      <tr className="border-b">
                        <th className="h-10 px-2 font-medium">Time</th>
                        <th className="h-10 px-2 font-medium">Symbol</th>
                        <th className="h-10 px-2 font-medium">Strategy</th>
                        <th className="h-10 px-2 font-medium">Window</th>
                        <th className="h-10 px-2 font-medium">Regime</th>
                        <th className="h-10 px-2 font-medium">Model</th>
                        <th className="h-10 px-2 font-medium text-right">PnL</th>
                        <th className="h-10 px-2 font-medium text-right">EV</th>
                      </tr>
                    </thead>
                    <tbody>
                       {filteredAttribution.map((row, i) => (
                         <tr key={i} className="border-b hover:bg-muted/50">
                           <td className="p-2">{new Date(row.created_at).toLocaleDateString()}</td>
                           <td className="p-2 font-bold">{row.symbol}</td>
                           <td className="p-2">{row.strategy}</td>
                           <td className="p-2"><Badge variant="secondary">{row.window}</Badge></td>
                           <td className="p-2">{row.regime}</td>
                           <td className="p-2 text-muted-foreground text-xs">{row.model_version}</td>
                           <td className={`p-2 text-right ${row.realized_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                             ${row.realized_pnl?.toFixed(2)}
                           </td>
                           <td className="p-2 text-right">{row.ev?.toFixed(2) ?? '-'}</td>
                         </tr>
                       ))}
                       {filteredAttribution.length === 0 && (
                         <tr><td colSpan={8} className="text-center p-4">No data found</td></tr>
                       )}
                    </tbody>
                 </table>
               </div>
             </CardContent>
           </Card>
        </TabsContent>

        <TabsContent value="leakage">
          <Card>
            <CardHeader>
               <CardTitle>EV Leakage by Bucket</CardTitle>
               <CardDescription>Where are we losing expected value?</CardDescription>
            </CardHeader>
            <CardContent>
               <div className="relative w-full overflow-auto">
                 <table className="w-full caption-bottom text-sm text-left">
                    <thead>
                      <tr className="border-b">
                        <th className="h-10 px-2 font-medium">Strategy</th>
                        <th className="h-10 px-2 font-medium">Regime</th>
                        <th className="h-10 px-2 font-medium">Window</th>
                        <th className="h-10 px-2 font-medium text-right">Trade Count</th>
                        <th className="h-10 px-2 font-medium text-right">Total EV</th>
                        <th className="h-10 px-2 font-medium text-right">Realized PnL</th>
                        <th className="h-10 px-2 font-medium text-right">Leakage</th>
                      </tr>
                    </thead>
                    <tbody>
                       {leakage.map((row, i) => (
                         <tr key={i} className="border-b hover:bg-muted/50">
                           <td className="p-2 font-medium">{row.strategy}</td>
                           <td className="p-2">{row.regime}</td>
                           <td className="p-2">{row.window}</td>
                           <td className="p-2 text-right">{row.trade_count}</td>
                           <td className="p-2 text-right">{row.total_ev?.toFixed(2)}</td>
                           <td className="p-2 text-right">{row.total_pnl?.toFixed(2)}</td>
                           <td className={`p-2 text-right font-bold ${row.ev_leakage < 0 ? 'text-red-500' : 'text-green-500'}`}>
                             {row.ev_leakage?.toFixed(2)}
                           </td>
                         </tr>
                       ))}
                    </tbody>
                 </table>
               </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
