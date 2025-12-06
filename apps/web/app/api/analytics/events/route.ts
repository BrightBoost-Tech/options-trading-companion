import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

// Use the environment variable for API base URL, fallback to local default if needed
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { event_name, category, properties } = body;

    // Get auth token from cookies (supabase-auth-token) if available
    const cookieStore = cookies();
    // Supabase auth helpers usually store session in a cookie named sb-<project-ref>-auth-token
    // But we can also forward all cookies or just rely on the backend to handle unauthenticated events if allowed.
    // However, the prompt says "Include auth cookies/headers as needed".
    // Usually we might need to forward the Authorization header.
    // Let's grab all cookies to be safe and forward them.

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    // Forward Authorization header if present in the incoming request (though this is client-side fetch, so we might need to set it in logEvent or rely on cookies)
    // The logEvent in lib/analytics.ts is a simple fetch, it doesn't automatically attach auth headers unless we use a wrapper.
    // But since this is a Next.js route handler, the user session is likely in cookies.
    // We will attempt to forward the cookie string.
    const cookieHeader = request.headers.get('cookie');
    if (cookieHeader) {
      headers['Cookie'] = cookieHeader;
    }

    const response = await fetch(`${API_BASE_URL}/analytics/events`, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({
        event_name,
        category,
        properties
      }),
    });

    if (!response.ok) {
        // If backend fails, we return 200 anyway to not break frontend, or maybe we want to propagate for debugging?
        // The instructions say "Return a simple 200/204 or the backend’s status."
        // "Swallow errors – analytics must never break UX" was for the client.
        // Here we can return what the backend returns.
        return new NextResponse(null, { status: response.status });
    }

    return new NextResponse(null, { status: 200 });

  } catch (error) {
    console.error('Error proxying analytics event:', error);
    // Return 200 to client to avoid errors
    return new NextResponse(null, { status: 200 });
  }
}
