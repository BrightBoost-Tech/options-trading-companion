"""Collection-order regression: test_capital_basis_consistency.py must leave
NO MagicMock residue in sys.modules after it is imported AND its tests run.

Guards the 2026-07-17 sys.modules poison class. The pre-fix
test_capital_basis_consistency.py assigned MagicMocks for ``supabase``,
``packages.quantum.check_version`` and ``packages.quantum.ops_endpoints`` into
sys.modules at MODULE level and never restored them, permanently shadowing the
REAL modules for every later-collected test in the same CI shard. Concretely,
test_entries_only_halt.py imports the real ``packages.quantum.ops_endpoints``;
the leaked MagicMock made ``logging.getLogger(<MagicMock>)`` raise
"A logger name must be a string" (4 spurious failures, green single-file / red
at full-suite collection order). Same fix + guard family as
test_weekly_report_win_rate.py and test_inbox_ranker_comprehensive.py.

This runs the target module's import + unittest suite in a CLEAN interpreter
and asserts none of the previously-shadowed keys is a MagicMock at TWO points:

  1. immediately after IMPORT, before the target's own tests run — this is the
     collection-order-critical window (pytest imports every test module during
     collection before running any test, so a stub still live here poisons
     every later-collected module). A module-scoped tearDownModule restore
     would leave residue HERE and is correctly rejected.
  2. after the target's tests RUN — defence in depth against a call-time
     re-leak.

Subprocess isolation makes the residue check immune to whatever the parent
pytest process already imported.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

# The three modules the target stubs. If any is still a MagicMock after the
# target's tests complete, restoration regressed and the poison is back.
SHADOWED_KEYS = (
    "supabase",
    "packages.quantum.check_version",
    "packages.quantum.ops_endpoints",
)

_TARGET_MODULE = "packages.quantum.tests.test_capital_basis_consistency"

# …/packages/quantum/tests/<this file>  ->  parents[3] is the repo root that
# holds the importable ``packages`` package.
_REPO_ROOT = Path(__file__).resolve().parents[3]

_PROBE = textwrap.dedent(
    f"""
    import sys, unittest
    from unittest.mock import MagicMock

    shadowed = {SHADOWED_KEYS!r}

    def _residue():
        return sorted(
            k for k in shadowed if isinstance(sys.modules.get(k), MagicMock)
        )

    # (1) IMPORT — the collection-time window. Residue here poisons every
    #     later-collected module, so it must already be clean.
    mod = __import__({_TARGET_MODULE!r}, fromlist=["*"])
    post_import = _residue()
    if post_import:
        print("RESIDUE_AFTER_IMPORT:" + ",".join(post_import))
        raise SystemExit(11)

    # (2) RUN the target's own tests, then re-check (call-time re-leak guard).
    result = unittest.TextTestRunner(verbosity=0).run(
        unittest.TestLoader().loadTestsFromModule(mod)
    )
    post_run = _residue()
    if post_run:
        print("RESIDUE_AFTER_RUN:" + ",".join(post_run))
        raise SystemExit(12)
    if not result.wasSuccessful():
        print("TARGET_TESTS_FAILED")
        raise SystemExit(13)
    print("CLEAN")
    raise SystemExit(0)
    """
)


def _run_probe() -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # Guarantee the repo root is importable regardless of how the outer
    # pytest run configured sys.path (there is no root conftest doing it).
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) + (os.pathsep + existing if existing else "")
    )
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def test_target_leaves_no_magicmock_residue():
    """Importing + running test_capital_basis_consistency.py must not leave a
    MagicMock behind in sys.modules for any module it stubs."""
    proc = _run_probe()
    assert proc.returncode == 0 and "CLEAN" in proc.stdout, (
        "test_capital_basis_consistency.py left MagicMock residue in "
        "sys.modules (or its own tests failed under isolation).\n"
        f"returncode={proc.returncode}\n"
        f"stdout:\n{proc.stdout}\n"
        f"stderr (tail):\n{proc.stderr[-2000:]}"
    )
