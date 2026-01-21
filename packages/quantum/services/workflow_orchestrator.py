from supabase import Client
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, TYPE_CHECKING
import json
import asyncio
import os
import sys

if TYPE_CHECKING:
    from packages.quantum.services.market_data_truth_layer import TruthSnapshotV4

from .cash_service import CashService
from .sizing_engine import calculate_sizing
from .journal_service import JournalService
from .options_utils import group_spread_positions, format_occ_symbol_readable, compute_legs_fingerprint
from .exit_stats_service import ExitStatsService
from .market_data_truth_layer import MarketDataTruthLayer
from .analytics_service import AnalyticsService
from packages.quantum.analytics.strategy_policy import StrategyPolicy
from packages.quantum.services.risk_budget_engine import RiskBudgetEngine
from packages.quantum.services.analytics.small_account_compounder import SmallAccountCompounder, CapitalTier, SizingConfig
from packages.quantum.analytics.capital_scan_policy import CapitalScanPolicy
from packages.quantum.agents.agents.sizing_agent import SizingAgent
from packages.quantum.agents.agents.exit_plan_agent import ExitPlanAgent

from packages.quantum.services.decision_lineage_builder import DecisionLineageBuilder

# Importing existing logic
from packages.quantum.options_scanner import scan_for_opportunities
from packages.quantum.analytics.regime_engine_v3 import RegimeEngineV3, RegimeState, GlobalRegimeSnapshot
from packages.quantum.models import Holding
from packages.quantum.ev_calculator import calculate_exit_metrics
from packages.quantum.analytics.loss_minimizer import LossMinimizer
from packages.quantum.analytics.conviction_service import ConvictionService
from packages.quantum.services.iv_repository import IVRepository
from packages.quantum.services.iv_point_service import IVPointService
from packages.quantum.nested_logging import log_decision, log_inference

# v3 Observability
from packages.quantum.observability.telemetry import TradeContext, compute_features_hash, emit_trade_event
import uuid

# v4 Observability: Lineage Signing & Audit Logging
from packages.quantum.observability.lineage import LineageSigner, get_code_sha
from packages.quantum.observability.audit_log_service import AuditLogService, build_attribution_from_lineage

# Constants for table names
TRADE_SUGGESTIONS_TABLE = "trade_suggestions"
WEEKLY_REPORTS_TABLE = "weekly_trade_reports"
SUGGESTION_LOGS_TABLE = "suggestion_logs"


# =============================================================================
# Replay Feature Store Integration
# =============================================================================
def _get_decision_context():
    """Lazy import to get current decision context (avoids circular imports)."""
    try:
        from packages.quantum.services.replay.decision_context import (
            get_current_decision_context,
            is_replay_enabled,
        )
        if not is_replay_enabled():
            return None
        return get_current_decision_context()
    except ImportError:
        return None


def _record_regime_features(global_snap: "GlobalRegimeSnapshot") -> None:
    """Record global regime features to decision context if active."""
    ctx = _get_decision_context()
    if ctx is None:
        return

    try:
        # Extract features from global snapshot
        features = {
            "state": global_snap.state.value if hasattr(global_snap.state, 'value') else str(global_snap.state),
            "risk_score": global_snap.risk_score,
            "risk_scaler": global_snap.risk_scaler,
            "trend_score": global_snap.trend_score,
            "vol_score": global_snap.vol_score,
            "corr_score": global_snap.corr_score,
            "breadth_score": global_snap.breadth_score,
            "liquidity_score": getattr(global_snap, 'liquidity_score', None),
            "as_of_ts": str(global_snap.as_of_ts),
        }
        # Include raw features dict if available
        if hasattr(global_snap, 'features') and global_snap.features:
            features["raw_features"] = global_snap.features

        ctx.record_feature("__global__", "regime_features", features)
    except Exception:
        pass  # Non-critical, don't block on failure


def _record_symbol_features(symbol: str, sym_snap, global_snap: "GlobalRegimeSnapshot") -> None:
    """Record symbol-level features to decision context if active."""
    ctx = _get_decision_context()
    if ctx is None:
        return

    try:
        features = {
            "symbol": symbol,
            "state": sym_snap.state.value if hasattr(sym_snap.state, 'value') else str(sym_snap.state),
            "score": sym_snap.score,
            "iv_rank": sym_snap.iv_rank,
            "atm_iv_30d": getattr(sym_snap, 'atm_iv_30d', None),
            "rv_20d": getattr(sym_snap, 'rv_20d', None),
            "iv_rv_spread": getattr(sym_snap, 'iv_rv_spread', None),
            "skew_25d": getattr(sym_snap, 'skew_25d', None),
            "term_slope": getattr(sym_snap, 'term_slope', None),
            "as_of_ts": str(sym_snap.as_of_ts),
            "global_state": global_snap.state.value if hasattr(global_snap.state, 'value') else str(global_snap.state),
        }
        # Include raw features if available
        if hasattr(sym_snap, 'features') and sym_snap.features:
            features["raw_features"] = sym_snap.features

        ctx.record_feature(symbol, "symbol_features", features)
    except Exception:
        pass  # Non-critical


def _record_surface_snapshot(symbol: str, sym_snap) -> None:
    """
    Record surface snapshot to decision context if active.

    v1.1: Captures derived surface data from sym_snap for deterministic replay.
    Stores as an input (market data snapshot) rather than a computed feature.
    """
    ctx = _get_decision_context()
    if ctx is None:
        return

    try:
        import time

        # Build surface payload from sym_snap fields (no heavy computation)
        surface_payload = {
            "symbol": symbol,
            "atm_iv_30d": getattr(sym_snap, 'atm_iv_30d', None),
            "skew_25d": getattr(sym_snap, 'skew_25d', None),
            "term_slope": getattr(sym_snap, 'term_slope', None),
            "rv_20d": getattr(sym_snap, 'rv_20d', None),
            "iv_rv_spread": getattr(sym_snap, 'iv_rv_spread', None),
            "iv_rank": getattr(sym_snap, 'iv_rank', None),
            "as_of_ts": str(sym_snap.as_of_ts) if hasattr(sym_snap, 'as_of_ts') else None,
        }

        metadata = {
            "derived_from": "regime_engine_v3",
            "received_ts": int(time.time() * 1000),
        }

        ctx.record_input(
            key=f"{symbol}:surface:v1",
            snapshot_type="surface",
            payload=surface_payload,
            metadata=metadata,
        )
    except Exception:
        pass  # Non-critical

# 1. Add MIDDAY_TEST_MODE flag
MIDDAY_TEST_MODE = os.getenv("MIDDAY_TEST_MODE", "false").lower() == "true"
COMPOUNDING_MODE = os.getenv("COMPOUNDING_MODE", "false").lower() == "true"
APP_VERSION = os.getenv("APP_VERSION", "v2-dev")

# Exit Mode Router Guardrails
# Threshold for treating a position as a "deep loser" (default: 50% loss)
LOSS_EXIT_THRESHOLD = float(os.getenv("LOSS_EXIT_THRESHOLD", "0.5"))
# Maximum multiplier for take_profit_limit relative to current price
MAX_TAKE_PROFIT_MULTIPLIER = float(os.getenv("MAX_TAKE_PROFIT_MULTIPLIER", "3.0"))
# Optional absolute cap on take_profit_limit (0 = disabled)
MAX_TAKE_PROFIT_ABS = float(os.getenv("MAX_TAKE_PROFIT_ABS", "0"))


def clamp_risk_budget(per_trade_budget: float, remaining: float) -> float:
    return max(0.0, min(float(per_trade_budget or 0.0), float(remaining or 0.0)))


# =============================================================================
# Wave 1.3.2: In-memory dedupe guard for integrity incidents
# =============================================================================
# This set tracks which integrity incidents have been emitted within this process.
# It prevents redundant service instantiations and duplicate prints within a single run.
# DB-level idempotency (via event_key) still protects across processes/runs.
_INTEGRITY_INCIDENT_EMITTED: set = set()


def _clear_integrity_incident_cache() -> None:
    """
    Wave 1.3.2: Clear the in-memory integrity incident cache.
    Useful for testing or when you want to force re-emission.
    """
    global _INTEGRITY_INCIDENT_EMITTED
    _INTEGRITY_INCIDENT_EMITTED = set()


# =============================================================================
# Wave 1.3.1: Deterministic trace ID helper for forensic continuity
# =============================================================================

def deterministic_supersede_trace_id(
    user_id: str,
    cycle_date: str,
    window: str,
    ticker: str,
    legs_fingerprint: str,
    old_strategy: str,
    new_strategy: str
) -> str:
    """
    Wave 1.3.1: Generate a deterministic trace_id for supersede events.

    This ensures that supersede events always have the same trace_id for the
    same logical action, even across retries. This is critical for forensic
    continuity - random UUIDs fragment the trace chain.

    Uses uuid5 with NAMESPACE_URL for deterministic, reproducible UUIDs.

    Args:
        user_id: User UUID
        cycle_date: Cycle date (YYYY-MM-DD)
        window: Window (e.g., "morning_limit")
        ticker: Underlying ticker
        legs_fingerprint: Position fingerprint (or "nofp" if missing)
        old_strategy: Strategy being superseded
        new_strategy: New strategy replacing the old one

    Returns:
        Deterministic UUID string
    """
    # Create stable key from all context fields
    fp = legs_fingerprint or "nofp"
    key = f"supersede:{user_id}:{cycle_date}:{window}:{ticker}:{fp}:{old_strategy}:{new_strategy}"

    # Generate deterministic UUID using uuid5
    deterministic_uuid = uuid.uuid5(uuid.NAMESPACE_URL, key)
    return str(deterministic_uuid)


def deterministic_integrity_trace_id(
    user_id: str,
    cycle_date: str,
    window: str,
    ticker: str,
    strategy: str
) -> str:
    """
    Wave 1.3.1: Generate a deterministic trace_id for integrity incidents.

    Used when logging missing fingerprint incidents to ensure idempotency
    and forensic traceability.

    Args:
        user_id: User UUID
        cycle_date: Cycle date (YYYY-MM-DD)
        window: Window (e.g., "morning_limit")
        ticker: Underlying ticker
        strategy: Strategy name

    Returns:
        Deterministic UUID string
    """
    key = f"integrity_incident:missing_fingerprint:{user_id}:{cycle_date}:{window}:{ticker}:{strategy}"
    deterministic_uuid = uuid.uuid5(uuid.NAMESPACE_URL, key)
    return str(deterministic_uuid)


def _emit_integrity_incident(
    supabase: Client,
    user_id: str,
    cycle_date: str,
    window: str,
    ticker: str,
    strategy: str
) -> str:
    """
    Wave 1.3.1: Emit audit and analytics events for missing fingerprint incident.

    This surfaces the issue in forensic logs so upstream fingerprint generation
    can be fixed. Uses idempotency to avoid spamming on retries.

    Wave 1.3.2: Added in-memory dedupe guard to prevent redundant emissions
    within a single process run. Returns trace_id for linking.

    Args:
        supabase: Supabase client
        user_id: User UUID
        cycle_date: Cycle date (YYYY-MM-DD)
        window: Window (e.g., "morning_limit")
        ticker: Underlying ticker
        strategy: Strategy name

    Returns:
        The deterministic trace_id for this incident (for linking purposes)
    """
    # Wave 1.3.2: Compute deterministic trace_id first (needed for return value)
    trace_id = deterministic_integrity_trace_id(
        user_id=user_id,
        cycle_date=cycle_date,
        window=window,
        ticker=ticker,
        strategy=strategy
    )

    if not supabase:
        return trace_id

    # Wave 1.3.2: In-memory dedupe guard
    # Prevents redundant service instantiations and prints within a single run.
    # DB idempotency still protects across processes/runs.
    dedupe_key = f"{user_id}:{cycle_date}:{window}:{ticker}:{strategy}"
    if dedupe_key in _INTEGRITY_INCIDENT_EMITTED:
        return trace_id  # Already emitted in this process

    _INTEGRITY_INCIDENT_EMITTED.add(dedupe_key)

    try:
        # Build incident payload (used for both audit and analytics)
        incident_payload = {
            "type": "missing_legs_fingerprint",
            "user_id": user_id,
            "window": window,
            "cycle_date": cycle_date,
            "ticker": ticker,
            "strategy": strategy,
            "action": "fallback_query_latest_by_created_at"
        }

        # Emit audit event
        try:
            audit_service = AuditLogService(supabase)
            audit_service.log_audit_event(
                user_id=user_id,
                trace_id=trace_id,
                suggestion_id=None,  # Not known yet
                event_name="integrity_incident",
                payload=incident_payload,
                strategy=strategy
            )
        except Exception as audit_err:
            print(f"[Wave1.3.2] Failed to write integrity incident audit event: {audit_err}")

        # Emit analytics event with idempotency_payload for deduplication
        try:
            analytics_service = AnalyticsService(supabase)
            analytics_service.log_event(
                user_id=user_id,
                event_name="integrity_incident",
                category="system",
                properties=incident_payload,
                trace_id=trace_id,
                idempotency_payload=incident_payload  # Enables trace-scoped idempotency
            )
        except Exception as analytics_err:
            print(f"[Wave1.3.2] Failed to write integrity incident analytics event: {analytics_err}")

        print(f"[Wave1.3.2] Integrity incident logged: missing_legs_fingerprint for {ticker}/{strategy}")

    except Exception as e:
        # Swallow errors to not disrupt main flow
        print(f"[Wave1.3.2] Error emitting integrity incident: {e}")

    return trace_id


def _emit_integrity_incident_linked(
    supabase: Client,
    user_id: str,
    suggestion_id: str,
    trace_id: str,
    cycle_date: str,
    window: str,
    ticker: str,
    strategy: str
) -> None:
    """
    Wave 1.3.2: Emit a linked integrity incident event after fallback query finds a row.

    This creates a suggestion-scoped event that links the trace-scoped integrity_incident
    to a concrete suggestion_id, improving forensic joins.

    The event is naturally idempotent:
    - Audit: uses suggestion_id:event_name for deduplication
    - Analytics: includes suggestion_id in properties for suggestion-scoped dedupe

    Args:
        supabase: Supabase client
        user_id: User UUID
        suggestion_id: The found suggestion's ID
        trace_id: The deterministic trace_id from the original incident
        cycle_date: Cycle date (YYYY-MM-DD)
        window: Window (e.g., "morning_limit")
        ticker: Underlying ticker
        strategy: Strategy name
    """
    if not supabase or not suggestion_id:
        return

    try:
        # Build linked incident payload
        linked_payload = {
            "type": "missing_legs_fingerprint_linked",
            "linked_suggestion_id": suggestion_id,
            "user_id": user_id,
            "window": window,
            "cycle_date": cycle_date,
            "ticker": ticker,
            "strategy": strategy,
            "action": "linked_to_existing_suggestion"
        }

        # Emit audit event (suggestion-scoped idempotency via suggestion_id:event_name)
        try:
            audit_service = AuditLogService(supabase)
            audit_service.log_audit_event(
                user_id=user_id,
                trace_id=trace_id,
                suggestion_id=suggestion_id,  # Now linked!
                event_name="integrity_incident_linked",
                payload=linked_payload,
                strategy=strategy
            )
        except Exception as audit_err:
            print(f"[Wave1.3.2] Failed to write linked integrity incident audit event: {audit_err}")

        # Emit analytics event (suggestion-scoped via properties.suggestion_id)
        try:
            analytics_service = AnalyticsService(supabase)
            analytics_service.log_event(
                user_id=user_id,
                event_name="integrity_incident_linked",
                category="system",
                properties={
                    **linked_payload,
                    "suggestion_id": suggestion_id  # Enables suggestion-scoped dedupe
                },
                trace_id=trace_id
                # No idempotency_payload needed - suggestion_id provides suggestion-scoped key
            )
        except Exception as analytics_err:
            print(f"[Wave1.3.2] Failed to write linked integrity incident analytics event: {analytics_err}")

    except Exception as e:
        # Swallow errors to not disrupt main flow
        print(f"[Wave1.3.2] Error emitting linked integrity incident: {e}")


# =============================================================================
# Wave 1.2: Insert-idempotent suggestion helper
# Wave 1.3: Fixed NULL legs_fingerprint handling
# Wave 1.3.1: Added integrity incident telemetry for missing fingerprint
# Wave 1.3.2: Added in-memory dedupe and linked incident event
# =============================================================================

def insert_or_get_suggestion(
    supabase: Client,
    suggestion: dict,
    unique_fields: tuple
) -> tuple:
    """
    Wave 1.2: Insert a suggestion or return existing row if already exists.

    This prevents updates to immutable integrity fields (lineage_hash, lineage_sig,
    decision_lineage, trace_id, code_sha, data_hash) which are protected by
    Wave 1.1 database trigger.

    Wave 1.3: Fixed NULL legs_fingerprint handling. When fingerprint is None/falsy,
    we omit the fingerprint filter and use order by created_at desc to get the
    latest matching row. This avoids incorrect SQL NULL matching.

    Args:
        supabase: Supabase client
        suggestion: Cleaned suggestion dict (no _v4_* fields)
        unique_fields: Tuple of (user_id, window, cycle_date, ticker, strategy, legs_fingerprint)

    Returns:
        Tuple of (suggestion_id, trace_id, is_new)
        - suggestion_id: UUID of the inserted or existing suggestion
        - trace_id: trace_id of the inserted or existing suggestion
        - is_new: True if newly inserted, False if existing
    """
    user_id, window, cycle_date, ticker, strategy, legs_fingerprint = unique_fields

    try:
        # Attempt insert
        result = supabase.table(TRADE_SUGGESTIONS_TABLE).insert(suggestion).execute()
        if result.data:
            row = result.data[0]
            return (row.get("id"), row.get("trace_id"), True)
        return (None, None, False)

    except Exception as e:
        error_str = str(e).lower()
        # Handle unique violation - fetch existing row
        if "unique" in error_str or "duplicate" in error_str or "23505" in error_str:
            try:
                # Query for existing suggestion using unique constraint fields
                query = supabase.table(TRADE_SUGGESTIONS_TABLE) \
                    .select("id, trace_id, lineage_hash, lineage_sig, status") \
                    .eq("user_id", user_id) \
                    .eq("window", window) \
                    .eq("cycle_date", cycle_date) \
                    .eq("ticker", ticker) \
                    .eq("strategy", strategy)

                # Wave 1.3: Handle None/falsy fingerprint safely
                # Don't use .is_("legs_fingerprint", "null") as it doesn't match SQL NULL correctly.
                # Instead, omit the filter and order by created_at desc to get the latest row.
                incident_trace_id = None  # Wave 1.3.2: Track for linking
                if legs_fingerprint:
                    query = query.eq("legs_fingerprint", legs_fingerprint)
                else:
                    # Without fingerprint, we can't uniquely identify; get latest by created_at
                    query = query.order("created_at", desc=True)

                    # Wave 1.3.1/1.3.2: Emit integrity incident telemetry for missing fingerprint
                    # Returns trace_id for linking after we find the row
                    incident_trace_id = _emit_integrity_incident(
                        supabase=supabase,
                        user_id=user_id,
                        cycle_date=cycle_date,
                        window=window,
                        ticker=ticker,
                        strategy=strategy
                    )

                existing = query.limit(1).execute()

                if existing.data:
                    row = existing.data[0]
                    found_id = row.get("id")
                    print(f"[Wave1.3] Suggestion already exists for {ticker}/{strategy} (id={found_id})")

                    # Wave 1.3.2: Emit linked incident if fingerprint was missing
                    if incident_trace_id and found_id:
                        _emit_integrity_incident_linked(
                            supabase=supabase,
                            user_id=user_id,
                            suggestion_id=found_id,
                            trace_id=incident_trace_id,
                            cycle_date=cycle_date,
                            window=window,
                            ticker=ticker,
                            strategy=strategy
                        )

                    return (found_id, row.get("trace_id"), False)

            except Exception as fetch_err:
                print(f"[Wave1.3] Error fetching existing suggestion: {fetch_err}")

            return (None, None, False)

        # Re-raise non-unique errors
        raise e


# =============================================================================
# Close Suggestion Supersede Helper
# =============================================================================

# Close strategies that can supersede each other (same position, different exit modes)
CLOSE_STRATEGIES = ("take_profit_limit", "salvage_exit", "lottery_trap")


def supersede_prior_close_suggestions(
    supabase: Client,
    *,
    user_id: str,
    cycle_date: str,
    window: str,
    ticker: str,
    legs_fingerprint: str,
    new_strategy: str,
    reason: str = "superseded_by_new_exit_mode"
) -> int:
    """
    Supersede prior pending/staged close suggestions for the same position.

    When the exit router changes strategy (e.g., take_profit_limit → salvage_exit),
    the old suggestion should not remain visible. This function marks prior close
    suggestions as 'superseded' so the UI only shows the best current exit suggestion.

    Wave 1.3: Now emits audit and analytics events for each superseded suggestion
    to provide forensic visibility in traces.

    Wave 1.3.1: Uses deterministic trace_id fallback instead of random UUIDs when
    the original suggestion lacks a trace_id. This ensures forensic continuity -
    the same supersede action always produces the same trace_id across retries.

    Args:
        supabase: Supabase admin client
        user_id: User UUID
        cycle_date: Cycle date (YYYY-MM-DD)
        window: Window (e.g., "morning_limit")
        ticker: Underlying ticker
        legs_fingerprint: Fingerprint identifying the position structure
        new_strategy: The new strategy being inserted (won't be superseded)
        reason: Reason string stored in dismissed_reason

    Returns:
        Number of suggestions superseded

    Notes:
        - Only supersedes status in ('pending', 'queued', 'staged')
        - Never touches 'executed', 'filled', 'cancelled' suggestions
        - Only considers close strategies: take_profit_limit, salvage_exit, lottery_trap
    """
    if not supabase or not legs_fingerprint:
        return 0

    try:
        # Find prior close suggestions for the same position
        # Strategy must be in CLOSE_STRATEGIES but NOT the new strategy
        other_strategies = [s for s in CLOSE_STRATEGIES if s != new_strategy]

        if not other_strategies:
            return 0

        # Wave 1.3: Fetch trace_id as well for audit/analytics events
        query = supabase.table(TRADE_SUGGESTIONS_TABLE) \
            .select("id, strategy, status, trace_id") \
            .eq("user_id", user_id) \
            .eq("cycle_date", cycle_date) \
            .eq("window", window) \
            .eq("ticker", ticker) \
            .eq("legs_fingerprint", legs_fingerprint) \
            .in_("strategy", other_strategies) \
            .in_("status", ["pending", "queued", "staged"])

        result = query.execute()

        if not result.data:
            return 0

        # Wave 1.3: Initialize services for event emission
        audit_service = AuditLogService(supabase)
        analytics_service = AnalyticsService(supabase)

        superseded_count = 0
        for row in result.data:
            suggestion_id = row.get("id")
            old_strategy = row.get("strategy")
            trace_id = row.get("trace_id")

            # Wave 1.3.1: Use deterministic trace_id fallback instead of random UUID
            # This ensures forensic continuity - same supersede action always gets same trace_id
            effective_trace_id = trace_id or deterministic_supersede_trace_id(
                user_id=user_id,
                cycle_date=cycle_date,
                window=window,
                ticker=ticker,
                legs_fingerprint=legs_fingerprint,
                old_strategy=old_strategy,
                new_strategy=new_strategy
            )

            try:
                # Mark as superseded
                supabase.table(TRADE_SUGGESTIONS_TABLE).update({
                    "status": "superseded",
                    "dismissed_reason": reason
                }).eq("id", suggestion_id).execute()

                print(f"[Supersede] Marked {old_strategy} suggestion {suggestion_id} as superseded "
                      f"(replaced by {new_strategy})")
                superseded_count += 1

                # Wave 1.3: Emit audit event for forensics
                supersede_payload = {
                    "superseded_suggestion_id": suggestion_id,
                    "old_strategy": old_strategy,
                    "new_strategy": new_strategy,
                    "reason": reason,
                    "cycle_date": cycle_date,
                    "window": window,
                    "ticker": ticker,
                    "legs_fingerprint": legs_fingerprint
                }

                try:
                    audit_service.log_audit_event(
                        user_id=user_id,
                        trace_id=effective_trace_id,  # Wave 1.3.1: deterministic
                        suggestion_id=suggestion_id,
                        event_name="suggestion_superseded",
                        payload=supersede_payload,
                        strategy=old_strategy
                    )
                except Exception as audit_err:
                    print(f"[Supersede] Failed to write audit event: {audit_err}")

                # Wave 1.3: Emit analytics event with idempotency_payload
                try:
                    analytics_service.log_event(
                        user_id=user_id,
                        event_name="suggestion_superseded",
                        category="system",
                        properties={
                            "suggestion_id": suggestion_id,
                            "old_strategy": old_strategy,
                            "new_strategy": new_strategy,
                            "reason": reason,
                            "ticker": ticker,
                            "window": window,
                            "cycle_date": cycle_date
                        },
                        trace_id=effective_trace_id,  # Wave 1.3.1: deterministic
                        idempotency_payload=supersede_payload  # Wave 1.3: enables trace-scoped idempotency
                    )
                except Exception as analytics_err:
                    print(f"[Supersede] Failed to write analytics event: {analytics_err}")

            except Exception as update_err:
                print(f"[Supersede] Failed to update suggestion {suggestion_id}: {update_err}")

        return superseded_count

    except Exception as e:
        print(f"[Supersede] Error querying prior suggestions: {e}")
        return 0


def compute_exit_mode(
    unit_price: float,
    unit_cost: float,
    market_data: dict = None
) -> dict:
    """
    Exit Mode Router: Determines the appropriate exit strategy for a position.

    Returns dict with:
        - mode: "normal" | "salvage" | "lottery_trap" | "not_executable"
        - limit_price: float or None
        - rationale_prefix: str (to prepend to rationale)
        - warning: str or None
        - clamp_reason: str or None (if limit was clamped)
    """
    result = {
        "mode": "normal",
        "limit_price": None,
        "rationale_prefix": "",
        "warning": None,
        "clamp_reason": None
    }

    # Check for missing/stale quotes
    if market_data is None:
        # Allow normal flow but flag as potentially stale
        pass

    # Check if this is a deep loser (e.g., down 50%+)
    if unit_cost > 0 and unit_price <= unit_cost * LOSS_EXIT_THRESHOLD:
        # Deep loser - use LossMinimizer
        loss_pct = ((unit_cost - unit_price) / unit_cost) * 100 if unit_cost > 0 else 0

        # Build position dict for LossMinimizer
        position_for_analysis = {
            "current_price": unit_price,
            "quantity": 1,  # Per-unit analysis
            "cost_basis": unit_cost
        }

        # Get bid/ask from market_data if available
        analysis_market_data = None
        if market_data:
            bid = market_data.get("bid", unit_price)
            ask = market_data.get("ask", unit_price)
            if bid is not None and ask is not None:
                analysis_market_data = {"bid": bid, "ask": ask}

        # Call LossMinimizer
        analysis = LossMinimizer.analyze_position(
            position=position_for_analysis,
            market_data=analysis_market_data
        )

        result["limit_price"] = analysis.limit_price
        result["warning"] = analysis.warning

        # Determine mode from scenario
        if "Salvage" in analysis.scenario:
            result["mode"] = "salvage"
            result["rationale_prefix"] = f"SALVAGE EXIT ({loss_pct:.0f}% loss): "
        else:
            result["mode"] = "lottery_trap"
            result["rationale_prefix"] = f"LOTTERY TRAP ({loss_pct:.0f}% loss): "

    return result


def clamp_take_profit_limit(
    limit_price: float,
    unit_price: float,
    mode: str = "normal"
) -> tuple:
    """
    Clamps take_profit_limit to prevent absurd targets.

    Returns (clamped_price, clamp_reason or None)
    """
    if limit_price is None or limit_price <= 0:
        return limit_price, None

    # Don't clamp salvage/lottery modes - they already have reasonable limits
    if mode in ("salvage", "lottery_trap"):
        return limit_price, None

    clamp_reason = None
    original_limit = limit_price

    # Apply multiplier cap
    max_by_multiplier = unit_price * MAX_TAKE_PROFIT_MULTIPLIER
    if limit_price > max_by_multiplier and max_by_multiplier > 0:
        limit_price = max_by_multiplier
        clamp_reason = f"Clamped from ${original_limit:.2f} (>{MAX_TAKE_PROFIT_MULTIPLIER}x current)"

    # Apply absolute cap if configured
    if MAX_TAKE_PROFIT_ABS > 0 and limit_price > MAX_TAKE_PROFIT_ABS:
        limit_price = MAX_TAKE_PROFIT_ABS
        clamp_reason = f"Clamped from ${original_limit:.2f} (>abs cap ${MAX_TAKE_PROFIT_ABS:.2f})"

    return round(limit_price, 2), clamp_reason


def normalize_win_rate(value) -> tuple[float, float]:
    """
    Returns (ratio_0_to_1, pct_0_to_100).
    Accepts either:
      - ratio in [0,1]  (ex: 0.73)
      - percent in [0,100] (ex: 73.0)
    Clamps ratio to [0,1] defensively.
    """
    if value is None:
        return 0.0, 0.0
    try:
        v = float(value)
    except Exception:
        return 0.0, 0.0
    ratio = (v / 100.0) if v > 1.0 else v
    if ratio < 0.0:
        ratio = 0.0
    if ratio > 1.0:
        ratio = 1.0
    return ratio, ratio * 100.0

def build_midday_order_json(
    cand: dict,
    contracts: int,
    leg_snapshots_v4: Optional[Dict[str, "TruthSnapshotV4"]] = None
) -> dict:
    """
    Builds order JSON for midday suggestions.

    Args:
        cand: Candidate dict with legs, symbol, strategy, suggested_entry
        contracts: Number of contracts
        leg_snapshots_v4: Optional V4 snapshots for quality gating

    Returns:
        Order JSON dict. If quality gates fail, returns with status="NOT_EXECUTABLE".
    """
    legs = cand.get("legs") or []
    leg_orders = []

    for leg in legs:
        sym = leg.get("symbol")
        side = leg.get("side")  # "buy"/"sell"
        if sym and side and contracts > 0:
            leg_orders.append({
                "symbol": sym,
                "side": side,
                "quantity": contracts,
            })

    # Default order type
    order_type = "multi_leg" if len(leg_orders) > 1 else "single_leg"
    limit_price = float(cand.get("suggested_entry") or 0.0)

    # PR3.1: Short-circuit if candidate is already blocked by upstream quality gate
    if cand.get("blocked_reason") == "marketdata_quality_gate":
        blocked_detail = cand.get("blocked_detail", "marketdata_quality_issues")
        return {
            "order_type": order_type,
            "status": "NOT_EXECUTABLE",
            "reason": f"Blocked by marketdata quality gate: {blocked_detail}",
            "contracts": contracts,
            "limit_price": None,
            "legs": leg_orders,
            "underlying": cand.get("symbol") or cand.get("ticker"),
            "strategy": cand.get("strategy") or cand.get("strategy_key") or cand.get("type"),
        }

    # 3. Limit Order Constraint Logic
    if cand.get("order_type_force_limit"):
        order_type = "limit"

        # V4 Quality Gate: Check snapshots if provided
        if leg_snapshots_v4:
            leg_symbols = [leg.get("symbol") for leg in legs if leg.get("symbol")]
            from packages.quantum.services.market_data_truth_layer import (
                check_snapshots_executable, MARKETDATA_MIN_QUALITY_SCORE
            )
            is_exec, quality_issues = check_snapshots_executable(
                leg_snapshots_v4, leg_symbols, MARKETDATA_MIN_QUALITY_SCORE
            )
            if not is_exec:
                return {
                    "order_type": "limit",
                    "status": "NOT_EXECUTABLE",
                    "reason": f"Quote quality gate failed: {'; '.join(quality_issues)}",
                    "contracts": contracts,
                    "limit_price": None,
                    "legs": leg_orders,
                    "underlying": cand.get("symbol"),
                    "strategy": cand.get("strategy") or cand.get("strategy_key"),
                }

        # Calculate deterministic limit price from mid (if quotes available)
        # Note: 'suggested_entry' from scanner is typically abs(total_cost), which is mid-based.
        # But to be safe and explicit as requested, we re-verify or rely on it.
        # If suggested_entry is 0 or quotes are missing, we should flag it.

        # Check for valid quotes on all legs (backward compat check)
        quotes_valid = True
        for leg in legs:
            # We check if mid was used/available in scanner
            # Scanner sets 'mid' key in legs if bid/ask were present.
            if leg.get("mid") is None:
                quotes_valid = False
                break

        if not quotes_valid:
            # Mark as NOT_EXECUTABLE if quotes are missing
            # We set a status in order_json or handle upstream?
            # The prompt says: "mark suggestion as NOT_EXECUTABLE (or set limit_price=None + reason)"
            # Since this function returns order_json, we'll embed the error state.
            return {
                "order_type": "limit",
                "status": "NOT_EXECUTABLE",
                "reason": "Missing quotes for limit order calculation",
                "contracts": contracts,
                "limit_price": None,
                "legs": leg_orders,
                "underlying": cand.get("symbol"),
                "strategy": cand.get("strategy") or cand.get("strategy_key"),
            }

    order_json = {
        "order_type": order_type,
        "contracts": contracts,
        "limit_price": limit_price,
        "legs": leg_orders,
        "underlying": cand.get("symbol"),
        "strategy": cand.get("strategy") or cand.get("strategy_key"),
    }
    return order_json


def postprocess_midday_sizing(sizing: dict, max_loss_per_contract: float) -> dict:
    """
    Ensures sizing metadata fields are correctly populated and distinct.
    Specifically prevents max_loss_total from being overwritten by capital_required.
    """
    # Fix: Do NOT overwrite max_loss_total with capital_required.
    # Especially important for credit spreads where max_loss > capital/margin.
    if "max_loss_total" not in sizing:
        sizing["max_loss_total"] = sizing.get("contracts", 0) * max_loss_per_contract

    sizing["capital_required_total"] = sizing.get("capital_required", 0.0)
    return sizing


async def run_morning_cycle(supabase: Client, user_id: str):
    """
    1. Read latest portfolio snapshot + positions.
    2. Group into spreads using group_spread_positions.
    3. Generate EV-based profit-taking suggestions (and skip stop-loss).
    4. Insert records into trade_suggestions table with window='morning_limit'.
    """
    print(f"Running morning cycle for user {user_id}")
    analytics_service = AnalyticsService(supabase)

    # 1. Fetch current positions
    try:
        res = supabase.table("positions").select("*").eq("user_id", user_id).execute()
        positions = res.data or []
    except Exception as e:
        print(f"Error fetching positions for morning cycle: {e}")
        return

    # 2. Group into Spreads
    spreads = group_spread_positions(positions)

    # Initialize Market Data Truth Layer
    truth_layer = MarketDataTruthLayer()

    # V3: Compute Global Regime Snapshot ONCE
    iv_repo = IVRepository(supabase)
    iv_point_service = IVPointService(supabase)

    regime_engine = RegimeEngineV3(
        supabase_client=supabase,
        market_data=truth_layer,
        iv_repository=iv_repo,
        iv_point_service=iv_point_service,
    )

    global_snap = regime_engine.compute_global_snapshot(datetime.now())

    # Record regime features to decision context (for replay feature store)
    _record_regime_features(global_snap)

    # Record rates/divs for deterministic replay (Patch 2.1)
    truth_layer.rates_divs("SPY", as_of=datetime.now(timezone.utc))

    # Try to persist global snapshot
    try:
        supabase.table("regime_snapshots").insert(global_snap.to_dict()).execute()
    except Exception:
        pass

    # === RISK BUDGET CHECK ===
    risk_engine = RiskBudgetEngine(supabase)
    # Get deployable capital approx for equity calc inside engine
    # We can fetch real cash or assume 0 if morning cycle doesn't fetch it,
    # but accurate equity is needed. Let's fetch cash quickly.
    try:
        cash_service = CashService(supabase)
        deployable_capital = await cash_service.get_deployable_capital(user_id)
    except:
        deployable_capital = 0.0

    budgets = risk_engine.compute(user_id, deployable_capital, global_snap.state.value, positions)

    # Updated to access keys from Pydantic model
    remaining_global = budgets.global_allocation.remaining
    max_alloc_global = budgets.global_allocation.max_limit
    usage_global = budgets.global_allocation.used

    is_over_budget = remaining_global <= 0
    budget_usage_pct = 0.0
    if max_alloc_global > 0:
        budget_usage_pct = (usage_global / max_alloc_global) * 100

    suggestions = []

    # 3. Generate Exit Suggestions per Spread
    for spread in spreads:
        legs = spread.legs # Object access
        if not legs:
            continue

        total_cost = 0.0
        total_value = 0.0
        total_quantity = 0.0

        underlying = spread.underlying
        net_delta = 0.0
        iv_rank = 50.0 # Default fallback
        # iv_regime initialized via V3 logic below
        effective_regime_state = RegimeState.NORMAL
        iv_regime = "normal"

        ref_symbol = legs[0]["symbol"]

        try:
            # 3a. Use Truth Layer for Options Data
            leg_symbols = [l["symbol"] for l in legs]
            snapshots = truth_layer.snapshot_many(leg_symbols)

            # V4: Get quality-scored snapshots and check for stale/invalid quotes
            # Pass raw_snapshots to avoid double fetch
            snapshots_v4 = truth_layer.snapshot_many_v4(leg_symbols, raw_snapshots=snapshots)
            from packages.quantum.services.market_data_truth_layer import (
                check_snapshots_executable,
                format_quality_gate_result,
                format_blocked_detail,
                build_marketdata_block_payload,
                get_marketdata_quality_policy,
                get_marketdata_min_quality_score,
                get_marketdata_max_freshness_ms,
                get_marketdata_warn_penalty,
                EFFECTIVE_ACTION_SKIP_FATAL,
                EFFECTIVE_ACTION_SKIP_POLICY,
                EFFECTIVE_ACTION_DEFER,
                EFFECTIVE_ACTION_DOWNRANK,
                EFFECTIVE_ACTION_DOWNRANK_FALLBACK,
            )
            is_executable, quality_issues = check_snapshots_executable(snapshots_v4, leg_symbols)

            # PR3.2: Track deferred gate result for downstream handling
            # Stored as tuple: (gate_result, policy, blocked_detail) for later processing
            deferred_quality_warning = None

            if not is_executable:
                # V4 structured logging: emit full quality gate result
                gate_result = format_quality_gate_result(snapshots_v4, leg_symbols)
                policy = get_marketdata_quality_policy()

                # Decide action based on policy and fatal/non-fatal codes
                if gate_result["has_fatal"]:
                    # Fatal issues always cause skip, regardless of policy
                    log_payload = {
                        "event": "marketdata.v4.quality_gate",
                        "effective_action": EFFECTIVE_ACTION_SKIP_FATAL,
                        "spread_id": str(spread.id),
                        "underlying": underlying,
                        "leg_symbols": leg_symbols,
                        "policy": policy,
                        "min_quality_score": get_marketdata_min_quality_score(),
                        "max_freshness_ms": get_marketdata_max_freshness_ms(),
                        **gate_result,
                    }
                    logger.warning(
                        f"Skipping spread {spread.id}: fatal quality issues",
                        extra={"quality_gate": log_payload}
                    )
                    continue
                elif policy == "skip":
                    # Skip policy: treat any warning as skip
                    log_payload = {
                        "event": "marketdata.v4.quality_gate",
                        "effective_action": EFFECTIVE_ACTION_SKIP_POLICY,
                        "spread_id": str(spread.id),
                        "underlying": underlying,
                        "leg_symbols": leg_symbols,
                        "policy": policy,
                        "min_quality_score": get_marketdata_min_quality_score(),
                        "max_freshness_ms": get_marketdata_max_freshness_ms(),
                        **gate_result,
                    }
                    logger.warning(
                        f"Skipping spread {spread.id}: quality warning (policy=skip)",
                        extra={"quality_gate": log_payload}
                    )
                    continue
                else:
                    # PR3.2: Defer/downrank policy - store for later processing
                    # Actual downrank/defer decision happens when suggestion is built (has access to metrics)
                    deferred_blocked_detail = format_blocked_detail(gate_result)
                    deferred_quality_warning = (gate_result, policy, deferred_blocked_detail)

            # V3 Symbol Snapshot
            sym_snap = regime_engine.compute_symbol_snapshot(underlying, global_snap)
            effective_regime_state = regime_engine.get_effective_regime(sym_snap, global_snap)

            # Record symbol features to decision context (for replay feature store)
            _record_symbol_features(underlying, sym_snap, global_snap)
            _record_surface_snapshot(underlying, sym_snap)

            # Map to scoring regime string for compatibility
            iv_regime = regime_engine.map_to_scoring_regime(effective_regime_state)
            iv_rank_score = sym_snap.iv_rank if sym_snap.iv_rank is not None else 50.0

            # Sum Deltas
            for leg in legs:
                sym = leg["symbol"]
                qty = float(leg.get("quantity", 0))

                norm_sym = truth_layer.normalize_symbol(sym)
                snap = snapshots.get(norm_sym, {})

                greeks = snap.get("greeks", {})
                delta = greeks.get("delta", 0.0) or 0.0

                net_delta += delta * qty

            # Use IV from context as reference
            norm_ref = truth_layer.normalize_symbol(ref_symbol)
            first_snap = snapshots.get(norm_ref, {})
            iv_decimal = first_snap.get("iv")
            if iv_decimal is None:
                 iv_decimal = 0.5 # fallback

        except Exception as e:
            print(f"Error fetching greeks for {ref_symbol}: {e}")
            iv_decimal = 0.5
            iv_rank_score = 50.0

        # Calculate spread financials
        for leg in legs:
            qty = float(leg.get("quantity", 0))
            cost = float(leg.get("cost_basis", 0) or 0)
            curr = float(leg.get("current_price", 0) or 0)

            total_cost += cost * qty * 100
            total_value += curr * qty * 100
            total_quantity += qty

        if total_cost == 0: total_cost = 0.01

        qty_unit = float(legs[0].get("quantity", 1))
        if qty_unit == 0: qty_unit = 1

        unit_price = (total_value / 100.0) / qty_unit
        unit_cost = (total_cost / 100.0) / qty_unit

        # Calculate EV-based Target
        metrics = calculate_exit_metrics(
            current_price=unit_price,
            cost_basis=unit_cost,
            delta=net_delta / qty_unit,
            iv=iv_decimal,
            days_to_expiry=30
        )

        # Risk Budget Check Annotation
        budget_note = ""
        if is_over_budget:
            budget_note = f" [Risk Budget Exceeded: {budget_usage_pct:.0f}% used]"

        # === EXIT MODE ROUTER ===
        # Gather market data for LossMinimizer (bid/ask from truth layer)
        exit_market_data = None
        try:
            norm_ref = truth_layer.normalize_symbol(ref_symbol)
            first_snap = snapshots.get(norm_ref, {})
            if first_snap:
                exit_market_data = {
                    "bid": first_snap.get("bid"),
                    "ask": first_snap.get("ask")
                }
        except Exception:
            pass

        exit_mode_result = compute_exit_mode(unit_price, unit_cost, exit_market_data)
        exit_mode = exit_mode_result["mode"]
        exit_warning = exit_mode_result.get("warning")

        # Determine final limit price and strategy based on exit mode
        final_limit_price = None
        strategy_name = "take_profit_limit"
        clamp_reason = None

        if exit_mode in ("salvage", "lottery_trap"):
            # Use LossMinimizer's recommended limit price
            final_limit_price = exit_mode_result.get("limit_price") or unit_price
            strategy_name = "salvage_exit" if exit_mode == "salvage" else "lottery_trap"
        elif metrics.expected_value > 0 and metrics.limit_price > unit_price:
            # Normal take-profit path - apply clamping guardrails
            final_limit_price, clamp_reason = clamp_take_profit_limit(
                metrics.limit_price, unit_price, exit_mode
            )
        else:
            # No suggestion for this position (negative EV or price already above target)
            continue

        # Skip if no valid limit price
        if final_limit_price is None or final_limit_price <= 0:
            continue

        # Build rationale text based on exit mode
        if exit_mode == "salvage":
            hist_stats = {"insufficient_history": True}  # Don't fetch stats for salvage
            rationale_text = (
                f"{exit_mode_result['rationale_prefix']}"
                f"Exit near bid/mid at ${final_limit_price:.2f} to preserve remaining capital. "
                f"Current: ${unit_price:.2f}, Cost: ${unit_cost:.2f}.{budget_note}"
            )
            if exit_warning:
                rationale_text += f" ⚠️ {exit_warning}"

        elif exit_mode == "lottery_trap":
            hist_stats = {"insufficient_history": True}  # Don't fetch stats for lottery
            rationale_text = (
                f"{exit_mode_result['rationale_prefix']}"
                f"GTC limit at ${final_limit_price:.2f} (volatility trap). "
                f"Position near worthless (${unit_price:.2f}); may catch spike.{budget_note}"
            )
            if exit_warning:
                rationale_text += f" ⚠️ {exit_warning}"

        else:
            # Normal take-profit
            hist_stats = ExitStatsService.get_stats(
                underlying=underlying,
                regime=iv_regime,
                strategy="take_profit_limit",
                supabase_client=supabase
            )

            if hist_stats.get("insufficient_history") or hist_stats.get("win_rate") is None:
                rationale_text = (
                    f"Take profit at ${final_limit_price:.2f} based on EV model. "
                    f"(Insufficient history for win-rate stats in {iv_regime} regime.){budget_note}"
                )
            else:
                win_rate_pct = hist_stats['win_rate'] * 100
                rationale_text = (
                    f"Take profit at ${final_limit_price:.2f} based on {win_rate_pct:.0f}% "
                    f"historical win rate for similar exits in {iv_regime} regime.{budget_note}"
                )

            if clamp_reason:
                rationale_text += f" [{clamp_reason}]"

            # Compute input-only features for hash (stable across price/EV changes)
            # features_for_hash: inputs only (ticker, spread_type, DTE, width, iv_regime, global_regime, symbol_regime, effective_regime)

            # Helper to compute width/DTE
            strikes = [float(l.get("strike", 0)) for l in legs]
            width = max(strikes) - min(strikes) if len(strikes) > 1 else 0.0

            try:
                # legs[0]["expiry"] is YYYY-MM-DD
                expiry_dt = datetime.strptime(legs[0]["expiry"], "%Y-%m-%d")
                dte = (expiry_dt - datetime.now()).days
            except Exception:
                dte = 30 # fallback

            features_for_hash = {
                "ticker": spread.ticker,
                "spread_type": spread.spread_type,
                "dte": dte,
                "width": width,
                "iv_regime": iv_regime,
                "global_regime": global_snap.state.value,
                "symbol_regime": sym_snap.state.value,
                "effective_regime": effective_regime_state.value
            }

            ctx = TradeContext.create_new(
                model_version=APP_VERSION,
                window="morning_limit",
                strategy=strategy_name,
                regime=iv_regime
            )
            ctx.features_hash = compute_features_hash(features_for_hash)

            # v4: Build lineage for exit suggestion
            exit_lineage = DecisionLineageBuilder()
            exit_lineage.set_strategy(strategy_name)
            exit_lineage.add_constraint("exit_mode", exit_mode)
            exit_lineage.add_constraint("target_price", final_limit_price)
            if is_over_budget:
                exit_lineage.add_constraint("risk_budget_status", "violated")
            exit_lineage_dict = exit_lineage.build()
            exit_sig_result = LineageSigner.sign(exit_lineage_dict)

            order_json = {
                "side": "close_spread",
                "limit_price": round(final_limit_price, 2),
                "legs": [
                    {
                        "symbol": l["symbol"],
                        "display_symbol": format_occ_symbol_readable(l["symbol"]),
                        "quantity": l["quantity"],
                        "side": l.get("side", "") # Added side from leg for fingerprinting
                    } for l in legs
                ]
            }

            # Add exit mode info to order_json for UI display
            if exit_mode != "normal":
                order_json["exit_mode"] = exit_mode
                if exit_warning:
                    order_json["warning"] = exit_warning

            # Calculate fingerprint
            fingerprint = compute_legs_fingerprint(order_json)

            suggestion = {
                    "user_id": user_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "valid_until": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
                    "window": "morning_limit",
                    "ticker": spread.ticker,
                    "display_symbol": spread.ticker,
                    "strategy": strategy_name,
                    "direction": "close",
                    "ev": metrics.expected_value if exit_mode == "normal" else 0.0,
                    "probability_of_profit": metrics.prob_of_profit if exit_mode == "normal" else None,
                    "rationale": rationale_text,
                    "historical_stats": hist_stats,
                    "order_json": order_json,
                "sizing_metadata": {
                    "reason": metrics.reason if exit_mode == "normal" else f"exit_mode={exit_mode}",
                    "exit_mode": exit_mode,
                    "clamp_reason": clamp_reason,
                    "context": {
                        "iv_rank": iv_rank_score,
                        "iv_regime": iv_regime,
                        "global_state": global_snap.state.value,
                        "regime_v3_global": global_snap.state.value,
                        "regime_v3_symbol": sym_snap.state.value,
                        "regime_v3_effective": effective_regime_state.value
                    },
                    "risk_budget": {
                         "remaining": remaining_global,
                         "usage_pct": budget_usage_pct,
                         "status": "violated" if is_over_budget else "ok"
                    },
                    "spread_details": {
                        "underlying": underlying,
                        "expiry": legs[0]["expiry"],
                        "type": spread.spread_type
                    }
                },
                "status": "pending",
                "trace_id": ctx.trace_id,
                "model_version": ctx.model_version,
                "features_hash": ctx.features_hash,
                "regime": ctx.regime,
                "legs_fingerprint": fingerprint,
                # v4 Observability Fields
                "decision_lineage": exit_lineage_dict,
                "lineage_hash": exit_sig_result.hash,
                "lineage_sig": exit_sig_result.signature,
                "lineage_version": exit_sig_result.version,
                "code_sha": get_code_sha(),
                "data_hash": ctx.features_hash
            }
            # Store v4 context for post-insert event emission
            suggestion["_v4_ctx"] = ctx
            suggestion["_v4_lineage"] = exit_lineage_dict
            suggestion["_v4_budget_info"] = {
                "remaining": remaining_global,
                "usage_pct": budget_usage_pct,
                "status": "violated" if is_over_budget else "ok"
            }
            suggestion["_v4_props"] = {
                "ev": metrics.expected_value,
                "ticker": spread.ticker,
                "probability_of_profit": metrics.prob_of_profit
            }

            # PR3.2: Apply deferred marketdata quality handling if warnings were present
            if deferred_quality_warning is not None:
                gate_result, policy, blocked_detail = deferred_quality_warning
                downrank_applied = False
                effective_action = EFFECTIVE_ACTION_DEFER
                downrank_reason = None
                warn_penalty = None

                if policy == "downrank":
                    # Try to find and apply penalty to ranking scalar
                    # Morning suggestions have 'ev' (expected_value) as the ranking scalar
                    ev_value = suggestion.get("ev")
                    if ev_value is not None and ev_value != 0:
                        warn_penalty = get_marketdata_warn_penalty()
                        original_ev = ev_value
                        suggestion["ev"] = float(ev_value) * warn_penalty
                        downrank_applied = True
                        effective_action = EFFECTIVE_ACTION_DOWNRANK
                        logger.info(
                            f"Downrank applied to spread {spread.id}: ev {original_ev:.4f} -> {suggestion['ev']:.4f}",
                            extra={"quality_gate": {
                                "event": "marketdata.v4.quality_gate.downrank_applied",
                                "effective_action": EFFECTIVE_ACTION_DOWNRANK,
                                "spread_id": str(spread.id),
                                "underlying": underlying,
                                "policy": policy,
                                "warn_penalty": warn_penalty,
                                "original_ev": original_ev,
                                "penalized_ev": suggestion["ev"],
                            }}
                        )
                    else:
                        # No ranking scalar found, fallback to defer
                        downrank_reason = "no_rank_scalar_found_fallback_to_defer"
                        effective_action = EFFECTIVE_ACTION_DOWNRANK_FALLBACK

                # Build the payload with effective_action
                deferred_gate_payload = build_marketdata_block_payload(
                    gate_result, policy, effective_action,
                    downrank_applied=downrank_applied,
                    downrank_reason=downrank_reason,
                    warn_penalty=warn_penalty
                )

                # Attach payload always
                suggestion["marketdata_quality"] = deferred_gate_payload

                # Block only if NOT successfully downranked
                if effective_action != EFFECTIVE_ACTION_DOWNRANK:
                    suggestion["status"] = "NOT_EXECUTABLE"
                    suggestion["blocked_reason"] = "marketdata_quality_gate"
                    suggestion["blocked_detail"] = blocked_detail

                    # Log defer/fallback event
                    logger.info(
                        f"Quality warning for spread {spread.id}: {effective_action} (policy={policy})",
                        extra={"quality_gate": {
                            "event": "marketdata.v4.quality_gate.defer_applied",
                            "effective_action": effective_action,
                            "spread_id": str(spread.id),
                            "underlying": underlying,
                            "policy": policy,
                            "warning_count": gate_result["warning_count"],
                            "symbols": [s["symbol"] + ":" + s["code"] for s in gate_result["symbols"] if s["code"] != "OK"],
                        }}
                    )

            suggestions.append(suggestion)

            # Note: emit_trade_event moved to post-insert to ensure suggestion_id exists first (v4 ordering)

            # Log Decision
            if ctx.trace_id:
                log_decision(
                    trace_id=ctx.trace_id,
                    user_id=user_id,
                    decision_type="morning_suggestion",
                    content={
                        "action": "close",
                        "strategy": "take_profit_limit",
                        "target_price": metrics.limit_price,
                        "ev": metrics.expected_value,
                        "rationale": rationale_text
                    }
                )

    # 4. Insert suggestions (Wave 1.2: insert-idempotent, no upsert of integrity fields)
    if suggestions:
        cycle_date = datetime.now(timezone.utc).date().isoformat()
        inserts_count = 0
        existing_count = 0

        # Deduplicate by fingerprint to prevent conflicts
        suggestion_map_by_fp = {}
        for s in suggestions:
            fp = s.get("legs_fingerprint")
            if fp:
                suggestion_map_by_fp[fp] = s

        final_suggestion_list = list(suggestion_map_by_fp.values())

        # Map to track suggestion_id by original trace_id (for post-insert events)
        inserted_suggestions = []

        for s in final_suggestion_list:
            s["cycle_date"] = cycle_date
            # PR3.2: Preserve NOT_EXECUTABLE status from quality gate
            if s.get("status") != "NOT_EXECUTABLE":
                s["status"] = "pending"

            # Clean v4 internal fields before insert
            clean_s = {k: v for k, v in s.items() if not k.startswith("_v4_")}

            # Wave 1.2: Use insert-or-get to avoid updating immutable fields
            unique_fields = (
                user_id,
                "morning_limit",
                cycle_date,
                s.get("ticker"),
                s.get("strategy"),
                s.get("legs_fingerprint")
            )

            # Supersede prior close suggestions if this is a close suggestion
            # This ensures only ONE pending exit suggestion exists per position
            strategy = s.get("strategy")
            direction = s.get("direction")
            if direction == "close" and strategy in CLOSE_STRATEGIES:
                supersede_prior_close_suggestions(
                    supabase,
                    user_id=user_id,
                    cycle_date=cycle_date,
                    window="morning_limit",
                    ticker=s.get("ticker"),
                    legs_fingerprint=s.get("legs_fingerprint"),
                    new_strategy=strategy,
                    reason=f"superseded_by_{strategy}"
                )

            try:
                suggestion_id, existing_trace_id, is_new = insert_or_get_suggestion(
                    supabase, clean_s, unique_fields
                )

                if suggestion_id:
                    # Store result for post-insert event emission
                    inserted_suggestions.append({
                        "suggestion_id": suggestion_id,
                        "trace_id": existing_trace_id if not is_new else s.get("trace_id"),
                        "is_new": is_new,
                        "original": s
                    })

                    if is_new:
                        inserts_count += 1
                    else:
                        existing_count += 1

            except Exception as e:
                print(f"[Wave1.2] Error inserting morning suggestion {s.get('ticker')}: {e}")

        print(f"Morning suggestions: {inserts_count} inserted, {existing_count} existing (unchanged)")

        # === v4 OBSERVABILITY: Post-insert event emission ===
        try:
            audit_service = AuditLogService(supabase)

            for item in inserted_suggestions:
                suggestion_id = item["suggestion_id"]
                trace_id = item["trace_id"]
                s = item["original"]

                # Get stored v4 context
                ctx = s.get("_v4_ctx")
                lineage_dict = s.get("_v4_lineage", {})
                budget_info = s.get("_v4_budget_info", {})
                props = s.get("_v4_props", {})

                if ctx:
                    # Set suggestion_id on context
                    ctx.suggestion_id = suggestion_id

                    # Emit analytics event (now idempotent via Wave 1.2)
                    emit_trade_event(
                        analytics_service,
                        user_id,
                        ctx,
                        "suggestion_generated",
                        properties=props
                    )

                # Write audit event (idempotent via Wave 1.1)
                audit_payload = {
                    "lineage": lineage_dict,
                    "ticker": s.get("ticker"),
                    "strategy": s.get("strategy"),
                    "ev": s.get("ev"),
                    "window": s.get("window")
                }
                audit_service.log_audit_event(
                    user_id=user_id,
                    trace_id=trace_id,
                    suggestion_id=suggestion_id,
                    event_name="suggestion_generated",
                    payload=audit_payload,
                    strategy=s.get("strategy"),
                    regime=s.get("regime")
                )

                # Write XAI attribution (idempotent via Wave 1.1)
                attribution = build_attribution_from_lineage(
                    lineage=lineage_dict,
                    ctx_regime=s.get("regime"),
                    sym_regime=s.get("sizing_metadata", {}).get("context", {}).get("regime_v3_symbol"),
                    global_regime=global_snap.state.value if global_snap else None,
                    budget_info=budget_info
                )
                audit_service.write_attribution(
                    suggestion_id=suggestion_id,
                    trace_id=trace_id,
                    **attribution
                )

            print(f"[v4] Emitted events and wrote audit/attribution for {len(inserted_suggestions)} morning suggestions")

        except Exception as e:
            print(f"[v4] Error in morning post-insert observability: {e}")

        # 5. Log suggestions
        try:
            logs = []
            for s in suggestions:
                target = s.get("order_json", {}).get("limit_price", 0.0)
                logs.append({
                    "user_id": user_id,
                    "created_at": s["created_at"],
                    "regime_context": {"cycle": "morning_limit", "global": global_snap.state.value},
                    "symbol": s["ticker"],
                    "strategy_type": s["strategy"],
                    "direction": s["direction"],
                    "target_price": target,
                    "confidence_score": s.get("probability_of_profit", 0) * 100,
                })

            if logs:
                supabase.table(SUGGESTION_LOGS_TABLE).insert(logs).execute()
                print(f"Logged {len(logs)} morning suggestions to ledger.")
        except Exception as e:
            print(f"Error logging morning suggestions: {e}")


async def run_midday_cycle(supabase: Client, user_id: str):
    """
    1. Use CashService.get_deployable_capital.
    2. Call optimizer/scanner to generate candidate trades.
    3. For each candidate, call sizing_engine.calculate_sizing.
    4. Insert trade_suggestions with window='midday_entry' and sizing_metadata.
    """
    print(f"Running midday cycle for user {user_id}")
    analytics_service = AnalyticsService(supabase)
    print("\n=== MIDDAY DEBUG ===")

    cash_service = CashService(supabase)
    deployable_capital = await cash_service.get_deployable_capital(user_id)
    print(f"Deployable capital: {deployable_capital}")

    # Fetch positions for RiskBudgetEngine
    try:
        res = supabase.table("positions").select("*").eq("user_id", user_id).execute()
        positions = res.data or []
    except Exception as e:
        print(f"Error fetching positions for midday risk check: {e}")
        positions = []

    can_scan, scan_reason = CapitalScanPolicy.can_scan(deployable_capital)
    if not can_scan:
        print(f"Skipping scan: {scan_reason}")
        return

    # V3: Compute Global Regime Snapshot ONCE
    truth_layer = MarketDataTruthLayer()
    iv_repo = IVRepository(supabase)
    iv_point_service = IVPointService(supabase)

    regime_engine = RegimeEngineV3(
        supabase_client=supabase,
        market_data=truth_layer,
        iv_repository=iv_repo,
        iv_point_service=iv_point_service,
    )

    global_snap = regime_engine.compute_global_snapshot(datetime.now())

    # Record regime features to decision context (for replay feature store)
    _record_regime_features(global_snap)

    # Record rates/divs for deterministic replay (Patch 2.1)
    truth_layer.rates_divs("SPY", as_of=datetime.now(timezone.utc))

    # Try to persist global snapshot
    try:
        supabase.table("regime_snapshots").insert(global_snap.to_dict()).execute()
    except Exception:
        pass

    # === RISK BUDGET ENGINE ===
    risk_engine = RiskBudgetEngine(supabase)
    budgets = risk_engine.compute(user_id, deployable_capital, global_snap.state.value, positions)

    remaining_global = budgets.global_allocation.remaining
    usage_global = budgets.global_allocation.used
    max_global = budgets.global_allocation.max_limit

    print(f"Risk Budget: Remaining=${remaining_global:.2f}, Usage=${usage_global:.2f}, Cap=${max_global:.2f} ({budgets.regime})")

    if remaining_global <= 0 and not MIDDAY_TEST_MODE:
         print("Risk budget exhausted. Skipping midday cycle.")
         # Log Veto
         try:
             # Generate a trace_id for this rejection event
             veto_trace_id = uuid.uuid4()
             # Log a dummy inference to satisfy FK constraint
             log_inference(
                 symbol_universe=[],
                 inputs_snapshot={},
                 predicted_mu={},
                 predicted_sigma={},
                 optimizer_profile="midday_veto",
                 trace_id=veto_trace_id
             )
             # Attempt to extract strategy from candidate if available
             strat = None # Global budget check has no candidate yet
             log_decision(
                 trace_id=veto_trace_id,
                 user_id=user_id,
                 decision_type="trade_veto",
                 content={
                     "reason": "global_risk_budget_exhausted",
                     "agent": "RiskBudgetEngine",
                     "remaining_global": remaining_global,
                     "strategy": strat
                 }
             )
         except Exception as e:
             print(f"Error logging global veto: {e}")
         return

    # 2. Call Scanner (market-wide)
    candidates = []
    scout_results = []

    # Fetch user policy settings
    banned_strategies = []
    try:
        # Try to fetch from settings table if it exists and has the column
        # Fallback to empty if not found
        settings_res = supabase.table("settings").select("banned_strategies").eq("user_id", user_id).single().execute()
        if settings_res.data:
            banned_strategies = settings_res.data.get("banned_strategies") or []
    except Exception as e:
        # settings table might not exist or column missing, non-critical
        print(f"Note: Could not fetch banned_strategies for user {user_id}: {e}")

    # Initialize Policy for Final Gate
    policy = StrategyPolicy(banned_strategies)

    try:
        # Step C: Wire user_id from cycle orchestration into scanner
        scout_results = scan_for_opportunities(
            supabase_client=supabase,
            user_id=user_id,
            global_snapshot=global_snap,
            banned_strategies=banned_strategies,
            portfolio_cash=deployable_capital
        )

        print(f"Scanner returned {len(scout_results)} raw opportunities.")

        for c in scout_results:
            c["window"] = "midday_entry"

        conviction_service = ConvictionService(supabase=supabase)
        scout_results = conviction_service.adjust_suggestion_scores(scout_results, user_id)

        # NEW: Rank and Select Pipeline using SmallAccountCompounder
        # Detect capital tier
        tier = SmallAccountCompounder.get_tier(deployable_capital)
        print(f"[Midday] Account Tier: {tier.name} (Compounding: {COMPOUNDING_MODE})")

        # Select candidates
        remaining_global_budget = float(
            budgets.get("remaining")
            or budgets.get("remaining_budget")
            or budgets.get("remaining_dollars")
            or 0.0
        )

        # Config
        midday_config = SizingConfig(compounding_enabled=COMPOUNDING_MODE)

        # Use Global regime state for selection estimation
        current_regime = global_snap.state.value

        candidates = SmallAccountCompounder.rank_and_select(
            candidates=scout_results,
            capital=deployable_capital,
            risk_budget=remaining_global_budget,
            config=midday_config,
            regime=current_regime
        )

        print(f"Top {len(candidates)} candidates selected for midday:")
        for c in candidates:
            print(f"  {c.get('ticker', c.get('symbol'))} score={c.get('score')} type={c.get('type')}")

        if not candidates:
            print("No candidates selected for midday entries.")
            return

    except Exception as e:
        print(f"Scanner failed: {e}")
        return

    suggestions = []

    # 3. Size and Prepare Suggestions
    for cand in candidates:
        # Initialize Lineage Builder for this candidate
        lineage = DecisionLineageBuilder()
        lineage.add_agent("Scanner", score=cand.get("score")) # Scanner was used to find this candidate

        ticker = cand.get("ticker") or cand.get("symbol")
        strategy = cand.get("strategy") or cand.get("type") or "unknown"
        lineage.set_strategy(strategy)

        # V3: Compute Symbol Snapshot
        sym_snap = regime_engine.compute_symbol_snapshot(ticker, global_snap)
        effective_regime = regime_engine.get_effective_regime(sym_snap, global_snap)
        effective_regime_str = effective_regime.value
        scoring_regime = regime_engine.map_to_scoring_regime(effective_regime)

        # Record symbol features to decision context (for replay feature store)
        _record_symbol_features(ticker, sym_snap, global_snap)
        _record_surface_snapshot(ticker, sym_snap)

        # Extract pricing info. structure of candidate varies, assuming basic keys
        price = float(cand.get("suggested_entry", 0))
        ev = float(cand.get("ev", 0))

        if price <= 0:
            continue

        # --- SIZING INPUTS (compute BEFORE calling calculate_sizing) ---
        price = float(cand.get("suggested_entry", 0.0) or 0.0)  # per-share premium magnitude
        max_loss = float(cand.get("max_loss_per_contract") or (price * 100.0))
        collateral = float(
            cand.get("collateral_required_per_contract")
            or cand.get("collateral_per_contract")
            or max_loss
        )

        # --- AGENT-BASED SIZING ---
        # Defaults to classic logic, overridden if agent is enabled
        QUANT_AGENTS_ENABLED = os.getenv("QUANT_AGENTS_ENABLED", "false").lower() == "true"

        # Use SmallAccountCompounder for variable sizing (classic path)
        tier = SmallAccountCompounder.get_tier(deployable_capital)
        sizing_vars = SmallAccountCompounder.calculate_variable_sizing(
            candidate=cand,
            capital=deployable_capital,
            tier=tier,
            regime=scoring_regime,
            compounding=COMPOUNDING_MODE
        )

        # Classic Risk Calculations
        risk_budget_dollars = sizing_vars["risk_budget"]
        risk_multiplier = sizing_vars["multipliers"]["score"]
        recommended_risk = budgets.max_risk_per_trade
        final_risk_dollars = min(risk_budget_dollars, recommended_risk)
        final_risk_dollars = clamp_risk_budget(final_risk_dollars, remaining_global)

        max_contracts_limit = 25
        sizing_agent_signal = None

        if QUANT_AGENTS_ENABLED:
            try:
                sizing_agent = SizingAgent()

                # V3: Prepare Agent Signals
                # Use ONLY real agent signals from the scanner (no mocks)
                current_agent_signals = cand.get("agent_signals", {}).copy()

                sizing_ctx = {
                    "deployable_capital": deployable_capital,
                    "max_loss_per_contract": max_loss,
                    "collateral_required_per_contract": collateral,
                    "base_score": cand.get("score", 50.0),
                    "agent_signals": current_agent_signals
                }
                sizing_agent_signal = sizing_agent.evaluate(sizing_ctx)

                # Apply Agent Constraints
                # Handle both dict and Pydantic model for sizing_agent_signal (evaluate returns model)
                sizing_meta = sizing_agent_signal.metadata if hasattr(sizing_agent_signal, "metadata") else sizing_agent_signal.get("metadata", {})
                constraints = sizing_meta.get("constraints", {})

                agent_target_risk = constraints.get("sizing.target_risk_usd", 0.0)

                # Use the tighter of (Agent Target, Global Budget Remaining)
                # But allow Agent to be the primary sizer
                final_risk_dollars = min(agent_target_risk, remaining_global)

                # Agent also dictates max contracts
                max_contracts_limit = constraints.get("sizing.recommended_contracts", 25)

                # Record in Lineage
                if constraints:
                    for k, v in constraints.items():
                        lineage.add_constraint(k, v)

                # Add agent to lineage with score and metadata
                sizing_score = sizing_agent_signal.score if hasattr(sizing_agent_signal, "score") else sizing_agent_signal.get("score", 50.0)
                lineage.add_agent("SizingAgent", score=sizing_score, metadata={"constraints": constraints})

                # Update candidate signals
                if "agent_signals" not in cand:
                    cand["agent_signals"] = {}

                # Store signal
                if hasattr(sizing_agent_signal, "model_dump"):
                    cand["agent_signals"]["sizing"] = sizing_agent_signal.model_dump()
                else:
                    cand["agent_signals"]["sizing"] = sizing_agent_signal

                # Handle model vs dict for score
                sizing_score = sizing_agent_signal.score if hasattr(sizing_agent_signal, "score") else sizing_agent_signal.get("score", 50.0)

                # Update Summary Score
                if "agent_summary" not in cand:
                    cand["agent_summary"] = {"overall_score": sizing_score}
                else:
                    # Simple re-average
                    current_overall = cand["agent_summary"].get("overall_score", 50.0)
                    new_overall = (current_overall + sizing_score) / 2
                    cand["agent_summary"]["overall_score"] = new_overall

                print(f"[Midday] SizingAgent applied: Risk=${final_risk_dollars:.2f}, Contracts={max_contracts_limit}")

            except Exception as e:
                print(f"[Midday] SizingAgent failed: {e}. Falling back to classic sizing.")
                # Log Fallback
                try:
                     # We need a trace_id. Using a new one for this event if needed, or context's if available later?
                     # Context is not created yet. We'll create a temporary trace.
                     fallback_trace_id = uuid.uuid4()
                     log_inference(
                         symbol_universe=[ticker],
                         inputs_snapshot={},
                         predicted_mu={},
                         predicted_sigma={},
                         optimizer_profile="midday_fallback",
                         trace_id=fallback_trace_id
                     )
                     # Attempt to extract strategy
                     strat = cand.get("strategy") or cand.get("type")
                     log_decision(
                         trace_id=fallback_trace_id,
                         user_id=user_id,
                         decision_type="system_fallback",
                         content={
                             "component": "SizingAgent",
                             "error": str(e),
                             "fallback": "classic_sizing",
                             "ticker": ticker,
                             "strategy": strat
                         }
                     )
                except Exception as log_err:
                     print(f"Error logging fallback: {log_err}")
                # Fallback to calculated above

            # --- EXIT PLAN AGENT ---
            try:
                exit_agent = ExitPlanAgent()
                exit_ctx = {
                    "strategy_type": strategy
                }
                exit_signal = exit_agent.evaluate(exit_ctx)

                # Store signal
                if "agent_signals" not in cand:
                    cand["agent_signals"] = {}

                if hasattr(exit_signal, "model_dump"):
                    cand["agent_signals"]["exit_plan"] = exit_signal.model_dump()
                else:
                    cand["agent_signals"]["exit_plan"] = exit_signal

                # Handle model vs dict for exit_signal
                exit_score = exit_signal.score if hasattr(exit_signal, "score") else exit_signal.get("score", 50.0)

                # Update Summary Constraints
                if "agent_summary" not in cand:
                    # If SizingAgent didn't run or failed, init
                    cand["agent_summary"] = {"overall_score": exit_score, "active_constraints": {}}

                if "active_constraints" not in cand["agent_summary"]:
                    cand["agent_summary"]["active_constraints"] = {}

                # Merge ONLY constraints into active_constraints
                exit_meta = exit_signal.metadata if hasattr(exit_signal, "metadata") else exit_signal.get("metadata", {})
                exit_constraints = exit_meta.get("constraints", {})
                cand["agent_summary"]["active_constraints"].update(exit_constraints)

                if exit_constraints:
                    for k, v in exit_constraints.items():
                        lineage.add_constraint(k, v)

                exit_score = exit_signal.score if hasattr(exit_signal, "score") else exit_signal.get("score", 50.0)
                lineage.add_agent("ExitPlanAgent", score=exit_score, metadata={"constraints": exit_constraints})

                print(f"[Midday] ExitPlanAgent applied: {exit_constraints}")

            except Exception as e:
                print(f"[Midday] ExitPlanAgent failed: {e}")
                # We don't necessarily fail everything if exit plan fails, but we can log it
                # lineage.set_fallback(...) - careful not to overwrite SizingAgent fallback if any
                pass

        if final_risk_dollars <= 0:
            print(f"[Midday] Skipped {ticker}: Risk budget exhausted for trade (Remaining: ${remaining_global:.2f})")
            # Log Veto
            try:
                veto_trace_id = uuid.uuid4()
                log_inference(
                    symbol_universe=[ticker],
                    inputs_snapshot={},
                    predicted_mu={},
                    predicted_sigma={},
                    optimizer_profile="midday_veto",
                    trace_id=veto_trace_id
                )
                # Attempt to extract strategy from candidate if available
                strat = cand.get("strategy") or cand.get("type")
                log_decision(
                    trace_id=veto_trace_id,
                    user_id=user_id,
                    decision_type="trade_veto",
                    content={
                        "reason": "risk_budget_exhausted",
                        "ticker": ticker,
                        "strategy": strat,
                        "agent": "RiskBudgetEngine",
                        "remaining_global": remaining_global
                    }
                )
            except Exception as e:
                print(f"Error logging trade veto: {e}")
            continue

        # Update variable for sizing engine
        risk_budget_dollars = final_risk_dollars

        # Determine Sizing Source
        # Check if SizingAgent is in agents_involved (list of dicts now)
        has_sizing_agent = any(a["name"] == "SizingAgent" for a in lineage.agents_involved)
        if QUANT_AGENTS_ENABLED and has_sizing_agent and not lineage.fallback_reason:
            lineage.set_sizing_source("SizingAgent")
        else:
            lineage.set_sizing_source("ClassicSizing")

        # --- SIZING (single call) ---
        sizing = calculate_sizing(
            account_buying_power=deployable_capital,
            ev_per_contract=float(cand.get("ev", 0.0) or 0.0),
            contract_ask=price,  # keep for logging compatibility
            max_loss_per_contract=max_loss,
            collateral_required_per_contract=collateral,
            risk_budget_dollars=risk_budget_dollars,
            risk_multiplier=1.0,   # multiplier already baked into risk_budget_dollars
            max_contracts=max_contracts_limit,
            profile="aggressive",
        )

        allowed_risk_dollars = sizing.get("max_dollar_risk", 0.0)

        # If contracts == 0, check reasons.
        if sizing["contracts"] == 0:
            print(f"[Midday] Skipped {ticker}: {sizing['reason']} (Allowed Risk: ${allowed_risk_dollars:.2f})")
            # Log Veto
            try:
                veto_trace_id = uuid.uuid4()
                log_inference(
                    symbol_universe=[ticker],
                    inputs_snapshot={},
                    predicted_mu={},
                    predicted_sigma={},
                    optimizer_profile="midday_veto",
                    trace_id=veto_trace_id
                )
                # Attempt to extract strategy
                strat = cand.get("strategy") or cand.get("type")
                log_decision(
                    trace_id=veto_trace_id,
                    user_id=user_id,
                    decision_type="trade_veto",
                    content={
                        "reason": sizing.get('reason'),
                        "ticker": ticker,
                        "strategy": strat,
                        "agent": "SizingAgent"
                    }
                )
            except Exception as e:
                print(f"Error logging sizing veto: {e}")

        print(
            f"[Midday] {ticker} sizing: contracts={sizing.get('contracts')}, "
            f"max_risk_exceeded={sizing.get('max_risk_exceeded', False)}, "
            f"risk_mult={risk_multiplier:.2f}, "
            f"allowed=${allowed_risk_dollars:.2f}, "
            f"ev_per_contract={ev}, "
            f"reason={sizing.get('reason')}"
        )

        is_max_risk = sizing.get("max_risk_exceeded", False)
        if MIDDAY_TEST_MODE and sizing["contracts"] <= 0 and not is_max_risk:
             sizing["contracts"] = 1
             sizing["reason"] = (sizing.get("reason", "") or "") + " | dev_override=1_contract"

        if sizing["contracts"] > 0:
            if "context" not in sizing:
                sizing["context"] = {
                    "iv_rank": cand.get("iv_rank"),
                    "iv_regime": scoring_regime,
                    "global_state": global_snap.state.value,
                    "regime_v3_global": global_snap.state.value,
                    "regime_v3_symbol": sym_snap.state.value,
                    "regime_v3_effective": effective_regime_str
                }
            else:
                # Update existing context
                sizing["context"].update({
                    "regime_v3_global": global_snap.state.value,
                    "regime_v3_symbol": sym_snap.state.value,
                    "regime_v3_effective": effective_regime_str,
                    "iv_regime": scoring_regime # ensure consistency
                })

            # Persist sizing metadata as requested
            sizing["capital_required"] = sizing.get("capital_required", 0)

            postprocess_midday_sizing(sizing, max_loss)

            sizing["risk_multiplier"] = risk_multiplier
            sizing["budget_snapshot"] = budgets.model_dump()
            sizing["allowed_risk_dollars"] = allowed_risk_dollars

            cand_features = {
                "ticker": ticker,
                "strategy": strategy,
                "ev": ev,
                "price": price,
                "score": cand.get("score"),
                "iv_rank": cand.get("iv_rank"),
                "sizing": sizing,
                "regime": effective_regime_str
            }

            ctx = TradeContext.create_new(
                model_version=APP_VERSION,
                window="midday_entry",
                strategy=strategy,
                regime=effective_regime_str
            )
            ctx.features_hash = compute_features_hash(cand_features)

            pop = cand.get("probability_of_profit")

            # PR3.1: V4 Quality Gate for Midday Entries
            # Get leg symbols and fetch market data for quality check
            midday_legs = cand.get("legs") or []
            midday_leg_symbols = [leg.get("symbol") for leg in midday_legs if leg.get("symbol")]
            midday_snapshots_v4 = None
            midday_deferred_gate_payload = None
            midday_deferred_blocked_detail = None

            if midday_leg_symbols:
                from packages.quantum.services.market_data_truth_layer import (
                    check_snapshots_executable,
                    format_quality_gate_result,
                    format_blocked_detail,
                    build_marketdata_block_payload,
                    get_marketdata_quality_policy,
                    get_marketdata_min_quality_score,
                    get_marketdata_max_freshness_ms,
                    get_marketdata_warn_penalty,
                    EFFECTIVE_ACTION_SKIP_FATAL,
                    EFFECTIVE_ACTION_SKIP_POLICY,
                    EFFECTIVE_ACTION_DEFER,
                    EFFECTIVE_ACTION_DOWNRANK,
                    EFFECTIVE_ACTION_DOWNRANK_FALLBACK,
                )
                midday_raw_snapshots = truth_layer.snapshot_many(midday_leg_symbols)
                midday_snapshots_v4 = truth_layer.snapshot_many_v4(midday_leg_symbols, raw_snapshots=midday_raw_snapshots)
                is_executable, quality_issues = check_snapshots_executable(midday_snapshots_v4, midday_leg_symbols)

                if not is_executable:
                    gate_result = format_quality_gate_result(midday_snapshots_v4, midday_leg_symbols)
                    midday_policy = get_marketdata_quality_policy()

                    if gate_result["has_fatal"]:
                        # Fatal issues always cause skip
                        log_payload = {
                            "event": "marketdata.v4.quality_gate",
                            "effective_action": EFFECTIVE_ACTION_SKIP_FATAL,
                            "ticker": ticker,
                            "strategy": strategy,
                            "leg_symbols": midday_leg_symbols,
                            "policy": midday_policy,
                            "min_quality_score": get_marketdata_min_quality_score(),
                            "max_freshness_ms": get_marketdata_max_freshness_ms(),
                            **gate_result,
                        }
                        logger.warning(
                            f"Skipping midday candidate {ticker} {strategy}: fatal quality issues",
                            extra={"quality_gate": log_payload}
                        )
                        continue
                    elif midday_policy == "skip":
                        # Skip policy: treat any warning as skip
                        log_payload = {
                            "event": "marketdata.v4.quality_gate",
                            "effective_action": EFFECTIVE_ACTION_SKIP_POLICY,
                            "ticker": ticker,
                            "strategy": strategy,
                            "leg_symbols": midday_leg_symbols,
                            "policy": midday_policy,
                            "min_quality_score": get_marketdata_min_quality_score(),
                            "max_freshness_ms": get_marketdata_max_freshness_ms(),
                            **gate_result,
                        }
                        logger.warning(
                            f"Skipping midday candidate {ticker} {strategy}: quality warning (policy=skip)",
                            extra={"quality_gate": log_payload}
                        )
                        continue
                    else:
                        # PR3.2: Defer/downrank policy with effective_action
                        downrank_applied = False
                        downrank_reason = None
                        effective_action = EFFECTIVE_ACTION_DEFER
                        warn_penalty = None

                        # Attempt downrank if policy is downrank and we have a ranking scalar
                        if midday_policy == "downrank":
                            ranking_scalar = cand.get("score") or cand.get("ev") or cand.get("expected_value")
                            if ranking_scalar is not None:
                                warn_penalty = get_marketdata_warn_penalty()
                                # Apply penalty to the field we found
                                if cand.get("score") is not None:
                                    original_score = cand["score"]
                                    cand["score"] = float(cand["score"]) * warn_penalty
                                    downrank_applied = True
                                    effective_action = EFFECTIVE_ACTION_DOWNRANK
                                elif cand.get("ev") is not None:
                                    original_ev = cand["ev"]
                                    cand["ev"] = float(cand["ev"]) * warn_penalty
                                    ev = cand["ev"]  # Update local variable too
                                    downrank_applied = True
                                    effective_action = EFFECTIVE_ACTION_DOWNRANK
                            else:
                                downrank_reason = "no_rank_scalar_found_fallback_to_defer"
                                effective_action = EFFECTIVE_ACTION_DOWNRANK_FALLBACK

                        midday_deferred_gate_payload = build_marketdata_block_payload(
                            gate_result, midday_policy, effective_action,
                            downrank_applied=downrank_applied,
                            downrank_reason=downrank_reason,
                            warn_penalty=warn_penalty
                        )
                        midday_deferred_blocked_detail = format_blocked_detail(gate_result)

                        # Log with effective_action
                        if effective_action == EFFECTIVE_ACTION_DOWNRANK:
                            logger.info(
                                f"Downrank applied to midday {ticker} {strategy} (policy={midday_policy})",
                                extra={"quality_gate": {
                                    "event": "marketdata.v4.quality_gate.downrank_applied",
                                    "effective_action": effective_action,
                                    "ticker": ticker,
                                    "strategy": strategy,
                                    "policy": midday_policy,
                                    "warn_penalty": warn_penalty,
                                    "warning_count": gate_result["warning_count"],
                                    "symbols": [s["symbol"] + ":" + s["code"] for s in gate_result["symbols"] if s["code"] != "OK"],
                                }}
                            )
                        else:
                            logger.info(
                                f"Quality warning for midday {ticker} {strategy}: {effective_action} (policy={midday_policy})",
                                extra={"quality_gate": {
                                    "event": "marketdata.v4.quality_gate.defer_applied",
                                    "effective_action": effective_action,
                                    "ticker": ticker,
                                    "strategy": strategy,
                                    "policy": midday_policy,
                                    "warning_count": gate_result["warning_count"],
                                    "symbols": [s["symbol"] + ":" + s["code"] for s in gate_result["symbols"] if s["code"] != "OK"],
                                }}
                            )

                        # Store effective_action for later use
                        midday_deferred_gate_payload["_effective_action"] = effective_action

            order_json = build_midday_order_json(cand, sizing["contracts"], leg_snapshots_v4=midday_snapshots_v4)

            # Calculate fingerprint
            fingerprint = compute_legs_fingerprint(order_json)

            # Final Policy Gate (should have been filtered upstream, but redundant check)
            if not policy.is_allowed(strategy):
                print(f"[Midday] Final Gate: Rejecting {ticker} {strategy} due to policy.")
                continue

            # v4: Build and sign lineage
            lineage_dict = lineage.build()
            sig_result = LineageSigner.sign(lineage_dict)

            suggestion = {
                "user_id": user_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "valid_until": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
                "window": "midday_entry",
                "ticker": ticker,
                "strategy": strategy,
                "direction": "long",
                "order_json": order_json,
                "sizing_metadata": sizing,
                "decision_lineage": lineage_dict,
                "status": "pending",
                "source": "scanner",
                "ev": ev,
                "probability_of_profit": pop,
                "internal_cand": cand,
                "trace_id": ctx.trace_id,
                "model_version": ctx.model_version,
                "features_hash": ctx.features_hash,
                "regime": ctx.regime,
                "legs_fingerprint": fingerprint,
                # v4 Observability Fields
                "lineage_hash": sig_result.hash,
                "lineage_sig": sig_result.signature,
                "lineage_version": sig_result.version,
                "code_sha": get_code_sha(),
                "data_hash": ctx.features_hash  # For now, same as features_hash
            }

            # --- AGENT FIELDS ---
            if "agent_signals" in cand:
                suggestion["agent_signals"] = cand["agent_signals"]
            if "agent_summary" in cand:
                suggestion["agent_summary"] = cand["agent_summary"]

            # Store v4 context for post-insert event emission
            suggestion["_v4_ctx"] = ctx
            suggestion["_v4_lineage"] = lineage_dict
            suggestion["_v4_budget_info"] = {
                "remaining": remaining_global,
                "usage_pct": (usage_global / max_global * 100) if max_global > 0 else 0,
                "status": "ok" if remaining_global > 0 else "violated"
            }

            # PR3.2: Apply deferred marketdata quality handling if warnings were present
            if midday_deferred_gate_payload is not None:
                # Always attach the payload
                # Remove internal field before attaching
                effective_action = midday_deferred_gate_payload.pop("_effective_action", "defer")
                suggestion["marketdata_quality"] = midday_deferred_gate_payload

                # Only block if NOT successfully downranked
                if effective_action != "downrank":
                    suggestion["status"] = "NOT_EXECUTABLE"
                    suggestion["blocked_reason"] = "marketdata_quality_gate"
                    suggestion["blocked_detail"] = midday_deferred_blocked_detail

            suggestions.append(suggestion)

            # Note: emit_trade_event moved to post-insert to ensure suggestion_id exists first (v4 ordering)

            # Log Decision
            if ctx.trace_id:
                log_decision(
                    trace_id=ctx.trace_id,
                    user_id=user_id,
                    decision_type="midday_suggestion",
                    content={
                        "action": "open",
                        "strategy": strategy,
                        "sizing": sizing, # Full sizing details
                        "ev": ev,
                        "score": cand.get("score")
                    }
                )

    print(f"FINAL MIDDAY SUGGESTION COUNT: {len(suggestions)}")

    # Wave 1.2: Insert-idempotent, no upsert of integrity fields
    if suggestions:
        cycle_date = datetime.now(timezone.utc).date().isoformat()
        inserts_count = 0
        existing_count = 0

        # Map to track suggestion_id by original trace_id (for post-insert events)
        inserted_suggestions = []

        for s in suggestions:
            s["cycle_date"] = cycle_date
            # PR3.2: Preserve NOT_EXECUTABLE status from quality gate
            if s.get("status") != "NOT_EXECUTABLE":
                s["status"] = "pending"

            # Clean internal fields (including v4 context stored for post-insert processing)
            clean_s = {k: v for k, v in s.items() if k != 'internal_cand' and not k.startswith('_v4_')}

            # Wave 1.2: Use insert-or-get to avoid updating immutable fields
            unique_fields = (
                user_id,
                "midday_entry",
                cycle_date,
                s.get("ticker"),
                s.get("strategy"),
                s.get("legs_fingerprint")
            )

            try:
                suggestion_id, existing_trace_id, is_new = insert_or_get_suggestion(
                    supabase, clean_s, unique_fields
                )

                if suggestion_id:
                    # Store result for post-insert event emission
                    inserted_suggestions.append({
                        "suggestion_id": suggestion_id,
                        "trace_id": existing_trace_id if not is_new else s.get("trace_id"),
                        "is_new": is_new,
                        "original": s
                    })

                    if is_new:
                        inserts_count += 1
                    else:
                        existing_count += 1

            except Exception as e:
                error_str = str(e).lower()
                # Fallback: remove agent fields if insert failed (likely missing columns)
                if "agent_signals" in error_str or "agent_summary" in error_str or "column" in error_str:
                    print(f"[Wave1.2] Insert failed due to agent columns, retrying without them: {e}")
                    clean_s_fallback = {k: v for k, v in clean_s.items()
                                        if k not in ("agent_signals", "agent_summary")}
                    try:
                        suggestion_id, existing_trace_id, is_new = insert_or_get_suggestion(
                            supabase, clean_s_fallback, unique_fields
                        )
                        if suggestion_id:
                            inserted_suggestions.append({
                                "suggestion_id": suggestion_id,
                                "trace_id": existing_trace_id if not is_new else s.get("trace_id"),
                                "is_new": is_new,
                                "original": s
                            })
                            if is_new:
                                inserts_count += 1
                            else:
                                existing_count += 1
                    except Exception as fallback_err:
                        print(f"[Wave1.2] Fallback insert also failed: {fallback_err}")
                else:
                    print(f"[Wave1.2] Error inserting midday suggestion {s.get('ticker')}: {e}")

        print(f"Midday suggestions: {inserts_count} inserted, {existing_count} existing (unchanged)")

        # === v4 OBSERVABILITY: Post-insert event emission ===
        try:
            audit_service = AuditLogService(supabase)

            for item in inserted_suggestions:
                suggestion_id = item["suggestion_id"]
                trace_id = item["trace_id"]
                s = item["original"]

                # Get stored v4 context
                ctx = s.get("_v4_ctx")
                lineage_dict = s.get("_v4_lineage", {})
                budget_info = s.get("_v4_budget_info", {})

                if ctx:
                    # Set suggestion_id on context
                    ctx.suggestion_id = suggestion_id

                    # Emit analytics event (now idempotent via Wave 1.2)
                    cand = s.get("internal_cand", {})
                    props = {"ev": s.get("ev"), "score": cand.get("score")}
                    if s.get("probability_of_profit") is not None:
                        props["probability_of_profit"] = s.get("probability_of_profit")

                    emit_trade_event(
                        analytics_service,
                        user_id,
                        ctx,
                        "suggestion_generated",
                        properties=props
                    )

                # Write audit event (idempotent via Wave 1.1)
                audit_payload = {
                    "lineage": lineage_dict,
                    "ticker": s.get("ticker"),
                    "strategy": s.get("strategy"),
                    "ev": s.get("ev"),
                    "window": s.get("window")
                }
                audit_service.log_audit_event(
                    user_id=user_id,
                    trace_id=trace_id,
                    suggestion_id=suggestion_id,
                    event_name="suggestion_generated",
                    payload=audit_payload,
                    strategy=s.get("strategy"),
                    regime=s.get("regime")
                )

                # Write XAI attribution (idempotent via Wave 1.1)
                attribution = build_attribution_from_lineage(
                    lineage=lineage_dict,
                    ctx_regime=s.get("regime"),
                    sym_regime=s.get("sizing_metadata", {}).get("context", {}).get("regime_v3_symbol"),
                    global_regime=global_snap.state.value if global_snap else None,
                    budget_info=budget_info
                )
                audit_service.write_attribution(
                    suggestion_id=suggestion_id,
                    trace_id=trace_id,
                    **attribution
                )

            print(f"[v4] Emitted events and wrote audit/attribution for {len(inserted_suggestions)} midday suggestions")

        except Exception as e:
            print(f"[v4] Error in midday post-insert observability: {e}")

        try:
            logs = []
            for s in suggestions:
                cand = s.get("internal_cand", {})
                regime_ctx = {
                    "iv_rank": cand.get("iv_rank"),
                    "trend": cand.get("trend"),
                    "score": cand.get("score"),
                    "global_state": global_snap.state.value,
                    "effective_regime": s.get("regime")
                }

                logs.append({
                    "user_id": user_id,
                    "created_at": s["created_at"],
                    "regime_context": regime_ctx,
                    "symbol": s["ticker"],
                    "strategy_type": s["strategy"],
                    "direction": s["direction"],
                    "target_price": s["order_json"]["limit_price"],
                    "confidence_score": cand.get("score", 0),
                })

            if logs:
                supabase.table(SUGGESTION_LOGS_TABLE).insert(logs).execute()
                print(f"Logged {len(logs)} midday suggestions to ledger.")
        except Exception as e:
            print(f"Error logging midday suggestions: {e}")


async def run_weekly_report(supabase: Client, user_id: str):
    """
    1. Use JournalService to aggregate stats for the current week.
    2. Write weekly_trade_reports row with metrics + report_markdown stub.
    """
    print(f"Running weekly report for user {user_id}")

    journal_service = JournalService(supabase)

    try:
        stats = journal_service.get_journal_stats(user_id)
        metrics = stats.get("stats", {})
    except Exception as e:
        print(f"Error fetching journal stats: {e}")
        metrics = {}

    win_rate_raw = metrics.get("win_rate", 0)
    win_rate_ratio, win_rate_pct = normalize_win_rate(win_rate_raw)

    total_pnl = metrics.get("total_pnl", 0)
    trade_count = metrics.get("trade_count", 0)

    report_md = f"""
# Weekly Trading Report

**Week Ending:** {datetime.now().strftime('%Y-%m-%d')}

## Performance Summary
- **P&L:** ${total_pnl:.2f}
- **Win Rate:** {win_rate_pct:.1f}%
- **Trades:** {trade_count}

## AI Insights
*Generated based on your trading history...*
(Placeholder for deeper AI analysis)
    """

    # --- ADAPTIVE CAPS: LossMinimizer Feedback Loop ---
    # Fetch recent trades to analyze losses
    recent_losses_summary = {}
    try:
        # We need a summary of recent losses. JournalService stats usually aggregated.
        # Let's try to get raw trades if possible or use stats.
        # For simplicity in this scope, we infer from stats or assume we'd query recent losing trades.
        # Since I cannot easily change JournalService, I will pass the aggregated stats and current regime.
        # Ideally, LossMinimizer would query the DB itself or we'd pass a list of recent executions.

        # Determine global regime for context
        truth_layer = MarketDataTruthLayer()
        iv_repo = IVRepository(supabase)
        iv_point_service = IVPointService(supabase)

        regime_engine = RegimeEngineV3(
            supabase_client=supabase,
            market_data=truth_layer,
            iv_repository=iv_repo,
            iv_point_service=iv_point_service,
        )
        global_snap = regime_engine.compute_global_snapshot(datetime.now())
        current_regime_str = global_snap.state.value

        # Placeholder: In a real implementation, query 'trade_executions' or 'outcomes_log' for last N losses.
        # Here we pass minimal info to satisfy the contract.
        recent_losses_summary = {
            "regime": current_regime_str,
            "win_rate": win_rate_ratio,
            "win_rate_pct": win_rate_pct,
            "total_pnl": total_pnl
        }

        policy = LossMinimizer.generate_guardrail_policy(user_id, recent_losses_summary)

        # Persist Policy to Learning Loop
        if policy:
            policy_details = {
                "policy_version": "v1",
                "regime_state": str(current_regime_str),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "loss_minimizer",
                "policy": policy,
                "inputs": {
                    "lookback_days": 7,
                    "loss_summary": recent_losses_summary,
                },
            }

            try:
                supabase.table("learning_feedback_loops").insert({
                    "user_id": user_id,
                    "outcome_type": "guardrail_policy",
                    "details_json": policy_details,
                }).execute()
                print("Persisted adaptive guardrail policy.")
            except Exception as ex:
                print(f"Failed to persist guardrail policy: {ex}")

    except Exception as e:
        print(f"Adaptive Caps Error: {e}")

    report_data = {
        "user_id": user_id,
        "week_ending": datetime.now().strftime('%Y-%m-%d'),
        "total_pnl": total_pnl,
        "win_rate": win_rate_ratio,
        "trade_count": trade_count,
        "missed_opportunities": [],
        "report_markdown": report_md.strip()
    }

    try:
        supabase.table(WEEKLY_REPORTS_TABLE).upsert(
            report_data,
            on_conflict="user_id,week_ending"
        ).execute()
        print("Upserted weekly report.")
    except Exception as e:
        print(f"Error upserting weekly report: {e}")
