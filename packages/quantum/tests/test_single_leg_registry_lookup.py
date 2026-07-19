"""Versioned-registry opt-in lookup for the single-leg experiment (item 3).

The opt-in is read from the RAW ``policy_registrations.policy_config`` jsonb —
NOT through PolicyConfig (whose ``from_dict`` keeps only its 11 dataclass fields
and would DROP the ``single_leg_experiment_enabled`` key). These tests drive the
real helper + the generator entrypoint with a fake supabase returning:
  * a SYNTHETIC row carrying the opt-in -> enabled (and a candidate is produced)
  * the REAL 50-policy shape (11 keys, no opt-in) -> disabled (dark)
  * a missing row / a read fault -> disabled (fail-closed to dark)
and prove PolicyConfig.from_dict drops the key (why the raw read is required).
"""

from packages.quantum.brokers.execution_router import SHADOW_ONLY_ROUTING
from packages.quantum.policy_lab.config import PolicyConfig
from packages.quantum.strategies import single_leg_experiment as sl
from packages.quantum.tests.test_single_leg_experiment_generation import (
    passing_context,
    real_estimator,
)

# The real approved small_tier_v1 config shape (11 PolicyConfig keys, verified via
# MCP: 0/50 carry the opt-in key).
REAL_50_SHAPE = {
    "max_risk_pct_per_trade": 0.035, "risk_multiplier": 1.0,
    "sizing_method": "budget_proportional", "budget_cap_pct": 0.25,
    "max_suggestions_per_day": 4, "min_score_threshold": 30.0,
    "max_positions_open": 4, "stop_loss_pct": 0.30, "target_profit_pct": 0.50,
    "max_dte_to_enter": 45, "min_dte_to_exit": 7,
}


class _FakeRegistry:
    """supabase stub: any .table(...).select(...).eq(...).[eq(...)].limit(...)
    .execute() returns the configured registry row(s). ``raise_on_read`` simulates
    a read fault; ``rows=None`` simulates a missing row."""

    def __init__(self, policy_config=None, rows=None, raise_on_read=False):
        if rows is not None:
            self._rows = rows
        elif policy_config is None:
            self._rows = []
        else:
            self._rows = [{"policy_config": policy_config}]
        self._raise = raise_on_read

    def table(self, *_a, **_k):
        return self

    select = eq = limit = order = lambda self, *_a, **_k: self

    def execute(self):
        if self._raise:
            raise RuntimeError("registry read blew up")
        return type("R", (), {"data": self._rows})()


# ── load_policy_registration_config: RAW jsonb, fail-closed ───────────────────

def test_load_returns_raw_config_including_optin_key():
    cfg = sl.load_policy_registration_config(
        _FakeRegistry({"single_leg_experiment_enabled": True, "foo": 1}), "pid")
    assert cfg == {"single_leg_experiment_enabled": True, "foo": 1}


def test_load_missing_row_returns_none():
    assert sl.load_policy_registration_config(_FakeRegistry(rows=[]), "pid") is None


def test_load_read_fault_returns_none_fail_closed():
    assert sl.load_policy_registration_config(_FakeRegistry(raise_on_read=True), "pid") is None


def test_load_null_config_returns_none():
    assert sl.load_policy_registration_config(_FakeRegistry(rows=[{"policy_config": None}]), "pid") is None


# ── experiment_enabled_for_registration ───────────────────────────────────────

def test_enabled_for_synthetic_optin_row():
    reg = _FakeRegistry({"single_leg_experiment_enabled": True})
    assert sl.experiment_enabled_for_registration(reg, "pid") is True


def test_disabled_for_real_50_shape():
    # The REAL approved shape has NO opt-in key -> experiment stays dark.
    assert sl.experiment_enabled_for_registration(_FakeRegistry(REAL_50_SHAPE), "pid") is False


def test_disabled_for_missing_and_faulted_registry():
    assert sl.experiment_enabled_for_registration(_FakeRegistry(rows=[]), "pid") is False
    assert sl.experiment_enabled_for_registration(_FakeRegistry(raise_on_read=True), "pid") is False


# ── from_dict DROPS the opt-in key (why the raw read is mandatory) ─────────────

def test_policyconfig_from_dict_drops_optin_key():
    pc = PolicyConfig.from_dict({**REAL_50_SHAPE, "single_leg_experiment_enabled": True})
    assert not hasattr(pc, "single_leg_experiment_enabled")
    assert "single_leg_experiment_enabled" not in pc.to_dict()


# ── Route-driven: generator resolves opt-in from the registry ─────────────────

def test_generator_enabled_via_synthetic_registry_row_produces_candidate():
    reg = _FakeRegistry({"single_leg_experiment_enabled": True})
    res = sl.generate_single_leg_candidates(
        [passing_context()], routing_mode=SHADOW_ONLY_ROUTING,
        ev_estimator=real_estimator, policy_registration_id="pid", supabase=reg,
    )
    assert res.enabled is True
    assert len(res.candidates) == 1 and res.candidates[0].strategy_type == "long_call"


def test_generator_dark_for_real_50_shape_registry_row():
    reg = _FakeRegistry(REAL_50_SHAPE)
    res = sl.generate_single_leg_candidates(
        [passing_context()], routing_mode=SHADOW_ONLY_ROUTING,
        ev_estimator=real_estimator, policy_registration_id="pid", supabase=reg,
    )
    assert res.enabled is False and res.candidates == [] and res.rejections == []


def test_generator_dark_when_registry_row_missing():
    res = sl.generate_single_leg_candidates(
        [passing_context()], routing_mode=SHADOW_ONLY_ROUTING,
        ev_estimator=real_estimator, policy_registration_id="pid",
        supabase=_FakeRegistry(rows=[]),
    )
    assert res.enabled is False
