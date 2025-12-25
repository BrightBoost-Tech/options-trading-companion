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
import PortfolioHoldingsTable from '@/components/dashboard/PortfolioHoldingsTable';
import PaperPortfolioWidget from '@/components/dashboard/PaperPortfolioWidget';
import { fetchWithAuth, fetchWithAuthTimeout } from '@/lib/api';
import { QuantumTooltip } from "@/components/ui/QuantumTooltip";
import { ThemeToggle } from '@/components/ThemeToggle';
import { AlertTriangle, Wallet, Loader2, RefreshCw } from 'lucide-react';

const mockAlerts = [
  { id: '1', message: 'SPY credit put spread scout: 475/470 for $1.50 credit', time: '2 min ago' },
  { id: '2', message: 'QQQ IV rank above 50% - consider premium selling', time: '15 min ago' },
];

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
  const [journalLoading, setJournalLoading] = useState(false);

  // Historical Simulation State
  const [simCursor, setSimCursor] = useState<string>('2023-01-01');
  const [simResult, setSimResult] = useState<any>(null);
  const [simLoading, setSimLoading] = useState(false);
  const [simMode, setSimMode] = useState<'deterministic' | 'random'>('deterministic');
  const [workflowsRunning, setWorkflowsRunning] = useState(false);

  // Load data with staged execution
  useEffect(() => {
    let mounted = true;

    const loadStaged = async () => {
      // Phase 1: Critical Data (Snapshot) - Blocking for initial meaningful paint
      await loadSnapshot();
      if (!mounted) return;

      // Phase 2: Risk & Journal - Fire and forget
      Promise.all([loadRiskDashboard(), loadJournalStats()]);

      // Phase 3: Secondary Data (Scout, Suggestions, Reports)
      // Small delay to prioritize rendering of Phase 1 & 2
      await new Promise(r => setTimeout(r, 100));
      if (!mounted) return;

      loadWeeklyScout();
      loadMorningSuggestions();
      loadMiddaySuggestions();
      loadWeeklyReports();
      loadRebalanceSuggestions();
    };

    loadStaged();

    return () => { mounted = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadSnapshot = async () => {
    try {
      const data = await fetchWithAuthTimeout('/portfolio/snapshot', 15000);
      setSnapshot(data);
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load snapshot:', err);
    }
  };

  const loadRiskDashboard = async () => {
    try {
      const data = await fetchWithAuthTimeout('/risk/dashboard', 10000);
      setRiskData(data);
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load risk dashboard:', err);
    }
  };

  const loadWeeklyScout = async () => {
    setScoutLoading(true);
    try {
      const data = await fetchWithAuthTimeout('/scout/weekly', 20000);
      setWeeklyScout(data);
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load scout:', err);
    } finally {
      setScoutLoading(false);
    }
  };

  const loadJournalStats = async () => {
    setJournalLoading(true);
    try {
      const data = await fetchWithAuthTimeout('/journal/stats', 10000);
      setJournalStats(data);
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load journal stats:', err);
    } finally {
      setJournalLoading(false);
    }
  };

  const loadMorningSuggestions = async () => {
    try {
      const data = await fetchWithAuthTimeout('/suggestions?window=morning_limit', 15000);
      setMorningSuggestions(Array.isArray(data.suggestions) ? data.suggestions : []);
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load morning suggestions', err);
      setMorningSuggestions([]);
    }
  };

  const loadMiddaySuggestions = async () => {
    try {
      const data = await fetchWithAuthTimeout('/suggestions?window=midday_entry', 15000);
      setMiddaySuggestions(Array.isArray(data.suggestions) ? data.suggestions : []);
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load midday suggestions', err);
      setMiddaySuggestions([]);
    }
  };

  const loadRebalanceSuggestions = async () => {
    try {
      const data = await fetchWithAuthTimeout('/rebalance/suggestions', 15000);
      setRebalanceSuggestions(Array.isArray(data.suggestions) ? data.suggestions : []);
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load rebalance suggestions', err);
      setRebalanceSuggestions([]);
    }
  };

  const loadWeeklyReports = async () => {
    try {
      const data = await fetchWithAuthTimeout('/weekly-reports', 15000);
      setWeeklyReports(Array.isArray(data.reports) ? data.reports : []);
    } catch (err: any) {
      if (isAbortError(err)) return;
      console.error('Failed to load weekly reports', err);
      setWeeklyReports([]);
    }
  };

  const runAllWorkflows = async () => {
    setWorkflowsRunning(true);
    try {
      await fetchWithAuthTimeout('/tasks/run-all', 30000, {
        method: 'POST',
      });
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
    } finally {
      setWorkflowsRunning(false);
    }
  };

  const runHistoricalCycle = async () => {
    setSimLoading(true);
    try {
      const payload: any = { mode: simMode };
      if (simMode === 'deterministic') {
          payload.cursor = simCursor;
          payload.symbol = 'SPY';
      } else {
          payload.cursor = simCursor;
      }

      const data = await fetchWithAuth('/historical/run-cycle', {
        method: 'POST',
        body: JSON.stringify(payload),
      });

      setSimResult(data);
      if (data.nextCursor) {
          setSimCursor(data.nextCursor);
      }
    } catch (err) {
      console.error('Simulation error', err);
    } finally {
      setSimLoading(false);
    }
  };

  // --- DERIVED STATE ---

  const hasPositions =
    Array.isArray(snapshot?.positions ?? snapshot?.holdings) &&
    (snapshot?.positions ?? snapshot?.holdings)?.length > 0;

  return (
    <DashboardLayout mockAlerts={mockAlerts}>
      <div className="max-w-7xl mx-auto p-8 space-y-6">

        {/* DASHBOARD TITLE */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h1 className="text-3xl font-bold text-foreground">Dashboard</h1>
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
            <div className="bg-card rounded-lg shadow overflow-hidden border border-border">
              <div className="px-6 py-4 border-b border-border flex justify-between items-center">
                <h2 className="text-xl font-semibold text-foreground">Positions</h2>
                <div className="flex gap-2">
                  <SyncHoldingsButton onSyncComplete={loadSnapshot} />
                  <a href="/paper" className="text-xs px-3 py-1 flex items-center rounded bg-blue-50 text-blue-700 hover:bg-blue-100 border border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800">
                     <Wallet className="w-3 h-3 mr-1" /> Paper Portfolio
                  </a>
                  <button
                    onClick={runAllWorkflows}
                    disabled={workflowsRunning}
                    className="text-xs px-3 py-1 rounded border border-purple-200 text-purple-700 hover:bg-purple-50 dark:border-purple-800 dark:text-purple-300 dark:hover:bg-purple-900 disabled:opacity-50 disabled:cursor-wait inline-flex items-center gap-1.5"
                  >
                    {workflowsRunning && <Loader2 className="w-3 h-3 animate-spin" />}
                    {workflowsRunning ? 'Generating...' : 'Generate Suggestions (Dev)'}
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
        <div className="bg-card rounded-lg shadow p-6 border-l-4 border-indigo-500 border border-border border-l-0">
            <div className="flex justify-between items-center mb-4">
                <div>
                    <h2 className="text-lg font-bold text-foreground">Historical Regime Cycle</h2>
                    <p className="text-sm text-muted-foreground">Manual verification of regime transitions & strategy logic.</p>
                </div>
                <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2 bg-muted p-1 rounded-lg border border-border">
                         <button
                            onClick={() => setSimMode('deterministic')}
                            aria-pressed={simMode === 'deterministic'}
                            className={`px-3 py-1 text-xs font-medium rounded transition-colors ${simMode === 'deterministic' ? 'bg-white dark:bg-zinc-700 text-indigo-700 dark:text-indigo-300 shadow-sm border border-gray-200 dark:border-zinc-600' : 'text-gray-500 hover:text-gray-300'}`}
                         >
                            Deterministic
                         </button>
                         <button
                            onClick={() => setSimMode('random')}
                            aria-pressed={simMode === 'random'}
                            className={`px-3 py-1 text-xs font-medium rounded transition-colors ${simMode === 'random' ? 'bg-white dark:bg-zinc-700 text-indigo-700 dark:text-indigo-300 shadow-sm border border-gray-200 dark:border-zinc-600' : 'text-gray-500 hover:text-gray-300'}`}
                         >
                            Random
                         </button>
                    </div>

                    {simMode === 'deterministic' && (
                        <div className="text-sm text-muted-foreground bg-muted/50 px-3 py-1 rounded">
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
                <div className="bg-muted/50 rounded-lg p-5 border border-border">
                    {simResult.done && !simResult.entryTime ? (
                         <p className="text-muted-foreground italic flex items-center gap-2">
                             <AlertTriangle className="w-4 h-4" />
                             {simResult.message || "No trades triggered in remaining data."}
                         </p>
                    ) : (
                        <div className="grid grid-cols-2 md:grid-cols-5 gap-6">
                            <div>
                                <p className="text-xs text-muted-foreground uppercase tracking-wide">Strategy / Regime</p>
                                <p className="font-semibold text-foreground mt-1">{simResult.strategy || 'Standard'}</p>
                                <div className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-200 mt-1">
                                    {simResult.regime || 'Neutral'}
                                </div>
                            </div>

                            <div>
                                <p className="text-xs text-muted-foreground uppercase tracking-wide">Entry</p>
                                <p className="font-semibold text-foreground mt-1">{simResult.entryTime}</p>
                                <p className="text-sm text-muted-foreground">@ ${simResult.entryPrice?.toFixed(2)}</p>
                                <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase mt-1 inline-block ${simResult.direction === 'long' ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-200' : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-200'}`}>
                                    {simResult.direction}
                                </span>
                            </div>

                            <div>
                                <p className="text-xs text-muted-foreground uppercase tracking-wide">Exit</p>
                                {simResult.exitTime ? (
                                    <>
                                        <p className="font-semibold text-foreground mt-1">{simResult.exitTime}</p>
                                        <p className="text-sm text-muted-foreground">@ ${simResult.exitPrice?.toFixed(2)}</p>
                                    </>
                                ) : (
                                    <p className="text-sm text-muted-foreground italic mt-1">Position Open</p>
                                )}
                            </div>

                            <div>
                                <p className="text-xs text-muted-foreground uppercase tracking-wide">P&L</p>
                                {simResult.pnl !== undefined ? (
                                    <p className={`font-bold text-2xl mt-1 ${simResult.pnl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                                        {simResult.pnl >= 0 ? '+' : ''}{simResult.pnl.toFixed(2)}
                                    </p>
                                ) : (
                                    <p className="text-muted-foreground text-xl mt-1">---</p>
                                )}
                            </div>

                            <div className="bg-card p-2 rounded border border-border">
                                <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">Conviction</p>
                                <div className="flex items-center justify-between text-sm">
                                    <span className="text-muted-foreground">Entry:</span>
                                    <span className="font-mono font-bold text-foreground">{simResult.entryConviction?.toFixed(2) || '--'}</span>
                                </div>
                                <div className="flex items-center justify-between text-sm mt-1">
                                    <span className="text-muted-foreground">Exit:</span>
                                    <span className="font-mono font-bold text-foreground">{simResult.exitConviction?.toFixed(2) || '--'}</span>
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
                <div className="bg-gradient-to-r from-purple-50 to-pink-50 dark:from-purple-950/40 dark:to-pink-950/40 rounded-lg shadow p-6 border-l-4 border-purple-500 h-fit border border-border border-l-0">
                    <div className="flex justify-between items-start mb-4">
                        <h3 className="text-lg font-semibold text-purple-900 dark:text-purple-200 flex items-center gap-2">📊 Trade Journal</h3>
                        <button
                          onClick={loadJournalStats}
                          disabled={journalLoading}
                          className="text-sm text-purple-700 dark:text-purple-300 flex items-center gap-1 hover:underline disabled:opacity-50"
                        >
                          <RefreshCw className={`w-3 h-3 ${journalLoading ? 'animate-spin' : ''}`} />
                          Refresh
                        </button>
                    </div>
                    {journalStats ? (
                        <div className="space-y-4">
                             <div className="grid grid-cols-2 gap-4">
                                <div className="bg-card p-3 rounded border border-purple-200 dark:border-purple-800">
                                    <p className="text-xs text-muted-foreground">Win Rate</p>
                                    <p className="text-xl font-bold text-purple-900 dark:text-purple-200">{journalStats.stats.win_rate?.toFixed(1) || 0}%</p>
                                </div>
                                <div className="bg-card p-3 rounded border border-purple-200 dark:border-purple-800">
                                    <p className="text-xs text-muted-foreground">Total P&L</p>
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
