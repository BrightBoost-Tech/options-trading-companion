'use client';

import { useEffect, useState, useCallback } from 'react';
import { usePlaidLink } from 'react-plaid-link';
import { API_URL } from '@/lib/constants';

interface PlaidLinkProps {
  userId: string;
  onSuccess: (public_token: string, metadata: any) => void;
  onExit?: (error: any, metadata: any) => void;
}

/**
 * PlaidLink Component
 *
 * Uses react-plaid-link to handle the integration.
 * Ensures single script loading and proper lifecycle management.
 * Initiates connection ONLY on user interaction.
 */
export default function PlaidLink({ userId, onSuccess, onExit }: PlaidLinkProps) {
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [loadingToken, setLoadingToken] = useState(false);
  const [error, setError] = useState<string>('');

  // 1. Fetch Link Token ON CLICK
  const fetchToken = useCallback(async () => {
    if (!userId) return;

    setLoadingToken(true);
    setError('');

    try {
      console.log('🟡 Fetching link token...');
      const response = await fetch(`${API_URL}/plaid/create_link_token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });

      if (!response.ok) {
        let errorMsg = `API error ${response.status}`;
        try {
          const errorData = await response.json();
          if (errorData.detail) errorMsg = errorData.detail;
        } catch (e) { /* ignore */ }
        throw new Error(errorMsg);
      }

      const data = await response.json();

      if (data.link_token) {
        console.log('🟢 Link token received');
        setLinkToken(data.link_token);
      } else {
        throw new Error('No link_token in response');
      }
    } catch (err: any) {
      console.error('🔴 Error fetching link token:', err);
      setError(err.message);
    } finally {
      setLoadingToken(false);
    }
  }, [userId]);


  // 2. Initialize Plaid Link Hook
  // Only initialize when we have a token
  const config = {
    token: linkToken,
    onSuccess: useCallback((public_token: string, metadata: any) => {
      console.log('🟢 Plaid Link Success', metadata);
      // Reset token to prevent re-use
      setLinkToken(null);
      onSuccess(public_token, metadata);
    }, [onSuccess]),
    onExit: useCallback((err: any, metadata: any) => {
      if (err) console.error('🔴 Plaid Link Exit Error:', err);
      // Reset token so user can try again with a fresh one
      setLinkToken(null);
      if (onExit) onExit(err, metadata);
    }, [onExit]),
  };

  const { open, ready, error: linkError } = usePlaidLink(config);

  // Auto-open when ready (since user already clicked "Connect")
  useEffect(() => {
      if (ready && linkToken) {
          open();
      }
  }, [ready, linkToken, open]);

  // Handle errors from the hook itself
  useEffect(() => {
    if (linkError) {
      console.error("Plaid Link Hook Error:", linkError);
      setError(linkError.message || "Error initializing Plaid Link");
      setLinkToken(null); // Reset on error
    }
  }, [linkError]);

  // Render States

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

  // Initial State: Button to start flow
  return (
    <div className="space-y-3">
      <button
        onClick={fetchToken}
        disabled={loadingToken || !!linkToken}
        className={`px-6 py-3 rounded-lg font-medium transition-all shadow-sm flex items-center gap-2
          ${loadingToken || linkToken
            ? 'bg-gray-100 text-gray-500 cursor-wait'
            : 'bg-green-600 text-white hover:bg-green-700 hover:shadow-md'}
        `}
      >
        {loadingToken || linkToken ? (
           <>
             <div className="h-4 w-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin"></div>
             <span>Connecting...</span>
           </>
        ) : (
           'Connect Broker Account'
        )}
      </button>

      {/* Helper text */}
      <div className="flex flex-col gap-1">
          <p className="text-xs text-gray-500 flex items-center gap-1">
            <span className="text-green-500">🔒</span> Secure connection via Plaid
          </p>
      </div>
    </div>
  );
}
