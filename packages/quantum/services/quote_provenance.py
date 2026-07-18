"""Option-quote provenance recorder — Lane 4C, OBSERVE-ONLY.

Makes quote-source / known-at / quality evidence DURABLE so a
429/fallback cycle can be adjudicated after the fact: was the Polygon
fallback truth-preserving (same executable picture) or did the source
switch change a spread-gate verdict (source-driven opportunity loss)?
The 2026-07-16 gap: this evidence lived only in ephemeral log lines
("[SNAPSHOT] Alpaca missed N option(s), falling back to Polygon"), so
the verdict-change question was NOT-PROVEN.

Design contract (all three enforced by tests):

1. OBSERVE-ONLY — no method influences any scan decision. The recorder
   is threaded per-cycle the same way RejectionStats is (constructed in
   ``scan_for_opportunities``, attached to the cycle's
   ``MarketDataTruthLayer`` instance — never a module global).
2. FAIL-SOFT — every public method swallows its own errors; persist
   failures increment a LOUD counter surfaced by ``flush()``. A missing
   table (the migration ships unapplied) is a TYPED no-op
   (``schema_absent``), never an exception.
3. NO SECRETS — rows are scrubbed at the single persistence seam:
   key-like dict keys are redacted and ``apiKey=`` / ``Bearer`` value
   patterns removed. The truth layer's key-prefix LOG line is
   deliberately NOT copied into durable rows.

Volume is bounded per cycle: always-persist classes (anomalous fetch
events, spread-REJECTED leg sets, SELECTED leg sets) + deterministic
1-in-N sampling for the rest + a hard per-cycle row cap. See the
migration (supabase/migrations/20260717120000_option_quote_provenance.sql)
for the schema + retention notes.
"""

import hashlib
import logging
import os
import re
import threading
from datetime import date, datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TABLE_NAME = "option_quote_provenance"

# Defaults (env-overridable, read at construction time)
DEFAULT_MAX_ROWS_PER_CYCLE = 250
DEFAULT_SAMPLE_N = 10
DEFAULT_MAX_QUOTE_NOTES = 2000

_EXPLICIT_FALSY = {"0", "false", "no", "off"}

# Key names that must never reach a durable row with their value intact.
_SECRET_KEY_RE = re.compile(
    r"(?i)(api[-_]?key|secret|token|authoriz|credential|passw|apca)"
)
# Value patterns (query-string keys, bearer headers) scrubbed from strings.
_SECRET_VALUE_RE = re.compile(
    r"(?i)(apiKey=[^&\s'\"]+|Bearer\s+[A-Za-z0-9._\-]+)"
)

# Error signatures meaning "the table does not exist" (migration unapplied):
# Postgres 42P01 / PostgREST PGRST205 / plain-text variants.
_SCHEMA_ABSENT_MARKERS = (
    "42p01",
    "pgrst205",
    "does not exist",
    "could not find the table",
)


def is_provenance_enabled() -> bool:
    """QUOTE_PROVENANCE_ENABLED — default-ON additive observability.

    Unset/empty -> ON; only an explicit falsy (0/false/no/off) disables.
    This is a capture kill switch, not a behavioral flag: scan verdicts
    are byte-identical either way (pinned by the immutability test).
    """
    raw = os.getenv("QUOTE_PROVENANCE_ENABLED", "")
    return raw.strip().lower() not in _EXPLICIT_FALSY


def scrub_text(value: str) -> str:
    """Remove apiKey=/Bearer-style secret material from a string."""
    return _SECRET_VALUE_RE.sub("[REDACTED]", value)


def scrub(obj: Any) -> Any:
    """Recursively redact secret-named keys and secret-shaped values."""
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if _SECRET_KEY_RE.search(str(k)):
                out[str(k)] = "[REDACTED]"
            else:
                out[str(k)] = scrub(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [scrub(x) for x in obj]
    if isinstance(obj, str):
        return scrub_text(obj)
    return obj


def _bare(contract: Optional[str]) -> str:
    """Canonical note key: OCC symbol without the O: prefix."""
    s = str(contract or "")
    return s[2:] if s.startswith("O:") else s


def _to_ms(ts: Any) -> Optional[int]:
    """Normalize a provider timestamp (s/ms/us/ns) to milliseconds."""
    if ts is None:
        return None
    try:
        v = float(ts)
    except (TypeError, ValueError):
        return None
    if v > 1e16:      # nanoseconds
        return int(v / 1e6)
    if v > 1e14:      # microseconds
        return int(v / 1e3)
    if v > 1e11:      # already milliseconds
        return int(v)
    return int(v * 1000)


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def leg_fingerprint(legs: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    """Deterministic identity for a leg set (contract|side|strike|expiry)."""
    if not legs:
        return None
    parts = sorted(
        "|".join(
            str(leg.get(k) if not isinstance(leg.get(k), float)
                else round(leg.get(k), 4))
            for k in ("symbol", "side", "strike", "expiry")
        )
        for leg in legs
        if isinstance(leg, dict)
    )
    if not parts:
        return None
    return hashlib.sha256(";".join(parts).encode("utf-8")).hexdigest()[:16]


class QuoteProvenanceRecorder:
    """Per-cycle buffer of quote-provenance evidence, flushed in one
    batched, sampled, capped, scrubbed insert at cycle end.

    Threaded per-cycle exactly like RejectionStats (constructor DI of the
    supabase client + cycle_date); thread-safe for the scanner's
    ThreadPoolExecutor workers.
    """

    def __init__(
        self,
        supabase: Optional[Any] = None,
        cycle_date: Optional[date] = None,
        job_run_id: Optional[str] = None,
        enabled: Optional[bool] = None,
    ):
        self._supabase = supabase
        self._cycle_date = cycle_date
        self._job_run_id = job_run_id
        self._enabled = is_provenance_enabled() if enabled is None else bool(enabled)
        self._lock = threading.Lock()

        # In-memory provenance notes (contract -> note) joined into leg sets.
        self._quote_notes: Dict[str, Dict[str, Any]] = {}
        # Per-underlying chain source (leg join fallback when no per-leg note).
        self._chain_notes: Dict[str, Dict[str, Any]] = {}
        # Buffered candidate rows (policy applied at flush).
        self._fetch_events: List[Dict[str, Any]] = []
        self._leg_sets: List[Dict[str, Any]] = []
        self._selected: set = set()

        try:
            self._max_rows = int(os.getenv(
                "QUOTE_PROVENANCE_MAX_ROWS_PER_CYCLE",
                str(DEFAULT_MAX_ROWS_PER_CYCLE)))
        except ValueError:
            self._max_rows = DEFAULT_MAX_ROWS_PER_CYCLE
        try:
            self._sample_n = max(1, int(os.getenv(
                "QUOTE_PROVENANCE_SAMPLE_N", str(DEFAULT_SAMPLE_N))))
        except ValueError:
            self._sample_n = DEFAULT_SAMPLE_N
        try:
            self._max_notes = int(os.getenv(
                "QUOTE_PROVENANCE_MAX_QUOTE_NOTES",
                str(DEFAULT_MAX_QUOTE_NOTES)))
        except ValueError:
            self._max_notes = DEFAULT_MAX_QUOTE_NOTES

        # LOUD counters (surfaced via flush() / counts()).
        self._persist_failures = 0
        self._schema_absent = False
        self._schema_absent_noops = 0
        self._rows_written = 0
        self._dropped_over_cap = 0
        self._sampled_out = 0
        self._notes_dropped = 0
        self._buffer_dropped = 0

    # ------------------------------------------------------------------
    # Properties / reporting
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    def counts(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "rows_written": self._rows_written,
                "persist_failures": self._persist_failures,
                "schema_absent": self._schema_absent,
                "schema_absent_noops": self._schema_absent_noops,
                "dropped_over_cap": self._dropped_over_cap,
                "sampled_out": self._sampled_out,
                "notes_dropped": self._notes_dropped,
                "buffer_dropped": self._buffer_dropped,
                "buffered_fetch_events": len(self._fetch_events),
                "buffered_leg_sets": len(self._leg_sets),
            }

    # ------------------------------------------------------------------
    # Note surface (in-memory only; joined into leg-set rows)
    # ------------------------------------------------------------------
    def note_quote(
        self,
        contract: str,
        *,
        source: str,
        bid: Any = None,
        ask: Any = None,
        mid: Any = None,
        quote_ts: Any = None,
        stale_age_ms: Any = None,
        fallback_reason: Optional[str] = None,
        http_status: Optional[int] = None,
        from_cache: bool = False,
        requested_at: Optional[str] = None,
        received_at: Optional[str] = None,
    ) -> None:
        """Record what a source RETURNED for one option contract."""
        if not self._enabled:
            return
        try:
            b, a = _num(bid), _num(ask)
            note = {
                "source": str(source or "unknown"),
                "bid": b,
                "ask": a,
                "mid": _num(mid),
                "quote_ts_ms": _to_ms(quote_ts),
                "stale_age_ms": _num(stale_age_ms),
                "fallback_reason": fallback_reason,
                "http_status": http_status,
                "from_cache": bool(from_cache),
                "requested_at": requested_at,
                "received_at": received_at,
                "crossed": (b is not None and a is not None
                            and b > 0 and a > 0 and a < b),
                "zero_bid": (b is None or b <= 0),
            }
            key = _bare(contract)
            with self._lock:
                if key in self._quote_notes or len(self._quote_notes) < self._max_notes:
                    self._quote_notes[key] = note
                else:
                    self._notes_dropped += 1
        except Exception:
            logger.debug("quote_provenance.note_quote failed", exc_info=True)

    def note_chain(
        self,
        underlying: str,
        *,
        source: str,
        fallback_reason: Optional[str] = None,
        contracts_count: Optional[int] = None,
        from_cache: bool = False,
    ) -> None:
        """Record which source served the option CHAIN for an underlying."""
        if not self._enabled:
            return
        try:
            with self._lock:
                self._chain_notes[str(underlying)] = {
                    "source": str(source or "unknown"),
                    "fallback_reason": fallback_reason,
                    "contracts_count": contracts_count,
                    "from_cache": bool(from_cache),
                }
        except Exception:
            logger.debug("quote_provenance.note_chain failed", exc_info=True)

    # ------------------------------------------------------------------
    # Truth-layer boundary events
    # ------------------------------------------------------------------
    @staticmethod
    def _derive_fallback_reason(
        fetch_meta: Optional[Dict[str, Any]],
        had_misses: bool,
    ) -> Optional[str]:
        """429 > error > miss precedence, from the boundary's request log."""
        requests_log = (fetch_meta or {}).get("requests", [])
        statuses = [r.get("status") for r in requests_log]
        if 429 in statuses:
            return "429"
        if any(r.get("error") for r in requests_log):
            return "error"
        if any(s is not None and s != 200 for s in statuses):
            return "error"
        if had_misses:
            return "miss"
        return None

    def record_snapshot_boundary(
        self,
        *,
        requested_options: List[str],
        alpaca_snaps: Dict[str, Dict],
        polygon_snaps: Dict[str, Dict],
        dark: List[str],
        fetch_meta: Optional[Dict[str, Any]],
        requested_at: Optional[str],
        received_at: Optional[str],
    ) -> None:
        """One snapshot_many options-path call: notes + one fetch event."""
        if not self._enabled:
            return
        try:
            had_misses = bool(polygon_snaps) or bool(dark)
            reason = self._derive_fallback_reason(fetch_meta, had_misses)

            for ticker, snap in (alpaca_snaps or {}).items():
                q = (snap or {}).get("quote", {}) or {}
                self.note_quote(
                    ticker, source="alpaca",
                    bid=q.get("bid"), ask=q.get("ask"), mid=q.get("mid"),
                    quote_ts=snap.get("provider_ts") or q.get("quote_ts"),
                    stale_age_ms=snap.get("staleness_ms"),
                    requested_at=requested_at, received_at=received_at,
                )
            for ticker, snap in (polygon_snaps or {}).items():
                q = (snap or {}).get("quote", {}) or {}
                self.note_quote(
                    ticker, source="polygon_fallback",
                    bid=q.get("bid"), ask=q.get("ask"), mid=q.get("mid"),
                    quote_ts=snap.get("provider_ts") or q.get("quote_ts"),
                    stale_age_ms=snap.get("staleness_ms"),
                    fallback_reason=reason,
                    requested_at=requested_at, received_at=received_at,
                )

            requests_log = (fetch_meta or {}).get("requests", [])
            statuses = [r.get("status") for r in requests_log]
            served_alpaca = len(alpaca_snaps or {})
            served_fallback = len(polygon_snaps or {})
            if served_alpaca and served_fallback:
                src = "mixed"
            elif served_fallback:
                src = "polygon_fallback"
            elif served_alpaca:
                src = "alpaca"
            else:
                src = "unknown"
            event = {
                "record_type": "fetch_event",
                "boundary": "snapshot_many_options",
                "source": src,
                "fallback_reason": reason,
                "http_statuses": statuses,
                "requested_at": requested_at,
                "received_at": received_at,
                "details": {
                    "requested": len(requested_options or []),
                    "served_alpaca": served_alpaca,
                    "served_polygon_fallback": served_fallback,
                    "dark": list(dark or [])[:20],
                    "requests": requests_log[:20],
                },
                "_always": reason is not None,
            }
            with self._lock:
                if len(self._fetch_events) < self._max_rows * 2:
                    self._fetch_events.append(event)
                else:
                    self._buffer_dropped += 1
        except Exception:
            logger.debug(
                "quote_provenance.record_snapshot_boundary failed",
                exc_info=True,
            )

    def record_chain_boundary(
        self,
        underlying: str,
        *,
        source: str,
        contracts_count: int,
        fetch_meta: Optional[Dict[str, Any]],
        requested_at: Optional[str],
        received_at: Optional[str],
    ) -> None:
        """One option_chain fetch: chain note + one fetch event."""
        if not self._enabled:
            return
        try:
            fell_back = source == "polygon_fallback"
            reason = self._derive_fallback_reason(fetch_meta, fell_back)
            if not fell_back:
                # Alpaca served the chain: any earlier non-200 was recovered
                # within the boundary; only surface it in the statuses list.
                reason = None
            self.note_chain(
                underlying, source=source, fallback_reason=reason,
                contracts_count=contracts_count,
            )
            requests_log = (fetch_meta or {}).get("requests", [])
            event = {
                "record_type": "fetch_event",
                "boundary": "option_chain",
                "symbol": str(underlying),
                "source": source,
                "fallback_reason": reason,
                "http_statuses": [r.get("status") for r in requests_log],
                "requested_at": requested_at,
                "received_at": received_at,
                "details": {
                    "contracts_count": contracts_count,
                    "pages": len(requests_log),
                    "requests": requests_log[:20],
                },
                "_always": reason is not None,
            }
            with self._lock:
                if len(self._fetch_events) < self._max_rows * 2:
                    self._fetch_events.append(event)
                else:
                    self._buffer_dropped += 1
        except Exception:
            logger.debug(
                "quote_provenance.record_chain_boundary failed", exc_info=True
            )

    # ------------------------------------------------------------------
    # Scanner spread-gate verdicts
    # ------------------------------------------------------------------
    def record_spread_verdict(
        self,
        *,
        symbol: str,
        strategy_key: Optional[str],
        verdict: str,
        threshold: Any,
        option_spread_pct: Any,
        reject_reason: Optional[str] = None,
        is_condor: bool = False,
        is_credit_spread: bool = False,
        combo_source: Optional[str] = None,
        combo_width_share: Any = None,
        entry_cost_share: Any = None,
        max_loss_share: Any = None,
        legs: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """One spread-gate evaluation of a candidate leg set.

        The verdict/threshold are the gate's OWN values, passed through —
        the recorder computes nothing that could disagree with the gate.
        """
        if not self._enabled:
            return
        try:
            if is_condor:
                denominator = "max_leg_spread_pct"
            elif is_credit_spread:
                denominator = "max_loss"
            else:
                denominator = "entry_cost"

            leg_rows: List[Dict[str, Any]] = []
            leg_sources: List[str] = []
            leg_fallback_reasons: List[str] = []
            with self._lock:
                notes = dict(self._quote_notes)
                chain_note = self._chain_notes.get(str(symbol))
            for leg in (legs or []):
                if not isinstance(leg, dict):
                    continue
                contract = _bare(leg.get("symbol"))
                b, a = _num(leg.get("bid")), _num(leg.get("ask"))
                note = notes.get(contract)
                if note is not None:
                    src = note.get("source", "unknown")
                    if note.get("fallback_reason"):
                        leg_fallback_reasons.append(note["fallback_reason"])
                elif chain_note is not None:
                    src = chain_note.get("source", "unknown")
                    if chain_note.get("fallback_reason"):
                        leg_fallback_reasons.append(
                            chain_note["fallback_reason"])
                else:
                    src = "unknown"
                if src != "unknown":
                    leg_sources.append(
                        "polygon_fallback" if src.startswith("polygon")
                        else src
                    )
                leg_rows.append({
                    "contract": contract,
                    "side": leg.get("side"),
                    "strike": _num(leg.get("strike")),
                    "expiry": leg.get("expiry"),
                    "bid": b,
                    "ask": a,
                    "mid": _num(leg.get("mid") or leg.get("premium")),
                    "source": src,
                    "quote_ts_ms": (note or {}).get("quote_ts_ms"),
                    "stale_age_ms": (note or {}).get("stale_age_ms"),
                    "from_cache": (note or {}).get("from_cache"),
                    "crossed": (b is not None and a is not None
                                and b > 0 and a > 0 and a < b),
                    "zero_bid": (b is None or b <= 0),
                })

            uniq = set(leg_sources)
            if not uniq:
                agg_source = "unknown"
            elif len(uniq) == 1:
                agg_source = uniq.pop()
            else:
                agg_source = "mixed"

            row = {
                "record_type": "leg_set",
                "boundary": "spread_gate",
                "symbol": str(symbol),
                "strategy_key": strategy_key,
                "source": agg_source,
                "fallback_reason": (leg_fallback_reasons[0]
                                    if leg_fallback_reasons else None),
                "verdict": verdict,
                "reject_reason": reject_reason,
                "threshold": _num(threshold),
                "option_spread_pct": _num(option_spread_pct),
                "spread_basis": {
                    "denominator_basis": denominator,
                    "combo_source": combo_source,
                    "combo_width_share": _num(combo_width_share),
                    "entry_cost_share": _num(entry_cost_share),
                    "max_loss_share": _num(max_loss_share),
                },
                "legs": leg_rows,
                "leg_fingerprint": leg_fingerprint(legs),
                "crossed": any(l.get("crossed") for l in leg_rows),
                "zero_bid": any(l.get("zero_bid") for l in leg_rows),
            }
            with self._lock:
                if len(self._leg_sets) < self._max_rows * 2:
                    self._leg_sets.append(row)
                else:
                    self._buffer_dropped += 1
        except Exception:
            logger.debug(
                "quote_provenance.record_spread_verdict failed", exc_info=True
            )

    def mark_selected(self, symbol: str, strategy_key: Optional[str]) -> None:
        """Stamp (symbol, strategy) as EMITTED — its leg-set rows persist
        unconditionally at flush (never sampled out)."""
        if not self._enabled:
            return
        try:
            with self._lock:
                self._selected.add((str(symbol), str(strategy_key or "")))
        except Exception:
            logger.debug("quote_provenance.mark_selected failed", exc_info=True)

    # ------------------------------------------------------------------
    # Flush (single persistence seam: sampling, cap, scrub, batch insert)
    # ------------------------------------------------------------------
    def _is_schema_absent_error(self, exc: BaseException) -> bool:
        msg = str(exc).lower()
        return any(marker in msg for marker in _SCHEMA_ABSENT_MARKERS)

    def flush(self) -> Dict[str, Any]:
        """Apply the persistence policy and write one batched insert.

        Never raises. Returns the counters snapshot (loud on failure).
        """
        try:
            return self._flush_inner()
        except Exception:
            # Belt + suspenders: flush must never break the scan.
            logger.warning("quote_provenance.flush failed", exc_info=True)
            with self._lock:
                self._persist_failures += 1
            return self.counts()

    def _flush_inner(self) -> Dict[str, Any]:
        if not self._enabled or self._supabase is None:
            return self.counts()

        with self._lock:
            fetch_events = list(self._fetch_events)
            leg_sets = list(self._leg_sets)
            selected = set(self._selected)
            self._fetch_events = []
            self._leg_sets = []

        always_rows: List[Dict[str, Any]] = []
        sampled_pool: List[Dict[str, Any]] = []

        for row in leg_sets:
            is_selected = (row.get("symbol"),
                           str(row.get("strategy_key") or "")) in selected
            row["selected"] = is_selected
            if row.get("verdict") == "rejected" or is_selected:
                always_rows.append(row)
            else:
                sampled_pool.append(row)

        anomalous_events = [e for e in fetch_events if e.get("_always")]
        clean_events = [e for e in fetch_events if not e.get("_always")]

        kept_sampled: List[Dict[str, Any]] = []
        sampled_out = 0
        for idx, row in enumerate(clean_events + sampled_pool):
            if idx % self._sample_n == 0:
                row["sampled"] = True
                kept_sampled.append(row)
            else:
                sampled_out += 1

        # Priority order under the cap: the anomalous / decision-bearing
        # rows survive first.
        ordered = anomalous_events + always_rows + kept_sampled
        dropped = 0
        if len(ordered) > self._max_rows:
            dropped = len(ordered) - self._max_rows
            ordered = ordered[: self._max_rows]

        with self._lock:
            self._sampled_out += sampled_out
            self._dropped_over_cap += dropped

        if not ordered:
            return self.counts()

        cycle_iso = (self._cycle_date.isoformat()
                     if self._cycle_date is not None else None)
        final_rows: List[Dict[str, Any]] = []
        for row in ordered:
            row.pop("_always", None)
            row.setdefault("sampled", False)
            row.setdefault("selected", False)
            if cycle_iso is not None:
                row["cycle_date"] = cycle_iso
            if self._job_run_id is not None:
                row["job_run_id"] = self._job_run_id
            final_rows.append(scrub(row))

        try:
            chunk_size = 100
            for i in range(0, len(final_rows), chunk_size):
                self._supabase.table(TABLE_NAME).insert(
                    final_rows[i:i + chunk_size]
                ).execute()
            with self._lock:
                self._rows_written += len(final_rows)
        except Exception as exc:  # noqa: BLE001 — classified below
            if self._is_schema_absent_error(exc):
                with self._lock:
                    self._schema_absent = True
                    self._schema_absent_noops += 1
                logger.warning(
                    "option_quote_provenance table absent — provenance "
                    "no-op (migration unapplied); rows_dropped=%d",
                    len(final_rows),
                )
            else:
                with self._lock:
                    self._persist_failures += 1
                logger.warning(
                    "quote_provenance persist FAILED (rows=%d): %s",
                    len(final_rows), exc,
                )
        return self.counts()
