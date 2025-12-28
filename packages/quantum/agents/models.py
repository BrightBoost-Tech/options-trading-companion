from packages.quantum.agents.core import AgentSignal, BaseQuantAgent

# Backward compatibility alias
# If any code imports AgentSignal from models, it gets the core version.
# We re-export them here.
__all__ = ["AgentSignal", "BaseQuantAgent"]
