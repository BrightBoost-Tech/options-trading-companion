'use client';
 
import { useState } from 'react';
import { createClientComponentClient } from '@supabase/auth-helpers-nextjs';
import { useRouter } from 'next/navigation';

export default function SyncHoldingsButton() {
  const [loading, setLoading] = useState(false);
  const supabase = createClientComponentClient();
  const router = useRouter();
 
  const handleSync = async () => {
    setLoading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      
      if (!session) {
        console.error("No session found");
        return;
      }
 
      const response = await fetch('http://localhost:8000/plaid/sync_holdings', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': \`Bearer \${session.access_token}\`,
        },
      });
 
      if (!response.ok) {
        throw new Error('Failed to sync holdings');
      }
 
      // Refresh the current route to update server components or trigger re-fetches
      router.refresh();
      
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
