'use client';

import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import { API_URL, TEST_USER_ID } from '@/lib/constants';
import { supabase } from '@/lib/supabase';
import { StrategyConfig, BacktestRequest, BacktestResult } from '@/lib/types';
import { Badge } from '@/components/ui/badge'; // Assuming Badge exists or will use basic styling

interface StrategyProfilesPanelProps {
    className?: string;
}

export default function StrategyProfilesPanel({ className }: StrategyProfilesPanelProps) {
    const [strategies, setStrategies] = useState<StrategyConfig[]>([]);
    const [loading, setLoading] = useState(false);
    const [selectedStrategy, setSelectedStrategy] = useState<StrategyConfig | null>(null);
    const [isEditing, setIsEditing] = useState(false);

    // Backtest Modal State
    const [showBacktestModal, setShowBacktestModal] = useState(false);
    const [backtestParams, setBacktestParams] = useState<BacktestRequest>({
        start_date: '2023-01-01',
        end_date: '2023-12-31',
        ticker: 'SPY',
        strategy_name: ''
    });
    const [backtestResults, setBacktestResults] = useState<BacktestResult[]>([]);

    useEffect(() => {
        loadStrategies();
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

    const loadStrategies = async () => {
        setLoading(true);
        try {
            const headers = await getAuthHeaders();
            const res = await fetch(`${API_URL}/strategies`, { headers });
            if (res.ok) {
                const data = await res.json();
                // Extract params and merge with name/version if needed,
                // but the API returns rows with 'params' column.
                // We need to map the DB row to StrategyConfig.
                const configs = data.strategies.map((row: any) => ({
                    ...row.params,
                    name: row.name,
                    version: row.version,
                    description: row.description
                }));
                setStrategies(configs);
            }
        } catch (err) {
            console.error('Failed to load strategies', err);
        } finally {
            setLoading(false);
        }
    };

    const handleSaveStrategy = async (config: StrategyConfig) => {
        try {
            const headers = await getAuthHeaders();
            const res = await fetch(`${API_URL}/strategies`, {
                method: 'POST',
                headers,
                body: JSON.stringify(config)
            });
            if (res.ok) {
                await loadStrategies();
                setIsEditing(false);
                setSelectedStrategy(null);
            } else {
                console.error("Failed to save strategy");
            }
        } catch (err) {
             console.error("Error saving strategy", err);
        }
    };

    const handleRunBacktest = async () => {
        if (!selectedStrategy) return;
        try {
            const headers = await getAuthHeaders();
            const payload = {
                ...backtestParams,
                strategy_name: selectedStrategy.name
            };

            const res = await fetch(`${API_URL}/simulation/batch`, {
                method: 'POST',
                headers,
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                const data = await res.json();
                alert(`Backtest queued! Batch ID: ${data.batch_id}`);
                setShowBacktestModal(false);
                // Optionally poll for results or add to a "Recent Batches" list
                loadBacktestResults(data.batch_id);
            } else {
                console.error("Failed to queue backtest");
            }
        } catch (err) {
            console.error("Error running backtest", err);
        }
    };

    const loadBacktestResults = async (batchId: string) => {
        // Simple polling for demo purposes
        const headers = await getAuthHeaders();
        const interval = setInterval(async () => {
            const res = await fetch(`${API_URL}/simulation/batch/${batchId}`, { headers });
            if (res.ok) {
                const data = await res.json();
                if (data.results && data.results.length > 0) {
                     setBacktestResults(prev => [...data.results, ...prev]); // Prepend new results
                     clearInterval(interval);
                }
            }
        }, 2000);

        // Stop polling after 30 seconds
        setTimeout(() => clearInterval(interval), 30000);
    };

    return (
        <Card className={className}>
            <CardHeader>
                <div className="flex justify-between items-center">
                    <CardTitle>Strategy Profiles</CardTitle>
                    <button
                        onClick={() => {
                            setSelectedStrategy({
                                name: 'New Strategy',
                                version: 1,
                                conviction_floor: 0.5,
                                conviction_slope: 1.0,
                                max_risk_pct_per_trade: 0.02,
                                max_risk_pct_portfolio: 0.25,
                                max_concurrent_positions: 5,
                                max_spread_bps: 20,
                                max_days_to_expiry: 45,
                                min_underlying_liquidity: 1000000,
                                take_profit_pct: 0.5,
                                stop_loss_pct: 0.5,
                                max_holding_days: 10
                            });
                            setIsEditing(true);
                        }}
                        className="text-sm bg-indigo-600 text-white px-3 py-1 rounded hover:bg-indigo-700"
                    >
                        + Create
                    </button>
                </div>
                <CardDescription>Manage trading strategies and run simulations.</CardDescription>
            </CardHeader>
            <CardContent>
                {/* Strategy List */}
                <div className="space-y-4">
                    {loading ? <p>Loading...</p> : strategies.map((s, i) => (
                        <div key={`${s.name}-${s.version}`} className="border p-4 rounded flex justify-between items-center">
                            <div>
                                <h4 className="font-bold">{s.name} <span className="text-xs text-gray-500">v{s.version}</span></h4>
                                <p className="text-sm text-gray-600">{s.description || 'No description'}</p>
                                <div className="text-xs text-gray-500 mt-1 space-x-2">
                                    <span>Floor: {s.conviction_floor}</span>
                                    <span>Slope: {s.conviction_slope}</span>
                                    <span>Risk: {s.max_risk_pct_per_trade * 100}%</span>
                                </div>
                            </div>
                            <div className="flex gap-2">
                                <button
                                    onClick={() => {
                                        setSelectedStrategy(s);
                                        setIsEditing(true);
                                    }}
                                    className="text-xs border border-gray-300 px-2 py-1 rounded hover:bg-gray-50"
                                >
                                    Edit
                                </button>
                                <button
                                    onClick={() => {
                                        setSelectedStrategy(s);
                                        setShowBacktestModal(true);
                                    }}
                                    className="text-xs bg-purple-50 text-purple-700 border border-purple-200 px-2 py-1 rounded hover:bg-purple-100"
                                >
                                    Run Backtest
                                </button>
                            </div>
                        </div>
                    ))}
                </div>

                {/* Backtest Results Table */}
                {backtestResults.length > 0 && (
                    <div className="mt-8">
                        <h3 className="font-semibold mb-2">Recent Backtest Results</h3>
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead className="bg-gray-50">
                                    <tr>
                                        <th className="p-2 text-left">Strategy</th>
                                        <th className="p-2 text-left">Ticker</th>
                                        <th className="p-2 text-left">Period</th>
                                        <th className="p-2 text-right">Trades</th>
                                        <th className="p-2 text-right">Win Rate</th>
                                        <th className="p-2 text-right">P&L</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {backtestResults.map((res, idx) => (
                                        <tr key={idx} className="border-t hover:bg-gray-50">
                                            <td className="p-2">{res.strategy_name} v{res.version}</td>
                                            <td className="p-2">{res.ticker}</td>
                                            <td className="p-2 text-xs text-gray-500">{res.start_date} - {res.end_date}</td>
                                            <td className="p-2 text-right">{res.trades_count}</td>
                                            <td className="p-2 text-right">{(res.win_rate * 100).toFixed(1)}%</td>
                                            <td className={`p-2 text-right font-medium ${res.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                                                ${res.total_pnl.toFixed(2)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
            </CardContent>

            {/* Edit Modal (Overlay) */}
            {isEditing && selectedStrategy && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                    <div className="bg-white p-6 rounded-lg w-full max-w-lg max-h-[90vh] overflow-y-auto">
                        <h3 className="text-lg font-bold mb-4">{selectedStrategy.version > 1 ? 'Edit Strategy' : 'Create Strategy'}</h3>
                        <form onSubmit={(e) => { e.preventDefault(); handleSaveStrategy(selectedStrategy); }}>
                            <div className="grid grid-cols-2 gap-4">
                                <div className="col-span-2">
                                    <label className="block text-xs font-medium">Name</label>
                                    <input
                                        className="w-full border rounded p-1"
                                        value={selectedStrategy.name}
                                        onChange={e => setSelectedStrategy({...selectedStrategy, name: e.target.value})}
                                    />
                                </div>
                                <div className="col-span-2">
                                    <label className="block text-xs font-medium">Description</label>
                                    <textarea
                                        className="w-full border rounded p-1"
                                        value={selectedStrategy.description || ''}
                                        onChange={e => setSelectedStrategy({...selectedStrategy, description: e.target.value})}
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-medium">Conviction Floor</label>
                                    <input
                                        type="number" step="0.05"
                                        className="w-full border rounded p-1"
                                        value={selectedStrategy.conviction_floor}
                                        onChange={e => setSelectedStrategy({...selectedStrategy, conviction_floor: parseFloat(e.target.value)})}
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-medium">Max Risk %</label>
                                    <input
                                        type="number" step="0.01"
                                        className="w-full border rounded p-1"
                                        value={selectedStrategy.max_risk_pct_per_trade}
                                        onChange={e => setSelectedStrategy({...selectedStrategy, max_risk_pct_per_trade: parseFloat(e.target.value)})}
                                    />
                                </div>
                                {/* Add more fields as needed for the demo */}
                            </div>
                            <div className="flex justify-end gap-2 mt-6">
                                <button type="button" onClick={() => setIsEditing(false)} className="px-3 py-1 border rounded">Cancel</button>
                                <button type="submit" className="px-3 py-1 bg-indigo-600 text-white rounded">Save</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Backtest Modal */}
            {showBacktestModal && selectedStrategy && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                    <div className="bg-white p-6 rounded-lg w-full max-w-md">
                        <h3 className="text-lg font-bold mb-4">Run Backtest: {selectedStrategy.name}</h3>
                        <div className="space-y-4">
                            <div>
                                <label className="block text-xs font-medium">Ticker</label>
                                <input
                                    className="w-full border rounded p-1"
                                    value={backtestParams.ticker}
                                    onChange={e => setBacktestParams({...backtestParams, ticker: e.target.value})}
                                />
                            </div>
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-xs font-medium">Start Date</label>
                                    <input
                                        type="date"
                                        className="w-full border rounded p-1"
                                        value={backtestParams.start_date}
                                        onChange={e => setBacktestParams({...backtestParams, start_date: e.target.value})}
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-medium">End Date</label>
                                    <input
                                        type="date"
                                        className="w-full border rounded p-1"
                                        value={backtestParams.end_date}
                                        onChange={e => setBacktestParams({...backtestParams, end_date: e.target.value})}
                                    />
                                </div>
                            </div>
                            <div>
                                <label className="block text-xs font-medium">Param Grid (JSON, Optional)</label>
                                <textarea
                                    className="w-full border rounded p-1 h-20 text-xs font-mono"
                                    placeholder='{"conviction_floor": [0.4, 0.6]}'
                                    onChange={e => {
                                        try {
                                            const val = e.target.value ? JSON.parse(e.target.value) : undefined;
                                            setBacktestParams({...backtestParams, param_grid: val});
                                        } catch {
                                            // Ignore invalid JSON while typing
                                        }
                                    }}
                                />
                            </div>
                        </div>
                        <div className="flex justify-end gap-2 mt-6">
                            <button onClick={() => setShowBacktestModal(false)} className="px-3 py-1 border rounded">Cancel</button>
                            <button onClick={handleRunBacktest} className="px-3 py-1 bg-purple-600 text-white rounded">Queue Simulation</button>
                        </div>
                    </div>
                </div>
            )}
        </Card>
    );
}
