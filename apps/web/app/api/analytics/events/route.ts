import { NextRequest, NextResponse } from 'next/server';

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    // Propagate headers for auth/dev bypass
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (req.headers.has('authorization')) {
      headers['authorization'] = req.headers.get('authorization')!;
    }
    if (req.headers.has('x-test-mode-user')) {
      headers['x-test-mode-user'] = req.headers.get('x-test-mode-user')!;
    }
    if (req.headers.has('cookie')) {
      headers['cookie'] = req.headers.get('cookie')!;
    }

    // Determine the upstream base URL
    // Use NEXT_PUBLIC_API_URL but ensure it is absolute for server-side fetch.
    // If it starts with '/', it is relative, which node-fetch/undici cannot handle without base.
    // Fallback to localhost:8000 (backend default) if not absolute.
    let apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
    if (apiUrl.startsWith('/')) {
        apiUrl = 'http://127.0.0.1:8000';
    }

    const res = await fetch(`${apiUrl}/analytics/events`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      // Even if backend fails, return 200 to client to avoid noise
      // but log it on server console
      console.warn(`[Analytics Proxy] Backend failed: ${res.status}`);
      return NextResponse.json({ status: 'ok', warning: 'backend_failed' }, { status: 200 });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (e) {
    console.error('[Analytics Proxy] Error:', e);
    // Always return 200 OK for analytics to prevent client-side spam
    return NextResponse.json({ status: 'ok', warning: 'proxy_failed' }, { status: 200 });
  }
}
