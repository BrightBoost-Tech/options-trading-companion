"""Order-matrix regression harness for the alpaca ``sys.modules`` stub-leak
class (Lane D).

WHAT THIS GUARDS
----------------
~70 test modules used to install an ad-hoc alpaca stub into ``sys.modules`` at
import time via ``sys.modules.setdefault`` with NO teardown and inconsistent
attribute coverage. Because ``setdefault`` only writes when the key is absent,
the FIRST module collected won and its (often bare) stub shadowed the real,
installed ``alpaca-py`` for the whole interpreter. A later victim doing
``from alpaca.trading.requests import GetPortfolioHistoryRequest`` then passed
or failed purely on COLLECTION ORDER (the PR #1362 red). The root fix is
``packages/quantum/tests/_alpaca_stub.ensure_alpaca`` (invoked from the suite
conftest) which binds the REAL package — or a complete stub when alpaca-py is
genuinely absent — before any test module runs.

This harness proves the fix generalises and cannot silently regress:

  * a STATIC guard fails if any test module reintroduces the leaking pattern
    (module-level ``sys.modules.setdefault``/assignment of an alpaca module);
  * SUBPROCESS order matrices (fresh interpreters) prove every relevant order
    is green and identical — polluter→victim, victim→polluter, two→victim,
    a representative collection, randomized orders, and the same module twice;
  * DIRECT probes prove ``ensure_alpaca`` evicts a shadowing stub and binds the
    real package, that the isolation context manager cleans up after an
    injected exception, and that importing many ex-polluters leaves the real
    ``alpaca`` canonical (no stub / MagicMock residue) in ``sys.modules``.

The known QUANT_AGENTS parser seam (``workflow_orchestrator`` sizing) and the
prior capital-basis MagicMock-leak isolation guard are included so the proof
spans pollution classes.
"""

import ast
import os
import random
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# …/packages/quantum/tests/<this file> -> parents[3] is the repo root that
# holds the importable ``packages`` package.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_TESTS_DIR = Path(__file__).resolve().parent

# ── representative modules across the leak/victim/functional-stub classes ──
VICTIM = "packages/quantum/tests/test_alpaca_authoritative_equity.py"
POLLUTER_A = "packages/quantum/tests/test_reentry_cooldown.py"      # ex bare stub
POLLUTER_B = "packages/quantum/tests/test_stage_time_greeks.py"     # ex loop stub
WORKFLOW_QUANT_AGENTS = (
    "packages/quantum/tests/test_workflow_orchestrator_ranker_positions.py"
)
FUNCTIONAL_STUB = "packages/quantum/tests/test_submit_option_order_credit_seam.py"
PRIOR_ISO_GUARD = "packages/quantum/tests/test_capital_basis_sysmodules_isolation.py"

REPRESENTATIVE = [
    VICTIM,
    POLLUTER_A,
    POLLUTER_B,
    WORKFLOW_QUANT_AGENTS,
    FUNCTIONAL_STUB,
    "packages/quantum/tests/test_equity_state_helpers.py",
    "packages/quantum/tests/test_entries_only_halt.py",
    "packages/quantum/tests/test_cost_basis_model.py",
]

# The sys.modules keys that must never carry a leaked stub after any run.
_ALPACA_KEYS = (
    "alpaca",
    "alpaca.trading",
    "alpaca.trading.requests",
    "alpaca.trading.enums",
)


def _env():
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_REPO_ROOT) + (
        os.pathsep + existing if existing else ""
    )
    return env


def _run_pytest(order):
    """Run pytest on the given file order in a FRESH interpreter."""
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", *order,
            "-p", "no:cacheprovider", "-q", "-o", "addopts=",
        ],
        cwd=str(_REPO_ROOT),
        env=_env(),
        capture_output=True,
        text=True,
    )
    return proc


def _assert_green(proc, order):
    assert proc.returncode == 0, (
        "collection/order-dependent failure for order:\n  "
        + " ".join(order)
        + f"\nreturncode={proc.returncode}\n"
        f"stdout (tail):\n{proc.stdout[-3000:]}\n"
        f"stderr (tail):\n{proc.stderr[-1500:]}"
    )
    # No collection errors and at least one test ran.
    assert "error" not in proc.stdout.lower().split("=== warnings")[0] or \
        "passed" in proc.stdout, proc.stdout[-2000:]


def _run_probe(body):
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        cwd=str(_REPO_ROOT),
        env=_env(),
        capture_output=True,
        text=True,
    )
    return proc


# ── (1) STATIC anti-pattern guard: catches reintroduction directly ──


def test_no_module_level_alpaca_sysmodules_stub_reintroduced():
    """No test module may install an alpaca module into ``sys.modules`` at
    module (import) level via ``setdefault``/assignment — the leaking pattern.
    Behavioural stubs must be scoped+restored (``patch.dict`` /
    ``alpaca_modules_isolated``); import resolution goes through
    ``ensure_alpaca``."""

    def _is_alpaca_key(node):
        return (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and (node.value == "alpaca" or node.value.startswith("alpaca.")))

    def _is_alpaca_sysmodules_write(node):
        # sys.modules["alpaca..."] = ...   OR   sys.modules.setdefault(<alpaca>, ...)
        # Scoped to the alpaca class (this lane); the adjacent MagicMock module
        # leaks (supabase/market_data/dotenv) are tracked separately.
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Subscript)
                        and isinstance(t.value, ast.Attribute)
                        and t.value.attr == "modules"
                        and isinstance(t.value.value, ast.Name)
                        and t.value.value.id == "sys"
                        and _is_alpaca_key(getattr(t, "slice", None))):
                    return True
        call = node.value if isinstance(node, (ast.Expr, ast.Assign)) else None
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                and call.func.attr == "setdefault" \
                and isinstance(call.func.value, ast.Attribute) \
                and call.func.value.attr == "modules" \
                and isinstance(call.func.value.value, ast.Name) \
                and call.func.value.value.id == "sys" and call.args:
            a0 = call.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                return a0.value == "alpaca" or a0.value.startswith("alpaca.")
            if isinstance(a0, ast.Name):  # `for _m in (...): setdefault(_m, ...)`
                return True
        return False

    offenders = []
    for path in sorted(_TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Only MODULE-LEVEL statements leak past collection; a scoped patch.dict
        # inside a function is fine.
        for node in tree.body:
            targets = [node]
            if isinstance(node, ast.For):
                targets += list(node.body)
            for t in targets:
                if _is_alpaca_sysmodules_write(t):
                    offenders.append(path.name)
                    break
    assert not offenders, (
        "module-level alpaca sys.modules stub reintroduced (leaks past "
        "collection order). Route import resolution through "
        "packages.quantum.tests._alpaca_stub.ensure_alpaca, and scope any "
        "behavioural stub with patch.dict / alpaca_modules_isolated:\n  "
        + "\n  ".join(sorted(set(offenders)))
    )


# ── (2) SUBPROCESS order matrices ──


def test_polluter_then_victim_green():
    _assert_green(_run_pytest([POLLUTER_A, VICTIM]), [POLLUTER_A, VICTIM])


def test_victim_then_polluter_green():
    _assert_green(_run_pytest([VICTIM, POLLUTER_A]), [VICTIM, POLLUTER_A])


def test_two_polluters_then_victim_green():
    order = [POLLUTER_A, POLLUTER_B, VICTIM]
    _assert_green(_run_pytest(order), order)


def test_quant_agents_seam_after_polluter_green():
    """The PR #1362 seam: a bare-stub polluter collected before the
    workflow_orchestrator QUANT_AGENTS sizing test must not break it."""
    order = [POLLUTER_A, WORKFLOW_QUANT_AGENTS, VICTIM]
    _assert_green(_run_pytest(order), order)


def test_functional_stub_interleaved_with_victim_and_prior_guard_green():
    """The recording functional stub (restore-safe patch.dict) interleaved
    with the victim and the prior-class isolation guard stays green — proving
    cross-class non-interference."""
    order = [FUNCTIONAL_STUB, VICTIM, PRIOR_ISO_GUARD]
    _assert_green(_run_pytest(order), order)


def test_representative_collection_green():
    _assert_green(_run_pytest(REPRESENTATIVE), REPRESENTATIVE)


@pytest.mark.parametrize("seed", [1, 7, 42, 1362])
def test_randomized_orders_all_green(seed):
    order = list(REPRESENTATIVE)
    random.Random(seed).shuffle(order)
    _assert_green(_run_pytest(order), order)


def test_same_victim_module_twice_one_interpreter():
    """Import + run the victim's unittest suite TWICE in one interpreter
    (reload between) — both green, proving no first-run state poisons a
    second run."""
    body = f"""
        import importlib, unittest, sys
        from packages.quantum.tests._alpaca_stub import ensure_alpaca
        ensure_alpaca()
        modname = "packages.quantum.tests.test_alpaca_authoritative_equity"
        for i in range(2):
            mod = importlib.import_module(modname)
            mod = importlib.reload(mod)
            res = unittest.TextTestRunner(verbosity=0).run(
                unittest.TestLoader().loadTestsFromModule(mod)
            )
            if not res.wasSuccessful():
                print("RUN_%d_FAILED" % i)
                raise SystemExit(20 + i)
        print("BOTH_RUNS_GREEN")
    """
    proc = _run_probe(body)
    assert proc.returncode == 0 and "BOTH_RUNS_GREEN" in proc.stdout, (
        f"rc={proc.returncode}\nstdout:\n{proc.stdout}\n"
        f"stderr (tail):\n{proc.stderr[-1500:]}"
    )


# ── (3) DIRECT helper probes ──


def test_ensure_alpaca_evicts_shadowing_stub_and_binds_real():
    """A bare shim already in sys.modules (a legacy polluter) is evicted by
    ensure_alpaca so the REAL package binds — the exact mechanism that ends
    the order dependency."""
    body = """
        import sys, types
        # Simulate a legacy bare-stub polluter winning the setdefault race.
        for name in ("alpaca", "alpaca.trading", "alpaca.trading.requests"):
            sys.modules.setdefault(name, types.ModuleType(name))
        # Pre-condition: the bare shim lacks the real symbol.
        try:
            from alpaca.trading.requests import GetPortfolioHistoryRequest  # noqa
            print("PRECONDITION_UNEXPECTED_SYMBOL")
            raise SystemExit(31)
        except ImportError:
            pass
        from packages.quantum.tests._alpaca_stub import ensure_alpaca
        assert ensure_alpaca() == "real", "expected the real package to bind"
        from alpaca.trading.requests import GetPortfolioHistoryRequest as G
        assert getattr(G, "__module__", None) == "alpaca.trading.requests"
        req = sys.modules["alpaca.trading.requests"]
        assert getattr(req, "__file__", None), "bound module must be real (has __file__)"
        print("EVICTED_AND_REAL")
    """
    proc = _run_probe(body)
    assert proc.returncode == 0 and "EVICTED_AND_REAL" in proc.stdout, (
        f"rc={proc.returncode}\nstdout:\n{proc.stdout}\n"
        f"stderr (tail):\n{proc.stderr[-1500:]}"
    )


def test_isolation_context_manager_restores_after_exception():
    body = """
        import sys, types
        from packages.quantum.tests._alpaca_stub import ensure_alpaca, alpaca_modules_isolated
        ensure_alpaca()
        before = {k: sys.modules[k] for k in list(sys.modules)
                  if k == "alpaca" or k.startswith("alpaca.")}
        real_req = sys.modules["alpaca.trading.requests"]
        try:
            with alpaca_modules_isolated():
                sys.modules["alpaca.trading.requests"] = types.ModuleType("alpaca.trading.requests")
                sys.modules["alpaca.injected.during.block"] = types.ModuleType("alpaca.injected.during.block")
                raise ValueError("boom")
        except ValueError:
            pass
        after = {k: sys.modules[k] for k in list(sys.modules)
                 if k == "alpaca" or k.startswith("alpaca.")}
        assert sys.modules["alpaca.trading.requests"] is real_req, "exact object not restored"
        assert "alpaca.injected.during.block" not in sys.modules, "added key not removed"
        assert set(before) == set(after), "keyset changed"
        print("RESTORED_AFTER_EXCEPTION")
    """
    proc = _run_probe(body)
    assert proc.returncode == 0 and "RESTORED_AFTER_EXCEPTION" in proc.stdout, (
        f"rc={proc.returncode}\nstdout:\n{proc.stdout}\n"
        f"stderr (tail):\n{proc.stderr[-1500:]}"
    )


def test_no_stub_or_magicmock_residue_after_importing_expolluters():
    """Importing a batch of ex-polluter modules (their module-level
    ensure_alpaca calls) must leave the REAL alpaca canonical — no leftover
    stub or MagicMock in the alpaca sys.modules keys."""
    modules = [
        "packages.quantum.tests.test_reentry_cooldown",
        "packages.quantum.tests.test_stage_time_greeks",
        "packages.quantum.tests.test_alpaca_authoritative_equity",
        "packages.quantum.tests.test_cost_basis_model",
        "packages.quantum.tests.test_entries_only_halt",
    ]
    body = f"""
        import sys
        from unittest.mock import MagicMock
        keys = {list(_ALPACA_KEYS)!r}
        for m in {modules!r}:
            __import__(m)
        bad = []
        for k in keys:
            mod = sys.modules.get(k)
            if mod is None:
                continue
            if isinstance(mod, MagicMock):
                bad.append(k + ":MagicMock")
            elif getattr(mod, "__otc_test_alpaca_stub__", False):
                bad.append(k + ":stub")
            elif not getattr(mod, "__file__", None):
                bad.append(k + ":no-__file__")
        if bad:
            print("RESIDUE:" + ",".join(bad))
            raise SystemExit(41)
        print("NO_RESIDUE_ALL_REAL")
    """
    proc = _run_probe(body)
    assert proc.returncode == 0 and "NO_RESIDUE_ALL_REAL" in proc.stdout, (
        f"rc={proc.returncode}\nstdout:\n{proc.stdout}\n"
        f"stderr (tail):\n{proc.stderr[-1500:]}"
    )


def test_complete_stub_fallback_when_alpaca_absent():
    """When alpaca-py is genuinely absent, ensure_alpaca installs a COMPLETE
    stub: every referenced submodule resolves and request models capture their
    kwargs (so a no-alpaca dev box is deterministic too)."""
    body = """
        import sys, importlib.abc
        class _Block(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if name == "alpaca" or name.startswith("alpaca."):
                    raise ModuleNotFoundError(name)
                return None
        sys.meta_path.insert(0, _Block())
        for k in [k for k in sys.modules if k == "alpaca" or k.startswith("alpaca.")]:
            del sys.modules[k]
        from packages.quantum.tests._alpaca_stub import ensure_alpaca
        assert ensure_alpaca() == "stub"
        from alpaca.trading.requests import GetPortfolioHistoryRequest as G
        r = G(period="1W", timeframe="1D")
        assert r.period == "1W" and r.timeframe == "1D"
        from alpaca.trading.enums import OrderSide           # noqa
        from alpaca.data.historical import StockHistoricalDataClient  # noqa
        assert getattr(sys.modules["alpaca"], "__otc_test_alpaca_stub__", False)
        print("STUB_FALLBACK_COMPLETE")
    """
    proc = _run_probe(body)
    assert proc.returncode == 0 and "STUB_FALLBACK_COMPLETE" in proc.stdout, (
        f"rc={proc.returncode}\nstdout:\n{proc.stdout}\n"
        f"stderr (tail):\n{proc.stderr[-1500:]}"
    )
