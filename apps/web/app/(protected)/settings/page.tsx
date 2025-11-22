'use client';

import { useState, useRef } from 'react';
import PlaidLink from '@/components/PlaidLink';
import DashboardLayout from '@/components/DashboardLayout';
import { supabase } from '@/lib/supabase';
import { API_URL } from '@/lib/constants';

export default function SettingsPage() {
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [connectedInstitution, setConnectedInstitution] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  // Use a fake user ID for testing
  const testUserId = 'test-user-123';

  const handlePlaidSuccess = async (publicToken: string, metadata: any) => {
      console.log('Plaid success:', metadata);

      try {
          const response = await fetch(`${API_URL}/plaid/exchange_token`, {
              method: 'POST',
              headers: {
                  'Content-Type': 'application/json',
              },
              body: JSON.stringify({ public_token: publicToken })
          });

          if (!response.ok) {
              const errorData = await response.json();
              throw new Error(errorData.detail || 'Failed to exchange token');
          }

          const data = await response.json();
          console.log('Exchange success:', data);

          setConnectedInstitution(metadata.institution?.name || 'Unknown Broker');
          setConnectionError(null);

          // Optionally save the item_id or update local state to reflect "Connected" permanently
          // For now, we just show the connected state in UI

      } catch (error: any) {
          console.error('Exchange token failed:', error);
          setConnectionError(`Connection failed: ${error.message}`);
      }
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadStatus(null);

    try {
      const { data: { session } } = await supabase.auth.getSession();

      const formData = new FormData();
      formData.append('file', file);

      const headers: any = {};

      if (session) {
          headers['Authorization'] = `Bearer ${session.access_token}`;
      } else {
          // Fallback to test mode if no session (but warn user)
          // Ideally we only do this if we are in a "dev" mode or user explicitly opts in?
          // For now, if no session, we assume test mode as per request to "support local test mode"
          console.log('⚠️ No session found, attempting upload in Test Mode');
          headers['X-Test-Mode-User'] = testUserId;
      }

      const response = await fetch(`${API_URL}/holdings/upload_csv`, {
        method: 'POST',
        headers: headers,
        body: formData
      });

      if (!response.ok) {
        throw new Error('Upload failed');
      }

      const data = await response.json();
      setUploadStatus(`Success! Imported ${data.count} holdings.`);

      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    } catch (err: any) {
      setUploadStatus(`Error: ${err.message}`);
    } finally {
      setUploading(false);
    }
  };

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
                   <h3 className="text-lg font-medium text-green-900">Broker Connected</h3>
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
                <PlaidLink 
                  userId={testUserId}
                  onSuccess={handlePlaidSuccess}
                  onExit={() => {
                    // Optional: handle exit without success
                  }}
                />
              </div>
            </div>
          )}
        </div>

        {/* Robinhood CSV Import */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-semibold mb-4">📂 Import Holdings (CSV)</h2>
          <p className="text-gray-600 mb-4 text-sm">
             If you cannot connect via Plaid, you can upload a CSV export from Robinhood or other brokers.
             <br />
             Expected headers: <code>Symbol, Quantity, Average Cost, Current Price</code>
          </p>

          <div className="flex items-center gap-4">
             <label className="block">
               <span className="sr-only">Choose file</span>
               <input
                 type="file"
                 accept=".csv"
                 onChange={handleFileUpload}
                 ref={fileInputRef}
                 disabled={uploading}
                 className="block w-full text-sm text-gray-500
                   file:mr-4 file:py-2 file:px-4
                   file:rounded-full file:border-0
                   file:text-sm file:font-semibold
                   file:bg-blue-50 file:text-blue-700
                   hover:file:bg-blue-100
                 "
               />
             </label>
             {uploading && <span className="text-sm text-gray-500">Uploading...</span>}
          </div>

          {uploadStatus && (
            <div className={`mt-4 p-3 rounded text-sm ${uploadStatus.startsWith('Success') ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
              {uploadStatus}
            </div>
          )}
        </div>

        <div className="bg-yellow-50 border border-yellow-300 rounded-lg p-4">
          <p className="text-sm">
            ⚠️ Test Mode: Using fake user ID for Plaid. Auth is required for CSV upload.
          </p>
        </div>
      </div>
    </DashboardLayout>
  );
}
