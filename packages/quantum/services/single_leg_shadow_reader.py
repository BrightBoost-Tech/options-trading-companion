"""Deterministic read-only report for the single-leg shadow experiment."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

EPOCH = "single_leg_experiment_v1"
CONTROL_MATCH = {
    "sl_exp_throughput_v1": "aggressive",
    "sl_exp_conviction_v1": "conservative",
}


def _rows(response: Any) -> List[Dict[str, Any]]:
    rows = getattr(response, "data", None)
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def _query_section(name: str, query) -> Dict[str, Any]:
    try:
        return {"status": "OK", "rows": _rows(query.execute()), "error": None}
    except Exception as exc:
        return {
            "status": "FAILED-FETCH",
            "rows": [],
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            "section": name,
        }


def fetch_single_leg_shadow_sections(
    client: Any,
    user_id: str,
    *,
    epoch: str = EPOCH,
) -> Dict[str, Dict[str, Any]]:
    """Fetch every experiment surface independently.

    A failed section is never represented as an empty measurement. Each section
    carries its own status so downstream synthesis can abstain precisely.
    """

    sections = {
        "epoch": _query_section(
            "epoch",
            client.table("single_leg_experiment_epochs")
            .select("epoch_name,state,routing_mode,max_contracts,live_submit_allowed,config_hash,version,enabled_at,enabled_by,created_at")
            .eq("epoch_name", epoch),
        ),
        "policies": _query_section(
            "policies",
            client.table("policy_registrations")
            .select("policy_registration_id,policy_family,anchor_lineage,approval_status,effective_epoch,config_hash,policy_config,created_at,approved_at")
            .eq("effective_epoch", epoch),
        ),
        "bindings": _query_section(
            "bindings",
            client.table("single_leg_experiment_bindings")
            .select("policy_registration_id,epoch_name,portfolio_id,user_id,role,routing_mode,execution_mode,enabled,created_at")
            .eq("epoch_name", epoch)
            .eq("user_id", user_id),
        ),
        "runs": _query_section(
            "runs",
            client.table("single_leg_shadow_runs")
            .select("run_id,source_job_run_id,source_decision_id,source_code_sha,policy_epoch,policy_registration_id,portfolio_id,user_id,as_of,status,counts,error_details,created_at,started_at,finished_at")
            .eq("policy_epoch", epoch)
            .eq("user_id", user_id),
        ),
        "attempts": _query_section(
            "attempts",
            client.table("single_leg_shadow_attempts")
            .select("attempt_id,run_id,policy_registration_id,user_id,symbol,direction,strategy_type,stage,reason_code,candidate_fingerprint,occ_symbol,strike,expiry,debit_per_contract,ev_expected_value,ev_pop,ev_basis,ev_model,considered_contracts,viable_contracts,provider,known_at,created_at")
            .eq("user_id", user_id),
        ),
        "events": _query_section(
            "events",
            client.table("single_leg_shadow_lifecycle_events")
            .select("event_id,run_id,policy_registration_id,user_id,event_type,entity_type,entity_id,candidate_fingerprint,payload,occurred_at,created_at")
            .eq("user_id", user_id),
        ),
        "orders": _query_section(
            "orders",
            client.table("single_leg_shadow_orders")
            .select("order_id,run_id,policy_registration_id,portfolio_id,user_id,candidate_fingerprint,symbol,occ_symbol,option_type,strategy_type,contracts,fill_price_per_share,debit_total,source_known_at,routing_mode,execution_mode,lifecycle_state,live_submit_allowed,status,filled_at,created_at")
            .eq("user_id", user_id),
        ),
        "positions": _query_section(
            "positions",
            client.table("single_leg_shadow_positions")
            .select("position_id,order_id,run_id,policy_registration_id,portfolio_id,user_id,candidate_fingerprint,symbol,occ_symbol,option_type,strategy_type,strike,expiry,contracts,entry_price_per_share,entry_debit_total,status,routing_mode,execution_mode,lifecycle_state,live_submit_allowed,opened_at,closed_at,terminal_spot,terminal_value,realized_pnl,close_reason")
            .eq("user_id", user_id),
        ),
        "outcomes": _query_section(
            "outcomes",
            client.table("single_leg_shadow_outcomes")
            .select("outcome_id,position_id,run_id,policy_registration_id,portfolio_id,user_id,candidate_fingerprint,symbol,strategy_type,opened_at,closed_at,entry_debit_total,terminal_value,realized_pnl,close_reason,execution_mode,experiment,is_paper,created_at")
            .eq("user_id", user_id),
        ),
        "cash_events": _query_section(
            "cash_events",
            client.table("single_leg_shadow_cash_events")
            .select("cash_event_id,portfolio_id,policy_registration_id,user_id,order_id,position_id,event_type,amount,balance_before,balance_after,idempotency_key,created_at")
            .eq("user_id", user_id),
        ),
    }
    for section in sections.values():
        if section["status"] == "OK" and not section["rows"]:
            section["status"] = "HONEST-EMPTY"
    return sections


def _number(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _time_values(rows: Iterable[Mapping[str, Any]], keys: Tuple[str, ...]) -> List[str]:
    values: List[str] = []
    for row in rows:
        for key in keys:
            raw = row.get(key)
            if raw:
                values.append(str(raw))
                break
    return sorted(values)


def _counter_rows(counter: Counter) -> List[Dict[str, Any]]:
    return [
        {"key": key, "count": counter[key]}
        for key in sorted(counter, key=lambda item: str(item))
    ]


def summarize_single_leg_shadow_sections(
    sections: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Produce a deterministic, cohort-separated summary."""

    failed = sorted(
        name for name, section in sections.items()
        if section.get("status") == "FAILED-FETCH"
    )
    rows = {
        name: list(section.get("rows") or [])
        for name, section in sections.items()
    }

    attempts = rows.get("attempts", [])
    orders = rows.get("orders", [])
    positions = rows.get("positions", [])
    outcomes = rows.get("outcomes", [])
    runs = rows.get("runs", [])
    events = rows.get("events", [])
    bindings = rows.get("bindings", [])
    policies = rows.get("policies", [])

    attempts_by_stage = Counter(str(row.get("stage") or "<null>") for row in attempts)
    rejections = Counter(
        (
            str(row.get("stage") or "<null>"),
            str(row.get("reason_code") or "<null>"),
        )
        for row in attempts
        if row.get("stage") in ("selection_rejected", "gate_rejected", "execution_rejected")
    )
    events_by_type = Counter(str(row.get("event_type") or "<null>") for row in events)
    runs_by_status = Counter(str(row.get("status") or "<null>") for row in runs)
    positions_by_status = Counter(str(row.get("status") or "<null>") for row in positions)

    policy_summary: Dict[str, Dict[str, Any]] = {}
    policy_ids = sorted(
        {
            str(row.get("policy_registration_id"))
            for collection in (policies, bindings, runs, attempts, orders, positions, outcomes)
            for row in collection
            if row.get("policy_registration_id")
        }
    )
    for policy_id in policy_ids:
        policy_attempts = [row for row in attempts if row.get("policy_registration_id") == policy_id]
        policy_orders = [row for row in orders if row.get("policy_registration_id") == policy_id]
        policy_positions = [row for row in positions if row.get("policy_registration_id") == policy_id]
        policy_outcomes = [row for row in outcomes if row.get("policy_registration_id") == policy_id]
        policy_runs = [row for row in runs if row.get("policy_registration_id") == policy_id]
        policy_summary[policy_id] = {
            "matched_control_family": CONTROL_MATCH.get(policy_id),
            "runs": len(policy_runs),
            "attempts": len(policy_attempts),
            "generated_candidates": sum(
                1 for row in policy_attempts if row.get("stage") == "candidate_generated"
            ),
            "internal_fills": len(policy_orders),
            "open_positions": sum(1 for row in policy_positions if row.get("status") == "open"),
            "closed_positions": sum(1 for row in policy_positions if row.get("status") == "closed"),
            "outcomes": len(policy_outcomes),
            "realized_pnl": round(sum(_number(row.get("realized_pnl")) for row in policy_outcomes), 2),
        }

    times = _time_values(
        runs + attempts + orders + positions + outcomes,
        ("as_of", "known_at", "filled_at", "opened_at", "closed_at", "created_at"),
    )

    epoch_rows = rows.get("epoch", [])
    epoch = epoch_rows[0] if epoch_rows else None
    opt_in_policies = sorted(
        str(row.get("policy_registration_id"))
        for row in policies
        if isinstance(row.get("policy_config"), Mapping)
        and row["policy_config"].get("single_leg_experiment_enabled") is True
    )

    summary = {
        "status": "PARTIAL" if failed else "OK",
        "failed_sections": failed,
        "section_status": {
            name: section.get("status") for name, section in sorted(sections.items())
        },
        "epoch": {
            "state": epoch.get("state") if epoch else None,
            "routing_mode": epoch.get("routing_mode") if epoch else None,
            "max_contracts": epoch.get("max_contracts") if epoch else None,
            "live_submit_allowed": epoch.get("live_submit_allowed") if epoch else None,
            "version": epoch.get("version") if epoch else None,
        },
        "policy_counts": {
            "total": len(policies),
            "approved": sum(1 for row in policies if row.get("approval_status") == "approved"),
            "draft": sum(1 for row in policies if row.get("approval_status") == "draft"),
            "opt_in": len(opt_in_policies),
            "opt_in_policy_ids": opt_in_policies,
        },
        "binding_counts": {
            "total": len(bindings),
            "enabled": sum(1 for row in bindings if row.get("enabled") is True),
            "experimental": sum(1 for row in bindings if row.get("role") == "experimental"),
        },
        "headline": {
            "runs": len(runs),
            "attempts": len(attempts),
            "generated_candidates": attempts_by_stage.get("candidate_generated", 0),
            "internal_fills": len(orders),
            "open_positions": positions_by_status.get("open", 0),
            "closed_positions": positions_by_status.get("closed", 0),
            "outcomes": len(outcomes),
            "realized_pnl": round(sum(_number(row.get("realized_pnl")) for row in outcomes), 2),
            "first_evidence_at": times[0] if times else None,
            "latest_evidence_at": times[-1] if times else None,
        },
        "runs_by_status": _counter_rows(runs_by_status),
        "attempts_by_stage": _counter_rows(attempts_by_stage),
        "rejections": [
            {"stage": stage, "reason_code": reason, "count": count}
            for (stage, reason), count in sorted(rejections.items())
        ],
        "events_by_type": _counter_rows(events_by_type),
        "positions_by_status": _counter_rows(positions_by_status),
        "policies": {key: policy_summary[key] for key in sorted(policy_summary)},
        "isolation": {
            "routing_modes": sorted({str(row.get("routing_mode")) for row in orders if row.get("routing_mode")}),
            "execution_modes": sorted({str(row.get("execution_mode")) for row in orders + outcomes if row.get("execution_mode")}),
            "live_submit_true_rows": sum(1 for row in orders + positions if row.get("live_submit_allowed") is True),
            "non_one_contract_orders": sum(1 for row in orders if row.get("contracts") != 1),
        },
    }
    return summary


def read_single_leg_shadow_evidence(
    client: Any,
    user_id: str,
    *,
    epoch: str = EPOCH,
) -> Dict[str, Any]:
    sections = fetch_single_leg_shadow_sections(client, user_id, epoch=epoch)
    return {
        "epoch": epoch,
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "summary": summarize_single_leg_shadow_sections(sections),
        "sections": sections,
    }
