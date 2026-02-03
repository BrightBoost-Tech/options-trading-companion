'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import PlaidLink from '@/components/PlaidLink';
import DashboardLayout from '@/components/DashboardLayout';
import { Button } from '@/components/ui/button';
import { Unplug, CheckCircle2 } from 'lucide-react';
import { supabase } from '@/lib/supabase';
import { fetchWithAuth } from '@/lib/api';
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

          // fetchWithAuth automatically handles Authorization header and URL prefixing
          const data = await fetchWithAuth<any>('/plaid/status');

          if (data && data.connected) {
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
          // Using shared fetchWithAuth helper which handles prefixing
          const data = await fetchWithAuth('/plaid/exchange_token', {
              method: 'POST',
              headers: {
                  'Content-Type': 'application/json',
              },
              body: JSON.stringify({
                  public_token: publicToken,
                  metadata: metadata
              })
          });

          console.log('Exchange success:', data);

          setConnectedInstitution(metadata.institution?.name || 'Connected Broker');

          // ✅ FIX: Trigger sync with correct headers for Dev Mode
          try {
              await fetchWithAuth('/plaid/sync_holdings', {
                  method: 'POST'
              });
              console.log("✅ Initial sync successful");
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
             <div className="bg-green-50/50 dark:bg-green-900/20 border border-green-200 dark:border-green-900 p-4 rounded-lg flex items-center justify-between">
                <div className="flex items-center gap-3">
                   <div className="h-10 w-10 rounded-full bg-green-100 dark:bg-green-900/40 flex items-center justify-center">
                     <CheckCircle2 className="h-6 w-6 text-green-600 dark:text-green-400" />
                   </div>
                   <div>
                      <h3 className="text-base font-medium text-green-900 dark:text-green-100">Connected</h3>
                      <p className="text-sm text-green-700 dark:text-green-300">Linked to <span className="font-semibold">{connectedInstitution}</span></p>
                   </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setConnectedInstitution(null)}
                  className="text-red-600 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20"
                  aria-label="Disconnect broker account"
                >
                  <Unplug className="mr-2 h-4 w-4" />
                  Disconnect
                </Button>
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
