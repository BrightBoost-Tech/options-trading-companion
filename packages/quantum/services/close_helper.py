"""
Canonical close-position writer. PR #6 Commit 3.

The shared close helper that all 4 close handlers (reconciler, exit
evaluator, paper_endpoints orphan repair, manual endpoint) invoke to
atomically write a paper_positions row to status='closed'. Together
with `compute_realized_pl` in close_math.py, this pair eliminates
the pre-PR-#6 class of close-path bug where each handler had its
own math + write logic that could subtly diverge.

Scope — paper_positions ONLY
The helper writes exactly one row atomically: status='closed',
realized_pl, close_reason, fill_source, closed_at, quantity=0,
updated_at=now(). It does NOT write paper_orders, cash_balance,
ledger entries, learning_feedback_loops, or any other downstream
table. Callers orchestrate those writes with their own idempotent
patterns. Rationale per the Gap D decision: each downstream write
has distinct concerns and ownership; bundling them here makes the
helper a mini-transaction-manager with implicit ordering. Linear
caller orchestration is verbose but auditable.

Idempotency contract
Calling close_position_shared twice on the same position_id raises
PositionAlreadyClosed. NOT a silent no-op. Close is a one-way
operation — a second call means upstream dedup failed, a retry
looped incorrectly, or two handlers raced. Callers must write a
severity='critical' risk_alert on this exception and NOT retry.

Race safety
Uses conditional UPDATE (WHERE id=? AND status IS DISTINCT FROM
'closed') rather than SELECT FOR UPDATE + UPDATE. The conditional
filter is atomic at the Postgres MVCC level — two concurrent
close attempts get serialized; only one finds status != 'closed'
and writes; the other's UPDATE affects zero rows. The helper then
does a diagnostic SELECT to distinguish "already closed" from
"doesn't exist" and raises the appropriate exception.

(Supabase PostgREST does not support FOR UPDATE directly; achieving
the user's originally-spec'd "FOR UPDATE + check + UPDATE" would
require a custom Postgres function / migration. Conditional UPDATE
provides the same serialization guarantee via compare-and-swap with
MVCC, in a single round-trip for the happy path.)

Callers' obligations
    1. Call compute_realized_pl(...) inside try/except PartialFillDetected.
       On that exception, write a severity='critical' risk_alert and
       return — do NOT invoke this helper.
    2. On success, call close_position_shared(...) inside try/except
       PositionAlreadyClosed.
    3. On PositionAlreadyClosed: caller writes a severity='critical'
       risk_alert with duplicate-close-attempt context (new fill_source
       attempted, existing close_reason on row), does NOT retry.
    4. Callers then perform their own downstream writes (paper_orders,
       cash_balance, ledger) idempotently.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional


# Enum values mirror the Phase 1 migration CHECK constraints verbatim
# (20260423000001_expand_close_reason_enum_phase1.sql). The Python
# tuples are the source of truth for callers; the DB CHECKs are the
# source of truth for what's accepted on the wire. They MUST match.
#
# Phase 2 (20260424000001_contract_close_reason_enum_phase2.sql) drops
# the 5 legacy close_reason values from the DB CHECK. These Python
# constants reflect the post-Phase-2 strict enum — callers writing
# through this helper never emit legacy values.

CloseReason = Literal[
    "target_profit_hit",
    "stop_loss_hit",
    "dte_threshold",
    "expiration_day",
    "manual_close_user_initiated",
    "alpaca_fill_reconciler_sign_corrected",
    "alpaca_fill_reconciler_standard",
    "envelope_force_close",
    "orphan_fill_repair",
]

_VALID_CLOSE_REASONS = frozenset([
    "target_profit_hit",
    "stop_loss_hit",
    "dte_threshold",
    "expiration_day",
    "manual_close_user_initiated",
    "alpaca_fill_reconciler_sign_corrected",
    "alpaca_fill_reconciler_standard",
    "envelope_force_close",
    "orphan_fill_repair",
])

FillSource = Literal[
    "alpaca_fill_reconciler",
    "orphan_fill_repair",
    "exit_evaluator",
    "manual_endpoint",
]

_VALID_FILL_SOURCES = frozenset([
    "alpaca_fill_reconciler",
    "orphan_fill_repair",
    "exit_evaluator",
    "manual_endpoint",
])


class PositionAlreadyClosed(Exception):
    """Raised when close_position_shared is invoked on a position
    already at status='closed'.

    Indicates upstream dedup failure or race condition between
    handlers. Helper raises loudly rather than silently no-op'ing;
    close is one-way and a duplicate attempt is a symptom of
    something broken further up the call chain.

    Exception args carry diagnostic context so the caller's
    risk_alert can surface the conflict:
        position_id        — the position that rejected the close
        new_fill_source    — the fill_source the caller tried to apply
        existing_close_reason / existing_fill_source / existing_closed_at
                           — the values already on the row
    """

    def __init__(
        self,
        position_id: str,
        new_fill_source: str,
        existing_close_reason: Optional[str] = None,
        existing_fill_source: Optional[str] = None,
        existing_closed_at: Optional[str] = None,
    ):
        self.position_id = position_id
        self.new_fill_source = new_fill_source
        self.existing_close_reason = existing_close_reason
        self.existing_fill_source = existing_fill_source
        self.existing_closed_at = existing_closed_at
        super().__init__(
            f"Position {position_id} is already closed. "
            f"Attempted fill_source={new_fill_source!r}; "
            f"existing close_reason={existing_close_reason!r}, "
            f"existing fill_source={existing_fill_source!r}, "
            f"existing closed_at={existing_closed_at!r}. "
            f"Upstream dedup failure or race condition suspected."
        )


class PositionNotFound(Exception):
    """Raised when close_position_shared targets a position_id that
    has no row in paper_positions. Distinct from
    PositionAlreadyClosed — the latter means the row exists but is
    closed, while this means the row does not exist at all."""


def close_position_shared(
    supabase: Any,
    position_id: str,
    realized_pl: Decimal,
    close_reason: CloseReason,
    fill_source: FillSource,
    closed_at: Optional[datetime] = None,
) -> None:
    """Atomically close a paper_positions row.

    Args:
        supabase: Supabase client (admin or user scope — caller
            decides the permissions context).
        position_id: UUID of the row to close.
        realized_pl: Must be a non-None Decimal. Callers compute via
            compute_realized_pl() before invoking this helper. The
            helper does NOT compute realized_pl internally (A2
            decision from PR #6 scope discussion).
        close_reason: One of the 9 enum values. Must match the
            close_path_required DB CHECK exactly.
        fill_source: One of the 4 enum values. Must match the
            check_fill_source_enum DB CHECK exactly.
        closed_at: Timestamp of the close. Defaults to utcnow().
            Callers may override with the actual Alpaca filled_at
            if they're reconciling a past broker fill.

    Raises:
        PartialFillDetected: NOT raised by this helper — callers
            must catch this from compute_realized_pl BEFORE invoking
            this helper. If a caller somehow propagates a partial
            fill's realized_pl=None here, it's caught as a value
            error below.
        ValueError: If realized_pl is None, close_reason is not in
            the 9-value enum, or fill_source is not in the 4-value
            enum. Defense in depth — the DB CHECKs would reject
            invalid values too, but failing earlier gives better
            stack traces.
        PositionAlreadyClosed: Position exists but status='closed'
            already. Caller must write severity='critical'
            risk_alert and NOT retry.
        PositionNotFound: Position row does not exist.

    Callers MUST NOT:
        - Retry on PositionAlreadyClosed (close is one-way)
        - Swallow the exception silently
        - Invoke this helper on partial-filled close orders
    """
    # Validate inputs (defense in depth vs DB CHECKs).
    if realized_pl is None:
        raise ValueError(
            f"close_position_shared: realized_pl is required (got "
            f"None). Position {position_id} will not be closed. "
            f"Callers must invoke compute_realized_pl() first and "
            f"pass the returned Decimal."
        )
    if not isinstance(realized_pl, Decimal):
        # Be permissive on numeric types but coerce to Decimal to
        # guarantee the DB write gets a Decimal-typed value.
        realized_pl = Decimal(str(realized_pl))

    if close_reason not in _VALID_CLOSE_REASONS:
        raise ValueError(
            f"close_position_shared: close_reason {close_reason!r} "
            f"is not in the 9-value enum. Valid values: "
            f"{sorted(_VALID_CLOSE_REASONS)}."
        )
    if fill_source not in _VALID_FILL_SOURCES:
        raise ValueError(
            f"close_position_shared: fill_source {fill_source!r} is "
            f"not in the 4-value enum. Valid values: "
            f"{sorted(_VALID_FILL_SOURCES)}."
        )

    if closed_at is None:
        closed_at = datetime.now(timezone.utc)
    closed_at_iso = closed_at.isoformat()

    now_iso = datetime.now(timezone.utc).isoformat()

    # Conditional UPDATE. status IS DISTINCT FROM 'closed' matches
    # 'open', NULL, or any non-'closed' value. Atomic at MVCC level.
    update_res = supabase.table("paper_positions").update({
        "status": "closed",
        "quantity": 0,
        "realized_pl": str(realized_pl),  # Decimal → string for PostgREST
        "close_reason": close_reason,
        "fill_source": fill_source,
        "closed_at": closed_at_iso,
        "updated_at": now_iso,
    }).eq("id", position_id).neq("status", "closed").execute()

    # Supabase PostgREST returns .data as the list of updated rows.
    # A successful close writes exactly 1 row.
    updated_rows = update_res.data if update_res.data is not None else []
    if len(updated_rows) == 1:
        return  # happy path

    # Zero rows affected → either the position doesn't exist OR it
    # was already closed (or raced to closed by a concurrent caller).
    # Diagnostic fetch to distinguish.
    diag_res = supabase.table("paper_positions").select(
        "status, close_reason, fill_source, closed_at"
    ).eq("id", position_id).limit(1).execute()

    diag_rows = diag_res.data if diag_res.data is not None else []
    if not diag_rows:
        raise PositionNotFound(
            f"Position {position_id} does not exist in paper_positions."
        )

    existing = diag_rows[0]
    if existing.get("status") == "closed":
        raise PositionAlreadyClosed(
            position_id=position_id,
            new_fill_source=fill_source,
            existing_close_reason=existing.get("close_reason"),
            existing_fill_source=existing.get("fill_source"),
            existing_closed_at=existing.get("closed_at"),
        )

    # Row exists, status is not 'closed', but the UPDATE still didn't
    # write. This shouldn't happen under normal conditions — possible
    # causes: RLS policy blocking, concurrent status change to an
    # unexpected value, or a race that closed-then-reopened between
    # our UPDATE and SELECT. Fail loudly.
    raise RuntimeError(
        f"close_position_shared: UPDATE on position {position_id} "
        f"affected 0 rows but diagnostic SELECT shows "
        f"status={existing.get('status')!r}. Possible RLS block, "
        f"race condition, or unexpected schema state. Investigate."
    )
