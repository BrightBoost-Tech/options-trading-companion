'use client';

import { useState, useEffect } from 'react';
import DashboardLayout from '@/components/DashboardLayout';
import { API_URL, TEST_USER_ID } from '@/lib/constants';
import { supabase } from '@/lib/supabase';

export default function JournalPage() {
  const [entries, setEntries] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadJournalEntries();
  }, []);

  const loadJournalEntries = async () => {
    setLoading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };

      if (session?.access_token) {
        headers['Authorization'] = `Bearer ${session.access_token}`;
      } else {
        headers['X-Test-Mode-User'] = TEST_USER_ID;
      }

      const response = await fetch(`${API_URL}/journal/entries`, { headers });

      if (response.ok) {
        const data = await response.json();
        setEntries(data.entries || []);
      } else {
        console.warn(`Journal entries fetch failed: ${response.status}`);
        setEntries([]);
      }
    } catch (error) {
      console.error('Failed to load journal entries:', error);
      setEntries([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <DashboardLayout>
      <div className="max-w-7xl mx-auto p-8 space-y-8">
        <div className="flex justify-between items-center">
          <h1 className="text-3xl font-bold">Trade Journal</h1>
          <button className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
            Log New Trade
          </button>
        </div>

        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="px-6 py-4 border-b">
            <h3 className="text-lg font-semibold">All Entries</h3>
          </div>
          {loading ? (
            <div className="p-12 text-center text-gray-500">Loading entries...</div>
          ) : entries.length === 0 ? (
            <div className="p-12 text-center text-gray-500">
              <p className="text-lg">No trades logged yet.</p>
              <p className="text-sm mt-2">Use the &quot;Log New Trade&quot; button to get started.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Strategy</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Entry Date</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Entry Price</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P&L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {entries.map((entry) => (
                    <tr key={entry.id}>
                      <td className="px-6 py-4 font-medium">{entry.symbol}</td>
                      <td className="px-6 py-4">{entry.strategy}</td>
                      <td className="px-6 py-4">{new Date(entry.entry_date).toLocaleDateString()}</td>
                      <td className="px-6 py-4">${entry.entry_price?.toFixed(2)}</td>
                      <td className="px-6 py-4">
                        <span className={`px-2 py-1 rounded text-xs ${entry.status === 'open' ? 'bg-blue-100 text-blue-800' : 'bg-green-100 text-green-800'}`}>
                          {entry.status}
                        </span>
                      </td>
                      <td className={`px-6 py-4 font-medium ${entry.pnl > 0 ? 'text-green-600' : 'text-red-600'}`}>
                        {entry.pnl ? `$${entry.pnl.toFixed(2)}` : 'N/A'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </DashboardLayout>
  );
}