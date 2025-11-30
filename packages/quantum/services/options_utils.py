import re
from typing import List, Dict, Any, Optional

def parse_option_symbol(symbol: str) -> Dict[str, Any]:
    """
    Parses OCC option symbol.
    Format: ROOTyyMMdd[C/P]00000000
    Example: O:AMZN230616C00125000 -> {underlying: AMZN, expiry: 2023-06-16, type: C, strike: 125.0}
    """
    clean = symbol.replace("O:", "")

    # Regex to capture parts
    # Group 1: Underlying (letters, can have dots)
    # Group 2: Expiry (6 digits)
    # Group 3: Type (C/P)
    # Group 4: Strike (8 digits)
    match = re.match(r"^([A-Z\.-]+)(\d{6})([CP])(\d{8})$", clean)

    if not match:
        return {}

    underlying = match.group(1)
    expiry_str = match.group(2) # YYMMDD
    opt_type = match.group(3)
    strike_str = match.group(4)

    # Format expiry to YYYY-MM-DD
    # Assuming 20xx
    expiry = f"20{expiry_str[0:2]}-{expiry_str[2:4]}-{expiry_str[4:6]}"

    strike = float(strike_str) / 1000.0

    return {
        "underlying": underlying,
        "expiry": expiry,
        "type": opt_type,
        "strike": strike
    }

def group_spread_positions(positions: List[Dict]) -> List[Dict]:
    """
    Groups individual positions into spreads based on underlying, expiry.
    Matches logic from frontend groupOptionSpreads.
    """
    grouped = {}
    singles = []

    for pos in positions:
        symbol = pos.get("symbol", "")
        # Skip cash
        if "USD" in symbol or "CASH" in symbol:
            continue

        parsed = parse_option_symbol(symbol)
        if not parsed:
            singles.append({**pos, "parsed": {}})
            continue

        # Key: Underlying + Expiry
        # Note: Frontend groups by underlying+expiry, then detects type (Call/Put spread vs Iron Condor etc)
        # For Morning suggestions, we want to group Vertical Spreads primarily.
        # Key = (Underlying, Expiry)
        key = (parsed["underlying"], parsed["expiry"])

        if key not in grouped:
            grouped[key] = []

        grouped[key].append({**pos, "parsed": parsed})

    final_spreads = []

    for key, legs in grouped.items():
        underlying, expiry = key

        # Determine spread type
        # If all same type (C or P), it's a Vertical Spread
        # If mix, could be Straddle/Strangle/Iron Condor

        types = set(l["parsed"]["type"] for l in legs)

        # If single leg, treat as single
        if len(legs) == 1:
            leg = legs[0]
            final_spreads.append({
                "ticker": f"{underlying} {expiry} {leg['parsed']['strike']}{leg['parsed']['type']}",
                "underlying": underlying,
                "expiry": expiry,
                "type": leg["parsed"]["type"], # C or P
                "strategy_type": "single",
                "legs": legs
            })
            continue

        # Multi-leg logic
        if len(types) == 1:
            # Vertical Spread (e.g. Call Debit Spread)
            spread_type = list(types)[0] # C or P

            # Determine debit/credit?
            # Need quantities to know short/long

            final_spreads.append({
                "ticker": f"{underlying} {expiry} {spread_type} Spread",
                "underlying": underlying,
                "expiry": expiry,
                "type": spread_type,
                "strategy_type": "vertical_spread",
                "legs": legs
            })
        else:
            # Mixed types (e.g. Iron Condor)
            final_spreads.append({
                "ticker": f"{underlying} {expiry} Combo",
                "underlying": underlying,
                "expiry": expiry,
                "type": "MIXED",
                "strategy_type": "combo",
                "legs": legs
            })

    # Add back non-option positions if any (filtered out earlier but if needed)

    return final_spreads
