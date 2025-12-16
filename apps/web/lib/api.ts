import { supabase } from '@/lib/supabase';
import { API_URL, TEST_USER_ID } from '@/lib/constants';

type FetchInput = RequestInfo | URL;

// --- Auth Header Caching ---
let cachedHeaders: Record<string, string> | null = null;
let cachedHeadersTimestamp = 0;

/**
 * Returns cached auth headers if valid (default TTL 5000ms), otherwise fetches new ones.
 * This prevents repeated session calls during component fan-out.
 */
export async function getAuthHeadersCached(ttlMs = 5000): Promise<Record<string, string>> {
  const now = Date.now();
  if (cachedHeaders && (now - cachedHeadersTimestamp < ttlMs)) {
    return { ...cachedHeaders };
  }

  const { data: { session } } = await supabase.auth.getSession();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  if (session?.access_token) {
    headers['Authorization'] = `Bearer ${session.access_token}`;
  } else {
    headers['X-Test-Mode-User'] = TEST_USER_ID;
  }

  cachedHeaders = headers;
  cachedHeadersTimestamp = now;
  return { ...headers };
}

/**
 * Helper for making authenticated requests to the backend.
 * Automatically injects the Supabase session token (via cached helper) or falls back to the test user ID.
 * Prepends API_URL if the input is a relative path starting with '/'.
 *
 * Returns the parsed JSON response by default.
 * Throws an error if the response is not ok.
 */
export async function fetchWithAuth<T = any>(
  input: FetchInput,
  init?: RequestInit
): Promise<T> {
  // 1. Get auth headers (cached)
  const authHeaders = await getAuthHeadersCached();

  // 2. Construct final headers
  const headers: Record<string, string> = { ...authHeaders };

  // 3. Merge with user-provided headers
  if (init?.headers) {
    if (init.headers instanceof Headers) {
      init.headers.forEach((value, key) => {
        headers[key] = value;
      });
    } else if (Array.isArray(init.headers)) {
      init.headers.forEach(([key, value]) => {
        headers[key] = value;
      });
    } else {
      Object.assign(headers, init.headers);
    }
  }

  // 4. Normalize URL (prepend API_URL if relative path)
  let url = input;
  if (typeof input === 'string' && input.startsWith('/')) {
    url = `${API_URL}${input}`;
  }

  // 5. Execute fetch
  const response = await fetch(url, {
    ...init,
    headers,
  });

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  // 6. Return parsed JSON
  return response.json();
}

/**
 * Wrapper for fetchWithAuth that aborts the request after a specified timeout.
 */
export async function fetchWithAuthTimeout<T = any>(
  input: FetchInput,
  timeoutMs: number,
  init?: RequestInit
): Promise<T> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetchWithAuth<T>(input, {
      ...init,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(id);
  }
}
