'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { usePlaidLink, PlaidLinkOptions } from 'react-plaid-link';
import { API_URL } from '@/lib/constants';
import { logEvent } from '@/lib/analytics';

interface PlaidLinkProps {
  userId: string;
  onSuccess: (public_token: string, metadata: any) => void;
  onExit?: (error: any, metadata: any) => void;
}

// -- HELPER: Manually Load Plaid Script Singleton --
// This ensures we never fetch the script twice, regardless of React renders.
const loadPlaidScript = () => {
  return new Promise<void>((resolve, reject) => {
    // 1. If window.Plaid already exists, we are good.
    if ((window as any).Plaid) {
      resolve();
      return;
    }

    // 2. If the script tag exists but is loading, attach listener
    const existingScript = document.getElementById('plaid-link-initialize');
    if (existingScript) {
      existingScript.addEventListener('load', () => resolve());
      existingScript.addEventListener('error', () => reject(new Error('Plaid script failed to load')));
      return;
    }

    // 3. Inject script manually
    const script = document.createElement('script');
    script.id = 'plaid-link-initialize';
    script.src = 'https://cdn.plaid.com/link/v2/stable/link-initialize.js';
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Failed to load Plaid script'));
    document.body.appendChild(script);
  });
};

/**
 * Headless Component
 * Purely responsible for OPENING the modal.
 * It assumes the script is ALREADY loaded by the parent.
 */
function PlaidLinkHeadless({ token, onSuccess, onExit, onCleanup }: {
    token: string,
    onSuccess: (public_token: string, metadata: any) => void,
    onExit: ((error: any, metadata: any) => void) | undefined,
    onCleanup: () => void
}) {
    // Config: We rely on the fact that window.Plaid exists.
    // The hook will detect it and skip internal script injection.
    const config: PlaidLinkOptions = {
        token,
        onSuccess: useCallback((public_token: string, metadata: any) => {
            onSuccess(public_token, metadata);
            onCleanup();
        }, [onSuccess, onCleanup]),
        onExit: useCallback((err: any, metadata: any) => {
            if (err) {
                logEvent({
                    eventName: 'plaid_link_error',
                    category: 'system',
                    properties: { error_code: err.error_code, error_message: err.error_message }
                });
            }
            if (onExit) onExit(err, metadata);
            onCleanup();
        }, [onExit, onCleanup]),
    };

    const { open, ready, error } = usePlaidLink(config);

    // Auto-open
    useEffect(() => {
        if (ready && !error) {
            open();
        }
    }, [ready, error, open]);

    if (error) {
        return <div className="text-red-600 text-xs mt-2">Error initializing Link: {error.message}</div>;
    }

    return null;
}

/**
 * Main Component
 * Orchestrates:
 * 1. Fetching Link Token
 * 2. ensuring Script is Loaded (Singleton)
 * 3. Mounting the Headless component
 */
export default function PlaidLink({ userId, onSuccess, onExit }: PlaidLinkProps) {
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [scriptLoaded, setScriptLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');

  const fetchToken = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError('');

    try {
      logEvent({ eventName: 'plaid_link_started', category: 'ux' });

      // Step A: Load Script & Fetch Token in Parallel
      console.log('🟡 Initializing Plaid Connection...');
      
      const scriptPromise = loadPlaidScript();
      
      const tokenPromise = fetch(`${API_URL}/plaid/create_link_token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });

      // Wait for both
      const [_, response] = await Promise.all([scriptPromise, tokenPromise]);

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `API Error ${response.status}`);
      }

      const data = await response.json();
      if (!data.link_token) throw new Error('No link_token in response');

      console.log('🟢 TOKEN VALUE:', data.link_token);
      setScriptLoaded(true);
      setLinkToken(data.link_token);

    } catch (err: any) {
      console.error('🔴 Initialization Error:', err);
      setError(err.message || 'Connection failed');
    } finally {
      setLoading(false);
    }
  }, [userId]);

  const cleanup = useCallback(() => {
      setLinkToken(null);
      // We do NOT reset scriptLoaded. Once loaded, it stays loaded.
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
         We only mount Headless if we have the TOKEN *AND* the SCRIPT is ready.
         This prevents the hook from trying to inject the script itself.
      */}
      {linkToken && scriptLoaded && (
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
