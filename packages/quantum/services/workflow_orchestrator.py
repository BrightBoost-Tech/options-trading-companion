from supabase import Client
from datetime import datetime, timedelta, timezone
import json
import asyncio
import os
import sys

from .cash_service import CashService
from .sizing_engine import calculate_sizing
from .journal_service import JournalService
from .options_utils import group_spread_positions, format_occ_symbol_readable
from .exit_stats_service import ExitStatsService
from .market_data_truth_layer import MarketDataTruthLayer
from .analytics_service import AnalyticsService

# Importing existing logic
from packages.quantum.options_scanner import scan_for_opportunities
from packages.quantum.analytics.regime_engine_v3 import RegimeEngineV3, RegimeState, GlobalRegimeSnapshot
from packages.quantum.models import Holding
from packages.quantum.market_data import PolygonService
from packages.quantum.ev_calculator import calculate_exit_metrics
from packages.quantum.analytics.loss_minimizer import LossMinimizer
from packages.quantum.analytics.conviction_service import ConvictionService
from packages.quantum.services.iv_repository import IVRepository
from packages.quantum.services.iv_point_service import IVPointService

# v3 Observability
from packages.quantum.observability.telemetry import TradeContext, compute_features_hash, emit_trade_event

# Constants for table names
TRADE_SUGGESTIONS_TABLE = "trade_suggestions"
WEEKLY_REPORTS_TABLE = "weekly_trade_reports"
SUGGESTION_LOGS_TABLE = "suggestion_logs"

# 1. Add MIDDAY_TEST_MODE flag
MIDDAY_TEST_MODE = os.getenv("MIDDAY_TEST_MODE", "false").lower() == "true"
APP_VERSION = os.getenv("APP_VERSION", "v2-dev")

async def run_morning_cycle(supabase: Client, user_id: str):
    """
    1. Read latest portfolio snapshot + positions.
    2. Group into spreads using group_spread_positions.
    3. Generate EV-based profit-taking suggestions (and skip stop-loss).
    4. Insert records into trade_suggestions table with window='morning_limit'.
    """
    print(f"Running morning cycle for user {user_id}")
    analytics_service = AnalyticsService(supabase)

    # 1. Fetch current positions
    try:
        res = supabase.table("positions").select("*").eq("user_id", user_id).execute()
        positions = res.data or []
    except Exception as e:
        print(f"Error fetching positions for morning cycle: {e}")
        return

    # 2. Group into Spreads
    spreads = group_spread_positions(positions)

    # Initialize Market Data Truth Layer
    truth_layer = MarketDataTruthLayer()

    # V3: Compute Global Regime Snapshot ONCE
    # market_data = PolygonService() # REMOVED: Not used in morning cycle, and not for RegimeEngine
    iv_repo = IVRepository(supabase)
    iv_point_service = IVPointService(supabase)

    regime_engine = RegimeEngineV3(
        supabase_client=supabase,
        market_data=truth_layer,
        iv_repository=iv_repo,
        iv_point_service=iv_point_service,
    )

    global_snap = regime_engine.compute_global_snapshot(datetime.now())
    # Try to persist global snapshot
    try:
        supabase.table("regime_snapshots").insert(global_snap.to_dict()).execute()
    except Exception:
        pass

    suggestions = []

    # 3. Generate Exit Suggestions per Spread
    for spread in spreads:
        legs = spread.legs # Object access
        if not legs:
            continue

        total_cost = 0.0
        total_value = 0.0
        total_quantity = 0.0

        underlying = spread.underlying
        net_delta = 0.0
        iv_rank = 50.0 # Default fallback
        # iv_regime initialized via V3 logic below
        effective_regime_state = RegimeState.NORMAL
        iv_regime = "normal"

        ref_symbol = legs[0]["symbol"]

        try:
            # 3a. Use Truth Layer for Options Data
            leg_symbols = [l["symbol"] for l in legs]
            snapshots = truth_layer.snapshot_many(leg_symbols)

            # V3 Symbol Snapshot
            sym_snap = regime_engine.compute_symbol_snapshot(underlying, global_snap)
            effective_regime_state = regime_engine.get_effective_regime(sym_snap, global_snap)

            # Map to scoring regime string for compatibility
            iv_regime = regime_engine.map_to_scoring_regime(effective_regime_state)
            iv_rank_score = sym_snap.iv_rank if sym_snap.iv_rank is not None else 50.0

            # Sum Deltas
            for leg in legs:
                sym = leg["symbol"]
                qty = float(leg.get("quantity", 0))

                norm_sym = truth_layer.normalize_symbol(sym)
                snap = snapshots.get(norm_sym, {})

                greeks = snap.get("greeks", {})
                delta = greeks.get("delta", 0.0) or 0.0

                net_delta += delta * qty

            # Use IV from context as reference
            norm_ref = truth_layer.normalize_symbol(ref_symbol)
            first_snap = snapshots.get(norm_ref, {})
            iv_decimal = first_snap.get("iv")
            if iv_decimal is None:
                 iv_decimal = 0.5 # fallback

        except Exception as e:
            print(f"Error fetching greeks for {ref_symbol}: {e}")
            iv_decimal = 0.5
            iv_rank_score = 50.0

        # Calculate spread financials
        for leg in legs:
            qty = float(leg.get("quantity", 0))
            cost = float(leg.get("cost_basis", 0) or 0)
            curr = float(leg.get("current_price", 0) or 0)

            total_cost += cost * qty * 100
            total_value += curr * qty * 100
            total_quantity += qty

        if total_cost == 0: total_cost = 0.01

        qty_unit = float(legs[0].get("quantity", 1))
        if qty_unit == 0: qty_unit = 1

        unit_price = (total_value / 100.0) / qty_unit
        unit_cost = (total_cost / 100.0) / qty_unit

        # Calculate EV-based Target
        metrics = calculate_exit_metrics(
            current_price=unit_price,
            cost_basis=unit_cost,
            delta=net_delta / qty_unit,
            iv=iv_decimal,
            days_to_expiry=30
        )

        if unit_price < unit_cost * 0.5:
             pass

        if metrics.expected_value > 0 and metrics.limit_price > unit_price:

            hist_stats = ExitStatsService.get_stats(
                underlying=underlying,
                regime=iv_regime,
                strategy="take_profit_limit",
                supabase_client=supabase
            )

            if hist_stats.get("insufficient_history") or hist_stats.get("win_rate") is None:
                rationale_text = (
                    f"Take profit at ${metrics.limit_price:.2f} based on EV model. "
                    f"(Insufficient history for win-rate stats in {iv_regime} regime.)"
                )
            else:
                win_rate_pct = hist_stats['win_rate'] * 100
                rationale_text = (
                    f"Take profit at ${metrics.limit_price:.2f} based on {win_rate_pct:.0f}% "
                    f"historical win rate for similar exits in {iv_regime} regime."
                )

            features_dict = {
                "unit_price": unit_price,
                "unit_cost": unit_cost,
                "delta": net_delta / qty_unit,
                "iv_rank": iv_rank_score,
                "regime": iv_regime,
                "global_regime": global_snap.state.value,
                "strategy": "take_profit_limit",
                "underlying": underlying
            }

            ctx = TradeContext.create_new(
                model_version=APP_VERSION,
                window="morning_limit",
                strategy="take_profit_limit",
                regime=iv_regime
            )
            ctx.features_hash = compute_features_hash(features_dict)

            suggestion = {
                    "user_id": user_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "valid_until": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
                    "window": "morning_limit",
                    "ticker": spread.ticker,
                    "display_symbol": spread.ticker,
                    "strategy": "take_profit_limit",
                    "direction": "close",
                    "ev": metrics.expected_value,
                    "probability_of_profit": metrics.prob_of_profit,
                    "rationale": rationale_text,
                    "historical_stats": hist_stats,
                    "order_json": {
                        "side": "close_spread",
                        "limit_price": round(metrics.limit_price, 2),
                        "legs": [
                            {
                                "symbol": l["symbol"],
                                "display_symbol": format_occ_symbol_readable(l["symbol"]),
                                "quantity": l["quantity"]
                            } for l in legs
                        ]
                    },
                "sizing_metadata": {
                    "reason": metrics.reason,
                    "context": {
                        "iv_rank": iv_rank_score,
                        "iv_regime": iv_regime,
                        "global_state": global_snap.state.value,
                        "regime_v3_global": global_snap.state.value,
                        "regime_v3_symbol": sym_snap.state.value,
                        "regime_v3_effective": effective_regime_state.value
                    },
                    "spread_details": {
                        "underlying": underlying,
                        "expiry": legs[0]["expiry"],
                        "type": spread.spread_type
                    }
                },
                "status": "pending",
                "trace_id": ctx.trace_id,
                "model_version": ctx.model_version,
                "features_hash": ctx.features_hash,
                "regime": ctx.regime
            }
            suggestions.append(suggestion)

            emit_trade_event(
                analytics_service,
                user_id,
                ctx,
                "suggestion_generated",
                properties={"ev": metrics.expected_value, "ticker": spread.ticker}
            )

    # 4. Insert suggestions
    if suggestions:
        try:
            supabase.table(TRADE_SUGGESTIONS_TABLE) \
                .delete() \
                .eq("user_id", user_id) \
                .eq("window", "morning_limit") \
                .execute()

            supabase.table(TRADE_SUGGESTIONS_TABLE).insert(suggestions).execute()
            print(f"Inserted {len(suggestions)} morning suggestions.")
        except Exception as e:
            print(f"Error inserting morning suggestions: {e}")

        # 5. Log suggestions
        try:
            logs = []
            for s in suggestions:
                target = s.get("order_json", {}).get("limit_price", 0.0)
                logs.append({
                    "user_id": user_id,
                    "created_at": s["created_at"],
                    "regime_context": {"cycle": "morning_limit", "global": global_snap.state.value},
                    "symbol": s["ticker"],
                    "strategy_type": s["strategy"],
                    "direction": s["direction"],
                    "target_price": target,
                    "confidence_score": s.get("probability_of_profit", 0) * 100,
                })

            if logs:
                supabase.table(SUGGESTION_LOGS_TABLE).insert(logs).execute()
                print(f"Logged {len(logs)} morning suggestions to ledger.")
        except Exception as e:
            print(f"Error logging morning suggestions: {e}")


async def run_midday_cycle(supabase: Client, user_id: str):
    """
    1. Use CashService.get_deployable_capital.
    2. Call optimizer/scanner to generate candidate trades.
    3. For each candidate, call sizing_engine.calculate_sizing.
    4. Insert trade_suggestions with window='midday_entry' and sizing_metadata.
    """
    print(f"Running midday cycle for user {user_id}")
    analytics_service = AnalyticsService(supabase)
    print("\n=== MIDDAY DEBUG ===")

    cash_service = CashService(supabase)
    deployable_capital = await cash_service.get_deployable_capital(user_id)
    print(f"Deployable capital: {deployable_capital}")

    if deployable_capital < 100:
        print("Insufficient capital to scan.")
        return

    # V3: Compute Global Regime Snapshot ONCE
    truth_layer = MarketDataTruthLayer()
    iv_repo = IVRepository(supabase)
    iv_point_service = IVPointService(supabase)

    regime_engine = RegimeEngineV3(
        supabase_client=supabase,
        market_data=truth_layer,
        iv_repository=iv_repo,
        iv_point_service=iv_point_service,
    )

    global_snap = regime_engine.compute_global_snapshot(datetime.now())
    # Try to persist global snapshot
    try:
        supabase.table("regime_snapshots").insert(global_snap.to_dict()).execute()
    except Exception:
        pass

    # 2. Call Scanner (market-wide)
    candidates = []
    scout_results = []

    try:
        # Step C: Wire user_id from cycle orchestration into scanner
        scout_results = scan_for_opportunities(supabase_client=supabase, user_id=user_id)

        print(f"Scanner returned {len(scout_results)} raw opportunities.")

        for c in scout_results:
            c["window"] = "midday_entry"

        conviction_service = ConvictionService(supabase=supabase)
        scout_results = conviction_service.adjust_suggestion_scores(scout_results, user_id)

        scout_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        candidates = scout_results[:2]

        print(f"Top {len(candidates)} scanner results for midday (top 2 by score):")
        for c in candidates:
            print(f"  {c.get('ticker', c.get('symbol'))} score={c.get('score')} type={c.get('type')}")

        if not candidates:
            print("No candidates selected for midday entries.")
            return

    except Exception as e:
        print(f"Scanner failed: {e}")
        return

    suggestions = []

    # 3. Size and Prepare Suggestions
    for cand in candidates:
        ticker = cand.get("ticker") or cand.get("symbol")
        strategy = cand.get("strategy") or cand.get("type") or "unknown"

        # V3: Compute Symbol Snapshot
        sym_snap = regime_engine.compute_symbol_snapshot(ticker, global_snap)
        effective_regime = regime_engine.get_effective_regime(sym_snap, global_snap)
        effective_regime_str = effective_regime.value
        scoring_regime = regime_engine.map_to_scoring_regime(effective_regime)

        # Extract pricing info. structure of candidate varies, assuming basic keys
        price = float(cand.get("suggested_entry", 0))
        ev = float(cand.get("ev", 0))

        if price <= 0:
            continue

        sizing = calculate_sizing(
            account_buying_power=deployable_capital,
            ev_per_contract=ev,
            contract_ask=price,
            max_risk_pct=0.40,
            profile="AGGRESSIVE",
        )

        print(
            f"[Midday] {ticker} sizing: contracts={sizing.get('contracts')}, "
            f"max_risk_exceeded={sizing.get('max_risk_exceeded', False)}, "
            f"risk_pct={0.40}, "
            f"ev_per_contract={ev}, "
            f"reason={sizing.get('reason')}"
        )

        is_max_risk = sizing.get("max_risk_exceeded", False)
        if MIDDAY_TEST_MODE and sizing["contracts"] <= 0 and not is_max_risk:
             sizing["contracts"] = 1
             sizing["reason"] = (sizing.get("reason", "") or "") + " | dev_override=1_contract"

        if sizing["contracts"] > 0:
            if "context" not in sizing:
                sizing["context"] = {
                    "iv_rank": cand.get("iv_rank"),
                    "iv_regime": scoring_regime,
                    "global_state": global_snap.state.value,
                    "regime_v3_global": global_snap.state.value,
                    "regime_v3_symbol": sym_snap.state.value,
                    "regime_v3_effective": effective_regime_str
                }
            else:
                # Update existing context
                sizing["context"].update({
                    "regime_v3_global": global_snap.state.value,
                    "regime_v3_symbol": sym_snap.state.value,
                    "regime_v3_effective": effective_regime_str,
                    "iv_regime": scoring_regime # ensure consistency
                })

            cand_features = {
                "ticker": ticker,
                "strategy": strategy,
                "ev": ev,
                "price": price,
                "score": cand.get("score"),
                "iv_rank": cand.get("iv_rank"),
                "sizing": sizing,
                "regime": effective_regime_str
            }

            ctx = TradeContext.create_new(
                model_version=APP_VERSION,
                window="midday_entry",
                strategy=strategy,
                regime=effective_regime_str
            )
            ctx.features_hash = compute_features_hash(cand_features)

            suggestion = {
                "user_id": user_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "valid_until": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
                "window": "midday_entry",
                "ticker": ticker,
                "strategy": strategy,
                "direction": "long",
                "order_json": {
                    "side": "buy",
                    "limit_price": price,
                    "contracts": sizing["contracts"]
                },
                "sizing_metadata": sizing,
                "status": "pending",
                "source": "scanner",
                "ev": ev,
                "internal_cand": cand,
                "trace_id": ctx.trace_id,
                "model_version": ctx.model_version,
                "features_hash": ctx.features_hash,
                "regime": ctx.regime
            }
            suggestions.append(suggestion)

            emit_trade_event(
                analytics_service,
                user_id,
                ctx,
                "suggestion_generated",
                properties={"ev": ev, "score": cand.get("score")}
            )

    print(f"FINAL MIDDAY SUGGESTION COUNT: {len(suggestions)}")

    if suggestions:
        try:
            supabase.table(TRADE_SUGGESTIONS_TABLE) \
                .delete() \
                .eq("user_id", user_id) \
                .eq("window", "midday_entry") \
                .execute()

            suggestions_to_insert = [{k: v for k, v in s.items() if k != 'internal_cand'} for s in suggestions]

            supabase.table(TRADE_SUGGESTIONS_TABLE).insert(suggestions_to_insert).execute()
            print(f"Inserted {len(suggestions)} midday suggestions.")
        except Exception as e:
            print(f"Error inserting midday suggestions: {e}")

        try:
            logs = []
            for s in suggestions:
                cand = s.get("internal_cand", {})
                regime_ctx = {
                    "iv_rank": cand.get("iv_rank"),
                    "trend": cand.get("trend"),
                    "score": cand.get("score"),
                    "global_state": global_snap.state.value,
                    "effective_regime": s.get("regime")
                }

                logs.append({
                    "user_id": user_id,
                    "created_at": s["created_at"],
                    "regime_context": regime_ctx,
                    "symbol": s["ticker"],
                    "strategy_type": s["strategy"],
                    "direction": s["direction"],
                    "target_price": s["order_json"]["limit_price"],
                    "confidence_score": cand.get("score", 0),
                })

            if logs:
                supabase.table(SUGGESTION_LOGS_TABLE).insert(logs).execute()
                print(f"Logged {len(logs)} midday suggestions to ledger.")
        except Exception as e:
            print(f"Error logging midday suggestions: {e}")


async def run_weekly_report(supabase: Client, user_id: str):
    """
    1. Use JournalService to aggregate stats for the current week.
    2. Write weekly_trade_reports row with metrics + report_markdown stub.
    """
    print(f"Running weekly report for user {user_id}")

    journal_service = JournalService(supabase)

    try:
        stats = journal_service.get_journal_stats(user_id)
        metrics = stats.get("stats", {})
    except Exception as e:
        print(f"Error fetching journal stats: {e}")
        metrics = {}

    win_rate_pct = metrics.get("win_rate", 0)
    # Normalize to ratio (0.0 - 1.0) if it looks like a percent (>1.0)
    win_rate_ratio = (win_rate_pct / 100.0) if win_rate_pct > 1.0 else win_rate_pct

    total_pnl = metrics.get("total_pnl", 0)
    trade_count = metrics.get("trade_count", 0)

    report_md = f"""
# Weekly Trading Report

**Week Ending:** {datetime.now().strftime('%Y-%m-%d')}

## Performance Summary
- **P&L:** ${total_pnl:.2f}
- **Win Rate:** {win_rate_pct:.1f}%
- **Trades:** {trade_count}

## AI Insights
*Generated based on your trading history...*
(Placeholder for deeper AI analysis)
    """

    # --- ADAPTIVE CAPS: LossMinimizer Feedback Loop ---
    # Fetch recent trades to analyze losses
    recent_losses_summary = {}
    try:
        # We need a summary of recent losses. JournalService stats usually aggregated.
        # Let's try to get raw trades if possible or use stats.
        # For simplicity in this scope, we infer from stats or assume we'd query recent losing trades.
        # Since I cannot easily change JournalService, I will pass the aggregated stats and current regime.
        # Ideally, LossMinimizer would query the DB itself or we'd pass a list of recent executions.

        # Determine global regime for context
        truth_layer = MarketDataTruthLayer()
        iv_repo = IVRepository(supabase)
        iv_point_service = IVPointService(supabase)

        regime_engine = RegimeEngineV3(
            supabase_client=supabase,
            market_data=truth_layer,
            iv_repository=iv_repo,
            iv_point_service=iv_point_service,
        )
        global_snap = regime_engine.compute_global_snapshot(datetime.now())
        current_regime_str = global_snap.state.value

        # Placeholder: In a real implementation, query 'trade_executions' or 'outcomes_log' for last N losses.
        # Here we pass minimal info to satisfy the contract.
        recent_losses_summary = {
            "regime": current_regime_str,
            "win_rate": win_rate_ratio,
            "win_rate_pct": win_rate_pct,
            "total_pnl": total_pnl
        }

        policy = LossMinimizer.generate_guardrail_policy(user_id, recent_losses_summary)

        # Persist Policy to Learning Loop
        if policy:
            policy_details = {
                "policy_version": "v1",
                "regime_state": str(current_regime_str),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "loss_minimizer",
                "policy": policy,
                "inputs": {
                    "lookback_days": 7,
                    "loss_summary": recent_losses_summary,
                },
            }

            try:
                supabase.table("learning_feedback_loops").insert({
                    "user_id": user_id,
                    "outcome_type": "guardrail_policy",
                    "details_json": policy_details,
                }).execute()
                print("Persisted adaptive guardrail policy.")
            except Exception as ex:
                print(f"Failed to persist guardrail policy: {ex}")

    except Exception as e:
        print(f"Adaptive Caps Error: {e}")

    report_data = {
        "user_id": user_id,
        "week_ending": datetime.now().strftime('%Y-%m-%d'),
        "total_pnl": total_pnl,
        "win_rate": win_rate_pct,
        "trade_count": trade_count,
        "missed_opportunities": [],
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
