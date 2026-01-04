import { fetchWithAuth } from "./api";

export enum UpgradeCapability {
  AGENT_SIZING = "AGENT_SIZING",
  COUNTERFACTUAL_ANALYSIS = "COUNTERFACTUAL_ANALYSIS",
  ADVANCED_EVENT_GUARDRAILS = "ADVANCED_EVENT_GUARDRAILS",
}

export interface CapabilityState {
  capability: UpgradeCapability;
  is_active: boolean;
  reason?: string;
}

export interface UserCapabilitiesResponse {
  capabilities: CapabilityState[];
}

export const CapabilityDisplayNames: Record<UpgradeCapability, string> = {
  [UpgradeCapability.AGENT_SIZING]: "Agent-Driven Sizing",
  [UpgradeCapability.COUNTERFACTUAL_ANALYSIS]: "Missed-Opportunity Analysis",
  [UpgradeCapability.ADVANCED_EVENT_GUARDRAILS]: "Advanced Event Guardrails",
};

export const CapabilityDescriptions: Record<UpgradeCapability, string> = {
  [UpgradeCapability.AGENT_SIZING]: "Automatically size trades based on risk profile and account value.",
  [UpgradeCapability.COUNTERFACTUAL_ANALYSIS]: "Learn from trades you didn't take.",
  [UpgradeCapability.ADVANCED_EVENT_GUARDRAILS]: "Protect against earnings and macro events.",
};

export async function fetchCapabilities(): Promise<UserCapabilitiesResponse> {
  try {
    const res = await fetchWithAuth("/capabilities");
    if (!res.ok) {
        // Fallback for dev/first run
        return { capabilities: [] };
    }
    return await res.json();
  } catch (e) {
      console.error("Failed to fetch capabilities", e);
      return { capabilities: [] };
  }
}
