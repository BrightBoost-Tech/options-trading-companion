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

  // Dev Auth Bypass
  const devBypass = process.env.NEXT_PUBLIC_ENABLE_DEV_AUTH_BYPASS === '1';
  // Use the global TEST_USER_ID constant if explicit dev user is not set,
  // ensuring alignment with backend test user ID.
  const devUser = process.env.NEXT_PUBLIC_DEV_USER_ID || TEST_USER_ID;

  if (devBypass) {
    headers['X-Test-Mode-User'] = devUser;
  } else if (session?.access_token) {
    headers['Authorization'] = `Bearer ${session.access_token}`;
  } else {
    // Fallback for tests/local (deprecated behavior, but kept for compatibility)
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
 * Throws a typed ApiError if the response is not ok.
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
