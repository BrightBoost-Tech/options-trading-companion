'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

interface DashboardLayoutProps {
  children: React.ReactNode;
  mockAlerts?: { id: string; message: string; time: string }[];
}

export default function DashboardLayout({ children, mockAlerts = [] }: DashboardLayoutProps) {
  const pathname = usePathname();
  const isDashboard = pathname === '/dashboard';

  return (
    <div className="min-h-screen bg-gray-50">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-[100] focus:px-4 focus:py-2 focus:bg-white focus:text-blue-600 focus:shadow-lg focus:rounded-md focus:border focus:border-blue-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        Skip to main content
      </a>
      <div className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-8 py-4 flex justify-between items-center">
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-bold">
              <Link href="/dashboard">Options Trading Companion</Link>
            </h1>
            {!isDashboard && (
              <Link
                href="/dashboard"
                className="text-sm text-gray-500 hover:text-gray-900 flex items-center gap-1"
              >
                ← Back to Dashboard
              </Link>
            )}
          </div>
          <div className="flex items-center gap-4">
            {isDashboard && (
              <div className="relative">
                <button aria-label="Notifications" className="p-2 rounded-full hover:bg-gray-100">
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                  </svg>
                </button>
                <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
                  {mockAlerts.length}
                </span>
              </div>
            )}
            <Link href="/settings" className={`hover:text-gray-900 ${pathname === '/settings' ? 'text-gray-900 font-medium' : 'text-gray-600'}`}>
              Settings
            </Link>
            <Link href="/journal" className={`hover:text-gray-900 ${pathname === '/journal' ? 'text-gray-900 font-medium' : 'text-gray-600'}`}>
              Journal
            </Link>
            <Link href="/portfolio" className={`hover:text-gray-900 ${pathname === '/portfolio' ? 'text-gray-900 font-medium' : 'text-gray-600'}`}>
              Portfolio
            </Link>
            <Link href="/compose" className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
              New Trade
            </Link>
          </div>
        </div>
      </div>
      <main id="main-content">
        {children}
      </main>
    </div>
  );
}
