'use client';

import { useEffect, useState, useCallback } from 'react';
import { usePlaidLink, PlaidLinkOptions } from 'react-plaid-link';
import { API_URL } from '@/lib/constants';

interface PlaidLinkProps {
  userId: string;
  onSuccess: (public_token: string, metadata: any) => void;
  onExit?: (error: any, metadata: any) => void;
}

/**
 * Headless Component
 * 
 * This component is only mounted AFTER we have a link_token.
 * Its sole job is to initialize the Plaid hook and open the modal immediately.
 */
function PlaidLinkHeadless({ token, onSuccess, onExit, onCleanup }: {
    token: string,
    onSuccess: (public_token: string, metadata: any) => void,
    onExit: (error: any, metadata: any) => void,
    onCleanup: () => void
}) {
    const config: PlaidLinkOptions = {
        token,
        onSuccess: (public_token, metadata) => {
            onSuccess(public_token, metadata);
            onCleanup(); // Unmount this component
        },
        onExit: (err, metadata) => {
            if (onExit) onExit(err, metadata);
            onCleanup(); // Unmount this component
        },
    };

    const { open, ready, error } = usePlaidLink(config);

    // Auto-open when ready
    useEffect(() => {
        if (ready && !error) {
            open();
        }
    }, [ready, error, open]);

    if (error) {
        return <div className="text-red-600 text-xs mt-2">Error initializing Link: {error.message}</div>;
    }

    return null; // This component is invisible
}

/**
 * Main PlaidLink Component
 * 
 * Manages the "Connect" UI state and the API call to fetch the token.
 * Does NOT load the Plaid script until the token is successfully retrieved.
 */
export default function PlaidLink({ userId, onSuccess, onExit }: PlaidLinkProps) {
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string>('');

  const handleFetchToken = useCallback(async () => {
    if (!userId) return;

    setIsLoading(true);
    setFetchError('');

    try {
      console.log('🟡 Fetching Plaid Link Token...');
      const response = await fetch(`${API_URL}/plaid/create_link_token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `API error ${response.status}`);
      }

      const data = await response.json();

      if (data.link_token) {
        console.log('🟢 Link token received');
        setLinkToken(data.link_token);
      } else {
        throw new Error('No link_token returned from API');
      }
    } catch (err: any) {
      console.error('🔴 Error fetching link token:', err);
      setFetchError(err.message || 'Failed to initialize connection');
    } finally {
      setIsLoading(false);
    }
  }, [userId]);

  const cleanup = useCallback(() => {
      setLinkToken(null);
  }, []);

  // If initial fetch failed, show error UI
  if (fetchError) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-sm font-medium text-red-800">Connection Initialization Failed</p>
        <p className="text-xs text-red-600 mt-1">{fetchError}</p>
        <button 
          onClick={() => { setFetchError(''); setLinkToken(null); }}
          className="mt-2 text-xs text-red-700 underline hover:text-red-800"
        >
          Try Again
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={handleFetchToken}
        disabled={isLoading || !!linkToken}
        className={`px-6 py-3 rounded-lg font-medium transition-all shadow-sm flex items-center gap-2
          ${isLoading || linkToken
            ? 'bg-gray-100 text-gray-500 cursor-wait'
            : 'bg-green-600 text-white hover:bg-green-700 hover:shadow-md'}
        `}
      >
        {isLoading || linkToken ? (
           <>
             <div className="h-4 w-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin"></div>
             <span>
                 {isLoading ? 'Preparing Secure Connection...' : 'Opening Plaid...'}
             </span>
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
        This is the Key Fix:
        We only render the component (and thus load the script) 
        when we have a valid linkToken.
      */}
      {linkToken && (
          <PlaidLinkHeadless
              token={linkToken}
              onSuccess={onSuccess}
              onExit={onExit}
              onCleanup={cleanup}
          />
      )}
    </div>
  );
}
