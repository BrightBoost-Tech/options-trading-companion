from typing import List, Dict, Optional
import logging
import os
from datetime import datetime, timedelta
from supabase import Client
import numpy as np
import sys
import os

# Fix import for when running from different contexts
from packages.quantum.market_data import PolygonService
from packages.quantum.services.earnings_calendar_service import EarningsCalendarService
from packages.quantum.observability.alerts import alert
from packages.quantum.analytics import option_liquidity as _option_liquidity

logger = logging.getLogger(__name__)

class UniverseService:
    # Top 50 liquid tickers + broad market ETFs
    BASE_UNIVERSE = [
        "SPY", "QQQ", "IWM", "DIA", "GLD", "TLT", "XLK", "XLF", "XLV", "XLY",
        "XLP", "XLE", "XLI", "XLB", "XLC", "XLU", "SMH", "HYG", "EEM", "FXI",
        "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "NVDA", "AMD",
        "NFLX", "INTC", "CSCO", "CMCSA", "PEP", "AVGO", "TXN", "ADBE", "QCOM",
        # FISV removed 2026-06-05: deactivated 2026-05-19 (corp action) but
        # still listed here — sync_universe upserts is_active=True for every
        # BASE_UNIVERSE member, so any universe_sync run would have silently
        # REACTIVATED it. Removal keeps the deactivation durable.
        "COST", "TMUS", "AMGN", "CHTR", "SBUX", "PYPL", "INTU", "GILD",
        "BKNG", "ADP", "ISRG", "MDLZ", "REGN", "VRTX", "CSX", "MU", "AMAT",
        # micro_live $500 capital additions — cheap-options names with deep ATM OI.
        # Liquidity evidence + rejection rationale for GE/PLTR/NIO in
        # docs/micro_live_config.md.
        "F", "BAC", "SOFI", "T", "KO", "VZ",
        # 2026-04-28 sub-$50 expansion to broaden scanner reach for micro tier.
        # Selected for established options markets and sub-$50 underlyings;
        # mid-cap mix avoids the FXI-style penny-premium spread blowout (>$15
        # each). Travel pair (AAL+CCL) intentionally limited to two names to
        # cap concentration. Backlog #87b.
        "PFE", "WBD", "AAL", "CCL", "KMI", "DKNG", "EWZ", "LYFT",
    ]

    def __init__(self, supabase: Client, polygon_service: PolygonService = None):
        self.supabase = supabase
        self.polygon = polygon_service or PolygonService()
        self.earnings_service = EarningsCalendarService(self.polygon)
        # Reporting-only handoff to options_scanner. Values describe this
        # instance's most recent selection; None means the DB measurement was
        # unavailable, never a fabricated zero.
        self.last_selection_counts = {
            "active_universe_count": None,
            "selected_symbol_count": None,
            "selection_source": "not_run",
        }

    # Int-like keys that must be sanitized for Postgres BigInt
    INT_LIKE_KEYS = {
        "market_cap", "volume", "avg_volume", "avg_volume_30d",
        "shares_outstanding", "open_interest", "timestamp_ms",
        "liquidity_score"
    }

    # Polygon /v3/reference/tickers `type` values for exchange-traded
    # products that LEGITIMATELY carry no market_cap (ETF/ETN/trust/
    # fund shells). For these, the size component scores on notional
    # dollar volume instead of zeroing — the 2026-06-05 inverted-
    # selection fix: SPY/QQQ/IWM + all sector ETFs were hard-capped at
    # 60 (0/40 size points) and statically dropped from every bound cut.
    FUND_ASSET_TYPES = {"ETF", "ETN", "ETV", "ETS", "FUND"}

    @staticmethod
    def sanitize_metrics(payload: Dict) -> Dict:
        """
        Sanitizes dictionary values to ensure int-like fields are actual integers.
        Useful for Postgres bigint columns which reject floats or decimal strings.
        """
        sanitized = payload.copy()
        for key, value in payload.items():
            if key in UniverseService.INT_LIKE_KEYS:
                if value is None:
                    # Omit key if None to avoid overwriting with NULL or errors
                    sanitized.pop(key, None)
                    continue

                try:
                    # Coerce: float -> int, "123.45" -> 123
                    sanitized[key] = int(float(value))
                except (ValueError, TypeError):
                    # Omit key if coercion fails
                    sanitized.pop(key, None)

        return sanitized

    def sync_universe(self):
        """
        Upserts the base universe into scanner_universe table.
        This effectively 'seeds' the universe.
        """
        print("Syncing universe with base list...")
        data = []
        for symbol in self.BASE_UNIVERSE:
            data.append({
                "symbol": symbol,
                "is_active": True,
                "last_updated": datetime.now().isoformat()
            })

        try:
            # Upsert symbols. We preserve existing fields where not specified
            # but in Supabase upsert requires fetching or just overwrite.
            # We just overwrite 'is_active' and 'last_updated' effectively if conflict.
            self.supabase.table("scanner_universe").upsert(data, on_conflict="symbol").execute()
            print(f"Synced {len(data)} symbols to scanner_universe.")
        except Exception as e:
            # H9 Anti-pattern 2 fix (closes h9_allow_list.yml legacy
            # entry, 2026-05-18): replace silent print-swallow with
            # loud alert. Universe sync failure means the scanner
            # operates against stale `scanner_universe` rows on the
            # next cycle. The function preserves its pre-fix return
            # contract (None, implicit) — visibility is the change,
            # not control flow. `get_scan_candidates` falls back to
            # BASE_UNIVERSE on read-side failure, so single-cycle
            # write failure is recoverable; persistent failure
            # compounds across cycles and surfaces via the alert
            # repeating.
            alert(
                self.supabase,
                alert_type="universe_sync_upsert_failed",
                severity="warning",
                message=f"Universe sync failed: {e}",
                metadata={
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:500],
                    "batch_size": len(data),
                    "function_name": "UniverseService.sync_universe",
                    "consequence": (
                        "scanner_universe table not refreshed this run; "
                        "scanner falls back to BASE_UNIVERSE on read. "
                        "Persistent failure compounds across cycles."
                    ),
                },
            )
            logger.error(f"sync_universe: upsert failed: {e}")

    @classmethod
    def compute_liquidity_score(
        cls,
        *,
        market_cap,
        avg_vol,
        iv_rank,
        asset_type=None,
        avg_notional=None,
        details_fetch_failed=False,
    ):
        """Equity liquidity score (0-100). Pure — testable without I/O.

        Components (unchanged for the common case):
        - Size (max 40): market-cap brackets when a cap is present —
          byte-identical to the pre-fix heuristic for every single-name
          equity with a successful details fetch.
        - Volume (max 40): 30d average SHARE volume brackets (unchanged).
        - IV-rank presence (max 20): unchanged.

        2026-06-05 fixes (size component only):
        - ETF/fund (legit no market_cap): score size on notional dollar
          volume (price x share volume) instead of zeroing. Brackets
          calibrated so deep ETFs land where comparable caps would:
          >$1B/day=40, >$100M=30, >$10M=20.
        - Missing cap on a name that SHOULD have one (CS etc.), or a
          failed details fetch (guardrail returns {}): same notional
          fallback so ranking stays sane, but flagged as an anomaly so
          the caller alerts LOUDLY (H9 — a silently-zeroed fetch failure
          is indistinguishable from an ETF downstream; this makes the
          two cases distinct).

        Returns (score, meta) where meta carries `size_source`
        ('market_cap' | 'notional_fund' | 'notional_fallback'),
        `cap_missing_anomaly` (True only for the should-have-a-cap
        case), and `details_fetch_failed` (passed through).
        """
        l_score = 0
        cap_missing_anomaly = False

        # Size component (max 40 pts)
        if market_cap:
            if market_cap > 100_000_000_000: l_score += 40
            elif market_cap > 10_000_000_000: l_score += 30
            elif market_cap > 2_000_000_000: l_score += 20
            size_source = "market_cap"
        else:
            is_fund = (asset_type or "").upper() in cls.FUND_ASSET_TYPES
            notional = float(avg_notional or 0.0)
            if notional > 1_000_000_000: l_score += 40
            elif notional > 100_000_000: l_score += 30
            elif notional > 10_000_000: l_score += 20
            if is_fund and not details_fetch_failed:
                size_source = "notional_fund"
            else:
                # Single-name (or unknown type / failed fetch) without a
                # market cap — the H9 silent-failure class. Score on the
                # proxy but flag for the loud alert.
                size_source = "notional_fallback"
                cap_missing_anomaly = True

        # Volume Score (unchanged)
        if avg_vol > 10_000_000: l_score += 40
        elif avg_vol > 1_000_000: l_score += 30
        elif avg_vol > 200_000: l_score += 10

        # IV Rank Score (unchanged)
        if iv_rank is not None:
            l_score += 20

        return min(100, l_score), {
            "size_source": size_source,
            "cap_missing_anomaly": cap_missing_anomaly,
            "details_fetch_failed": details_fetch_failed,
        }

    def update_metrics(self):
        """
        Iterates over active symbols and updates metrics using Polygon.
        """
        print("[UniverseService] Updating universe metrics...")
        try:
            res = self.supabase.table("scanner_universe").select("symbol").eq("is_active", True).execute()
            symbols = [r['symbol'] for r in res.data]
        except Exception as e:
            print(f"[UniverseService] Error fetching active symbols: {e}")
            return

        updates = []
        cap_anomalies = []  # H9: should-have-a-cap names scored without one
        for sym in symbols:
            try:
                # 1. Basic Details (Sector, Market Cap, Asset Type)
                # NOTE: the fetch is @guardrail'd with fallback={} — an API
                # error arrives here as an EMPTY dict, which used to be
                # indistinguishable from an ETF's legitimately-absent
                # market_cap (both silently scored 0/40 size points).
                # `details_fetch_failed` + `type` now split the two cases.
                details = self.polygon.get_ticker_details(sym)
                details_fetch_failed = not details
                market_cap = details.get("market_cap")  # Raw value (float/None)
                asset_type = details.get("type")  # 'CS', 'ETF', 'ETV', ...
                sector = details.get("sic_description", "Unknown")

                # 2. Volume (Avg 30d) & IV Rank
                # We use get_historical_prices which now returns volumes.
                # avg_notional (price x volume) feeds the ETF / failed-cap
                # size fallback in compute_liquidity_score.
                avg_vol = 0
                avg_notional = 0.0

                try:
                    hist = self.polygon.get_historical_prices(sym, days=30)
                    if hist and 'volumes' in hist:
                        vols = hist['volumes']
                        if vols:
                            avg_vol = int(np.mean(vols))
                            prices = hist.get('prices') or []
                            if prices and len(prices) == len(vols):
                                avg_notional = float(np.mean(
                                    [p * v for p, v in zip(prices, vols)]
                                ))
                            elif prices:
                                avg_notional = float(np.mean(prices)) * avg_vol
                except Exception as e:
                    # print(f"Error fetching history for {sym}: {e}")
                    pass

                iv_rank = self.polygon.get_iv_rank(sym)

                # Removed local classify_iv_regime logic.
                # RegimeEngineV3 is the source of truth.

                # 3. Liquidity Score (0-100) — see compute_liquidity_score
                # for the component breakdown + the 2026-06-05 ETF /
                # failed-fetch size fixes.
                l_score, score_meta = self.compute_liquidity_score(
                    market_cap=market_cap,
                    avg_vol=avg_vol,
                    iv_rank=iv_rank,
                    asset_type=asset_type,
                    avg_notional=avg_notional,
                    details_fetch_failed=details_fetch_failed,
                )
                if score_meta["cap_missing_anomaly"]:
                    cap_anomalies.append({
                        "symbol": sym,
                        "asset_type": asset_type,
                        "details_fetch_failed": details_fetch_failed,
                        "avg_notional": round(avg_notional),
                        "score": l_score,
                    })
                    logger.warning(
                        "update_metrics: %s has no market_cap but is not a "
                        "known fund type (type=%r, fetch_failed=%s) — size "
                        "component scored on notional fallback ($%.0f/day), "
                        "score=%d",
                        sym, asset_type, details_fetch_failed,
                        avg_notional, l_score,
                    )

                # 4. Earnings Date
                earnings_date = self.earnings_service.get_earnings_date(sym)
                earnings_str = earnings_date.isoformat() if earnings_date else None

                updates.append({
                    "symbol": sym,
                    "sector": sector,
                    "market_cap": market_cap,
                    "avg_volume_30d": avg_vol,
                    "iv_rank": iv_rank,
                    "iv_regime": None, # Deprecated source of truth
                    "liquidity_score": l_score,
                    "earnings_date": earnings_str,
                    "last_updated": datetime.now().isoformat()
                })

            except Exception as e:
                print(f"[UniverseService] Error updating {sym}: {e}")

        # H9: the silent-zero class, made LOUD. One aggregate alert per run
        # (update_metrics is operator-triggered and rare; per-symbol detail
        # is in the metadata + the per-symbol logger.warning above).
        if cap_anomalies:
            try:
                alert(
                    self.supabase,
                    alert_type="market_cap_unavailable",
                    severity="warning",
                    message=(
                        f"{len(cap_anomalies)} non-fund symbol(s) scored "
                        f"without a market cap (details fetch failed or cap "
                        f"absent); size component fell back to notional "
                        f"dollar volume"
                    ),
                    metadata={
                        "symbols": [a["symbol"] for a in cap_anomalies],
                        "anomalies": cap_anomalies[:50],
                        "function_name": "UniverseService.update_metrics",
                        "consequence": (
                            "Affected symbols ranked on notional dollar "
                            "volume this run instead of market cap. If the "
                            "details fetch keeps failing, verify Polygon "
                            "/v3/reference/tickers for these symbols."
                        ),
                    },
                )
            except Exception as alert_err:
                logger.exception(
                    "market_cap_unavailable alert write failed: %s", alert_err
                )

        if updates:
            try:
                # Sanitize all updates before sending to DB
                sanitized_updates = [self.sanitize_metrics(u) for u in updates]
                self.supabase.table("scanner_universe").upsert(sanitized_updates).execute()
                print(f"[UniverseService] Updated metrics for {len(sanitized_updates)} symbols.")
            except Exception as e:
                print(f"[UniverseService] Error saving metrics: {e}")

    def get_scan_candidates(
        self,
        limit: int = 30,
        *,
        job_run_id: Optional[str] = None,
        caller: Optional[str] = None,
    ) -> List[Dict]:
        """
        Returns top candidates for scanning.
        Returns list of dicts: {'symbol': str, 'earnings_date': str | None}

        Every call writes one row to universe_selection_log capturing
        the full selection decision (selected + dropped, with score
        thresholds). This closes the H9 silent-decision observability
        gap discovered 2026-05-19: prior to this surface the top-N
        truncation made 50-of-70 selection decisions per cycle with
        zero queryable trace. See docs/loud_error_doctrine.md H9
        silent-decision generalization.

        The write is fail-soft (selection cannot be blocked by an
        observability failure) but loud — insert failure fires
        `universe_selection_log_write_failed` (severity=warning).
        """
        candidates: List[Dict] = []
        all_rows: List[Dict] = []
        fallback_used = False
        fallback_reason: Optional[str] = None
        active_universe_count: Optional[int] = None
        sort_order = "liquidity_score DESC, symbol ASC"  # overwritten below

        try:
            # Pull FULL active universe ordered by liquidity_score DESC,
            # symbol ASC (mirrors PostgREST default tiebreak). We slice
            # top-N for the return value AND keep the dropped tail for
            # the selection log. The cost difference vs the previous
            # `.limit(limit)` query is ~20 extra rows at current
            # universe size (70 active); negligible.
            #
            # OPTION-liquidity weighting (flag-gated, default OFF — see
            # analytics.option_liquidity). When OFF this query + order is
            # byte-identical to the pre-feature behavior AND does not
            # reference the new option_liquidity_score column (migration-
            # independent). When ON, the column is selected and the active
            # universe is RE-ORDERED by a blended priority
            # (equity liquidity_score × would_be_weight(option_liquidity_score))
            # so persistently wide-option names are DE-PRIORITIZED (weight,
            # not hard drop — they still appear, ranked lower; reversible).
            _ol = _option_liquidity  # module-bound at import time
            _weighting_on = _ol.is_weighting_enabled()

            # avg_volume_30d feeds the tie-break re-sort below (2026-06-05:
            # ties at a bound cut used to resolve alphabetically — MARA/RIVN
            # lost their slot to KHC by spelling). Long-standing column
            # written by update_metrics; no migration dependency.
            _cols = "symbol, earnings_date, liquidity_score, avg_volume_30d"
            if _weighting_on:
                _cols += ", option_liquidity_score"

            res = self.supabase.table("scanner_universe")\
                .select(_cols)\
                .eq("is_active", True)\
                .order("liquidity_score", desc=True)\
                .order("symbol", desc=False)\
                .execute()

            all_rows = list(res.data or [])
            active_universe_count = len(all_rows)

            if _weighting_on and all_rows:
                # #1015 blended priority — sort key deliberately untouched
                # by the tie-break fix (blended floats effectively never
                # tie; keeping it byte-identical isolates this PR from the
                # weighting graduation).
                sort_order = (
                    "liquidity_score*would_be_weight(option_liquidity_score)"
                    " DESC, symbol ASC"
                )
                all_rows = sorted(
                    all_rows,
                    key=lambda r: (
                        -(float(r.get("liquidity_score") or 0.0)
                          * _ol.would_be_weight(r.get("option_liquidity_score"))),
                        r.get("symbol") or "",
                    ),
                )
            elif all_rows:
                # Tie-break fix (2026-06-05): equal liquidity_scores resolve
                # on 30d share volume (a liquidity signal), alphabet last.
                # Done in Python (not a third PostgREST .order) so NULL
                # volume deterministically sorts LAST within a tie across
                # postgrest-py versions (DESC default is NULLS FIRST).
                sort_order = (
                    "liquidity_score DESC, avg_volume_30d DESC NULLS LAST,"
                    " symbol ASC"
                )
                all_rows = sorted(
                    all_rows,
                    key=lambda r: (
                        -(float(r.get("liquidity_score") or 0.0)),
                        -(float(r.get("avg_volume_30d") or 0.0)),
                        r.get("symbol") or "",
                    ),
                )

            for r in all_rows[:limit]:
                candidates.append({
                    "symbol": r["symbol"],
                    "earnings_date": r.get("earnings_date"),
                })
        except Exception as e:
            print(f"Error getting candidates from DB: {e}")
            fallback_used = True
            fallback_reason = f"{type(e).__name__}: {str(e)[:200]}"

        # Fallback to a slice of BASE_UNIVERSE if DB fails or is empty.
        if not candidates:
            if not fallback_used:
                fallback_used = True
                fallback_reason = fallback_reason or "empty_query_result"
            print("Falling back to BASE_UNIVERSE")
            candidates = [
                {"symbol": s, "earnings_date": None}
                for s in self.BASE_UNIVERSE[:limit]
            ]

        # Selection log write (H9 verified-decision). Best-effort, must
        # not block the caller — but must alert loudly on failure so
        # the observability surface itself can't silently regress.
        try:
            self._log_selection(
                all_rows=all_rows,
                selected=candidates,
                limit=limit,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
                job_run_id=job_run_id,
                caller=caller,
                sort_order=sort_order,
            )
        except Exception as log_err:
            # Per Loud-Error Doctrine valid-pattern 5: alert-write
            # failure must not undo the primary work (returning the
            # candidate list). The alert helper itself is fail-soft
            # to logger; this outer try guards against any further
            # blow-up so the scanner's universe load is never
            # blocked by an observability path failure.
            try:
                alert(
                    self.supabase,
                    alert_type="universe_selection_log_write_failed",
                    severity="warning",
                    message=(
                        f"universe_selection_log write failed: "
                        f"{type(log_err).__name__}: {str(log_err)[:200]}"
                    ),
                    metadata={
                        "error_class": type(log_err).__name__,
                        "error_message": str(log_err)[:500],
                        "function_name": "UniverseService.get_scan_candidates",
                        "caller": caller,
                        "limit": limit,
                        "candidates_returned": len(candidates),
                        "consequence": (
                            "Universe selection succeeded; observability "
                            "row missing for this cycle. Selection itself "
                            "is unaffected."
                        ),
                    },
                )
            except Exception as alert_err:
                logger.exception(
                    "universe_selection_log_write_failed alert also "
                    "failed: %s", alert_err,
                )

        self.last_selection_counts = {
            "active_universe_count": active_universe_count,
            "selected_symbol_count": len(candidates),
            "selection_source": "fallback" if fallback_used else "scanner_universe",
        }
        return candidates

    def _log_selection(
        self,
        *,
        all_rows: List[Dict],
        selected: List[Dict],
        limit: int,
        fallback_used: bool,
        fallback_reason: Optional[str],
        job_run_id: Optional[str],
        caller: Optional[str],
        sort_order: str = "liquidity_score DESC, symbol ASC",
    ) -> None:
        """Write a universe_selection_log row capturing this call's
        selection decision (inclusion + exclusion).

        Raises on insert failure; caller fires the H9 alert. Verified-
        write anchor: PostgREST returns `data` containing inserted rows;
        a non-1-length response means the insert did not land and we
        raise so the caller's alert path fires.
        """
        selected_symbols = [c["symbol"] for c in selected]
        total_active = len(all_rows)
        # Symbols beyond the slice that were active but not selected.
        dropped_symbols = [
            r["symbol"] for r in all_rows[limit:]
        ] if all_rows else []

        score_threshold: Optional[float] = None
        score_at_cutoff: Optional[float] = None
        if all_rows:
            selected_rows = all_rows[:limit]
            dropped_rows = all_rows[limit:]
            if selected_rows:
                score_threshold = selected_rows[-1].get("liquidity_score")
            if dropped_rows:
                score_at_cutoff = dropped_rows[0].get("liquidity_score")

        payload = {
            "job_run_id": job_run_id,
            "total_active": total_active,
            "limit_applied": int(limit),
            "selected_count": len(selected_symbols),
            "dropped_count": len(dropped_symbols),
            "selected_symbols": selected_symbols,
            "dropped_symbols": dropped_symbols,
            "score_threshold": score_threshold,
            "score_at_cutoff": score_at_cutoff,
            "metadata": {
                "caller": caller,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "sort_order": sort_order,
            },
        }

        res = self.supabase.table("universe_selection_log")\
            .insert(payload)\
            .execute()

        # Verified-write anchor (Rule 2): PostgREST insert returns the
        # inserted row in `data`. Empty `data` with no exception is the
        # silent-rejection shape (RLS denial, etc.) — raise so the
        # caller's alert fires.
        if not getattr(res, "data", None):
            raise RuntimeError(
                "universe_selection_log insert returned empty data "
                "(silent rejection — RLS / constraint / shape mismatch)"
            )

    def get_universe(self, limit: int = 30):
        # Backwards-compatible alias
        return self.get_scan_candidates(limit=limit)
