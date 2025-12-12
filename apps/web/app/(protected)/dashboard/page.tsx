'use client';

import { useState, useEffect } from 'react';
import DashboardLayout from '@/components/DashboardLayout';
import DashboardOnboarding from '@/components/dashboard/DashboardOnboarding';
import SyncHoldingsButton from '@/components/SyncHoldingsButton';
import PortfolioOptimizer from '@/components/dashboard/PortfolioOptimizer';
import { WeeklyProgressCard } from '@/components/dashboard/WeeklyProgressCard';
import SuggestionTabs from '@/components/dashboard/SuggestionTabs';
import StrategyProfilesPanel from '@/components/dashboard/StrategyProfilesPanel';
import DisciplineSummary from '@/components/dashboard/DisciplineSummary';
import RiskSummaryCard from '@/components/dashboard/RiskSummaryCard';
import HoldingsTreemap from '@/components/dashboard/HoldingsTreemap';
import OptimizerInsightCard from '@/components/dashboard/OptimizerInsightCard';
import PortfolioHoldingsTable from '@/components/dashboard/PortfolioHoldingsTable'; // Phase 8.4
import PaperPortfolioWidget from '@/components/dashboard/PaperPortfolioWidget';
import { supabase } from '@/lib/supabase';
import { API_URL, TEST_USER_ID } from '@/lib/constants';
import { groupOptionSpreads, formatOptionDisplay } from '@/lib/formatters';
import { QuantumTooltip } from "@/components/ui/QuantumTooltip";
import { ThemeToggle } from '@/components/ThemeToggle';
import { AlertTriangle, AlertCircle, Activity, Wallet } from 'lucide-react';

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
  const [riskData, setRiskData] = useState<any>(null); // Phase 8.2 Risk Dashboard

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
  const [simMode, setSimMode] = useState<'deterministic' | 'random'>('deterministic');

  // Load data on mount
  useEffect(() => {
    loadSnapshot();
    loadRiskDashboard(); // Phase 8.2
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

  const loadRiskDashboard = async () => {
    try {
      const headers = await getAuthHeaders();
      const response = await fetchWithTimeout(`${API_URL}/risk/dashboard`, {
         headers,
         timeout: 10000
      });
      if (response.ok) {
         setRiskData(await response.json());
      }
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load risk dashboard:', err);
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
      const payload: any = { mode: simMode };
      if (simMode === 'deterministic') {
          payload.cursor = simCursor;
          payload.symbol = 'SPY';
      } else {
          // In random mode, cursor and symbol are optional (server chooses)
          // But API schema requires cursor. We can send a dummy or the current one.
          // run_historical_cycle body: cursor=..., symbol=..., mode=...
          // If random, the server overrides date. But we should send something valid.
          payload.cursor = simCursor;
          // symbol omitted -> server chooses random if configured
      }

      const res = await fetch(`${API_URL}/historical/run-cycle`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const data = await res.json();
        setSimResult(data);
        if (data.nextCursor) {
            setSimCursor(data.nextCursor);
        }
        // If random mode, we might want to update the displayed cursor/symbol to what was actually used
        if (data.entryTime) {
            // Optional: update simCursor to match what was chosen?
            // setSimCursor(data.entryTime);
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

  // --- DERIVED STATE ---

  // Use snapshot risk metrics if available
  const riskMetrics = snapshot?.risk_metrics || {};
  const greeks = riskMetrics.greeks || {};
  const greekAlerts = riskMetrics.greek_alerts || {};

  const hasPositions =
    Array.isArray(snapshot?.positions ?? snapshot?.holdings) &&
    (snapshot?.positions ?? snapshot?.holdings)?.length > 0;

  return (
    <DashboardLayout mockAlerts={mockAlerts}>
      <div className="max-w-7xl mx-auto p-8 space-y-6">

        {/* DASHBOARD TITLE */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Dashboard</h1>
            <QuantumTooltip
              content="Your command center for portfolio insights, AI-driven suggestions, and risk tracking."
            />
          </div>
          <ThemeToggle />
        </div>

        <DashboardOnboarding
          hasPositions={hasPositions}
          onSyncComplete={loadSnapshot}
        />
        
        {/* SECTION 0: WEEKLY SCOUT / PROGRESS */}
        <div>
          <div className="flex items-center gap-2 mb-2">
             <h2 className="text-xl font-semibold">Weekly Scout</h2>
             <QuantumTooltip
               label="Regime Analysis"
               content="Analyzes implied volatility and trend to suggest premium-buying or premium-selling bias."
             />
          </div>
          <WeeklyProgressCard />
        </div>

        {/* SECTION 1: POSITIONS & OPTIMIZER */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <div className="bg-white dark:bg-zinc-900 rounded-lg shadow overflow-hidden">
              <div className="px-6 py-4 border-b dark:border-zinc-800 flex justify-between items-center">
                <h2 className="text-xl font-semibold dark:text-gray-100">Positions</h2>
                <div className="flex gap-2">
                  <SyncHoldingsButton onSyncComplete={loadSnapshot} />
                  <a href="/paper" className="text-xs px-3 py-1 flex items-center rounded bg-blue-50 text-blue-700 hover:bg-blue-100 border border-blue-200 dark:bg-blue-900 dark:text-blue-100 dark:border-blue-800">
                     <Wallet className="w-3 h-3 mr-1" /> Paper Portfolio
                  </a>
                  <button
                    onClick={runAllWorkflows}
                    className="text-xs px-3 py-1 rounded border border-purple-200 text-purple-700 hover:bg-purple-50 dark:border-purple-800 dark:text-purple-300 dark:hover:bg-purple-900"
                  >
                    Generate Suggestions (Dev)
                  </button>
                </div>
              </div>
              <PortfolioHoldingsTable
                  holdings={snapshot?.holdings || []}
                  onSync={loadSnapshot}
                  onGenerateSuggestions={runAllWorkflows}
              />
            </div>
          </div>

          {/* OPTIMIZER PANEL */}
          <div className="flex flex-col gap-6">
            <div className="h-[500px]">
               <div className="flex items-center gap-2 mb-2">
                 <h2 className="text-xl font-semibold">Optimizer</h2>
                 <QuantumTooltip
                    label="Quantum-Inspired"
                    content="Uses constrained optimization to balance your portfolio deltas and thetas based on your holdings."
                  />
               </div>
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

        {/* PHASE 8: RISK COCKPIT */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            <RiskSummaryCard
                summary={riskData?.summary}
                greeks={riskData?.greeks}
                exposure={riskData?.exposure}
                loading={!riskData}
            />
            <HoldingsTreemap
                exposure={riskData?.exposure}
                loading={!riskData}
            />
            <PaperPortfolioWidget />
            <DisciplineSummary />
        </div>

        {/* NEW SECTION: STRATEGY PROFILES */}
        <StrategyProfilesPanel />

        {/* SECTION 1.5: HISTORICAL SIMULATION (Polished) */}
        <div className="bg-white dark:bg-zinc-900 rounded-lg shadow p-6 border-l-4 border-indigo-500">
            <div className="flex justify-between items-center mb-4">
                <div>
                    <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Historical Regime Cycle</h2>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Manual verification of regime transitions & strategy logic.</p>
                </div>
                <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2 bg-gray-50 dark:bg-zinc-800 p-1 rounded-lg border border-gray-200 dark:border-zinc-700">
                         <button
                            onClick={() => setSimMode('deterministic')}
                            className={`px-3 py-1 text-xs font-medium rounded transition-colors ${simMode === 'deterministic' ? 'bg-white dark:bg-zinc-700 text-indigo-700 dark:text-indigo-300 shadow-sm border border-gray-200 dark:border-zinc-600' : 'text-gray-500 hover:text-gray-300'}`}
                         >
                            Deterministic
                         </button>
                         <button
                            onClick={() => setSimMode('random')}
                            className={`px-3 py-1 text-xs font-medium rounded transition-colors ${simMode === 'random' ? 'bg-white dark:bg-zinc-700 text-indigo-700 dark:text-indigo-300 shadow-sm border border-gray-200 dark:border-zinc-600' : 'text-gray-500 hover:text-gray-300'}`}
                         >
                            Random
                         </button>
                    </div>

                    {simMode === 'deterministic' && (
                        <div className="text-sm text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-zinc-800 px-3 py-1 rounded">
                            Date: <span className="font-mono font-bold">{simCursor}</span>
                        </div>
                    )}

                    <button
                        onClick={runHistoricalCycle}
                        disabled={simLoading || (simMode === 'deterministic' && simResult?.done)}
                        className={`px-4 py-2 rounded text-white font-medium shadow-sm transition-colors ${
                            simLoading ? 'bg-gray-400 dark:bg-zinc-600 cursor-not-allowed' : 'bg-indigo-600 hover:bg-indigo-700 dark:bg-indigo-700 dark:hover:bg-indigo-800'
                        }`}
                    >
                        {simLoading ? 'Processing...' : (simMode === 'deterministic' && simResult?.done) ? 'End of Data' : simMode === 'random' ? 'Run Random Cycle' : 'Step Forward 1 Cycle'}
                    </button>
                </div>
            </div>

            {/* Simulation Results Display */}
            {simResult && !simResult.error && (
                <div className="bg-gray-50 dark:bg-zinc-800 rounded-lg p-5 border border-gray-200 dark:border-zinc-700">
                    {simResult.done && !simResult.entryTime ? (
                         <p className="text-gray-500 dark:text-gray-400 italic flex items-center gap-2">
                             <AlertTriangle className="w-4 h-4" />
                             {simResult.message || "No trades triggered in remaining data."}
                         </p>
                    ) : (
                        <div className="grid grid-cols-2 md:grid-cols-5 gap-6">
                            <div>
                                <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">Strategy / Regime</p>
                                <p className="font-semibold text-gray-900 dark:text-gray-100 mt-1">{simResult.strategy || 'Standard'}</p>
                                <div className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200 mt-1">
                                    {simResult.regime || 'Neutral'}
                                </div>
                            </div>

                            <div>
                                <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">Entry</p>
                                <p className="font-semibold text-gray-900 dark:text-gray-100 mt-1">{simResult.entryTime}</p>
                                <p className="text-sm text-gray-600 dark:text-gray-400">@ ${simResult.entryPrice?.toFixed(2)}</p>
                                <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase mt-1 inline-block ${simResult.direction === 'long' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'}`}>
                                    {simResult.direction}
                                </span>
                            </div>

                            <div>
                                <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">Exit</p>
                                {simResult.exitTime ? (
                                    <>
                                        <p className="font-semibold text-gray-900 dark:text-gray-100 mt-1">{simResult.exitTime}</p>
                                        <p className="text-sm text-gray-600 dark:text-gray-400">@ ${simResult.exitPrice?.toFixed(2)}</p>
                                    </>
                                ) : (
                                    <p className="text-sm text-gray-400 dark:text-gray-500 italic mt-1">Position Open</p>
                                )}
                            </div>

                            <div>
                                <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">P&L</p>
                                {simResult.pnl !== undefined ? (
                                    <p className={`font-bold text-2xl mt-1 ${simResult.pnl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                                        {simResult.pnl >= 0 ? '+' : ''}{simResult.pnl.toFixed(2)}
                                    </p>
                                ) : (
                                    <p className="text-gray-400 text-xl mt-1">---</p>
                                )}
                            </div>

                            <div className="bg-white dark:bg-zinc-700 p-2 rounded border border-gray-100 dark:border-zinc-600">
                                <p className="text-xs text-gray-500 dark:text-gray-300 uppercase tracking-wide mb-1">Conviction</p>
                                <div className="flex items-center justify-between text-sm">
                                    <span className="text-gray-500 dark:text-gray-400">Entry:</span>
                                    <span className="font-mono font-bold dark:text-gray-200">{simResult.entryConviction?.toFixed(2) || '--'}</span>
                                </div>
                                <div className="flex items-center justify-between text-sm mt-1">
                                    <span className="text-gray-500 dark:text-gray-400">Exit:</span>
                                    <span className="font-mono font-bold dark:text-gray-200">{simResult.exitConviction?.toFixed(2) || '--'}</span>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            )}
            {simResult?.error && (
                <div className="bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 p-3 rounded text-sm mt-2 flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4" />
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
            <div className="space-y-6">
                <div className="bg-gradient-to-r from-purple-50 to-pink-50 dark:from-purple-950/40 dark:to-pink-950/40 rounded-lg shadow p-6 border-l-4 border-purple-500 h-fit">
                    <div className="flex justify-between items-start mb-4">
                        <h3 className="text-lg font-semibold text-purple-900 dark:text-purple-200 flex items-center gap-2">📊 Trade Journal</h3>
                        <button onClick={loadJournalStats} className="text-sm text-purple-700 dark:text-purple-300 underline">Refresh</button>
                    </div>
                    {journalStats ? (
                        <div className="space-y-4">
                             <div className="grid grid-cols-2 gap-4">
                                <div className="bg-white dark:bg-zinc-800 p-3 rounded border border-purple-200 dark:border-purple-800">
                                    <p className="text-xs text-gray-600 dark:text-gray-400">Win Rate</p>
                                    <p className="text-xl font-bold text-purple-900 dark:text-purple-200">{journalStats.stats.win_rate?.toFixed(1) || 0}%</p>
                                </div>
                                <div className="bg-white dark:bg-zinc-800 p-3 rounded border border-purple-200 dark:border-purple-800">
                                    <p className="text-xs text-gray-600 dark:text-gray-400">Total P&L</p>
                                    <p className={`text-xl font-bold ${(journalStats.stats.total_pnl || 0) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                                        ${(journalStats.stats.total_pnl || 0).toFixed(0)}
                                    </p>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="text-center py-8 text-purple-700 dark:text-purple-300 text-sm">No trades logged yet.</div>
                    )}
                </div>
            </div>
        </div>

      </div>
    </DashboardLayout>
  );
}
