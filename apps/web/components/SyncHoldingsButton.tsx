'use client';

import { useState } from 'react';
import { fetchWithAuth, ApiError } from '@/lib/api';
import { Button } from '@/components/ui/button';
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
      await fetchWithAuth(`/plaid/sync_holdings`, {
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

       <Button
        variant="outline"
        size="sm"
        onClick={handleSync}
        loading={loading}
        className={className}
      >
        {loading ? 'Syncing...' : (
            <>
                <RefreshCw className="mr-2 h-3.5 w-3.5 text-gray-500" aria-hidden="true" />
                Sync
            </>
        )}
      </Button>
    </div>
  );
}
