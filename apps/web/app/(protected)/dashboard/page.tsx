'use client';

import { useState, useEffect } from 'react';
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

       // If we have holdings, switch to "Custom" or specific logic to use them in optimizer
       // For now, let's just default to "broad_market" or update custom symbols
       if (snapshot.holdings.length > 0) {
         setCustomSymbols(snapshot.holdings.map((h: any) => h.symbol));
         // setPortfolioType('custom'); // Optional: auto-switch
       }
    }
  }, [snapshot]);

  const loadSnapshot = async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const response = await fetch(`${API_URL}/portfolio/snapshot`, {
         headers: { 'Authorization': `Bearer ${session.access_token}` }
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
      const response = await fetch(`${API_URL}/scout/weekly`);
      if (response.ok) {
        const data = await response.json();
        setWeeklyScout(data);
      } else {
        setScoutError(`Failed to load data: ${response.statusText}`);
        console.error('Scout failed:', response.statusText);
      }
    } catch (err: any) {
      setScoutError('Failed to connect to server');
      console.error('Failed to load scout:', err);
    } finally {
      setScoutLoading(false);
    }
  };

  const loadJournalStats = async () => {
    setJournalLoading(true);
    setJournalError(null);
    try {
      const response = await fetch(`${API_URL}/journal/stats`);
      if (response.ok) {
        const data = await response.json();
        setJournalStats(data);
      } else {
        setJournalError(`Failed to load stats: ${response.statusText}`);
        console.error('Journal failed:', response.statusText);
      }
    } catch (err: any) {
      setJournalError('Failed to connect to server');
      console.error('Failed to load journal:', err);
    } finally {
      setJournalLoading(false);
    }
  };

  const getSymbols = () => {
    if (portfolioType === 'custom') {
      return customSymbols;
    }
    return PORTFOLIO_PRESETS[portfolioType as keyof typeof PORTFOLIO_PRESETS].symbols;
  };

  const runOptimization = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const symbols = getSymbols();
      const response = await fetch(`${API_URL}/compare/real`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbols: symbols,
          risk_aversion: riskAversion
        })
      });
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Optimization failed');
      }
      
      const data = await response.json();
      setOptimizationResults(data);
      
    } catch (err: any) {
      setError(err.message || 'Unknown error');
      console.error('Optimization error:', err);
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
    if (showQuantum && !loading) {
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
        {/* Weekly Options Scout */}
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
            <div className="bg-red-50 p-3 rounded border border-red-200 mb-3 text-sm text-red-600">
              {scoutError}
            </div>
          )}

          {weeklyScout && weeklyScout.top_picks && (
            <div className="space-y-3">
              {weeklyScout.top_picks.slice(0, 3).map((opp: any, idx: number) => (
                <div key={idx} className="bg-white rounded-lg p-4 border border-green-200">
                  <div className="flex justify-between items-start mb-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-lg font-bold text-gray-900">#{idx + 1} {opp.symbol}</span>
                        <span className="text-xs bg-green-100 text-green-800 px-2 py-1 rounded font-medium">
                          Score: {opp.score}/100
                        </span>
                      </div>
                      <p className="text-sm text-gray-600 mt-1">{opp.type}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-medium text-gray-900">${opp.credit.toFixed(2)} credit</p>
                      <p className="text-xs text-gray-600">{opp.risk_reward}</p>
                    </div>
                  </div>
                  
                  <div className="grid grid-cols-3 gap-2 text-xs mt-3 mb-3">
                    <div>
                      <span className="text-gray-600">Strikes:</span>
                      <span className="font-medium ml-1">{opp.short_strike}/{opp.long_strike}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">DTE:</span>
                      <span className="font-medium ml-1">{opp.dte}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">IV Rank:</span>
                      <span className="font-medium ml-1">{(opp.iv_rank * 100).toFixed(0)}%</span>
                    </div>
                  </div>

                  <div className="border-t pt-2">
                    <p className="text-xs text-gray-600 mb-1 font-medium">Why this trade:</p>
                    {opp.reasons.slice(0, 2).map((reason: string, i: number) => (
                      <p key={i} className="text-xs text-gray-700">• {reason}</p>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Trade Journal Stats */}
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
             <div className="bg-red-50 p-3 rounded border border-red-200 mb-3 text-sm text-red-600">
               {journalError}
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

          {!journalStats && !journalLoading && (
            <div className="text-center py-8 text-purple-700">
              <p className="text-sm">No trades yet. Start logging your trades to see auto-learning in action!</p>
            </div>
          )}
        </div>

        {/* Existing sections... */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold mb-4">Portfolio Risk</h3>
          <div className="space-y-4">
            {/* If we have metrics from snapshot, use them. Else use placeholder or nothing */}
            {/* Since snapshot.risk_metrics might be simple, let's just show what we have */}

            {snapshot ? (
              <div>
                <div className="flex justify-between mb-2">
                  <span className="text-sm font-medium">Last Updated</span>
                  <span className="text-sm font-medium">
                    {new Date(snapshot.created_at).toLocaleString()}
                  </span>
                </div>
                {/* Placeholder for real metrics if available in snapshot */}
                 <p className="text-sm text-gray-500">
                   {snapshot.holdings.length} positions tracked.
                 </p>
              </div>
            ) : (
               <p className="text-sm text-gray-500">Sync your portfolio to see risk metrics.</p>
            )}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold mb-4">Recent Alerts</h3>
          <div className="space-y-3">
            {mockAlerts.map((alert) => (
              <div key={alert.id} className="flex items-start gap-3 p-3 bg-blue-50 rounded-lg">
                <svg className="w-5 h-5 text-blue-600 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M10 2a6 6 0 00-6 6v3.586l-.707.707A1 1 0 004 14h12a1 1 0 00.707-1.707L16 11.586V8a6 6 0 00-6-6z" />
                </svg>
                <div className="flex-1">
                  <p className="text-sm font-medium text-gray-900">{alert.message}</p>
                  <p className="text-xs text-gray-500 mt-1">{alert.time}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

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
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {snapshot?.holdings?.length > 0 ? (
                      snapshot.holdings.map((position: any, idx: number) => (
                        <tr key={idx} className="hover:bg-gray-50">
                          <td className="px-6 py-4 whitespace-nowrap font-medium">{position.symbol}</td>
                          <td className="px-6 py-4 whitespace-nowrap">{position.quantity}</td>
                          <td className="px-6 py-4 whitespace-nowrap">${position.cost_basis?.toFixed(2) || '-'}</td>
                          <td className="px-6 py-4 whitespace-nowrap">${position.current_price?.toFixed(2) || '-'}</td>
                          <td className="px-6 py-4 whitespace-nowrap">
                             <span className={`px-2 py-1 rounded text-xs ${position.source === 'plaid' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                               {position.source}
                             </span>
                          </td>
                        </tr>
                      ))
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
      </div>
    </DashboardLayout>
  );
}
