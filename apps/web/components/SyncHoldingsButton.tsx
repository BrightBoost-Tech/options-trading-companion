'use client';

import { useState } from 'react';
import { supabase } from '@/lib/supabase';
import { API_URL } from '@/lib/constants';
import { cn } from '@/lib/utils';

interface SyncHoldingsButtonProps {
  onSyncComplete?: () => void;
  className?: string;
}

export default function SyncHoldingsButton({ onSyncComplete, className }: SyncHoldingsButtonProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const handleSync = async () => {
    setLoading(true);
    setError(null);
    setStatusMsg(null);

    try {
      const { data: { session } } = await supabase.auth.getSession();

      // Define Headers
      const headers: Record<string, string> = {
          'Content-Type': 'application/json'
      };

      if (session) {
          headers['Authorization'] = `Bearer ${session.access_token}`;
      } else {
          // 🛠️ FIX: If no session, send the Test User ID header
          headers['X-Test-Mode-User'] = '75ee12ad-b119-4f32-aeea-19b4ef55d587';
      }

      const response = await fetch(`${API_URL}/plaid/sync_holdings`, {
        method: 'POST',
        headers: headers
      });

      if (!response.ok) {
         const errorData = await response.json().catch(() => ({}));

         // Specific handling for "No Plaid account" (404)
         if (response.status === 404) {
            console.warn("Plaid sync skipped: No linked account.");
            setStatusMsg("No Plaid linked");
            // Even if Plaid is missing, we treat this as "done" so the table can refresh
            // (e.g. if CSV was uploaded but table is stale)
            if (onSyncComplete) onSyncComplete();
            return;
         }

         throw new Error(errorData.detail || 'Sync failed');
      }

      const data = await response.json();
      setStatusMsg(`Synced ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`);
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
       {statusMsg && (
        <span className="text-xs text-gray-500 hidden sm:inline">
          {statusMsg}
        </span>
      )}
      {error && (
         <span className="text-xs text-red-500 hidden sm:inline" title={error}>
           {error}
         </span>
      )}
      <button
        onClick={handleSync}
        disabled={loading}
        className={cn("flex items-center gap-1 px-3 py-1.5 bg-white border border-gray-300 rounded-md text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50 shadow-sm", className)}
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
