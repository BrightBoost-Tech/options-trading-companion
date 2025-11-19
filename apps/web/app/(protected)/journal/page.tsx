'use client';

import { useState } from 'react';

const mockGuardrails = [
  { id: '1', rule_key: 'earnings_buffer', rule_text: 'if days_to_earnings < 7 then reject', priority: 'high', enabled: true, added_ts: '2025-01-10' },
  { id: '2', rule_key: 'iv_rank_minimum', rule_text: 'if iv_rank < 0.30 then reject', priority: 'medium', enabled: true, added_ts: '2025-01-08' },
  { id: '3', rule_key: 'spread_width', rule_text: 'if spread_bps > 50 then reject', priority: 'low', enabled: false, added_ts: '2025-01-05' },
];

const mockTrades = [
  { id: '1', symbol: 'SPY', strategy: 'Credit Put Spread', open_ts: '2025-01-15', close_ts: '2025-01-20', pnl_pct: 45.5 },
  { id: '2', symbol: 'QQQ', strategy: 'Iron Condor', open_ts: '2025-01-12', close_ts: '2025-01-18', pnl_pct: -25.3 },
  { id: '3', symbol: 'IWM', strategy: 'Credit Put Spread', open_ts: '2025-01-08', close_ts: '2025-01-15', pnl_pct: 50.0 },
];

const mockLossReviews = [
  { 
    id: '1', 
    trade_id: '2',
    symbol: 'QQQ',
    root_cause: 'vol_crush', 
    confidence: 0.85,
    created_at: '2025-01-18',
    recommended_rule: 'Avoid opening new positions within 3 days after major earnings announcements in high-correlation names'
  },
];

export default function JournalPage() {
  const [activeTab, setActiveTab] = useState<'guardrails' | 'trades' | 'reviews'>('guardrails');

  const priorityColors = {
    high: 'bg-red-100 text-red-800',
    medium: 'bg-yellow-100 text-yellow-800',
    low: 'bg-green-100 text-green-800',
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-8 py-4 flex justify-between items-center">
          <h1 className="text-2xl font-bold">Journal</h1>
          <a href="/dashboard" className="text-gray-600 hover:text-gray-900">
            ← Back to Dashboard
          </a>
        </div>
      </div>

      <div className="max-w-7xl mx-auto p-8">
        {/* Tabs */}
        <div className="bg-white rounded-lg shadow mb-6">
          <div className="border-b">
            <nav className="flex">
              <button
                onClick={() => setActiveTab('guardrails')}
                className={`px-6 py-3 font-medium border-b-2 ${
                  activeTab === 'guardrails'
                    ? 'border-blue-600 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                Active Guardrails
              </button>
              <button
                onClick={() => setActiveTab('reviews')}
                className={`px-6 py-3 font-medium border-b-2 ${
                  activeTab === 'reviews'
                    ? 'border-blue-600 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                Loss Reviews
              </button>
              <button
                onClick={() => setActiveTab('trades')}
                className={`px-6 py-3 font-medium border-b-2 ${
                  activeTab === 'trades'
                    ? 'border-blue-600 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                Closed Trades
              </button>
            </nav>
          </div>

          <div className="p-6">
            {activeTab === 'guardrails' && (
              <div className="space-y-4">
                {mockGuardrails.map((rule) => (
                  <div key={rule.id} className="flex items-start gap-4 p-4 border rounded-lg">
                    <input
                      type="checkbox"
                      checked={rule.enabled}
                      className="mt-1"
                      readOnly
                    />
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <span className={`px-2 py-1 text-xs font-medium rounded ${priorityColors[rule.priority as keyof typeof priorityColors]}`}>
                          {rule.priority}
                        </span>
                        <span className="text-sm text-gray-500">
                          Added {new Date(rule.added_ts).toLocaleDateString()}
                        </span>
                      </div>
                      <p className="font-medium mb-1">{rule.rule_key}</p>
                      <p className="text-gray-700 text-sm">{rule.rule_text}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {activeTab === 'reviews' && (
              <div className="space-y-4">
                {mockLossReviews.map((review) => (
                  <div key={review.id} className="p-6 border rounded-lg">
                    <div className="flex justify-between mb-4">
                      <div>
                        <span className="font-medium text-lg">{review.symbol}</span>
                        <span className="ml-2 text-sm text-gray-500">
                          {new Date(review.created_at).toLocaleDateString()}
                        </span>
                      </div>
                      <div className="text-sm">
                        <span className="font-medium">Confidence:</span>{' '}
                        <span className={review.confidence >= 0.7 ? 'text-green-600' : 'text-yellow-600'}>
                          {(review.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                    </div>
                    <div className="space-y-3">
                      <div>
                        <p className="text-sm font-medium text-gray-600 mb-1">Root Cause</p>
                        <p className="text-gray-900">{review.root_cause.replace('_', ' ')}</p>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-gray-600 mb-1">Recommended Guardrail</p>
                        <p className="text-gray-900 bg-blue-50 p-3 rounded">{review.recommended_rule}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {activeTab === 'trades' && (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Strategy</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Open</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Close</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P&L %</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {mockTrades.map((trade) => (
                      <tr key={trade.id} className="hover:bg-gray-50">
                        <td className="px-6 py-4 whitespace-nowrap font-medium">{trade.symbol}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm">{trade.strategy}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                          {new Date(trade.open_ts).toLocaleDateString()}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                          {new Date(trade.close_ts).toLocaleDateString()}
                        </td>
                        <td className={`px-6 py-4 whitespace-nowrap text-sm font-medium ${
                          trade.pnl_pct >= 0 ? 'text-green-600' : 'text-red-600'
                        }`}>
                          {trade.pnl_pct >= 0 ? '+' : ''}{trade.pnl_pct.toFixed(2)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
