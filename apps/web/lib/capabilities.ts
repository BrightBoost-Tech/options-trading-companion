import { fetchWithAuth } from "./api";

export enum UpgradeCapability {
  AGENT_SIZING_ENABLED = "AGENT_SIZING_ENABLED",
  COUNTERFACTUAL_FEEDBACK = "COUNTERFACTUAL_FEEDBACK",
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
  [UpgradeCapability.AGENT_SIZING_ENABLED]: "Agent-Driven Sizing",
  [UpgradeCapability.COUNTERFACTUAL_FEEDBACK]: "Missed-Opportunity Analysis",
  [UpgradeCapability.ADVANCED_EVENT_GUARDRAILS]: "Advanced Event Guardrails",
};

export const CapabilityDescriptions: Record<UpgradeCapability, string> = {
  [UpgradeCapability.AGENT_SIZING_ENABLED]: "Automatically size trades based on risk profile and account value.",
  [UpgradeCapability.COUNTERFACTUAL_FEEDBACK]: "Learn from trades you didn't take.",
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
