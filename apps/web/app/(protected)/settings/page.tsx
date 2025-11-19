'use client';

import { useState } from 'react';
import PlaidLink from '@/components/PlaidLink';

export default function SettingsPage() {
  const [showPlaidConnect, setShowPlaidConnect] = useState(false);
  
  // Use a fake user ID for testing
  const testUserId = 'test-user-123';

  const handleConnectClick = () => {
    console.log('🔵 Connect clicked');
    alert('Showing Plaid connection...');
    setShowPlaidConnect(true);
  };

  console.log('🔵 Render - showPlaidConnect:', showPlaidConnect);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto p-8">
        <h1 className="text-3xl font-bold mb-6">Settings (Test Mode)</h1>

        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-semibold mb-4">🔗 Broker Connection</h2>
          
          <p className="text-sm text-gray-500 mb-4">
            Debug: showPlaidConnect = {showPlaidConnect ? 'TRUE' : 'FALSE'}
          </p>
          
          {!showPlaidConnect ? (
            <div>
              <p className="text-gray-600 mb-4">Connect your broker via Plaid</p>
              <button
                onClick={handleConnectClick}
                className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
              >
                Connect Broker (Test Mode)
              </button>
            </div>
          ) : (
            <div className="bg-green-50 border-2 border-green-500 p-6 rounded-lg">
              <h3 className="text-lg font-semibold mb-4">✅ Connect Your Brokerage</h3>
              <p className="text-sm mb-4">User ID: {testUserId}</p>
              
              <div className="bg-white p-4 border-2 border-purple-300 rounded">
                <p className="text-sm font-bold mb-2">PlaidLink Component:</p>
                <PlaidLink 
                  userId={testUserId}
                  onSuccess={(token: string, meta: any) => {
                    alert(`Success! Connected to ${meta.institution.name}`);
                    console.log('Plaid success:', meta);
                  }}
                  onExit={() => {
                    alert('Plaid closed');
                    setShowPlaidConnect(false);
                  }}
                />
              </div>
              
              <button 
                onClick={() => setShowPlaidConnect(false)} 
                className="mt-4 px-4 py-2 bg-gray-500 text-white rounded"
              >
                Cancel
              </button>
            </div>
          )}
        </div>

        <div className="bg-yellow-50 border border-yellow-300 rounded-lg p-4 mt-6">
          <p className="text-sm">
            ⚠️ Test Mode: Using fake user ID. Auth is disabled for debugging.
          </p>
        </div>
      </div>
    </div>
  );
}
