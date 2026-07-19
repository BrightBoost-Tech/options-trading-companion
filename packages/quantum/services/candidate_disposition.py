"""Durable per-candidate terminal disposition (Lane 4B, funnel phase-2).

OBSERVE-ONLY. Closes the AAPL/IWM-fate gap: a candidate that
``rank_and_select`` SELECTED but that then died at the H7 pre-filter, the
PortfolioAllocator, sizing, the policy final gate, or the ranker verdict was
never durable anywhere — ``suggestion_rejections`` has no uniqueness, no
selected flag and no candidate fingerprint (only PK unique; verified against
live pg_indexes 2026-07-17); ``trade_suggestions`` holds only persisted rows;
``decision_runs`` manifests are cycle-level. This module writes to the NEW
``candidate_terminal_dispositions`` table (migration
``supabase/migrations/20260717100000_candidate_terminal_dispositions.sql`` —
a FILE only until the operator applies it).

Invariant: every SELECTED candidate reaches EXACTLY ONE final disposition per
(candidate identity, cycle), while every underlying attempt/rejection event
elsewhere (suggestion_rejections, trade_suggestions, decision manifests) is
preserved untouched.

Candidate identity = (cycle_id, candidate_fingerprint, attempt) where
``candidate_fingerprint`` REUSES ``compute_legs_fingerprint`` (structure-only,
leg-order-independent, size/price-excluded) so the pre-persist identity equals
the persisted ``trade_suggestions.legs_fingerprint`` for the same structure.
``is_primary`` carries the primary/fallback strategy flag; ``attempt``
increments when the same fingerprint re-enters the same cycle.

Disposition taxonomy (mirrors the migration CHECK — the contract test pins
set-equality):
    scanner_rejected | h7_dropped | allocator_dropped | rank_blocked |
    persisted_blocked | persisted_executable | staged | broker_submitted |
    filled | superseded_retry

Mapping notes (honesty over prettiness — detail.reason always carries the
exact cause):
  - ``h7_dropped`` covers the capital/priceability-fit family between
    selection and persist: the active H7 pre-filter, sized-to-zero
    (the real H7 round-trip verdict), risk-budget exhaustion, and the
    unpriceable-candidate death. Because the value is deliberately
    overloaded, EVERY ``h7_dropped`` final carries exactly one canonical
    ``detail['h7_subreason']`` (H7_SUBREASONS) as a queryable sub-taxonomy —
    writer-enforced (strict raise in dev/test, fail-soft + counted in
    production; owner decision 2026-07-18). Parent
    ``WHERE disposition='h7_dropped'`` queries are unchanged.
  - ``rank_blocked`` covers verdict blocks: edge_below_minimum (raev<=-999)
    and the redundant policy final gate.
  - ``persisted_blocked`` / ``persisted_executable`` are the persist-seam
    outcomes; a persist that yielded no row is ``persisted_blocked`` with
    ``detail.insert_failed=true`` (the row is LOST — the flag is the truth).
  - ``staged`` / ``broker_submitted`` / ``filled`` are later-lifecycle values
    reserved for the executor phase (no call sites in this PR).
  - ``superseded_retry`` is never passed by callers: it is what an OLD final
    becomes when a NEWER attempt of the same identity finalizes.

Fail-soft doctrine (RejectionStats conventions): a disposition write NEVER
breaks the cycle. Failures are counted and logged loudly once; a missing
table (migration not applied yet) is a TYPED no-op — ``table_missing_noops``
is surfaced in the cycle result so the degradation is visible, never silent.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from packages.quantum.services.options_utils import compute_legs_fingerprint

logger = logging.getLogger(__name__)

TABLE = "candidate_terminal_dispositions"

DISPOSITIONS = frozenset({
    "scanner_rejected",
    "h7_dropped",
    "allocator_dropped",
    "rank_blocked",
    "persisted_blocked",
    "persisted_executable",
    "staged",
    "broker_submitted",
    "filled",
    "superseded_retry",
})

# ── H7 typed-subreason taxonomy (owner decision 2026-07-18,
# H7_DROPPED_PARENT_PLUS_TYPED_SUBREASON) ────────────────────────────────
# The parent ``h7_dropped`` value is DELIBERATELY overloaded — it is the
# capital/priceability-fit family between selection and persist (C2 packet
# §2). To keep the family queryable without splitting the top-level enum
# (no new disposition values, backward-compatible ``WHERE disposition=
# 'h7_dropped'`` queries), every ``h7_dropped`` final MUST carry EXACTLY ONE
# canonical ``detail['h7_subreason']`` from this set. This is the queryable
# sub-taxonomy; ``detail.reason`` / ``detail.sizing_outcome`` keep the exact
# free-text cause underneath it (never removed).
#
# Canonical values ↔ orchestrator call sites (workflow_orchestrator.py):
#   roundtrip_bp     — H7 pre-filter active drop (:~2798) AND the true H7
#                      round-trip verdict is the sizing engine's own; the
#                      prefilter check is literally
#                      collateral + close_bp×safety > deployable_capital.
#   quality_gate     — marketdata quality-gate HARD-mode E4/E5 drops
#                      (:~3739 / :~3792, sizing_outcome='marketdata_quality_gate')
#                      AND the unpriceable-candidate death E1 (:~3260,
#                      suggested_entry<=0) — a data/priceability death, same
#                      family as the gate, NOT capital-fit (adjudicated:
#                      labelling it sizing_zero would falsely imply it reached
#                      the sizing engine).
#   sizing_zero      — the dominant death: sizing engine returns contracts==0
#                      (E3, :~4064). Its 6 root causes (no-BP, round-trip,
#                      risk<1-contract, collateral, invalid-max-loss,
#                      lifecycle-veto) stay in detail.reason/sizing_outcome.
#   risk_budget      — per-candidate risk budget exhausted, final_risk_dollars
#                      <= 0 (E2, :~3502).
#   account_capacity — RESERVED: an account/tier capacity death recorded as
#                      h7_dropped. No current call site maps here (allocator
#                      caps → allocator_dropped; tier max_trades → pre-selection,
#                      unrecorded; sizing no-BP → folded into sizing_zero per
#                      the owner decision). Kept canonical for a future
#                      account-capacity drop that lands in the h7 family.
H7_SUBREASONS = frozenset({
    "roundtrip_bp",
    "quality_gate",
    "sizing_zero",
    "risk_budget",
    "account_capacity",
})

# Writer-side sentinel stamped when a production h7_dropped final arrives with
# a missing/invalid subreason (a CALL-SITE BUG). NOT a canonical value — it is
# the honest "the call site failed to type this" marker, always paired with
# detail['h7_subreason_violation']=True and a writer_taxonomy_violation count.
H7_SUBREASON_UNSPECIFIED = "unspecified"


class H7SubreasonViolation(ValueError):
    """A ``h7_dropped`` final was recorded without a canonical
    ``detail['h7_subreason']``.

    In STRICT mode (dev/test — see :func:`_taxonomy_strict`) the writer raises
    this so the offending call site fails CI (the #1126 costume class: a green
    test must never hide an un-typed h7_dropped). In PRODUCTION the writer's
    absolute fail-soft doctrine wins: it counts + logs + stamps the
    ``unspecified`` sentinel and STILL writes the row (never blocks the cycle).
    """


def _taxonomy_strict() -> bool:
    """Whether a missing/invalid h7_subreason should RAISE (dev/test) or
    fail-soft (production).

    Explicit override ``CANDIDATE_DISPOSITION_STRICT_TAXONOMY`` wins both ways
    (1/true/yes/on → strict, else soft); absent → strict under pytest, soft in
    production. Re-read each call so tests can toggle it.
    """
    override = os.environ.get("CANDIDATE_DISPOSITION_STRICT_TAXONOMY")
    if override is not None and override.strip() != "":
        return override.strip().lower() in ("1", "true", "yes", "on")
    return ("PYTEST_CURRENT_TEST" in os.environ) or ("pytest" in sys.modules)

# PostgREST/Postgres signatures for "the table itself is absent" — the
# designed state until the operator applies the migration. Column-level
# errors (PGRST204/42703) deliberately do NOT match: those are real
# failures and count as write_failures (loud), not typed no-ops.
_TABLE_MISSING_MARKERS = (
    "pgrst205",
    "42p01",
    "could not find the table",
)


def _is_table_missing_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if any(m in msg for m in _TABLE_MISSING_MARKERS):
        return True
    # 'relation "...candidate_terminal_dispositions..." does not exist'
    return "does not exist" in msg and TABLE in msg


def _is_unique_violation(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "23505" in msg or "duplicate key" in msg


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def candidate_fingerprint(cand: Dict[str, Any]) -> str:
    """Legs-based candidate identity fingerprint.

    REUSES ``compute_legs_fingerprint`` (structure-only: underlying, expiry,
    type, strike, side; excludes quantity/price; leg-order-independent), so
    for any candidate that later persists, this equals the row's
    ``trade_suggestions.legs_fingerprint`` by construction —
    ``build_midday_order_json`` copies leg symbol/side verbatim.

    Defensive fallback for a legless candidate (never emitted by the scanner
    today): a marked symbol+strategy hash, so identity never silently
    collides with a real legs fingerprint.
    """
    legs = (cand or {}).get("legs") or []
    if legs:
        return compute_legs_fingerprint({"legs": legs})
    sym = (cand or {}).get("ticker") or (cand or {}).get("symbol") or ""
    strat = (cand or {}).get("strategy") or (cand or {}).get("type") or "unknown"
    digest = hashlib.sha256(f"{sym}:{strat}".encode("utf-8")).hexdigest()
    return f"nolegs:{digest}"


def _candidate_is_primary(cand: Dict[str, Any]) -> bool:
    """Primary/fallback flag. Absent marker -> primary (the scanner emits no
    fallback-strategy candidates today; the column exists so a future
    fallback emitter cannot collide identities silently)."""
    c = cand or {}
    return not bool(c.get("is_fallback_strategy") or c.get("is_fallback"))


class CandidateDispositionRecorder:
    """Per-cycle idempotent writer for candidate terminal dispositions.

    One instance per midday cycle. All writes are fail-soft; counters are
    surfaced into the cycle result via :meth:`counters_dict` so the
    suggestions_open handler persists them in ``job_runs.result``.
    """

    def __init__(
        self,
        supabase: Any,
        user_id: Optional[str],
        cycle_date: str,
        cycle_id: Optional[str] = None,
        window: str = "midday_entry",
    ):
        self._sb = supabase
        self.user_id = user_id
        self.cycle_date = cycle_date
        self.cycle_id = str(cycle_id) if cycle_id else str(uuid.uuid4())
        self.window = window
        try:
            from packages.quantum.observability.lineage import get_code_sha
            self._code_sha = get_code_sha()
        except Exception:
            self._code_sha = "unknown"

        # id(cand) -> identity dict {fingerprint, attempt, symbol, strategy,
        #                            is_primary}
        self._registry: Dict[int, Dict[str, Any]] = {}
        # fingerprint -> highest attempt registered this cycle
        self._attempts: Dict[str, int] = {}
        # fingerprint -> attempt currently holding the final disposition
        self._finals: Dict[str, int] = {}
        # (fingerprint, attempt) -> last detail written (merged on re-final)
        self._final_details: Dict[Any, Dict[str, Any]] = {}

        self._table_missing = False
        self._disabled = supabase is None
        self._warned_write_failure = False
        self._warned_taxonomy_violation = False
        self.counters: Dict[str, int] = {
            "attempts_recorded": 0,
            "finals_recorded": 0,
            "write_failures": 0,
            "table_missing_noops": 0,
            # h7_dropped final recorded with a missing/invalid h7_subreason
            # (a call-site BUG). Always 0 in normal operation — the dev/test
            # strict raise guarantees every SHIPPED call site is typed.
            "writer_taxonomy_violation": 0,
        }

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    @classmethod
    def create(
        cls,
        supabase: Any,
        user_id: Optional[str],
        cycle_date: str,
        window: str = "midday_entry",
    ) -> "CandidateDispositionRecorder":
        """Build a recorder, linking cycle_id to the active replay
        DecisionContext when one exists (REPLAY_ENABLE on); otherwise a fresh
        per-cycle UUID. Fail-soft: context resolution errors fall back to the
        UUID."""
        cycle_id = None
        try:
            from packages.quantum.services.replay.decision_context import (
                get_current_decision_context,
            )
            dc = get_current_decision_context()
            if dc is not None:
                cycle_id = str(dc.decision_id)
        except Exception:
            cycle_id = None
        return cls(supabase, user_id=user_id, cycle_date=cycle_date,
                   cycle_id=cycle_id, window=window)

    # ------------------------------------------------------------------
    # identity registry
    # ------------------------------------------------------------------
    def _register(
        self,
        cand: Optional[Dict[str, Any]],
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        fingerprint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Idempotently resolve a candidate dict to its cycle identity."""
        key = id(cand) if cand is not None else None
        if key is not None and key in self._registry:
            return self._registry[key]

        c = cand or {}
        fp = fingerprint or candidate_fingerprint(c)
        attempt = self._attempts.get(fp, 0) + 1
        self._attempts[fp] = attempt
        ident = {
            "fingerprint": fp,
            "attempt": attempt,
            "symbol": symbol or c.get("ticker") or c.get("symbol") or "unknown",
            "strategy": (strategy or c.get("strategy") or c.get("type")
                         or "unknown"),
            "is_primary": _candidate_is_primary(c),
        }
        if key is not None:
            self._registry[key] = ident
        return ident

    # ------------------------------------------------------------------
    # write plumbing (fail-soft)
    # ------------------------------------------------------------------
    def _noop(self) -> None:
        self.counters["table_missing_noops"] += 1

    def _execute(self, op_desc: str, fn) -> bool:
        """Run one client operation; classify failures. Returns success."""
        if self._disabled:
            return False
        if self._table_missing:
            self._noop()
            return False
        try:
            fn()
            return True
        except Exception as exc:
            if _is_table_missing_error(exc):
                self._table_missing = True
                self._noop()
                logger.warning(
                    "[CANDIDATE_DISPOSITION] table %s missing — typed no-op "
                    "for the rest of this cycle (migration unapplied): %s",
                    TABLE, exc,
                )
                return False
            self.counters["write_failures"] += 1
            if not self._warned_write_failure:
                self._warned_write_failure = True
                logger.warning(
                    "[CANDIDATE_DISPOSITION] %s write failed (non-fatal, "
                    "further failures counted silently): %s", op_desc, exc,
                )
            else:
                logger.debug(
                    "[CANDIDATE_DISPOSITION] %s write failed: %s",
                    op_desc, exc,
                )
            return False

    def _base_row(self, ident: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "cycle_date": self.cycle_date,
            "user_id": self.user_id,
            "window": self.window,
            "symbol": ident["symbol"],
            "strategy": ident["strategy"],
            "candidate_fingerprint": ident["fingerprint"],
            "attempt": ident["attempt"],
            "is_primary": ident["is_primary"],
            "selected": True,
            "code_sha": self._code_sha,
        }

    def _upsert(self, rows: List[Dict[str, Any]]) -> bool:
        return self._execute(
            "upsert",
            lambda: self._sb.table(TABLE).upsert(
                rows if len(rows) > 1 else rows[0],
                on_conflict="cycle_id,candidate_fingerprint,attempt",
            ).execute(),
        )

    def _cost_reconciliation(
        self, cand: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Observe-only multi-basis cost artifact for this candidate (Lane 2C,
        phase-2 consumer #1). Lazy import so the writer carries no static
        ``cost_basis`` dependency (the import-lock allowlists the builder, not
        this writer). Absolutely fail-soft: any failure returns None and the
        artifact is simply omitted — a disposition row is NEVER lost to a cost
        artifact failure, and the artifact NEVER feeds a decision (nothing in
        the decision path reads this table)."""
        if cand is None:
            return None
        try:
            from packages.quantum.services.cost_reconciliation_artifact import (
                build_cost_reconciliation,
            )
            return build_cost_reconciliation(cand)
        except Exception as exc:  # never touch the write path
            logger.debug(
                "[CANDIDATE_DISPOSITION] cost_reconciliation skipped "
                "(non-fatal): %s", exc,
            )
            return None

    def _demote_other_finals(self, fingerprint: str, keep_attempt: int) -> None:
        """Supersede semantics: any OTHER attempt of this identity that holds
        the final loses it — its disposition becomes ``superseded_retry`` —
        so the partial unique (one final per identity per cycle) is an
        invariant, not a race."""
        self._execute(
            "supersede-update",
            lambda: self._sb.table(TABLE)
            .update({
                "is_final": False,
                "disposition": "superseded_retry",
                "finalized_at": _utcnow_iso(),
            })
            .eq("cycle_id", self.cycle_id)
            .eq("candidate_fingerprint", fingerprint)
            .eq("is_final", True)
            .neq("attempt", keep_attempt)
            .execute(),
        )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def record_selected(self, candidates: List[Dict[str, Any]]) -> None:
        """Record the post-rank_and_select SELECTED set (selected=true).

        One non-final attempt row per candidate; batched into a single
        idempotent upsert. Never mutates the candidate dicts.
        """
        try:
            cands = list(candidates or [])
            if not cands or self._disabled:
                return
            rows = []
            now = _utcnow_iso()
            for cand in cands:
                ident = self._register(cand)
                row = self._base_row(ident)
                row["is_final"] = False
                row["disposition"] = None
                row["selected_at"] = now
                rows.append(row)
            if self._upsert(rows):
                self.counters["attempts_recorded"] += len(rows)
        except Exception as exc:  # absolute fail-soft
            self.counters["write_failures"] += 1
            logger.warning(
                "[CANDIDATE_DISPOSITION] record_selected failed "
                "(non-fatal): %s", exc,
            )

    def record_final(
        self,
        cand: Optional[Dict[str, Any]],
        disposition: str,
        detail: Optional[Dict[str, Any]] = None,
        suggestion_id: Optional[str] = None,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        fingerprint: Optional[str] = None,
    ) -> None:
        """Record THE final disposition for a candidate's current attempt.

        - Re-finalizing the SAME attempt refines the row (details merged,
          last disposition wins — e.g. rank_blocked at the ranker seam gains
          its suggestion_id at the persist seam).
        - Finalizing a DIFFERENT attempt of the same identity demotes the
          old final to ``superseded_retry`` first (supersede, not violation).
        """
        try:
            if disposition not in DISPOSITIONS:
                self.counters["write_failures"] += 1
                logger.warning(
                    "[CANDIDATE_DISPOSITION] invalid disposition %r "
                    "(taxonomy: %s) — write refused",
                    disposition, sorted(DISPOSITIONS),
                )
                return
            if self._disabled:
                return

            ident = self._register(cand, symbol=symbol, strategy=strategy)
            fp, attempt = ident["fingerprint"], ident["attempt"]

            merged_detail = dict(
                self._final_details.get((fp, attempt)) or {}
            )
            if detail:
                merged_detail.update(detail)
            if (fingerprint and fingerprint != fp
                    and "persisted_fingerprint_mismatch" not in merged_detail):
                # The persisted legs_fingerprint should equal the candidate
                # fingerprint by construction; if it ever diverges, record
                # the divergence rather than silently switching identity.
                merged_detail["persisted_fingerprint_mismatch"] = fingerprint

            # --- H7 typed-subreason contract (owner decision 2026-07-18) ---
            # Every ``h7_dropped`` final MUST carry exactly one canonical
            # ``detail['h7_subreason']`` (H7_SUBREASONS). A missing/invalid
            # subreason is a CALL-SITE BUG: raise in dev/test so CI catches it
            # (the #1126 costume class), fail-SOFT in production — count it,
            # log loudly ONCE, stamp a queryable ``unspecified`` sentinel, and
            # STILL write the row. The one-final-per-candidate invariant wins
            # over a crisp taxonomy value; the violation is never silent.
            if disposition == "h7_dropped":
                sub = merged_detail.get("h7_subreason")
                if sub not in H7_SUBREASONS:
                    self.counters["writer_taxonomy_violation"] += 1
                    if not self._warned_taxonomy_violation:
                        self._warned_taxonomy_violation = True
                        logger.warning(
                            "[CANDIDATE_DISPOSITION] h7_dropped final for "
                            "%s/%s carried %s h7_subreason %r (canonical: %s) "
                            "— CALL-SITE BUG; row stamped %r (violation "
                            "counted, invariant preserved)",
                            ident.get("symbol"), ident.get("strategy"),
                            "a missing" if sub is None else "an invalid", sub,
                            sorted(H7_SUBREASONS), H7_SUBREASON_UNSPECIFIED,
                        )
                    if _taxonomy_strict():
                        raise H7SubreasonViolation(
                            "record_final(disposition='h7_dropped') requires "
                            "detail['h7_subreason'] in "
                            f"{sorted(H7_SUBREASONS)}; got {sub!r}"
                        )
                    merged_detail["h7_subreason"] = H7_SUBREASON_UNSPECIFIED
                    merged_detail["h7_subreason_violation"] = True

            # Observe-only multi-basis cost reconciliation (Lane 2C, phase-2
            # consumer #1). Computed ONCE per attempt (re-finals of the same
            # attempt inherit it via _final_details); typed 'unavailable' for
            # any basis not reconstructable at this seam; fail-soft — a None
            # simply omits the artifact and never blocks the write.
            if "cost_reconciliation" not in merged_detail:
                artifact = self._cost_reconciliation(cand)
                if artifact is not None:
                    merged_detail["cost_reconciliation"] = artifact

            prior = self._finals.get(fp)
            if prior is not None and prior != attempt:
                self._demote_other_finals(fp, attempt)

            row = self._base_row(ident)
            row["is_final"] = True
            row["disposition"] = disposition
            row["finalized_at"] = _utcnow_iso()
            if merged_detail:
                row["detail"] = merged_detail
            if suggestion_id is not None:
                row["suggestion_id"] = suggestion_id

            ok = self._upsert([row])
            if not ok and not self._table_missing and not self._disabled:
                # Defensive: another writer (or a prior partial cycle) may
                # hold the partial-unique final. Demote and retry once.
                self._demote_other_finals(fp, attempt)
                ok = self._upsert([row])
            if ok:
                self.counters["finals_recorded"] += 1
                self._finals[fp] = attempt
                self._final_details[(fp, attempt)] = merged_detail
        except H7SubreasonViolation:
            # STRICT (dev/test) taxonomy enforcement — re-raise so the
            # offending call site fails CI. Production never reaches here
            # (_taxonomy_strict() is False; the soft path stamps + counts).
            raise
        except Exception as exc:  # absolute fail-soft
            self.counters["write_failures"] += 1
            logger.warning(
                "[CANDIDATE_DISPOSITION] record_final failed (non-fatal): %s",
                exc,
            )

    def counters_dict(self) -> Dict[str, Any]:
        """Typed counters for the cycle result (job_runs.result visibility)."""
        return {
            "cycle_id": self.cycle_id,
            "table_missing": self._table_missing,
            **self.counters,
        }
