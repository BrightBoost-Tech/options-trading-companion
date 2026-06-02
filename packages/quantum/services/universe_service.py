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
        "COST", "TMUS", "AMGN", "CHTR", "SBUX", "PYPL", "INTU", "GILD", "FISV",
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

    # Int-like keys that must be sanitized for Postgres BigInt
    INT_LIKE_KEYS = {
        "market_cap", "volume", "avg_volume", "avg_volume_30d",
        "shares_outstanding", "open_interest", "timestamp_ms",
        "liquidity_score"
    }

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
        for sym in symbols:
            try:
                # 1. Basic Details (Sector, Market Cap)
                details = self.polygon.get_ticker_details(sym)
                market_cap = details.get("market_cap")  # Raw value (float/None)
                sector = details.get("sic_description", "Unknown")

                # 2. Volume (Avg 30d) & IV Rank
                # We use get_historical_prices which now returns volumes
                avg_vol = 0

                try:
                    hist = self.polygon.get_historical_prices(sym, days=30)
                    if hist and 'volumes' in hist:
                        vols = hist['volumes']
                        if vols:
                            avg_vol = int(np.mean(vols))
                except Exception as e:
                    # print(f"Error fetching history for {sym}: {e}")
                    pass

                iv_rank = self.polygon.get_iv_rank(sym)

                # Removed local classify_iv_regime logic.
                # RegimeEngineV3 is the source of truth.

                # 3. Liquidity Score (0-100)
                # Heuristic:
                # - Market Cap (Max 40 pts): >100B=40, >10B=30, >2B=20
                # - Volume (Max 40 pts): >10M=40, >1M=30, >100k=10
                # - IV Rank Presence (Max 20 pts): If we have IV rank, data is good.

                l_score = 0

                # Market Cap Score
                if market_cap:
                    if market_cap > 100_000_000_000: l_score += 40
                    elif market_cap > 10_000_000_000: l_score += 30
                    elif market_cap > 2_000_000_000: l_score += 20

                # Volume Score
                if avg_vol > 10_000_000: l_score += 40
                elif avg_vol > 1_000_000: l_score += 30
                elif avg_vol > 200_000: l_score += 10

                # IV Rank Score
                if iv_rank is not None:
                    l_score += 20

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
                    "liquidity_score": min(100, l_score),
                    "earnings_date": earnings_str,
                    "last_updated": datetime.now().isoformat()
                })

            except Exception as e:
                print(f"[UniverseService] Error updating {sym}: {e}")

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

            _cols = "symbol, earnings_date, liquidity_score"
            if _weighting_on:
                _cols += ", option_liquidity_score"

            res = self.supabase.table("scanner_universe")\
                .select(_cols)\
                .eq("is_active", True)\
                .order("liquidity_score", desc=True)\
                .order("symbol", desc=False)\
                .execute()

            all_rows = list(res.data or [])

            if _weighting_on and all_rows:
                all_rows = sorted(
                    all_rows,
                    key=lambda r: (
                        -(float(r.get("liquidity_score") or 0.0)
                          * _ol.would_be_weight(r.get("option_liquidity_score"))),
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
                "sort_order": "liquidity_score DESC, symbol ASC",
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
