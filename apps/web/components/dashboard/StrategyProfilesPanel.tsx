'use client';

import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { getAuthHeadersCached, fetchWithAuth, ApiError, normalizeList } from '@/lib/api';
import { Play, Clock, Settings, Save, RefreshCw, AlertTriangle } from 'lucide-react';
import { StrategyConfig } from '@/lib/types';
// API_URL is handled by fetchWithAuth

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
  const [error, setError] = useState<string | null>(null);
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
      setError(null);
      // Explicitly type as any first to check shape safely
      const data = await fetchWithAuth<any>('/strategies');

      // Use helper to normalize { strategies: [...] } vs [...]
      const safeStrategies = normalizeList<StrategyConfig>(data, 'strategies');

      setStrategies(safeStrategies);

      if (safeStrategies.length > 0 && !selectedStrategy) {
        setSelectedStrategy(safeStrategies[0]);
      }
    } catch (err: any) {
      console.error('Failed to fetch strategies', err);
      // Extract trace_id or status if available
      let errorMsg = 'Failed to load strategies.';
      if (err instanceof ApiError) {
         errorMsg += ` (Status: ${err.status}`;
         if (err.trace_id) errorMsg += `, Trace: ${err.trace_id}`;
         errorMsg += ')';
      } else if (err.message) {
         errorMsg += ` ${err.message}`;
      }
      setError(errorMsg);
      setStrategies([]); // Ensure it's empty array
    } finally {
      setLoading(false);
    }
  };

  const fetchBacktests = async (strategyName: string) => {
    try {
      setBtLoading(true);
      const data = await fetchWithAuth(`/strategies/${strategyName}/backtests`);
      if (Array.isArray(data)) {
        setBacktests(data);
      } else {
        setBacktests(normalizeList(data, 'backtests'));
      }
    } catch (err) {
      console.error('Failed to fetch backtests', err);
      setBacktests([]);
    } finally {
      setBtLoading(false);
    }
  };

  const handleSaveConfig = async () => {
    if (!selectedStrategy) return;
    try {
      const params = JSON.parse(editingConfig);

      const updated = await fetchWithAuth('/strategies', {
        method: 'POST',
        body: JSON.stringify({
          name: selectedStrategy.name,
          description: selectedStrategy.description,
          parameters: params
        })
      });

      // Update local list
      // Note: Endpoint usually returns { status: "ok", data: [...] }
      const newConfig = updated.data ? updated.data[0] : updated; // Fallback
      if (newConfig && newConfig.name) {
          setStrategies(prev => prev.map(s => s.name === newConfig.name ? newConfig : s));
          setSelectedStrategy(newConfig);
          alert('Configuration saved!');
      } else {
          // If response structure is unexpected but no error thrown
          alert('Configuration saved (refresh to see changes).');
      }
    } catch (err: any) {
      console.error(err);
      if (err instanceof SyntaxError) {
          alert('Invalid JSON');
      } else {
          alert(`Failed to save: ${err.detail || err.message}`);
      }
    }
  };

  const runBacktest = async () => {
    if (!selectedStrategy) return;
    try {
      setSimRunning(true);
      setSimResult(null);
      // Run quick simulation for immediate feedback
      // Must include ticker as per backend schema
      // V1 endpoint does not support initial_capital, so removed.

      const result = await fetchWithAuth(`/strategies/${selectedStrategy.name}/backtest`, {
        method: 'POST',
        body: JSON.stringify({
            start_date: "2023-01-01",
            end_date: "2023-12-31",
            ticker: "SPY" // Required by backend
        })
      });

      setSimResult(result);
      // Refresh history
      fetchBacktests(selectedStrategy.name);

    } catch (err: any) {
      console.error('Simulation failed', err);
      alert(`Backtest failed: ${JSON.stringify(err.detail || err.message || err)}`);
    } finally {
      setSimRunning(false);
    }
  };

  const triggerBatchSim = async () => {
    if (!selectedStrategy) return;
    try {
      await fetchWithAuth(`/simulation/batch`, {
         method: 'POST',
         body: JSON.stringify({
             strategy_name: selectedStrategy.name,
             ticker: "SPY", // Required by backend
             start_date: "2023-01-01", // Required by backend
             end_date: "2023-12-31", // Required by backend
             // Param grid logic would go here
             param_grid: {
                 "conviction_floor": [0.6, 0.7, 0.8]
             }
         })
      });
      alert("Batch simulation queued!");
    } catch (err: any) {
        console.error("Batch sim failed", err);
        alert(`Failed to queue batch sim: ${JSON.stringify(err.detail || err.message)}`);
    }
  };

  if (loading) return <div className="p-4 text-center">Loading strategies...</div>;

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row gap-6">
        {/* Sidebar List */}
        <div className="w-full md:w-1/4 space-y-2">
           <h3 className="font-semibold text-muted-foreground uppercase text-xs mb-2">Available Profiles</h3>
           {error && (
             <div className="p-3 mb-2 text-xs bg-red-50 text-red-600 border border-red-200 rounded flex items-start gap-2">
               <AlertTriangle className="w-4 h-4 shrink-0" />
               <span className="break-words">{error}</span>
             </div>
           )}
           {strategies.length === 0 && !error && (
               <div className="text-sm text-muted-foreground italic p-2">No strategies found.</div>
           )}
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
             <div className="h-full flex items-center justify-center text-muted-foreground p-8">
               {error ? 'Unable to load strategies. Please try again later.' : 'Select a profile to edit'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
