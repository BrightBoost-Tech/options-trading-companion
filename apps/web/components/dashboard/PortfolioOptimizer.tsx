'use client'

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Sparkles, Activity, AlertTriangle, CheckCircle, ArrowRight, RefreshCw } from 'lucide-react';
import { API_URL } from '@/lib/constants';

// Types based on our Python API
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

export default function PortfolioOptimizer({ positions }) {
  const [isQuantum, setIsQuantum] = useState(false)
  const [isOptimizing, setIsOptimizing] = useState(false)
  const [results, setResults] = useState<{ trades: Trade[], metrics: Metrics } | null>(null)
  const [diagnostic, setDiagnostic] = useState<any>(null)
  const [showDiag, setShowDiag] = useState(false)

  const handleOptimize = async () => {
    setIsOptimizing(true)
    try {
      const res = await fetch(`${API_URL}/optimize/portfolio`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          positions: positions || [], // Pass real props
          risk_aversion: 1.0,
          skew_preference: isQuantum ? 10.0 : 0.0, // The Switch!
          cash_balance: 1000.0
        })
      })
      const data = await res.json()
      setResults(data)
    } catch (e) {
      console.error(e)
    } finally {
      setIsOptimizing(false)
    }
  }

  const runDiagnostics = async () => {
    const res = await fetch(`${API_URL}/diagnostics/phase1`)
    const data = await res.json()
    setDiagnostic(data)
    setShowDiag(true)
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden h-full flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
        <div className="flex items-center gap-2">
          {isQuantum ? <Sparkles className="w-5 h-5 text-purple-600" /> : <Activity className="w-5 h-5 text-emerald-600" />}
          <h2 className="font-semibold text-slate-800">
            {isQuantum ? 'Quantum Optimizer (Dirac-3 Ready)' : 'Classical Optimizer (MVO)'}
          </h2>
        </div>

        <div className="flex items-center gap-3">
             <button onClick={runDiagnostics} className="text-xs text-slate-500 hover:text-slate-800 underline">
                Test Core
             </button>
             <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              className="sr-only peer"
              checked={isQuantum}
              onChange={() => setIsQuantum(!isQuantum)}
            />
            <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-purple-600"></div>
          </label>
        </div>
      </div>

      {/* Main Content */}
      <div className="p-6 flex-1 overflow-y-auto">

        {/* Empty State */}
        {!results && !isOptimizing && (
          <div className="text-center py-10">
            <p className="text-slate-500 mb-4 text-sm">
              {isQuantum
                ? "Minimizes Tail Risk (Skewness) using Cubic Tensors."
                : "Balances Risk (Variance) and Return."}
            </p>
            <button
              onClick={handleOptimize}
              className={`px-4 py-2 rounded-lg text-white text-sm font-medium transition-colors ${
                isQuantum ? 'bg-purple-600 hover:bg-purple-700' : 'bg-emerald-600 hover:bg-emerald-700'
              }`}
            >
              Run Optimization
            </button>
          </div>
        )}

        {/* Loading State */}
        {isOptimizing && (
          <div className="flex flex-col items-center justify-center py-12 space-y-4">
             <RefreshCw className={`w-8 h-8 animate-spin ${isQuantum ? 'text-purple-600' : 'text-emerald-500'}`} />
             <p className="text-xs text-slate-400 font-mono">
                {isQuantum ? "CALCULATING TENSORS (N^3)..." : "SOLVING QUADRATIC..."}
             </p>
          </div>
        )}

        {/* Results State */}
        {results && !isOptimizing && (
          <div className="space-y-6">

            {/* Metrics Grid */}
            <div className="grid grid-cols-3 gap-4">
              <MetricTile
                label="Exp. Return"
                value={`${(results.metrics.expected_return * 100).toFixed(1)}%`}
                color="text-slate-900"
              />
              <MetricTile
                label="Sharpe Ratio"
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

            {/* Actionable Trades */}
            <div>
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
                Recommended Actions
              </h3>
              <div className="space-y-2">
                {results.trades.length === 0 ? (
                    <div className="text-sm text-slate-400 italic">Portfolio is optimal. No trades needed.</div>
                ) : (
                    results.trades.map((trade, idx) => (
                      <div key={idx} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg border border-slate-100">
                        <div className="flex items-center gap-3">
                          <span className={`px-2 py-1 rounded text-[10px] font-bold ${
                            trade.action === 'BUY'
                              ? 'bg-emerald-100 text-emerald-700'
                              : 'bg-amber-100 text-amber-700'
                          }`}>
                            {trade.action}
                          </span>
                          <div>
                            <span className="font-semibold text-sm text-slate-800">{trade.symbol}</span>
                            <span className="text-xs text-slate-500 ml-2">{trade.est_quantity} units</span>
                          </div>
                        </div>
                        <div className="text-right">
                            <div className="text-sm font-medium">${trade.value.toLocaleString()}</div>
                            <div className="text-[10px] text-slate-400">{trade.rationale}</div>
                        </div>
                      </div>
                    ))
                )}
              </div>
            </div>

             <button onClick={handleOptimize} className="w-full py-2 mt-2 text-xs text-slate-400 hover:text-slate-600">
                Re-run Optimization
             </button>
          </div>
        )}
      </div>

      {/* Diagnostic Modal (Test Suite) */}
      <AnimatePresence>
        {showDiag && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-white/95 backdrop-blur-sm z-10 flex flex-col p-6"
          >
             <h3 className="font-bold text-lg mb-4">Core System Diagnostics</h3>
             {diagnostic ? (
                <div className="space-y-4">
                    <div className={`p-4 rounded-lg border ${diagnostic.test_passed ? 'bg-emerald-50 border-emerald-200' : 'bg-red-50 border-red-200'}`}>
                        <div className="flex items-center gap-2 mb-2">
                            {diagnostic.test_passed ? <CheckCircle className="text-emerald-600 w-5 h-5"/> : <AlertTriangle className="text-red-600 w-5 h-5"/>}
                            <span className="font-semibold">{diagnostic.test_passed ? "Phase 1: PASSED" : "Phase 1: FAILED"}</span>
                        </div>
                        <p className="text-sm text-slate-600 mb-2">{diagnostic.message}</p>
                    </div>

                    <div className="grid grid-cols-2 gap-4 text-xs font-mono bg-slate-900 text-slate-200 p-4 rounded-lg">
                        <div>
                            <div className="text-slate-400 mb-1">CLASSICAL WEIGHTS</div>
                            <div>SAFE: {diagnostic.classical_weights?.SAFE}</div>
                            <div>RISKY: {diagnostic.classical_weights?.RISKY}</div>
                        </div>
                        <div>
                            <div className="text-purple-400 mb-1">QUANTUM WEIGHTS</div>
                            <div>SAFE: {diagnostic.quantum_weights?.SAFE}</div>
                            <div>RISKY: {diagnostic.quantum_weights?.RISKY}</div>
                        </div>
                    </div>
                    <p className="text-xs text-slate-500 mt-2">
                        *Verification Logic: The Quantum solver correctly identified the negative skew (crash risk) in the 'RISKY' asset and reduced allocation compared to the Classical solver.
                    </p>
                </div>
             ) : (
                <div className="animate-pulse">Running math engine verification...</div>
             )}
             <button
                onClick={() => setShowDiag(false)}
                className="mt-auto w-full py-3 bg-slate-900 text-white rounded-lg hover:bg-slate-800"
             >
                Close Diagnostics
             </button>
          </motion.div>
        )}
      </AnimatePresence>
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
        <div className={`p-3 rounded-lg border ${active ? 'bg-purple-50 border-purple-200' : 'bg-slate-50 border-slate-100'}`}>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</div>
            <div className={`text-lg font-bold ${color}`}>{value}</div>
        </div>
    )
}
