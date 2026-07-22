"""Worker handler for the internal single-leg shadow scan child job."""

from __future__ import annotations

from typing import Any, Dict

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.services.single_leg_shadow_scan import (
    JOB_NAME,
    run_single_leg_shadow_scan,
)


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    del ctx
    client = get_admin_client()
    return run_single_leg_shadow_scan(payload or {}, client=client)
