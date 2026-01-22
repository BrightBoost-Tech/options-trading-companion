'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { supabase } from '@/lib/supabase';

interface RequireAuthProps {
  children: React.ReactNode;
}

/**
 * Client-side auth guard component.
 * Checks for a valid Supabase session on mount and redirects to /login if missing.
 *
 * Note: In development with NEXT_PUBLIC_ENABLE_DEV_AUTH_BYPASS=1,
 * this component still checks for a session but pages can function
 * via the test mode headers in api.ts.
 */
export function RequireAuth({ children }: RequireAuthProps) {
  const router = useRouter();
  const [isChecking, setIsChecking] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    let mounted = true;

    const checkAuth = async () => {
      try {
        const { data: { session } } = await supabase.auth.getSession();

        if (!mounted) return;

        if (session) {
          setIsAuthenticated(true);
        } else {
          // Check if dev bypass is enabled (non-production only)
          const isProd = process.env.NODE_ENV === 'production';
          const devBypassEnabled = !isProd && process.env.NEXT_PUBLIC_ENABLE_DEV_AUTH_BYPASS === '1';

          if (devBypassEnabled) {
            // In dev with bypass, allow access without session
            setIsAuthenticated(true);
          } else {
            // No session and no bypass - redirect to login
            router.replace('/login');
            return;
          }
        }
      } catch (error) {
        console.error('Auth check failed:', error);
        router.replace('/login');
        return;
      } finally {
        if (mounted) {
          setIsChecking(false);
        }
      }
    };

    checkAuth();

    // Listen for auth state changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (!mounted) return;

      if (event === 'SIGNED_OUT' || (!session && process.env.NODE_ENV === 'production')) {
        router.replace('/login');
      } else if (event === 'SIGNED_IN' && session) {
        setIsAuthenticated(true);
      }
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, [router]);

  // Show minimal loading state while checking auth
  if (isChecking) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  // Not authenticated - will redirect, show nothing to prevent flash
  if (!isAuthenticated) {
    return null;
  }

  return <>{children}</>;
}

export default RequireAuth;
