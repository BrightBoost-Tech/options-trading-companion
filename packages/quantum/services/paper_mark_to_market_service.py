"""
Paper Mark-to-Market Service

Refreshes current_mark and unrealized_pl on open paper_positions using
live option quotes, then saves an EOD snapshot for checkpoint evaluation.

Schedule: 3:30 PM CDT (before checkpoint), while quotes are still live.
"""

import logging
from datetime import datetime, timezone, date
from typing import Dict, Any, List, Optional

from packages.quantum.observability.alerts import alert
from packages.quantum.risk.payoff_bounds import (
    evaluate_payoff_bound,
    payoff_bound_alert_fields,
)
from packages.quantum.risk.mark_math import compute_current_value, finalize_mark

logger = logging.getLogger(__name__)


class PaperMarkToMarketService:
    """Fetches fresh quotes and marks open paper positions to market."""

    def __init__(self, supabase_client):
        self.client = supabase_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_marks(self, user_id: str) -> Dict[str, Any]:
        """
        Fetch fresh quotes for all open positions and update current_mark + unrealized_pl.

        Uses the MarketDataTruthLayer's /v3/snapshot endpoint for Polygon,
        with automatic fallback to Alpaca's indicative options feed when
        Polygon returns empty bid/ask (plan doesn't include options quotes).

        Returns summary dict with positions_marked, errors, etc.
        """
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer

        truth_layer = MarketDataTruthLayer()
        positions = self._get_open_positions(user_id)

        if not positions:
            return {"status": "ok", "positions_marked": 0, "reason": "no_open_positions"}

        # Batch-fetch all leg symbols in one API call via truth layer
        all_leg_symbols = []
        for pos in positions:
            legs = pos.get("legs") or []
            for leg in legs:
                if isinstance(leg, dict):
                    sym = leg.get("occ_symbol") or leg.get("symbol", "")
                    if sym:
                        all_leg_symbols.append(sym)
            # Fallback: position-level symbol if no legs
            if not legs and pos.get("symbol"):
                all_leg_symbols.append(pos["symbol"])

        # Single batched snapshot call (uses /v3/snapshot with ticker.any_of)
        snapshots = truth_layer.snapshot_many(all_leg_symbols) if all_leg_symbols else {}

        # #2026-05-13 MTM-staleness PR-2: bulk pre-fetch Alpaca's
        # broker-authoritative position values (single API call per
        # refresh cycle). Used as fallback when snapshot path returns
        # incomplete leg data. Pre-fix this path silently skipped such
        # positions → DB unrealized_pl stayed stale → risk envelope ran
        # on stale value (2026-05-12 CSX: DB -$8 vs Alpaca truth -$196).
        # Dict keyed by Polygon-format OCC symbol (matches leg.occ_symbol
        # / leg.symbol convention); Alpaca's serializer at
        # alpaca_client.py:_serialize_position converts to that format
        # for length->10 option symbols.
        broker_positions_by_symbol: Dict[str, Dict[str, Any]] = {}
        try:
            from packages.quantum.brokers.alpaca_client import get_alpaca_client
            alpaca = get_alpaca_client()
            if alpaca:
                for bp in alpaca.get_positions():
                    sym = bp.get("symbol")
                    if sym:
                        broker_positions_by_symbol[sym] = bp
        except Exception as exc:
            logger.warning(
                f"[MARK_TO_MARKET] Alpaca position pre-fetch failed: {exc}. "
                f"Falling back to snapshot-only path; any positions with "
                f"incomplete snapshots will silently skip + fire "
                f"mtm_refresh_partial alert per PR-1."
            )
            try:
                alert(
                    self.client,
                    alert_type="mtm_broker_prefetch_failed",
                    severity="warning",
                    message=(
                        f"Alpaca position pre-fetch failed during refresh_marks: "
                        f"{type(exc).__name__}"
                    ),
                    user_id=user_id,
                    metadata={
                        "source": "paper_mark_to_market_service.refresh_marks",
                        "error_class": type(exc).__name__,
                        "error_message": str(exc)[:500],
                        "consequence": (
                            "Broker fallback unavailable this cycle. "
                            "Positions with incomplete snapshots will silently "
                            "skip per pre-PR-2 behavior (PR-1's "
                            "mtm_refresh_partial alert still fires). "
                            "Re-fires next cycle (15-min cadence)."
                        ),
                    },
                )
            except Exception as alert_err:
                logger.warning(
                    f"[MARK_TO_MARKET] mtm_broker_prefetch_failed alert "
                    f"path failed: {alert_err}"
                )

        marked = 0
        skipped = 0
        fallback_used = 0
        errors = []
        batch_updates = []

        for pos in positions:
            pos_id = pos["id"]
            try:
                current_value = self._compute_position_value_from_snapshots(pos, snapshots)
                value_source = "snapshot"
                if current_value is None:
                    # #2026-05-13 MTM-staleness PR-2: snapshot path returned
                    # None (incomplete leg pricing). Try broker-authoritative
                    # fallback via Alpaca position values before giving up.
                    # If broker fallback also fails (drift case: leg absent
                    # from Alpaca, or pre-fetch failed earlier this cycle),
                    # silent-skip + PR-1's alert as before.
                    current_value = self._compute_position_value_from_broker(
                        pos, broker_positions_by_symbol,
                    )
                    if current_value is None:
                        skipped += 1
                        errors.append({
                            "position_id": pos_id,
                            "error": "snapshot_incomplete_and_broker_lookup_missing",
                        })
                        continue
                    value_source = "alpaca_fallback"
                    fallback_used += 1
                    logger.info(
                        f"[MARK_TO_MARKET] Broker fallback used for "
                        f"position={pos_id} symbol={pos.get('symbol')} "
                        f"current_value={current_value}"
                    )

                qty = float(pos.get("quantity") or 1)
                multiplier = 100
                # #3 unification: single shared full-count mark math (H13).
                # finalize_mark scales unrealized_pl exactly once and returns the
                # per-contract mark. This path already marked correctly at
                # full-count; routing it through the shared module guarantees the
                # intraday path (which double-counted) now computes identically.
                per_contract_mark, unrealized = finalize_mark(
                    qty, pos["avg_entry_price"], current_value, multiplier
                )

                # ── Payoff-bound guard (Task 1, 2026-05-28) ───────────────
                # Layered ON TOP of the mark math above — changes no
                # computation. Bounds the just-computed unrealized to the
                # spread's physical payoff envelope and surfaces impossible
                # marks loudly before they reach the DB / exit decision.
                # Convention-agnostic (pos.quantity + strikes + avg_entry,
                # never legs.quantity). For correctly-marked positions (e.g.
                # F, which this path marks correctly at full-count) the value
                # is in-bounds and untouched. The legs.quantity convention
                # split itself is #3, not fixed here.
                _bound = evaluate_payoff_bound(pos, unrealized)
                if _bound.applicable and not _bound.in_bounds:
                    alert(
                        self.client,
                        user_id=user_id,
                        position_id=pos.get("id"),
                        symbol=pos.get("symbol"),
                        **payoff_bound_alert_fields(
                            pos, _bound,
                            "paper_mark_to_market_service.refresh_marks",
                        ),
                    )
                    unrealized = _bound.clamped_value

                old_mark = pos.get("current_mark")
                old_upl = pos.get("unrealized_pl")
                entry_value = float(pos["avg_entry_price"] or 0) * abs(qty) * multiplier
                mtm_msg = (
                    f"[MTM_DEBUG] position={pos_id} symbol={pos.get('symbol')} "
                    f"qty={qty} entry_value={entry_value} current_value={current_value} "
                    f"per_contract_mark={per_contract_mark} unrealized={unrealized} "
                    f"old_mark={old_mark} old_upl={old_upl}"
                )
                logger.info(mtm_msg)
                print(mtm_msg, flush=True)

                batch_updates.append({
                    "id": pos_id,
                    "current_mark": per_contract_mark,
                    "unrealized_pl": unrealized,
                    # last_marked_at populated ONLY on the success branch
                    # (#2026-05-12 MTM-staleness PR-1). Skipped positions
                    # intentionally leave this stale so future queries
                    # like "open positions not marked in last 30m" surface
                    # the silently-skipped ones.
                    "last_marked_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                marked += 1

            except Exception as e:
                logger.error(f"[MARK_TO_MARKET] Failed to compute mark for {pos_id}: {e}")
                errors.append({"position_id": pos_id, "error": str(e)})

        # Per-row UPDATE is the only supported write path here. The
        # prior implementation used a batch INSERT-ON-CONFLICT which
        # always failed on Postgres 23502 because the INSERT side
        # provides only {id, current_mark, unrealized_pl, updated_at};
        # every other NOT NULL column on paper_positions (user_id,
        # portfolio_id, symbol, strategy_key) defaulted to NULL. That
        # error fired once per position per cycle and was handled via
        # a try/except fallback that ran the same per-row UPDATE we
        # now use primarily. Promoted fallback to primary to eliminate
        # the spurious 23502 log noise and the error-path-as-control-
        # flow pattern (Issue 1 correction, audit note 2026-04-20 —
        # live AMZN a0f05755 occurrences at 20:00:11Z and 20:30:02Z
        # triggered the re-diagnosis).
        if batch_updates:
            for upd in batch_updates:
                try:
                    self.client.table("paper_positions").update({
                        k: v for k, v in upd.items() if k != "id"
                    }).eq("id", upd["id"]).execute()
                except Exception as upd_err:
                    logger.error(
                        f"[MARK_TO_MARKET] Update failed for "
                        f"position={upd['id']}: {upd_err}"
                    )
                    errors.append({"position_id": upd["id"], "error": str(upd_err)})

        if skipped:
            logger.info(
                f"[MARK_TO_MARKET] user={user_id} marked={marked} "
                f"skipped={skipped} (incomplete quotes) total={len(positions)}"
            )

        # PR-1 alert reframed by PR-2 (#2026-05-13): pre-PR-2 this fired
        # whenever snapshot was incomplete (frequent — option-leg quote
        # data is unreliable on Alpaca paper account). Post-PR-2 it fires
        # only when BOTH snapshot AND broker fallback failed — true drift
        # case: Alpaca-side position missing for a leg we have in DB, or
        # broker pre-fetch failed earlier this cycle. Alert count should
        # drop to near-zero after PR-2 merges; remaining fires indicate
        # genuine drift worth investigating.
        if skipped > 0 or errors:
            try:
                alert(
                    self.client,
                    alert_type="mtm_refresh_partial",
                    severity="warning",
                    message=(
                        f"MTM refresh partial: {marked}/{len(positions)} marked "
                        f"({fallback_used} via broker fallback), "
                        f"{skipped} skipped — BOTH snapshot AND broker "
                        f"fallback failed"
                    ),
                    user_id=user_id,
                    metadata={
                        "source": "paper_mark_to_market_service.refresh_marks",
                        "positions_marked": marked,
                        "positions_skipped": skipped,
                        "fallback_used": fallback_used,
                        "total_positions": len(positions),
                        "errors": errors[:20] if errors else [],
                        "consequence": (
                            "Skipped positions retain stale unrealized_pl. "
                            "Post-PR-2 semantics: this state indicates true "
                            "drift (e.g., Alpaca-side position missing for a "
                            "leg in DB) or broker pre-fetch failure earlier "
                            "this cycle — not the routine snapshot-incomplete "
                            "case that PR-2 handles via fallback. Investigate "
                            "per-position errors below."
                        ),
                    },
                )
            except Exception as alert_err:
                logger.warning(
                    f"[MARK_TO_MARKET] mtm_refresh_partial alert path "
                    f"failed: {alert_err}"
                )

        return {
            "status": "ok" if not errors else "partial",
            "positions_marked": marked,
            "positions_skipped": skipped,
            # #2026-05-13 PR-2 success metric: how often did broker
            # fallback rescue an incomplete snapshot? Operator can
            # query the result envelope to monitor this directly
            # (or grep "Broker fallback used" in logs).
            "fallback_used": fallback_used,
            "errors": errors if errors else None,
            "total_positions": len(positions),
        }

    def save_eod_snapshot(self, user_id: str, snapshot_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Save current unrealized_pl for all open positions as an EOD snapshot.
        Used by checkpoint to compute daily unrealized change.
        """
        snapshot_date = snapshot_date or date.today()
        positions = self._get_open_positions(user_id)

        if not positions:
            return {"status": "ok", "snapshots_saved": 0}

        # Batch all snapshots into a single upsert
        snapshot_rows = []
        for pos in positions:
            snapshot_rows.append({
                "position_id": pos["id"],
                "user_id": user_id,
                "portfolio_id": pos["portfolio_id"],
                "snapshot_date": snapshot_date.isoformat(),
                "current_mark": pos.get("current_mark"),
                "unrealized_pl": float(pos.get("unrealized_pl") or 0.0),
            })

        saved = 0
        if snapshot_rows:
            try:
                self.client.table("paper_eod_snapshots").upsert(
                    snapshot_rows, on_conflict="position_id,snapshot_date"
                ).execute()
                saved = len(snapshot_rows)
            except Exception as e:
                logger.error(f"[MARK_TO_MARKET] Batch EOD snapshot failed, falling back: {e}")
                for row in snapshot_rows:
                    try:
                        self.client.table("paper_eod_snapshots").upsert(
                            row, on_conflict="position_id,snapshot_date"
                        ).execute()
                        saved += 1
                    except Exception as e2:
                        logger.error(f"[MARK_TO_MARKET] Snapshot failed for {row['position_id']}: {e2}")

        return {"status": "ok", "snapshots_saved": saved}

    def get_current_unrealized_total(self, user_id: str) -> float:
        """
        Sum unrealized_pl across all open paper positions for a user.
        Used by checkpoint to compute total_pnl = realized + unrealized.
        """
        positions = self._get_open_positions(user_id)
        return sum(float(p.get("unrealized_pl") or 0.0) for p in positions)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_open_positions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all open paper positions for a user via portfolio join.

        Scope filter (2026-06-06 fix): quantity != 0 alone leaked CLOSED
        rows with residual quantity into MTM scope forever — the canonical
        close helper sets status='closed' but does not zero quantity. Two
        production leakers: an expired-legs CSX row that could never mark
        again (permanent mtm_refresh_partial alarm = cried-wolf noise) and
        a manually-closed F row whose unrealized_pl kept mutating post-
        close. The status predicate mirrors close_helper's liveness check
        (`status != 'closed'`, see close_helper.py conditional UPDATE)
        rather than `status == 'open'`, so any future intermediate live
        state (staging/partial) stays marked; only definitively closed
        rows leave scope.
        """
        try:
            port_res = self.client.table("paper_portfolios") \
                .select("id") \
                .eq("user_id", user_id) \
                .execute()

            portfolio_ids = [p["id"] for p in (port_res.data or [])]
            if not portfolio_ids:
                return []

            pos_res = self.client.table("paper_positions") \
                .select("*") \
                .in_("portfolio_id", portfolio_ids) \
                .neq("status", "closed") \
                .neq("quantity", 0) \
                .execute()

            return pos_res.data or []
        except Exception as e:
            logger.error(f"[MARK_TO_MARKET] Failed to fetch positions for {user_id}: {e}")
            return []

    @staticmethod
    def _compute_position_value(
        position: Dict[str, Any],
        poly_service,
        is_valid_quote_fn,
    ) -> Optional[float]:
        """
        Compute current market value of a position from its legs' mid-prices.

        Returns total value in dollars, or None if ANY leg fails to get a
        valid quote.  Partial pricing of multi-leg positions is dangerous:
        a missing short-leg quote understates liabilities and overstates profit.
        """
        legs = position.get("legs") or []
        if not legs:
            # No legs — try to quote the symbol directly
            symbol = position.get("symbol", "")
            quote = poly_service.get_recent_quote(symbol)
            if not quote or not is_valid_quote_fn(quote):
                return None
            bid = float(quote.get("bid_price") or quote.get("bid") or 0)
            ask = float(quote.get("ask_price") or quote.get("ask") or 0)
            mid = (bid + ask) / 2.0 if (bid and ask) else 0.0
            if mid <= 0:
                return None
            qty = abs(float(position.get("quantity") or 1))
            return mid * 100 * qty

        # First pass: collect mid-prices for ALL legs.  If any leg fails,
        # abort the entire position — never partially price.
        leg_values: List[float] = []
        failed_legs: List[str] = []
        priceable_legs = 0

        for leg in legs:
            if isinstance(leg, str):
                continue  # Skip malformed leg entries

            occ_symbol = leg.get("occ_symbol") or leg.get("symbol", "")
            if not occ_symbol:
                continue

            priceable_legs += 1

            quote = poly_service.get_recent_quote(occ_symbol)
            if not quote or not is_valid_quote_fn(quote):
                failed_legs.append(occ_symbol)
                continue

            bid = float(quote.get("bid_price") or quote.get("bid") or 0)
            ask = float(quote.get("ask_price") or quote.get("ask") or 0)
            mid = (bid + ask) / 2.0 if (bid and ask) else 0.0
            if mid <= 0:
                failed_legs.append(occ_symbol)
                continue

            multiplier = 100
            leg_qty = float(leg.get("quantity") or position.get("quantity") or 1)
            action = leg.get("action", "buy")
            side_mult = 1.0 if action == "buy" else -1.0

            leg_values.append(mid * multiplier * abs(leg_qty) * side_mult)

        if priceable_legs == 0:
            return None

        # All-or-nothing: reject partial pricing
        if failed_legs:
            pos_id = position.get("id", "?")
            logger.warning(
                f"[MARK_TO_MARKET] Skipping position {pos_id}: "
                f"{len(failed_legs)}/{priceable_legs} legs failed to price "
                f"({', '.join(failed_legs)}). Keeping previous mark."
            )
            return None

        return sum(leg_values)

    @staticmethod
    def _compute_position_value_from_snapshots(
        position: Dict[str, Any],
        snapshots: Dict[str, Dict],
    ) -> Optional[float]:
        """
        Compute current market value from pre-fetched truth layer snapshots.

        Same all-or-nothing logic as _compute_position_value, but reads from
        the snapshot dict (keyed by normalized symbol) instead of making
        per-leg API calls. Uses /v3/snapshot which works for options on all
        Polygon plans (unlike /v3/quotes which requires Options add-on).
        """
        from packages.quantum.services.cache_key_builder import normalize_symbol

        legs = position.get("legs") or []
        if not legs:
            symbol = position.get("symbol", "")
            norm = normalize_symbol(symbol)
            snap = snapshots.get(norm, {})
            q = snap.get("quote", snap)  # try nested "quote" dict, fall back to flat
            bid = float(q.get("bid") or 0)
            ask = float(q.get("ask") or 0)
            mid = float(q.get("mid") or 0) if not (bid > 0 and ask > 0) else (bid + ask) / 2.0
            if mid <= 0:
                return None
            qty = abs(float(position.get("quantity") or 1))
            return mid * 100 * qty

        # #3 unification: shared full-count leg-sum (H13). The per-leg
        # aggregation formula is identical across both mark readers and is now
        # the single implementation in risk.mark_math.compute_current_value.
        def _mid_for(occ_symbol: str) -> Optional[float]:
            norm = normalize_symbol(occ_symbol)
            snap = snapshots.get(norm, {})
            q = snap.get("quote", snap)  # nested "quote" dict, fall back to flat
            bid = float(q.get("bid") or 0)
            ask = float(q.get("ask") or 0)
            return (bid + ask) / 2.0 if (bid > 0 and ask > 0) else float(q.get("mid") or 0)

        failed_legs: List[str] = []
        current_value = compute_current_value(
            legs, _mid_for, position.get("quantity"), failed_legs=failed_legs
        )
        if failed_legs:
            pos_id = position.get("id", "?")
            logger.warning(
                f"[MARK_TO_MARKET] Skipping position {pos_id}: "
                f"{len(failed_legs)} leg(s) failed to price "
                f"({', '.join(failed_legs)}). Keeping previous mark."
            )
            return None
        return current_value

    @staticmethod
    def _compute_position_value_from_broker(
        position: Dict[str, Any],
        broker_positions_by_symbol: Dict[str, Dict[str, Any]],
    ) -> Optional[float]:
        """
        Broker-authoritative fallback for refresh_marks. Used when
        ``_compute_position_value_from_snapshots`` returns None
        (incomplete leg pricing in the snapshot path).

        Returns signed current_value matching the snapshot helper's
        contract: sum of per-leg market values with side_mult inverting
        short legs. Downstream math in ``refresh_marks``
        (``unrealized = current_value - entry_value``, inverted for
        negative qty) operates unchanged.

        Returns None if any leg is missing from Alpaca's response — true
        drift case (Alpaca-side position state diverged from DB) where
        caller treats None as silent-skip + alert per PR-1 framing.

        2026-05-13 PR-2: ships this method as the structural fix for the
        H9 wrapper-drift cascade that produced the 2026-05-12 CSX
        situation (DB -$8 vs Alpaca truth -$196 because option-snapshot
        path silently degraded). Same broker-truth pattern as #93's
        ``equity_state.get_alpaca_options_buying_power``.
        """
        multiplier = 100
        legs = position.get("legs") or []

        # Single-leg / leg-less position: lookup by position-level symbol.
        if not legs:
            symbol = position.get("symbol", "")
            if not symbol:
                return None
            bp = broker_positions_by_symbol.get(symbol)
            if not bp:
                return None
            current_price = bp.get("current_price")
            if current_price is None or float(current_price) <= 0:
                return None
            qty = abs(float(position.get("quantity") or 1))
            return float(current_price) * multiplier * qty

        # Multi-leg position: shared full-count leg-sum (H13), priced from the
        # broker's current_price as the value SOURCE. Same arithmetic as the
        # snapshot path — only the price source differs.
        def _broker_price_for(occ_symbol: str) -> Optional[float]:
            bp = broker_positions_by_symbol.get(occ_symbol)
            if not bp:
                return None  # leg absent from Alpaca → drift case
            cp = bp.get("current_price")
            if cp is None or float(cp) <= 0:
                return None
            return float(cp)

        failed_legs: List[str] = []
        current_value = compute_current_value(
            legs, _broker_price_for, position.get("quantity"),
            multiplier=multiplier, failed_legs=failed_legs,
        )
        if failed_legs:
            pos_id = position.get("id", "?")
            logger.warning(
                f"[MARK_TO_MARKET] Broker fallback skipping position "
                f"{pos_id}: {len(failed_legs)} leg(s) missing from Alpaca "
                f"response ({', '.join(failed_legs)}). Drift case — caller "
                f"alerts via PR-1's mtm_refresh_partial path."
            )
            return None
        return current_value
