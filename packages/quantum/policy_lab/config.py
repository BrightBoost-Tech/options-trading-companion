"""
Policy Lab configuration — defines risk/sizing/exit parameters per cohort.

Each cohort gets a PolicyConfig that controls how the shared opportunity
set is filtered, sized, and managed. The forecast stack (scoring, regime,
opportunity ranking) is shared; only the policy layer diverges.
"""

import os
from dataclasses import dataclass, asdict, field
from typing import Dict, Optional


@dataclass
class PolicyConfig:
    """Risk policy parameters for a single cohort."""

    # Sizing
    max_risk_pct_per_trade: float = 0.03
    risk_multiplier: float = 1.0
    sizing_method: str = "budget_proportional"  # fixed, budget_proportional, half_kelly
    budget_cap_pct: float = 0.35  # % of deployable capital

    # Entry filtering
    max_suggestions_per_day: int = 3
    min_score_threshold: float = 60.0
    max_positions_open: int = 10

    # Exit conditions
    stop_loss_pct: float = 2.0       # multiplier of max_credit (2.0 = -200%)
    target_profit_pct: float = 0.50  # fraction of max_credit (0.50 = 50%)
    max_dte_to_enter: int = 60
    min_dte_to_exit: int = 7         # close when DTE <= this

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PolicyConfig":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


# ── Default cohort configs ────────────────────────────────────────────

# Small-account defaults ($500 baseline).
# Tighter targets for faster capital rotation.
# stop_loss_pct: fraction of entry cost (0.15 = -15%)
# target_profit_pct: fraction of entry cost (0.25 = +25%)

CONSERVATIVE = PolicyConfig(
    max_risk_pct_per_trade=0.015,
    risk_multiplier=0.8,
    sizing_method="budget_proportional",
    budget_cap_pct=0.25,
    max_suggestions_per_day=2,
    min_score_threshold=70.0,
    max_positions_open=2,
    stop_loss_pct=0.15,
    target_profit_pct=0.25,
    max_dte_to_enter=45,
    min_dte_to_exit=14,
)

NEUTRAL = PolicyConfig(
    max_risk_pct_per_trade=0.025,
    risk_multiplier=1.0,
    sizing_method="budget_proportional",
    budget_cap_pct=0.30,
    max_suggestions_per_day=3,
    min_score_threshold=50.0,
    max_positions_open=3,
    stop_loss_pct=0.20,
    target_profit_pct=0.35,
    max_dte_to_enter=45,
    min_dte_to_exit=10,
)

AGGRESSIVE = PolicyConfig(
    max_risk_pct_per_trade=0.035,
    risk_multiplier=1.2,
    sizing_method="budget_proportional",
    budget_cap_pct=0.35,
    max_suggestions_per_day=4,
    min_score_threshold=30.0,
    max_positions_open=4,
    stop_loss_pct=0.30,
    target_profit_pct=0.50,
    max_dte_to_enter=45,
    min_dte_to_exit=7,
)

DEFAULT_CONFIGS: Dict[str, PolicyConfig] = {
    "conservative": CONSERVATIVE,
    "neutral": NEUTRAL,
    "aggressive": AGGRESSIVE,
}


def get_policy_config(cohort_name: str) -> PolicyConfig:
    """Get default PolicyConfig by cohort name."""
    return DEFAULT_CONFIGS.get(cohort_name, NEUTRAL)


def load_cohort_configs(user_id: str, supabase) -> Dict[str, PolicyConfig]:
    """
    Load active cohort configs from DB with fallback to defaults.

    Returns dict mapping cohort_name → PolicyConfig.
    """
    try:
        result = supabase.table("policy_lab_cohorts") \
            .select("cohort_name, policy_config") \
            .eq("user_id", user_id) \
            .eq("is_active", True) \
            .execute()

        configs = {}
        for row in result.data or []:
            name = row["cohort_name"]
            db_config = row.get("policy_config") or {}
            base = get_policy_config(name)
            # Merge DB overrides onto defaults
            merged = base.to_dict()
            merged.update({k: v for k, v in db_config.items() if k in merged})
            configs[name] = PolicyConfig.from_dict(merged)
        return configs if configs else DEFAULT_CONFIGS.copy()
    except Exception:
        return DEFAULT_CONFIGS.copy()


def is_policy_lab_enabled() -> bool:
    """Check if Policy Lab is enabled via feature flag."""
    return os.environ.get("POLICY_LAB_ENABLED", "").lower() in ("1", "true")
