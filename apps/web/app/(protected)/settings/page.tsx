'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import PlaidLink from '@/components/PlaidLink';
import DashboardLayout from '@/components/DashboardLayout';
import { supabase } from '@/lib/supabase';
import { API_URL } from '@/lib/constants';
import { logEvent } from '@/lib/analytics';

export default function SettingsPage() {
  const [connectedInstitution, setConnectedInstitution] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  
  // In a real app, we'd get this from Auth Context
  // For now, assuming user is logged in or we use a test user if explicitly enabled
  const [testUserId] = useState('75ee12ad-b119-4f32-aeea-19b4ef55d587');

  // We need to know the REAL user ID for proper backend saving
  // If not logged in (dev mode), we might use testUserId
  const [userId, setUserId] = useState<string>(testUserId);

  // Fetch real user on mount
  useEffect(() => {
      supabase.auth.getUser().then(({ data: { user } }) => {
          if (user) {
              setUserId(user.id);
              checkPlaidStatus(user.id);
          }
      });
  }, []);

  const checkPlaidStatus = async (currentUserId: string) => {
      try {
          const { data: { session } } = await supabase.auth.getSession();
          if (!session) return;

          const res = await fetch(`${API_URL}/plaid/status`, {
              headers: {
                  'Authorization': `Bearer ${session.access_token}`
              }
          });
          const data = await res.json();
          if (data.connected) {
              setConnectedInstitution(data.institution || 'Connected Broker');
          }
      } catch (e) {
          console.error("Failed to check Plaid status", e);
      }
  };

  const handlePlaidSuccess = useCallback(async (publicToken: string, metadata: any) => {
      console.log('Plaid success:', metadata);
      setConnectionError(null);

      logEvent({
        eventName: 'plaid_link_completed',
        category: 'ux',
        properties: {
            link_session_id: metadata.link_session_id,
            institution: metadata.institution?.name,
            accounts_count: metadata.accounts?.length
        }
      });

      try {
          // Exchange token
          const response = await fetch(`${API_URL}/plaid/exchange_token`, {
              method: 'POST',
              headers: {
                  'Content-Type': 'application/json',
              },
              // We must pass user_id so the backend can save the item to the right user
              body: JSON.stringify({
                  public_token: publicToken,
                  user_id: userId
              })
          });

          if (!response.ok) {
              const errorData = await response.json();
              throw new Error(errorData.detail || 'Failed to exchange token');
          }

          const data = await response.json();
          console.log('Exchange success:', data);

          setConnectedInstitution(metadata.institution?.name || 'Connected Broker');

          // ✅ FIX: Trigger sync with correct headers for Dev Mode
          try {
              const { data: { session } } = await supabase.auth.getSession();

              const headers: Record<string, string> = {
                  'Content-Type': 'application/json'
              };

              if (session) {
                  // Real User Login
                  headers['Authorization'] = `Bearer ${session.access_token}`;
              } else if (userId) {
                  // 🛠️ DEV MODE BYPASS: Pass the user ID explicitly
                  headers['X-Test-Mode-User'] = userId;
              }

              const syncRes = await fetch(`${API_URL}/plaid/sync_holdings`, {
                  method: 'POST',
                  headers: headers
              });

              if (syncRes.ok) {
                  console.log("✅ Initial sync successful");
              } else {
                  console.warn("⚠️ Initial sync failed", await syncRes.text());
              }

          } catch (e) {
              console.warn("Initial sync failed:", e);
          }

      } catch (error: any) {
          console.error('Exchange token failed:', error);
          setConnectionError(`Connection failed: ${error.message}`);
      }
  }, [userId]);

  return (
    <DashboardLayout>
      <div className="max-w-4xl mx-auto p-8 space-y-6">
        <h1 className="text-3xl font-bold mb-2">Settings</h1>

        {/* Plaid Connection */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-semibold mb-4">🔗 Broker Connection (Plaid)</h2>
          
          {connectionError && (
              <div className="bg-red-50 border border-red-200 p-3 rounded mb-4 text-red-700 text-sm">
                  {connectionError}
              </div>
          )}

          {connectedInstitution ? (
             <div className="bg-green-50 border border-green-200 p-4 rounded-lg flex items-center justify-between">
                <div>
                   <h3 className="text-lg font-medium text-green-900">✅ Connected</h3>
                   <p className="text-sm text-green-700">Linked to: {connectedInstitution}</p>
                </div>
                <button
                  onClick={() => setConnectedInstitution(null)}
                  className="px-3 py-1 text-sm text-green-800 underline hover:text-green-900"
                >
                  Disconnect
                </button>
             </div>
          ) : (
            <div className="bg-gray-50 border border-gray-200 p-6 rounded-lg">
              <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-semibold">Connect Your Brokerage</h3>
              </div>
              
              <p className="text-gray-600 mb-4">Connect your broker securely via Plaid to automatically sync holdings.</p>

              <div className="bg-white p-4 border rounded shadow-sm">
                {/* Key userId to remount if it changes */}
                <PlaidLink 
                  key={userId}
                  userId={userId}
                  onSuccess={handlePlaidSuccess}
                  onExit={(err, metadata) => {
                     if (err) setConnectionError(err.display_message || err.error_message || 'Connection cancelled');
                  }}
                />
              </div>
            </div>
          )}
        </div>

        <div className="bg-blue-50 border border-blue-300 rounded-lg p-4 mt-8">
          <p className="text-xs text-blue-800">
            🧪 <strong>Development Mode Active:</strong> Use real brokerage credentials.
          </p>
        </div>
      </div>
    </DashboardLayout>
  );
}
