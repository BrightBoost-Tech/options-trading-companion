'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import DashboardLayout from '@/components/DashboardLayout';
import SyncHoldingsButton from '@/components/SyncHoldingsButton';
import { formatOptionDisplay } from '@/lib/formatters';
import { fetchWithAuthTimeout, ApiError } from '@/lib/api';
import { RequireAuth } from '@/components/RequireAuth';
import { AuthRequired } from '@/components/AuthRequired';

export default function PortfolioPage() {
  const [holdings, setHoldings] = useState<any[]>([]);
  const [snapshot, setSnapshot] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [authMissing, setAuthMissing] = useState(false);
  const router = useRouter();

  useEffect(() => {
    loadSnapshot();
  }, []);

  const loadSnapshot = async () => {
    setLoading(true);
    try {
      const data = await fetchWithAuthTimeout('/portfolio/snapshot', 10000);
      setSnapshot(data);
      setHoldings(data.holdings || []);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setAuthMissing(true);
        return;
      }
      console.error('Failed to load snapshot:', err);
    } finally {
      setLoading(false);
    }
  };

  // Show auth required UI if authentication is missing
  if (authMissing) {
    return (
      <DashboardLayout>
        <AuthRequired message="Please log in to view your portfolio." />
      </DashboardLayout>
    );
  }

  if (loading && !snapshot) {
    return (
      <DashboardLayout>
        <div className="flex h-[50vh] items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        </div>
      </DashboardLayout>
    );
  }

  // Group holdings by type or other logic if needed. For now, flat list matching dashboard.
  const stockHoldings = holdings.filter(h => !h.option_contract);
  const optionHoldings = holdings.filter(h => h.option_contract);

  return (
    <RequireAuth>
    <DashboardLayout>
      <div className="max-w-7xl mx-auto p-8">
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-3xl font-bold">My Portfolio</h1>
          <div className="flex gap-3">
             <SyncHoldingsButton onSyncComplete={loadSnapshot} />
          </div>
        </div>

        {/* Risk Metrics / Summary Card */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
             <div className="bg-white rounded-lg shadow p-6">
                <h3 className="text-sm font-medium text-gray-500 mb-2">Total Positions</h3>
                <p className="text-3xl font-bold text-gray-900">{holdings.length}</p>
             </div>
             <div className="bg-white rounded-lg shadow p-6">
                 <h3 className="text-sm font-medium text-gray-500 mb-2">Data Source</h3>
                 <p className="text-xl font-semibold text-gray-900 capitalize">
                     {snapshot?.data_source || 'Unknown'}
                 </p>
             </div>
             <div className="bg-white rounded-lg shadow p-6">
                 <h3 className="text-sm font-medium text-gray-500 mb-2">Last Updated</h3>
                 <p className="text-sm text-gray-900">
                     {snapshot?.created_at ? new Date(snapshot.created_at).toLocaleString() : 'Never'}
                 </p>
             </div>
        </div>

        <div className="bg-white rounded-lg shadow overflow-hidden">
            <div className="px-6 py-4 border-b">
              <h3 className="text-lg font-semibold">Current Holdings</h3>
            </div>

            {holdings.length === 0 ? (
              <div className="p-12 text-center text-gray-500">
                <p className="mb-4 text-lg">No positions found.</p>
                <p className="text-sm">Sync via Plaid or Import CSV in Settings to get started.</p>
                <button
                    onClick={() => router.push('/settings')}
                    className="mt-4 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                >
                    Go to Settings
                </button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Qty</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Avg Cost</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Current Price</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">IV Rank</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">DTE</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P&L %</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Value</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {holdings.map((pos, idx) => {
                        const value = (pos.quantity || 0) * (pos.current_price || 0);
                        const isLowDTE = pos.option_contract && pos.dte < 3;

                        const getSeverityClass = (s?: string) => {
                          if (s === 'critical') return 'bg-red-50 text-red-700';
                          if (s === 'warning') return 'bg-yellow-50 text-yellow-700';
                          if (s === 'success') return 'bg-green-50 text-green-700';
                          return '';
                        };

                        return (
                      <tr key={idx} className={`hover:bg-gray-50 ${isLowDTE ? 'bg-red-100' : ''}`}>
                        <td className="px-6 py-4 font-medium">
                          {pos.option_contract ? formatOptionDisplay(pos.symbol) : pos.symbol}
                        </td>
                        <td className="px-6 py-4">
                          <span className={`px-2 py-1 rounded text-xs ${!pos.option_contract ? 'bg-blue-100 text-blue-800' : 'bg-purple-100 text-purple-800'}`}>
                            {!pos.option_contract ? 'Stock' : 'Option'}
                          </span>
                        </td>
                        <td className="px-6 py-4">{pos.quantity}</td>
                        <td className="px-6 py-4">${(pos.cost_basis || 0).toFixed(2)}</td>
                        <td className="px-6 py-4">${(pos.current_price || 0).toFixed(2)}</td>
                        <td className="px-6 py-4">{pos.iv_rank !== null && pos.iv_rank !== undefined ? `${Math.round(pos.iv_rank)}%` : 'N/A'}</td>
                        <td className="px-6 py-4">{pos.dte || 'N/A'}</td>
                        <td className="px-6 py-4">
                          {pos.pnl_percent !== undefined ? (
                            <span className={`px-2 py-1 rounded text-xs font-semibold ${getSeverityClass(pos.pnl_severity)}`}>
                              {pos.pnl_percent.toFixed(1)}%
                            </span>
                          ) : '—'}
                        </td>
                        <td className="px-6 py-4 font-medium">${value.toFixed(2)}</td>
                        <td className="px-6 py-4">
                             <span className={`px-2 py-1 rounded text-xs ${pos.source === 'plaid' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                               {pos.source || 'Manual'}
                             </span>
                        </td>
                      </tr>
                    )})}
                  </tbody>
                </table>
              </div>
            )}
          </div>
      </div>
    </DashboardLayout>
    </RequireAuth>
  );
}
