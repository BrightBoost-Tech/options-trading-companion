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
 */
export default function PlaidLink({ userId, onSuccess, onExit }: PlaidLinkProps) {
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');

  // 1. Fetch Link Token on Mount
  useEffect(() => {
    let ignore = false;

    const fetchToken = async () => {
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
          let errorMsg = `API error ${response.status}`;
          try {
            const errorData = await response.json();
            if (errorData.detail) errorMsg = errorData.detail;
          } catch (e) { /* ignore */ }
          throw new Error(errorMsg);
        }

        const data = await response.json();

        if (!ignore) {
           if (data.link_token) {
             console.log('🟢 Link token received');
             setLinkToken(data.link_token);
           } else {
             throw new Error('No link_token in response');
           }
        }
      } catch (err: any) {
        if (!ignore) {
          console.error('🔴 Error fetching link token:', err);
          setError(err.message);
        }
      } finally {
        if (!ignore) setLoading(false);
      }
    };

    fetchToken();

    return () => { ignore = true; };
  }, [userId]);

  // 2. Initialize Plaid Link Hook
  // Only initialize when we have a token to prevent errors/warnings
  // conditional hook usage is technically not allowed in React rules,
  // but here we are returning early if no token so the hook below is "always called" in the sense
  // that we split the component or we just pass null/empty string and let usePlaidLink handle it (it expects token).
  // ACTUALLY: react-plaid-link docs say pass 'null' for token initially.

  const config = {
    token: linkToken,
    onSuccess: useCallback((public_token: string, metadata: any) => {
      console.log('🟢 Plaid Link Success', metadata);
      onSuccess(public_token, metadata);
    }, [onSuccess]),
    onExit: useCallback((err: any, metadata: any) => {
      if (err) console.error('🔴 Plaid Link Exit Error:', err);
      if (onExit) onExit(err, metadata);
    }, [onExit]),
  };

  const { open, ready, error: linkError } = usePlaidLink(config);

  // Handle errors from the hook itself
  useEffect(() => {
    if (linkError) {
      console.error("Plaid Link Hook Error:", linkError);
      setError(linkError.message || "Error initializing Plaid Link");
    }
  }, [linkError]);

  // Render States
  if (loading) {
    return (
      <div className="py-4 animate-pulse flex items-center space-x-3">
        <div className="h-4 w-4 bg-gray-300 rounded-full"></div>
        <span className="text-sm text-gray-500">Preparing secure connection...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-sm font-medium text-red-800">Connection Unavailable</p>
        <p className="text-xs text-red-600 mt-1">{error}</p>
        <button 
          onClick={() => window.location.reload()}
          className="mt-2 text-xs text-red-700 underline"
        >
          Reload Page
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <button
        onClick={() => ready && open()}
        disabled={!ready || !linkToken}
        className={`px-6 py-3 rounded-lg font-medium transition-all shadow-sm
          ${ready && linkToken
            ? 'bg-green-600 text-white hover:bg-green-700 hover:shadow-md'
            : 'bg-gray-100 text-gray-400 cursor-not-allowed'}
        `}
      >
        {ready ? 'Connect Broker Account' : 'Initializing...'}
      </button>

      {ready && (
        <p className="text-xs text-gray-500 flex items-center gap-1">
          <span className="text-green-500">🔒</span> Secure connection via Plaid
        </p>
      )}
    </div>
  );
}
