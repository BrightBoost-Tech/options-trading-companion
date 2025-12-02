import { supabase } from '@/lib/supabase';
import { API_URL, TEST_USER_ID } from '@/lib/constants';

type FetchInput = RequestInfo | URL;

/**
 * Helper for making authenticated requests to the backend.
 * Automatically injects the Supabase session token or falls back to the test user ID.
 * Prepends API_URL if the input is a relative path starting with '/'.
 *
 * Returns the parsed JSON response by default.
 * Throws an error if the response is not ok.
 */
export async function fetchWithAuth<T = any>(
  input: FetchInput,
  init?: RequestInit
): Promise<T> {
  // 1. Get current session for auth token
  const { data: { session } } = await supabase.auth.getSession();

  // 2. Construct default headers
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  // 3. Add Authorization or Test Mode header
  if (session?.access_token) {
    headers['Authorization'] = `Bearer ${session.access_token}`;
  } else {
    headers['X-Test-Mode-User'] = TEST_USER_ID;
  }

  // 4. Merge with user-provided headers
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

  // 5. Normalize URL (prepend API_URL if relative path)
  let url = input;
  if (typeof input === 'string' && input.startsWith('/')) {
    url = `${API_URL}${input}`;
  }

  // 6. Execute fetch
  const response = await fetch(url, {
    ...init,
    headers,
  });

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  // 7. Return parsed JSON
  return response.json();
}
