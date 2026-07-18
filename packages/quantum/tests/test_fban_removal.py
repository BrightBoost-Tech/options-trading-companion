# packages/quantum/tests/test_fban_removal.py
"""F-BAN phantom-feature removal guards.

F-BAN was a per-strategy `banned_strategies` capability that LOOKED
configurable but had no real producer: a dead `settings.banned_strategies`
read that silently degraded to `[]`, threaded through StrategyPolicy into the
selector/scanner/design-agent, plus a redundant final gate — all permanently
fed `[]`. It was removed (owner decision F_BAN=REMOVE_PHANTOM_FEATURE).

These tests prove:
  1. no production code path any longer claims the feature exists;
  2. the selector entrypoints no longer accept the phantom parameter;
  3. the zero-ban decisions the selector actually made are UNCHANGED by the
     removal (decision-equivalence).

The DB column `settings.banned_strategies` (untracked schema drift, 0 rows)
is deliberately LEFT in place and documented in docs/backlog.md +
audit/ledger.md — it is NOT referenced by any code, so it does not appear in
the production tree scanned below.
"""
import inspect
import os

import pytest

from packages.quantum.analytics.strategy_selector import StrategySelector


# ---------------------------------------------------------------------------
# 1. Structural: the phantom is gone from production code.
# ---------------------------------------------------------------------------

def test_strategy_policy_module_deleted():
    """The StrategyPolicy enforcement module had no real producer and was
    deleted. Importing it must fail."""
    with pytest.raises(ModuleNotFoundError):
        __import__("packages.quantum.analytics.strategy_policy")


# packages/quantum root (parent of this tests/ dir).
PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Production files permitted to mention the phantom identifier. Empty BY
# DESIGN: the ledgered drift-column note lives in docs/ + audit/ledger.md,
# outside the packages/quantum code tree. Add a path here (with a ledger
# reference) only if a real, end-to-end ban producer is reintroduced.
ALLOWLIST: set = set()

PHANTOM_TOKEN = "banned_" + "strategies"  # split so this guard file self-excludes


def _iter_production_py():
    for root, _dirs, files in os.walk(PKG_ROOT):
        parts = set(root.replace("\\", "/").split("/"))
        if "tests" in parts or "__pycache__" in parts:
            continue
        for fn in files:
            if fn.endswith(".py"):
                yield os.path.join(root, fn)


def test_no_banned_strategies_references_in_production():
    offenders = []
    for path in _iter_production_py():
        rel = os.path.relpath(path, PKG_ROOT).replace("\\", "/")
        if rel in ALLOWLIST:
            continue
        with open(path, encoding="utf-8") as f:
            if PHANTOM_TOKEN in f.read():
                offenders.append(rel)
    assert offenders == [], (
        "F-BAN phantom references resurfaced in production code: "
        f"{offenders}. Per-strategy bans were removed as a phantom feature; "
        "a real ban control must be built end-to-end per the decision packet "
        "(migration + write surface + loud typed read failure), never a dead "
        "read threaded through the selector."
    )


# ---------------------------------------------------------------------------
# 2. The selector entrypoints no longer accept the phantom parameter.
# ---------------------------------------------------------------------------

def test_selector_signatures_drop_banned_strategies():
    sel = StrategySelector()
    for fn in (sel.determine_strategy, sel.get_candidates):
        assert PHANTOM_TOKEN not in inspect.signature(fn).parameters

    with pytest.raises(TypeError):
        sel.determine_strategy(
            "SPY", "BULLISH", 400.0, 90.0,
            effective_regime="ELEVATED",
            **{PHANTOM_TOKEN: ["credit_spreads"]},
        )
    with pytest.raises(TypeError):
        sel.get_candidates(
            "SPY", "BULLISH", 400.0, 90.0,
            effective_regime="ELEVATED",
            **{PHANTOM_TOKEN: ["credit_spreads"]},
        )


# ---------------------------------------------------------------------------
# 3. Decision-equivalence: the zero-ban decisions are unchanged.
#    determine_strategy has no phase gate, so these are env-independent.
#    (get_candidates' zero-ban pools are pinned in
#    test_strategy_selector_get_candidates.py.)
# ---------------------------------------------------------------------------

DETERMINE_MATRIX = [
    ("BULLISH", 10.0, "normal", "LONG_CALL_DEBIT_SPREAD"),
    ("BULLISH", 40.0, "normal", "LONG_CALL_DEBIT_SPREAD"),
    ("BULLISH", 90.0, "ELEVATED", "SHORT_PUT_CREDIT_SPREAD"),
    ("BEARISH", 10.0, "normal", "LONG_PUT_DEBIT_SPREAD"),
    ("BEARISH", 40.0, "normal", "LONG_PUT_DEBIT_SPREAD"),
    ("BEARISH", 90.0, "ELEVATED", "SHORT_CALL_CREDIT_SPREAD"),
    ("NEUTRAL", 90.0, "ELEVATED", "IRON_CONDOR"),
    ("NEUTRAL", 10.0, "normal", "HOLD"),
    ("EARNINGS", 90.0, "ELEVATED", "IRON_CONDOR"),
    ("EARNINGS", 10.0, "normal", "HOLD"),
]


@pytest.mark.parametrize("sentiment,iv,regime,expected", DETERMINE_MATRIX)
def test_determine_strategy_zero_ban_decisions(sentiment, iv, regime, expected):
    sel = StrategySelector()
    res = sel.determine_strategy(
        "TEST", sentiment, 100.0, iv, effective_regime=regime
    )
    assert res["strategy"] == expected


def test_shock_regime_defaults_to_cash():
    sel = StrategySelector()
    res = sel.determine_strategy(
        "TEST", "BULLISH", 100.0, 50.0, effective_regime="SHOCK"
    )
    assert res["strategy"] == "CASH"
