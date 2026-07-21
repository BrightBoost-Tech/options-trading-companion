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
  - ``rank_blocked`` is the RANKER/selection-seam family. It covers two
    distinguishable-by-``detail`` sub-cases: (a) a SELECTED candidate whose
    ranker VERDICT blocked it — ``detail.reason='edge_below_minimum'``
    (raev<=-999) or the redundant policy final gate, ``selected=true``; and
    (b) an EMITTED candidate the ranker did NOT select at all —
    ``rank_and_select`` out-ranked it past the tier cap / risk budget / the
    score floor — ``detail.reason='not_selected_by_ranker'``,
    ``detail.selection_stage='rank_and_select'``, ``selected=false`` (the
    non-selected-alternate class; see :meth:`record_not_selected`). The exact
    per-alternate break reason is NOT reconstructable at this seam
    (``rank_and_select`` returns only the survivors), so it is honestly NOT
    fabricated — only known facts (score, emitted/selected counts) are stamped.
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

    def _base_row(
        self, ident: Dict[str, Any], selected: bool = True
    ) -> Dict[str, Any]:
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
            # True for the rank_and_select-SELECTED set (record_selected /
            # every selected-seam record_final); False only for the
            # non-selected alternates (record_not_selected). The scanner
            # emitted them as concrete opportunities but the ranker did not
            # pick them — the honest flag, not a default.
            "selected": selected,
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
        selected: bool = True,
    ) -> None:
        """Record THE final disposition for a candidate's current attempt.

        - Re-finalizing the SAME attempt refines the row (details merged,
          last disposition wins — e.g. rank_blocked at the ranker seam gains
          its suggestion_id at the persist seam).
        - Finalizing a DIFFERENT attempt of the same identity demotes the
          old final to ``superseded_retry`` first (supersede, not violation).
        - ``selected`` defaults True (every selected-seam call is byte-
          identical to before). :meth:`record_not_selected` passes False for
          the non-selected alternates.
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

            row = self._base_row(ident, selected=selected)
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

    def record_not_selected(
        self,
        emitted: List[Dict[str, Any]],
        selected: List[Dict[str, Any]],
        *,
        stage: str = "rank_and_select",
        reason: str = "not_selected_by_ranker",
    ) -> None:
        """Record ONE ``rank_blocked`` final for every EMITTED scanner
        candidate that the ranker did NOT select.

        Closes the non-selected-alternate gap: ``rank_and_select`` returns only
        its survivors, so the scanner-emitted candidates it passed over
        (out-ranked past the tier cap / risk budget / the score floor) had NO
        durable terminal fate — only the selected primaries were recorded. This
        writes their honest final at the SELECTION seam (``selected=false``),
        so ``emitted == selected_finals + not_selected_finals`` per cycle.

        HONESTY (contract §4 — known facts only):
          - identity: candidate fingerprint + symbol + strategy + cycle_id
            (all from the candidate / recorder, never fabricated);
          - ``detail.selection_stage`` / ``detail.reason``: the seam + a typed
            reason (NOT the exact per-alternate break cause — that is not
            reconstructable here; ``rank_and_select`` returns no per-drop
            reason, so inventing capacity-vs-budget-vs-floor would be a lie);
          - ``detail.score``: stamped ONLY when the candidate actually carries
            one (the ranker sorts on it); typed-unavailable otherwise;
          - ``detail.emitted_count`` / ``detail.selected_count``: the cycle's
            known funnel widths;
          - affordability / round-trip BP are DELIBERATELY absent — a
            non-selected alternate never reached H7 / sizing, so those were
            never computed (typed-unavailable = not stamped, never zeroed).

        Membership is by object identity (``id``): ``rank_and_select`` appends
        the SAME candidate dicts it selected, so a survivor is excluded even
        when a structurally-identical alternate shares its fingerprint.

        Fail-soft: never raises into the cycle; per-candidate failures are
        counted by :meth:`record_final` (write_failures) and surfaced in the
        cycle result.
        """
        try:
            emitted_list = list(emitted or [])
            if not emitted_list or self._disabled:
                return
            selected_ids = {id(c) for c in (selected or [])}
            selected_count = len(selected_ids)
            emitted_count = len(emitted_list)
            for cand in emitted_list:
                if id(cand) in selected_ids:
                    continue
                detail: Dict[str, Any] = {
                    "reason": reason,
                    "selection_stage": stage,
                    "emitted_count": emitted_count,
                    "selected_count": selected_count,
                }
                score = (cand or {}).get("score")
                if isinstance(score, (int, float)):
                    detail["score"] = score
                else:
                    # Typed-unavailable: the ranker's sort key was absent on
                    # this candidate; never fabricate a numeric rank/score.
                    detail["score_unavailable"] = True
                self.record_final(
                    cand, "rank_blocked", detail=detail, selected=False,
                )
        except Exception as exc:  # absolute fail-soft
            self.counters["write_failures"] += 1
            logger.warning(
                "[CANDIDATE_DISPOSITION] record_not_selected failed "
                "(non-fatal): %s", exc,
            )

    def counters_dict(self) -> Dict[str, Any]:
        """Typed counters for the cycle result (job_runs.result visibility)."""
        return {
            "cycle_id": self.cycle_id,
            "table_missing": self._table_missing,
            **self.counters,
        }


# ── Executor-phase lifecycle milestones (A3-LIFECYCLE, v1.6) ───────────────
# The three later-lifecycle disposition VALUES (already in the migration CHECK
# — no migration is needed to write them) form a MONOTONIC forward chain that
# advances the SINGLE is_final row a candidate already holds. They are set by
# a DIFFERENT job than the midday recorder (the executor stages; the broker
# poll fills), so the writer is cross-job and keys on the stable
# ``suggestion_id`` (the persist seam stamped it; ``idx_ctd_suggestion``
# serves the lookup), NOT the recorder's in-memory identity.
#
# HONESTY CONTRACT (why this needs no migration and loses no history):
#   - persisted_executable is the funnel entry the midday persist seam writes.
#     A milestone ADVANCES that row's disposition to the furthest state
#     reached; ``detail['lifecycle'][milestone]`` is an APPEND-ONLY timeline
#     (each milestone's timestamp + ``from`` predecessor + stage/order/broker/
#     fill ids), so no prior disposition history is erased — the disposition
#     column is the furthest milestone, the lifecycle dict is the full record.
#   - A candidate that died at ANY other terminal (scanner_rejected,
#     h7_dropped, allocator_dropped, rank_blocked, persisted_blocked,
#     superseded_retry) is NOT on this chain, so it can NEVER advance — the
#     predecessor guard makes a blocked/non-executable candidate un-advanceable
#     by construction (defense in depth with the executor only staging
#     executable rows).
#   - Monotonic + idempotent: a re-run advancing to a state the row already
#     holds/passed is a typed no-op (no regression, no duplicate row — it is an
#     UPDATE, never an INSERT).
#   - A missing table (migration unapplied) is a typed no-op; a missing row
#     (no persisted_executable predecessor) is a typed ORPHAN no-op — a
#     milestone NEVER fabricates a final row from the executor. Both are
#     counted and returned, never silent.
#
# OBSERVE-ONLY: this never gates, stages, submits, or fills — it only records.
MILESTONES = ("staged", "broker_submitted", "filled")

# The forward LIVE lifecycle chain: the persist-seam entry followed by the
# three executor-phase milestones, in order.
_LIVE_CHAIN = ("persisted_executable",) + MILESTONES
_CHAIN_INDEX = {name: i for i, name in enumerate(_LIVE_CHAIN)}


def _milestone_predecessors(milestone: str) -> frozenset:
    """The set of dispositions a row may hold to advance TO ``milestone``
    (every chain state strictly before it). ``persisted_executable`` is always
    a valid predecessor; a milestone may skip intermediate states (a live fill
    observed without a separate staged/submitted stamp) but never regress."""
    return frozenset(_LIVE_CHAIN[: _CHAIN_INDEX[milestone]])


def _ms_bump(counters: Optional[Dict[str, int]], key: str) -> None:
    if counters is not None:
        counters[key] = counters.get(key, 0) + 1


def advance_candidate_milestone(
    supabase: Any,
    suggestion_id: Optional[str],
    milestone: str,
    *,
    ids: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
    counters: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Advance a persisted candidate's lifecycle disposition to a later
    executor-phase MILESTONE (``staged`` → ``broker_submitted`` → ``filled``),
    keyed on the stable ``suggestion_id``.

    OBSERVE-ONLY, cross-job, fail-soft, idempotent and monotonic. Returns a
    typed result ``{"status": ...}``; NEVER raises into the caller. When a
    ``counters`` dict is supplied, the outcome is tallied into it (prefixed
    ``milestone_*``) so the caller can surface it in ``job_runs.result``.

    Statuses: ``advanced`` · ``already_at_or_past`` · ``not_advanceable``
    (blocked/dead terminal — never advances) · ``orphan_no_row`` (no
    persisted_executable predecessor — never fabricated) · ``table_missing``
    (migration unapplied — typed no-op) · ``read_failed`` / ``write_failed``
    (counted, loud) · ``invalid_milestone`` · ``disabled`` (no client / id).
    """
    result: Dict[str, Any] = {
        "status": "error", "milestone": milestone, "suggestion_id": suggestion_id,
    }
    try:
        if milestone not in MILESTONES:
            result["status"] = "invalid_milestone"
            _ms_bump(counters, "milestone_invalid")
            logger.warning(
                "[CANDIDATE_DISPOSITION] advance_candidate_milestone: invalid "
                "milestone %r (chain: %s) — write refused",
                milestone, list(MILESTONES),
            )
            return result
        if supabase is None or not suggestion_id:
            result["status"] = "disabled"
            _ms_bump(counters, "milestone_disabled")
            return result

        # 1) Locate THE one is_final row carrying this suggestion_id.
        try:
            res = (
                supabase.table(TABLE)
                .select("id, disposition, detail")
                .eq("suggestion_id", suggestion_id)
                .eq("is_final", True)
                .limit(1)
                .execute()
            )
            rows = res.data or []
        except Exception as exc:
            if _is_table_missing_error(exc):
                result["status"] = "table_missing"
                _ms_bump(counters, "milestone_table_missing_noops")
                logger.warning(
                    "[CANDIDATE_DISPOSITION] table %s missing — milestone %s is "
                    "a typed no-op (migration unapplied): %s",
                    TABLE, milestone, exc,
                )
                return result
            result["status"] = "read_failed"
            _ms_bump(counters, "milestone_write_failures")
            logger.warning(
                "[CANDIDATE_DISPOSITION] milestone %s read failed for "
                "suggestion %s (non-fatal): %s",
                milestone, str(suggestion_id)[:8], exc,
            )
            return result

        if not rows:
            # No persisted_executable predecessor row — a milestone can only
            # ADVANCE a candidate the funnel already recorded; it never
            # fabricates a final from the executor. Counted + visible.
            result["status"] = "orphan_no_row"
            _ms_bump(counters, "milestone_orphan_no_row")
            return result

        row = rows[0]
        current = row.get("disposition")
        preds = _milestone_predecessors(milestone)

        if current not in preds:
            result["current"] = current
            if current in _CHAIN_INDEX and _CHAIN_INDEX[current] >= _CHAIN_INDEX[milestone]:
                # Already at or past this milestone — idempotent no-op, never
                # a regression.
                result["status"] = "already_at_or_past"
                _ms_bump(counters, "milestone_already_at_or_past")
            else:
                # A blocked / dead terminal (or NULL) — must NEVER advance.
                result["status"] = "not_advanceable"
                _ms_bump(counters, "milestone_not_advanceable")
            return result

        # 2) Monotonic forward advance — APPEND-ONLY lifecycle timeline so no
        #    prior disposition history is erased.
        detail = dict(row.get("detail") or {})
        lifecycle = dict(detail.get("lifecycle") or {})
        entry: Dict[str, Any] = {"at": _utcnow_iso(), "from": current}
        for src in (ids, extra):
            if src:
                for k, v in src.items():
                    if v is not None:
                        entry[k] = v
        lifecycle[milestone] = entry
        detail["lifecycle"] = lifecycle

        try:
            (
                supabase.table(TABLE)
                .update({
                    "disposition": milestone,
                    "detail": detail,
                    "finalized_at": _utcnow_iso(),
                })
                .eq("id", row.get("id"))
                # Optimistic-concurrency guard: a concurrent advance changes
                # the disposition out from under us → this matches 0 rows and
                # the write is a harmless no-op (no duplicate, no regression).
                .eq("disposition", current)
                .execute()
            )
        except Exception as exc:
            if _is_table_missing_error(exc):
                result["status"] = "table_missing"
                _ms_bump(counters, "milestone_table_missing_noops")
                return result
            result["status"] = "write_failed"
            _ms_bump(counters, "milestone_write_failures")
            logger.warning(
                "[CANDIDATE_DISPOSITION] milestone %s write failed for "
                "suggestion %s (non-fatal): %s",
                milestone, str(suggestion_id)[:8], exc,
            )
            return result

        result["status"] = "advanced"
        result["from"] = current
        _ms_bump(counters, "milestone_advanced")
        return result
    except Exception as exc:  # absolute fail-soft
        _ms_bump(counters, "milestone_write_failures")
        logger.warning(
            "[CANDIDATE_DISPOSITION] advance_candidate_milestone unexpected "
            "failure (non-fatal): %s", exc,
        )
        return result
