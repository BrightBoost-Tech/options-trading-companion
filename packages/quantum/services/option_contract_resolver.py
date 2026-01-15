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
