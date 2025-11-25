'use client';

import { useState, useEffect, useCallback } from 'react';
import DashboardLayout from '@/components/DashboardLayout';
import SyncHoldingsButton from '@/components/SyncHoldingsButton';
import { supabase } from '@/lib/supabase';
import { API_URL } from '@/lib/constants';

const mockAlerts = [
  { id: '1', message: 'SPY credit put spread scout: 475/470 for $1.50 credit', time: '2 min ago' },
  { id: '2', message: 'QQQ IV rank above 50% - consider premium selling', time: '15 min ago' },
];

const PORTFOLIO_PRESETS = {
  broad_market: { name: 'Broad Market', symbols: ['SPY', 'QQQ', 'IWM', 'DIA', 'VTI'] },
  tech: { name: 'Tech Growth', symbols: ['AAPL', 'MSFT', 'GOOGL', 'NVDA', 'META'] },
  value: { name: 'Value', symbols: ['BRK.B', 'JPM', 'JNJ', 'PG', 'XOM'] },
  growth: { name: 'High Growth', symbols: ['TSLA', 'AMZN', 'NFLX', 'SHOP', 'SQ'] },
  dividend: { name: 'Dividend', symbols: ['SCHD', 'VYM', 'DVY', 'VIG', 'DGRO'] },
  custom: { name: 'Custom', symbols: ['SPY', 'QQQ', 'IWM', 'DIA', 'VTI'] }
};

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

// 🛠️ DEV MODE: Use the specific User ID found in your backend logs
const TEST_USER_ID = '75ee12ad-b119-4f32-aeea-19b4ef55d587';

export default function DashboardPage() {
  const [showQuantum, setShowQuantum] = useState(false);
  const [optimizationResults, setOptimizationResults] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Snapshot data
  const [snapshot, setSnapshot] = useState<any>(null);

  // Options Scout state
  const [weeklyScout, setWeeklyScout] = useState<any>(null);
  const [scoutLoading, setScoutLoading] = useState(false);
  const [scoutError, setScoutError] = useState<string | null>(null);
  
  // Journal state
  const [journalStats, setJournalStats] = useState<any>(null);
  const [journalLoading, setJournalLoading] = useState(false);
  const [journalError, setJournalError] = useState<string | null>(null);
  const [showJournal, setShowJournal] = useState(false);
  
  const [portfolioType, setPortfolioType] = useState('broad_market');
  const [customSymbols, setCustomSymbols] = useState(['SPY', 'QQQ', 'IWM', 'DIA', 'VTI']);
  const [riskAversion, setRiskAversion] = useState(2.0);
  
  const [currentHoldings, setCurrentHoldings] = useState<{[key: string]: number}>({});

  // Load data on mount
  useEffect(() => {
    loadSnapshot();
    loadWeeklyScout();
    loadJournalStats();
  }, []);

  // Update currentHoldings when snapshot changes
  useEffect(() => {
    if (snapshot && snapshot.holdings) {
       const holdingsMap: {[key: string]: number} = {};
       let totalValue = 0;

       snapshot.holdings.forEach((h: any) => {
         // Skip Cash for allocation math
         if (h.symbol !== 'CUR:USD') {
             const value = h.quantity * h.current_price;
             totalValue += value;
         }
       });

       if (totalValue > 0) {
         snapshot.holdings.forEach((h: any) => {
           if (h.symbol !== 'CUR:USD') {
               holdingsMap[h.symbol] = (h.quantity * h.current_price) / totalValue;
           }
         });
       }

       setCurrentHoldings(holdingsMap);

       if (snapshot.holdings.length > 0) {
         // Filter out cash from optimizer
         const validSymbols = snapshot.holdings
            .filter((h: any) => h.symbol !== 'CUR:USD')
            .map((h: any) => h.symbol);
            
         if (validSymbols.length > 0) {
             setCustomSymbols(validSymbols);
             setPortfolioType('custom'); 
         }
       }
    }
  }, [snapshot]);

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
         timeout: 10000
      });

      if (response.ok) {
        const data = await response.json();
        setSnapshot(data);
      }
    } catch (err) {
      console.error('Failed to load snapshot:', err);
    }
  };

  const loadWeeklyScout = async () => {
    setScoutLoading(true);
    setScoutError(null);
    try {
      const headers = await getAuthHeaders();
      const response = await fetchWithTimeout(`${API_URL}/scout/weekly`, {
        headers,
        timeout: 20000
      });

      if (response.ok) {
        const data = await response.json();
        setWeeklyScout(data);
      } else {
        setScoutError(`Failed to load data`);
      }
    } catch (err: any) {
      setScoutError('Unable to connect');
    } finally {
      setScoutLoading(false);
    }
  };

  const loadJournalStats = async () => {
    setJournalLoading(true);
    setJournalError(null);
    try {
      const headers = await getAuthHeaders();
      const response = await fetchWithTimeout(`${API_URL}/journal/stats`, { 
          headers,
          timeout: 10000 
      });
      
      if (response.ok) {
        const data = await response.json();
        setJournalStats(data);
      } else {
        setJournalError(`Failed to load stats`);
      }
    } catch (err: any) {
      setJournalError('Unable to connect');
    } finally {
      setJournalLoading(false);
    }
  };

  const getSymbols = useCallback(() => {
    if (portfolioType === 'custom') {
      if (!customSymbols || customSymbols.length === 0) {
          return PORTFOLIO_PRESETS.broad_market.symbols;
      }
      return customSymbols;
    }
    return PORTFOLIO_PRESETS[portfolioType as keyof typeof PORTFOLIO_PRESETS].symbols;
  }, [portfolioType, customSymbols]);

  const runOptimization = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const headers = await getAuthHeaders();
      const symbols = getSymbols();
      const response = await fetchWithTimeout(`${API_URL}/compare/real`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          symbols: symbols,
          risk_aversion: riskAversion
        }),
        timeout: 45000 
      });
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Optimization failed');
      }
      
      const data = await response.json();
      setOptimizationResults(data);
      
    } catch (err: any) {
      setError(err.message || 'Timed out or failed');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (showQuantum && !optimizationResults && !loading) {
      runOptimization();
    }
  }, [showQuantum]);

  useEffect(() => {
    if (showQuantum && !loading && optimizationResults) {
       setOptimizationResults(null);
       runOptimization();
    }
  }, [portfolioType, riskAversion]);

  useEffect(() => {
    const saved = localStorage.getItem('user_settings');
    if (saved) {
      const settings = JSON.parse(saved);
      setShowQuantum(settings.quantum_mode || false);
    }
  }, []);

  const calculateDrift = () => {
    if (!optimizationResults) return null;
    const optimal = optimizationResults.mean_variance.weights;
    const symbols = getSymbols();
    let totalDrift = 0;
    const drifts: {[key: string]: number} = {};
    
    symbols.forEach(symbol => {
      const current = currentHoldings[symbol] || 0;
      const target = optimal[symbol] || 0;
      const drift = target - current;
      drifts[symbol] = drift;
      totalDrift += Math.abs(drift);
    });
    
    return {
      total: totalDrift,
      bySymbol: drifts,
      needsRebalance: totalDrift > 0.10
    };
  };

  const drift = calculateDrift();

  // --- RENDER HELPERS ---
  const renderPositionRow = (position: any, idx: number, type: 'option' | 'stock') => {
      const cost = position.cost_basis * position.quantity;
      const value = position.current_price * position.quantity;
      const pnl = value - cost;
      const pnlPercent = position.cost_basis > 0 ? (pnl / cost) * 100 : 0;

      return (
        <tr key={`${type}-${idx}`} className="hover:bg-gray-50">
            <td className={`px-6 py-4 font-medium ${type === 'option' ? 'text-purple-600' : 'text-gray-900'}`}>
                {position.symbol}
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
                {type === 'option' && pnlPercent >= 50 && (
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
        
        {/* SECTION 1: POSITIONS & OPTIMIZER (Moved to Top) */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <div className="bg-white rounded-lg shadow overflow-hidden">
              <div className="px-6 py-4 border-b flex justify-between items-center">
                <h2 className="text-xl font-semibold">Positions</h2>
                <SyncHoldingsButton onSyncComplete={loadSnapshot} />
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
                            {/* OPTIONS */}
                            {snapshot.holdings.some((h:any) => h.symbol.length > 6 && h.symbol !== 'CUR:USD') && (
                                <tr className="bg-purple-50">
                                    <td colSpan={5} className="px-6 py-2 text-xs font-bold text-purple-800 uppercase">🎯 Option Plays</td>
                                </tr>
                            )}
                            {snapshot.holdings
                                .filter((h:any) => h.symbol.length > 6 && h.symbol !== 'CUR:USD')
                                .map((h:any, idx:number) => renderPositionRow(h, idx, 'option'))
                            }

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
          <div>
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">Portfolio Optimizer</h3>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={showQuantum}
                    onChange={(e) => {
                      const enabled = e.target.checked;
                      setShowQuantum(enabled);
                      const settings = JSON.parse(localStorage.getItem('user_settings') || '{}');
                      settings.quantum_mode = enabled;
                      localStorage.setItem('user_settings', JSON.stringify(settings));
                    }}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                </label>
              </div>

              {!showQuantum ? (
                <div className="space-y-3">
                  <p className="text-gray-600 text-sm">Enable optimizer to analyze portfolios</p>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-2">Portfolio Type</label>
                    <select
                      value={portfolioType}
                      onChange={(e) => setPortfolioType(e.target.value)}
                      className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      {Object.entries(PORTFOLIO_PRESETS).map(([key, preset]) => (
                        <option key={key} value={key}>{preset.name}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-2">
                      Risk: {riskAversion === 1 ? 'Aggressive' : riskAversion === 2 ? 'Moderate' : 'Conservative'}
                    </label>
                    <input
                      type="range" min="1" max="3" step="0.5"
                      value={riskAversion}
                      onChange={(e) => setRiskAversion(parseFloat(e.target.value))}
                      className="w-full"
                    />
                  </div>
                </div>
              ) : loading ? (
                <div className="text-center py-8">
                  <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
                  <p className="mt-4 text-sm text-gray-600">Optimizing...</p>
                </div>
              ) : optimizationResults ? (
                <div className="space-y-4">
                  {/* Optimizer Results UI */}
                  <div className="bg-blue-50 p-4 rounded border border-blue-200">
                    <p className="text-sm font-medium text-blue-900 mb-3">Mean-Variance (MV)</p>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-blue-700">Sharpe:</span>
                        <span className="font-bold text-blue-900">{optimizationResults.mean_variance.sharpe_est.toFixed(3)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-blue-700">Return:</span>
                        <span className="font-bold text-blue-900">{(optimizationResults.mean_variance.portfolio_return * 100).toFixed(2)}%</span>
                      </div>
                    </div>
                  </div>
                  <button onClick={runOptimization} disabled={loading} className="w-full py-2 px-4 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700">Recompute</button>
                </div>
              ) : null}
            </div>
          </div>
        </div>

        {/* SECTION 2: SCOUT & JOURNAL (Moved Below) */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Weekly Options Scout */}
            <div className="bg-gradient-to-r from-green-50 to-emerald-50 rounded-lg shadow p-6 border-l-4 border-green-500">
                <div className="flex justify-between items-start mb-4">
                    <h3 className="text-lg font-semibold text-green-900 flex items-center gap-2">🎯 Weekly Options Scout</h3>
                    <button onClick={loadWeeklyScout} className="text-sm text-green-700 underline">Refresh</button>
                </div>
                {scoutLoading && <div className="py-4 text-center text-sm animate-pulse">Scanning...</div>}
                {weeklyScout?.top_picks && (
                    <div className="space-y-3">
                    {weeklyScout.top_picks.slice(0, 3).map((opp: any, idx: number) => (
                        <div key={idx} className="bg-white rounded-lg p-4 border border-green-200">
                            <div className="flex justify-between items-start mb-2">
                                <span className="text-lg font-bold text-gray-900">#{idx + 1} {opp.symbol}</span>
                                <span className="text-sm font-medium">${opp.credit.toFixed(2)} credit</span>
                            </div>
                            <p className="text-sm text-gray-600">{opp.type} • IV Rank: {(opp.iv_rank * 100).toFixed(0)}%</p>
                        </div>
                    ))}
                    </div>
                )}
            </div>

            {/* Trade Journal Stats */}
            <div className="bg-gradient-to-r from-purple-50 to-pink-50 rounded-lg shadow p-6 border-l-4 border-purple-500">
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
