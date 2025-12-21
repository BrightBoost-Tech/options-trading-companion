'use client';

import { useState } from 'react';
import { fetchWithAuth, ApiError } from '@/lib/api';
import { API_URL } from '@/lib/constants';
import { cn } from '@/lib/utils';
import { RefreshCw } from 'lucide-react';

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
      await fetchWithAuth(`${API_URL}/plaid/sync_holdings`, {
        method: 'POST'
      });

      setStatusMsg(`Synced ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`);
      if (onSyncComplete) onSyncComplete();

    } catch (err: any) {
      // Specific handling for "No Plaid account" (404) from ApiError
      if (err instanceof ApiError && err.status === 404) {
        console.warn("Plaid sync skipped: No linked account.");
        setStatusMsg("No Plaid linked");
        if (onSyncComplete) onSyncComplete();
        return;
      }

      console.error('Sync error:', err);
      setError(err.message || 'Failed to sync');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
       {/* Status Messages - improved visibility and a11y */}
       <div role="status" aria-live="polite" className="text-xs flex items-center">
          {statusMsg && <span className="text-gray-500 mr-2">{statusMsg}</span>}
          {error && <span className="text-red-500 mr-2" title={error}>{error}</span>}
       </div>

       {/* Button - using native element with existing styles but improved a11y */}
       <button
        onClick={handleSync}
        disabled={loading}
        aria-busy={loading}
        className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-300 rounded-md text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50 shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400",
            className
        )}
      >
        <RefreshCw
            className={cn(
                "w-3.5 h-3.5",
                loading ? "animate-spin text-blue-600" : "text-gray-500"
            )}
            aria-hidden="true"
        />
        <span>{loading ? 'Syncing...' : 'Sync'}</span>
      </button>
    </div>
  );
}
