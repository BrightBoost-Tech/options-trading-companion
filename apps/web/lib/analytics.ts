export type AnalyticsPayload = {
  eventName: string;
  category: 'ux' | 'system' | 'trade' | 'learning';
  properties?: Record<string, any>;
};

export async function logEvent({ eventName, category, properties }: AnalyticsPayload) {
  try {
    await fetch('/api/analytics/events', {
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
