"""Operator-invoked RUNTIME_STATE_ECHO — DB-backed dark-control state (2026-07-23).

Companion to ``flag_echo`` (startup, env-parsed booleans), NOT a second copy of it.
Some dark controls are gated by DATABASE STATE, not an env flag, so the startup
``[FLAG_ECHO]`` cannot see them: the single-leg experiment is armed by an *epoch
row* + per-policy registry opt-in; the 50-policy shadow fleet is armed by
``shadow_fleets``/``shadow_micro_accounts`` binding rows; E19's executor is gated
on the fleet epoch being active. This reader reports those THREE DB-state surfaces
so an accidental arm is greppable — the DB analogue of the flag echo.

DELIBERATELY NOT WIRED TO STARTUP. ``flag_echo`` fires at module import (api.py /
jobs.runner) because a boolean parse is free; a DB read is not, and must never sit
on a process's start path. This module is imported and called ONLY by an operator
tool / evidence reader, never at import time. A test pins that api.py and
jobs/runner.py do not reference it.

TRUTH-DOCTRINE COMPLIANCE:
  * Read-only. Never writes, never issues an RPC, never mutates a row.
  * Four-state honesty (mirrors ``single_leg_shadow_reader``): OK (rows present),
    HONEST-EMPTY (query succeeded, zero rows — a real measured-empty), FAILED-FETCH
    (the read threw — NOT an empty measurement), NOT-FETCHED (a dependent read that
    could not be attempted, e.g. micro-accounts when the fleet id is unknown).
  * Fail-CLOSED: a failed or absent read NEVER renders as "armed"/"active". The
    single-leg epoch reports ``epoch_absent`` only on a genuine zero-row read and
    ``epoch_read_failed`` on an exception — a dark control is never reported live
    off a broken read (§10 empty-data-is-not-a-failed-read; H9).
  * Every field is labelled ``source="DB_state"`` so it is never confused with the
    env-parsed FLAG_ECHO values.
  * No secrets: this reads status/count/enum columns only, never a credential.

The epoch identifiers are IMPORTED from the modules that own them (pointer
discipline, not embedded strings), so a rename can't silently desync the reader.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Pointer discipline: the SAME constants production arms against.
from packages.quantum.policy_lab.shadow_fleet import FLEET_EPOCH
from packages.quantum.services.single_leg_shadow_evidence import EPOCH as SINGLE_LEG_EPOCH

logger = logging.getLogger(__name__)

SOURCE = "DB_state"

# Four-state honesty vocabulary (shared idiom with single_leg_shadow_reader).
OK = "OK"
HONEST_EMPTY = "HONEST-EMPTY"
FAILED_FETCH = "FAILED-FETCH"
NOT_FETCHED = "NOT-FETCHED"


def _rows(response: Any) -> List[Dict[str, Any]]:
    rows = getattr(response, "data", None)
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def _query_section(name: str, query: Any) -> Dict[str, Any]:
    """Execute one read; classify OK / HONEST-EMPTY / FAILED-FETCH. Never raises."""
    try:
        rows = _rows(query.execute())
    except Exception as exc:  # noqa: BLE001 — a failed read is a typed state, not []
        return {
            "section": name,
            "status": FAILED_FETCH,
            "rows": [],
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        }
    return {
        "section": name,
        "status": OK if rows else HONEST_EMPTY,
        "rows": rows,
        "error": None,
    }


def _not_fetched(name: str, reason: str) -> Dict[str, Any]:
    return {"section": name, "status": NOT_FETCHED, "rows": [], "error": reason}


# ── Section fetchers (each independent; one failure never sinks the others) ──

def _fetch_single_leg_epoch(client: Any, epoch: str) -> Dict[str, Any]:
    return _query_section(
        "single_leg_epoch",
        client.table("single_leg_experiment_epochs")
        .select(
            "epoch_name,state,routing_mode,max_contracts,"
            "live_submit_allowed,version"
        )
        .eq("epoch_name", epoch),
    )


def _fetch_fleet(client: Any, user_id: str, epoch: str) -> Dict[str, Any]:
    return _query_section(
        "fleet",
        client.table("shadow_fleets")
        .select("id,epoch_name,status,effective_at,legacy_terminal_verified_at")
        .eq("user_id", user_id)
        .eq("epoch_name", epoch),
    )


def _fetch_micro_accounts(client: Any, fleet_section: Dict[str, Any]) -> Dict[str, Any]:
    """Dependent read: needs the fleet id. If the fleet read did not yield a row,
    this is NOT-FETCHED (never a fabricated empty)."""
    if fleet_section["status"] != OK or not fleet_section["rows"]:
        return _not_fetched("bindings", f"fleet_status={fleet_section['status']}")
    fleet_id = fleet_section["rows"][0].get("id")
    if not fleet_id:
        return _not_fetched("bindings", "fleet_row_missing_id")
    return _query_section(
        "bindings",
        client.table("shadow_micro_accounts")
        .select("id,slot_number,state,portfolio_id,policy_registration_id")
        .eq("fleet_id", fleet_id),
    )


def _fetch_policies(client: Any, epoch: str) -> Dict[str, Any]:
    return _query_section(
        "policies",
        client.table("policy_registrations")
        .select("policy_registration_id,policy_family,approval_status,effective_epoch")
        .eq("effective_epoch", epoch),
    )


def _fetch_receipts(client: Any) -> Dict[str, Any]:
    return _query_section(
        "receipts",
        client.table("fleet_reconciliation_receipts").select("*").limit(500),
    )


# ── Derivations (fail-closed; never report "armed" off a broken/absent read) ──

def _derive_single_leg(section: Dict[str, Any]) -> Dict[str, Any]:
    status = section["status"]
    if status == FAILED_FETCH:
        # H9 / §10: a failed read is fail-closed, NEVER "armed".
        state = "epoch_read_failed"
    elif status in (HONEST_EMPTY, NOT_FETCHED):
        state = "epoch_absent"
    else:
        row = section["rows"][0]
        state = row.get("state") or "unknown"
    row = section["rows"][0] if section["rows"] else {}
    return {
        "source": SOURCE,
        "read_status": status,
        "epoch_name": SINGLE_LEG_EPOCH,
        "epoch_state": state,
        "armed": state == "enabled",  # only a genuine 'enabled' epoch row is armed
        "routing_mode": row.get("routing_mode"),
        "live_submit_allowed": row.get("live_submit_allowed"),
        "read_error": section.get("error"),
    }


def _derive_fleet(
    fleet_section: Dict[str, Any],
    bindings_section: Dict[str, Any],
    policies_section: Dict[str, Any],
    receipts_section: Dict[str, Any],
) -> Dict[str, Any]:
    fleet_row = fleet_section["rows"][0] if fleet_section["rows"] else {}
    status = fleet_row.get("status")
    effective_at = fleet_row.get("effective_at")
    # A fleet is ACTIVE only on a successful read with an active status AND a set
    # effective_at. A failed/absent read is fail-closed to not-active.
    active = bool(
        fleet_section["status"] == OK
        and status == "active"
        and effective_at
    )
    micro_rows = bindings_section["rows"]
    bound = sum(1 for r in micro_rows if r.get("policy_registration_id"))
    active_slots = sum(1 for r in micro_rows if r.get("state") == "active")
    policy_rows = policies_section["rows"]
    approved = sum(1 for r in policy_rows if r.get("approval_status") == "approved")
    return {
        "source": SOURCE,
        "fleet_epoch": FLEET_EPOCH,
        "fleet_read_status": fleet_section["status"],
        "fleet_status": status,
        "effective_at": effective_at,
        "legacy_terminal_verified_at": fleet_row.get("legacy_terminal_verified_at"),
        "active": active,
        "bindings_read_status": bindings_section["status"],
        "slots_total": len(micro_rows),
        "slots_bound_to_policy": bound,
        "slots_active": active_slots,
        "policies_read_status": policies_section["status"],
        "policies_total": len(policy_rows),
        "policies_approved": approved,
        "receipts_read_status": receipts_section["status"],
        "receipts_total": len(receipts_section["rows"]),
        "read_errors": {
            k: v["error"]
            for k, v in (
                ("fleet", fleet_section),
                ("bindings", bindings_section),
                ("policies", policies_section),
                ("receipts", receipts_section),
            )
            if v.get("error")
        },
    }


def _derive_e19(fleet_view: Dict[str, Any]) -> Dict[str, Any]:
    """E19 executor state is DERIVED from the fleet epoch — there is no E19
    execution-state table (the executor is post-fleet-epoch and has no runtime;
    census #14, 2026-07-23). Fail-closed: a failed fleet read is unknown, an
    inactive fleet blocks E19."""
    fleet_read = fleet_view["fleet_read_status"]
    if fleet_read == FAILED_FETCH:
        state = "unknown_fleet_read_failed"
    elif fleet_read in (HONEST_EMPTY, NOT_FETCHED):
        state = "blocked_no_fleet"
    elif not fleet_view["active"]:
        state = "blocked_pre_fleet_epoch"
    else:
        # Fleet active — but the executor still writes no runtime rows today.
        state = "fleet_active_no_executor_runtime"
    return {
        "source": SOURCE,
        "derived_from": "fleet_epoch_state",
        "note": "no E19 execution-state table exists; gated on fleet activation",
        "execution_state": state,
        "runtime_rows": 0,  # no E19 execution table to count — structurally zero
    }


def collect_runtime_state(
    client: Any,
    user_id: str,
    *,
    single_leg_epoch: str = SINGLE_LEG_EPOCH,
    fleet_epoch: str = FLEET_EPOCH,
) -> Dict[str, Any]:
    """Read the three DB-state dark-control surfaces. Pure w.r.t. ``client`` —
    deterministic given the same rows. Never raises (per-section fail-closed)."""
    single_leg_section = _fetch_single_leg_epoch(client, single_leg_epoch)
    fleet_section = _fetch_fleet(client, user_id, fleet_epoch)
    bindings_section = _fetch_micro_accounts(client, fleet_section)
    policies_section = _fetch_policies(client, fleet_epoch)
    receipts_section = _fetch_receipts(client)

    sections = {
        "single_leg_epoch": single_leg_section,
        "fleet": fleet_section,
        "bindings": bindings_section,
        "policies": policies_section,
        "receipts": receipts_section,
    }
    section_status = {name: sec["status"] for name, sec in sorted(sections.items())}
    degraded = sorted(n for n, s in section_status.items() if s == FAILED_FETCH)

    fleet_view = _derive_fleet(
        fleet_section, bindings_section, policies_section, receipts_section
    )
    return {
        "source": SOURCE,
        "status": "DEGRADED" if degraded else "OK",
        "failed_sections": degraded,
        "section_status": section_status,
        "single_leg": _derive_single_leg(single_leg_section),
        "fleet": fleet_view,
        "e19_execution": _derive_e19(fleet_view),
    }


def render_runtime_state_block(state: Dict[str, Any]) -> str:
    """One greppable multi-line ``[RUNTIME_STATE_ECHO]`` block. Deterministic."""
    sl = state["single_leg"]
    fl = state["fleet"]
    e19 = state["e19_execution"]
    lines = [
        f"[RUNTIME_STATE_ECHO] DB-backed dark-control state "
        f"(source={SOURCE}, status={state['status']}, "
        f"failed_sections={state['failed_sections']})",
        f"[RUNTIME_STATE_ECHO]   single_leg: epoch={sl['epoch_name']} "
        f"state={sl['epoch_state']} armed={sl['armed']} "
        f"(read={sl['read_status']})",
        f"[RUNTIME_STATE_ECHO]   fleet: epoch={fl['fleet_epoch']} "
        f"status={fl['fleet_status']} active={fl['active']} "
        f"slots={fl['slots_total']} bound={fl['slots_bound_to_policy']} "
        f"active_slots={fl['slots_active']} approved_policies={fl['policies_approved']} "
        f"receipts={fl['receipts_total']} (read={fl['fleet_read_status']})",
        f"[RUNTIME_STATE_ECHO]   e19: execution_state={e19['execution_state']} "
        f"runtime_rows={e19['runtime_rows']} (derived_from={e19['derived_from']})",
    ]
    return "\n".join(lines)


def runtime_state_echo(
    client: Any,
    user_id: str,
    *,
    log: bool = True,
    single_leg_epoch: str = SINGLE_LEG_EPOCH,
    fleet_epoch: str = FLEET_EPOCH,
) -> Dict[str, Any]:
    """Operator entry point: collect + (optionally) log the block + return the dict.

    NOT called at process startup — a DB read must never sit on the start path.
    """
    state = collect_runtime_state(
        client, user_id, single_leg_epoch=single_leg_epoch, fleet_epoch=fleet_epoch
    )
    state["generated_at"] = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    if log:
        logger.info(render_runtime_state_block(state))
    return state
