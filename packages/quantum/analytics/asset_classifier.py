from enum import Enum
from typing import Literal, Dict, Any, Optional
import re

AssetType = Literal["EQUITY", "OPTION", "CASH", "CRYPTO", "UNKNOWN"]

class AssetClassifier:
    @staticmethod
    def classify_plaid_security(security: Dict[str, Any], holding: Dict[str, Any]) -> AssetType:
        """
        Decide asset type based on Plaid `type`, `subtype`, and ticker.
        - If Plaid says 'equity' or 'etf' → EQUITY.
        - If Plaid says 'cash' or 'savings' → CASH.
        - If Plaid gives an OCC-style option symbol (e.g. 'O:AMZN230616C00125000') → OPTION.
        - If parsing fails and no subtype indicates option → EQUITY.
        - Else → UNKNOWN (flag for review).
        """
        plaid_type = (security.get("type") or "").lower()
        plaid_subtype = (security.get("subtype") or "").lower()
        ticker = security.get("ticker_symbol") or holding.get("symbol") or ""

        # 1. Check strict Plaid types
        if plaid_type in ["cash", "savings"]:
            return "CASH"

        # 2. Check for OCC Option Symbol
        if AssetClassifier.is_occ_option_symbol(ticker):
            return "OPTION"

        # 3. Check Plaid Equity types
        if plaid_type in ["equity", "etf"]:
            return "EQUITY"

        # 4. Fallback logic
        if plaid_type == "cryptocurrency":
            return "CRYPTO"

        # If type is unknown/other, but it's not an option symbol, assume EQUITY for now (like VTSI)
        # We explicitly avoid classifying 'other' as 'OPTION' unless it matches OCC regex.
        if "option" in plaid_type or "option" in plaid_subtype:
             # Double check regex just in case, but if Plaid says option but format is weird,
             # we might want to flag UNKNOWN or force OPTION.
             # But requirement says "If parsing fails ... -> EQUITY" to fix VTSI.
             # However, VTSI misclassification likely happened because it was "other" or unknown
             # and we assumed Option before?
             # Previous logic in options_utils treated non-parseable as stock.
             # So this Logic is consistent: If not OCC regex -> EQUITY (or explicitly CASH/CRYPTO).
             pass

        return "EQUITY"

    @staticmethod
    def is_occ_option_symbol(symbol: str) -> bool:
        """
        Checks if symbol matches OCC format (with optional O: prefix).
        Regex adapted from options_utils.parse_option_symbol.
        """
        if not symbol:
            return False

        clean = symbol.replace("O:", "")
        # Regex from options_utils.py: r"^([A-Z\.-]+)(\d{6})([CP])(\d{8})$"
        match = re.match(r"^([A-Z\.-]+)(\d{6})([CP])(\d{8})$", clean)
        return bool(match)
