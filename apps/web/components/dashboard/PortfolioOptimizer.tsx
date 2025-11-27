'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Sparkles,
  Activity,
  AlertTriangle,
  CheckCircle,
  RefreshCw,
  Cpu,
  ShieldCheck,
  Zap
} from 'lucide-react'
import clsx from 'clsx'
import { API_URL } from '@/lib/constants'

// --- Types ---
interface Trade {
  symbol: string;
  action: 'BUY' | 'SELL';
  value: number;
  est_quantity: number;
  rationale: string;
}

interface Metrics {
  expected_return: number;
  sharpe_ratio: number;
  tail_risk_score: number;
}

interface OptimizationResult {
  status: string;
  mode: string; // "QCI Dirac-3" | "Surrogate (Fallback)" | "Classical"
  target_weights: Record<string, number>;
  trades: Trade[];
  metrics: Metrics;
}

interface PortfolioOptimizerProps {
  positions: any[];
  onOptimizationComplete: (metrics: Metrics | null) => void;
}

export default function PortfolioOptimizer({ positions, onOptimizationComplete }: PortfolioOptimizerProps) {
  const [isQuantum, setIsQuantum] = useState(false)
  const [isOptimizing, setIsOptimizing] = useState(false)
  const [results, setResults] = useState<OptimizationResult | null>(null)

  // Diagnostics State
  const [diagnostic, setDiagnostic] = useState<any>(null)
  const [showDiag, setShowDiag] = useState(false)
  const [isDiagLoading, setIsDiagLoading] = useState(false)

  const handleOptimize = async () => {
    setIsOptimizing(true)
    setResults(null)

    try {
      // 1. Data Mapping (DB -> API Schema)
      const formattedPositions = (positions || []).map((p: any) => ({
        symbol: p.symbol,
        // Handle string/number conversion safely
        current_quantity: Number(p.quantity || p.current_quantity || 0),
        current_price: Number(p.current_price || p.price || 0),
        current_value: (Number(p.quantity || 0) * Number(p.current_price || 0)) || p.current_value || 0
      }));

      // 2. API Call
      const res = await fetch(`${API_URL}/optimize/portfolio`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          positions: formattedPositions,
          risk_aversion: 1.0,
          skew_preference: isQuantum ? 10000.0 : 0.0, // High skew penalty triggers Quantum logic
          cash_balance: 1000.0
        })
      })

      if (!res.ok) {
        const errorText = await res.text();
        try {
           const errJson = JSON.parse(errorText);
           alert(`Error: ${errJson.detail?.[0]?.msg || errJson.detail || "Unknown Backend Error"}`);
        } catch {
           alert(`Optimization Failed (Status ${res.status})`);
        }
        return;
      }

      const data = await res.json()
      setResults(data)
      onOptimizationComplete(data.metrics)

    } catch (e) {
      console.error("Optimization Error:", e)
      alert("Could not connect to optimization engine. Check backend.")
    } finally {
      setIsOptimizing(false)
    }
  }

  const runDiagnostics = async () => {
    setIsDiagLoading(true)
    setShowDiag(true)
    try {
        const res = await fetch(`${API_URL}/diagnostics/phase1`)
        const data = await res.json()
        setDiagnostic(data)
    } catch (e) {
        setDiagnostic({ test_passed: false, message: "Connection Failed" })
    } finally {
        setIsDiagLoading(false)
    }
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden h-full flex flex-col relative">

      {/* --- Header --- */}
      <div className="p-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
        <div className="flex items-center gap-2">
          {isQuantum ? (
            <div className="flex items-center gap-2">
               <div className="relative">
                 <Sparkles className="w-5 h-5 text-purple-600 animate-pulse" />
                 <div className="absolute inset-0 bg-purple-400 blur-sm opacity-30 animate-pulse"></div>
               </div>
               <span className="font-bold text-slate-800 bg-clip-text text-transparent bg-gradient-to-r from-purple-600 to-indigo-600">
                 Dirac-3 Optimizer
               </span>
            </div>
          ) : (
            <div className="flex items-center gap-2">
               <Activity className="w-5 h-5 text-emerald-600" />
               <span className="font-semibold text-slate-700">Classical MVO</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-4">
             <button onClick={runDiagnostics} className="text-[10px] font-mono text-slate-400 hover:text-indigo-600 transition-colors">
                TEST_CORE_SYSTEM
             </button>

             {/* The requested Toggle */}
             <div className="flex items-center gap-2">
                <span className={`text-xs font-medium transition-colors ${isQuantum ? 'text-purple-700' : 'text-slate-500'}`}>
                  Optimize Tail Risk
                </span>
                <button
                  onClick={() => setIsQuantum(!isQuantum)}
                  className={clsx(
                    "relative w-10 h-5 rounded-full transition-colors duration-300 focus:outline-none",
                    isQuantum ? "bg-purple-600" : "bg-slate-300"
                  )}
                >
                  <div className={clsx(
                    "absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow-md transform transition-transform duration-300",
                    isQuantum ? "translate-x-5" : "translate-x-0"
                  )} />
                </button>
             </div>
        </div>
      </div>

      {/* --- Main Content --- */}
      <div className="p-6 flex-1 overflow-y-auto">

        {/* Empty State */}
        {!results && !isOptimizing && (
          <div className="flex flex-col items-center justify-center h-full py-8 text-center">
            <div className={clsx("p-4 rounded-full mb-4 bg-opacity-10", isQuantum ? "bg-purple-100" : "bg-emerald-100")}>
                {isQuantum ? <Cpu className="w-8 h-8 text-purple-600" /> : <ShieldCheck className="w-8 h-8 text-emerald-600" />}
            </div>
            <h3 className="text-slate-800 font-medium mb-2">
              {isQuantum ? "Quantum Skew Optimization" : "Mean-Variance Optimization"}
            </h3>
            <p className="text-sm text-slate-500 max-w-xs mx-auto mb-6">
              {isQuantum
                ? "Utilizes QCI Dirac-3 hardware to minimize tail risk (skewness) and maximize momentum."
                : "Standard Markowitz model. Balances expected return against volatility."}
            </p>
            <button
              onClick={handleOptimize}
              className={clsx(
                "px-6 py-2.5 rounded-lg text-white text-sm font-medium transition-all shadow-md hover:shadow-lg transform hover:-translate-y-0.5",
                isQuantum ? "bg-gradient-to-r from-purple-600 to-indigo-600" : "bg-emerald-600 hover:bg-emerald-700"
              )}
            >
              Run Optimization
            </button>
          </div>
        )}

        {/* Loading State */}
        {isOptimizing && (
          <div className="flex flex-col items-center justify-center py-20 space-y-6">
             <div className="relative">
                <RefreshCw className={clsx("w-10 h-10 animate-spin", isQuantum ? "text-purple-600" : "text-emerald-500")} />
                {isQuantum && <div className="absolute inset-0 bg-purple-500 blur-xl opacity-20 animate-pulse"></div>}
             </div>
             <div className="text-center space-y-1">
                <p className="font-medium text-slate-800">
                    {isQuantum ? "Accessing Quantum Backend..." : "Solving Quadratic Equation..."}
                </p>
                <p className="text-xs text-slate-400 font-mono">
                    {isQuantum ? "Constructing Hamiltonian (N³ Tensor)" : "Calculating Covariance Matrix"}
                </p>
             </div>
          </div>
        )}

        {/* Results State */}
        {results && !isOptimizing && (
          <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">

            {/* 1. Source Badge (The requested feature) */}
            <div className="flex justify-center">
                <OptimizationBadge mode={results.mode} />
            </div>

            {/* 2. Metrics Grid */}
            <div className="grid grid-cols-3 gap-3">
              <MetricTile
                label="Exp. Return"
                value={`${(results.metrics.expected_return * 100).toFixed(1)}%`}
                color="text-slate-900"
              />
              <MetricTile
                label="Sharpe"
                value={results.metrics.sharpe_ratio.toFixed(2)}
                color="text-emerald-600"
              />
              <MetricTile
                label="Tail Risk"
                value={results.metrics.tail_risk_score.toFixed(4)}
                color={isQuantum ? "text-purple-600" : "text-slate-500"}
                active={isQuantum}
              />
            </div>

            {/* 3. Trades List */}
            <div>
              <h3 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-3">
                Strategic Rebalance
              </h3>
              <div className="space-y-2">
                {results.trades.length === 0 ? (
                    <div className="p-4 bg-slate-50 rounded-lg text-center border border-slate-100">
                        <CheckCircle className="w-5 h-5 text-emerald-500 mx-auto mb-2" />
                        <p className="text-sm text-slate-600">Portfolio is optimal.</p>
                    </div>
                ) : (
                    results.trades.map((trade, idx) => (
                      <div key={idx} className="flex items-center justify-between p-3 bg-white rounded-lg border border-slate-100 shadow-sm hover:shadow-md transition-shadow">
                        <div className="flex items-center gap-3">
                          <span className={clsx(
                              "px-2.5 py-1 rounded text-[10px] font-bold uppercase tracking-wider",
                              trade.action === 'BUY' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'
                          )}>
                            {trade.action}
                          </span>
                          <div>
                            <span className="font-bold text-sm text-slate-800">{trade.symbol}</span>
                            <span className="text-xs text-slate-500 ml-2">x {trade.est_quantity}</span>
                          </div>
                        </div>
                        <div className="text-right">
                            <div className="text-sm font-bold text-slate-700">${trade.value.toLocaleString()}</div>
                            <div className="text-[10px] text-slate-400">{trade.rationale}</div>
                        </div>
                      </div>
                    ))
                )}
              </div>
            </div>

             <button
                onClick={handleOptimize}
                className="w-full py-3 mt-2 text-xs font-medium text-slate-400 hover:text-indigo-600 border border-transparent hover:border-indigo-100 rounded-lg transition-all"
             >
                Re-run Optimization Model
             </button>
          </div>
        )}
      </div>

      {/* --- Diagnostic Modal --- */}
      <AnimatePresence>
        {showDiag && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-white/95 backdrop-blur-md z-20 flex flex-col p-6"
          >
             <div className="flex justify-between items-center mb-6">
                <h3 className="font-bold text-lg text-slate-800">System Diagnostics</h3>
                <button onClick={() => setShowDiag(false)} className="text-slate-400 hover:text-slate-600">Close</button>
             </div>

             {isDiagLoading ? (
                <div className="flex-1 flex flex-col items-center justify-center text-slate-400 space-y-3">
                    <Zap className="w-8 h-8 animate-bounce text-yellow-500" />
                    <span className="text-sm font-mono">Running Unit Tests...</span>
                </div>
             ) : diagnostic ? (
                <div className="space-y-4">
                    <div className={clsx(
                        "p-4 rounded-lg border flex items-center gap-3",
                        diagnostic.test_passed ? "bg-emerald-50 border-emerald-200" : "bg-red-50 border-red-200"
                    )}>
                        {diagnostic.test_passed
                            ? <CheckCircle className="text-emerald-600 w-6 h-6"/>
                            : <AlertTriangle className="text-red-600 w-6 h-6"/>}
                        <div>
                            <div className="font-bold text-sm">
                                {diagnostic.test_passed ? "Phase 1 Logic: VERIFIED" : "Phase 1 Logic: FAILED"}
                            </div>
                            <div className="text-xs opacity-80">{diagnostic.message}</div>
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3 text-[10px] font-mono">
                        <div className="bg-slate-100 p-3 rounded">
                            <div className="text-slate-500 mb-1">CLASSICAL (MVO)</div>
                            <div className="flex justify-between"><span>SAFE:</span> <span>{diagnostic.classical_weights?.SAFE}</span></div>
                            <div className="flex justify-between"><span>RISKY:</span> <span>{diagnostic.classical_weights?.RISKY}</span></div>
                        </div>
                        <div className="bg-slate-900 text-purple-200 p-3 rounded">
                            <div className="text-purple-400 mb-1">QUANTUM (SKEW)</div>
                            <div className="flex justify-between"><span>SAFE:</span> <span>{diagnostic.quantum_weights?.SAFE}</span></div>
                            <div className="flex justify-between"><span>RISKY:</span> <span>{diagnostic.quantum_weights?.RISKY}</span></div>
                        </div>
                    </div>
                </div>
             ) : null}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// --- Subcomponents ---

function OptimizationBadge({ mode }: { mode: string }) {
    if (mode === 'QCI Dirac-3') {
        return (
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-gradient-to-r from-purple-600 to-indigo-600 text-white shadow-sm">
                <Sparkles className="w-3 h-3" />
                <span className="text-[10px] font-bold tracking-wide uppercase">Powered by QCI Dirac-3</span>
            </div>
        )
    }
    // New: Specific Trial Badges
    if (mode.includes('Quota')) {
        return (
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-100">
                <AlertTriangle className="w-3 h-3" />
                <span className="text-[10px] font-bold tracking-wide uppercase">Trial Quota Exceeded (Simulated)</span>
            </div>
        )
    }
    if (mode.includes('Limit')) {
        return (
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-100">
                <ShieldCheck className="w-3 h-3" />
                <span className="text-[10px] font-bold tracking-wide uppercase">Asset Limit (Simulated)</span>
            </div>
        )
    }
    if (mode.includes('Surrogate')) {
        return (
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-100">
                <Cpu className="w-3 h-3" />
                <span className="text-[10px] font-bold tracking-wide uppercase">Quantum Surrogate</span>
            </div>
        )
    }
    return (
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-slate-100 text-slate-600">
            <Activity className="w-3 h-3" />
            <span className="text-[10px] font-bold tracking-wide uppercase">Classical Algorithm</span>
        </div>
    )
}

interface MetricTileProps {
  label: string;
  value: string;
  color: string;
  active?: boolean;
}

function MetricTile({ label, value, color, active = false }: MetricTileProps) {
    return (
        <div className={clsx(
            "p-3 rounded-lg border transition-colors",
            active ? "bg-purple-50 border-purple-200" : "bg-slate-50 border-slate-100"
        )}>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 font-semibold">{label}</div>
            <div className={clsx("text-lg font-bold", color)}>{value}</div>
        </div>
    )
}