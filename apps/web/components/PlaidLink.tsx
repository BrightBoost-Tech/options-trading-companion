'use client';

import { useEffect, useState, useCallback } from 'react';
import { usePlaidLink } from 'react-plaid-link';
import { API_URL } from '@/lib/constants';

interface PlaidLinkProps {
  userId: string;
  onSuccess: (public_token: string, metadata: any) => void;
  onExit?: (error: any, metadata: any) => void;
}

// Inner component that only mounts when we have a token
// This ensures usePlaidLink is only called with a valid token, preventing multiple initializations
function PlaidButton({ token, onSuccess, onExit }: { token: string } & Omit<PlaidLinkProps, 'userId'>) {
  const handleSuccess = useCallback((public_token: string, metadata: any) => {
    console.log('🟢 Plaid success!', metadata);
    onSuccess(public_token, metadata);
  }, [onSuccess]);

  const handleExit = useCallback((error: any, metadata: any) => {
    console.log('🔴 Plaid exit', { error, metadata });
    if (error) {
      console.error('❌ Plaid Link Error:', error);
    }
    if (onExit) onExit(error, metadata);
  }, [onExit]);

  const { open, ready } = usePlaidLink({
    token,
    onSuccess: handleSuccess,
    onExit: handleExit,
  });

  return (
    <div className="space-y-3">
      <button
        onClick={() => ready && open()}
        disabled={!ready}
        className="px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed font-medium transition-colors shadow-lg"
      >
        {ready ? '✅ Connect Broker Account' : '⏳ Loading Plaid...'}
      </button>

      {ready && (
        <p className="text-xs text-gray-600">
          🔒 Ready to connect • Click above to open secure Plaid window
        </p>
      )}
    </div>
  );
}

export default function PlaidLink({ userId, onSuccess, onExit }: PlaidLinkProps) {
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    let ignore = false;

    const fetchToken = async () => {
      if (!userId) return;
      
      // Reset state for new fetch
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
            if (errorData.detail) {
              errorMsg = errorData.detail;
            }
          } catch (e) {
            // ignore json parse error
          }
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
          console.error('🔴 Error:', err);
          setError(err.message);
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    };

    fetchToken();

    return () => {
      ignore = true;
    };
  }, [userId]);

  // Manual retry handler
  const handleRetry = () => {
    // To trigger a retry, we can't easily re-run the effect unless deps change.
    // A simple way is to reload, but that's heavy.
    // Better: expose a state that triggers re-fetch.
    // For now, sticking to the simplest "Refresh Page" or just acknowledge retry limitation.
    // Or we can add a `retryCount` to state and dependencies.
    window.location.reload();
  };

  if (loading) {
    return (
      <div className="py-4">
        <div className="animate-pulse flex items-center space-x-3">
          <div className="h-5 w-5 bg-green-500 rounded-full"></div>
          <span className="text-sm text-gray-600">Connecting to Plaid...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-sm font-medium text-red-800">❌ Connection Error</p>
        <p className="text-xs text-red-600 mt-1">{error}</p>
        <button 
          onClick={handleRetry}
          className="mt-3 text-sm text-red-700 underline hover:text-red-900"
        >
          Retry
        </button>
      </div>
    );
  }

  // Only render PlaidButton when we have a token
  if (!linkToken) {
    return null;
  }

  return (
    <PlaidButton
      token={linkToken}
      onSuccess={onSuccess}
      onExit={onExit}
    />
  );
}
