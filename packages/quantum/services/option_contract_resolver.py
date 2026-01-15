"""
Option Contract Resolver - Resolves option contracts based on criteria.

PR2: Provides utilities to find specific option contracts given:
- Underlying symbol
- Option right (call/put)
- Target DTE
- Moneyness (ATM, OTM, ITM)
"""
from datetime import date, datetime, timedelta
from typing import Optional, Literal, List, Dict, Any

from packages.quantum.market_data import PolygonService
from packages.quantum.services.options_utils import build_occ_symbol


class OptionContractResolver:
    """
    Resolves option contracts based on specified criteria.

    Uses Polygon option chain data to find contracts matching:
    - Target DTE (days to expiration)
    - Moneyness (ATM, OTM, ITM)
    - Option right (call/put)
    """

    def __init__(self, polygon_service: PolygonService = None):
        self.polygon = polygon_service or PolygonService()

    def resolve_contract(
        self,
        underlying: str,
        right: Literal["call", "put"],
        target_dte: int = 30,
        moneyness: Literal["atm", "otm_5pct", "itm_5pct"] = "atm",
        as_of_date: date = None
    ) -> Optional[str]:
        """
        Resolves to a specific OCC option symbol based on criteria.

        Args:
            underlying: Stock ticker (e.g., "SPY", "AAPL")
            right: Option type - "call" or "put"
            target_dte: Target days to expiration (default 30)
            moneyness: Strike selection relative to spot:
                - "atm": At-the-money (closest to spot)
                - "otm_5pct": 5% out-of-the-money
                - "itm_5pct": 5% in-the-money
            as_of_date: Reference date for DTE calculation (default: today)

        Returns:
            OCC option symbol (e.g., "O:SPY240315C00450000") or None if not found.

        Example:
            >>> resolver = OptionContractResolver()
            >>> symbol = resolver.resolve_contract("SPY", "call", target_dte=30, moneyness="atm")
            >>> print(symbol)
            'O:SPY240315C00450000'
        """
        as_of_date = as_of_date or date.today()

        # Get current spot price
        spot = self._get_spot_price(underlying)
        if spot is None or spot <= 0:
            return None

        # Calculate target strike based on moneyness
        target_strike = self._calculate_target_strike(spot, right, moneyness)

        # Get option chain
        chain = self._get_filtered_chain(underlying, right, target_dte, as_of_date)
        if not chain:
            return None

        # Find best matching contract
        best_contract = self._find_best_match(chain, target_strike, target_dte, as_of_date)
        if not best_contract:
            return None

        return best_contract.get("ticker")

    def resolve_contract_with_details(
        self,
        underlying: str,
        right: Literal["call", "put"],
        target_dte: int = 30,
        moneyness: Literal["atm", "otm_5pct", "itm_5pct"] = "atm",
        as_of_date: date = None
    ) -> Optional[Dict[str, Any]]:
        """
        Like resolve_contract but returns full contract details.

        Returns:
            Dict with: ticker, strike, expiration, type, bid, ask, price, delta, etc.
            Returns None if no matching contract found.
        """
        as_of_date = as_of_date or date.today()

        spot = self._get_spot_price(underlying)
        if spot is None or spot <= 0:
            return None

        target_strike = self._calculate_target_strike(spot, right, moneyness)

        chain = self._get_filtered_chain(underlying, right, target_dte, as_of_date)
        if not chain:
            return None

        best_contract = self._find_best_match(chain, target_strike, target_dte, as_of_date)
        if not best_contract:
            return None

        # Enrich with spot and calculated fields
        best_contract["underlying"] = underlying
        best_contract["spot_price"] = spot
        best_contract["target_strike"] = target_strike
        best_contract["moneyness"] = moneyness

        return best_contract

    def _get_spot_price(self, underlying: str) -> Optional[float]:
        """Gets current spot price for underlying."""
        try:
            quote = self.polygon.get_recent_quote(underlying)
            price = quote.get("price")
            if price and price > 0:
                return price

            # Fallback: use bid/ask midpoint
            bid = quote.get("bid", 0)
            ask = quote.get("ask", 0)
            if bid > 0 and ask > 0:
                return (bid + ask) / 2

            # Last resort: use historical close
            hist = self.polygon.get_historical_prices(underlying, days=2)
            if hist and hist.get("prices"):
                return hist["prices"][-1]

            return None
        except Exception:
            return None

    def _calculate_target_strike(
        self,
        spot: float,
        right: str,
        moneyness: str
    ) -> float:
        """
        Calculates target strike based on spot price and moneyness.

        For calls:
            - ATM: spot
            - OTM 5%: spot * 1.05
            - ITM 5%: spot * 0.95

        For puts:
            - ATM: spot
            - OTM 5%: spot * 0.95
            - ITM 5%: spot * 1.05
        """
        if moneyness == "atm":
            return spot

        is_call = right.lower() == "call"

        if moneyness == "otm_5pct":
            return spot * 1.05 if is_call else spot * 0.95
        elif moneyness == "itm_5pct":
            return spot * 0.95 if is_call else spot * 1.05

        return spot

    def _get_filtered_chain(
        self,
        underlying: str,
        right: str,
        target_dte: int,
        as_of_date: date
    ) -> List[Dict]:
        """
        Fetches and filters option chain for target DTE range.

        Widens DTE window to ensure we find contracts:
        - Min DTE: target_dte - 10 (but >= 5)
        - Max DTE: target_dte + 15
        """
        min_dte = max(5, target_dte - 10)
        max_dte = target_dte + 15

        try:
            chain = self.polygon.get_option_chain(underlying, min_dte=min_dte, max_dte=max_dte)
        except Exception:
            return []

        # Filter by right (call/put)
        right_lower = right.lower()
        filtered = [c for c in chain if c.get("type", "").lower() == right_lower]

        return filtered

    def _find_best_match(
        self,
        chain: List[Dict],
        target_strike: float,
        target_dte: int,
        as_of_date: date
    ) -> Optional[Dict]:
        """
        Finds the best matching contract from the chain.

        Scoring:
        - Primary: Closest DTE to target (weight: 2x)
        - Secondary: Closest strike to target (weight: 1x)

        Returns contract with lowest combined score.
        """
        if not chain:
            return None

        scored = []
        for contract in chain:
            strike = contract.get("strike", 0)
            exp_str = contract.get("expiration", "")

            if not (strike > 0 and exp_str):
                continue

            # Calculate DTE
            try:
                exp_date = datetime.fromisoformat(exp_str).date()
            except ValueError:
                try:
                    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                except ValueError:
                    continue

            dte = (exp_date - as_of_date).days
            if dte < 1:
                continue

            # Score: lower is better
            dte_diff = abs(dte - target_dte)
            strike_diff = abs(strike - target_strike) / target_strike  # Normalized

            # Combined score (DTE weighted 2x)
            score = (dte_diff * 2) + (strike_diff * 100)

            scored.append((score, contract))

        if not scored:
            return None

        # Return best match (lowest score)
        scored.sort(key=lambda x: x[0])
        return scored[0][1]

    def build_contract_symbol(
        self,
        underlying: str,
        expiry: date,
        right: str,
        strike: float
    ) -> str:
        """
        Builds an OCC option symbol from components.

        Convenience wrapper around build_occ_symbol.

        Args:
            underlying: Stock ticker
            expiry: Expiration date
            right: "call" or "put"
            strike: Strike price

        Returns:
            OCC symbol (e.g., "O:AAPL240119C00150000")
        """
        return build_occ_symbol(underlying, expiry, right, strike)

    def resolve_contract_with_coverage(
        self,
        underlying: str,
        right: Literal["call", "put"],
        target_dte: int = 30,
        moneyness: Literal["atm", "otm_5pct", "itm_5pct"] = "atm",
        as_of_date: date = None,
        window_start: date = None,
        window_end: date = None,
        min_bars: int = 60,
        max_candidates: int = 30
    ) -> Optional[str]:
        """
        PR6: Resolves to an option symbol that has sufficient historical OHLC coverage.

        Unlike resolve_contract, this method verifies that the chosen contract has
        enough historical bars within the backtest window. This prevents selecting
        contracts that barely trade in the evaluation period.

        Args:
            underlying: Stock ticker (e.g., "SPY", "AAPL")
            right: Option type - "call" or "put"
            target_dte: Target days to expiration (default 30)
            moneyness: Strike selection relative to spot
            as_of_date: Reference date for DTE calculation
            window_start: Start of backtest window (required for coverage check)
            window_end: End of backtest window (required for coverage check)
            min_bars: Minimum number of OHLC bars required (default 60)
            max_candidates: Maximum candidates to check for coverage (default 30)

        Returns:
            OCC option symbol with sufficient coverage, or None if not found.

        Example:
            >>> resolver = OptionContractResolver()
            >>> symbol = resolver.resolve_contract_with_coverage(
            ...     "SPY", "call", target_dte=30, moneyness="atm",
            ...     as_of_date=date(2024, 1, 1),
            ...     window_start=date(2024, 1, 1),
            ...     window_end=date(2024, 3, 31),
            ...     min_bars=60
            ... )
        """
        as_of_date = as_of_date or date.today()

        # If no window specified, fall back to basic resolution
        if window_start is None or window_end is None:
            return self.resolve_contract(
                underlying, right, target_dte, moneyness, as_of_date
            )

        # Get current spot price
        spot = self._get_spot_price(underlying)
        if spot is None or spot <= 0:
            return None

        # Calculate target strike based on moneyness
        target_strike = self._calculate_target_strike(spot, right, moneyness)

        # Get option chain
        chain = self._get_filtered_chain(underlying, right, target_dte, as_of_date)
        if not chain:
            return None

        # Score and rank all candidates
        scored_candidates = self._score_candidates(chain, target_strike, target_dte, as_of_date)
        if not scored_candidates:
            return None

        # Check top N candidates for sufficient historical coverage
        window_start_dt = datetime.combine(window_start, datetime.min.time())
        window_end_dt = datetime.combine(window_end, datetime.min.time())

        for score, contract in scored_candidates[:max_candidates]:
            ticker = contract.get("ticker")
            if not ticker:
                continue

            # Fetch historical OHLC for this contract
            try:
                hist = self.polygon.get_option_historical_prices(
                    ticker,
                    start_date=window_start_dt,
                    end_date=window_end_dt
                )

                if hist and hist.get("prices"):
                    bar_count = len(hist["prices"])
                    if bar_count >= min_bars:
                        return ticker
            except Exception:
                # Skip this candidate on error
                continue

        # No candidate met the min_bars requirement
        return None

    def _score_candidates(
        self,
        chain: List[Dict],
        target_strike: float,
        target_dte: int,
        as_of_date: date
    ) -> List[tuple]:
        """
        Scores and ranks all candidates in the chain.

        Returns:
            List of (score, contract) tuples sorted by score (lowest first).
        """
        scored = []
        for contract in chain:
            strike = contract.get("strike", 0)
            exp_str = contract.get("expiration", "")

            if not (strike > 0 and exp_str):
                continue

            # Calculate DTE
            try:
                exp_date = datetime.fromisoformat(exp_str).date()
            except ValueError:
                try:
                    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                except ValueError:
                    continue

            dte = (exp_date - as_of_date).days
            if dte < 1:
                continue

            # Score: lower is better
            dte_diff = abs(dte - target_dte)
            strike_diff = abs(strike - target_strike) / target_strike  # Normalized

            # Combined score (DTE weighted 2x)
            score = (dte_diff * 2) + (strike_diff * 100)

            scored.append((score, contract))

        # Sort by score (lowest first)
        scored.sort(key=lambda x: x[0])
        return scored

    def resolve_contract_asof(
        self,
        underlying: str,
        right: Literal["call", "put"],
        target_dte: int = 30,
        moneyness: Literal["atm", "otm_5pct", "itm_5pct"] = "atm",
        as_of_date: date = None
    ) -> Optional[str]:
        """
        PR7: Resolves an option contract using historical data as of a specific date.

        Unlike resolve_contract (which uses current market snapshot), this method:
        - Uses historical closing price of underlying at as_of_date for strike calc
        - Uses reference endpoint to list contracts (works for historical dates)
        - Does NOT require current market data

        Args:
            underlying: Stock ticker (e.g., "SPY")
            right: Option type - "call" or "put"
            target_dte: Target days to expiration (default 30)
            moneyness: Strike selection relative to spot
            as_of_date: Historical date to resolve contract as of

        Returns:
            OCC option symbol or None if not found
        """
        as_of_date = as_of_date or date.today()

        # Get historical spot price at as_of_date
        spot = self.polygon.get_historical_spot_price(underlying, as_of_date)
        if spot is None or spot <= 0:
            return None

        # Calculate target strike based on moneyness
        target_strike = self._calculate_target_strike(spot, right, moneyness)

        # Calculate expiration window around target_dte
        target_exp = as_of_date + timedelta(days=target_dte)
        exp_start = target_exp - timedelta(days=10)
        exp_end = target_exp + timedelta(days=15)

        # Calculate strike range (±15% from target)
        strike_min = target_strike * 0.85
        strike_max = target_strike * 1.15

        # Get contract candidates from reference endpoint
        candidates = self.polygon.get_option_contract_candidates(
            underlying=underlying,
            as_of_date=as_of_date,
            right=right,
            exp_start=exp_start,
            exp_end=exp_end,
            strike_min=strike_min,
            strike_max=strike_max,
            limit=100
        )

        if not candidates:
            return None

        # Score and find best match
        scored = self._score_candidates(candidates, target_strike, target_dte, as_of_date)
        if not scored:
            return None

        return scored[0][1].get("ticker")

    def resolve_contract_asof_with_coverage(
        self,
        underlying: str,
        right: Literal["call", "put"],
        target_dte: int = 30,
        moneyness: Literal["atm", "otm_5pct", "itm_5pct"] = "atm",
        as_of_date: date = None,
        window_start: date = None,
        window_end: date = None,
        min_bars: int = 20,
        max_candidates: int = 30
    ) -> Optional[str]:
        """
        PR7: Resolves option contract as-of date with OHLC coverage validation.

        Combines historical contract resolution with bar coverage check.
        Used for rolling contract selection where each entry needs its own contract.

        Args:
            underlying: Stock ticker
            right: "call" or "put"
            target_dte: Target days to expiration
            moneyness: Strike selection
            as_of_date: Date to resolve contract as of (entry date)
            window_start: Start of coverage window (usually as_of_date)
            window_end: End of coverage window
            min_bars: Minimum OHLC bars required
            max_candidates: Max candidates to check

        Returns:
            OCC option symbol with sufficient coverage, or None
        """
        as_of_date = as_of_date or date.today()
        window_start = window_start or as_of_date
        window_end = window_end or (as_of_date + timedelta(days=30))

        # Get historical spot
        spot = self.polygon.get_historical_spot_price(underlying, as_of_date)
        if spot is None or spot <= 0:
            return None

        target_strike = self._calculate_target_strike(spot, right, moneyness)

        # Expiration must be after window_end to avoid expiry during holding
        target_exp = as_of_date + timedelta(days=target_dte)
        exp_start = max(window_end, target_exp - timedelta(days=10))
        exp_end = target_exp + timedelta(days=30)

        strike_min = target_strike * 0.85
        strike_max = target_strike * 1.15

        candidates = self.polygon.get_option_contract_candidates(
            underlying=underlying,
            as_of_date=as_of_date,
            right=right,
            exp_start=exp_start,
            exp_end=exp_end,
            strike_min=strike_min,
            strike_max=strike_max,
            limit=100
        )

        if not candidates:
            return None

        # Score candidates
        scored = self._score_candidates(candidates, target_strike, target_dte, as_of_date)
        if not scored:
            return None

        # Check coverage for top candidates
        window_start_dt = datetime.combine(window_start, datetime.min.time())
        window_end_dt = datetime.combine(window_end, datetime.min.time())

        for score, contract in scored[:max_candidates]:
            ticker = contract.get("ticker")
            if not ticker:
                continue

            try:
                hist = self.polygon.get_option_historical_prices(
                    ticker,
                    start_date=window_start_dt,
                    end_date=window_end_dt
                )

                if hist and hist.get("prices"):
                    bar_count = len(hist["prices"])
                    if bar_count >= min_bars:
                        return ticker
            except Exception:
                continue

        return None
