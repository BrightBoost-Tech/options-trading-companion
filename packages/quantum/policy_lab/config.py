"""
Policy Lab configuration — defines risk/sizing/exit parameters per cohort.

Each cohort gets a PolicyConfig that controls how the shared opportunity
set is filtered, sized, and managed. The forecast stack (scoring, regime,
opportunity ranking) is shared; only the policy layer diverges.
"""

import logging
import os
from dataclasses import dataclass, asdict, field, replace
from typing import Dict, Optional

logger = logging.getLogger(__name__)


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
    stop_loss_pct=0.40,
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
    stop_loss_pct=0.50,
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
    stop_loss_pct=0.65,
    target_profit_pct=0.50,
    max_dte_to_enter=45,
    min_dte_to_exit=7,
)

DEFAULT_CONFIGS: Dict[str, PolicyConfig] = {
    "conservative": CONSERVATIVE,
    "neutral": NEUTRAL,
    "aggressive": AGGRESSIVE,
}


# ── Fail-SAFE fallback for a LOAD FAULT (NOT an empty seed) ───────────
# DEFAULT_CONFIGS is the legitimate *empty-seed* baseline (first boot, no
# cohort rows yet). It is NOT a safe fallback for a DB/load FAULT: its stops
# are LOOSER than the live champion's (aggressive 0.65 vs live ~0.30), so
# returning it on a fault SILENTLY WIDENS the live stop — a fail-OPEN that
# weakens loss protection with zero signal. On a fault we instead fail SAFE:
# prefer the last-known-good configs cached from the most recent successful
# load (live-tight); if none exists yet, use TIGHT_FALLBACK, whose stops are
# clamped <= the live champion (0.30) so they can only be tighter — never
# looser — than what is actually running.
_TIGHT_STOP_CEILING = 0.30  # never looser than the live champion's stop

TIGHT_FALLBACK: Dict[str, PolicyConfig] = {
    name: replace(cfg, stop_loss_pct=min(cfg.stop_loss_pct, _TIGHT_STOP_CEILING))
    for name, cfg in DEFAULT_CONFIGS.items()
}

# Last-known-good cache: populated on every SUCCESSFUL non-empty load so a
# later fault can fail back to live-tight values instead of loose defaults.
_LAST_KNOWN_GOOD: Optional[Dict[str, PolicyConfig]] = None


def get_policy_config(cohort_name: str) -> PolicyConfig:
    """Get default PolicyConfig by cohort name."""
    return DEFAULT_CONFIGS.get(cohort_name, NEUTRAL)


def load_cohort_configs(user_id: str, supabase) -> Dict[str, PolicyConfig]:
    """
    Load active cohort configs from DB.

    Returns dict mapping cohort_name → PolicyConfig.

    Fail-OPEN fix (loss-protection): a load FAULT must be distinguished from a
    legitimate empty seed. Both used to return the LOOSE DEFAULT_CONFIGS, so a
    DB/load exception silently widened the live champion's stop (0.65 vs the
    live ~0.30) with zero signal.
      • Query SUCCEEDS, rows present  → live configs; cache as last-known-good.
      • Query SUCCEEDS, zero rows     → legitimate empty seed → DEFAULT_CONFIGS
        (preserves first-boot semantics; NOT a fault, no fault log).
      • Exception during load (FAULT) → fail SAFE: last-known-good cache if we
        have one, else TIGHT_FALLBACK — NEVER the loose DEFAULT_CONFIGS — and
        log LOUDLY ([CONFIG_FAULT]).
    """
    global _LAST_KNOWN_GOOD
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
        if configs:
            # Successful, non-empty load → live-tight values. Cache for the
            # fault fail-safe (store a copy so callers can't mutate the cache).
            _LAST_KNOWN_GOOD = dict(configs)
            return configs
        # Successful but EMPTY → legitimate empty seed (first boot). Preserve
        # the baseline; do NOT poison the cache with loose defaults.
        return DEFAULT_CONFIGS.copy()
    except Exception:
        # LOAD FAULT — must NOT fail OPEN to the loose DEFAULT_CONFIGS (that
        # would silently widen the live champion's stop). Fail SAFE to the
        # last-known-good cache (live-tight) or, absent one, TIGHT_FALLBACK.
        fallback = dict(_LAST_KNOWN_GOOD) if _LAST_KNOWN_GOOD else TIGHT_FALLBACK.copy()
        source = "last-known-good cache" if _LAST_KNOWN_GOOD else "TIGHT_FALLBACK"
        logger.exception(
            "[CONFIG_FAULT] load_cohort_configs failed for user_id=%s — failing "
            "SAFE to %s (tight stops, never the loose DEFAULT_CONFIGS); "
            "aggressive stop_loss_pct=%s",
            user_id, source,
            getattr(fallback.get("aggressive"), "stop_loss_pct", None),
        )
        return fallback


def is_policy_lab_enabled() -> bool:
    """Check if Policy Lab is enabled via feature flag."""
    return os.environ.get("POLICY_LAB_ENABLED", "").lower() in ("1", "true")
