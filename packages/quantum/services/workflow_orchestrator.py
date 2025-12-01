from supabase import Client
from datetime import datetime, timedelta, timezone
import json
import asyncio
import os
import sys

# Ensure imports work regardless of execution context
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from .cash_service import CashService
from .sizing_engine import calculate_sizing
from .journal_service import JournalService
from .options_utils import group_spread_positions

# Importing existing logic
from options_scanner import scan_for_opportunities
from models import Holding
from market_data import PolygonService
from ev_calculator import calculate_exit_metrics

# Constants for table names
TRADE_SUGGESTIONS_TABLE = "trade_suggestions"
WEEKLY_REPORTS_TABLE = "weekly_trade_reports"

# 1. Add MIDDAY_TEST_MODE flag
MIDDAY_TEST_MODE = os.getenv("MIDDAY_TEST_MODE", "false").lower() == "true"

async def run_morning_cycle(supabase: Client, user_id: str):
    """
    1. Read latest portfolio snapshot + positions.
    2. Group into spreads using group_spread_positions.
    3. Generate EV-based profit-taking suggestions (and skip stop-loss).
    4. Insert records into trade_suggestions table with window='morning_limit'.
    """
    print(f"Running morning cycle for user {user_id}")

    # 1. Fetch current positions
    try:
        res = supabase.table("positions").select("*").eq("user_id", user_id).execute()
        positions = res.data or []
    except Exception as e:
        print(f"Error fetching positions for morning cycle: {e}")
        return

    # 2. Group into Spreads
    spreads = group_spread_positions(positions)

    # Initialize Polygon Service for Greeks
    poly = PolygonService()

    suggestions = []

    # 3. Generate Exit Suggestions per Spread
    for spread in spreads:
        legs = spread.get("legs", [])
        if not legs:
            continue

        # Calculate aggregate cost basis and current value
        # cost_basis/current_price are per share. Quantity is usually number of contracts.
        # Contract size is 100.

        total_cost = 0.0
        total_value = 0.0
        total_quantity = 0.0

        # We need a representative symbol for market data fetch
        # If it's a spread, we might need Greeks of the legs or underlying.
        # For simple EV exit, let's look at the underlying IV and Price action.
        underlying = spread.get("underlying")

        # Check liquidity / Greeks
        # We need Delta and IV.
        # Option 1: Fetch Greeks for each leg and sum them (Portfolio Delta).
        # Option 2: Use underlying IV and approximation.

        net_delta = 0.0

        # We'll use the first leg to get IV reference if possible
        ref_symbol = legs[0]["symbol"]

        iv_rank = 0.5 # Default

        try:
            # Get Snapshot for Greeks of the first leg (approximation for spread environment)
            # Ideally we sum deltas.
            for leg in legs:
                sym = leg["symbol"]
                qty = float(leg.get("quantity", 0))

                # Snapshot
                snap = poly.get_option_snapshot(sym)
                greeks = snap.get("greeks", {})
                delta = greeks.get("delta", 0.0) or 0.0

                # Add to net delta (weighted by qty)
                # Note: spread["type"] might be "C" or "P" or "MIXED".
                # If we are Long the spread, we own the legs.
                # Plaid quantities are usually positive for long.
                # Wait, Plaid 'quantity' can be negative for short?
                # Need to check data source. Usually Plaid returns positive quantity for long.
                # If short, it might be negative?
                # Assuming positive for now, logic below might need refinement for short legs.

                # Polygon delta is usually -1 to 1.
                net_delta += delta * qty

                # Capture IV from one of the legs
                if "implied_volatility" in snap:
                    iv_rank = snap["implied_volatility"]

        except Exception as e:
            print(f"Error fetching greeks for {ref_symbol}: {e}")

        # Calculate spread financials
        for leg in legs:
            qty = float(leg.get("quantity", 0))
            cost = float(leg.get("cost_basis", 0))
            curr = float(leg.get("current_price", 0))

            total_cost += cost * qty * 100
            total_value += curr * qty * 100
            total_quantity += qty # This is sum of legs, not spread count.

        # Assume spread count is min(qty of legs) roughly?
        # For simplicity, treat the suggestion as "Close this entire spread group".

        # Avoid div by zero
        if total_cost == 0: total_cost = 0.01

        spread_price = total_value / 100.0 # Aggregate price per unit (if quantity normalized)
        # Actually, let's work with Totals for metrics, then divide by "unit" count?
        # Or just use the total value.

        # We need a "Current Price" per spread unit to suggest a "Limit Price".
        # Let's assume quantity is homogeneous (e.g. 1 spread = 1 of each leg).
        # If not, it's messy. We will assume 1:1 ratio for morning suggestions.
        # So "Current Price" = Net Value / Quantity of first leg.

        qty_unit = float(legs[0].get("quantity", 1))
        if qty_unit == 0: qty_unit = 1

        unit_price = (total_value / 100.0) / qty_unit
        unit_cost = (total_cost / 100.0) / qty_unit

        # Calculate EV-based Target
        # Use our new helper
        metrics = calculate_exit_metrics(
            current_price=unit_price,
            cost_basis=unit_cost,
            delta=net_delta / qty_unit, # Average delta per unit
            iv=iv_rank,
            days_to_expiry=30 # Placeholder, could parse from expiry
        )

        # Only suggest if profitable and positive expectation
        if metrics.expected_value > 0 and metrics.limit_price > unit_price:
            suggestion = {
                "user_id": user_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "valid_until": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
                "window": "morning_limit",
                "ticker": spread.get("ticker"), # e.g. "KURA 04/17/26 Call Spread"
                "strategy": "take_profit_limit",
                "direction": "close",
                "ev": metrics.expected_value,
                "probability_of_profit": metrics.prob_of_profit,
                "order_json": {
                    "side": "close_spread",
                    "limit_price": round(metrics.limit_price, 2),
                    "legs": [
                        {"symbol": l["symbol"], "quantity": l["quantity"]} for l in legs
                    ]
                },
                "sizing_metadata": {
                    "reason": metrics.reason,
                    "spread_details": {
                        "underlying": underlying,
                        "expiry": spread.get("expiry"),
                        "type": spread.get("type")
                    }
                },
                "status": "pending"
            }
            suggestions.append(suggestion)

    # 4. Insert suggestions
    if suggestions:
        try:
            # Clear old morning suggestions for this user
            supabase.table(TRADE_SUGGESTIONS_TABLE) \
                .delete() \
                .eq("user_id", user_id) \
                .eq("window", "morning_limit") \
                .execute()

            supabase.table(TRADE_SUGGESTIONS_TABLE).insert(suggestions).execute()
            print(f"Inserted {len(suggestions)} morning suggestions.")
        except Exception as e:
            print(f"Error inserting morning suggestions: {e}")


async def run_midday_cycle(supabase: Client, user_id: str):
    """
    1. Use CashService.get_deployable_capital.
    2. Call optimizer/scanner to generate candidate trades.
    3. For each candidate, call sizing_engine.calculate_sizing.
    4. Insert trade_suggestions with window='midday_entry' and sizing_metadata.
    """
    print(f"Running midday cycle for user {user_id}")

    # 3. Add full debug logging to midday cycle
    print("\n=== MIDDAY DEBUG ===")

    cash_service = CashService(supabase)

    # 1. Get deployable capital
    deployable_capital = await cash_service.get_deployable_capital(user_id)
    print(f"Deployable capital: {deployable_capital}")

    if deployable_capital < 100: # Min threshold to bother scanning
        print("Insufficient capital to scan.")
        return

    # 2. Call Scanner (market-wide)
    candidates = []
    scout_results = []
    try:
        # 5. Ensure midday scanning uses full market (no symbols passed)
        scout_results = scan_for_opportunities()  # <-- no symbols arg
        print(f"Scanner returned {len(scout_results)} raw opportunities.")

        print("Top 10 scanner results:")
        for c in scout_results[:10]:
            print(f"- {c.get('ticker')} score={c.get('score')} ev={c.get('ev')}")

        # 4. Guarantee midday suggestions when MIDDAY_TEST_MODE=true
        # A. After scanner returns results:
        if MIDDAY_TEST_MODE:
            print("MIDDAY_TEST_MODE ACTIVE: ignoring score threshold.")
            candidates = scout_results[:3]   # top 3 unfiltered
        else:
            candidates = [c for c in scout_results if c.get("score", 0) >= 20]

        print(f"{len(candidates)} candidates with score >= 20")

    except Exception as e:
        print(f"Scanner failed: {e}")
        return

    suggestions = []

    # 3. Size and Prepare Suggestions
    for cand in candidates:
        ticker = cand.get("ticker")
        strategy = cand.get("strategy", "unknown")

        # Extract pricing info. structure of candidate varies, assuming basic keys
        # The scanner returns dicts with 'suggested_entry', 'ev', etc.
        price = float(cand.get("suggested_entry", 0))
        ev = float(cand.get("ev", 0))

        if price <= 0:
            continue

        # 4. Sizing
        sizing = calculate_sizing(
            account_buying_power=deployable_capital,
            ev_per_contract=ev,
            contract_ask=price,
            max_risk_pct=0.05 # 5% risk per trade
        )

        print(f"SIZING: {ticker} price={price} ev={ev} contracts={sizing['contracts']} risk={sizing}")

        # B. After sizing:
        if MIDDAY_TEST_MODE:
            # Force at least 1 contract for testing
            if sizing["contracts"] <= 0:
                sizing["contracts"] = 1
                sizing["reason"] = "Forced by MIDDAY_TEST_MODE"

        if sizing["contracts"] > 0:
            suggestion = {
                "user_id": user_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "valid_until": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(), # Close of day roughly
                "window": "midday_entry",
                "ticker": ticker,
                "strategy": strategy,
                "direction": "long", # simplified assumption
                "order_json": {
                    "side": "buy",
                    "limit_price": price,
                    "contracts": sizing["contracts"]
                },
                "sizing_metadata": sizing,
                "status": "pending",
                "ev": ev
            }
            suggestions.append(suggestion)

    # C. If candidates still empty:
    if MIDDAY_TEST_MODE and len(suggestions) == 0:
        print("MIDDAY_TEST_MODE: Forcing fallback suggestions")
        fallback = scout_results[:3]
        for item in fallback:
            suggestions.append({
                "user_id": user_id,
                "window": "midday_entry",
                "ticker": item.get("ticker"),
                "strategy": item.get("strategy", "unknown"),
                "direction": "long",
                "ev": item.get("ev", 0),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "valid_until": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
                "order_json": {
                    "side": "buy",
                    "limit_price": float(item.get("suggested_entry", 0)),
                    "contracts": 1
                },
                "sizing_metadata": {"contracts": 1, "test_forced": True},
                "status": "pending"
            })

    print(f"FINAL MIDDAY SUGGESTION COUNT: {len(suggestions)}")

    # Insert suggestions
    if suggestions:
        try:
            # Clear old midday suggestions for this user
            supabase.table(TRADE_SUGGESTIONS_TABLE) \
                .delete() \
                .eq("user_id", user_id) \
                .eq("window", "midday_entry") \
                .execute()

            supabase.table(TRADE_SUGGESTIONS_TABLE).insert(suggestions).execute()
            print(f"Inserted {len(suggestions)} midday suggestions.")
        except Exception as e:
            print(f"Error inserting midday suggestions: {e}")


async def run_weekly_report(supabase: Client, user_id: str):
    """
    1. Use JournalService to aggregate stats for the current week.
    2. Write weekly_trade_reports row with metrics + report_markdown stub.
    """
    print(f"Running weekly report for user {user_id}")

    journal_service = JournalService(supabase)

    # Get stats
    try:
        stats = journal_service.get_journal_stats(user_id)
        # Expected stats structure: {"stats": {...}, "recent_trades": [...]}
        metrics = stats.get("stats", {})
    except Exception as e:
        print(f"Error fetching journal stats: {e}")
        metrics = {}

    # Basic content generation
    win_rate = metrics.get("win_rate", 0)
    total_pnl = metrics.get("total_pnl", 0)
    # Fix: JournalService returns 'trade_count', not 'total_trades'
    trade_count = metrics.get("trade_count", 0)

    report_md = f"""
# Weekly Trading Report

**Week Ending:** {datetime.now().strftime('%Y-%m-%d')}

## Performance Summary
- **P&L:** ${total_pnl:.2f}
- **Win Rate:** {win_rate * 100:.1f}%
- **Trades:** {trade_count}

## AI Insights
*Generated based on your trading history...*
(Placeholder for deeper AI analysis)
    """

    report_data = {
        "user_id": user_id,
        "week_ending": datetime.now().strftime('%Y-%m-%d'),
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "trade_count": trade_count,
        "missed_opportunities": [], # Placeholder
        "report_markdown": report_md.strip()
    }

    try:
        supabase.table(WEEKLY_REPORTS_TABLE).upsert(
            report_data,
            on_conflict="user_id,week_ending"
        ).execute()
        print("Upserted weekly report.")
    except Exception as e:
        print(f"Error upserting weekly report: {e}")
