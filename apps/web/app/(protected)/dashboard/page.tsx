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

// Helper to prevent hanging indefinitely
const fetchWithTimeout = async (resource: RequestInfo, options: FetchOptions = {}) => {
  const { timeout = 15000, ...rest } = options; // 15s timeout default

  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);

  const response = await fetch(resource, {
    ...rest,
    signal: controller.signal
  });

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
         const value = h.quantity * h.current_price;
         totalValue += value;
       });

       if (totalValue > 0) {
         snapshot.holdings.forEach((h: any) => {
           holdingsMap[h.symbol] = (h.quantity * h.current_price) / totalValue;
         });
       }

       setCurrentHoldings(holdingsMap);

       if (snapshot.holdings.length > 0) {
         setCustomSymbols(snapshot.holdings.map((h: any) => h.symbol));
         // Automatically switch to Custom view if we have real holdings
         setPortfolioType('custom'); 
       }
    }
  }, [snapshot]);

  const loadSnapshot = async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      
      const headers: Record<string, string> = {
          'Content-Type': 'application/json'
      };

      if (session) {
          headers['Authorization'] = `Bearer ${session.access_token}`;
      } else {
          // 🛠️ FIX: Pass Test User ID if not logged in
          headers['X-Test-Mode-User'] = TEST_USER_ID;
      }

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
      const { data: { session } } = await supabase.auth.getSession();
      
      const headers: Record<string, string> = {
          'Content-Type': 'application/json'
      };

      if (session) {
        headers['Authorization'] = `Bearer ${session.access_token}`;
      } else {
         headers['X-Test-Mode-User'] = TEST_USER_ID;
      }

      const response = await fetchWithTimeout(`${API_URL}/scout/weekly`, {
        headers: headers,
        timeout: 20000
      });

      if (response.ok) {
        const data = await response.json();
        setWeeklyScout(data);
      } else {
        setScoutError(`Failed to load data`);
        console.error('Scout failed:', response.statusText);
      }
    } catch (err: any) {
      setScoutError('Unable to connect');
      console.error('Failed to load scout:', err);
    } finally {
      setScoutLoading(false);
    }
  };

  const loadJournalStats = async () => {
    setJournalLoading(true);
    setJournalError(null);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      const headers: Record<string, string> = {
          'Content-Type': 'application/json'
      };
      // Note: Journal endpoint might not need auth in current API implementation, 
      // but good practice to pass it if user specific
      if (session) {
        headers['Authorization'] = `Bearer ${session.access_token}`;
      }

      const response = await fetchWithTimeout(`${API_URL}/journal/stats`, { 
          headers,
          timeout: 10000 
      });
      
      if (response.ok) {
        const data = await response.json();
        setJournalStats(data);
      } else {
        setJournalError(`Failed to load stats`);
        console.error('Journal failed:', response.statusText);
      }
    } catch (err: any) {
      setJournalError('Unable to connect');
      console.error('Failed to load journal:', err);
    } finally {
      setJournalLoading(false);
    }
  };

  const getSymbols = useCallback(() => {
    if (portfolioType === 'custom') {
      // Ensure we have valid symbols, fallback to defaults if empty
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
      const { data: { session } } = await supabase.auth.getSession();
      const headers: any = { 'Content-Type': 'application/json' };
      
      if (session) {
        headers['Authorization'] = `Bearer ${session.access_token}`;
      } else {
         headers['X-Test-Mode-User'] = TEST_USER_ID;
      }

      const symbols = getSymbols();
      const response = await fetchWithTimeout(`${API_URL}/compare/real`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          symbols: symbols,
          risk_aversion: riskAversion
        }),
        timeout: 45000 // Long timeout for optimization
      });
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Optimization failed');
      }
      
      const data = await response.json();
      setOptimizationResults(data);
      
    } catch (err: any) {
      setError(err.message || 'Timed out or failed');
      console.error('Optimization error:', err);
    } finally {
      setLoading(false);
    }
  };

  // Trigger initial optimization when enabling quantum mode
  useEffect(() => {
    if (showQuantum && !optimizationResults && !loading) {
      runOptimization();
    }
  }, [showQuantum]);

  // Re-run when inputs change
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

  return (
    <DashboardLayout mockAlerts={mockAlerts}>
      <div className="max-w-7xl mx-auto p-8 space-y-6">
        {/* 1. Positions + Optimizer at top */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            {/* Positions table card */}
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
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Current Value</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P&amp;L</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {/* 1. OPTIONS PLAYS */}
                    {snapshot?.holdings?.filter((h:any) => h.symbol.length > 6 && h.symbol !== 'CUR:USD').length > 0 && (
                      <tr className="bg-purple-50">
                        <td colSpan={5} className="px-6 py-2 text-xs font-bold text-purple-800 uppercase tracking-wider">
                          🎯 Option Plays
                        </td>
                      </tr>
                    )}
                    {snapshot?.holdings?.filter((h:any) => h.symbol.length > 6 && h.symbol !== 'CUR:USD').map((position: any, idx: number) => {
                      const cost = position.cost_basis * position.quantity;
                      const value = position.current_price * position.quantity;
                      const pnl = value - cost;
                      const pnlPercent = position.cost_basis > 0 ? (pnl / cost) * 100 : 0;

                      return (
                        <tr key={idx} className="hover:bg-gray-50">
                          <td className="px-6 py-4 font-medium text-purple-600">{position.symbol}</td>
                          <td className="px-6 py-4">{position.quantity}</td>
                          <td className="px-6 py-4 whitespace-nowrap font-medium">
                            ${position.cost_basis?.toFixed(2)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div>${position.current_price?.toFixed(2)}</div>
                            <div className="text-xs text-gray-400">Total: ${value.toFixed(0)}</div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className={`font-bold ${pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                              {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)} ({pnlPercent.toFixed(1)}%)
                            </div>
                            {pnlPercent >= 50 && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800 animate-pulse">
                                TARGET HIT 🎯
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}

                    {/* 2. STOCK HOLDINGS */}
                    {snapshot?.holdings?.filter((h:any) => h.symbol.length <= 6 && h.symbol !== 'CUR:USD').length > 0 && (
                      <tr className="bg-blue-50">
                        <td colSpan={5} className="px-6 py-2 text-xs font-bold text-blue-800 uppercase tracking-wider">
                          📈 Long Term Holds
                        </td>
                      </tr>
                    )}
                    {snapshot?.holdings?.filter((h:any) => h.symbol.length <= 6 && h.symbol !== 'CUR:USD').map((position: any, idx: number) => {
                      const cost = position.cost_basis * position.quantity;
                      const value = position.current_price * position.quantity;
                      const pnl = value - cost;
                      const pnlPercent = position.cost_basis > 0 ? (pnl / cost) * 100 : 0;

                      return (
                        <tr key={idx} className="hover:bg-gray-50">
                          <td className="px-6 py-4 font-medium">{position.symbol}</td>
                          <td className="px-6 py-4">{position.quantity}</td>
                          <td className="px-6 py-4 whitespace-nowrap font-medium">
                            ${position.cost_basis?.toFixed(2)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div>${position.current_price?.toFixed(2)}</div>
                            <div className="text-xs text-gray-400">Total: ${value.toFixed(0)}</div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className={`font-bold ${pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                              {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)} ({pnlPercent.toFixed(1)}%)
                            </div>
                            {pnlPercent >= 50 && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800 animate-pulse">
                                TARGET HIT 🎯
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}

                    {/* 3. CASH */}
                    {snapshot?.holdings?.filter((h:any) => h.symbol === 'CUR:USD').map((position: any, idx: number) => (
                      <tr key={`cash-${idx}`} className="bg-green-50 border-t-2 border-green-100">
                          <td className="px-6 py-4 font-bold text-green-800">💵 CASH</td>
                          <td className="px-6 py-4 text-green-800">---</td>
                          <td className="px-6 py-4 text-green-800">---</td>
                          <td className="px-6 py-4 font-bold text-green-800">${position.quantity?.toFixed(2)}</td>
                          <td className="px-6 py-4"><span className="text-xs bg-green-200 text-green-800 px-2 py-1 rounded">Sweep</span></td>
                      </tr>
                    ))}

                    {(!snapshot?.holdings || snapshot?.holdings?.length === 0) && (
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
          <div>
            {/* Portfolio Optimizer sidebar card */}
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
                  <p className="text-gray-600 text-sm">
                    Enable optimizer to analyze portfolios
                  </p>
                  
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-2">
                      Portfolio Type
                    </label>
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
                      type="range"
                      min="1"
                      max="3"
                      step="0.5"
                      value={riskAversion}
                      onChange={(e) => setRiskAversion(parseFloat(e.target.value))}
                      className="w-full"
                    />
                    <div className="flex justify-between text-xs text-gray-500">
                      <span>Aggressive</span>
                      <span>Conservative</span>
                    </div>
                  </div>
                </div>
              ) : loading ? (
                <div className="text-center py-8">
                  <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
                  <p className="mt-4 text-sm text-gray-600">Optimizing...</p>
                </div>
              ) : error ? (
                <div className="bg-red-50 border border-red-200 rounded p-4">
                  <p className="text-sm text-red-600 font-medium mb-2">Error</p>
                  <p className="text-xs text-red-600">{error}</p>
                  <button
                    onClick={runOptimization}
                    className="mt-3 text-xs text-red-700 underline hover:text-red-900"
                  >
                    Retry
                  </button>
                </div>
              ) : optimizationResults ? (
                <div className="space-y-4">
                  {optimizationResults.data_source && (
                    <div className="bg-green-50 border border-green-200 rounded p-3">
                      <div className="flex items-center gap-2">
                        <svg className="w-4 h-4 text-green-600" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                        </svg>
                        <span className="text-xs font-medium text-green-800">
                          {PORTFOLIO_PRESETS[portfolioType as keyof typeof PORTFOLIO_PRESETS].name} • {optimizationResults.data_points} days
                        </span>
                      </div>
                    </div>
                  )}

                  {drift && drift.needsRebalance && (
                    <div className="bg-yellow-50 border border-yellow-200 rounded p-3">
                      <div className="flex items-center gap-2">
                        <svg className="w-4 h-4 text-yellow-600" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                        </svg>
                        <span className="text-xs font-medium text-yellow-800">
                          Drift: {(drift.total * 100).toFixed(1)}% - Rebalance needed
                        </span>
                      </div>
                    </div>
                  )}

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
                      <div className="flex justify-between">
                        <span className="text-blue-700">Vol:</span>
                        <span className="font-bold text-blue-900">{(optimizationResults.mean_variance.portfolio_std * 100).toFixed(2)}%</span>
                      </div>
                    </div>
                  </div>

                  <div className="bg-purple-50 p-4 rounded border border-purple-200">
                    <p className="text-sm font-medium text-purple-900 mb-3">Mean-Variance-Skew (MVS)</p>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-purple-700">Sharpe:</span>
                        <span className="font-bold text-purple-900">{optimizationResults.mean_variance_skew.sharpe_est.toFixed(3)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-purple-700">Return:</span>
                        <span className="font-bold text-purple-900">{(optimizationResults.mean_variance_skew.portfolio_return * 100).toFixed(2)}%</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-purple-700">Vol:</span>
                        <span className="font-bold text-purple-900">{(optimizationResults.mean_variance_skew.portfolio_std * 100).toFixed(2)}%</span>
                      </div>
                    </div>
                  </div>

                  <details className="text-xs" open>
                    <summary className="cursor-pointer text-gray-700 hover:text-gray-900 font-medium mb-2 select-none">
                      ▼ Allocations
                    </summary>
                    <div className="bg-gray-50 p-3 rounded space-y-3 mt-2">
                      {Object.entries(optimizationResults.mean_variance.weights).map(([asset, weight]: any) => {
                        const current = currentHoldings[asset] || 0;
                        const change = weight - current;
                        return (
                          <div key={asset}>
                            <div className="flex justify-between items-center mb-1">
                              <span className="font-medium">{asset}:</span>
                              <div className="flex items-center gap-2">
                                <span className="text-gray-500">{(current * 100).toFixed(1)}%</span>
                                <span>→</span>
                                <span className="font-bold">{(weight * 100).toFixed(1)}%</span>
                                {Math.abs(change) > 0.01 && (
                                  <span className={`text-xs ${change > 0 ? 'text-green-600' : 'text-red-600'}`}>
                                    ({change > 0 ? '+' : ''}{(change * 100).toFixed(1)}%)
                                  </span>
                                )}
                              </div>
                            </div>
                            <div className="w-full bg-gray-200 rounded-full h-2">
                              <div
                                className="h-2 rounded-full bg-blue-500"
                                style={{ width: `${weight * 100}%` }}
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </details>

                  <button
                    onClick={runOptimization}
                    disabled={loading}
                    className="w-full py-2 px-4 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:bg-gray-400"
                  >
                    Recompute
                  </button>

                  <p className="text-xs text-gray-500 text-center">
                    📊 Real Data • {riskAversion === 1 ? 'Aggressive' : riskAversion === 2 ? 'Moderate' : 'Conservative'}
                  </p>
                </div>
              ) : null}
            </div>
          </div>
        </div>

        {/* 2. Weekly Scout + Journal BELOW */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Weekly Options Scout component */}
          <div className="bg-gradient-to-r from-green-50 to-emerald-50 rounded-lg shadow p-6 border-l-4 border-green-500">
            <div className="flex justify-between items-start mb-4">
              <div>
                <h3 className="text-lg font-semibold text-green-900 flex items-center gap-2">
                  🎯 Weekly Options Scout
                  <span className="text-xs font-normal bg-green-200 text-green-800 px-2 py-1 rounded">
                    AUTO-UPDATED
                  </span>
                </h3>
                <p className="text-sm text-green-700 mt-1">
                  Top credit spread opportunities based on IV rank, delta, and risk/reward
                </p>
              </div>
              <button
                onClick={loadWeeklyScout}
                disabled={scoutLoading}
                className="text-sm text-green-700 hover:text-green-900 underline disabled:opacity-50"
              >
                {scoutLoading ? 'Loading...' : 'Refresh'}
              </button>
            </div>

            {scoutError && (
              <div className="bg-red-50 p-3 rounded border border-red-200 mb-3 text-sm text-red-600 flex justify-between items-center">
                <span>{scoutError}</span>
                <button onClick={loadWeeklyScout} className="underline hover:text-red-800">Retry</button>
              </div>
            )}

            {scoutLoading && !weeklyScout && (
                <div className="py-4 text-center text-green-800 text-sm animate-pulse">
                    Scanning market data...
                </div>
            )}

            {!scoutLoading && weeklyScout && weeklyScout.top_picks && (
              <div className="space-y-3">
                {weeklyScout.top_picks.slice(0, 3).map((idea: any, idx: number) => (
                  <ScoutIdea key={idx} idea={idea} />
                ))}
              </div>
            )}
          </div>
          {/* Trade Journal component */}
          <div className="bg-gradient-to-r from-purple-50 to-pink-50 rounded-lg shadow p-6 border-l-4 border-purple-500">
            <div className="flex justify-between items-start mb-4">
              <div>
                <h3 className="text-lg font-semibold text-purple-900 flex items-center gap-2">
                  📊 Trade Journal
                  <span className="text-xs font-normal bg-purple-200 text-purple-800 px-2 py-1 rounded">
                    AUTO-LEARNING
                  </span>
                </h3>
                <p className="text-sm text-purple-700 mt-1">
                  System learns from every trade and generates rules
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setShowJournal(!showJournal)}
                  className="text-sm text-purple-700 hover:text-purple-900 underline"
                >
                  {showJournal ? 'Hide Details' : 'Show Details'}
                </button>
                <button
                  onClick={loadJournalStats}
                  disabled={journalLoading}
                  className="text-sm text-purple-700 hover:text-purple-900 underline disabled:opacity-50"
                >
                  {journalLoading ? 'Loading...' : 'Refresh'}
                </button>
              </div>
            </div>

            {journalError && (
               <div className="bg-red-50 p-3 rounded border border-red-200 mb-3 text-sm text-red-600 flex justify-between items-center">
                 <span>{journalError}</span>
                 <button onClick={loadJournalStats} className="underline hover:text-red-800">Retry</button>
               </div>
            )}

            {journalLoading && !journalStats && (
                <div className="py-4 text-center text-purple-800 text-sm animate-pulse">
                    Analyzing trade patterns...
                </div>
            )}

            {journalStats && (
              <div className="space-y-4">
                {/* Stats Summary */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="bg-white rounded-lg p-3 border border-purple-200">
                    <p className="text-xs text-gray-600">Win Rate</p>
                    <p className="text-2xl font-bold text-purple-900">
                      {journalStats.stats.win_rate?.toFixed(1) || 0}%
                    </p>
                  </div>
                  <div className="bg-white rounded-lg p-3 border border-purple-200">
                    <p className="text-xs text-gray-600">Total Trades</p>
                    <p className="text-2xl font-bold text-purple-900">
                      {journalStats.stats.closed_trades || 0}
                    </p>
                  </div>
                  <div className="bg-white rounded-lg p-3 border border-purple-200">
                    <p className="text-xs text-gray-600">Total P&L</p>
                    <p className={`text-2xl font-bold ${(journalStats.stats.total_pnl || 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      ${(journalStats.stats.total_pnl || 0).toFixed(0)}
                    </p>
                  </div>
                  <div className="bg-white rounded-lg p-3 border border-purple-200">
                    <p className="text-xs text-gray-600">Avg P&L</p>
                    <p className={`text-2xl font-bold ${(journalStats.stats.avg_pnl || 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      ${(journalStats.stats.avg_pnl || 0).toFixed(0)}
                    </p>
                  </div>
                </div>

                {/* Auto-Generated Rules */}
                {journalStats.rules && journalStats.rules.length > 0 && (
                  <div className="bg-white rounded-lg p-4 border border-purple-200">
                    <p className="text-sm font-semibold text-purple-900 mb-2">🤖 Auto-Generated Rules:</p>
                    <div className="space-y-1">
                      {journalStats.rules.map((rule: string, i: number) => (
                        <p key={i} className="text-sm text-gray-700">{rule}</p>
                      ))}
                    </div>
                  </div>
                )}

                {/* Detailed Analysis */}
                {showJournal && journalStats.patterns && (
                  <div className="bg-white rounded-lg p-4 border border-purple-200">
                    <p className="text-sm font-semibold text-purple-900 mb-3">Pattern Analysis:</p>
                    {Object.entries(journalStats.patterns).map(([strategy, stats]: any) => {
                      if (strategy === 'iv_rank_analysis') return null;
                      return (
                        <div key={strategy} className="mb-3 pb-3 border-b last:border-b-0">
                          <p className="text-sm font-medium text-gray-900">{strategy}</p>
                          <div className="grid grid-cols-3 gap-2 mt-2 text-xs">
                            <div>
                              <span className="text-gray-600">Win Rate:</span>
                              <span className="font-medium ml-1">{stats.win_rate?.toFixed(1)}%</span>
                            </div>
                            <div>
                              <span className="text-gray-600">Trades:</span>
                              <span className="font-medium ml-1">{stats.wins + stats.losses}</span>
                            </div>
                            <div>
                              <span className="text-gray-600">P&L:</span>
                              <span className={`font-medium ml-1 ${stats.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                                ${stats.total_pnl?.toFixed(0)}
                              </span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {!journalStats && !journalLoading && !journalError && (
              <div className="text-center py-8 text-purple-700">
                <p className="text-sm">No trades yet. Start logging your trades to see auto-learning in action!</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
