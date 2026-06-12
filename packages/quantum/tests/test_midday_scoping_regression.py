"""Scoping regression guard for run_midday_cycle (2026-06-12 MARA cycle death).

Root cause: PR #958 (ea6bae8) left a function-local
``from ...supabase_config import get_admin_supabase as _get_admin_supabase``
inside run_midday_cycle's H9 allocator-mismatch branch. Python scoping is
compile-time: ANY binding of a name anywhere in a function makes that name
local to the WHOLE function, so every other ``_get_admin_supabase`` reference
in run_midday_cycle compiled to a local load of a variable that is only
assigned in a branch that never executes → UnboundLocalError.

Latent while all other references sat in rarely-fired except handlers.
N1 (#1058, 2ac071b) added the first mainline reference — the v5-A2
envelope feed ``tightened_daily_pnl(..., supabase=_get_admin_supabase())``
— and every midday cycle then died twice: once caught (the
"[RISK_ENVELOPE] Pre-entry check failed (non-fatal)" line), once fatally
when the except handler's own ``alert(_get_admin_supabase(), ...)`` re-raised.
Job ac2f0c08 (2026-06-12 16:00Z) selected MARA and produced no suggestion,
no round_trip_check, no FINAL MIDDAY SUGGESTION COUNT.

These tests compile the real module source with compile() — the same
compiler pass that decides local-vs-global — so this class of bug cannot
pass CI again regardless of which branch executes at runtime.
"""

import ast
import unittest
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).parent.parent / "services" / "workflow_orchestrator.py"
)


def _compile_module():
    src = _MODULE_PATH.read_text(encoding="utf-8")
    return src, compile(src, str(_MODULE_PATH), "exec")


def _find_code(code, name):
    """Depth-first search for a code object by co_name."""
    for const in code.co_consts:
        if hasattr(const, "co_name"):
            if const.co_name == name:
                return const
            found = _find_code(const, name)
            if found is not None:
                return found
    return None


def _module_level_import_names(tree):
    """Names bound by import statements at module top level."""
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


class TestRunMiddayCycleScopingCompiled(unittest.TestCase):
    """Pin the compiler's verdict: _get_admin_supabase resolves as a
    global in run_midday_cycle, never as a function-local."""

    @classmethod
    def setUpClass(cls):
        cls.src, cls.code = _compile_module()
        cls.midday = _find_code(cls.code, "run_midday_cycle")

    def test_run_midday_cycle_found(self):
        self.assertIsNotNone(
            self.midday, "run_midday_cycle code object not found"
        )

    def test_get_admin_supabase_is_not_a_local(self):
        """The exact 2026-06-12 failure shape: the name appearing in
        co_varnames means EVERY reference in the function is a local
        load and UnboundLocalError is reachable."""
        self.assertNotIn(
            "_get_admin_supabase",
            self.midday.co_varnames,
            "run_midday_cycle binds _get_admin_supabase locally — every "
            "reference in the function (envelope feed, alert sites) "
            "becomes a local load and raises UnboundLocalError on any "
            "path that doesn't execute the binding first "
            "(2026-06-12 MARA cycle death).",
        )
        self.assertNotIn("_get_admin_supabase", self.midday.co_cellvars)

    def test_get_admin_supabase_is_referenced_as_global(self):
        """The envelope call path still references the module-level
        helper (co_names = global/attribute loads)."""
        self.assertIn(
            "_get_admin_supabase",
            self.midday.co_names,
            "run_midday_cycle no longer references _get_admin_supabase "
            "as a global — if the alert plumbing changed, update this "
            "pin deliberately.",
        )

    def test_envelope_feed_still_routes_through_admin_client(self):
        """Source pin: the v5-A2 envelope feed passes the admin client
        into tightened_daily_pnl (the call that died on 2026-06-12)."""
        self.assertIn("tightened_daily_pnl(", self.src)
        anchor = self.src.find("tightened_daily_pnl(")
        window = self.src[anchor : anchor + 200]
        self.assertIn("_get_admin_supabase()", window)


class TestNoLocalImportShadowsModuleImport(unittest.TestCase):
    """General guard for the bug class: a function-local import must
    never rebind a name that is already imported at module level.
    (A late import under the SAME name shadows the module global for
    the entire function at compile time; use a distinct alias.)"""

    def test_workflow_orchestrator_has_no_shadowing_local_imports(self):
        src = _MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        module_imports = _module_level_import_names(tree)

        violations = []
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if node is func:
                    continue
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        bound = alias.asname or alias.name.split(".")[0]
                        if bound in module_imports:
                            violations.append(
                                f"{func.name}:{node.lineno} local import "
                                f"rebinds module-level name '{bound}'"
                            )
        self.assertEqual(
            violations,
            [],
            "Function-local imports shadow module-level imports "
            "(UnboundLocalError class, see module docstring): "
            + "; ".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
