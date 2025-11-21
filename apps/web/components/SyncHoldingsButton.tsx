'use client';

import { useState } from 'react';
import { supabase } from '@/lib/supabase';
import { API_URL } from '@/lib/constants';

interface SyncHoldingsButtonProps {
  onSyncComplete?: () => void;
}

export default function SyncHoldingsButton({ onSyncComplete }: SyncHoldingsButtonProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastSynced, setLastSynced] = useState<string | null>(null);

  const handleSync = async () => {
    setLoading(true);
    setError(null);

    try {
      const { data: { session } } = await supabase.auth.getSession();

      if (!session) {
        throw new Error("Not authenticated");
      }

      const response = await fetch(`${API_URL}/plaid/sync_holdings`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${session.access_token}`
        }
      });

      if (!response.ok) {
         const errorData = await response.json().catch(() => ({}));
         throw new Error(errorData.detail || 'Sync failed');
      }

      const data = await response.json();
      setLastSynced(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
      if (onSyncComplete) onSyncComplete();

    } catch (err: any) {
      console.error('Sync error:', err);
      setError(err.message || 'Failed to sync');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
       {lastSynced && (
        <span className="text-xs text-gray-500 hidden sm:inline">
          Synced {lastSynced}
        </span>
      )}
      {error && (
         <span className="text-xs text-red-500 hidden sm:inline" title={error}>
           Failed
         </span>
      )}
      <button
        onClick={handleSync}
        disabled={loading}
        className="flex items-center gap-1 px-3 py-1.5 bg-white border border-gray-300 rounded-md text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50 shadow-sm"
      >
        <svg
          className={`w-4 h-4 ${loading ? 'animate-spin text-blue-600' : 'text-gray-500'}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        <span>{loading ? 'Syncing...' : 'Sync'}</span>
      </button>
    </div>
  );
}
