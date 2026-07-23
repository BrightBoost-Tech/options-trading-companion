"""Regime V4 parallel shadow comparison — CHILD SCORER (observe-only).

Runs RegimeEngineV4 as a parallel, observe-only comparison beside the live
RegimeEngineV3, per cycle, with ZERO new provider calls and ZERO influence on
any live decision.  This module is the CHILD side (runs on the ``background``
queue, after the V3 cycle has already returned its suggestions).

⚠ CENSUS PIN — THIS is the single production module that references
``RegimeEngineV4`` (allowlisted by ``test_regime_v4_unwired.py``).  The live
decision path (scanner / orchestrator / selector / allocator / executor) still
carries ZERO V4-engine references.  The parent capture+enqueue seam lives in
``regime_v4_shadow_capture.py`` and does NOT import the V4 engine, so the live
import graph never pulls the engine in.

Design (Audit-B contract C1–C8):
- **Inputs (C2):** the child consumes ONLY the ``basket_closes`` /
  ``basket_quotes`` the live ``compute_global_snapshot`` already fetched this
  cycle (captured into the enqueue payload) plus the already-fetched per-symbol
  earnings signal.  A :class:`CapturedBarsShim` serves that captured data and
  RAISES on any un-captured symbol — V4's ``compute()`` is otherwise unchanged,
  so a live provider call is structurally impossible in the child.  VIX is a
  permanent typed-missing (no Polygon index entitlement); V4's SPY-RV proxy is
  the honest substitute.
- **Counterfactual (C3):** the child builds a throwaway global snapshot whose
  ``state = v4_vector.regime_state`` and calls the UNCHANGED PURE
  ``RegimeEngineV3.get_effective_regime`` then the UNCHANGED PURE
  ``StrategySelector.get_candidates`` with sentiment / iv_rank held fixed.  The
  selection delta is the strategy-key set-difference vs the captured V3 live
  pool — attributable SOLELY to the V3→V4 regime swap.  No EV / rank / alloc is
  re-run (that would need fresh pricing = new provider calls).
- **Rows (C1/C5):** two scopes — ``global`` (1/cycle) and ``symbol``
  (1/scanned-symbol/cycle) — persisted to ``regime_v4_comparisons`` with
  idempotency ``(cycle_id, code_sha, scope[, symbol])``.  A missing captured
  input is a TYPED ``missing_inputs`` reason + a ``partial`` status, never a
  fabricated bar / fake-flat regime.  A table-absent DB (migration unapplied)
  is a typed no-op.  A write failure folds to ``counts.errors`` (partial), never
  silence.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from packages.quantum.analytics.regime_engine_v3 import (
    GlobalRegimeSnapshot,
    RegimeEngineV3,
    SymbolRegimeSnapshot,
)
from packages.quantum.analytics.regime_engine_v4 import RegimeEngineV4
from packages.quantum.analytics.strategy_selector import StrategySelector
from packages.quantum.common_enums import RegimeState

logger = logging.getLogger(__name__)

OBS_TABLE = "regime_v4_comparisons"
V3_MODEL_VERSION = "v3"
V4_MODEL_VERSION = "v4_continuous"

# Permanent typed-missing on the volatility dimension: no Polygon index
# entitlement means we never feed a real VIX; V4's SPY-RV proxy is the honest
# substitute (Audit-B §7.7). Not a fetch bug — recorded, not fixed.
VIX_MISSING = "vix_unavailable_no_entitlement"


class CapturedInputMissing(Exception):
    """Raised by the shim when V4 requests a symbol/quote the parent did NOT
    capture — fail-closed to a typed-missing reason, NEVER a live provider
    call."""


class CapturedBarsShim:
    """A fetch-blocking market-data view over inputs the parent already fetched.

    V4's ``compute()`` touches market data ONLY through ``daily_bars`` /
    ``snapshot_many``; both are intercepted here.  ``daily_bars`` returns the
    captured closes IGNORING the date range (correct — every V4 factor slices
    the trailing ~20 observations, so the 100d basket closes reproduce V4's
    30/60/100d windows exactly) and RAISES :class:`CapturedInputMissing` on any
    un-captured symbol.  There is NO network code path — a provider call is
    structurally impossible.  ``fetch_attempts`` counts interceptions so a test
    can assert the shim, not a provider, served every read.
    """

    def __init__(
        self,
        basket_closes: Mapping[str, List[float]],
        basket_quotes: Mapping[str, Any],
    ):
        self._closes: Dict[str, List[float]] = {
            str(sym): [float(c) for c in (closes or [])]
            for sym, closes in (basket_closes or {}).items()
        }
        self._quotes: Dict[str, Any] = dict(basket_quotes or {})
        self.fetch_attempts = 0
        self.missing_symbols: List[str] = []

    def daily_bars(self, ticker: str, start: Any = None, end: Any = None):
        del start, end  # captured factors slice trailing; date range is inert
        self.fetch_attempts += 1
        closes = self._closes.get(str(ticker))
        if not closes:
            self.missing_symbols.append(str(ticker))
            raise CapturedInputMissing(f"captured_bars_missing:{ticker}")
        # Reconstruct the minimal bar shape V4 reads (b["close"] only).
        return [{"close": c} for c in closes]

    def snapshot_many(self, symbols):
        self.fetch_attempts += 1
        return {str(s): self._quotes.get(str(s), {}) for s in (symbols or [])}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_code_sha(explicit: Optional[str] = None) -> str:
    """Deploy identity (full 40-hex or 'unknown'). Model identity is a SEPARATE
    axis (v4_model_version), never the app SHA (§10 doctrine)."""
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    try:
        from packages.quantum.observability.lineage import resolve_git_sha
        return resolve_git_sha()
    except Exception:
        return "unknown"


def _scoring_regime_from_state(state_value: str) -> str:
    """Map a 6-state regime string to the legacy 3-state scoring regime, mirroring
    RegimeEngineV3.map_to_scoring_regime (kept local so the parent captures raw
    state only — zero parent-thread computation)."""
    if state_value == RegimeState.SHOCK.value:
        return "panic"
    if state_value in (RegimeState.ELEVATED.value, RegimeState.REBOUND.value):
        return "high_vol"
    return "normal"


def _coerce_state(value: Any) -> Optional[RegimeState]:
    try:
        return RegimeState(str(value).strip().lower())
    except Exception:
        return None


def compute_selection_delta(
    v3_selection: List[str], v4_selection: List[str]
) -> Dict[str, Any]:
    """Strategy-key set-difference between the captured V3 live pool and the V4
    counterfactual pool. Order-insensitive: ``added`` = in V4 not V3, ``removed``
    = in V3 not V4, ``changed`` = either non-empty."""
    v3_set = set(v3_selection or [])
    v4_set = set(v4_selection or [])
    added = sorted(v4_set - v3_set)
    removed = sorted(v3_set - v4_set)
    return {"added": added, "removed": removed, "changed": bool(added or removed)}


def _parse_as_of(as_of: Any) -> datetime:
    if isinstance(as_of, datetime):
        return as_of
    try:
        return datetime.fromisoformat(str(as_of))
    except Exception:
        return datetime.now(timezone.utc)


def _build_event_signals(
    per_symbol: List[Mapping[str, Any]], as_of_dt: datetime
) -> Tuple[Dict[str, Dict[str, bool]], bool]:
    """Derive V4's event_signals from the already-captured per-symbol earnings
    dates: is_earnings_week when earnings falls within [as_of, as_of+7d].
    Returns (event_signals, any_earnings_seen). Never fabricates a date."""
    as_of_date = as_of_dt.date()
    signals: Dict[str, Dict[str, bool]] = {}
    any_seen = False
    for entry in per_symbol or []:
        raw = entry.get("earnings_date")
        if not raw:
            continue
        try:
            ed = date.fromisoformat(str(raw)[:10])
        except Exception:
            continue
        any_seen = True
        delta_days = (ed - as_of_date).days
        signals[str(entry.get("symbol"))] = {
            "is_earnings_week": 0 <= delta_days <= 7
        }
    return signals, any_seen


def _vector_missing_inputs(v4_vector, shim: CapturedBarsShim) -> List[str]:
    """Typed missing-input reasons from V4's own data_quality + the shim's
    captured-input misses. VIX is ALWAYS typed-missing (RV-proxy substitute)."""
    reasons: List[str] = [VIX_MISSING]
    quality = getattr(v4_vector, "data_quality", {}) or {}
    # A False quality flag means the factor degraded to its neutral default.
    for dim in ("trend", "mr", "corr", "liq"):
        if quality.get(dim) is False:
            reasons.append(f"{dim}_degraded_captured_input")
    for sym in sorted(set(shim.missing_symbols)):
        reasons.append(f"captured_input_missing:{sym}")
    return reasons


# ---------------------------------------------------------------------------
# Row builders (mirror risk_basis_shadow.build_arm_evidence_row contract)
# ---------------------------------------------------------------------------

def build_global_row(
    *,
    cycle_id: str,
    code_sha: str,
    as_of: str,
    v3_global: Mapping[str, Any],
    v4_vector,
    missing_inputs: List[str],
    status: str,
) -> Dict[str, Any]:
    v3_state = str(v3_global.get("state"))
    v3_scoring = _scoring_regime_from_state(v3_state)
    v4_label = v4_vector.label
    v4_scoring = v4_vector.scoring_regime
    return {
        "scope": "global",
        "cycle_id": cycle_id,
        "decision_event_id": None,
        "symbol": None,
        "as_of_ts": as_of,
        "known_at": _now_iso(),
        "code_sha": code_sha,
        "v3_model_version": V3_MODEL_VERSION,
        "v4_model_version": V4_MODEL_VERSION,
        "v3_state": v3_state,
        "v3_scoring_regime": v3_scoring,
        "v3_risk_score": _num(v3_global.get("risk_score")),
        "v3_risk_scaler": _num(v3_global.get("risk_scaler")),
        "v3_global_state": v3_state,
        "v4_label": v4_label,
        "v4_scoring_regime": v4_scoring,
        "v4_risk_score": _num(v4_vector.risk_score),
        "v4_risk_scaler": _num(v4_vector.risk_scaler),
        "v4_vector": v4_vector.to_dict(),
        "scoring_regime_agree": (v3_scoring == v4_scoring),
        "state_agree": (v3_state == v4_label),
        "v3_effective_regime": None,
        "v4_counterfactual_effective_regime": None,
        "v3_selection": None,
        "v4_selection": None,
        "selection_delta": None,
        "candidates_considered": None,
        "sentiment": None,
        "iv_rank": None,
        "missing_inputs": missing_inputs,
        "status": status,
    }


def build_symbol_row(
    *,
    cycle_id: str,
    code_sha: str,
    as_of: str,
    v3_global_state: str,
    entry: Mapping[str, Any],
    v4_effective: RegimeState,
    v4_selection: List[str],
    missing_inputs: List[str],
    status: str,
) -> Dict[str, Any]:
    v3_effective = str(entry.get("v3_effective_regime"))
    v3_selection = list(entry.get("v3_selection") or [])
    delta = compute_selection_delta(v3_selection, v4_selection)
    return {
        "scope": "symbol",
        "cycle_id": cycle_id,
        "decision_event_id": entry.get("decision_event_id"),
        "symbol": str(entry.get("symbol")),
        "as_of_ts": as_of,
        "known_at": _now_iso(),
        "code_sha": code_sha,
        "v3_model_version": V3_MODEL_VERSION,
        "v4_model_version": V4_MODEL_VERSION,
        "v3_state": v3_effective,
        "v3_scoring_regime": _scoring_regime_from_state(v3_effective),
        "v3_risk_score": None,
        "v3_risk_scaler": None,
        "v3_global_state": v3_global_state,
        "v4_label": v4_effective.value,
        "v4_scoring_regime": _scoring_regime_from_state(v4_effective.value),
        "v4_risk_score": None,
        "v4_risk_scaler": None,
        "v4_vector": None,
        "scoring_regime_agree": (
            _scoring_regime_from_state(v3_effective)
            == _scoring_regime_from_state(v4_effective.value)
        ),
        "state_agree": (v3_effective == v4_effective.value),
        "v3_effective_regime": v3_effective,
        "v4_counterfactual_effective_regime": v4_effective.value,
        "v3_selection": v3_selection,
        "v4_selection": list(v4_selection),
        "selection_delta": delta,
        "candidates_considered": v3_selection,
        "sentiment": entry.get("sentiment"),
        "iv_rank": _num(entry.get("iv_rank")),
        "missing_inputs": missing_inputs,
        "status": status,
    }


def _num(x: Any) -> Optional[float]:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Counterfactual (pure, reused engines)
# ---------------------------------------------------------------------------

def _counterfactual_effective(
    engine_v3: RegimeEngineV3,
    *,
    as_of: str,
    v3_symbol_state: RegimeState,
    v4_global_state: RegimeState,
    v3_global: Mapping[str, Any],
) -> RegimeState:
    """UNCHANGED PURE ``get_effective_regime`` with ONLY the global regime swapped
    to V4's. get_effective_regime reads only the two snapshots' ``.state`` — the
    other fields are copied from V3's global (audit §4.2) but never consulted."""
    v3_symbol_snap = SymbolRegimeSnapshot(
        symbol="", as_of_ts=as_of, state=v3_symbol_state, score=0.0
    )
    v4_global_snap = GlobalRegimeSnapshot(
        as_of_ts=as_of,
        state=v4_global_state,
        risk_score=_num(v3_global.get("risk_score")) or 50.0,
        risk_scaler=_num(v3_global.get("risk_scaler")) or 1.0,
        trend_score=0.0,
        vol_score=0.0,
        corr_score=0.0,
        breadth_score=0.0,
        liquidity_score=0.0,
    )
    return engine_v3.get_effective_regime(v3_symbol_snap, v4_global_snap)


# ---------------------------------------------------------------------------
# Persistence (idempotent upsert; table-absent typed no-op)
# ---------------------------------------------------------------------------

def _is_table_missing_error(exc: BaseException) -> bool:
    msg = str(getattr(exc, "message", None) or exc).lower()
    return ("does not exist" in msg or "pgrst205" in msg or "could not find the table" in msg) \
        and OBS_TABLE in msg


def _persist_rows(client: Any, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Append-only idempotent write: INSERT ... ON CONFLICT DO NOTHING on
    (cycle_id, code_sha, scope, symbol_key). A re-run under identical code is a
    no-op (the row already exists); a redeploy legitimately re-observes under a
    new code_sha (a new row). Table-absent → typed no-op; any other write failure
    → error (partial, never silent)."""
    out = {"written": 0, "table_missing": False, "errors": 0}
    if not rows:
        return out
    try:
        (
            client.table(OBS_TABLE)
            .upsert(
                rows,
                on_conflict="cycle_id,code_sha,scope,symbol_key",
                ignore_duplicates=True,
            )
            .execute()
        )
        out["written"] = len(rows)
    except Exception as exc:  # noqa: BLE001
        if _is_table_missing_error(exc):
            out["table_missing"] = True
            logger.info(
                "[REGIME_V4_OBSERVE] %s absent — typed no-op (migration unapplied)",
                OBS_TABLE,
            )
        else:
            out["errors"] = len(rows)
            logger.warning(
                "[REGIME_V4_OBSERVE] persist failed (%s): %s",
                type(exc).__name__, str(exc)[:200],
            )
    return out


# ---------------------------------------------------------------------------
# Child entrypoint
# ---------------------------------------------------------------------------

def run_regime_v4_shadow_compare(
    payload: Mapping[str, Any],
    *,
    client: Any,
) -> Dict[str, Any]:
    """Execute the observe-only V4 comparison for one captured cycle.

    Returns typed job truth: ``ok``/``status``/``counts`` — honest ``partial`` /
    ``failed`` on evidence loss; one failure never blocks the parent (the parent
    already returned).  ZERO provider calls (the shim blocks every fetch); ZERO
    writes to any live decision surface.
    """
    counts = {
        "global_rows": 0,
        "symbol_rows": 0,
        "written": 0,
        "table_missing_noops": 0,
        "abstentions": 0,
        "errors": 0,
    }

    capture = payload.get("capture")
    cycle_id = str(payload.get("cycle_id") or "").strip()
    code_sha = _resolve_code_sha(payload.get("source_code_sha"))

    if not isinstance(capture, Mapping) or not cycle_id:
        counts["errors"] = 1
        return {
            "ok": False,
            "status": "failed",
            "reason": "capture_or_cycle_id_missing",
            "counts": counts,
        }

    basket_closes = capture.get("basket_closes") or {}
    basket_quotes = capture.get("basket_quotes") or {}
    per_symbol = list(capture.get("per_symbol") or [])
    v3_global = capture.get("v3_global") or {}
    as_of = str(capture.get("as_of") or v3_global.get("as_of_ts") or _now_iso())

    # Empty ≠ failed: a capture with no basket closes is an honest UNAVAILABLE
    # observation (nothing to compare V4 against), not a crash and not a
    # fabricated flat regime.
    if not basket_closes or not v3_global.get("state"):
        counts["abstentions"] = 1
        return {
            "ok": True,
            "status": "unavailable",
            "reason": "captured_basket_or_v3_global_absent",
            "counts": counts,
            "cycle_id": cycle_id,
        }

    as_of_dt = _parse_as_of(as_of)
    shim = CapturedBarsShim(basket_closes, basket_quotes)
    event_signals, any_earnings = _build_event_signals(per_symbol, as_of_dt)

    # --- V4 over captured inputs (single unchanged code path; shim blocks I/O) ---
    try:
        v4_engine = RegimeEngineV4(market_data=shim)
        v4_vector = v4_engine.compute(
            as_of_ts=as_of_dt,
            event_signals=event_signals or None,
            vix_data=None,  # typed-missing → RV proxy (VIX_MISSING)
        )
    except Exception as exc:  # noqa: BLE001 — a V4 crash is a failed observation
        counts["errors"] = 1
        logger.warning(
            "[REGIME_V4_OBSERVE] V4 compute failed: %s", str(exc)[:200]
        )
        return {
            "ok": False,
            "status": "failed",
            "reason": f"v4_compute_error:{type(exc).__name__}",
            "counts": counts,
            "cycle_id": cycle_id,
        }

    missing_inputs = _vector_missing_inputs(v4_vector, shim)
    if not any_earnings:
        missing_inputs.append("event_signals_absent")
    # A degraded factor (captured-input miss) makes the global read PARTIAL.
    global_status = "partial" if len(missing_inputs) > 1 else "ok"

    rows: List[Dict[str, Any]] = [
        build_global_row(
            cycle_id=cycle_id,
            code_sha=code_sha,
            as_of=as_of,
            v3_global=v3_global,
            v4_vector=v4_vector,
            missing_inputs=missing_inputs,
            status=global_status,
        )
    ]
    counts["global_rows"] = 1

    # --- per-symbol counterfactual (pure reused engines) ---
    v3_global_state = str(v3_global.get("state"))
    v4_global_state = v4_vector.regime_state
    engine_v3 = RegimeEngineV3(supabase_client=None, market_data=shim)
    selector = StrategySelector()

    for entry in per_symbol:
        symbol = str(entry.get("symbol") or "").strip()
        v3_sym_state = _coerce_state(entry.get("v3_symbol_state"))
        if not symbol or v3_sym_state is None or entry.get("v3_effective_regime") is None:
            # Typed missing-input abstention — never a fabricated regime/pool.
            counts["abstentions"] += 1
            continue
        try:
            v4_effective = _counterfactual_effective(
                engine_v3,
                as_of=as_of,
                v3_symbol_state=v3_sym_state,
                v4_global_state=v4_global_state,
                v3_global=v3_global,
            )
            v4_selection = [
                str(c.get("strategy"))
                for c in selector.get_candidates(
                    ticker=symbol,
                    sentiment=entry.get("sentiment"),
                    current_price=_num(entry.get("current_price")) or 0.0,
                    iv_rank=_num(entry.get("iv_rank")),
                    effective_regime=v4_effective.value,
                )
            ]
        except Exception as exc:  # noqa: BLE001 — one symbol never sinks the job
            counts["errors"] += 1
            logger.warning(
                "[REGIME_V4_OBSERVE] symbol counterfactual failed %s: %s",
                symbol, str(exc)[:200],
            )
            continue

        rows.append(
            build_symbol_row(
                cycle_id=cycle_id,
                code_sha=code_sha,
                as_of=as_of,
                v3_global_state=v3_global_state,
                entry=entry,
                v4_effective=v4_effective,
                v4_selection=v4_selection,
                missing_inputs=[VIX_MISSING],
                status="ok",
            )
        )
        counts["symbol_rows"] += 1

    persist = _persist_rows(client, rows)
    counts["written"] = persist["written"]
    counts["errors"] += persist["errors"]
    if persist["table_missing"]:
        counts["table_missing_noops"] = len(rows)

    # Job truth: a write failure OR a V4 crash makes the observer job partial/
    # failed; a table-absent no-op and typed abstentions are honest OK.
    if counts["errors"]:
        status = "partial"
        ok = False
    else:
        status = "ok"
        ok = True
    return {
        "ok": ok,
        "status": status,
        "cycle_id": cycle_id,
        "code_sha": code_sha,
        "counts": counts,
        "v3_global_state": v3_global_state,
        "v4_label": v4_vector.label,
    }
