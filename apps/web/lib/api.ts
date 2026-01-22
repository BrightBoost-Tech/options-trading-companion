import { supabase } from '@/lib/supabase';
import { API_URL, TEST_USER_ID } from '@/lib/constants';
import { DiscreteSolveRequest, DiscreteSolveResponse } from './types';

type FetchInput = RequestInfo | URL;

export class ApiError extends Error {
  status: number;
  detail?: string;
  trace_id?: string;
  note?: string;

  constructor(message: string, status: number, body?: any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    if (body && typeof body === 'object') {
      this.detail = body.detail;
      this.trace_id = body.trace_id;
      this.note = body.note;
    }
  }
}

// --- Auth Header Caching ---
let cachedHeaders: Record<string, string> | null = null;
let cachedHeadersTimestamp = 0;

/**
 * Returns cached auth headers if valid (default TTL 5000ms), otherwise fetches new ones.
 * This prevents repeated session calls during component fan-out.
 *
 * Production behavior:
 * - NEVER sends X-Test-Mode-User header
 * - Requires real Supabase JWT; if missing, sets X-Auth-Missing marker
 *
 * Development behavior:
 * - If NEXT_PUBLIC_ENABLE_DEV_AUTH_BYPASS=1, sends X-Test-Mode-User
 * - Otherwise uses Supabase JWT if available, or marks as unauthenticated
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

  // Environment checks
  const isProd = process.env.NODE_ENV === 'production';
  // Dev bypass is ONLY allowed in non-production
  const devBypassEnabled = !isProd && process.env.NEXT_PUBLIC_ENABLE_DEV_AUTH_BYPASS === '1';
  const devUser = process.env.NEXT_PUBLIC_DEV_USER_ID || TEST_USER_ID;

  if (devBypassEnabled) {
    // Dev-only: use test mode header
    headers['X-Test-Mode-User'] = devUser;
  } else if (session?.access_token) {
    // Real authentication via Supabase JWT
    headers['Authorization'] = `Bearer ${session.access_token}`;
  } else {
    // No session available - mark as unauthenticated
    // In production, this will cause fetchWithAuth to throw
    // In dev without bypass, this allows pages to detect missing auth
    headers['X-Auth-Missing'] = '1';
  }

  cachedHeaders = headers;
  cachedHeadersTimestamp = now;
  return { ...headers };
}

/**
 * Clears the cached auth headers.
 * Call this when the user logs out or when auth state changes.
 */
export function clearAuthHeadersCache(): void {
  cachedHeaders = null;
  cachedHeadersTimestamp = 0;
}

/**
 * Helper for making authenticated requests to the backend.
 * Automatically injects the Supabase session token (via cached helper).
 * Prepends API_URL if the input is a relative path starting with '/'.
 *
 * Returns the parsed JSON response by default.
 * Throws a typed ApiError if the response is not ok or if authentication is missing.
 */
export async function fetchWithAuth<T = any>(
  input: FetchInput,
  init?: RequestInit
): Promise<T> {
  // 1. Get auth headers (cached)
  const authHeaders = await getAuthHeadersCached();

  // 2. Check for missing authentication
  if (authHeaders['X-Auth-Missing'] === '1') {
    throw new ApiError('Authentication required', 401, { detail: 'not_authenticated' });
  }

  // 3. Construct final headers (exclude the marker)
  const headers: Record<string, string> = { ...authHeaders };
  delete headers['X-Auth-Missing'];

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

  // 6. Handle Response
  let data: any;
  const contentType = response.headers.get('content-type');
  if (contentType && contentType.includes('application/json')) {
    try {
      data = await response.json();
    } catch (e) {
      // Failed to parse JSON, data remains undefined
    }
  } else {
    // If text/plain or other, try to read text
    try {
        data = await response.text();
    } catch (e) {
        // failed to read text
    }
  }

  if (!response.ok) {
    const message = (data && typeof data === 'object' && data.detail)
      ? data.detail
      : `Request failed with status ${response.status}`;

    throw new ApiError(message, response.status, data);
  }

  return data as T;
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

/**
 * Helper to normalize list responses that might be wrapped in an object or null.
 * e.g. { strategies: [...] } vs [...]
 *
 * @param data The raw response data
 * @param listKey The key to look for if the data is an object wrapper (default: 'items')
 * @returns A guaranteed array
 */
export function normalizeList<T>(data: any, listKey: string = 'items'): T[] {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  if (typeof data === 'object' && Array.isArray(data[listKey])) return data[listKey];
  return [];
}

/**
 * Calls the /optimize/discrete endpoint to select optimal trades under constraints.
 *
 * @param req - The selection candidates and constraints
 * @returns The optimized selection result
 * @throws ApiError if backend returns non-2xx
 */
export async function postOptimizeDiscrete(req: DiscreteSolveRequest): Promise<DiscreteSolveResponse> {
  return fetchWithAuth<DiscreteSolveResponse>('/optimize/discrete', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}
