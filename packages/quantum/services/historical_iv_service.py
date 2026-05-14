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
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from packages.quantum.services.bs_inversion import invert_iv
from packages.quantum.services.iv_point_service import IVPointService

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
