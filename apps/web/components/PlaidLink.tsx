'use client';

import { useEffect, useState, useRef } from 'react';
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
  const { open, ready } = usePlaidLink({
    token,
    onSuccess: (public_token, metadata) => {
      console.log('🟢 Plaid success!', metadata);
      onSuccess(public_token, metadata);
    },
    onExit: (error, metadata) => {
      console.log('🔴 Plaid exit', { error, metadata });
      if (error) {
        console.error('❌ Plaid Link Error:', error);
      }
      if (onExit) onExit(error, metadata);
    },
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

  // Refs to handle strict mode double-invocation
  const hasFetchedToken = useRef(false);

  useEffect(() => {
    let ignore = false;

    const fetchToken = async () => {
      if (!userId) return;
      
      // Prevent redundant fetches if token is already set or processed
      if (hasFetchedToken.current) return;
      hasFetchedToken.current = true;

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
      // Note: We do NOT reset hasFetchedToken.current here because in Strict Mode
      // we want to persist the fact that we have already initiated a fetch
      // during the first mount, so the second mount (simulated) skips it.
    };
  }, [userId]);

  // Manual retry handler resets the ref
  const handleRetry = () => {
    hasFetchedToken.current = false;
    // Trigger re-run by resetting state or calling fetch logic?
    // Since we depend on useEffect, we can't easily re-trigger it without changing dependency or key.
    // So we extract logic or just brute force it.
    // Simpler: force re-mount or direct call.
    // Let's just direct call but we need to manage state.
    // Actually, best to just reset ref and let user click retry which calls a function.
    // But wait, useEffect won't re-run just because I called a function.
    // I'll just reload the page? No.
    // I'll extract fetch logic?
    window.location.reload(); // Simplest for retry in this context or
    // ideally we reset 'error' state which triggers re-render but not useEffect if deps same.
    // So we need to move fetch logic out or use a counter.
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
