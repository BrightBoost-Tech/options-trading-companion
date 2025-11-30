from supabase import Client
from datetime import datetime, timedelta, timezone
import json
import asyncio

from .cash_service import CashService
from .sizing_engine import calculate_sizing
from .journal_service import JournalService

# Importing existing logic
# Assuming these are available in the parent package or imported via absolute path
# from optimizer import optimize_portfolio # This is an endpoint, not a logic function in optimizer.py
from options_scanner import scan_for_opportunities
from models import Holding

# Constants for table names (matching those we will add to api.py)
TRADE_SUGGESTIONS_TABLE = "trade_suggestions"
WEEKLY_REPORTS_TABLE = "weekly_trade_reports"

async def run_morning_cycle(supabase: Client, user_id: str):
    """
    1. Read latest portfolio snapshot + positions.
    2. Enrich with risk / P&L (already done by enrichment_service when snapshot is created).
    3. Generate 'limit order' suggestions (take-profit & stop-loss) for existing positions.
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

    suggestions = []

    # 2. Generate Exit Suggestions (Simple logic for now)
    # Stop Loss at -50%, Take Profit at +50%
    for pos in positions:
        symbol = pos.get("symbol", "")
        # Skip cash
        if "USD" in symbol or "CASH" in symbol:
            continue

        cost_basis = float(pos.get("cost_basis", 0) or 0)
        current_price = float(pos.get("current_price", 0) or 0)
        qty = float(pos.get("quantity", 0) or 0)

        if qty == 0 or cost_basis == 0:
            continue

        # Basic logic: If we have an option, suggest a limit order
        # This is a placeholder for more advanced "Exit Strategy" logic
        # For now, we just suggest watching positions that are nearing thresholds

        pnl_pct = (current_price - cost_basis) / cost_basis

        strategy = "hold"
        limit_price = 0.0
        reason = ""

        if pnl_pct <= -0.4:
            strategy = "stop_loss_alert"
            limit_price = current_price # Sell at market/current
            reason = "Stop Loss Alert: Position down > 40%"
        elif pnl_pct >= 0.5:
             strategy = "take_profit_alert"
             limit_price = current_price
             reason = "Take Profit Alert: Position up > 50%"

        if strategy != "hold":
            suggestion = {
                "user_id": user_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "valid_until": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(), # End of day
                "window": "morning_limit",
                "ticker": symbol,
                "strategy": strategy,
                "direction": "sell" if qty > 0 else "cover",
                "order_json": {
                    "side": "sell" if qty > 0 else "buy",
                    "limit_price": limit_price,
                    "contracts": abs(qty)
                },
                "sizing_metadata": {
                    "capital_required": 0, # Exits don't require capital usually
                    "reason": reason
                },
                "status": "pending"
            }
            suggestions.append(suggestion)

    # 4. Insert suggestions
    if suggestions:
        try:
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

    cash_service = CashService(supabase)

    # 1. Get deployable capital
    deployable_capital = await cash_service.get_deployable_capital(user_id)
    print(f"Deployable capital: ${deployable_capital}")

    if deployable_capital < 100: # Min threshold to bother scanning
        print("Insufficient capital to scan.")
        return

    # 2. Call Scanner (using existing logic)
    # We need to fetch holdings first to exclude them or use them as basis,
    # but scan_for_opportunities usually takes a list of symbols.
    # For now, let's use a default list or user's watch list if available.
    # The prompt implies re-using existing logic. `scan_for_opportunities` in `options_scanner.py`
    # takes a list of symbols.

    # Let's try to get symbols from user positions + some defaults?
    # Or just run the weekly scout logic which defaults to positions.

    # Re-using weekly scout logic pattern:
    try:
        res = supabase.table("positions").select("symbol").eq("user_id", user_id).execute()
        holdings = res.data or []
        symbols = list(set([h["symbol"] for h in holdings if "USD" not in h["symbol"] and "CASH" not in h["symbol"]]))
    except Exception:
        symbols = []

    if not symbols:
        # Fallback to some major tech stocks if portfolio is empty, to give them something
        symbols = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "TSLA"]

    candidates = []
    try:
        # scan_for_opportunities is synchronous, might block if not careful, but we are in async def.
        # It calls API which might block. Ideally we run in executor if it's blocking.
        # But for now direct call as per existing api.py pattern.
        scout_results = scan_for_opportunities(symbols=symbols)
        # Filter for good scores
        candidates = [c for c in scout_results if c.get("score", 0) > 70]
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
                "status": "pending"
            }
            suggestions.append(suggestion)

    # Insert suggestions
    if suggestions:
        try:
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
    trade_count = metrics.get("total_trades", 0)

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
