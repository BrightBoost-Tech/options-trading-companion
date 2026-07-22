"""Internal-paper lifecycle for one-contract single-leg shadow candidates.

No function in this module imports or calls a broker adapter. Opens and closes
are committed only through SECURITY DEFINER RPCs created by
``20260722010000_single_leg_shadow_internal_lifecycle.sql``. The RPCs re-check
the enabled epoch, approved opt-in policy, experimental binding, one-contract
identity, portfolio cash, and shadow-only routing inside the same transaction.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from packages.quantum.services.replay.replay_truth_layer import ReplayTruthLayer
from packages.quantum.services.single_leg_shadow_evidence import (
    SingleLegShadowEvidenceWriter,
)

logger = logging.getLogger(__name__)

ORDERS_TABLE = "single_leg_shadow_orders"
POSITIONS_TABLE = "single_leg_shadow_positions"
OUTCOMES_TABLE = "single_leg_shadow_outcomes"
ATTEMPTS_TABLE = "single_leg_shadow_attempts"
RUNS_TABLE = "single_leg_shadow_runs"
EVENTS_TABLE = "single_leg_shadow_lifecycle_events"
OPEN_RPC = "rpc_open_single_leg_shadow_position_v1"
CLOSE_RPC = "rpc_close_single_leg_shadow_position_v1"


def _rows(result: Any) -> List[Dict[str, Any]]:
    rows = getattr(result, "data", None)
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _expiry(contract: Mapping[str, Any]) -> Optional[str]:
    raw = contract.get("expiry") or contract.get("expiration")
    return str(raw)[:10] if raw else None


def _occ(contract: Mapping[str, Any]) -> str:
    return str(
        contract.get("contract")
        or contract.get("occ_symbol")
        or contract.get("ticker")
        or ""
    )


def _find_contract(
    replay: ReplayTruthLayer,
    symbol: str,
    occ_symbol: str,
) -> Optional[Dict[str, Any]]:
    prefix = f"{symbol}:chain"
    for (key, snapshot_type) in sorted(replay.inputs_map):
        if snapshot_type != "chain" or not str(key).startswith(prefix):
            continue
        stored = replay.get_stored_input(key, snapshot_type)
        payload = stored.get("payload") if isinstance(stored, Mapping) else None
        if not isinstance(payload, list):
            continue
        for raw in payload:
            if isinstance(raw, Mapping) and _occ(raw) == occ_symbol:
                return dict(raw)
    return None


def _quote(contract: Mapping[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    nested = contract.get("quote")
    quote = nested if isinstance(nested, Mapping) else contract
    bid = _finite(quote.get("bid"))
    ask = _finite(quote.get("ask"))
    mid = _finite(quote.get("mid"))
    if mid is None and bid is not None and ask is not None:
        mid = (bid + ask) / 2.0
    return bid, ask, mid


def _option_type(strategy_type: str) -> Optional[str]:
    if strategy_type == "long_call":
        return "call"
    if strategy_type == "long_put":
        return "put"
    return None


def _policy_max_debit(client: Any, policy_registration_id: str) -> float:
    try:
        result = (
            client.table("policy_registrations")
            .select("policy_config")
            .eq("policy_registration_id", policy_registration_id)
            .eq("approval_status", "approved")
            .limit(1)
            .execute()
        )
        rows = _rows(result)
        config = rows[0].get("policy_config") if rows else None
        raw = (
            config.get("single_leg_max_debit_per_contract")
            if isinstance(config, Mapping)
            else None
        )
        parsed = _finite(raw)
        if parsed is not None and parsed > 0:
            return parsed
    except Exception:
        logger.exception("failed to read single-leg policy debit cap")
    return 150.0


def _run_row(client: Any, run_id: str) -> Optional[Dict[str, Any]]:
    result = (
        client.table(RUNS_TABLE)
        .select(
            "run_id,source_job_run_id,source_decision_id,source_code_sha,"
            "policy_epoch,policy_registration_id,portfolio_id,user_id,as_of,status"
        )
        .eq("run_id", run_id)
        .limit(1)
        .execute()
    )
    rows = _rows(result)
    return rows[0] if rows else None


def _candidate_attempts(client: Any, run_id: str) -> List[Dict[str, Any]]:
    result = (
        client.table(ATTEMPTS_TABLE)
        .select(
            "attempt_id,run_id,policy_registration_id,user_id,symbol,"
            "strategy_type,candidate_fingerprint,occ_symbol,strike,expiry,"
            "debit_per_contract,known_at,evidence"
        )
        .eq("run_id", run_id)
        .eq("stage", "candidate_generated")
        .execute()
    )
    return _rows(result)


def _record_execution_rejection(
    client: Any,
    run: Mapping[str, Any],
    attempt: Mapping[str, Any],
    *,
    reason_code: str,
    detail: str,
    evidence: Optional[Mapping[str, Any]] = None,
) -> bool:
    writer = SingleLegShadowEvidenceWriter(
        client,
        source_job_run_id=str(run.get("source_job_run_id")),
        source_decision_id=str(run.get("source_decision_id")),
        user_id=str(run.get("user_id")),
        policy_registration_id=str(run.get("policy_registration_id")),
        portfolio_id=str(run.get("portfolio_id")),
        policy_epoch=str(run.get("policy_epoch")),
        source_code_sha=run.get("source_code_sha"),
        as_of=run.get("as_of"),
    )
    if not writer.begin_run():
        return False
    ok_attempt = writer.record_attempt(
        symbol=str(attempt.get("symbol") or "<unknown>"),
        stage="execution_rejected",
        reason_code=reason_code,
        detail=detail,
        direction=(
            "bullish" if attempt.get("strategy_type") == "long_call" else "bearish"
        ),
        strategy_type=attempt.get("strategy_type"),
        candidate={
            "policy_registration_id": attempt.get("policy_registration_id"),
            "symbol": attempt.get("symbol"),
            "strategy_type": attempt.get("strategy_type"),
            "occ_symbol": attempt.get("occ_symbol"),
            "strike": attempt.get("strike"),
            "expiry": attempt.get("expiry"),
            "option_type": _option_type(str(attempt.get("strategy_type") or "")),
            "contracts": 1,
            "debit_per_contract": attempt.get("debit_per_contract"),
            "known_at": attempt.get("known_at"),
        },
        known_at=attempt.get("known_at"),
        evidence=evidence or {},
    )
    fingerprint = str(attempt.get("candidate_fingerprint") or "")
    ok_event = writer.record_event(
        event_type="execution_rejected",
        entity_type="candidate",
        entity_id=fingerprint or str(attempt.get("attempt_id")),
        candidate_fingerprint_value=fingerprint or None,
        payload={"reason_code": reason_code, "detail": detail},
        occurred_at=attempt.get("known_at"),
    )
    return ok_attempt and ok_event


def execute_run_candidates(
    client: Any,
    run_id: str,
    *,
    replay: Optional[ReplayTruthLayer] = None,
    rpc_caller: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """Internally fill all generated candidates for one experiment run.

    The fill uses the exact source-tape ask for a one-contract BUY. A missing,
    crossed, zero, non-finite, identity-mismatched, or over-cap quote is durably
    rejected. The function never imports or invokes a broker client.
    """

    counts = {
        "candidates": 0,
        "filled_internal": 0,
        "execution_rejected": 0,
        "idempotent_replays": 0,
        "errors": 0,
    }
    error_details: List[Dict[str, Any]] = []

    try:
        run = _run_row(client, run_id)
    except Exception as exc:
        return {
            "status": "run_read_failed",
            "counts": {**counts, "errors": 1},
            "error_details": [{"stage": "run_read", "error": str(exc)[:200]}],
        }
    if not run:
        return {
            "status": "run_missing",
            "counts": {**counts, "errors": 1},
            "error_details": [{"stage": "run_read", "run_id": run_id}],
        }

    try:
        attempts = _candidate_attempts(client, run_id)
    except Exception as exc:
        return {
            "status": "attempt_read_failed",
            "counts": {**counts, "errors": 1},
            "error_details": [{"stage": "attempt_read", "error": str(exc)[:200]}],
        }
    counts["candidates"] = len(attempts)
    if not attempts:
        return {"status": "honest_empty", "counts": counts, "error_details": []}

    if replay is None:
        replay = ReplayTruthLayer.from_decision_id(
            client, str(run.get("source_decision_id"))
        )
    if replay is None:
        for attempt in attempts:
            _record_execution_rejection(
                client,
                run,
                attempt,
                reason_code="source_decision_unavailable",
                detail="source tape unavailable at internal execution seam",
            )
        counts["execution_rejected"] = len(attempts)
        counts["errors"] = 1
        return {
            "status": "source_decision_unavailable",
            "counts": counts,
            "error_details": [{"stage": "load_source_tape"}],
        }

    if rpc_caller is None:
        rpc_caller = lambda name, params: client.rpc(name, params).execute()

    max_debit = _policy_max_debit(client, str(run.get("policy_registration_id")))

    for attempt in attempts:
        symbol = str(attempt.get("symbol") or "")
        occ_symbol = str(attempt.get("occ_symbol") or "")
        strategy_type = str(attempt.get("strategy_type") or "")
        option_type = _option_type(strategy_type)
        fingerprint = str(attempt.get("candidate_fingerprint") or "")
        contract = _find_contract(replay, symbol, occ_symbol)

        reason = None
        detail = None
        evidence: Dict[str, Any] = {}
        if contract is None:
            reason = "exact_contract_unavailable"
            detail = "exact selected contract is absent from the committed source tape"
        else:
            bid, ask, mid = _quote(contract)
            evidence = {
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "source": contract.get("source"),
                "provider_ts": contract.get("provider_ts"),
                "retrieved_ts": contract.get("retrieved_ts"),
            }
            if bid is None or ask is None or bid <= 0 or ask <= 0:
                reason = "execution_quote_unavailable"
                detail = "source-tape bid/ask is missing, non-finite, or non-positive"
            elif ask < bid:
                reason = "execution_quote_crossed"
                detail = f"source-tape ask {ask} is below bid {bid}"
            elif ask * 100 > max_debit + 1e-9:
                reason = "execution_debit_exceeds_max"
                detail = (
                    f"ask debit ${ask * 100:.2f} exceeds policy cap ${max_debit:.2f}"
                )
            elif not option_type or not fingerprint or not occ_symbol:
                reason = "execution_identity_invalid"
                detail = "candidate identity/strategy is incomplete"

        if reason:
            ok = _record_execution_rejection(
                client,
                run,
                attempt,
                reason_code=reason,
                detail=detail or reason,
                evidence=evidence,
            )
            counts["execution_rejected"] += 1
            if not ok:
                counts["errors"] += 1
                error_details.append(
                    {"stage": "write_execution_rejection", "symbol": symbol}
                )
            continue

        params = {
            "p_run_id": run_id,
            "p_policy_registration_id": run.get("policy_registration_id"),
            "p_portfolio_id": run.get("portfolio_id"),
            "p_user_id": run.get("user_id"),
            "p_candidate_fingerprint": fingerprint,
            "p_symbol": symbol,
            "p_occ_symbol": occ_symbol,
            "p_option_type": option_type,
            "p_strategy_type": strategy_type,
            "p_strike": attempt.get("strike"),
            "p_expiry": attempt.get("expiry"),
            "p_fill_price_per_share": ask,
            "p_source_known_at": attempt.get("known_at") or run.get("as_of"),
            "p_filled_at": attempt.get("known_at") or run.get("as_of"),
        }
        try:
            response = rpc_caller(OPEN_RPC, params)
            rows = getattr(response, "data", None)
            result = rows[0] if isinstance(rows, list) and rows else rows
            if not isinstance(result, Mapping):
                raise RuntimeError("open RPC returned no typed receipt")
            counts["filled_internal"] += 1
            if result.get("idempotent_replay"):
                counts["idempotent_replays"] += 1
        except Exception as exc:
            logger.exception("single-leg internal open failed: %s", symbol)
            ok = _record_execution_rejection(
                client,
                run,
                attempt,
                reason_code="internal_open_failed",
                detail=f"{type(exc).__name__}: {str(exc)[:160]}",
                evidence=evidence,
            )
            counts["execution_rejected"] += 1
            counts["errors"] += 1
            if not ok:
                counts["errors"] += 1
            error_details.append(
                {
                    "stage": "internal_open",
                    "symbol": symbol,
                    "error_class": type(exc).__name__,
                    "error": str(exc)[:200],
                }
            )

    return {
        "status": "partial" if counts["errors"] else "succeeded",
        "counts": counts,
        "error_details": error_details[:20],
    }


def _snapshot_spot(snapshot: Any) -> Optional[float]:
    if snapshot is None:
        return None
    quote = getattr(snapshot, "quote", None)
    if quote is None and isinstance(snapshot, Mapping):
        quote = snapshot.get("quote")
    values: Iterable[Any]
    if isinstance(quote, Mapping):
        values = (quote.get("last"), quote.get("mid"), quote.get("bid"))
    else:
        values = (
            getattr(quote, "last", None),
            getattr(quote, "mid", None),
            getattr(quote, "bid", None),
        )
    for value in values:
        parsed = _finite(value)
        if parsed is not None and parsed >= 0:
            return parsed
    return None


def _record_settlement_deferred(
    client: Any,
    position: Mapping[str, Any],
    as_of: datetime,
    reason: str,
) -> None:
    entity_id = f"{position.get('position_id')}:{as_of.date().isoformat()}"
    payload = {
        "reason": reason,
        "symbol": position.get("symbol"),
        "expiry": position.get("expiry"),
    }
    try:
        client.table(EVENTS_TABLE).insert(
            {
                "run_id": position.get("run_id"),
                "policy_registration_id": position.get("policy_registration_id"),
                "user_id": position.get("user_id"),
                "event_type": "settlement_deferred",
                "entity_type": "position_day",
                "entity_id": entity_id,
                "candidate_fingerprint": position.get("candidate_fingerprint"),
                "payload": payload,
                "occurred_at": as_of.isoformat(),
            }
        ).execute()
    except Exception as exc:
        msg = str(exc).lower()
        if "23505" not in msg and "duplicate key" not in msg:
            logger.exception("failed to persist settlement_deferred")


def settle_expired_positions(
    client: Any,
    user_id: str,
    *,
    as_of: Optional[datetime] = None,
    snapshot_fetcher: Optional[Callable[[List[str]], Mapping[str, Any]]] = None,
    rpc_caller: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """Settle expired one-contract positions at intrinsic value.

    Missing market truth never fabricates a terminal spot: the position remains
    open and a dated ``settlement_deferred`` event is written. The next natural
    evaluation retries safely.
    """

    as_of = as_of or datetime.now(timezone.utc)
    today = as_of.date().isoformat()
    counts = {
        "eligible": 0,
        "closed": 0,
        "deferred": 0,
        "idempotent_replays": 0,
        "errors": 0,
    }
    try:
        result = (
            client.table(POSITIONS_TABLE)
            .select(
                "position_id,run_id,policy_registration_id,portfolio_id,user_id,"
                "candidate_fingerprint,symbol,expiry,status"
            )
            .eq("user_id", user_id)
            .eq("status", "open")
            .lte("expiry", today)
            .execute()
        )
        positions = _rows(result)
    except Exception as exc:
        return {
            "status": "position_read_failed",
            "counts": {**counts, "errors": 1},
            "error_details": [{"stage": "position_read", "error": str(exc)[:200]}],
        }

    counts["eligible"] = len(positions)
    if not positions:
        return {"status": "honest_empty", "counts": counts, "error_details": []}

    symbols = sorted({str(row.get("symbol")) for row in positions if row.get("symbol")})
    if snapshot_fetcher is None:
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer

        truth = MarketDataTruthLayer()
        snapshot_fetcher = truth.snapshot_many_v4
    try:
        snapshots = snapshot_fetcher(symbols) or {}
    except Exception as exc:
        snapshots = {}
        logger.exception("single-leg expiry snapshot fetch failed")

    if rpc_caller is None:
        rpc_caller = lambda name, params: client.rpc(name, params).execute()

    errors: List[Dict[str, Any]] = []
    for position in positions:
        symbol = str(position.get("symbol") or "")
        spot = _snapshot_spot(snapshots.get(symbol))
        if spot is None:
            _record_settlement_deferred(client, position, as_of, "terminal_spot_unavailable")
            counts["deferred"] += 1
            continue
        try:
            response = rpc_caller(
                CLOSE_RPC,
                {
                    "p_position_id": position.get("position_id"),
                    "p_terminal_spot": spot,
                    "p_closed_at": as_of.isoformat(),
                    "p_close_reason": "expiry",
                },
            )
            rows = getattr(response, "data", None)
            receipt = rows[0] if isinstance(rows, list) and rows else rows
            if not isinstance(receipt, Mapping):
                raise RuntimeError("close RPC returned no typed receipt")
            counts["closed"] += 1
            if receipt.get("idempotent_replay"):
                counts["idempotent_replays"] += 1
        except Exception as exc:
            logger.exception("single-leg expiry close failed: %s", position.get("position_id"))
            counts["errors"] += 1
            errors.append(
                {
                    "stage": "expiry_close",
                    "position_id": position.get("position_id"),
                    "error_class": type(exc).__name__,
                    "error": str(exc)[:200],
                }
            )

    return {
        "status": "partial" if counts["errors"] else "succeeded",
        "counts": counts,
        "error_details": errors[:20],
    }
