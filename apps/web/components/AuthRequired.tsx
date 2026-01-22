'use client';

import Link from 'next/link';
import { LogIn } from 'lucide-react';

interface AuthRequiredProps {
  message?: string;
}

/**
 * Simple UI component shown when authentication is required but missing.
 * Used as a fallback when API calls return 401 or when a page
 * explicitly detects missing authentication.
 */
export function AuthRequired({ message = 'Please log in to access this page.' }: AuthRequiredProps) {
  return (
    <div className="flex min-h-[50vh] items-center justify-center p-8">
      <div className="w-full max-w-md rounded-lg border border-border bg-card p-8 text-center shadow-sm">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
          <LogIn className="h-6 w-6 text-muted-foreground" />
        </div>
        <h2 className="mb-2 text-xl font-semibold text-foreground">Login Required</h2>
        <p className="mb-6 text-sm text-muted-foreground">{message}</p>
        <Link
          href="/login"
          className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <LogIn className="mr-2 h-4 w-4" />
          Go to Login
        </Link>
      </div>
    </div>
  );
}

export default AuthRequired;
