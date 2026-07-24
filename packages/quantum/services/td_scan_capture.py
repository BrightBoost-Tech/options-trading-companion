"""⑤ Scan-time research-candidate capture (OBSERVE-ONLY, parent thread).

Captures a compact versioned IMMUTABLE envelope for EVERY fully-constructed
candidate in a scan cycle — emitted AND about-to-be-rejected (credit spreads /
condors that die at the EV / execution-cost / spread / earnings / lifecycle /
agent gates) — with the exact legs, per-leg delta, per-leg IV threaded from the
already-fetched source chain (ZERO new provider calls), spot, dte, the scanner's
own EV, a structure-only fingerprint, and full source identities.

This is the producer half of the terminal-distribution score-on-scan observer
(the background child scores the envelopes offline). IMPORT-LOCK: this module is
pure data assembly — it NEVER imports or names the observe-only scoring package
(the scorer lives in ``scripts/analytics`` and is reached only from the job
handler). Prose refers to it as the "terminal-distribution" observer (hyphen).

NON-INTERFERENCE (contract §C8): the recorder NEVER mutates the candidate dict
or its legs — it reads and copies. The scanner's ``candidates`` output is
byte-identical whether capture is on or off. All writes are fail-soft and happen
ONCE at the scan-boundary flush (never per-candidate on the hot path); a missing
table is a typed no-op. Default OFF: unset flag → a disabled recorder → zero
envelopes, zero writes, zero latency.

BASIS: contracts = 1 (per structure-contract). H9: a leg with no source IV/delta
keeps that field None (the scorer abstains, never defaults).
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from packages.quantum.services.options_utils import compute_legs_fingerprint

logger = logging.getLogger(__name__)

ENVELOPE_TABLE = "td_scan_envelopes"
ENVELOPE_SCHEMA_VERSION = 1

# Behavioral opt-in flag (default OFF, lenient truthy). Gates capture AND the
# background enqueue. UPPERCASE env name is deliberate — the import-lock marker
# is the lowercase package string, so this name is lock-safe.
FLAG_NAME = "TERMINAL_DISTRIBUTION_SCAN_OBSERVE_ENABLED"


def td_scan_observe_enabled() -> bool:
    """Effective value of the observe-only flag. Behavioral opt-in: unset/empty
    → OFF; only an explicit truthy (1/true/yes/on) enables. This is the REAL
    parser the FLAG_ECHO reads (anti-drift) and the capture/enqueue gate."""
    raw = os.getenv(FLAG_NAME)
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


# PostgREST/Postgres "table absent" signatures (the designed state until the
# migration is applied). Column-level errors deliberately do NOT match — those
# are real failures counted loudly.
_TABLE_MISSING_MARKERS = ("pgrst205", "42p01", "could not find the table")


def _is_table_missing_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if any(m in msg for m in _TABLE_MISSING_MARKERS):
        return True
    return "does not exist" in msg and ENVELOPE_TABLE in msg


def _is_unique_violation(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "23505" in msg or "duplicate key" in msg


def _finite(x: Any) -> Optional[float]:
    if isinstance(x, bool):
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    import math
    return f if math.isfinite(f) else None


def _occ_iv_map(chain: Any) -> Dict[str, Optional[float]]:
    """Build an OCC-symbol -> IV map from the already-fetched source chain. The
    truth-layer snapshot maps implied_volatility/impliedVolatility -> ``iv`` at
    the top level of each contract (nested schema); the flat/Polygon fallback
    carries it directly. Keyed by the contract's OCC symbol so it threads onto
    the leg BY IDENTITY. A symbol absent from the chain (or a dark IV) contributes
    None — the leg stays IV-less and the challenger abstains missing_iv (H9)."""
    idx: Dict[str, Optional[float]] = {}
    if not isinstance(chain, list):
        return idx
    for c in chain:
        if not isinstance(c, dict):
            continue
        occ = c.get("contract") or c.get("ticker") or c.get("occ_symbol") or c.get("symbol")
        if not occ:
            continue
        iv = c.get("iv")
        if iv is None:
            iv = c.get("implied_volatility") or c.get("impliedVolatility")
        idx[str(occ)] = _finite(iv)
    return idx


def _provider_ts_iso(snapshot_item: Any) -> Optional[str]:
    """Deterministic provider snapshot timestamp (never wall-clock). Mirrors
    build_scan_spot_capture's as_of source so known_at is the input snapshot's
    quote ts, preserving the candidate byte-pin."""
    if not isinstance(snapshot_item, dict):
        return None
    ts_ms = snapshot_item.get("provider_ts") or (snapshot_item.get("quote") or {}).get("quote_ts")
    if ts_ms is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def build_research_candidate_envelope(
    *,
    symbol: str,
    strategy: str,
    strategy_key: Optional[str],
    legs: List[Dict[str, Any]],
    chain: Any,
    current_price: Any,
    total_ev: Any,
    net_premium: Any,
    premium_direction: Optional[str],
    dte_days: Optional[float],
    iv_rank: Any = None,
    iv_rank_quality: Any = None,
    snapshot_item: Any = None,
    code_sha: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Assemble the §7a scorable envelope from data ALREADY resident on the parent
    thread at the scan seam. Threads per-leg IV from the source chain's ``iv`` key
    (the ONE new thread — zero fetch). Returns None for a candidate with no legs
    (typed ``not_scorable`` by the caller — it never reached exact-leg
    construction). NEVER mutates ``legs`` (envelope legs are fresh copies)."""
    if not legs:
        return None
    occ_iv = _occ_iv_map(chain)
    spot_iso = _provider_ts_iso(snapshot_item)
    env_legs: List[Dict[str, Any]] = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        occ = leg.get("symbol")
        env_legs.append({
            "symbol": occ,
            "side": leg.get("side"),
            "option_type": leg.get("type"),
            "strike": leg.get("strike"),
            "expiry": leg.get("expiry"),
            "delta": _finite(leg.get("delta")),
            # ⑤ IV threaded from the source chain contract (never onto the live
            # leg — that would change candidate output). None → challenger abstains.
            "iv": occ_iv.get(str(occ)) if occ is not None else None,
            "bid": leg.get("bid"),
            "ask": leg.get("ask"),
            "mid": leg.get("mid"),
            "premium": leg.get("premium"),
        })
    if not env_legs:
        return None
    fingerprint = compute_legs_fingerprint({"legs": legs})
    return {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "symbol": symbol,
        "ticker": symbol,
        "strategy": strategy,
        "strategy_key": strategy_key,
        "candidate_fingerprint": fingerprint,
        "code_sha": code_sha,
        "known_at": spot_iso,
        "legs": env_legs,
        "net_premium": _finite(net_premium),
        "premium_direction": premium_direction,
        "contracts": 1,
        "spot": _finite(current_price),
        "spot_as_of": spot_iso,
        "spot_source": "scanner_underlying_quote_mid",
        "dte_days": dte_days,
        "risk_free_rate": 0.0,
        "iv_rank": iv_rank,
        "iv_rank_quality": iv_rank_quality,
        # production as-emitted comparator (pop absent pre-emit — the pop block
        # runs later; the stored-baseline comparator abstains without it).
        "production_ev": _finite(total_ev),
        "production_pop": None,
    }


def _dte_days_from_legs(legs: List[Dict[str, Any]], known_at_iso: Optional[str]) -> Optional[float]:
    """max(leg expiry) − known_at date, matching challenger_study's derivation.
    Returns None if no parseable expiry / known_at (the challenger abstains
    invalid_dte)."""
    if not known_at_iso:
        return None
    try:
        known = datetime.fromisoformat(known_at_iso.replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None
    max_exp: Optional[date] = None
    for leg in legs or []:
        raw = (leg or {}).get("expiry")
        if not raw:
            continue
        try:
            exp = datetime.fromisoformat(str(raw)[:10]).date()
        except (TypeError, ValueError):
            continue
        if max_exp is None or exp > max_exp:
            max_exp = exp
    if max_exp is None:
        return None
    return float((max_exp - known).days)


class ScanEnvelopeRecorder:
    """Per-cycle, thread-safe, fail-soft recorder for scan-time envelopes.

    Created once per ``scan_for_opportunities`` cycle (like the quote-provenance
    recorder). ``record()`` runs on the per-symbol thread and ONLY appends a
    fresh envelope to an in-memory list (no DB call on the hot path).
    ``flush(candidates)`` runs once at the scan boundary: it resolves the
    ``emitted`` flag from the emitted candidates' fingerprints and writes all
    envelopes in a single batched insert, fail-soft (typed no-op on a missing
    table). Disabled (flag OFF or no client) → every method is a no-op, so the
    scanner is byte-identical and adds zero latency."""

    def __init__(
        self,
        supabase: Any,
        cycle_date: str,
        cycle_id: Optional[str] = None,
        user_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        code_sha: Optional[str] = None,
    ):
        self._sb = supabase
        self.cycle_date = cycle_date
        self.cycle_id = str(cycle_id) if cycle_id else str(uuid.uuid4())
        self.user_id = user_id
        flag_on = td_scan_observe_enabled() if enabled is None else bool(enabled)
        self._disabled = (supabase is None) or (not flag_on)
        self._lock = threading.Lock()
        self._envelopes: List[Dict[str, Any]] = []
        self._table_missing = False
        self._warned_write_failure = False
        if code_sha is not None:
            self._code_sha = code_sha
        else:
            try:
                from packages.quantum.observability.lineage import get_code_sha
                self._code_sha = get_code_sha()
            except Exception:
                self._code_sha = "unknown"
        self.counters: Dict[str, int] = {
            "captured": 0,
            "written": 0,
            "emitted": 0,
            "rejected": 0,
            "write_failures": 0,
            "table_missing_noops": 0,
            "duplicate_acks": 0,
        }

    @property
    def enabled(self) -> bool:
        return not self._disabled

    @classmethod
    def create(
        cls,
        supabase: Any,
        cycle_date: str,
        user_id: Optional[str] = None,
    ) -> "ScanEnvelopeRecorder":
        """Build a recorder, linking cycle_id to the active replay
        DecisionContext when one exists (REPLAY_ENABLE on) — the SAME id the
        background child is enqueued with at the suggestions_open tail — else a
        fresh per-cycle UUID. Fail-soft resolution."""
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
        return cls(supabase, cycle_date=cycle_date, cycle_id=cycle_id, user_id=user_id)

    def record(
        self,
        *,
        symbol: str,
        strategy: str,
        strategy_key: Optional[str],
        legs: List[Dict[str, Any]],
        chain: Any,
        current_price: Any,
        total_ev: Any,
        net_premium: Any,
        premium_direction: Optional[str],
        snapshot_item: Any = None,
        iv_rank: Any = None,
        iv_rank_quality: Any = None,
    ) -> None:
        """Capture ONE fully-constructed candidate. Runs on the per-symbol thread;
        appends only (no DB call). Absolute fail-soft — a capture error never
        breaks the scan. NEVER mutates ``legs`` / the candidate."""
        if self._disabled:
            return
        try:
            spot_iso = _provider_ts_iso(snapshot_item)
            dte_days = _dte_days_from_legs(legs, spot_iso)
            env = build_research_candidate_envelope(
                symbol=symbol,
                strategy=strategy,
                strategy_key=strategy_key,
                legs=legs,
                chain=chain,
                current_price=current_price,
                total_ev=total_ev,
                net_premium=net_premium,
                premium_direction=premium_direction,
                dte_days=dte_days,
                iv_rank=iv_rank,
                iv_rank_quality=iv_rank_quality,
                snapshot_item=snapshot_item,
                code_sha=self._code_sha,
            )
            if env is None:
                return
            with self._lock:
                self._envelopes.append(env)
                self.counters["captured"] += 1
        except Exception as exc:  # absolute fail-soft
            logger.debug("[TD_SCAN_CAPTURE] record failed (non-fatal): %s", exc)

    def _emitted_fingerprints(self, candidates: Any) -> set:
        fps: set = set()
        for c in candidates or []:
            try:
                legs = (c or {}).get("legs")
                if legs:
                    fps.add(compute_legs_fingerprint({"legs": legs}))
            except Exception:
                continue
        return fps

    def flush(self, candidates: Any = None) -> Dict[str, Any]:
        """Resolve ``emitted`` from the emitted candidate set and write all
        captured envelopes in ONE batched insert (fail-soft; typed no-op on a
        missing table). Idempotent-safe: a duplicate (cycle_id, fingerprint) on a
        re-scan is ACKed, never a second row. Never raises."""
        if self._disabled:
            return {"status": "disabled", **self.counters}
        with self._lock:
            envelopes = list(self._envelopes)
        if not envelopes:
            return {"status": "empty", **self.counters}
        emitted_fps = self._emitted_fingerprints(candidates)
        # Dedup by fingerprint (identical structures ARE the same candidate).
        seen: set = set()
        rows: List[Dict[str, Any]] = []
        for env in envelopes:
            fp = env.get("candidate_fingerprint")
            if fp in seen:
                continue
            seen.add(fp)
            emitted = fp in emitted_fps
            reject_reason = None if emitted else "unattributed_post_ev"
            reject_gate = None if emitted else "post_ev_gate"
            if emitted:
                self.counters["emitted"] += 1
            else:
                self.counters["rejected"] += 1
            rows.append({
                "cycle_id": self.cycle_id,
                "cycle_date": self.cycle_date,
                "user_id": self.user_id,
                "symbol": env.get("symbol"),
                "strategy": env.get("strategy"),
                "strategy_key": env.get("strategy_key"),
                "candidate_fingerprint": fp,
                "emitted": emitted,
                "reject_reason": reject_reason,
                "reject_gate": reject_gate,
                "code_sha": self._code_sha,
                "known_at": env.get("known_at"),
                "envelope": {**env, "emitted": emitted,
                             "reject_reason": reject_reason,
                             "reject_gate": reject_gate},
            })
        if not rows:
            return {"status": "empty", **self.counters}
        try:
            self._sb.table(ENVELOPE_TABLE).insert(rows).execute()
            self.counters["written"] += len(rows)
            return {"status": "ok", "cycle_id": self.cycle_id, **self.counters}
        except Exception as exc:
            if _is_table_missing_error(exc):
                self._table_missing = True
                self.counters["table_missing_noops"] += 1
                logger.warning(
                    "[TD_SCAN_CAPTURE] table %s missing — typed no-op "
                    "(migration unapplied): %s", ENVELOPE_TABLE, exc)
                return {"status": "table_missing", **self.counters}
            if _is_unique_violation(exc):
                self.counters["duplicate_acks"] += 1
                logger.info("[TD_SCAN_CAPTURE] duplicate envelope batch ACKed "
                            "(re-scan of cycle %s)", self.cycle_id)
                return {"status": "duplicate_ack", **self.counters}
            self.counters["write_failures"] += 1
            if not self._warned_write_failure:
                self._warned_write_failure = True
                logger.warning(
                    "[TD_SCAN_CAPTURE] envelope flush failed (non-fatal): %s", exc)
            return {"status": "write_failed", **self.counters}

    def counters_dict(self) -> Dict[str, Any]:
        return {"cycle_id": self.cycle_id, "enabled": self.enabled, **self.counters}
