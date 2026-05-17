"""Historical IV reconstruction service.

Reconstructs an ATM IV30 point for a historical date using Polygon's
``/v3/reference/options/contracts`` (contract listing) +
``/v2/aggs/ticker/{symbol}/range/1/day/...`` (per-contract daily close)
endpoints. Polygon's snapshot endpoint exposes IV for "now" only — this
class fills the gap by inverting Black-Scholes on historical closing prices
to produce the contract dicts that ``IVPointService.compute_atm_iv_target_from_chain``
already knows how to interpolate.

Three reused PolygonService methods (verified 2026-05-13 in market_data.py):
- ``get_option_contract_candidates`` (line 808) → reference contracts
- ``get_option_historical_prices`` (line 146) → daily OHLC per contract
- ``get_historical_spot_price`` (line 930) → underlying close on date

See ``docs/loud_error_doctrine.md`` H9 convention: every wrapper call
returns an explicit value or None; the orchestrator (handler layer) is
responsible for verifying writes via independent DB count.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from packages.quantum.services.bs_inversion import invert_iv
from packages.quantum.services.iv_point_service import IVPointService
from packages.quantum.services.cache_key_builder import normalize_symbol as _normalize_option_symbol

logger = logging.getLogger(__name__)

# Reference strike window: ATM ±20% of spot. Wide enough that
# ``_compute_atm_iv_for_expiry`` (in IVPointService) finds a closest-
# strike candidate; narrow enough to keep Polygon contract listing
# manageable (a single page is 1000 contracts).
ATM_STRIKE_RANGE_PCT = 0.20

# DTE window for contract candidates. IVPointService's interpolation
# requires bracketing expiries around the 30d target; pulling 2..365 day
# contracts gives the interpolator the term structure it needs.
DTE_MIN = 2
DTE_MAX = 365


class HistoricalIVService:
    """Reconstructs ATM IV30 points for historical dates.

    Stateless — instantiated per backfill run with a PolygonService
    reference. Risk-free rate and dividend yield are constructor args
    so the backfill handler can override (default 4.5% per α design
    spec; dividend yield 0 for index/ETF approximation).
    """

    def __init__(
        self,
        polygon_service,
        risk_free_rate: float = 0.045,
        dividend_yield: float = 0.0,
    ):
        self._polygon = polygon_service
        self.r = risk_free_rate
        self.q = dividend_yield

    # ---- Polygon thin wrappers (one responsibility each) ------------

    def get_historical_contracts(
        self,
        underlying: str,
        as_of_date: date,
        right: str,
        spot: float,
    ) -> List[Dict[str, Any]]:
        """Fetch contract reference listings near the ATM strike for
        ``as_of_date``. Returns the raw list from PolygonService
        (each: ``{ticker, strike, expiration, type, underlying}``).
        """
        strike_min = spot * (1 - ATM_STRIKE_RANGE_PCT)
        strike_max = spot * (1 + ATM_STRIKE_RANGE_PCT)
        exp_start = as_of_date + timedelta(days=DTE_MIN)
        exp_end = as_of_date + timedelta(days=DTE_MAX)

        return self._polygon.get_option_contract_candidates(
            underlying=underlying,
            as_of_date=as_of_date,
            right=right,
            exp_start=exp_start,
            exp_end=exp_end,
            strike_min=strike_min,
            strike_max=strike_max,
        )

    def get_historical_price_for_occ(
        self,
        occ_symbol: str,
        as_of_date: date,
    ) -> Optional[float]:
        """Fetch close price for ``occ_symbol`` on ``as_of_date``.

        Polygon's daily-aggregate endpoint takes a date range; we request
        only that single day. Returns None if no bar exists (most common
        for thinly-traded options).

        Used by the per-date entry point ``compute_historical_iv_point``.
        For window-aware backfills (e.g., the handler iterating a 60-day
        backfill window per symbol), prefer
        ``get_historical_price_range_for_occ`` to amortize the per-contract
        API call across all dates in a single request.
        """
        start_dt = datetime.combine(as_of_date, datetime.min.time())
        end_dt = start_dt
        result = self._polygon.get_option_historical_prices(
            option_symbol=occ_symbol,
            start_date=start_dt,
            end_date=end_dt,
        )
        if not result:
            return None
        prices = result.get("prices") or []
        if not prices:
            return None
        return float(prices[0])

    def get_historical_price_range_for_occ(
        self,
        occ_symbol: str,
        window_start: date,
        window_end: date,
    ) -> Dict[str, float]:
        """Fetch close prices for ``occ_symbol`` across [window_start,
        window_end]. Returns a dict keyed by ``YYYY-MM-DD`` string
        mapping to close price. Empty dict if no bars.

        Polygon's ``/v2/aggs/ticker/.../range/...`` endpoint already
        supports arbitrary date ranges in a single call — this wrapper
        replaces the per-day call pattern of
        ``get_historical_price_for_occ`` with a window-aware fetch
        that amortizes the per-contract API cost across all dates.

        Used by ``compute_historical_iv_points_for_window`` to drop
        per-symbol Polygon API call count from ~12,180 (per-date ×
        per-contract) to ~262 (window-amortized).

        Implementation note (timezone correctness):
            PolygonService.get_option_historical_prices' underlying
            implementation formats dates from Polygon's millisecond
            timestamps via local-timezone ``datetime.fromtimestamp``.
            For daily option bars, Polygon's timestamp is midnight ET
            (UTC-4/-5 depending on DST). On systems with local tz
            behind ET (Central/Mountain/Pacific/UTC), this misattributes
            the bar to the previous calendar day — e.g., a 2026-05-08
            bar shows up as "2026-05-07" on a Central-time worker.

            Per-date callers like ``get_historical_price_for_occ``
            mask this by taking ``prices[0]`` without checking dates
            (single-day query always returns exactly the requested
            day's bar regardless of how the date string is formatted).

            Window callers need date-keyed lookup to work, so this
            method goes direct to the underlying HTTP endpoint and
            re-formats timestamps as UTC. UTC vs ET both put midnight-ET
            on the correct calendar day, so UTC is fine.

            Production workers run on Railway = UTC by default, so the
            local-tz bug doesn't manifest there. This UTC-aware
            re-implementation makes the method correct on developer
            machines (typically Central tz) AND production.
        """
        if window_start > window_end:
            return {}
        if not getattr(self._polygon, "api_key", None):
            return {}

        # Direct HTTP call (no upstream wrapper) with UTC date formatting.
        # Endpoint shape matches PolygonService._get_option_historical_prices_api.
        symbol = _normalize_option_symbol(occ_symbol)
        url = (
            f"{self._polygon.base_url}/v2/aggs/ticker/{symbol}"
            f"/range/1/day/{window_start.isoformat()}/{window_end.isoformat()}"
        )
        params = {
            "adjusted": "true",
            "sort": "asc",
            "apiKey": self._polygon.api_key,
        }
        try:
            response = self._polygon.session.get(url, params=params, timeout=10)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "historical_iv_range_http_failed occ=%s window=%s..%s error=%s",
                occ_symbol, window_start, window_end, str(e),
            )
            return {}

        if response.status_code != 200:
            return {}

        try:
            data = response.json()
        except Exception:  # noqa: BLE001
            return {}

        bars = data.get("results") or []
        if not bars:
            return {}

        out: Dict[str, float] = {}
        for bar in bars:
            t_ms = bar.get("t")
            close = bar.get("c")
            if t_ms is None or close is None:
                continue
            # UTC-aware date formatting (vs upstream's local-tz fromtimestamp).
            bar_date = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            out[bar_date] = float(close)
        return out

    def get_historical_spot(
        self, underlying: str, as_of_date: date,
    ) -> Optional[float]:
        """Underlying close price on ``as_of_date``. PolygonService
        handles close-on-or-before semantics (weekends, holidays).
        """
        return self._polygon.get_historical_spot_price(underlying, as_of_date)

    # ---- Chain reconstruction --------------------------------------

    def reconstruct_chain_at_date(
        self, underlying: str, as_of_date: date, spot: float,
    ) -> List[Dict[str, Any]]:
        """Build a list of contract dicts in the shape that
        ``IVPointService._compute_atm_iv_for_expiry`` expects:

            [{"details": {"strike_price", "contract_type", "expiration_date"},
              "implied_volatility": float}, ...]

        For each candidate contract:
        1. Fetch the historical close price on ``as_of_date``
        2. Compute TTE from ``expiration - as_of_date``
        3. Invert BS to get IV
        4. Emit the contract dict if inversion succeeded

        Returns whatever inverted successfully — possibly empty if no
        contracts had usable prices on the date.
        """
        chain: List[Dict[str, Any]] = []

        for right in ("call", "put"):
            try:
                contracts = self.get_historical_contracts(
                    underlying, as_of_date, right, spot,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "historical_iv_contracts_failed underlying=%s "
                    "as_of_date=%s right=%s error=%s",
                    underlying, as_of_date, right, str(e),
                )
                continue

            for c in contracts:
                occ_symbol = c.get("ticker")
                strike = c.get("strike")
                exp_str = c.get("expiration")
                if not occ_symbol or strike is None or not exp_str:
                    continue

                try:
                    exp_date = date.fromisoformat(exp_str)
                except (ValueError, TypeError):
                    continue

                dte = (exp_date - as_of_date).days
                if dte < DTE_MIN or dte > DTE_MAX:
                    continue
                T = dte / 365.0

                price = self.get_historical_price_for_occ(occ_symbol, as_of_date)
                if price is None or price <= 0:
                    continue

                iv = invert_iv(
                    price=price,
                    S=spot,
                    K=float(strike),
                    T=T,
                    r=self.r,
                    q=self.q,
                    right=right,
                )
                if iv is None:
                    continue

                chain.append({
                    "details": {
                        "strike_price": float(strike),
                        "contract_type": right,
                        "expiration_date": exp_str,
                    },
                    "implied_volatility": float(iv),
                })

        return chain

    # ---- Public entry point ----------------------------------------

    def compute_historical_iv_point(
        self, underlying: str, as_of_date: date,
    ) -> Optional[Dict[str, Any]]:
        """Compute one IV30 point for ``(underlying, as_of_date)``.

        Pipeline:
        1. Resolve historical spot price
        2. Reconstruct option chain (BS inversion)
        3. Hand to ``IVPointService.compute_atm_iv_target_from_chain``
        4. Return result dict in the shape ``IVRepository.upsert_iv_point``
           accepts, OR None if any step produced insufficient data

        The output dict shape mirrors ``compute_atm_iv_target_from_chain``
        exactly so the repository upsert path needs no special-casing.
        """
        spot = self.get_historical_spot(underlying, as_of_date)
        if spot is None or spot <= 0:
            logger.info(
                "historical_iv_no_spot underlying=%s as_of_date=%s",
                underlying, as_of_date,
            )
            return None

        chain = self.reconstruct_chain_at_date(underlying, as_of_date, spot)
        if not chain:
            logger.info(
                "historical_iv_empty_chain underlying=%s as_of_date=%s spot=%.2f",
                underlying, as_of_date, spot,
            )
            return None

        as_of_ts = datetime.combine(as_of_date, datetime.min.time())
        result = IVPointService.compute_atm_iv_target_from_chain(
            chain_results=chain,
            spot=spot,
            as_of_ts=as_of_ts,
            target_dte=30.0,
        )

        if not result or result.get("iv") is None:
            logger.info(
                "historical_iv_interp_failed underlying=%s as_of_date=%s "
                "reason=%s",
                underlying, as_of_date, result.get("iv_method") if result else None,
            )
            return None

        # Annotate source so repository writes can be distinguished from
        # snapshot-era rows in audit queries. Repository casts
        # ``inputs`` through verbatim; downstream consumers don't care
        # about the extra key.
        inputs = dict(result.get("inputs") or {})
        inputs["backfill"] = True
        inputs["risk_free_rate"] = self.r
        inputs["dividend_yield"] = self.q
        result["inputs"] = inputs

        return result

    def compute_historical_iv_points_for_window(
        self,
        underlying: str,
        target_dates: List[date],
    ) -> Dict[date, Optional[Dict[str, Any]]]:
        """Compute IV30 for many dates with shared contract + OHLC cache.

        Window-aware version of ``compute_historical_iv_point`` designed
        for the historical backfill use case. Pre-fetches:

        - Contract universe ONCE per right (covering the union of strike
          and DTE ranges across all target_dates)
        - Each contract's OHLC ONCE across the full date window

        Per-date iteration then becomes a pure cache lookup + BS inversion
        + interpolation, with no Polygon API calls.

        Drops per-symbol Polygon API call count from ~12,180 (per-date ×
        per-contract single-day fetches) to ~262 (window-amortized).
        Empirically observed pace pre-refactor was ~93 s/(symbol-day);
        the refactor cuts most of that cost.

        Args:
            underlying: Stock ticker (e.g. "SPY"). Same shape as
                ``compute_historical_iv_point``.
            target_dates: List of historical dates to compute IV30 for.
                Must be a non-empty list; weekends/holidays are NOT
                pre-filtered (Polygon's range query simply returns no
                bars for non-trading days, and the per-date loop emits
                None for those).

        Returns:
            Dict mapping ``target_date`` -> result dict (same shape as
            ``compute_historical_iv_point``'s return) OR None when no
            usable chain could be reconstructed for that date.

            The return dict is dense over ``target_dates``: every date
            in the input list appears as a key.

        Behavior parity with per-date method:
            Per-date strike filtering (ATM ± ``ATM_STRIKE_RANGE_PCT``
            of THAT date's spot) and DTE filtering (DTE_MIN..DTE_MAX
            from THAT date) are applied client-side after the window
            fetch. Same code path through ``invert_iv`` +
            ``IVPointService.compute_atm_iv_target_from_chain``. Output
            for any single date matches what the per-date method would
            produce against the same Polygon state.

        Failure semantics:
            Per-date failures (no spot, no chain, no IV inversion) emit
            None for that date and continue. Chain-listing API failures
            for a given right emit None for all dates and continue with
            the other right. Catastrophic exceptions in the loop body
            are not caught here — callers are expected to wrap the call
            for per-symbol isolation in batch handlers.
        """
        if not target_dates:
            return {}

        window_start = min(target_dates)
        window_end = max(target_dates)

        # Per-date spot prices. These are cheap (Polygon stocks endpoint,
        # ~5-day window helper) and small in count (~60 per symbol vs
        # ~200 per-contract calls), so the per-date pattern stays.
        spots: Dict[date, Optional[float]] = {}
        for d in target_dates:
            spots[d] = self.get_historical_spot(underlying, d)

        usable_spots = [s for s in spots.values() if s and s > 0]
        if not usable_spots:
            logger.info(
                "historical_iv_window_no_spots underlying=%s window=%s..%s",
                underlying, window_start, window_end,
            )
            return {d: None for d in target_dates}

        # Widest strike range across the window for the contract-list
        # request. Per-date strike filtering re-narrows inside the loop
        # so the resulting per-date chain matches the per-date method.
        spot_min = min(usable_spots)
        spot_max = max(usable_spots)
        strike_min = spot_min * (1 - ATM_STRIKE_RANGE_PCT)
        strike_max = spot_max * (1 + ATM_STRIKE_RANGE_PCT)

        # Expiry window union: earliest target_date + DTE_MIN through
        # latest target_date + DTE_MAX covers every per-date interp need.
        exp_start = window_start + timedelta(days=DTE_MIN)
        exp_end = window_end + timedelta(days=DTE_MAX)

        # Pre-fetch contract universe ONCE per right.
        contracts_per_right: Dict[str, List[Dict[str, Any]]] = {}
        for right in ("call", "put"):
            try:
                contracts_per_right[right] = (
                    self._polygon.get_option_contract_candidates(
                        underlying=underlying,
                        as_of_date=window_start,
                        right=right,
                        exp_start=exp_start,
                        exp_end=exp_end,
                        strike_min=strike_min,
                        strike_max=strike_max,
                    )
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "historical_iv_window_contracts_failed underlying=%s "
                    "right=%s error=%s",
                    underlying, right, str(e),
                )
                contracts_per_right[right] = []

        # Pre-fetch each contract's OHLC across the FULL window in one
        # call. Dedup by ticker (some contracts may technically appear
        # in both call/put listings; the dict guards against re-fetch).
        contract_ohlc: Dict[str, Dict[str, float]] = {}
        for right in ("call", "put"):
            for c in contracts_per_right.get(right, []):
                occ = c.get("ticker")
                if not occ or occ in contract_ohlc:
                    continue
                try:
                    contract_ohlc[occ] = self.get_historical_price_range_for_occ(
                        occ, window_start, window_end,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "historical_iv_window_ohlc_failed occ=%s error=%s",
                        occ, str(e),
                    )
                    contract_ohlc[occ] = {}

        # Per-date interpolation from cached chain + OHLC. Mirrors
        # reconstruct_chain_at_date's behavior with per-date strike
        # and DTE filters applied client-side.
        results: Dict[date, Optional[Dict[str, Any]]] = {}
        for d in target_dates:
            spot = spots.get(d)
            if spot is None or spot <= 0:
                results[d] = None
                continue

            d_str = d.strftime("%Y-%m-%d")
            d_strike_min = spot * (1 - ATM_STRIKE_RANGE_PCT)
            d_strike_max = spot * (1 + ATM_STRIKE_RANGE_PCT)

            chain: List[Dict[str, Any]] = []
            for right in ("call", "put"):
                for c in contracts_per_right.get(right, []):
                    occ = c.get("ticker")
                    strike = c.get("strike")
                    exp_str = c.get("expiration")
                    if not occ or strike is None or not exp_str:
                        continue

                    strike_f = float(strike)
                    # Per-date strike filter: match per-date method.
                    if not (d_strike_min <= strike_f <= d_strike_max):
                        continue

                    try:
                        exp_date = date.fromisoformat(exp_str)
                    except (ValueError, TypeError):
                        continue

                    dte = (exp_date - d).days
                    if dte < DTE_MIN or dte > DTE_MAX:
                        continue
                    T = dte / 365.0

                    price = contract_ohlc.get(occ, {}).get(d_str)
                    if price is None or price <= 0:
                        continue

                    iv = invert_iv(
                        price=price,
                        S=spot,
                        K=strike_f,
                        T=T,
                        r=self.r,
                        q=self.q,
                        right=right,
                    )
                    if iv is None:
                        continue

                    chain.append({
                        "details": {
                            "strike_price": strike_f,
                            "contract_type": right,
                            "expiration_date": exp_str,
                        },
                        "implied_volatility": float(iv),
                    })

            if not chain:
                logger.info(
                    "historical_iv_window_empty_chain underlying=%s "
                    "as_of_date=%s spot=%.2f",
                    underlying, d, spot,
                )
                results[d] = None
                continue

            as_of_ts = datetime.combine(d, datetime.min.time())
            result = IVPointService.compute_atm_iv_target_from_chain(
                chain_results=chain,
                spot=spot,
                as_of_ts=as_of_ts,
                target_dte=30.0,
            )

            if not result or result.get("iv") is None:
                logger.info(
                    "historical_iv_window_interp_failed underlying=%s "
                    "as_of_date=%s reason=%s",
                    underlying, d,
                    result.get("iv_method") if result else None,
                )
                results[d] = None
                continue

            # Annotate consistent with per-date method.
            inputs = dict(result.get("inputs") or {})
            inputs["backfill"] = True
            inputs["risk_free_rate"] = self.r
            inputs["dividend_yield"] = self.q
            result["inputs"] = inputs

            results[d] = result

        return results
