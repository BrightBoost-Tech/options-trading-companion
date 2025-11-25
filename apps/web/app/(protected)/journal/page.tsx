'use client';

import { useState } from 'react';
import DashboardLayout from '@/components/DashboardLayout';

export default function JournalPage() {
  const [rules, setRules] = useState([
    { id: 1, type: 'high', label: 'Earnings Buffer', condition: 'if days_to_earnings < 7 then reject', active: true },
    { id: 2, type: 'medium', label: 'IV Rank Minimum', condition: 'if iv_rank < 0.30 then reject', active: true },
    { id: 3, type: 'low', label: 'Spread Width', condition: 'if spread_bps > 50 then reject', active: false },
  ]);

  return (
    <DashboardLayout>
      <div className="max-w-7xl mx-auto p-8 space-y-8">

        {/* Header Section */}
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Trade Journal</h1>
            <p className="text-gray-600 mt-1">Manage guardrails and review performance analysis.</p>
          </div>
          <div className="flex gap-2">
             <span className="px-3 py-1 bg-purple-100 text-purple-800 text-xs font-bold rounded-full uppercase tracking-wide">
               Auto-Learning Active
             </span>
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {[
            { label: 'Win Rate', value: '68.5%', color: 'text-green-600' },
            { label: 'Total Trades', value: '42', color: 'text-gray-900' },
            { label: 'Profit Factor', value: '2.1', color: 'text-blue-600' },
            { label: 'Avg Return', value: '+12%', color: 'text-green-600' },
          ].map((stat, i) => (
            <div key={i} className="bg-white p-4 rounded-xl shadow-sm border border-gray-100">
              <p className="text-xs text-gray-500 font-medium uppercase">{stat.label}</p>
              <p className={`text-2xl font-bold mt-1 ${stat.color}`}>{stat.value}</p>
            </div>
          ))}
        </div>

        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

          {/* Left Column: Active Guardrails */}
          <div className="lg:col-span-2 space-y-6">
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
              <div className="p-6 border-b border-gray-100 bg-gray-50 flex justify-between items-center">
                <h3 className="font-semibold text-gray-800 flex items-center gap-2">
                  🛡️ Active Guardrails
                </h3>
                <button className="text-sm text-blue-600 font-medium hover:underline">+ Add Rule</button>
              </div>

              <div className="p-6 space-y-4">
                {rules.map((rule) => (
                  <div key={rule.id} className={`group flex items-start gap-4 p-4 rounded-lg border transition-all duration-200 ${rule.active ? 'bg-white border-gray-200 shadow-sm hover:shadow-md' : 'bg-gray-50 border-gray-100 opacity-75'}`}>
                    <div className="pt-1">
                      <input
                        type="checkbox"
                        checked={rule.active}
                        onChange={() => {
                           const newRules = rules.map(r => r.id === rule.id ? {...r, active: !r.active} : r);
                           setRules(newRules);
                        }}
                        className="w-5 h-5 text-blue-600 rounded focus:ring-blue-500 border-gray-300 cursor-pointer"
                      />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded uppercase ${
                          rule.type === 'high' ? 'bg-red-100 text-red-700' :
                          rule.type === 'medium' ? 'bg-yellow-100 text-yellow-800' :
                          'bg-green-100 text-green-800'
                        }`}>
                          {rule.type} Priority
                        </span>
                        <span className="text-xs text-gray-400">• Added today</span>
                      </div>
                      <h4 className={`font-medium ${rule.active ? 'text-gray-900' : 'text-gray-500'}`}>
                        {rule.label}
                      </h4>
                      <p className="text-sm text-gray-600 font-mono mt-1 bg-gray-50 px-2 py-1 rounded inline-block">
                        {rule.condition}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right Column: Recent Analysis */}
          <div className="space-y-6">
            <div className="bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl shadow-sm p-6 border border-blue-100">
              <h3 className="font-semibold text-blue-900 mb-4">🧠 AI Insights</h3>
              <ul className="space-y-3">
                <li className="flex gap-3 items-start text-sm text-blue-800">
                  <span className="mt-1">💡</span>
                  <span>You perform <strong>32% better</strong> on Credit Spreads when VIX is above 20.</span>
                </li>
                <li className="flex gap-3 items-start text-sm text-blue-800">
                  <span className="mt-1">⚠️</span>
                  <span>High failure rate detected on <strong>0DTE</strong> trades in the last 7 days.</span>
                </li>
              </ul>
            </div>

            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
              <h3 className="font-semibold text-gray-800 mb-4">Review Queue</h3>
              <div className="space-y-3">
                <div className="p-3 rounded bg-red-50 border border-red-100">
                  <div className="flex justify-between text-sm mb-1">
                    <span className="font-bold text-red-700">TSLA Put Spread</span>
                    <span className="text-red-600">-$450</span>
                  </div>
                  <p className="text-xs text-red-600">Loss exceeds 2x risk. Review needed.</p>
                  <button className="mt-2 w-full text-center py-1.5 text-xs font-medium bg-white border border-red-200 text-red-700 rounded hover:bg-red-50">
                    Start Review
                  </button>
                </div>
              </div>
            </div>
          </div>

        </div>
      </div>
    </DashboardLayout>
  );
}