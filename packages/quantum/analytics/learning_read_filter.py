"""Historical-mode learning quarantine — fail-closed ``outcome_type`` allowlist
for live-affecting reads of ``learning_feedback_loops``.

The table mixes real per-trade closes (``outcome_type='trade_closed'``) with
synthetic / aggregate rows written by the historical simulator and by a retired
writer: ``historical_win`` / ``historical_loss`` (per-trade, carry
``pnl_realized``) and ``aggregate`` (``strategy='historical_cycle'``). A
live-affecting learning reader (conviction multipliers, strategy autotune) that
ingests those rows would train selection / threshold mutation on zero-spread
fantasy outcomes.

This module is the **single source of truth** + **enforcement point** for the
allowlist. It mirrors exactly the SQL filter already embedded in the
``learning_trade_outcomes_v3`` view
(``WHERE outcome_type IN ('trade_closed','individual_trade')``). It is a
**fail-closed allowlist, not an ``!= 'historical'`` denylist** — any unknown or
future synthetic ``outcome_type`` is excluded by default.

Kill switch: ``LEARNING_HISTORICAL_QUARANTINE_ENABLED``, **default ON**
(empty / unset → ON; only an explicit ``0/false/no/off`` disables — the
empty-string-no-op lesson, #1038 / #1040).

Two entry points:
- :func:`partition_trusted_rows` — for fetch-then-iterate readers. Filters an
  already-fetched row list in Python and **logs the excluded-row count** (the
  observability requirement). Used by conviction + autotune.
- :func:`apply_trusted_outcome_filter` — for count-only / efficiency-critical
  reads: chains ``.in_("outcome_type", ...)`` onto a supabase-py query builder.

A complementary AST backstop (``tests/test_learning_quarantine_gate.py``) fails
CI if a future live-affecting reader pulls ``learning_feedback_loops`` data
without routing through this module (helper = enforcement, scan = backstop).
"""

import logging
import os
from typing import Any, FrozenSet, List

logger = logging.getLogger(__name__)

# Single source of truth — identical to learning_trade_outcomes_v3's WHERE clause.
# View-grade allowlist: the set used by readers that mirror the view (conviction
# legacy multipliers, calibration). Conviction's legacy path aggregates on
# total_trades, which per-trade rows leave null, so this set is zero-delta there.
TRUSTED_LEARNING_OUTCOME_TYPES: FrozenSet[str] = frozenset(
    {"trade_closed", "individual_trade"}
)

# Realized-per-trade allowlist: the view-grade set PLUS the live transaction
# ingest's win/loss/breakeven convention (learning_ingest._create_outcome_record
# writes these for live sells). A reader that consumes per-trade realized pnl
# (strategy_autotune, via classify_outcome) must keep these — filtering to the
# narrower view-grade set would silently drop REAL live outcomes once live closes
# ingest. Still fail-closed: historical_win/historical_loss/aggregate and any
# unknown/future synthetic type are excluded (distinct strings from win/loss).
REALIZED_TRADE_OUTCOME_TYPES: FrozenSet[str] = TRUSTED_LEARNING_OUTCOME_TYPES | frozenset(
    {"win", "loss", "breakeven"}
)

FLAG_ENV = "LEARNING_HISTORICAL_QUARANTINE_ENABLED"


def is_quarantine_enabled() -> bool:
    """Kill switch — **DEFAULT ON**. Empty / unset → ON (NOT off; the
    empty-string-no-op lesson, INTRADAY_TARGET_PROFIT 2026-06-04 / #1038).
    Only an explicit ``0/false/no/off`` disables."""
    raw = os.environ.get(FLAG_ENV, "")
    if not raw.strip():
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def echo_flag_state() -> None:
    """Log the parsed kill-switch value once (pays down the SILENT-FLAG-PARSE
    backlog — flags must be read-back-confirmed, not assumed)."""
    raw = os.environ.get(FLAG_ENV, "")
    logger.info(
        "[LEARNING_QUARANTINE] flag %s raw=%r → enabled=%s",
        FLAG_ENV, raw, is_quarantine_enabled(),
    )


def _outcome_type(row: Any) -> Any:
    return row.get("outcome_type") if isinstance(row, dict) else None


def partition_trusted_rows(
    rows: Any, *, reader: str, allowed: FrozenSet[str] = TRUSTED_LEARNING_OUTCOME_TYPES
) -> List[Any]:
    """Return only the rows whose ``outcome_type`` is in ``allowed``, logging the
    **excluded-row count** for observability.

    ``allowed`` defaults to the view-grade :data:`TRUSTED_LEARNING_OUTCOME_TYPES`
    (conviction). A realized-pnl reader (autotune) passes
    :data:`REALIZED_TRADE_OUTCOME_TYPES`.

    Fail-closed: an unknown / new ``outcome_type`` (or a row without one) is
    excluded by default. No-op (returns the rows unchanged, with a loud
    warning) ONLY when the kill switch is explicitly OFF.

    ``reader`` is a short caller label for the observability log line.
    """
    rows = list(rows or [])
    if not is_quarantine_enabled():
        logger.warning(
            "[LEARNING_QUARANTINE] %s DISABLED — %s consuming %d UNFILTERED "
            "learning_feedback_loops row(s) (historical/synthetic rows may flow "
            "into learning)", FLAG_ENV, reader, len(rows),
        )
        return rows

    trusted = [r for r in rows if _outcome_type(r) in allowed]
    excluded = len(rows) - len(trusted)
    if excluded:
        logger.info(
            "[LEARNING_QUARANTINE] %s: excluded %d/%d learning_feedback_loops "
            "row(s) outside the trusted outcome_type allowlist %s",
            reader, excluded, len(rows), sorted(allowed),
        )
    return trusted


def apply_trusted_outcome_filter(query: Any) -> Any:
    """Chain the fail-closed ``outcome_type`` allowlist onto a supabase-py query
    builder for ``learning_feedback_loops``. Returns the query with
    ``.in_("outcome_type", TRUSTED_LEARNING_OUTCOME_TYPES)`` applied.

    Enforcement primitive for count-only reads. Fetch-then-iterate callers
    should prefer :func:`partition_trusted_rows` so the excluded-row count is
    observable. No-op (returns the query unchanged, with a loud warning) ONLY
    when the kill switch is explicitly OFF.
    """
    if not is_quarantine_enabled():
        logger.warning(
            "[LEARNING_QUARANTINE] %s DISABLED — query NOT filtered by the "
            "outcome_type allowlist", FLAG_ENV,
        )
        return query
    return query.in_("outcome_type", sorted(TRUSTED_LEARNING_OUTCOME_TYPES))
