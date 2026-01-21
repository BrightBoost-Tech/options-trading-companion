"""
FastAPI dependencies for go-live readiness gate enforcement.

Provides dependency injection for endpoints that require live execution privileges.
"""

from fastapi import Depends, HTTPException
from supabase import Client

from packages.quantum.security import get_current_user, get_supabase_user_client
from packages.quantum.services.go_live_validation_service import GoLiveValidationService
from packages.quantum.ops_endpoints import get_global_ops_control
from packages.quantum.policies.go_live_policy import evaluate_go_live_gate, GateDecision


def require_live_execution_allowed(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_user_client)
) -> GateDecision:
    """
    FastAPI dependency that enforces the go-live readiness gate.

    Raises HTTPException 403 if the gate denies live execution.

    Usage:
        @router.post("/some-live-endpoint")
        def my_endpoint(
            gate: GateDecision = Depends(require_live_execution_allowed)
        ):
            # gate.allowed is True here (otherwise 403 was raised)
            ...

    Returns:
        GateDecision if allowed

    Raises:
        HTTPException 403 with reason and context if denied
    """
    # Fetch ops state
    ops_state = get_global_ops_control()

    # Fetch user readiness
    service = GoLiveValidationService(supabase)
    user_readiness = service.get_or_create_state(user_id)

    # Evaluate gate
    decision = evaluate_go_live_gate(ops_state, user_readiness)

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "reason": decision.reason,
                "context": decision.context,
            }
        )

    return decision
