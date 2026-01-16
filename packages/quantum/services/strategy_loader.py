"""
Strategy Loader Service

Loads strategy configurations from the database by name, with fallback to defaults.
Used by suggestion generation tasks to apply user-specific or learned strategy configs.
"""

from typing import Optional, Dict, Any
from supabase import Client

from packages.quantum.strategy_profiles import StrategyConfig


# Default strategy configuration for spy_opt_autolearn_v6
DEFAULT_STRATEGY_CONFIG = {
    "name": "spy_opt_autolearn_v6",
    "version": 1,
    "description": "Baseline autolearn strategy for SPY options",
    "max_risk_pct_per_trade": 0.02,
    "max_risk_pct_portfolio": 0.10,
    "max_concurrent_positions": 5,
    "conviction_floor": 0.40,
    "conviction_slope": 0.5,
    "take_profit_pct": 0.10,
    "stop_loss_pct": 0.05,
    "max_holding_days": 14,
    "regime_whitelist": ["bull_quiet", "bull_volatile", "neutral"],
    "max_spread_bps": 150,
    "max_days_to_expiry": 60,
    "min_underlying_liquidity": 1_000_000,
}


def load_strategy_config(
    user_id: str,
    strategy_name: str,
    supabase: Client
) -> Dict[str, Any]:
    """
    Load the latest version of a strategy config by name for a user.

    Args:
        user_id: The user's UUID
        strategy_name: Name of the strategy (e.g., "spy_opt_autolearn_v6")
        supabase: Supabase client

    Returns:
        Dict containing strategy params, or default config if not found.
        Always includes 'name', 'version', and all strategy parameters.
    """
    try:
        result = supabase.table("strategy_configs") \
            .select("params, version, name") \
            .eq("user_id", user_id) \
            .eq("name", strategy_name) \
            .order("version", desc=True) \
            .limit(1) \
            .execute()

        if result.data and len(result.data) > 0:
            row = result.data[0]
            params = row.get("params", {})
            # Merge with defaults for any missing keys
            config = {**DEFAULT_STRATEGY_CONFIG, **params}
            config["name"] = row.get("name", strategy_name)
            config["version"] = row.get("version", 1)
            return config

    except Exception as e:
        print(f"[strategy_loader] Error loading config for {user_id}/{strategy_name}: {e}")

    # Return default config with provided name
    return {**DEFAULT_STRATEGY_CONFIG, "name": strategy_name}


def load_strategy_config_as_model(
    user_id: str,
    strategy_name: str,
    supabase: Client
) -> StrategyConfig:
    """
    Load strategy config and return as a validated StrategyConfig model.
    """
    config_dict = load_strategy_config(user_id, strategy_name, supabase)

    # Map dict keys to StrategyConfig fields
    return StrategyConfig(
        max_risk_pct_per_trade=config_dict.get("max_risk_pct_per_trade", 0.02),
        max_risk_pct_portfolio=config_dict.get("max_risk_pct_portfolio", 0.10),
        max_concurrent_positions=config_dict.get("max_concurrent_positions", 5),
        conviction_floor=config_dict.get("conviction_floor", 0.40),
        conviction_slope=config_dict.get("conviction_slope", 0.5),
        take_profit_pct=config_dict.get("take_profit_pct", 0.10),
        stop_loss_pct=config_dict.get("stop_loss_pct", 0.05),
        max_holding_days=config_dict.get("max_holding_days", 14),
        regime_whitelist=config_dict.get("regime_whitelist"),
        max_spread_bps=config_dict.get("max_spread_bps", 150),
        max_days_to_expiry=config_dict.get("max_days_to_expiry", 60),
        min_underlying_liquidity=config_dict.get("min_underlying_liquidity", 1_000_000),
    )


def ensure_default_strategy_exists(
    user_id: str,
    strategy_name: str,
    supabase: Client
) -> bool:
    """
    Ensure a default strategy config exists for the user.
    Creates one if it doesn't exist.

    Returns:
        True if config exists or was created, False on error.
    """
    try:
        # Check if exists
        result = supabase.table("strategy_configs") \
            .select("id") \
            .eq("user_id", user_id) \
            .eq("name", strategy_name) \
            .limit(1) \
            .execute()

        if result.data and len(result.data) > 0:
            return True

        # Create default
        config_data = {
            "user_id": user_id,
            "name": strategy_name,
            "version": 1,
            "description": DEFAULT_STRATEGY_CONFIG["description"],
            "params": DEFAULT_STRATEGY_CONFIG,
        }

        supabase.table("strategy_configs").insert(config_data).execute()
        print(f"[strategy_loader] Created default {strategy_name} config for user {user_id}")
        return True

    except Exception as e:
        print(f"[strategy_loader] Error ensuring config exists: {e}")
        return False
