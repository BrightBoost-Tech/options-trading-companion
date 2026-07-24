"""Isolated internal-paper lifecycle for the recurring shadow fleet (C2).

No function in this module imports or calls a broker adapter. Opens and closes
are committed ONLY through SECURITY DEFINER RPCs (migration
``20260723170000_fleet_shadow_internal_lifecycle.sql``) that re-check — inside the
same transaction — the active fleet, the active/bound micro-account, shadow-only
routing, the SELECTED-decision candidate identity, and portfolio cash. While the
fleet is inactive there is no selected decision and the RPCs reject every call:
this module is a true no-op.

Scope (C2 v1, symmetric with the single-leg lifecycle v1): open + EXPIRY
settlement. Intraday stop / target-profit / DTE trigger management on the
executable-corroborated UPL is the named remaining edge (see the PR body);
single-leg v1 is likewise expiry-only.

Cash model (uniform defined-risk collateral): at open the RPC reserves
``max_loss_total``; at expiry it releases ``max_loss_total + realized_pnl`` where
``realized_pnl = terminal_payoff_total - entry_net_cost_total``. Fills are at the
source-tape EXECUTABLE side (buy legs at ask, sell legs at bid); an unpriceable
leg is a typed rejection, never a mid fallback (H9).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from packages.quantum.services.options_utils import parse_option_symbol

logger = logging.getLogger(__name__)

RUNS_TABLE = "fleet_policy_decision_runs"
DECISIONS_TABLE = "fleet_policy_decisions"
ORDERS_TABLE = "fleet_shadow_orders"
POSITIONS_TABLE = "fleet_shadow_positions"
OPEN_RPC = "rpc_open_fleet_shadow_position_v1"
CLOSE_RPC = "rpc_close_fleet_shadow_position_v1"

_TABLE_MISSING_MARKERS = ("pgrst205", "42p01", "could not find the table", "schema cache")


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


def _is_table_missing(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _TABLE_MISSING_MARKERS)


# ─────────────────────────────────────────────────────────────────────────────
# Fail-closed open-position counter (C1 capacity input, wired by the handler).
# ─────────────────────────────────────────────────────────────────────────────
def count_open_fleet_positions(client: Any, shadow_micro_account_id: str) -> int:
    """Open fleet-shadow position count for one micro-account.

    A read error RAISES (fail-closed) so C1's per-policy try/except records
    ``evaluator_failed`` rather than silently sizing against a fabricated 0
    (the E8-3 []-sentinel lesson). While the fleet is inactive this is never
    reached (no active accounts). If the C2 table is absent there are provably
    zero fleet positions -> 0.
    """
    try:
        result = (
            client.table(POSITIONS_TABLE)
            .select("position_id", count="exact")
            .eq("shadow_micro_account_id", shadow_micro_account_id)
            .eq("status", "open")
            .execute()
        )
    except Exception as exc:
        if _is_table_missing(exc):
            return 0
        raise
    count = getattr(result, "count", None)
    if isinstance(count, int):
        return count
    return len(_rows(result))


# ─────────────────────────────────────────────────────────────────────────────
# Leg normalization + executable-side entry cost (from the source tape).
# ─────────────────────────────────────────────────────────────────────────────
def normalize_fleet_legs(
    order_json: Mapping[str, Any],
    fleet_contracts: int,
) -> Optional[Dict[str, Any]]:
    """Normalize a multi-leg structure to signed, fleet-sized legs.

    Returns None (typed rejection upstream) when the structure is malformed:
    missing/empty legs, an unparseable OCC symbol, a non-integer leg ratio, or
    mixed expiries. Never fabricates a leg (H9 / doctrine §10 canonical payoff).
    """
    legs = order_json.get("legs")
    if not isinstance(legs, list) or not legs:
        return None
    try:
        source_contracts = int(order_json.get("contracts") or 0)
    except (TypeError, ValueError):
        return None
    if source_contracts < 1 or fleet_contracts < 1:
        return None

    normalized: List[Dict[str, Any]] = []
    ratios: List[Tuple[str, int]] = []  # (side, leg_ratio) for entry-cost pairing
    expiries = set()
    underlying = str(order_json.get("underlying") or "").strip()
    for leg in legs:
        if not isinstance(leg, Mapping):
            return None
        side = str(leg.get("side") or "").lower()
        symbol = str(leg.get("symbol") or "")
        try:
            leg_qty = int(leg.get("quantity") or 0)
        except (TypeError, ValueError):
            return None
        if side not in ("buy", "sell") or leg_qty < 1:
            return None
        # Leg ratio must be an exact integer multiple of the structure quantity.
        if leg_qty % source_contracts != 0:
            return None
        ratio = leg_qty // source_contracts
        if ratio < 1:
            return None
        parsed = parse_option_symbol(symbol)
        if not parsed or parsed.get("type") not in ("C", "P"):
            return None
        strike = _finite(parsed.get("strike"))
        if strike is None or strike <= 0:
            return None
        expiries.add(parsed.get("expiry"))
        if not underlying:
            underlying = str(parsed.get("underlying") or "")
        normalized.append(
            {
                "option_type": "call" if parsed["type"] == "C" else "put",
                "strike": strike,
                "sign": 1 if side == "buy" else -1,
                "contracts": ratio * fleet_contracts,
                "occ_symbol": symbol,
            }
        )
        ratios.append((side, ratio))
    if len(expiries) != 1 or not underlying:
        return None
    return {
        "legs": normalized,
        "ratios": ratios,
        "underlying": underlying,
        "expiry": next(iter(expiries)),
    }


def _leg_executable_quote(
    replay: Any,
    underlying: str,
    occ_symbol: str,
) -> Tuple[Optional[float], Optional[float]]:
    """(bid, ask) for one leg from the committed source tape, or (None, None)."""
    prefix = f"{underlying}:chain"
    for (key, snapshot_type) in sorted(getattr(replay, "inputs_map", {}) or {}):
        if snapshot_type != "chain" or not str(key).startswith(prefix):
            continue
        stored = replay.get_stored_input(key, snapshot_type)
        payload = stored.get("payload") if isinstance(stored, Mapping) else None
        if not isinstance(payload, list):
            continue
        for raw in payload:
            if not isinstance(raw, Mapping):
                continue
            sym = str(raw.get("contract") or raw.get("occ_symbol") or raw.get("ticker") or "")
            if sym != occ_symbol:
                continue
            quote = raw.get("quote") if isinstance(raw.get("quote"), Mapping) else raw
            return _finite(quote.get("bid")), _finite(quote.get("ask"))
    return None, None


def compute_entry_net_cost(
    replay: Any,
    order_json: Mapping[str, Any],
    normalized: Mapping[str, Any],
    fleet_contracts: int,
) -> Optional[float]:
    """Executable-side net entry cost (buy->ask, sell->bid), signed debit>0.

    Returns None when ANY leg is unpriceable / crossed / non-positive in the
    source tape — a typed rejection upstream, never a mid fallback (H9).
    """
    underlying = str(normalized.get("underlying") or "")
    legs = order_json.get("legs") or []
    ratios = normalized.get("ratios") or []
    if len(legs) != len(ratios):
        return None
    net_per_share = 0.0
    for leg, (side, ratio) in zip(legs, ratios):
        occ = str(leg.get("symbol") or "")
        bid, ask = _leg_executable_quote(replay, underlying, occ)
        if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
            return None
        if side == "buy":
            net_per_share += ask * ratio
        else:
            net_per_share -= bid * ratio
    return round(net_per_share * fleet_contracts * 100, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Open lifecycle: fill every SELECTED decision for one evaluator run.
# ─────────────────────────────────────────────────────────────────────────────
def _selected_decisions(client: Any, run_id: str) -> List[Dict[str, Any]]:
    result = (
        client.table(DECISIONS_TABLE)
        .select(
            "id,run_id,fleet_id,fleet_epoch,shadow_micro_account_id,"
            "policy_registration_id,decision_event_id,candidate_suggestion_id,sizing"
        )
        .eq("run_id", run_id)
        .eq("disposition", "selected")
        .execute()
    )
    return _rows(result)


def _run_row(client: Any, run_id: str) -> Optional[Dict[str, Any]]:
    result = (
        client.table(RUNS_TABLE)
        .select(
            "run_id,fleet_id,fleet_epoch,shadow_micro_account_id,"
            "policy_registration_id,source_decision_id,user_id,as_of"
        )
        .eq("run_id", run_id)
        .limit(1)
        .execute()
    )
    rows = _rows(result)
    return rows[0] if rows else None


def _micro_portfolio(client: Any, shadow_micro_account_id: str) -> Optional[Dict[str, Any]]:
    result = (
        client.table("shadow_micro_accounts")
        .select("id,portfolio_id,policy_registration_id,state")
        .eq("id", shadow_micro_account_id)
        .limit(1)
        .execute()
    )
    rows = _rows(result)
    return rows[0] if rows else None


def _source_suggestion(client: Any, candidate_suggestion_id: str) -> Optional[Dict[str, Any]]:
    result = (
        client.table("trade_suggestions")
        .select("id,order_json,sizing_metadata")
        .eq("id", candidate_suggestion_id)
        .limit(1)
        .execute()
    )
    rows = _rows(result)
    return rows[0] if rows else None


def execute_fleet_run_candidates(
    client: Any,
    run_id: str,
    *,
    replay_factory: Optional[Callable[[Any, str], Any]] = None,
    rpc_caller: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """Internally fill every SELECTED candidate for one evaluator run.

    A no-op when there are no selected decisions (the invariant while the fleet
    is inactive). Never imports or invokes a broker. Each fill routes through the
    atomic open RPC, which re-checks fleet/micro active + shadow-only + selected
    identity + cash in-transaction.
    """
    counts = {
        "selected": 0,
        "filled_internal": 0,
        "execution_rejected": 0,
        "idempotent_replays": 0,
        "errors": 0,
    }
    error_details: List[Dict[str, Any]] = []

    try:
        run = _run_row(client, run_id)
        selected = _selected_decisions(client, run_id)
    except Exception as exc:
        return {
            "status": "read_failed",
            "counts": {**counts, "errors": 1},
            "error_details": [{"stage": "read", "error": str(exc)[:200]}],
        }
    if not run:
        return {"status": "run_missing", "counts": {**counts, "errors": 1}, "error_details": []}
    counts["selected"] = len(selected)
    if not selected:
        return {"status": "honest_empty", "counts": counts, "error_details": []}

    if replay_factory is None:
        from packages.quantum.services.replay.replay_truth_layer import ReplayTruthLayer

        replay_factory = ReplayTruthLayer.from_decision_id
    if rpc_caller is None:
        rpc_caller = lambda name, params: client.rpc(name, params).execute()

    replay = replay_factory(client, str(run.get("source_decision_id")))
    if replay is None:
        counts["execution_rejected"] = len(selected)
        counts["errors"] = 1
        return {
            "status": "source_decision_unavailable",
            "counts": counts,
            "error_details": [{"stage": "load_source_tape"}],
        }

    user_id = str(run.get("user_id"))
    as_of = run.get("as_of")

    for decision in selected:
        candidate_id = str(decision.get("candidate_suggestion_id") or decision.get("decision_event_id") or "")
        micro_id = str(decision.get("shadow_micro_account_id") or "")
        policy_id = str(decision.get("policy_registration_id") or "")
        sizing = decision.get("sizing") if isinstance(decision.get("sizing"), Mapping) else {}
        fleet_contracts = 0
        try:
            fleet_contracts = int(sizing.get("contracts") or 0)
        except (TypeError, ValueError):
            fleet_contracts = 0
        max_loss_total = _finite(sizing.get("max_loss_total"))

        reject = None
        try:
            micro = _micro_portfolio(client, micro_id)
            suggestion = _source_suggestion(client, candidate_id)
        except Exception as exc:
            counts["errors"] += 1
            error_details.append({"stage": "read_candidate", "candidate": candidate_id, "error": str(exc)[:160]})
            continue

        if not micro or not micro.get("portfolio_id"):
            reject = "micro_account_unbound"
        elif not suggestion or not isinstance(suggestion.get("order_json"), Mapping):
            reject = "source_suggestion_unavailable"
        elif fleet_contracts < 1 or max_loss_total is None or max_loss_total <= 0:
            reject = "sizing_unavailable"

        normalized = None
        entry_cost = None
        if reject is None:
            normalized = normalize_fleet_legs(suggestion["order_json"], fleet_contracts)
            if normalized is None:
                reject = "structure_malformed"
            else:
                entry_cost = compute_entry_net_cost(
                    replay, suggestion["order_json"], normalized, fleet_contracts
                )
                if entry_cost is None:
                    reject = "execution_quote_unavailable"

        if reject is not None:
            counts["execution_rejected"] += 1
            error_details.append({"stage": "execution_rejected", "candidate": candidate_id, "reason": reject})
            continue

        params = {
            "p_run_id": run_id,
            "p_shadow_micro_account_id": micro_id,
            "p_policy_registration_id": policy_id,
            "p_portfolio_id": micro["portfolio_id"],
            "p_user_id": user_id,
            "p_candidate_suggestion_id": candidate_id,
            "p_underlying": normalized["underlying"],
            "p_legs": [
                {k: leg[k] for k in ("option_type", "strike", "sign", "contracts")}
                for leg in normalized["legs"]
            ],
            "p_contracts": fleet_contracts,
            "p_entry_net_cost_total": entry_cost,
            "p_max_loss_total": max_loss_total,
            "p_expiry": normalized["expiry"],
            "p_source_known_at": as_of,
            "p_filled_at": as_of,
        }
        try:
            response = rpc_caller(OPEN_RPC, params)
            rows = getattr(response, "data", None)
            receipt = rows[0] if isinstance(rows, list) and rows else rows
            if not isinstance(receipt, Mapping):
                raise RuntimeError("open RPC returned no typed receipt")
            counts["filled_internal"] += 1
            if receipt.get("idempotent_replay"):
                counts["idempotent_replays"] += 1
        except Exception as exc:
            logger.exception("fleet internal open failed: %s", candidate_id)
            counts["execution_rejected"] += 1
            counts["errors"] += 1
            error_details.append(
                {
                    "stage": "internal_open",
                    "candidate": candidate_id,
                    "error_class": type(exc).__name__,
                    "error": str(exc)[:200],
                }
            )

    return {
        "status": "partial" if counts["errors"] else "succeeded",
        "counts": counts,
        "error_details": error_details[:20],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Expiry settlement.
# ─────────────────────────────────────────────────────────────────────────────
def _snapshot_spot(snapshot: Any) -> Optional[float]:
    if snapshot is None:
        return None
    quote = getattr(snapshot, "quote", None)
    if quote is None and isinstance(snapshot, Mapping):
        quote = snapshot.get("quote")
    if isinstance(quote, Mapping):
        values = (quote.get("last"), quote.get("mid"), quote.get("bid"))
    else:
        values = (getattr(quote, "last", None), getattr(quote, "mid", None), getattr(quote, "bid", None))
    for value in values:
        parsed = _finite(value)
        if parsed is not None and parsed >= 0:
            return parsed
    return None


def settle_expired_fleet_positions(
    client: Any,
    user_id: str,
    *,
    as_of: Optional[datetime] = None,
    snapshot_fetcher: Optional[Callable[[List[str]], Mapping[str, Any]]] = None,
    rpc_caller: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """Settle expired multi-leg fleet positions at the underlying terminal spot.

    Missing terminal spot NEVER fabricates a value: the position stays open and
    the next natural evaluation retries. No-op when nothing is expired (the
    invariant while the fleet is inactive).
    """
    as_of = as_of or datetime.now(timezone.utc)
    today = as_of.date().isoformat()
    counts = {"eligible": 0, "closed": 0, "deferred": 0, "idempotent_replays": 0, "errors": 0}

    try:
        result = (
            client.table(POSITIONS_TABLE)
            .select("position_id,user_id,underlying,expiry,status")
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

    underlyings = sorted({str(p.get("underlying")) for p in positions if p.get("underlying")})
    if snapshot_fetcher is None:
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer

        snapshot_fetcher = MarketDataTruthLayer().snapshot_many_v4
    try:
        snapshots = snapshot_fetcher(underlyings) or {}
    except Exception:
        snapshots = {}
        logger.exception("fleet expiry snapshot fetch failed")

    if rpc_caller is None:
        rpc_caller = lambda name, params: client.rpc(name, params).execute()

    errors: List[Dict[str, Any]] = []
    for position in positions:
        underlying = str(position.get("underlying") or "")
        spot = _snapshot_spot(snapshots.get(underlying))
        if spot is None:
            counts["deferred"] += 1  # never fabricate a terminal spot (H9)
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
            logger.exception("fleet expiry close failed: %s", position.get("position_id"))
            counts["errors"] += 1
            errors.append(
                {"stage": "expiry_close", "position_id": position.get("position_id"), "error": str(exc)[:200]}
            )

    return {
        "status": "partial" if counts["errors"] else "succeeded",
        "counts": counts,
        "error_details": errors[:20],
    }


def execute_fleet_selected_for_source(
    client: Any,
    source_decision_id: str,
    *,
    fleet_epoch: str,
    replay_factory: Optional[Callable[[Any, str], Any]] = None,
    rpc_caller: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """Open every SELECTED candidate across all evaluator runs of one source event.

    Handler convenience that leaves C1's ``run_fleet_policy_eval`` untouched: it
    queries the runs for the source event and drives the open lifecycle per run.
    A no-op when the fleet produced no runs (the invariant while inactive).
    """
    totals = {
        "runs": 0,
        "selected": 0,
        "filled_internal": 0,
        "execution_rejected": 0,
        "idempotent_replays": 0,
        "errors": 0,
    }
    try:
        result = (
            client.table(RUNS_TABLE)
            .select("run_id")
            .eq("source_decision_id", source_decision_id)
            .eq("fleet_epoch", fleet_epoch)
            .execute()
        )
        runs = _rows(result)
    except Exception as exc:
        return {"status": "run_read_failed", "counts": {**totals, "errors": 1},
                "error_details": [{"stage": "run_read", "error": str(exc)[:200]}]}

    details: List[Dict[str, Any]] = []
    for run in runs:
        run_id = str(run.get("run_id"))
        outcome = execute_fleet_run_candidates(
            client, run_id, replay_factory=replay_factory, rpc_caller=rpc_caller
        )
        totals["runs"] += 1
        for key in ("selected", "filled_internal", "execution_rejected", "idempotent_replays", "errors"):
            totals[key] += int((outcome.get("counts") or {}).get(key) or 0)
        details.extend(outcome.get("error_details") or [])

    return {
        "status": "partial" if totals["errors"] else "succeeded",
        "counts": totals,
        "error_details": details[:20],
    }
