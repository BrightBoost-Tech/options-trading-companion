'use client';

import { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { getAuthHeadersCached, fetchWithAuth } from '@/lib/api';
import { QuantumTooltip } from "@/components/ui/QuantumTooltip";
import { ChevronDown, ChevronRight, Play, Clock, Settings, Save, RefreshCw } from 'lucide-react';
import { StrategyConfig } from '@/lib/types';
import { API_URL } from '@/lib/constants';

interface StrategyBacktest {
  id: string;
  strategy_name: string;
  start_date: string;
  end_date: string;
  total_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  trade_count: number;
  created_at: string;
}

export default function StrategyProfilesPanel() {
  const [strategies, setStrategies] = useState<StrategyConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyConfig | null>(null);
  const [editingConfig, setEditingConfig] = useState<string>('');
  const [backtests, setBacktests] = useState<StrategyBacktest[]>([]);
  const [btLoading, setBtLoading] = useState(false);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  // New simulation state
  const [simRunning, setSimRunning] = useState(false);
  const [simResult, setSimResult] = useState<any>(null);

  useEffect(() => {
    fetchStrategies();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedStrategy) {
      setEditingConfig(JSON.stringify(selectedStrategy.parameters || {}, null, 2));
      fetchBacktests(selectedStrategy.name);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedStrategy]);

  const fetchStrategies = async () => {
    try {
      setLoading(true);
      const data = await fetchWithAuth('/strategies');
      setStrategies(data);
      if (data.length > 0 && !selectedStrategy) {
        setSelectedStrategy(data[0]);
      }
    } catch (err) {
      console.error('Failed to fetch strategies', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchBacktests = async (strategyName: string) => {
    try {
      setBtLoading(true);
      const data = await fetchWithAuth(`/strategies/${strategyName}/backtests`);
      setBacktests(data);
    } catch (err) {
      console.error('Failed to fetch backtests', err);
    } finally {
      setBtLoading(false);
    }
  };

  const handleSaveConfig = async () => {
    if (!selectedStrategy) return;
    try {
      const params = JSON.parse(editingConfig);
      const headers = await getAuthHeadersCached();
      const res = await fetch(`${API_URL}/strategies`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          name: selectedStrategy.name,
          description: selectedStrategy.description,
          parameters: params
        })
      });

      if (res.ok) {
        const updated = await res.json();
        // Update local list
        setStrategies(prev => prev.map(s => s.name === updated.name ? updated : s));
        setSelectedStrategy(updated);
        alert('Configuration saved!');
      } else {
        alert('Failed to save configuration');
      }
    } catch (err) {
      console.error(err);
      alert('Invalid JSON');
    }
  };

  const runBacktest = async () => {
    if (!selectedStrategy) return;
    try {
      setSimRunning(true);
      setSimResult(null);
      // Run quick simulation for immediate feedback
      const headers = await getAuthHeadersCached();
      const res = await fetch(`${API_URL}/strategies/${selectedStrategy.name}/backtest`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
            // Default quick params
            start_date: "2023-01-01",
            end_date: "2023-12-31",
            initial_capital: 100000
        })
      });

      if (res.ok) {
        const result = await res.json();
        setSimResult(result);
        // Refresh history
        fetchBacktests(selectedStrategy.name);
      }
    } catch (err) {
      console.error('Simulation failed', err);
    } finally {
      setSimRunning(false);
    }
  };

  const triggerBatchSim = async () => {
    if (!selectedStrategy) return;
    try {
      const headers = await getAuthHeadersCached();
      const res = await fetch(`${API_URL}/simulation/batch`, {
         method: 'POST',
         headers,
         body: JSON.stringify({
             strategy_name: selectedStrategy.name,
             // Param grid logic would go here
             param_grid: {
                 "conviction_floor": [0.6, 0.7, 0.8]
             }
         })
      });
      if (res.ok) {
          alert("Batch simulation queued!");
      }
    } catch (err) {
        console.error("Batch sim failed", err);
    }
  };

  if (loading) return <div className="p-4 text-center">Loading strategies...</div>;

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row gap-6">
        {/* Sidebar List */}
        <div className="w-full md:w-1/4 space-y-2">
           <h3 className="font-semibold text-muted-foreground uppercase text-xs mb-2">Available Profiles</h3>
           {strategies.map(s => (
             <button
               key={s.name}
               onClick={() => setSelectedStrategy(s)}
               className={`w-full text-left px-4 py-3 rounded-lg border transition-colors ${
                 selectedStrategy?.name === s.name
                 ? 'bg-indigo-50 border-indigo-200 text-indigo-900 dark:bg-indigo-900/20 dark:border-indigo-800 dark:text-indigo-100'
                 : 'bg-card border-border hover:bg-muted/50'
               }`}
             >
               <div className="font-medium">{s.name}</div>
               <div className="text-xs text-muted-foreground mt-1 truncate">{s.description}</div>
             </button>
           ))}
           <Button variant="outline" className="w-full mt-4 text-xs">
             + Create New Profile
           </Button>
        </div>

        {/* Main Editor Area */}
        <div className="flex-1 bg-card dark:bg-card rounded-lg shadow border border-border p-6">
          {selectedStrategy ? (
            <div className="space-y-6">
               <div className="flex justify-between items-start">
                 <div>
                    <h2 className="text-2xl font-bold text-foreground">{selectedStrategy.name}</h2>
                    <p className="text-muted-foreground">{selectedStrategy.description}</p>
                 </div>
                 <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={triggerBatchSim}>
                        <RefreshCw className="w-4 h-4 mr-2" />
                        Batch Sim
                    </Button>
                    <Button onClick={runBacktest} disabled={simRunning}>
                       {simRunning ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : <Play className="w-4 h-4 mr-2" />}
                       Run Test
                    </Button>
                 </div>
               </div>

               <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                  {/* JSON Editor */}
                  <div>
                     <div className="flex items-center justify-between mb-2">
                        <label className="text-sm font-medium flex items-center gap-2">
                           <Settings className="w-4 h-4" /> Parameters
                        </label>
                        <Button variant="ghost" size="sm" onClick={handleSaveConfig} className="h-8 text-xs">
                           <Save className="w-3 h-3 mr-1" /> Save
                        </Button>
                     </div>
                     <textarea
                        className="w-full h-[300px] font-mono text-sm p-4 bg-muted/30 border border-border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none text-foreground"
                        value={editingConfig}
                        onChange={(e) => setEditingConfig(e.target.value)}
                     />
                  </div>

                  {/* Results Panel */}
                  <div className="space-y-4">
                     <h3 className="text-sm font-medium flex items-center gap-2">
                        <Clock className="w-4 h-4" /> Recent Backtests
                     </h3>
                     <div className="bg-muted/30 rounded-lg border border-border h-[300px] overflow-y-auto">
                        {btLoading ? (
                            <div className="p-8 text-center text-sm text-muted-foreground">Loading history...</div>
                        ) : backtests.length === 0 ? (
                            <div className="p-8 text-center text-sm text-muted-foreground">No backtests run yet.</div>
                        ) : (
                            <table className="w-full text-sm text-left">
                                <thead className="bg-muted text-xs uppercase text-muted-foreground sticky top-0">
                                    <tr>
                                        <th className="px-4 py-2">Date</th>
                                        <th className="px-4 py-2">Return</th>
                                        <th className="px-4 py-2">Sharpe</th>
                                        <th className="px-4 py-2">Win Rate</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-border">
                                    {backtests.map(bt => (
                                        <tr key={bt.id} className="hover:bg-muted/50 cursor-pointer" onClick={() => setExpandedRow(expandedRow === bt.id ? null : bt.id)}>
                                            <td className="px-4 py-2">{new Date(bt.created_at).toLocaleDateString()}</td>
                                            <td className={`px-4 py-2 font-medium ${bt.total_return >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                                                {(bt.total_return * 100).toFixed(1)}%
                                            </td>
                                            <td className="px-4 py-2">{bt.sharpe_ratio.toFixed(2)}</td>
                                            <td className="px-4 py-2">{(bt.win_rate * 100).toFixed(0)}%</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                     </div>
                  </div>
               </div>
            </div>
          ) : (
            <div className="h-full flex items-center justify-center text-muted-foreground">
               Select a profile to edit
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
