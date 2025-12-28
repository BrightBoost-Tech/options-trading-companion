import re
import uuid
import hashlib
import json
from typing import List, Dict, Any, Optional
from packages.quantum.models import SpreadPosition

def parse_option_symbol(symbol: str) -> Dict[str, Any]:
    """
    Parses OCC option symbol.
    Format: ROOTyyMMdd[C/P]00000000
    Example: O:AMZN230616C00125000 -> {underlying: AMZN, expiry: 2023-06-16, type: C, strike: 125.0}
    """
    clean = symbol.replace("O:", "")

    # Regex to capture parts
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

def format_occ_symbol_readable(symbol: str) -> str:
    """
    Convert 'AMZN251219C00255000' to 'AMZN 12/19/25 C 255'.
    """
    # Use existing parsing logic if possible
    try:
        if "O:" in symbol: symbol = symbol.replace("O:", "")
        parsed = parse_option_symbol(symbol)
        if not parsed:
            return symbol # Return original if not parseable

        # Expiry is YYYY-MM-DD, convert to MM/DD/YY
        y, m, d = parsed["expiry"].split("-")
        short_y = y[2:]
        formatted_date = f"{m}/{d}/{short_y}"

        # Strike is float, maybe remove decimals if whole number
        strike = parsed["strike"]
        strike_str = f"{strike:.0f}" if strike.is_integer() else f"{strike}"

        return f"{parsed['underlying']} {formatted_date} {parsed['type']} {strike_str}"
    except Exception:
        return symbol

def compute_legs_fingerprint(order_json: dict) -> str:
    """
    Generates a deterministic hash for the trade structure based on its legs.

    SEMANTICS (Option A): Structure-Only Fingerprinting
    - Includes: Leg composition (underlying, expiry, type, strike, side).
    - Excludes: Quantity (size) and Price (limit/market).

    This ensures that two suggestions with the exact same structure (e.g. "Buy 100C Jan 2025")
    are treated as the SAME suggestion in the database, regardless of whether the system
    later suggests a different quantity or slightly updated limit price. The database
    uniqueness constraint ensures only one active suggestion per structure per cycle exists.
    Updates to size/price for the same structure should overwrite the existing record.

    Normalization:
    - Leg order is irrelevant (legs are sorted before hashing).
    - Symbols are parsed to canonical form to handle "O:" prefixes or formatting differences.
    """
    legs = order_json.get("legs", [])
    if not legs:
        # Fallback for empty legs (e.g. stock trade?)
        # Use underlying + side if available, or just fail safe
        underlying = order_json.get("underlying", "")
        if underlying:
             return hashlib.sha256(f"STOCK:{underlying}".encode("utf-8")).hexdigest()
        return "no_legs"

    normalized_legs = []
    for leg in legs:
        symbol = leg.get("symbol", "")
        side = leg.get("side", "").lower()

        # Parse symbol to get canonical parts
        parsed = parse_option_symbol(symbol)
        if not parsed:
            # Maybe it's a stock symbol?
            # Use raw symbol
            key = f"STOCK:{symbol}"
        else:
            # {underlying}:{expiry}:{type}:{strike}
            # formatting: strike is float, expiry YYYY-MM-DD
            key = f"{parsed['underlying']}:{parsed['expiry']}:{parsed['type']}:{parsed['strike']}"

        # Include side in the hash
        normalized_legs.append(f"{side}:{key}")

    # Sort to ensure A+B == B+A (order independence)
    normalized_legs.sort()

    # Hash
    raw_str = "|".join(normalized_legs)
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

def group_spread_positions(positions: List[Dict]) -> List[SpreadPosition]:
    """
    Groups individual positions into spreads based on underlying, expiry.
    Returns list of SpreadPosition objects.
    """
    grouped = {}
    singles = []

    # 1. Group by Underlying + Expiry
    for pos in positions:
        symbol = pos.get("symbol", "")
        # Skip cash
        if "USD" in symbol or "CASH" in symbol:
            continue

        parsed = parse_option_symbol(symbol)
        if not parsed:
            # Treat as stock/other if not parseable option
            continue

        key = (parsed["underlying"], parsed["expiry"])
        if key not in grouped:
            grouped[key] = []

        # Ensure we have quantity, cost, price
        pos_enriched = {**pos, "parsed": parsed}
        grouped[key].append(pos_enriched)

    final_spreads = []

    for key, legs in grouped.items():
        underlying, expiry = key

        # Calculate aggregates
        net_cost = 0.0
        current_value = 0.0
        delta = 0.0
        gamma = 0.0
        vega = 0.0
        theta = 0.0

        formatted_legs = []

        # Normalize quantity (assuming quantity is raw contracts)
        # We need to detect common quantity.
        # For now, we sum values. The 'quantity' of the spread is heuristic.
        # We'll use the quantity of the first leg as the spread quantity base
        # (simplified, assumes balanced legs).

        base_qty = abs(legs[0].get("quantity", 0)) if legs else 1.0

        user_id = legs[0].get("user_id", "")

        for leg in legs:
            qty = float(leg.get("quantity", 0))
            # Cost basis is total cost for position
            c_basis = float(leg.get("cost_basis", 0) or 0)
            # Current price is usually per share, need to multiply by 100 * qty for total value
            # BUT check if 'current_value' is already total. Usually 'current_value' in holding is total.
            # If not present, derive.
            # Assuming 'current_price' is per share.
            c_price = float(leg.get("current_price", 0))

            # Value calculation
            # If 'market_value' or 'current_value' exists in leg, use it.
            # Otherwise price * 100 * qty
            leg_val = leg.get("market_value") or leg.get("current_value")
            if leg_val is None:
                leg_val = c_price * 100 * qty
            else:
                leg_val = float(leg_val)

            net_cost += c_basis
            current_value += leg_val

            # Greeks - assuming they might be on the leg dict
            delta += float(leg.get("delta", 0)) * 100 * qty # Delta is usually per share
            gamma += float(leg.get("gamma", 0)) * 100 * qty
            vega += float(leg.get("vega", 0)) * 100 * qty
            theta += float(leg.get("theta", 0)) * 100 * qty

            formatted_legs.append({
                "symbol": leg["symbol"],
                "quantity": qty,
                "strike": leg["parsed"]["strike"],
                "expiry": leg["parsed"]["expiry"],
                "type": leg["parsed"]["type"],
                "side": "long" if qty > 0 else "short",
                "current_price": c_price
            })

        # Determine strategy type
        types = set(l["parsed"]["type"] for l in legs)
        sides = set("long" if l.get("quantity", 0) > 0 else "short" for l in legs)

        strategy_type = "custom"
        spread_ticker = f"{underlying} {expiry}"

        if len(legs) == 1:
            strategy_type = "single"
            l = legs[0]
            spread_ticker = f"{underlying} {expiry} {l['parsed']['strike']}{l['parsed']['type']}"
        elif len(legs) == 2:
            # Vertical? Same type, diff strikes, diff sides
            if len(types) == 1 and len(sides) == 2:
                t = list(types)[0]
                # Bull or Bear?
                # Debit Call Spread (Long lower strike, short higher strike)
                # Credit Call Spread (Short lower strike, long higher strike)
                # Sort by strike
                sorted_legs = sorted(legs, key=lambda x: x["parsed"]["strike"])
                lower = sorted_legs[0]
                higher = sorted_legs[1]

                if t == "C":
                    if lower.get("quantity") > 0:
                        strategy_type = "debit_call_spread"
                        spread_ticker += " Call Debit Spread"
                    else:
                        strategy_type = "credit_call_spread"
                        spread_ticker += " Call Credit Spread"
                else: # Put
                    if higher.get("quantity") > 0:
                        strategy_type = "debit_put_spread"
                        spread_ticker += " Put Debit Spread"
                    else:
                        strategy_type = "credit_put_spread"
                        spread_ticker += " Put Credit Spread"
            elif len(types) == 2:
                 spread_ticker += " Combo"

        # Construct Spread object dict
        spread_id = str(uuid.uuid4()) # Dynamic ID for now, or hash legs

        # Ensure type matches Literal in SpreadPosition
        # "debit_call_spread" -> "debit_call" mapping if needed?
        # SpreadPosition expects: "debit_call", "debit_put", "credit_call", "credit_put", "vertical", "iron_condor", "other", "single", "custom", "credit_spread", "debit_spread"

        # Mappings
        type_map = {
            "debit_call_spread": "debit_call",
            "debit_put_spread": "debit_put",
            "credit_call_spread": "credit_call",
            "credit_put_spread": "credit_put"
        }
        normalized_type = type_map.get(strategy_type, strategy_type)
        if normalized_type not in ["debit_call", "debit_put", "credit_call", "credit_put", "vertical", "iron_condor", "single", "credit_spread", "debit_spread"]:
             normalized_type = "other" if normalized_type == "custom" else normalized_type

        spread = SpreadPosition(
            id=spread_id,
            user_id=user_id,
            spread_type=normalized_type,
            underlying=underlying,
            ticker=spread_ticker,
            legs=formatted_legs,
            net_cost=net_cost,
            current_value=current_value,
            delta=delta,
            gamma=gamma,
            vega=vega,
            theta=theta,
            quantity=base_qty
        )
        final_spreads.append(spread)

    return final_spreads
