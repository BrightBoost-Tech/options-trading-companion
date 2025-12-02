'use client';

import { useState, useEffect } from 'react';
import DashboardLayout from '@/components/DashboardLayout';
import SyncHoldingsButton from '@/components/SyncHoldingsButton';
import PortfolioOptimizer from '@/components/dashboard/PortfolioOptimizer';
import SuggestionTabs from '@/components/SuggestionTabs';
import { supabase } from '@/lib/supabase';
import { API_URL, TEST_USER_ID } from '@/lib/constants';
import { groupOptionSpreads, formatOptionDisplay } from '@/lib/formatters';

const mockAlerts = [
  { id: '1', message: 'SPY credit put spread scout: 475/470 for $1.50 credit', time: '2 min ago' },
  { id: '2', message: 'QQQ IV rank above 50% - consider premium selling', time: '15 min ago' },
];

interface FetchOptions extends RequestInit {
  timeout?: number;
}

const fetchWithTimeout = async (resource: RequestInfo, options: FetchOptions = {}) => {
  const { timeout = 15000, ...rest } = options;
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  const response = await fetch(resource, { ...rest, signal: controller.signal });
  clearTimeout(id);
  return response;
};

const isAbortError = (err: any) =>
  err?.name === 'AbortError' || err?.message?.toLowerCase()?.includes('aborted');

export default function DashboardPage() {
  // Snapshot data
  const [snapshot, setSnapshot] = useState<any>(null);
  const [metrics, setMetrics] = useState<any>(null);

  // Optimizer suggestions (rebalance)
  const [rebalanceSuggestions, setRebalanceSuggestions] = useState<any[]>([]);

  // Options Scout state
  const [weeklyScout, setWeeklyScout] = useState<any>(null);
  const [scoutLoading, setScoutLoading] = useState(false);

  // Morning & Midday Suggestions
  const [morningSuggestions, setMorningSuggestions] = useState<any[]>([]);
  const [middaySuggestions, setMiddaySuggestions] = useState<any[]>([]);

  // Weekly Reports
  const [weeklyReports, setWeeklyReports] = useState<any[]>([]);
  
  // Journal state
  const [journalStats, setJournalStats] = useState<any>(null);

  // Historical Simulation State
  const [simCursor, setSimCursor] = useState<string>('2023-01-01');
  const [simResult, setSimResult] = useState<any>(null);
  const [simLoading, setSimLoading] = useState(false);

  // Load data on mount
  useEffect(() => {
    loadSnapshot();
    loadWeeklyScout();
    loadJournalStats();
    loadMorningSuggestions();
    loadMiddaySuggestions();
    loadWeeklyReports();
    loadRebalanceSuggestions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const getAuthHeaders = async () => {
      const { data: { session } } = await supabase.auth.getSession();
      const headers: Record<string, string> = {
          'Content-Type': 'application/json'
      };
      if (session) {
          headers['Authorization'] = `Bearer ${session.access_token}`;
      } else {
          headers['X-Test-Mode-User'] = TEST_USER_ID;
      }
      return headers;
  };

  const loadSnapshot = async () => {
    try {
      const headers = await getAuthHeaders();
      const response = await fetchWithTimeout(`${API_URL}/portfolio/snapshot`, {
         headers,
         timeout: 15000
      });

      if (response.ok) {
        const data = await response.json();
        setSnapshot(data);
      }
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load snapshot:', err);
    }
  };

  const loadWeeklyScout = async () => {
    setScoutLoading(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetchWithTimeout(`${API_URL}/scout/weekly`, {
        headers,
        timeout: 20000
      });

      if (response.ok) {
        const data = await response.json();
        setWeeklyScout(data);
      }
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load scout:', err);
    } finally {
      setScoutLoading(false);
    }
  };

  const loadJournalStats = async () => {
    try {
      const headers = await getAuthHeaders();
      const response = await fetchWithTimeout(`${API_URL}/journal/stats`, { 
          headers,
          timeout: 10000 
      });
      
      if (response.ok) {
        const data = await response.json();
        setJournalStats(data);
      }
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load journal stats:', err);
    }
  };

  const loadMorningSuggestions = async () => {
    try {
      const headers = await getAuthHeaders();
      const response = await fetchWithTimeout(`${API_URL}/suggestions?window=morning_limit`, {
        headers,
        timeout: 15000
      });
      if (response.ok) {
        const data = await response.json();
        setMorningSuggestions(Array.isArray(data.suggestions) ? data.suggestions : []);
      } else {
        setMorningSuggestions([]);
      }
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load morning suggestions', err);
      setMorningSuggestions([]);
    }
  };

  const loadMiddaySuggestions = async () => {
    try {
      const headers = await getAuthHeaders();
      const response = await fetchWithTimeout(`${API_URL}/suggestions?window=midday_entry`, {
        headers,
        timeout: 15000
      });
      if (response.ok) {
        const data = await response.json();
        setMiddaySuggestions(Array.isArray(data.suggestions) ? data.suggestions : []);
      } else {
        setMiddaySuggestions([]);
      }
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load midday suggestions', err);
      setMiddaySuggestions([]);
    }
  };

  const loadRebalanceSuggestions = async () => {
    try {
      const headers = await getAuthHeaders();
      const response = await fetchWithTimeout(`${API_URL}/rebalance/suggestions`, {
        headers,
        timeout: 15000
      });
      if (response.ok) {
        const data = await response.json();
        setRebalanceSuggestions(Array.isArray(data.suggestions) ? data.suggestions : []);
      } else {
        setRebalanceSuggestions([]);
      }
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load rebalance suggestions', err);
      setRebalanceSuggestions([]);
    }
  };

  const loadWeeklyReports = async () => {
    try {
      const headers = await getAuthHeaders();
      const response = await fetchWithTimeout(`${API_URL}/weekly-reports`, {
        headers,
        timeout: 15000
      });
      if (response.ok) {
        const data = await response.json();
        setWeeklyReports(Array.isArray(data.reports) ? data.reports : []);
      } else {
        setWeeklyReports([]);
      }
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load weekly reports', err);
      setWeeklyReports([]);
    }
  };

  const runAllWorkflows = async () => {
    try {
      const headers = await getAuthHeaders();
      const res = await fetchWithTimeout(`${API_URL}/tasks/run-all`, {
        method: 'POST',
        headers,
        timeout: 30000,
      });
      if (!res.ok) {
        console.error('Failed to run workflows', await res.text());
        return;
      }
      // After triggering, reload suggestions and weekly reports
      await Promise.all([
        loadMorningSuggestions(),
        loadMiddaySuggestions(),
        loadWeeklyReports(),
        loadRebalanceSuggestions()
      ]);
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to run workflows', err);
    }
  };

  const runHistoricalCycle = async () => {
    setSimLoading(true);
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/historical/run-cycle`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ cursor: simCursor, symbol: 'SPY' }),
      });

      if (res.ok) {
        const data = await res.json();
        setSimResult(data);
        if (data.nextCursor) {
            setSimCursor(data.nextCursor);
        }
      } else {
        console.error('Simulation failed', await res.text());
      }
    } catch (err) {
      console.error('Simulation error', err);
    } finally {
      setSimLoading(false);
    }
  };

  // --- RENDER HELPERS ---

  const getSpreads = (holdings: any[]) => {
      const optionHoldings = holdings.filter((h: any) =>
          typeof h.symbol === 'string' &&
          h.symbol.length > 8 &&
          h.symbol !== 'CUR:USD'
      );
      return groupOptionSpreads(optionHoldings);
  };

  const renderPositionRow = (position: any, idx: number, type: 'option' | 'stock') => {
      const cost = position.cost_basis * position.quantity;
      const value = position.current_price * position.quantity;
      const pnl = value - cost;

      const pnlPercent = position.pnl_percent !== undefined
        ? position.pnl_percent
        : (position.cost_basis > 0 ? (pnl / cost) * 100 : 0);

      const getSeverityClass = (s?: string) => {
        if (s === 'critical') return 'bg-red-100 text-red-800';
        if (s === 'warning') return 'bg-yellow-100 text-yellow-800';
        if (s === 'success') return 'bg-green-100 text-green-800';
        return '';
      };

      const displaySymbol = type === 'option' ? formatOptionDisplay(position.symbol) : position.symbol;

      return (
        <tr key={`${type}-${idx}`} className="hover:bg-gray-50">
            <td className={`px-6 py-4 font-medium ${type === 'option' ? 'text-purple-600' : 'text-gray-900'}`}>
                {displaySymbol}
            </td>
            <td className="px-6 py-4">{position.quantity}</td>
            <td className="px-6 py-4">${position.cost_basis?.toFixed(2)}</td>
            <td className="px-6 py-4">
                <div>${position.current_price?.toFixed(2)}</div>
                <div className="text-xs text-gray-400">Val: ${value.toFixed(0)}</div>
            </td>
            <td className="px-6 py-4 whitespace-nowrap">
                <div className={`font-bold ${pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)} ({pnlPercent.toFixed(1)}%)
                </div>

                {position.pnl_severity && (
                   <span className={`inline-flex ml-2 items-center px-2 py-0.5 rounded text-xs font-medium ${getSeverityClass(position.pnl_severity)}`}>
                      {position.pnl_severity.toUpperCase()}
                   </span>
                )}

                {type === 'option' && pnlPercent >= 50 && !position.pnl_severity && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800 animate-pulse">
                    TARGET HIT 🎯
                    </span>
                )}
            </td>
        </tr>
      );
  };

  return (
    <DashboardLayout mockAlerts={mockAlerts}>
      <div className="max-w-7xl mx-auto p-8 space-y-6">
        
        {/* SECTION 1: POSITIONS & OPTIMIZER */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <div className="bg-white rounded-lg shadow overflow-hidden">
              <div className="px-6 py-4 border-b flex justify-between items-center">
                <h2 className="text-xl font-semibold">Positions</h2>
                <div className="flex gap-2">
                  <SyncHoldingsButton onSyncComplete={loadSnapshot} />
                  <button
                    onClick={runAllWorkflows}
                    className="text-xs px-3 py-1 rounded border border-purple-200 text-purple-700 hover:bg-purple-50"
                  >
                    Generate Suggestions (Dev)
                  </button>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Qty</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Avg Cost</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Price</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P&L</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {snapshot?.holdings?.length > 0 ? (
                        <>
                            {/* OPTIONS & SPREADS */}
                            {snapshot.holdings.some((h:any) => h.symbol.length > 6 && h.symbol !== 'CUR:USD') && (
                                <>
                                    <tr className="bg-purple-50">
                                        <td colSpan={5} className="px-6 py-2 text-xs font-bold text-purple-800 uppercase">🎯 Option Plays</td>
                                    </tr>
                                    {getSpreads(snapshot.holdings).map((spread, idx) => {
                                        // Use formatOptionDisplay logic but customized for spread title
                                        // spread.expiry is YYYY-MM-DD
                                        const [year, month, day] = spread.expiry.split('-');
                                        const shortDate = `${month}/${day}/${year.slice(2)}`;
                                        const label = `${spread.underlying} ${shortDate} ${spread.type} Spread`;

                                        const legSummary = spread.legs
                                            .map(leg => `${leg.parsed.strike}${leg.parsed.type} x ${leg.quantity}`)
                                            .join(' / ');
                                        const totalValue = spread.legs.reduce(
                                            (sum, leg) => sum + leg.quantity * leg.current_price * 100,
                                            0
                                        );
                                        return (
                                            <tr key={`spread-${idx}`} className="hover:bg-gray-50 border-b border-gray-100">
                                              <td className="px-6 py-4 font-medium text-purple-700">{label}</td>
                                              <td className="px-6 py-4 text-sm text-gray-600" colSpan={3}>
                                                  {legSummary}
                                              </td>
                                              <td className="px-6 py-4 text-right font-medium text-gray-900">
                                                  ${totalValue.toFixed(2)}
                                              </td>
                                            </tr>
                                        );
                                    })}
                                </>
                            )}

                            {/* STOCKS */}
                            {snapshot.holdings.some((h:any) => h.symbol.length <= 6 && h.symbol !== 'CUR:USD') && (
                                <tr className="bg-blue-50">
                                    <td colSpan={5} className="px-6 py-2 text-xs font-bold text-blue-800 uppercase">📈 Long Term Holds</td>
                                </tr>
                            )}
                            {snapshot.holdings
                                .filter((h:any) => h.symbol.length <= 6 && h.symbol !== 'CUR:USD')
                                .map((h:any, idx:number) => renderPositionRow(h, idx, 'stock'))
                            }

                            {/* CASH */}
                            {snapshot.holdings.filter((h:any) => h.symbol === 'CUR:USD').map((position:any, idx:number) => (
                                <tr key={`cash-${idx}`} className="bg-green-50 border-t-2 border-green-100">
                                    <td className="px-6 py-4 font-bold text-green-800">💵 CASH</td>
                                    <td className="px-6 py-4 text-green-800">---</td>
                                    <td className="px-6 py-4 text-green-800">---</td>
                                    <td className="px-6 py-4 font-bold text-green-800">${position.quantity?.toFixed(2)}</td>
                                    <td className="px-6 py-4"><span className="text-xs bg-green-200 text-green-800 px-2 py-1 rounded">Sweep</span></td>
                                </tr>
                            ))}
                        </>
                    ) : (
                      <tr>
                        <td colSpan={5} className="px-6 py-8 text-center text-gray-500">
                          No positions found. Sync via Plaid or Import CSV in Settings.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* OPTIMIZER PANEL */}
          <div className="flex flex-col gap-6">
            <div className="h-[500px]">
              <PortfolioOptimizer
                positions={snapshot?.holdings}
                onOptimizationComplete={(m) => {
                  setMetrics(m);
                  // Refresh rebalance suggestions after optimization
                  loadRebalanceSuggestions();
                }}
              />
            </div>
          </div>
        </div>

        {/* Risk Header */}
        <div className="grid grid-cols-3 gap-4">
            <div className="bg-white p-4 rounded-lg shadow">
                <h4 className="text-sm font-medium text-gray-500">Beta-weighted Delta</h4>
                <p className="text-2xl font-bold">${metrics?.analytics?.beta_delta?.toFixed(2) || '0.00'}</p>
            </div>
            <div className="bg-white p-4 rounded-lg shadow">
                <h4 className="text-sm font-medium text-gray-500">Theta</h4>
                <p className="text-2xl font-bold">${metrics?.analytics?.theta_efficiency?.toFixed(2) || '0.00'}</p>
            </div>
            <div className="bg-white p-4 rounded-lg shadow">
                <h4 className="text-sm font-medium text-gray-500">Buying Power</h4>
                <p className="text-2xl font-bold">${snapshot?.buying_power?.toFixed(2) || '0.00'}</p>
            </div>
        </div>

        {/* SECTION 1.5: HISTORICAL SIMULATION */}
        <div className="bg-white rounded-lg shadow p-6">
            <div className="flex justify-between items-center mb-4">
                <div>
                    <h2 className="text-lg font-bold text-gray-900">Historical Regime Cycle</h2>
                    <p className="text-sm text-gray-500">Test the Regime Engine on past data. Step through history one cycle at a time.</p>
                </div>
                <div className="flex items-center gap-4">
                    <div className="text-sm text-gray-600">
                        Current Date: <span className="font-mono font-bold">{simCursor}</span>
                    </div>
                    <button
                        onClick={runHistoricalCycle}
                        disabled={simLoading || simResult?.done}
                        className={`px-4 py-2 rounded text-white font-medium ${
                            simLoading ? 'bg-gray-400 cursor-not-allowed' : 'bg-indigo-600 hover:bg-indigo-700'
                        }`}
                    >
                        {simLoading ? 'Simulating...' : simResult?.done ? 'End of Data' : 'Run 1 Historical Cycle'}
                    </button>
                </div>
            </div>

            {/* Simulation Results Display */}
            {simResult && !simResult.error && (
                <div className="bg-gray-50 rounded p-4 border border-gray-200">
                    {simResult.done && !simResult.entryTime ? (
                         <p className="text-gray-500 italic">{simResult.message || "No trades found in remaining data."}</p>
                    ) : (
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                            <div>
                                <p className="text-xs text-gray-500 uppercase">Entry</p>
                                <p className="font-semibold text-gray-900">{simResult.entryTime} @ ${simResult.entryPrice?.toFixed(2)}</p>
                                <span className={`text-xs px-2 py-0.5 rounded ${simResult.direction === 'long' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                                    {simResult.direction?.toUpperCase()}
                                </span>
                            </div>
                            <div>
                                <p className="text-xs text-gray-500 uppercase">Exit</p>
                                {simResult.exitTime ? (
                                    <p className="font-semibold text-gray-900">{simResult.exitTime} @ ${simResult.exitPrice?.toFixed(2)}</p>
                                ) : (
                                    <p className="text-sm text-gray-400 italic">Open...</p>
                                )}
                            </div>
                            <div>
                                <p className="text-xs text-gray-500 uppercase">P&L</p>
                                {simResult.pnl !== undefined ? (
                                    <p className={`font-bold text-lg ${simResult.pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                                        ${simResult.pnl.toFixed(2)}
                                    </p>
                                ) : (
                                    <p className="text-gray-400">---</p>
                                )}
                            </div>
                            <div>
                                <p className="text-xs text-gray-500 uppercase">Conviction (Entry/Exit)</p>
                                <div className="flex items-center gap-2">
                                    <span className="font-mono text-sm">{simResult.entryConviction?.toFixed(2) || '--'}</span>
                                    <span className="text-gray-400">→</span>
                                    <span className="font-mono text-sm">{simResult.exitConviction?.toFixed(2) || '--'}</span>
                                </div>
                                <p className="text-xs text-purple-600 mt-1">Regime: {simResult.regime}</p>
                            </div>
                        </div>
                    )}
                </div>
            )}
            {simResult?.error && (
                <div className="bg-red-50 text-red-700 p-3 rounded text-sm mt-2">
                    Error: {simResult.error}
                </div>
            )}
        </div>

        {/* SECTION 2: UNIFIED SUGGESTION HUB */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
                <SuggestionTabs
                  optimizerSuggestions={rebalanceSuggestions}
                  scoutSuggestions={weeklyScout?.top_picks || []}
                  journalQueue={[]}
                  morningSuggestions={morningSuggestions}
                  middaySuggestions={middaySuggestions}
                  weeklyReports={weeklyReports}
                  onRefreshScout={loadWeeklyScout}
                  scoutLoading={scoutLoading}
                  onRefreshJournal={() => {}}
                />
            </div>

            {/* Trade Journal Stats (Side Panel) */}
            <div className="bg-gradient-to-r from-purple-50 to-pink-50 rounded-lg shadow p-6 border-l-4 border-purple-500 h-fit">
                <div className="flex justify-between items-start mb-4">
                    <h3 className="text-lg font-semibold text-purple-900 flex items-center gap-2">📊 Trade Journal</h3>
                    <button onClick={loadJournalStats} className="text-sm text-purple-700 underline">Refresh</button>
                </div>
                {journalStats ? (
                    <div className="grid grid-cols-2 gap-4">
                        <div className="bg-white p-3 rounded border border-purple-200">
                            <p className="text-xs text-gray-600">Win Rate</p>
                            <p className="text-xl font-bold text-purple-900">{journalStats.stats.win_rate?.toFixed(1) || 0}%</p>
                        </div>
                        <div className="bg-white p-3 rounded border border-purple-200">
                            <p className="text-xs text-gray-600">Total P&L</p>
                            <p className={`text-xl font-bold ${(journalStats.stats.total_pnl || 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                                ${(journalStats.stats.total_pnl || 0).toFixed(0)}
                            </p>
                        </div>
                    </div>
                ) : (
                    <div className="text-center py-8 text-purple-700 text-sm">No trades logged yet.</div>
                )}
            </div>
        </div>

      </div>
    </DashboardLayout>
  );
}
