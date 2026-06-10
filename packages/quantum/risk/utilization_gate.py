"""85% total-utilization entry gate — small-tier capital policy (#1044).

Replaces (when explicitly enabled) the share-of-book ``concentration_symbol``
BLOCK as the entry-blocking capital control at small tier. The share-of-book
check measures the candidate against the CURRENT book's composition — on a
one-position book any open position is 100% of risk, so the BLOCK froze all
sequential accumulation (2026-06-09: the pending XLF entry was blocked by the
open NFLX = 100% > 40%) even when the new entry would have CURED the cited
concentration. This gate is pro-forma by construction — it measures what the
book would look like WITH the candidate:

    utilization = (committed + candidate_cost) / (committed + settled_obp)

- ``committed``   = Σ net cost basis of open BROKER option positions (broker
                    truth, fresh read per evaluation — NEVER DB marks, the
                    #1022 divergence class). For the defined-risk debit book
                    this system trades, net cost basis = max loss.
- ``settled_obp`` = ``equity_state.get_alpaca_options_buying_power`` — the
                    canonical #93/PR-864 settled-funds source (60s TTL,
                    effectively live). Reused, not re-derived.

Entry allowed iff ``utilization <= RISK_MAX_UTILIZATION_PCT``.

FAIL-CLOSED: any input the gate cannot read fresh (OBP None, broker positions
fetch error, missing cost_basis, missing/invalid threshold env, underivable
candidate cost) raises :class:`UtilizationGateError` — the caller blocks that
entry and logs loud. Utilization is never computed from a DB snapshot.

Flag polarity INVERTS from the safety-control convention (#1038/#1040
default-ON): ``RISK_UTILIZATION_GATE_ENABLED`` requires an EXPLICIT ``1`` to
enforce; absent/empty/anything-else → legacy behavior (the old concentration
BLOCK), so an env regression fails SAFE to the stricter policy. Rollback =
unset the flag. The threshold ``RISK_MAX_UTILIZATION_PCT`` likewise has NO
implicit default — enabling the gate without setting it is a config error and
fails closed (a live risk control must not assume its own limit).

Known freshness caveat (documented, accepted): within a single autopilot run
staging multiple entries, the 60s OBP TTL can lag a just-accepted order's BP
deduction. The pool denominator (committed + obp) bounds the drift, and the
per-candidate allocator split already constrains same-run sizing.

Scope guard (#1044): this module adds ONE gate. The per-symbol loss envelope
(RISK_MAX_SYMBOL_LOSS), daily/weekly loss envelopes and their force-close, the
#1040 re-entry cooldown, the #1038 entry-quote guard, position stop_loss, the
H7 prefilter, the per-contract floor, the per-candidate split, and the absolute
per-symbol $ sizing cap (RiskBudgetEngine ``underlying_allocation``) are all
untouched.
"""

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

FLAG_ENV = "RISK_UTILIZATION_GATE_ENABLED"
THRESHOLD_ENV = "RISK_MAX_UTILIZATION_PCT"
SMALL_TIER_NAME = "small"


class UtilizationGateError(Exception):
    """An input the gate needs (OBP, broker positions, threshold, candidate
    cost) could not be read fresh or is invalid. FAIL-CLOSED: the caller must
    block the entry and log loud — never substitute a DB snapshot or stale
    cache."""


class EntryUtilizationBlocked(Exception):
    """Raised to REJECT an entry whose pro-forma utilization exceeds the cap
    (mirrors the SymbolCooldownActive / EntryQuoteUnpriceable shape)."""

    def __init__(
        self,
        symbol: str,
        utilization: float,
        cap: float,
        committed: float,
        obp: float,
        candidate_cost: float,
    ):
        self.symbol = symbol
        self.utilization = utilization
        self.cap = cap
        self.committed = committed
        self.obp = obp
        self.candidate_cost = candidate_cost
        super().__init__(
            f"entry_utilization_blocked: symbol={symbol} "
            f"utilization={utilization:.4f} > cap={cap:.4f} "
            f"(committed=${committed:.2f} obp=${obp:.2f} "
            f"candidate=${candidate_cost:.2f})"
        )


def is_enabled() -> bool:
    """``RISK_UTILIZATION_GATE_ENABLED`` — behavioral-change flag, polarity
    INVERTED from safety controls: only an explicit ``1`` enables. Absent /
    empty / any other value → legacy concentration BLOCK (fail SAFE to the
    stricter policy)."""
    return os.environ.get(FLAG_ENV, "").strip() == "1"


def echo_flag_state() -> None:
    """Log the parsed flag value (flags must be read-back-confirmed, not
    assumed — the INTRADAY_TARGET_PROFIT 2026-06-04 lesson). Because this is
    a strict ``== "1"`` parse, a non-empty non-"1" value (e.g. ``true``) gets
    an explicit WARNING instead of a silent no-op."""
    raw = os.environ.get(FLAG_ENV, "")
    enabled = is_enabled()
    # WARNING level deliberately: the worker surfaces WARNING+ only, and the
    # 06-10 first exercise proved INFO is invisible in Railway logs (the
    # gate's behavior was verifiable only by control-flow inference).
    logger.warning(
        "[UTILIZATION_GATE] flag %s raw=%r → enabled=%s", FLAG_ENV, raw, enabled
    )
    if raw.strip() and not enabled:
        logger.warning(
            "[UTILIZATION_GATE] %s=%r is set but does NOT parse as enabled — "
            "this strict-parse flag requires exactly '1'. Legacy concentration "
            "BLOCK remains in force.",
            FLAG_ENV, raw,
        )


def max_utilization_pct() -> float:
    """The cap from ``RISK_MAX_UTILIZATION_PCT``. NO implicit default — a
    missing/invalid threshold while the gate is enabled is a config error and
    raises (fail-closed)."""
    raw = os.environ.get(THRESHOLD_ENV, "").strip()
    if not raw:
        raise UtilizationGateError(
            f"{THRESHOLD_ENV} is unset/empty while the utilization gate is "
            f"enabled — fail-closed (no implicit threshold for a live risk "
            f"control)"
        )
    try:
        val = float(raw)
    except ValueError as e:
        raise UtilizationGateError(
            f"{THRESHOLD_ENV}={raw!r} is not a float — fail-closed"
        ) from e
    if not (0.0 < val <= 1.0):
        raise UtilizationGateError(
            f"{THRESHOLD_ENV}={val} outside (0, 1] — fail-closed"
        )
    return val


# ── seams (monkeypatch targets in tests) ────────────────────────────────────

def _get_alpaca():
    from packages.quantum.brokers.alpaca_client import get_alpaca_client
    return get_alpaca_client()


def _get_obp(user_id: str, supabase: Any = None) -> Optional[float]:
    from packages.quantum.services import equity_state
    return equity_state.get_alpaca_options_buying_power(user_id, supabase=supabase)


# ── inputs ───────────────────────────────────────────────────────────────────

def fetch_committed_capital() -> float:
    """Σ net cost basis of open BROKER option positions, in dollars — the
    capital already committed to the defined-risk book (= max loss for debit
    structures). Fresh broker read every call; never DB marks.

    A net-credit book sums negative → clamped to 0 with a loud warning
    (utilization then understates committed risk for credit structures, but
    the denominator's OBP already reflects the broker's margin hold for short
    spreads). Raises :class:`UtilizationGateError` on any read failure.
    """
    try:
        alpaca = _get_alpaca()
        if alpaca is None:
            raise UtilizationGateError(
                "alpaca client unavailable (no credentials) — fail-closed"
            )
        positions = alpaca.get_positions()
    except UtilizationGateError:
        raise
    except Exception as e:
        raise UtilizationGateError(
            f"broker positions read failed: {type(e).__name__}: {e}"
        ) from e

    committed = 0.0
    for p in positions:
        if (p.get("asset_class") or "") != "us_option":
            continue
        cb = p.get("cost_basis")
        if cb is None:
            # None-preserving wrapper field (Anti-pattern 8): absence means
            # the broker didn't give us a number — never coerce to 0.
            raise UtilizationGateError(
                f"cost_basis missing on broker position "
                f"{p.get('symbol_alpaca') or p.get('symbol')} — fail-closed"
            )
        committed += float(cb)

    if committed < 0:
        logger.warning(
            "[UTILIZATION_GATE] net broker option cost basis is negative "
            "($%.2f — net-credit book); clamping committed to $0. Utilization "
            "will understate committed risk for credit structures.",
            committed,
        )
        committed = 0.0
    return committed


def candidate_cost_usd(suggestion: Dict[str, Any]) -> float:
    """The candidate's entry debit in dollars: ``limit_price × contracts ×
    100`` from the suggestion's ``order_json``. Raises
    :class:`UtilizationGateError` when not derivable as a positive number —
    fail-closed (a candidate we can't price must not slip the gate)."""
    oj = suggestion.get("order_json") or {}
    try:
        limit_price = float(oj.get("limit_price") or 0)
        contracts = float(oj.get("contracts") or 0)
    except (TypeError, ValueError):
        limit_price, contracts = 0.0, 0.0
    cost = limit_price * contracts * 100.0
    if cost <= 0:
        raise UtilizationGateError(
            f"candidate cost not derivable from order_json "
            f"(limit_price={oj.get('limit_price')!r}, "
            f"contracts={oj.get('contracts')!r}) — fail-closed"
        )
    return cost


def tier_is_small(user_id: str, supabase: Any = None) -> bool:
    """True iff ``get_tier(settled OBP)`` resolves to the small tier — the
    scope of the #1044 policy. OBP unreadable → False: the BLOCK→WARN
    demotion does NOT apply and the legacy (stricter) concentration BLOCK is
    retained — fail safe."""
    obp = _get_obp(user_id, supabase=supabase)
    if obp is None:
        logger.warning(
            "[UTILIZATION_GATE] OBP unreadable for tier resolution — "
            "demotion NOT applied (legacy concentration BLOCK retained)"
        )
        return False
    from packages.quantum.services.analytics.small_account_compounder import (
        SmallAccountCompounder,
    )
    return SmallAccountCompounder.get_tier(obp).name == SMALL_TIER_NAME


# ── the gate ────────────────────────────────────────────────────────────────

def evaluate_entry(
    user_id: str,
    symbol: str,
    candidate_cost: float,
    supabase: Any = None,
) -> Dict[str, Any]:
    """Compute pro-forma utilization for one candidate entry and LOG the
    evaluation (committed, OBP, candidate, utilization %, decision — every
    call, both decisions).

    Returns the evaluation dict when allowed. Raises
    :class:`EntryUtilizationBlocked` when ``utilization > cap`` and
    :class:`UtilizationGateError` when any input is unreadable (fail-closed).
    """
    cap = max_utilization_pct()  # config error surfaces before broker IO
    committed = fetch_committed_capital()
    obp = _get_obp(user_id, supabase=supabase)
    if obp is None:
        raise UtilizationGateError(
            "settled options_buying_power unavailable — fail-closed "
            "(never a DB snapshot)"
        )
    if candidate_cost is None or candidate_cost <= 0:
        raise UtilizationGateError(
            f"candidate_cost={candidate_cost!r} invalid — fail-closed"
        )
    pool = committed + obp
    if pool <= 0:
        raise UtilizationGateError(
            f"capital pool ${pool:.2f} <= 0 — fail-closed"
        )

    utilization = (committed + candidate_cost) / pool
    allowed = utilization <= cap
    # WARNING level deliberately — see echo_flag_state; "log every evaluation"
    # must mean observable, not muted at the worker's log level.
    logger.warning(
        "[UTILIZATION_GATE] symbol=%s committed=$%.2f obp=$%.2f "
        "candidate=$%.2f pool=$%.2f utilization=%.4f (%.1f%%) cap=%.2f "
        "decision=%s",
        symbol, committed, obp, candidate_cost, pool, utilization,
        utilization * 100.0, cap, "ALLOW" if allowed else "BLOCK",
    )
    if not allowed:
        raise EntryUtilizationBlocked(
            symbol, utilization, cap, committed, obp, candidate_cost
        )
    return {
        "symbol": symbol,
        "committed": committed,
        "obp": obp,
        "candidate_cost": candidate_cost,
        "pool": pool,
        "utilization": utilization,
        "cap": cap,
        "allowed": True,
    }
