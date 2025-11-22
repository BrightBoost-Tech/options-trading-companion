'use client';
 
import { useState } from 'react';
import { supabase } from '@/lib/supabase';
import { useRouter } from 'next/navigation';
import { API_URL } from '@/lib/constants';

export default function SyncHoldingsButton({ onSyncComplete }: { onSyncComplete?: () => void }) {
  const [loading, setLoading] = useState(false);
  const router = useRouter();
 
  const handleSync = async () => {
    setLoading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      
      let headers: any = {
        'Content-Type': 'application/json'
      };

      if (session) {
         headers['Authorization'] = `Bearer ${session.access_token}`;
      } else {
         console.warn("No session found, using test mode header if configured.");
         headers['X-Test-Mode-User'] = 'test-user-123';
      }
 
      const response = await fetch(`${API_URL}/plaid/sync_holdings`, {
        method: 'POST',
        headers: headers,
      });
 
      if (!response.ok) {
        // Check if it's a 404 (meaning no items to sync) which is fine
        if (response.status === 404) {
            console.log("No Plaid items found to sync, likely manual/csv user.");
        } else {
            throw new Error(`Failed to sync holdings: ${response.statusText}`);
        }
      }
 
      // Refresh the current route to update server components or trigger re-fetches
      router.refresh();
      if (onSyncComplete) {
          onSyncComplete();
      }
      
    } catch (error) {
      console.error("Sync Error:", error);
      alert("Error syncing holdings. Check console.");
    } finally {
      setLoading(false);
    }
  };
 
  return (
    <button
      onClick={handleSync}
      disabled={loading}
      className="bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded transition-colors flex items-center gap-2 disabled:opacity-50"
    >
      {loading ? (
        <span className="animate-spin">⟳</span>
      ) : (
        <span>↻</span>
      )}
      {loading ? 'Syncing...' : 'Sync Holdings'}
    </button>
  );
}
