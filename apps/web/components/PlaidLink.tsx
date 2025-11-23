'use client';

import { useEffect, useState, useCallback } from 'react';
import { usePlaidLink, PlaidLinkOptions } from 'react-plaid-link';
import { API_URL } from '@/lib/constants';

interface PlaidLinkProps {
  userId: string;
  onSuccess: (public_token: string, metadata: any) => void;
  onExit?: (error: any, metadata: any) => void;
}

// -- HEADLESS COMPONENT --
// This component is strictly responsible for the Plaid Hook lifecycle.
// It is only rendered when a valid 'token' exists.
function PlaidLinkHeadless({ 
  token, 
  onSuccess, 
  onExit,
  onCleanup 
}: {
    token: string,
    onSuccess: (public_token: string, metadata: any) => void,
    onExit: (error: any, metadata: any) => void,
    onCleanup: () => void
}) {
    const config: PlaidLinkOptions = {
        token,
        onSuccess: useCallback((public_token: string, metadata: any) => {
            // 1. Pass data up
            onSuccess(public_token, metadata);
            // 2. Unmount this component to clean up the hook
            onCleanup();
        }, [onSuccess, onCleanup]),
        onExit: useCallback((err: any, metadata: any) => {
            if (onExit) onExit(err, metadata);
            onCleanup();
        }, [onExit, onCleanup]),
    };

    const { open, ready, error } = usePlaidLink(config);

    // Auto-open modal when script is loaded and ready
    useEffect(() => {
        if (ready && !error) {
            open();
        }
    }, [ready, error, open]);

    if (error) {
        return <div className="text-red-600 text-xs mt-2">Error initializing Link: {error.message}</div>;
    }

    return null; // Invisible component
}

// -- MAIN COMPONENT --
export default function PlaidLink({ userId, onSuccess, onExit }: PlaidLinkProps) {
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');

  // Fetch token only on user interaction
  const fetchToken = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError('');

    try {
      console.log('🟡 Fetching link token...');
      const response = await fetch(`${API_URL}/plaid/create_link_token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `API Error: ${response.status}`);
      }

      const data = await response.json();
      if (!data.link_token) throw new Error('No link_token in response');

      console.log('🟢 Link token received');
      setLinkToken(data.link_token);

    } catch (err: any) {
      console.error('🔴 Error fetching token:', err);
      setError(err.message || 'Connection failed');
    } finally {
      setLoading(false);
    }
  }, [userId]);

  // Cleanup handler to reset state and unmount the headless component
  const handleCleanup = useCallback(() => {
      setLinkToken(null);
  }, []);

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-sm font-medium text-red-800">Connection Failed</p>
        <p className="text-xs text-red-600 mt-1">{error}</p>
        <button 
          onClick={() => { setError(''); setLinkToken(null); }}
          className="mt-2 text-xs text-red-700 underline"
        >
          Try Again
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <button
        onClick={fetchToken}
        disabled={loading || !!linkToken}
        className={`px-6 py-3 rounded-lg font-medium transition-all shadow-sm flex items-center gap-2
          ${loading || linkToken
            ? 'bg-gray-100 text-gray-500 cursor-wait'
            : 'bg-green-600 text-white hover:bg-green-700 hover:shadow-md'}
        `}
      >
        {loading || linkToken ? (
           <>
             <div className="h-4 w-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin"></div>
             <span>{loading ? 'Preparing...' : 'Opening Plaid...'}</span>
           </>
        ) : (
           'Connect Broker Account'
        )}
      </button>

      <div className="flex flex-col gap-1">
          <p className="text-xs text-gray-500 flex items-center gap-1">
            <span className="text-green-500">🔒</span> Secure connection via Plaid
          </p>
      </div>

      {/* 
         Mounting this component triggers the script injection via usePlaidLink.
         We only do this AFTER we have the token.
      */}
      {linkToken && (
          <PlaidLinkHeadless
              token={linkToken}
              onSuccess={onSuccess}
              onExit={onExit}
              onCleanup={handleCleanup}
          />
      )}
    </div>
  );
}
