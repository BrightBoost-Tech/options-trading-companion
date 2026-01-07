from datetime import datetime, date
from typing import List, Union, Any
import re

def normalize_symbol(symbol: str) -> str:
    """
    Normalizes a symbol:
    - Uppercase and trim
    - Handles 'O:' prefix for options (length > 5 chars)
    - 🛡️ Sentinel: Sanitizes input to prevent URL injection/traversal
    """
    if not symbol:
        return ""

    s = symbol.strip().upper()

    # 🛡️ Sentinel: Sanitize to prevent URL injection/traversal
    # Allow A-Z, 0-9, ., -, : (for O: prefix or currencies)
    # This prevents '?', '&', '/', and other special chars from breaking URL structure
    s = re.sub(r'[^A-Z0-9\.\-\:]', '', s)

    # Polygon option symbol logic
    # - Must be > 5 chars
    # - Must NOT start with O: (already handled or doesn't need it)
    # - Must NOT be a crypto pair (usually contains '-')
    # - Must NOT be a currency pair (usually contains ':')
    # - Must contain digits (options always have dates/prices)
    if len(s) > 5 and not s.startswith('O:') and '-' not in s and ':' not in s and any(c.isdigit() for c in s):
        return f"O:{s}"

    return s

def normalize_date(d: Union[str, date, datetime]) -> str:
    """
    Normalizes a date to YYYY-MM-DD string.
    """
    if d is None:
        return ""

    if isinstance(d, (datetime, date)):
        return d.strftime('%Y-%m-%d')

    if isinstance(d, str):
        # Try to parse ISO format
        try:
            # Handle Z if present (Python < 3.11 compat)
            clean_d = d.replace('Z', '+00:00') if d.endswith('Z') else d
            dt = datetime.fromisoformat(clean_d)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            # If not parseable as ISO, return as is
            return d

    return str(d)

def make_cache_key_parts(kind: str, **kwargs) -> List[str]:
    """
    Generates a deterministic list of cache key parts based on the kind of request.

    Supported kinds:
    - OHLC: symbol, days, to_date (or to_date_str)
    - QUOTE: symbol
    - SNAPSHOT: symbol
    - CHAIN: underlying, strike_range, limit, date_str
    - EARNINGS: symbol, today_str
    - DETAILS: symbol
    - IV_RANK: symbol
    """
    kind = kind.upper()

    if kind == "OHLC":
        sym = normalize_symbol(kwargs.get('symbol', ''))
        days = str(kwargs.get('days', 252))
        to_date = normalize_date(kwargs.get('to_date') or kwargs.get('to_date_str', ''))
        return [sym, days, to_date]

    elif kind in ("QUOTE", "SNAPSHOT", "DETAILS", "IV_RANK"):
        sym = normalize_symbol(kwargs.get('symbol', ''))
        return [sym]

    elif kind == "EARNINGS":
        sym = normalize_symbol(kwargs.get('symbol', ''))
        today = normalize_date(kwargs.get('today_str') or date.today())
        return [sym, today]

    elif kind == "CHAIN":
        underlying = normalize_symbol(kwargs.get('underlying', ''))
        # strike_range is float usually
        sr = kwargs.get('strike_range', 0.20)
        limit = kwargs.get('limit', 1000)

        # CHAIN uses hour resolution in current implementation
        date_val = kwargs.get('date_str')
        if not date_val:
             date_val = datetime.now().strftime('%Y-%m-%d-%H')

        return [underlying, str(sr), str(limit), str(date_val)]

    else:
        # Deterministic fallback: sorted keys
        return [f"{k}={kwargs[k]}" for k in sorted(kwargs.keys())]
