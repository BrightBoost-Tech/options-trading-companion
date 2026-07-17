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

Identity vs permission (2026-07-16 integration): strategy IDENTITY —
normalization, the canonical id vocabulary, and the tradable/no-trade
split — is owned by ``analytics/strategy_identity.py`` (the single
crosswalk). This module owns exactly ONE thing on top of it: the
BROKER-PERMISSION capability dimension (canonical id → minimum effective
level). It keeps NO normalization of its own and NO second copy of the
selector registry; the tradable domain is ``strategy_identity.TRADABLE_IDS``
and the import-time drift lock below fails LOUDLY if the two ever diverge.

Scope: OPEN orders only. CLOSES (position_id set) are exempt by contract —
a permission change must never trap an existing position (the same
trapped-is-worse-than-blocked asymmetry as #1038 quote validation). Callers
must not invoke this for closes; the ``is_open_order`` early-return is a
defensive double guard, mirroring _apply_entry_roundtrip_gate's
position_id check.

Fail-CLOSED (H9): a level we cannot read/prove on an OPEN order in a
live-entry context is a permission we do not have — typed rejection, never
permit-by-default. Unknown strategy ids get the CONSERVATIVE L3 requirement.
HOLD/CASH are no-trade VERDICTS, not option structures — they carry no
level requirement and must never be treated as submitted structures.
"""

import logging
import time
from typing import Any, Dict, Optional, Tuple

from packages.quantum.analytics.strategy_identity import (
    TRADABLE_IDS,
    StructureClass,
    normalize_strategy_id,  # canonical — re-exported for existing importers
    resolve_strategy_identity,
)

logger = logging.getLogger(__name__)


# Minimum EFFECTIVE options trading level per CANONICAL strategy id (the
# ``strategy_identity.normalize_strategy_id`` key form). This map is the
# BROKER-PERMISSION capability dimension — deliberately DISTINCT from
# strategy_identity's payoff-identity dimension (identity source =
# strategy_identity; permission map = here). It is NOT a second selector
# registry: the tradable domain is strategy_identity.TRADABLE_IDS, and
# ``_assert_permission_map_locked`` below fails the IMPORT if a
# selector-tradable id is ever missing from this map (no silent omission)
# or an unexplained key creeps in (no silent second registry).
STRATEGY_MIN_LEVEL: Dict[str, int] = {
    # Tradable domain (== strategy_identity.TRADABLE_IDS today) — all
    # multi-leg spreads → L3:
    "long_call_debit_spread": 3,
    "long_put_debit_spread": 3,
    "short_put_credit_spread": 3,
    "short_call_credit_spread": 3,
    "iron_condor": 3,
    # FUTURE-CAPABILITY ids (declared in FUTURE_CAPABILITY_IDS; not in the
    # selector's tradable set today — mapped so a future add inherits the
    # correct requirement instead of the conservative default):
    # single-leg long premium → L2:
    "long_call": 2,
    "long_put": 2,
    # L1 income structures:
    "covered_call": 1,
    "cash_secured_put": 1,
}

# Ids the permission map carries AHEAD of the selector: not tradable today,
# explicitly declared so the drift lock can tell "future capability" apart
# from "typo/stale key". HOLD/CASH are deliberately NOT here and NOT in the
# map — they are no-trade verdicts (strategy_identity NO_TRADE_IDS), never
# submitted structures.
FUTURE_CAPABILITY_IDS = frozenset(
    {"long_call", "long_put", "covered_call", "cash_secured_put"}
)

# Unknown strategy → CONSERVATIVE requirement, never permit-by-default: an
# id this map has never seen could be any structure, including multi-leg.
UNKNOWN_STRATEGY_MIN_LEVEL = 3


def _permission_map_drift(
    tradable_ids=None, permission_map=None, future_ids=None,
) -> Tuple[frozenset, frozenset]:
    """Compute both drift directions between the canonical tradable set and
    the permission map. Parameters exist for tests only; production uses the
    module-level values.

    Returns (missing, unexplained):
    - missing: selector-tradable canonical ids with NO permission mapping —
      a newly added selector strategy silently omitted from this map.
    - unexplained: permission-map keys that are neither tradable nor
      declared future-capability — a typo, a stale entry, or a second
      registry growing in the dark.
    """
    tids = frozenset(TRADABLE_IDS if tradable_ids is None else tradable_ids)
    pmap = frozenset(
        STRATEGY_MIN_LEVEL if permission_map is None else permission_map
    )
    fids = frozenset(
        FUTURE_CAPABILITY_IDS if future_ids is None else future_ids
    )
    missing = tids - pmap
    unexplained = pmap - tids - fids
    return missing, unexplained


def _assert_permission_map_locked(
    tradable_ids=None, permission_map=None, future_ids=None,
) -> None:
    """DRIFT LOCK (import-time): the permission map must cover EVERY
    canonical tradable id from strategy_identity, and must contain nothing
    that is neither tradable nor a declared future capability. Raises
    RuntimeError — a drifted map is a wrong permission model and must fail
    the import (CI trips on the same PR that adds the selector strategy),
    never silently fall through to the conservative default."""
    missing, unexplained = _permission_map_drift(
        tradable_ids, permission_map, future_ids
    )
    if missing or unexplained:
        raise RuntimeError(
            "[OPTIONS_LEVEL] DRIFT LOCK: STRATEGY_MIN_LEVEL diverged from "
            "strategy_identity's canonical tradable set. "
            f"missing_tradable_ids={sorted(missing)} "
            f"unexplained_keys={sorted(unexplained)} — every selector-"
            "tradable id needs an explicit minimum-level entry, and every "
            "extra key must be declared in FUTURE_CAPABILITY_IDS."
        )


_assert_permission_map_locked()


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


def is_no_trade_verdict(strategy_id: Any) -> bool:
    """True when ``strategy_id`` resolves to a canonical NO_TRADE verdict
    (HOLD/CASH per strategy_identity). A no-trade verdict is not an option
    structure — it has no broker-permission requirement and must never be
    staged/submitted as one."""
    identity = resolve_strategy_identity(str(strategy_id or ""))
    return identity is not None and identity.structure is StructureClass.NO_TRADE


def required_options_level(strategy_id: Any) -> Optional[int]:
    """Minimum EFFECTIVE level for ``strategy_id``, keyed by the CANONICAL
    id (strategy_identity normalization). Returns None for HOLD/CASH — a
    no-trade verdict has no requirement because there is nothing to submit.
    Unknown/missing ids get the conservative L3 requirement — never
    permit-by-default."""
    if is_no_trade_verdict(strategy_id):
        logger.warning(
            "[OPTIONS_LEVEL] no-trade verdict %r is not an option structure "
            "— no level requirement (it must never be staged or submitted)",
            strategy_id,
        )
        return None
    key = normalize_strategy_id(strategy_id)
    if key in STRATEGY_MIN_LEVEL:
        return STRATEGY_MIN_LEVEL[key]
    logger.warning(
        "[OPTIONS_LEVEL] unknown strategy id %r (normalized %r) — applying "
        "the conservative L%d REQUIREMENT (never permit-by-default)",
        strategy_id, key, UNKNOWN_STRATEGY_MIN_LEVEL,
    )
    return UNKNOWN_STRATEGY_MIN_LEVEL


# ── 60s account-read TTL cache ───────────────────────────────────────
# Mirrors equity_state.py's accepted 60s account-read pattern
# (_ALPACA_STATE_TTL_SECONDS = 60): multiple live candidates staged in one
# executor cycle reuse ONE broker account read instead of one GET each.
# Options levels change ~never intraday (a broker-side downgrade is a rare
# margin/compliance event); 60 seconds of staleness is far inside the
# trading cadence (the executor runs once per day, the monitor q15min).
# This is deliberately NOT a process-lifetime permission cache — every
# entry expires after 60s and the next stage call re-reads the broker.
# Bypass-safe: a read FAILURE (exception) or a None/non-dict payload is
# NEVER cached — the next call always re-reads, and the caller fails
# closed on the bad read (H9).
ACCOUNT_LEVEL_TTL_SECONDS = 60.0

# id(client) → (client, monotonic_ts, account_dict). The strong client ref
# both validates identity (``is`` check) and prevents id() reuse while an
# entry lives. Production holds ONE entry (get_alpaca_client() singleton).
_ACCOUNT_CACHE: Dict[int, Tuple[Any, float, Dict[str, Any]]] = {}


def get_account_with_ttl(client: Any) -> Optional[Dict[str, Any]]:
    """Return ``client.get_account()`` through a 60s TTL cache keyed per
    client identity.

    - Fresh cache hit (same client object, < ACCOUNT_LEVEL_TTL_SECONDS old)
      → the cached dict, zero broker calls.
    - Miss/expired → one real read; a successful dict payload is cached.
    - Exceptions propagate uncached; a None/non-dict payload returns
      uncached — failure is never served from (or into) the cache.
    """
    key = id(client)
    entry = _ACCOUNT_CACHE.get(key)
    now = time.monotonic()
    if entry is not None:
        cached_client, ts, account = entry
        if cached_client is client and (now - ts) < ACCOUNT_LEVEL_TTL_SECONDS:
            return account
    account = client.get_account()  # exceptions propagate — NEVER cached
    if not isinstance(account, dict):
        # None / malformed payload: never cached; caller fails closed and
        # every subsequent call re-reads (bypass-safe).
        return account
    _ACCOUNT_CACHE[key] = (client, now, account)
    return account


def reset_account_cache() -> None:
    """Drop all cached account reads (tests; never needed in production —
    entries self-expire after ACCOUNT_LEVEL_TTL_SECONDS)."""
    _ACCOUNT_CACHE.clear()


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

    HOLD/CASH (canonical no-trade verdicts): returns None without
    evaluating the account — there is no option structure to permission
    and nothing may be submitted for them (double guard; the wiring
    additionally never performs an account read for a no-trade verdict).
    """
    if not is_open_order:
        return None  # CLOSE — exempt; never evaluated

    required = required_options_level(strategy_id)
    if required is None:
        # HOLD/CASH — a no-trade verdict reached the level check. Not an
        # option structure: no requirement, nothing to submit, account
        # never consulted. required_options_level already logged loudly.
        return None
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
