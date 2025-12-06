// apps/web/lib/analytics.ts

import { API_URL } from "./constants";
import { fetchWithAuth } from "./api";

/**
 * Lightweight analytics client for frontend events.
 */
export async function logEvent(
  eventName: string,
  category: string,
  properties: Record<string, any> = {}
): Promise<void> {
  try {
    // Fire and forget, but catch errors to prevent crashing UI
    fetchWithAuth('/analytics/events', {
      method: 'POST',
      body: JSON.stringify({
        event_name: eventName,
        category,
        properties
      })
    }).catch(err => console.error("[Analytics] Logging failed:", err));
  } catch (e) {
    console.error("[Analytics] Error:", e);
  }
}
