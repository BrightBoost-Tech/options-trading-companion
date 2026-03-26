'use client';

import { useState, useEffect } from 'react';
import DashboardLayout from '@/components/DashboardLayout';
import { CheckCircle2 } from 'lucide-react';
import { supabase } from '@/lib/supabase';

export default function SettingsPage() {
  const [userId, setUserId] = useState<string | null>(null);

  useEffect(() => {
      supabase.auth.getUser().then(({ data: { user } }) => {
          if (user) setUserId(user.id);
      });
  }, []);

  return (
    <DashboardLayout>
      <div className="max-w-4xl mx-auto p-8 space-y-6">
        <h1 className="text-3xl font-bold mb-2">Settings</h1>

        {/* Broker Connection */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-semibold mb-4">🔗 Broker Connection</h2>

          <div className="bg-green-50/50 dark:bg-green-900/20 border border-green-200 dark:border-green-900 p-4 rounded-lg flex items-center gap-3">
            <div className="h-10 w-10 rounded-full bg-green-100 dark:bg-green-900/40 flex items-center justify-center">
              <CheckCircle2 className="h-6 w-6 text-green-600 dark:text-green-400" />
            </div>
            <div>
              <h3 className="text-base font-medium text-green-900 dark:text-green-100">Alpaca</h3>
              <p className="text-sm text-green-700 dark:text-green-300">
                Broker connection managed via environment configuration.
              </p>
            </div>
          </div>
        </div>

        <div className="bg-blue-50 border border-blue-300 rounded-lg p-4 mt-8">
          <p className="text-xs text-blue-800">
            🧪 <strong>Development Mode Active:</strong> Alpaca paper trading enabled.
          </p>
        </div>
      </div>
    </DashboardLayout>
  );
}
