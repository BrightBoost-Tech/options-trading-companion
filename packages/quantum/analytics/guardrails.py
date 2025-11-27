from datetime import datetime

def get_earnings_date(symbol: str):
    """
    Placeholder for a function that fetches the next earnings date for a symbol.
    MUST NOT return fake dates; return None if unknown.
    """
    # TODO: Implement this with a real data source (e.g., Polygon.io)
    return None

def apply_guardrails(candidates, current_date: datetime | None = None):
    """
    Applies hard filters and warnings to candidate trades using live data.
    No mock paths. If some reference data is unavailable, skip that rule gracefully.
    """
    if current_date is None:
        current_date = datetime.now()

    filtered = []

    for c in candidates:
        symbol = c.get("symbol")
        warnings = c.get("warnings", [])
        reason_to_reject = None

        # Guardrail 1: Earnings cliff (live)
        earnings_date = get_earnings_date(symbol)
        if earnings_date:
            days_to_earnings = (earnings_date - current_date).days
            if 0 <= days_to_earnings <= 5:
                warnings.append(f"EARNINGS_RISK: Reporting in {days_to_earnings} days.")

        # Guardrail 2: Liquidity check (live spreads)
        bid = c.get("bid")
        ask = c.get("ask")
        if bid is not None and ask is not None and ask > 0:
            spread_pct = (ask - bid) / ask
            if spread_pct > 0.05:
                reason_to_reject = f"LIQUIDITY_RISK: Spread is {spread_pct:.1%}"

        c["warnings"] = warnings

        if reason_to_reject:
            c["status"] = "REJECTED"
            c["note"] = reason_to_reject
        else:
            c.setdefault("status", "ACTIVE")

        filtered.append(c)

    return filtered
