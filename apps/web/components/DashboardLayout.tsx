'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Button, buttonVariants } from '@/components/ui/button';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Bell } from 'lucide-react';
import { cn } from '@/lib/utils';

interface DashboardLayoutProps {
  children: React.ReactNode;
  mockAlerts?: { id: string; message: string; time: string }[];
}

export default function DashboardLayout({ children, mockAlerts = [] }: DashboardLayoutProps) {
  const pathname = usePathname();
  const isDashboard = pathname === '/dashboard';

  return (
    <TooltipProvider>
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
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Notifications"
                    className="rounded-full"
                  >
                    <Bell className="w-6 h-6" />
                  </Button>
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
              <Link
                href="/compose"
                className={cn(buttonVariants({ variant: 'default' }), "bg-blue-600 hover:bg-blue-700")}
              >
                New Trade
              </Link>
            </div>
          </div>
        </div>
        <main id="main-content">
          {children}
        </main>
      </div>
    </TooltipProvider>
  );
}
