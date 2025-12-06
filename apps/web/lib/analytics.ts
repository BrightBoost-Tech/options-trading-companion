import { fetchWithAuth } from "@/lib/api";

export type AnalyticsPayload = {
  eventName: string;
  category: 'ux' | 'system' | 'trade' | 'learning';
  properties?: Record<string, any>;
};

export async function logEvent({ eventName, category, properties }: AnalyticsPayload) {
  try {
    // Use absolute URL on client to hit the Next.js proxy.
    // On server (SSR), fall back to relative path '/analytics/events' which fetchWithAuth
    // will prepend with API_URL to hit the backend directly.
    const url = typeof window !== 'undefined'
      ? `${window.location.origin}/api/analytics/events`
      : '/analytics/events';

    await fetchWithAuth(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ event_name: eventName, category, properties }),
    });
  } catch (err) {
    // Swallow errors – analytics must never break UX
    if (process.env.NODE_ENV === 'development') {
      console.warn('Analytics logEvent failed:', err);
    }
  }
}
