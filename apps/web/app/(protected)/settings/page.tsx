'use client';

import { useState, useRef } from 'react';
import PlaidLink from '@/components/PlaidLink';
import DashboardLayout from '@/components/DashboardLayout';
import { supabase } from '@/lib/supabase';
import { API_URL } from '@/lib/constants';

export default function SettingsPage() {
  const [showPlaidConnect, setShowPlaidConnect] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  // Use a fake user ID for testing
  const testUserId = 'test-user-123';

  const handleConnectClick = () => {
    console.log('🔵 Connect clicked');
    alert('Showing Plaid connection...');
    setShowPlaidConnect(true);
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadStatus(null);

    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) throw new Error("Not authenticated");

      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`${API_URL}/holdings/upload_csv`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${session.access_token}`
        },
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
          
          {!showPlaidConnect ? (
            <div>
              <p className="text-gray-600 mb-4">Connect your broker securely via Plaid to automatically sync holdings.</p>
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
