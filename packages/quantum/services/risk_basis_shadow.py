"""Risk-basis shadow (P0-B book-scaling, 2026-07-11) — OBSERVE-ONLY.

The risk stack costs the open book / a candidate on a PREMIUM / null-blind
basis: the allocator and RiskBudgetEngine see the open book as ~$0 (no
cost_basis persisted) and the utilization gate costs a candidate at premium,
not defined-risk max loss. The HONEST basis is max_loss_total (now persisted on
paper_positions, reused from trade_suggestions.max_loss_total).

This module computes BOTH bases at each consumer and logs [RISK_BASIS_SHADOW];
the honest basis becomes DECISIVE only when RISK_BASIS_MAX_LOSS_ENABLED=1
(default OFF — decisions stay on the current basis, byte-identical). Third
application of the Option-A observe→enforce pattern (after #1034 exit-mark
corroboration and #1116 mark-write corroboration).

⚠ UNITS: max_loss_total is a POSITION-LEVEL TOTAL (already × contracts × 100).
Never multiply it by qty again (the RBE double-scaling trap).
"""
import os
import logging
import uuid
import contextvars
from contextlib import contextmanager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def is_max_loss_basis_enabled() -> bool:
    """Behavioral opt-in (§3): ONLY '=1' makes the honest max_loss basis
    DECISIVE. Absent / empty / any other value → current basis (observe-only),
    so an env regression fails SAFE to today's behavior."""
    return (os.environ.get("RISK_BASIS_MAX_LOSS_ENABLED") or "").strip() == "1"


def log_risk_basis_shadow(consumer, current_usd, honest_usd, *,
                          context=None, threshold_usd=None):
    """One [RISK_BASIS_SHADOW] line per consumer decision: both bases + whether
    the honest basis WOULD flip the decision against a threshold. honest_usd
    None → NULL-basis (legacy / unpopulated max_loss_total), logged as such with
    no divergence claim. Observe-only; NEVER raises."""
    try:
        cur = float(current_usd or 0.0)
        if honest_usd is None:
            logger.info(
                "[RISK_BASIS_SHADOW] consumer=%s current=%.2f honest=NULL "
                "basis=null_legacy context=%s", consumer, cur, context or {})
            return
        hon = float(honest_usd)
        would_flip = None
        if threshold_usd is not None:
            t = float(threshold_usd)
            # the decision flips iff the two bases fall on opposite sides of t
            would_flip = (cur <= t < hon) or (hon <= t < cur)
        logger.info(
            "[RISK_BASIS_SHADOW] consumer=%s current=%.2f honest=%.2f delta=%.2f "
            "would_flip=%s context=%s",
            consumer, cur, hon, hon - cur, would_flip, context or {})
    except Exception as e:  # observe-only must never break a decision
        logger.warning("[RISK_BASIS_SHADOW] log failed consumer=%s: %s", consumer, e)


def log_shadow_heartbeat(window, evaluated, *, cycle=None, **fields):
    """Per-cycle LIVENESS line for an observe window — fires EVEN WHEN evaluated=0
    so a health check can distinguish 'ran, saw nothing' from 'did not run / logging
    lost' (the marker-silence ambiguity the arm notebooks had no answer for). window
    is a short tag e.g. 'RISK_BASIS' / 'BUCKET' / 'APPLY_ORDER' / 'EXECUTOR_SHADOW'.
    Observe-only; never raises."""
    try:
        extra = " ".join(f"{k}={v}" for k, v in fields.items()) if fields else ""
        logger.info("[%s_HEARTBEAT] cycle=%s evaluated=%d %s",
                    window, cycle if cycle is not None else "-",
                    int(evaluated or 0), extra)
    except Exception:  # observe-only must never break a cycle
        pass


def choose_basis(current_usd, honest_usd):
    """Return the value the DECISION should use: the honest basis when the flag
    is ARMED and honest is a usable positive number, else the current basis.
    Flag OFF → returns current_usd unchanged (byte-identical)."""
    if is_max_loss_basis_enabled():
        try:
            if honest_usd is not None and float(honest_usd) > 0:
                return float(honest_usd)
        except (TypeError, ValueError):
            pass
    return current_usd


def honest_position_risk(pos):
    """The honest per-position risk = max_loss_total, a POSITION-LEVEL TOTAL.
    Returns None when absent. ⚠ NEVER multiplies by qty — max_loss_total is
    already × contracts × 100; the RBE legacy path keys max_loss PER-CONTRACT
    and × qty, so re-scaling a _total would double-count. This helper IS the
    units-trap guard (unit-tested: a qty-4 position returns its total as-is)."""
    ml = pos.get("max_loss_total") if isinstance(pos, dict) else getattr(pos, "max_loss_total", None)
    try:
        return abs(float(ml)) if ml is not None else None
    except (TypeError, ValueError):
        return None


def compute_position_risk_basis(entry_premium_abs, qty,
                                suggestion_max_loss_total, suggestion_contracts):
    """(cost_basis_total, max_loss_total) for a newly-created position — WRITE
    side. cost_basis_total = |premium| × 100 × |qty| (premium basis, always
    available). max_loss_total = the suggestion's defined-risk TOTAL scaled to
    ACTUAL filled contracts; None (H9) when the suggestion carries no
    max_loss_total or an unusable contract count — never fabricated."""
    q = abs(int(qty or 0))
    try:
        cb = round(abs(float(entry_premium_abs or 0.0)) * 100.0 * q, 2)
        cost_basis_total = cb if cb > 0 else None
    except (TypeError, ValueError):
        cost_basis_total = None
    max_loss_total = None
    try:
        if suggestion_max_loss_total is not None:
            sc = int(suggestion_contracts or 0)
            if sc > 0 and q > 0:
                max_loss_total = round(float(suggestion_max_loss_total) * q / sc, 2)
    except (TypeError, ValueError):
        max_loss_total = None
    return cost_basis_total, max_loss_total


# ═══════════════════════════════════════════════════════════════════════════
# DURABLE ARM EVIDENCE (F-A4-RISKBASIS-SILENT, 2026-07-19) — OBSERVE-ONLY
# ═══════════════════════════════════════════════════════════════════════════
# The generic ``[RISK_BASIS_SHADOW]`` / heartbeat log lines above are EPHEMERAL
# (Railway logs roll off) and carry no coverage / typed-unavailable / code-SHA
# fields, so the exact P0-B observe→enforce arm decision (would arming
# RISK_BASIS_MAX_LOSS_ENABLED flip THIS consumer's decision, on how much real
# max_loss_total coverage) never reached a durable evidence contract. This
# block records ONE typed row per consumer decision into a per-cycle collector;
# the natural-cycle job handlers drain it into
# ``job_runs.result.cycle_metadata.risk_basis_arm_evidence`` (no migration).
#
# ⚠ OBSERVE-ONLY: nothing here feeds a decision. ``choose_basis`` /
# ``is_max_loss_basis_enabled`` semantics are UNCHANGED; recording is pure
# side-observation and NEVER raises into a decision path. An empty book is an
# EXPLICIT ``not_applicable_empty_book`` row, never silence; a failed READ is a
# typed ``unavailable`` reason, never a fabricated flat book (H9 / "empty data
# is not a failed read").

CURRENT_BASIS_NAME = "premium"        # today's decision basis (cost / premium)
HONEST_BASIS_NAME = "max_loss_total"  # the honest defined-risk basis proposed

_UNSET = object()  # sentinel: "no explicit would_flip override supplied"

# Per-cycle collector, bound implicitly for the duration of an
# ``arm_evidence_scope``. contextvars carry the SAME (mutable) collector object
# into awaited coroutines and child tasks, so a seam buried in the cycle appends
# to the scope its handler opened without threading a parameter through every
# intermediate frame.
_arm_evidence_ctx = contextvars.ContextVar("risk_basis_arm_evidence", default=None)


class ArmEvidenceCollector:
    """A per-cycle accumulator: ``rows`` (typed evidence) + ``errors`` (typed
    strings that must fold to job ``partial``). Never raises on append."""

    __slots__ = ("cycle_id", "rows", "errors")

    def __init__(self, cycle_id):
        self.cycle_id = cycle_id
        self.rows = []
        self.errors = []


@contextmanager
def arm_evidence_scope(cycle_id=None):
    """Bind a fresh :class:`ArmEvidenceCollector` for the duration of the block.
    Yields the collector; the caller drains ``.rows`` / ``.errors`` afterward
    (the reference survives the block — draining in a ``finally`` captures
    whatever accumulated even if the cycle raised)."""
    coll = ArmEvidenceCollector(cycle_id or f"cycle:{uuid.uuid4()}")
    token = _arm_evidence_ctx.set(coll)
    try:
        yield coll
    finally:
        _arm_evidence_ctx.reset(token)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _resolve_code_sha():
    """The existing deploy-SHA source (full 40-hex or 'unknown'). Imported
    lazily to avoid an import cycle; never raises."""
    try:
        from packages.quantum.observability.lineage import resolve_git_sha
        return resolve_git_sha()
    except Exception:
        return "unknown"


def _coverage_counts(positions):
    """(readable, total) over an open book: how many positions carry a usable
    ``max_loss_total`` (the honest basis) vs how many exist. Uses the units-trap
    guard ``honest_position_risk`` (dicts AND objects)."""
    total = 0
    readable = 0
    for p in positions or []:
        total += 1
        if honest_position_risk(p) is not None:
            readable += 1
    return readable, total


def _dollar_would_flip(current_usd, honest_usd, threshold_usd):
    """The decision flips iff the two dollar bases fall on opposite sides of a
    dollar threshold (same rule as ``log_risk_basis_shadow``). None when either
    the honest basis or the threshold is unavailable."""
    if honest_usd is None or threshold_usd is None:
        return None
    try:
        c, h, t = float(current_usd), float(honest_usd), float(threshold_usd)
    except (TypeError, ValueError):
        return None
    return (c <= t < h) or (h <= t < c)


def _round2(x):
    try:
        return round(float(x), 2) if x is not None else None
    except (TypeError, ValueError):
        return None


def build_arm_evidence_row(consumer, cycle_id, *, current_usd, honest_usd,
                           threshold_usd=None, threshold_pct=None,
                           would_flip_override=_UNSET, positions=None,
                           position_count=None, coverage_readable=None,
                           coverage_total=None, is_book=False,
                           unavailable_reason=None, context=None):
    """Build ONE typed arm-evidence row. Pure/deterministic; carries the full
    P0-B observe→enforce contract (cycle+consumer identity, both bases + values,
    coverage, would_flip against the REAL threshold in play, typed
    not-applicable/unavailable reason, position count, known-at, code SHA).

    - ``is_book`` + ``position_count == 0`` → ``not_applicable_empty_book``.
    - honest basis absent → typed ``unavailable`` (never a fabricated value).
    - ``would_flip_override`` lets a consumer whose threshold is NOT a dollar
      cut (the utilization gate's allow/block flip against a % cap) supply the
      real flip; otherwise it is computed from the dollar threshold."""
    # coverage / position count derivation
    if coverage_readable is None and coverage_total is None and positions is not None:
        coverage_readable, coverage_total = _coverage_counts(positions)
    if position_count is None and positions is not None:
        position_count = len(positions)

    reason = unavailable_reason
    status = "ok"
    if unavailable_reason is not None:
        status = "unavailable"
    elif is_book and (position_count == 0):
        status = "not_applicable_empty_book"
        reason = "empty_book"
    elif honest_usd is None:
        status = "unavailable"
        reason = "no_usable_max_loss_total"
    elif (coverage_total is not None and coverage_readable is not None
          and 0 < coverage_readable < coverage_total):
        # some positions priced honestly, some fell back to premium — the
        # honest SUM is a mixed basis (matches the live shadow line); flag it.
        status = "ok"
        reason = "partial_max_loss_coverage"

    if status in ("not_applicable_empty_book", "unavailable"):
        would_flip = None
    elif would_flip_override is not _UNSET:
        would_flip = would_flip_override
    else:
        would_flip = _dollar_would_flip(current_usd, honest_usd, threshold_usd)

    threshold_kind = None
    if threshold_usd is not None:
        threshold_kind = "dollars"
    elif threshold_pct is not None:
        threshold_kind = "utilization_pct"

    return {
        "consumer": consumer,
        "cycle_id": cycle_id,
        "status": status,
        "current_basis": CURRENT_BASIS_NAME,
        "current_usd": _round2(current_usd),
        "honest_basis": HONEST_BASIS_NAME,
        "honest_usd": (None if status == "not_applicable_empty_book"
                       else _round2(honest_usd)),
        "would_flip": would_flip,
        "threshold_kind": threshold_kind,
        "threshold_usd": _round2(threshold_usd),
        "threshold_pct": (float(threshold_pct) if threshold_pct is not None else None),
        "coverage_readable": coverage_readable,
        "coverage_total": coverage_total,
        "position_count": position_count,
        "unavailable_reason": reason,
        "known_at": _now_iso(),
        "code_sha": _resolve_code_sha(),
        "context": context or {},
    }


def record_arm_evidence(consumer, **kwargs):
    """Called AT a comparison seam. If an ``arm_evidence_scope`` is active,
    build + append one typed row; otherwise a no-op (the ephemeral log line has
    already fired separately, and non-cycle callers — api / dev routes — record
    nothing). OBSERVE-ONLY: never raises into the decision; a build failure is
    itself folded as a typed error so it surfaces at drain time."""
    coll = _arm_evidence_ctx.get()
    if coll is None:
        return None
    try:
        row = build_arm_evidence_row(consumer, coll.cycle_id, **kwargs)
    except Exception as e:  # pragma: no cover - defensive; observe-only
        try:
            coll.errors.append(
                f"arm_evidence_build_failed:{consumer}:{type(e).__name__}")
        except Exception:
            pass
        return None
    coll.rows.append(row)
    return row


def _build_arm_payload(cycle_id, rows, errors):
    """Assemble the durable payload written under
    ``cycle_metadata.risk_basis_arm_evidence``. Separated so a persistence
    fault is injectable at ONE deepest callee for the write-failure test."""
    rows = list(rows or [])
    consumers = {}
    for r in rows:
        c = r.get("consumer")
        consumers[c] = consumers.get(c, 0) + 1
    return {
        "cycle_id": cycle_id,
        "known_at": _now_iso(),
        "code_sha": _resolve_code_sha(),
        "rows": rows,
        "consumers": consumers,
        "errors": list(errors or []),
        # 'empty' is an EXPLICIT measured-empty marker — never silence.
        "status": "ok" if rows else "empty",
    }


def persist_arm_evidence(result, rows, errors, cycle_id="cycle"):
    """Merge the drained arm evidence into
    ``result['cycle_metadata']['risk_basis_arm_evidence']`` WITHOUT clobbering
    sibling ``cycle_metadata`` keys, and fold any typed arm error (build OR
    persist) into ``result['counts']['errors']`` so the job runner classifies
    the run ``partial`` (never silent). Returns the mutated ``result``. This
    helper never raises — a fault BUILDING the payload becomes a typed error."""
    if not isinstance(result, dict):
        return result
    folded_errors = list(errors or [])
    try:
        payload = _build_arm_payload(cycle_id, rows, folded_errors)
    except Exception as e:
        payload = {
            "cycle_id": cycle_id,
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
            "rows": [],
        }
        folded_errors = folded_errors + [
            f"arm_evidence_persist_failed:{type(e).__name__}"]

    cm = result.get("cycle_metadata")
    if not isinstance(cm, dict):
        cm = {}
        result["cycle_metadata"] = cm
    cm["risk_basis_arm_evidence"] = payload

    if folded_errors:
        counts = result.get("counts")
        if not isinstance(counts, dict):
            counts = {}
            result["counts"] = counts
        counts["errors"] = int(counts.get("errors") or 0) + len(folded_errors)
    return result
