'use client';

import { useEffect, useState } from 'react';
import { usePlaidLink } from 'react-plaid-link';
import { API_URL } from '@/lib/constants';

export default function PlaidLink({ userId, onSuccess, onExit }: any) {
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    console.log('🟡 PlaidLink mounted, userId:', userId);
    createLinkToken();
  }, [userId]);

  const createLinkToken = async () => {
    setLoading(true);
    setError('');
    
    try {
      console.log('🟡 Fetching link token...');
      
      const response = await fetch(`${API_URL}/plaid/create_link_token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });

      console.log('🟡 Response status:', response.status);
      
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
      console.log('🟢 Link token received!');
      
      if (data.link_token) {
        console.log('Token type:', typeof data.link_token); // Debug type
        setLinkToken(data.link_token);
      } else {
        throw new Error('No link_token in response');
      }
    } catch (err: any) {
      console.error('🔴 Error:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // CRITICAL: Always provide a valid config to usePlaidLink
  // Pass token as null initially, it will be updated when token arrives
  const { open, ready } = usePlaidLink({
    token: linkToken,
    onSuccess: (public_token: string, metadata: any) => {
      console.log('🟢 Plaid success!', metadata);
      onSuccess(public_token, metadata);
    },
    onExit: (error, metadata) => {
      console.log('🔴 Plaid exit', { error, metadata });
      // If there's an initialization error, it will appear here
      if (error) {
          console.error('❌ Plaid Link Error:', error);
          // Optionally bubble up error to parent or show in UI
      }
      if (onExit) onExit(error, metadata);
    },
  });

  console.log('🟡 Render:', { loading, error, hasToken: !!linkToken, ready });

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
          onClick={createLinkToken}
          className="mt-3 text-sm text-red-700 underline hover:text-red-900"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <button
        onClick={() => {
          console.log('🟢 Button clicked! Ready:', ready);
          console.log('Token check:', { type: typeof linkToken, value: linkToken ? linkToken.substring(0, 10) + '...' : null });
          if (ready && linkToken) {
            console.log('🟢 Opening Plaid modal...');
            open();
          } else {
            alert('Plaid is not ready yet. Please wait a moment...');
          }
        }}
        disabled={!ready || !linkToken}
        className="px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed font-medium transition-colors shadow-lg"
      >
        {!linkToken ? '⏳ Initializing...' : ready ? '✅ Connect Broker Account' : '⏳ Loading...'}
      </button>
      
      {linkToken && ready && (
        <p className="text-xs text-gray-600">
          🔒 Ready to connect • Click above to open secure Plaid window
        </p>
      )}
    </div>
  );
}
