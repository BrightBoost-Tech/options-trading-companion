'use client';

import { useState, useEffect } from 'react';
import { supabase } from '@/lib/supabase';
import { useRouter } from 'next/navigation';
import DashboardLayout from '@/components/DashboardLayout';
import SyncHoldingsButton from '@/components/SyncHoldingsButton';
import { API_URL, TEST_USER_ID } from '@/lib/constants';

interface FetchOptions extends RequestInit {
  timeout?: number;
}

// Helper to prevent hanging indefinitely (reused from Dashboard)
const fetchWithTimeout = async (resource: RequestInfo, options: FetchOptions = {}) => {
  const { timeout = 15000, ...rest } = options;

  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);

  const response = await fetch(resource, {
    ...rest,
    signal: controller.signal
  });

  clearTimeout(id);
  return response;
};

export default function PortfolioPage() {
  const [user, setUser] = useState<any>(null);
  const [holdings, setHoldings] = useState<any[]>([]);
  const [snapshot, setSnapshot] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    loadUser();
  }, []);

  useEffect(() => {
    if (user) {
      loadSnapshot();
    }
  }, [user]);

  const loadUser = async () => {
    const { data: { user } } = await supabase.auth.getUser();

    if (user) {
        setUser(user);
    } else {
        // Test Mode / Dev Fallback
        // If no user found, we can assume test mode if explicitly checking or if we want to support
        // unauthenticated viewing in dev.
        // For the purpose of the "Test Mode" requirement:
        console.log("⚠️ No user found, using Test Mode user.");
        setUser({ id: TEST_USER_ID, email: 'test@example.com' });
    }
  };

  const loadSnapshot = async () => {
    setLoading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      
      let headers: any = {};
      if (session) {
          headers['Authorization'] = `Bearer ${session.access_token}`;
      } else {
           // Test Mode Header
           headers['X-Test-Mode-User'] = TEST_USER_ID;
      }

      const response = await fetchWithTimeout(`${API_URL}/portfolio/snapshot`, {
         headers: headers,
         timeout: 10000
      });

      if (response.ok) {
        const data = await response.json();
        setSnapshot(data);
        setHoldings(data.holdings || []);
      }
    } catch (err) {
      console.error('Failed to load snapshot:', err);
    } finally {
      setLoading(false);
    }
  };

  if (!user) return <div className="p-8">Loading...</div>;

  // Group holdings by type or other logic if needed. For now, flat list matching dashboard.
  const stockHoldings = holdings.filter(h => !h.option_contract);
  const optionHoldings = holdings.filter(h => h.option_contract);

  return (
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
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Value</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {holdings.map((pos, idx) => {
                        const value = (pos.quantity || 0) * (pos.current_price || 0);
                        const isLowDTE = pos.option_contract && pos.dte < 3;
                        return (
                      <tr key={idx} className={`hover:bg-gray-50 ${isLowDTE ? 'bg-red-100' : ''}`}>
                        <td className="px-6 py-4 font-medium">{pos.symbol}</td>
                        <td className="px-6 py-4">
                          <span className={`px-2 py-1 rounded text-xs ${!pos.option_contract ? 'bg-blue-100 text-blue-800' : 'bg-purple-100 text-purple-800'}`}>
                            {!pos.option_contract ? 'Stock' : 'Option'}
                          </span>
                        </td>
                        <td className="px-6 py-4">{pos.quantity}</td>
                        <td className="px-6 py-4">${(pos.cost_basis || 0).toFixed(2)}</td>
                        <td className="px-6 py-4">${(pos.current_price || 0).toFixed(2)}</td>
                        <td className="px-6 py-4">{pos.iv_rank ? `${pos.iv_rank.toFixed(0)}%` : 'N/A'}</td>
                        <td className="px-6 py-4">{pos.dte || 'N/A'}</td>
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
  );
}
