"""Options-trading-level ENTRY preflight (2026-07-16).

WHY THIS EXISTS: the AlpacaClient.get_account() curated dict dropped the
account's options_approved_level / options_trading_level fields entirely, so
NOTHING in the pipeline could ever know whether the broker would permit the
structure being staged. A level downgrade (broker-side throttle, margin
event, or a future account migration) would surface only as an opaque broker
rejection — retried by submit_and_track, then parked needs_manual_review.
This module fails the ENTRY early and terminally at the stage seam instead.

Alpaca level semantics (broker docs):
  L1 — covered calls / cash-secured puts
  L2 — L1 + long calls / long puts
  L3 — L2 + spreads, straddles, condors (multi-leg)

Permission basis: the EFFECTIVE ``options_trading_level`` — the level the
broker will actually accept orders at right now. ``options_approved_level``
(the max the account was approved for) is carried for DIAGNOSTICS ONLY and
never grants permission.

Scope: OPEN orders only. CLOSES (position_id set) are exempt by contract —
a permission change must never trap an existing position (the same
trapped-is-worse-than-blocked asymmetry as #1038 quote validation). Callers
must not invoke this for closes; the ``is_open_order`` early-return is a
defensive double guard, mirroring _apply_entry_roundtrip_gate's
position_id check.

Fail-CLOSED (H9): a level we cannot read/prove on an OPEN order in a
live-entry context is a permission we do not have — typed rejection, never
permit-by-default. Unknown strategy ids get the CONSERVATIVE L3 requirement.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Minimum EFFECTIVE options trading level per strategy id. Keys are
# EXACT-NORMALIZED (lowercase, spaces/hyphens → underscores — the same
# normalization strategy_registry.infer_strategy_key_from_suggestion
# applies); the selector (analytics/strategy_selector.py) emits these ids
# UPPERCASE and ``normalize_strategy_id`` folds them here.
STRATEGY_MIN_LEVEL: Dict[str, int] = {
    # Selector-emitted structures — all multi-leg spreads → L3:
    "long_call_debit_spread": 3,
    "long_put_debit_spread": 3,
    "short_put_credit_spread": 3,
    "short_call_credit_spread": 3,
    "iron_condor": 3,
    # Single-leg long premium (NOT selector-reachable today) → L2:
    "long_call": 2,
    "long_put": 2,
    # L1 income structures (unsupported today; mapped so a future add
    # inherits the correct requirement instead of the conservative default):
    "covered_call": 1,
    "cash_secured_put": 1,
}

# Unknown strategy → CONSERVATIVE requirement, never permit-by-default: an
# id this map has never seen could be any structure, including multi-leg.
UNKNOWN_STRATEGY_MIN_LEVEL = 3


class EntryOptionsLevelError(Exception):
    """Base for OPEN-order options-level preflight rejections.

    Raised pre-insert/pre-broker-submit by the stage seam — the same clean
    no-order-row reject shape as EntryQuoteUnpriceable (#1038) and
    EntryRoundtripCostExceedsEV (#1101). The autopilot loops' existing
    handlers count it as not-executed; the wiring stamps
    ``trade_suggestions.blocked_reason`` from the class attribute below.
    """

    blocked_reason = "entry_options_level_error"


class EntryOptionsLevelUnavailable(EntryOptionsLevelError):
    """EFFECTIVE options_trading_level is missing/None/unreadable on an
    OPEN order in a live-entry context → fail CLOSED (H9: a permission we
    cannot prove is a permission we do not have)."""

    blocked_reason = "entry_options_level_unavailable"

    def __init__(self, strategy_id, required_level, approved_level,
                 detail: str = ""):
        self.strategy_id = strategy_id
        self.required_level = required_level
        self.approved_level = approved_level
        super().__init__(
            f"entry_options_level_unavailable: strategy={strategy_id!r} "
            f"required_level={required_level} effective_level=None "
            f"approved_level={approved_level}{detail}"
        )


class EntryOptionsLevelInsufficient(EntryOptionsLevelError):
    """EFFECTIVE options_trading_level is below the strategy's minimum —
    the broker would reject the order; fail it here, terminally, before any
    order row exists or a broker submit is attempted."""

    blocked_reason = "entry_options_level_insufficient"

    def __init__(self, strategy_id, required_level, effective_level,
                 approved_level):
        self.strategy_id = strategy_id
        self.required_level = required_level
        self.effective_level = effective_level
        self.approved_level = approved_level
        super().__init__(
            f"entry_options_level_insufficient: strategy={strategy_id!r} "
            f"required_level={required_level} "
            f"effective_level={effective_level} "
            f"approved_level={approved_level} (diagnostic only)"
        )


def normalize_strategy_id(strategy_id: Any) -> str:
    """Fold a strategy id to the map's key form — mirrors
    strategy_registry.infer_strategy_key_from_suggestion's normalization
    (lowercase, strip, spaces/hyphens → underscores)."""
    return (
        str(strategy_id or "")
        .lower()
        .strip()
        .replace(" ", "_")
        .replace("-", "_")
    )


def required_options_level(strategy_id: Any) -> int:
    """Minimum EFFECTIVE level for ``strategy_id``. Unknown/missing ids get
    the conservative L3 requirement — never permit-by-default."""
    key = normalize_strategy_id(strategy_id)
    if key in STRATEGY_MIN_LEVEL:
        return STRATEGY_MIN_LEVEL[key]
    logger.warning(
        "[OPTIONS_LEVEL] unknown strategy id %r (normalized %r) — applying "
        "the conservative L%d REQUIREMENT (never permit-by-default)",
        strategy_id, key, UNKNOWN_STRATEGY_MIN_LEVEL,
    )
    return UNKNOWN_STRATEGY_MIN_LEVEL


def check_options_level(
    strategy_id: Any,
    is_open_order: bool,
    account: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Preflight an order against the account's options trading level.

    Returns a diagnostics dict on ALLOW; raises a typed rejection
    (EntryOptionsLevelUnavailable / EntryOptionsLevelInsufficient) on
    reject. ``account`` is the AlpacaClient.get_account() curated dict.

    Closes: callers must not invoke this for closes (position_id set);
    ``is_open_order=False`` returns None without evaluating anything — the
    defensive double guard.
    """
    if not is_open_order:
        return None  # CLOSE — exempt; never evaluated

    required = required_options_level(strategy_id)
    acct = account or {}
    effective = acct.get("options_trading_level")
    approved = acct.get("options_approved_level")  # diagnostics ONLY

    if effective is None:
        logger.error(
            "[OPTIONS_LEVEL] EFFECTIVE options_trading_level is "
            "missing/None on an OPEN order — FAIL CLOSED (H9: cannot prove "
            "permission). strategy=%r required_level=%d approved_level=%r",
            strategy_id, required, approved,
        )
        raise EntryOptionsLevelUnavailable(strategy_id, required, approved)

    try:
        effective_int = int(effective)
    except (TypeError, ValueError):
        logger.error(
            "[OPTIONS_LEVEL] EFFECTIVE options_trading_level malformed "
            "(non-int-coercible: %r) on an OPEN order — FAIL CLOSED. "
            "strategy=%r required_level=%d approved_level=%r",
            effective, strategy_id, required, approved,
        )
        raise EntryOptionsLevelUnavailable(
            strategy_id, required, approved,
            detail=f" (malformed effective={effective!r})",
        )

    if effective_int < required:
        logger.error(
            "[OPTIONS_LEVEL] entry REJECTED: strategy=%r requires L%d but "
            "the account's EFFECTIVE options_trading_level is %d "
            "(approved_level=%r, diagnostic only) — terminal at the stage "
            "seam, no order row, no broker submit",
            strategy_id, required, effective_int, approved,
        )
        raise EntryOptionsLevelInsufficient(
            strategy_id, required, effective_int, approved,
        )

    return {
        "strategy_id": strategy_id,
        "normalized_strategy_id": normalize_strategy_id(strategy_id),
        "required_level": required,
        "effective_level": effective_int,
        "approved_level": approved,
    }
