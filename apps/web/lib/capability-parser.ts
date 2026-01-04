export interface CapabilityState {
    capability: string;
    is_active: boolean;
    reason?: string | null;
}

export interface UserCapabilitiesResponse {
    capabilities: CapabilityState[];
}

/**
 * Safely parses the capabilities response from the backend.
 * Handles both the legacy array format (if any) and the new object format.
 *
 * @param response The raw JSON response from /capabilities
 * @returns An array of CapabilityState objects
 */
export function parseCapabilitiesResponse(response: any): CapabilityState[] {
    if (!response) return [];

    // Case 1: Response is the array itself (legacy/fallback)
    if (Array.isArray(response)) {
        return response;
    }

    // Case 2: Response is object with capabilities array
    if (response && response.capabilities && Array.isArray(response.capabilities)) {
        return response.capabilities;
    }

    // Fallback: Empty array if format is unrecognized
    return [];
}

/**
 * Formats a capability ID (e.g., "AGENT_SIZING") into a human-readable string.
 * Example: "AGENT_SIZING" -> "Agent Sizing"
 */
export function formatCapabilityName(cap: string): string {
    if (!cap) return "";
    return cap
        .replace(/_/g, ' ')
        .toLowerCase()
        .replace(/\b\w/g, l => l.toUpperCase());
}
