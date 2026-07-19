"""Regression harness for the fork/collection reliability class.

WHY THIS EXISTS
---------------
A recurring Windows-local failure class: `rq` cannot be imported on Windows
because `rq/scheduler.py` runs ``get_context('fork').Process`` at module import,
and the 'fork' start method does not exist on Windows (``ValueError: cannot
find context for 'fork'``). Every test module that transitively imports
``packages.quantum.jobs.rq_enqueue`` (``from rq import Queue``) therefore failed
to COLLECT locally — the known "nine-file fork class". A sibling class seeded
security-config env or the rq stub first, so several files only errored when
collected SOLO or FIRST — an ordering artifact that made the whole set a house
of cards (which file passes depended on alphabetical collection order).

The fix (stub-if-absent + os.environ.setdefault self-seeding) makes each file
SELF-SUFFICIENT: it collects in a fresh interpreter regardless of collection
order. This harness locks that in and additionally guards against a future,
subtler regression: a test module that leaks a ``unittest.mock`` object into
``sys.modules`` at import time. Such residue silently poisons ``import`` for
every later module in the same process (any attribute/submodule resolves to an
auto-created Mock), which is exactly how ordering-dependent collection failures
are born.

WHAT IT ASSERTS
---------------
For every previously-broken file, in an ISOLATED fresh subprocess:
  1. the module imports cleanly (== it collects — pytest collection is a module
     import); a fresh interpreter proves order-independence and self-sufficiency,
  2. after import, NO value in ``sys.modules`` is a ``unittest.mock`` object
     (the future-pollution catcher).

CI (Linux, real rq) exercises the identical code path: the in-file
``try: import rq`` succeeds there, so the stub never engages and the assertion
is byte-identical to production behavior. The stub only materializes where rq
genuinely cannot load (Windows).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

# packages/quantum/tests/<thisfile> -> parents[1] == packages/quantum,
# parents[3] == repo root. pytest (prepend import mode) puts the repo root on
# sys.path so ``packages.quantum.*`` resolves; ``python -m`` additionally puts
# the CWD (packages/quantum) on sys.path so bare top-level modules
# (run_signed_task, internal_tasks, ...) resolve. The subprocess must reproduce
# BOTH or the faithful import cannot run.
_QUANTUM_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[3]

# The full membership of the historical fork/collection + ordering class
# (windows-local-test-env memory: 9 fork + 3 ordering). Each is imported in
# isolation below; adding a newly-hardened file here extends the guard.
PREVIOUSLY_BROKEN_MODULES = [
    # --- the nine-file fork class ---
    "packages.quantum.tests.test_api_info_disclosure",
    "packages.quantum.tests.test_background_queue_routing",
    "packages.quantum.tests.test_drift_summary_endpoint",
    "packages.quantum.tests.test_historical_training_loop",
    "packages.quantum.tests.test_optimizer_explain_endpoint",
    "packages.quantum.tests.test_rq_job_timeouts",
    "packages.quantum.tests.test_scheduler_routes_match",
    "packages.quantum.tests.test_security_exception_leaks",
    "packages.quantum.tests.test_validation_option_mode",
    # --- the three ordering-interaction files (pass solo; guarded here so a
    #     future module-level env/sys.modules leak that breaks them is caught) ---
    "packages.quantum.tests.test_run_signed_task",
    "packages.quantum.tests.test_security_headers",
    "packages.quantum.tests.test_task_signing_v4",
]

# Child program: import the target, then scan sys.modules for any mock residue.
# NonCallableMock is the common base of Mock/MagicMock/NonCallableMock/
# NonCallableMagicMock, so this catches every mock variant. A failed import
# raises and the interpreter exits non-zero with a traceback on stderr.
_CHILD_PROGRAM = (
    "import importlib, sys\n"
    "import unittest.mock as _m\n"
    "importlib.import_module(sys.argv[1])\n"
    "residue = sorted(\n"
    "    name for name, mod in list(sys.modules.items())\n"
    "    if isinstance(mod, _m.NonCallableMock)\n"
    ")\n"
    "if residue:\n"
    "    sys.stderr.write('MAGICMOCK_RESIDUE ' + ' '.join(residue) + '\\n')\n"
    "    raise SystemExit(3)\n"
    "raise SystemExit(0)\n"
)


def _subprocess_env() -> dict:
    env = dict(os.environ)
    extra = os.pathsep.join([str(_REPO_ROOT), str(_QUANTUM_DIR)])
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = extra + (os.pathsep + existing if existing else "")
    # api.py prints an emoji banner at import; a captured subprocess pipe on
    # Windows defaults to cp1252 and would raise UnicodeEncodeError on it. Both
    # CI (Linux, utf-8) and pytest's own capture handle that print, so utf-8 io
    # here reproduces the real collection environment rather than a console
    # codec quirk unrelated to collectability.
    env["PYTHONIOENCODING"] = "utf-8"
    return env


@pytest.mark.parametrize("module_name", PREVIOUSLY_BROKEN_MODULES)
def test_previously_broken_file_imports_clean_in_isolation(module_name):
    """Each historically-uncollectable file imports in a fresh interpreter with
    zero mock residue in sys.modules — order-independent, pollution-free."""
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_PROGRAM, module_name],
        capture_output=True,
        text=True,
        # The child emits utf-8 (PYTHONIOENCODING above; api.py's emoji banner);
        # decode the pipe as utf-8 too, else subprocess's reader thread raises a
        # UnicodeDecodeError under Windows' cp1252 default.
        encoding="utf-8",
        errors="replace",
        env=_subprocess_env(),
        cwd=str(_QUANTUM_DIR),
        timeout=180,
    )

    if proc.returncode == 3:
        pytest.fail(
            f"{module_name} left unittest.mock residue in sys.modules after "
            f"import (the future-pollution class — a leaked mock poisons import "
            f"for every later module).\nstderr:\n{proc.stderr}"
        )
    assert proc.returncode == 0, (
        f"{module_name} failed to import in isolation (== collection failure).\n"
        f"returncode={proc.returncode}\n"
        f"stdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )
