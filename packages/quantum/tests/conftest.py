"""Suite-wide conftest for ``packages/quantum/tests``.

Root fix (Lane D) for the alpaca ``sys.modules`` stub-leak class: make the
REAL, installed ``alpaca-py`` package canonical in ``sys.modules`` BEFORE any
test module in this tree is collected (or install a complete stub when
``alpaca-py`` is genuinely absent). pytest imports this conftest before it
collects sibling test modules, so every module-level ``sys.modules.setdefault``
alpaca shim in the suite finds the canonical package already present and
no-ops — the collection-order dependency that produced order-dependent reds is
eliminated for every invocation mode (single file, subset, full directory,
shuffled order, subprocess).

This is intentionally NOT an autouse fixture: it runs once at conftest import
and only guarantees that a declared third-party dependency is canonical. It
does not patch, wrap, or reorder any production module, so it cannot mask a
legitimate production import-order bug.

See ``packages/quantum/tests/_alpaca_stub.py`` for the canonical provider.
"""

import os
import sys

# conftest is imported by pytest before collecting sibling test modules. Make
# the repo root importable so the shared helper resolves regardless of the
# configured pytest rootdir (mirrors the CI PYTHONPATH and the pattern used by
# the existing subprocess-isolation tests).
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from packages.quantum.tests._alpaca_stub import ensure_alpaca  # noqa: E402

# Bind the canonical alpaca package at collection time, before any test
# module's own import-time alpaca shim can run.
ensure_alpaca()
