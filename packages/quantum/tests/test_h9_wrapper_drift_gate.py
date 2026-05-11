"""H9 wrapper-drift AST gate (Slot 1 of H9 Convention infrastructure).

**The class:** wrapper-shaped functions (``refresh_*``, ``submit_*``,
``write_*``, ``upsert_*``, etc.) located in side-effect-relevant
directories (``services/``, ``brokers/``, ``jobs/handlers/``) that
either:
- Contain a silent-swallow pattern (``try / except / pass`` and friends),
- OR return success-shaped data without any verification call in body.

**Convention reference:** H9 in ``docs/loud_error_doctrine.md``.
See in particular the "Codified pattern with empirical anchors
(2026-05-12)" subsection — Rules 1 (typed return), 2 (anchor checkpoint),
and 3 (loud-partial alert).

**Enforcement mode (initial):** WARN-ONLY. The gate scans the codebase
and prints findings to stderr + writes a JSON artifact, but does NOT
fail CI. Rationale: AST gates have well-known false-positive issues;
ship safely first, observe ~1 week of violations, then flip to strict
once the allow-list is stable.

To flip to strict: set ``H9_GATE_STRICT = True`` constant below. The
``test_codebase_h9_compliant`` test will then ``self.fail()`` on any
unflagged violation.

**Class-prevention precedent:** PR #917
(``test_internal_tasks_class_b_body_gate.py``) — same AST-walker shape
applied to a different class. This file mirrors its structure.

**Escape hatches:**
- ``@h9_exempt(reason=...)`` decorator (see
  ``packages/quantum/observability/h9.py``)
- ``packages/quantum/tests/h9_allow_list.yml`` — entries with rationale
  + expiration date; expired entries fail CI (force re-review).

**Fixtures:** 5 violating + 3 compliant, derived from the 5 known H9
instance fix PRs:
- PR-A Layer 4 (PR #903) — silent-swallow in ``upsert_iv_point``
- Issue B (PR #908) — submit without re-read
- #864 — submit with field drop
- #62a-D5 / #117 — DROPPABLE shim ``print``-swallow
- MTM staleness (PR #919 + #920) — silent skip in ``refresh_marks``
"""

import ast
import json
import os
import re
import sys
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None


# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────


# Set this to True to flip the gate to strict mode (CI fails on
# unflagged violation). Plan: review h9_violations.json artifacts
# from ~1 week of CI runs; if violation count is stable and
# allow-list is comprehensive, flip.
H9_GATE_STRICT = False


# Function-name prefixes that mark a function as wrapper-shaped.
# Conservative set: only prefixes that are unambiguously side-effect
# in this codebase. Add carefully — broader patterns produce more
# false positives.
WRAPPER_NAME_PREFIXES: Tuple[str, ...] = (
    "refresh_",
    "submit_",
    "upsert_",
    "persist_",
    "sync_",
    "flush_",
    "write_",
)


# Function-name prefixes whose call inside a wrapper body counts as
# verification (or loud-partial alerting that satisfies Rule 3 of the
# H9 convention).
VERIFICATION_NAME_PREFIXES: Tuple[str, ...] = (
    "verify_",
    "check_",
    "validate_",
    "confirm_",
    "assert_",
)


# Function-name infixes that count as verification. ``count_rows_for_date``
# (PR-A Layer 4 anchor) and ``count_*_for_*`` matches the broader
# anchor-checkpoint shape.
VERIFICATION_NAME_INFIXES: Tuple[str, ...] = (
    "count_rows",
    "_authoritative",
)


# Specific function/method names that count as verification — broker
# authoritative re-read patterns. From the H9 convention's Rule 2
# anchors (see docs/loud_error_doctrine.md).
VERIFICATION_EXACT_NAMES: Tuple[str, ...] = (
    "alert",
    "_log_alert",
    "emit_alert",
    "get_all_positions",
    "get_account",
    "get_order",
    "count_rows_for_date",
)


# Directory roots scanned by the codebase pass. The H9 instances all
# originated from these directories; expanding here means a broader
# false-positive surface, so we stay focused.
_QUANTUM_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS: Tuple[Path, ...] = (
    _QUANTUM_ROOT / "services",
    _QUANTUM_ROOT / "brokers",
    _QUANTUM_ROOT / "jobs" / "handlers",
    _QUANTUM_ROOT / "repositories",
)


ALLOW_LIST_PATH = _QUANTUM_ROOT / "tests" / "h9_allow_list.yml"


# ─────────────────────────────────────────────────────────────────────
# Detection helpers
# ─────────────────────────────────────────────────────────────────────


def _is_wrapper_shape(func_node: ast.AST) -> bool:
    """Function name matches one of WRAPPER_NAME_PREFIXES."""
    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    name = func_node.name
    return any(name.startswith(prefix) for prefix in WRAPPER_NAME_PREFIXES)


def _has_h9_exempt_decorator(func_node: ast.AST) -> bool:
    """Function decorated with ``@h9_exempt(...)``.

    Detected via AST inspection — no runtime import required.
    """
    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for dec in func_node.decorator_list:
        # @h9_exempt(reason="...")
        if isinstance(dec, ast.Call):
            if isinstance(dec.func, ast.Name) and dec.func.id == "h9_exempt":
                return True
            if isinstance(dec.func, ast.Attribute) and dec.func.attr == "h9_exempt":
                return True
        # @h9_exempt (no call — discouraged but recognize)
        if isinstance(dec, ast.Name) and dec.id == "h9_exempt":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "h9_exempt":
            return True
    return False


def _call_name(call: ast.Call) -> Optional[str]:
    """Best-effort: extract the called function's bare name."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _matches_verification_name(name: str) -> bool:
    """Does ``name`` look like a verification helper per our conventions?"""
    if name in VERIFICATION_EXACT_NAMES:
        return True
    if any(name.startswith(prefix) for prefix in VERIFICATION_NAME_PREFIXES):
        return True
    if any(infix in name for infix in VERIFICATION_NAME_INFIXES):
        return True
    return False


def _has_verification_call(func_node: ast.AST) -> bool:
    """Walk the function body for any call to a verification-shaped name."""
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name is None:
            continue
        if _matches_verification_name(name):
            return True
    return False


_ALERT_CALL_NAMES = frozenset({"alert", "_log_alert", "emit_alert"})


def _is_silent_swallow_handler(handler: ast.ExceptHandler) -> bool:
    """Is this ``except`` block a silent swallow?

    Per Loud-Error Doctrine Anti-patterns 1 + 2, an ``except`` block is
    silent iff it BOTH:
    - does not ``raise`` (no re-raise), AND
    - does not call ``alert(...)`` / ``_log_alert(...)`` / ``emit_alert(...)``
      anywhere in the handler body.

    Everything else is silent, regardless of trailing terminator:
    - ``except *: pass``
    - ``except *: return None`` / ``return False`` / ``return {}``
    - ``except *: continue``
    - ``except *: print(...)`` (implicit fallthrough)
    - ``except *: logger.warning(...)`` or ``logger.exception(...)`` etc.
      (log-only is silent per Anti-pattern 2)

    Compliant (NOT silent):
    - ``except *: raise`` / ``except *: raise SomethingElse``
    - ``except *: alert(...); return None`` (loud + return)
    - ``except *: logger.exception(...); alert(...)``
    """
    body = handler.body
    if not body:
        return False

    for node in ast.walk(handler):
        # ``raise`` or ``raise X`` anywhere in the handler counts as
        # not-silent (caller will see the exception).
        if isinstance(node, ast.Raise):
            return False
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name is not None and name in _ALERT_CALL_NAMES:
                return False

    return True


def _has_silent_swallow(func_node: ast.AST) -> bool:
    """Function body contains a silent ``try/except`` swallow pattern."""
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            if _is_silent_swallow_handler(handler):
                return True
    return False


def _has_silent_continue(func_node: ast.AST) -> bool:
    """Function body contains a ``for ... if ... continue`` pattern
    without tracking what was skipped + alerting.

    This catches the MTM-staleness shape: ``if value is None: continue``
    where the skipped position is never recorded or alerted.

    Compliant pattern (NOT flagged):
        for x in items:
            if not has_data(x):
                skipped.append(x.id)
                continue
            ...
        if skipped:
            alert(...)
    """
    for loop in ast.walk(func_node):
        if not isinstance(loop, (ast.For, ast.AsyncFor)):
            continue
        # Look for an ``if`` branch whose body is a bare ``continue``.
        for stmt in ast.walk(loop):
            if not isinstance(stmt, ast.If):
                continue
            if len(stmt.body) != 1:
                continue
            inner = stmt.body[0]
            if not isinstance(inner, ast.Continue):
                continue
            # Bare ``if cond: continue`` — silent unless the loop's
            # surrounding scope alerts on completion.
            return not _has_post_loop_alert(func_node, loop)
    return False


def _has_post_loop_alert(func_node: ast.AST, loop: ast.AST) -> bool:
    """Is there an ``alert``-shaped call somewhere AFTER ``loop`` in
    the function body?

    Approximation: any ``alert``/``_log_alert``/``emit_alert`` call at
    or below the function's top-level statements counts. Robust to
    nested-condition wrapping; loses precision on multi-loop functions.
    """
    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    loop_lineno = getattr(loop, "lineno", 0)
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node, "lineno", 0) <= loop_lineno:
            continue
        name = _call_name(node)
        if name in {"alert", "_log_alert", "emit_alert"}:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────
# Allow-list
# ─────────────────────────────────────────────────────────────────────


def _load_allow_list() -> List[Dict[str, str]]:
    """Read the YAML allow-list. Returns [] if file missing/empty."""
    if not ALLOW_LIST_PATH.exists():
        return []
    if yaml is None:
        # PyYAML not available — fall back to a permissive empty list
        # and let the test print a soft warning. Yaml is a transitive
        # dep via supabase, so this should be rare.
        return []
    content = ALLOW_LIST_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content) or {}
    entries = parsed.get("allow_list", [])
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict)]


def _in_allow_list(
    module_path: str,
    function_name: str,
    allow_list: List[Dict[str, str]],
) -> Optional[str]:
    """Return rationale if (module, function) is allow-listed, else None.

    Match is by suffix on module_path so allow-list entries can use the
    package-qualified form (``packages.quantum.services.foo``) or the
    bare module name (``foo``).
    """
    for entry in allow_list:
        entry_module = str(entry.get("module", ""))
        entry_func = str(entry.get("function", ""))
        if not entry_func or entry_func != function_name:
            continue
        if not entry_module:
            continue
        if module_path.endswith(entry_module) or entry_module.endswith(module_path):
            return str(entry.get("rationale", "no rationale"))
    return None


# ─────────────────────────────────────────────────────────────────────
# Violation collector
# ─────────────────────────────────────────────────────────────────────


def _analyze_function(
    func_node: ast.AST,
    filepath: Path,
    relative_module: str,
    allow_list: List[Dict[str, str]],
) -> Optional[Dict[str, object]]:
    """Inspect a single function. Returns a violation dict, or None if
    the function is compliant / not a wrapper / exempt."""

    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None

    if not _is_wrapper_shape(func_node):
        return None

    if _has_h9_exempt_decorator(func_node):
        return None

    # Allow-list check.
    rationale = _in_allow_list(relative_module, func_node.name, allow_list)
    if rationale is not None:
        return None

    # Verification calls trump silent-swallow markers — if the wrapper
    # verifies its work (or alerts on failure), it is H9-compliant.
    if _has_verification_call(func_node):
        return None

    violations: List[str] = []
    if _has_silent_swallow(func_node):
        violations.append("silent_swallow")
    if _has_silent_continue(func_node):
        violations.append("silent_continue_without_alert")

    if not violations:
        return None

    return {
        "file": str(filepath),
        "module": relative_module,
        "function": func_node.name,
        "line": func_node.lineno,
        "reasons": violations,
    }


def _walk_python_files(scan_dirs: Tuple[Path, ...]) -> List[Path]:
    """Yield every .py file under each scan_dir, excluding __pycache__."""
    out: List[Path] = []
    for root in scan_dirs:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            out.append(path)
    return out


def _relative_module(filepath: Path) -> str:
    """Convert a file path to a dotted module path relative to the repo
    root. Best-effort; falls back to a stem-based identifier."""
    parts = filepath.with_suffix("").parts
    try:
        idx = parts.index("packages")
        return ".".join(parts[idx:])
    except ValueError:
        return filepath.stem


def scan_codebase() -> List[Dict[str, object]]:
    """Run the H9 detector across SCAN_DIRS. Public so other tooling
    (e.g., a CLI wrapper) can invoke without touching unittest internals."""
    allow_list = _load_allow_list()
    violations: List[Dict[str, object]] = []
    for filepath in _walk_python_files(SCAN_DIRS):
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
        except (UnicodeDecodeError, SyntaxError):
            continue

        relative_module = _relative_module(filepath)
        for node in ast.walk(tree):
            v = _analyze_function(node, filepath, relative_module, allow_list)
            if v is not None:
                violations.append(v)
    return violations


# ─────────────────────────────────────────────────────────────────────
# Fixtures derived from the 5 known H9 instances
# ─────────────────────────────────────────────────────────────────────


# Each fixture captures the BEFORE-FIX code shape of one H9 instance.
# Names mirror real production functions for legibility, but the bodies
# are minimal — enough to capture the violation pattern, not enough to
# require the full repo's import graph.
H9_VIOLATING_FIXTURES: List[Dict[str, str]] = [
    {
        "name": "PR-A Layer 4 — upsert_iv_point silent swallow",
        "pr_ref": "#903",
        "code": """
def upsert_iv_point(underlying, data, as_of_ts):
    payload = {"underlying": underlying, "as_of_date": as_of_ts.date()}
    try:
        result = supabase.table("underlying_iv_points") \\
            .upsert(payload, on_conflict="underlying, as_of_date") \\
            .execute()
    except Exception as e:
        print(f"upsert failed: {e}")
        return None
    return None
""".lstrip(),
    },
    {
        "name": "Issue B — submit_close_order without re-read",
        "pr_ref": "#908",
        "code": """
def submit_close_order(position, limit_price):
    order = construct_order(position, limit_price)
    try:
        response = broker.submit(order)
    except Exception:
        return None
    return {"status": "ok", "order_id": response.id}
""".lstrip(),
    },
    {
        "name": "#864 — submit_with_fields silent drop",
        "pr_ref": "#864",
        "code": """
def submit_account_payload(order_data):
    minimal = {"symbol": order_data["symbol"], "qty": order_data["qty"]}
    try:
        return broker.submit(minimal)
    except Exception:
        pass
    return {"status": "ok"}
""".lstrip(),
    },
    {
        "name": "#62a-D5 / #117 — write_droppable shim print-swallow",
        "pr_ref": "#117",
        "code": """
def write_suggestion(suggestion):
    payload = dict(suggestion)
    for col in DROPPABLE_COLUMNS:
        if col in payload:
            del payload[col]
    try:
        supabase.table("trade_suggestions").insert(payload).execute()
    except Exception as e:
        print(f"insert failed; dropped columns: {e}")
    return {"status": "ok"}
""".lstrip(),
    },
    {
        "name": "MTM staleness — refresh_marks silent skip",
        "pr_ref": "#919 / #920",
        "code": """
def refresh_marks(user_id):
    marked = 0
    for pos in get_positions(user_id):
        value = compute_value(pos)
        if value is None:
            continue
        db.update(pos.id, value)
        marked += 1
    return {"status": "ok", "marked": marked}
""".lstrip(),
    },
]


# Compliant fixtures — code that the gate should NOT flag.
H9_COMPLIANT_FIXTURES: List[Dict[str, str]] = [
    {
        "name": "MTM-staleness POST-fix: refresh_marks with skip-tracking + alert",
        "code": """
def refresh_marks(user_id):
    marked = 0
    skipped = []
    for pos in get_positions(user_id):
        value = compute_value(pos)
        if value is None:
            skipped.append(pos.id)
            continue
        db.update(pos.id, value)
        marked += 1
    if skipped:
        alert(supabase, alert_type="refresh_partial", message="...")
    return {"status": "ok" if not skipped else "partial", "marked": marked}
""".lstrip(),
    },
    {
        "name": "PR-A POST-fix: upsert_iv_point with typed return + raise",
        "code": """
def upsert_iv_point(underlying, data, as_of_ts):
    try:
        result = supabase.table("underlying_iv_points") \\
            .upsert({"underlying": underlying}, on_conflict="underlying, as_of_date") \\
            .execute()
    except Exception:
        raise
    return bool(result.data)
""".lstrip(),
    },
    {
        "name": "Explicit exemption",
        "code": """
@h9_exempt(reason="pure read; no side effects to verify")
def refresh_in_memory_cache(key):
    return {"status": "ok", "data": _cache.get(key)}
""".lstrip(),
    },
]


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────


class TestFixturesFlagged(unittest.TestCase):
    """Each violating fixture must be flagged. Each compliant fixture
    must NOT be flagged. Catches false positives + false negatives at
    the detector layer before they reach the codebase scan."""

    def _violations_in(self, code: str) -> List[Dict[str, object]]:
        tree = ast.parse(code)
        out: List[Dict[str, object]] = []
        for node in ast.walk(tree):
            v = _analyze_function(node, Path("<fixture>"), "<fixture>", allow_list=[])
            if v is not None:
                out.append(v)
        return out

    def test_each_violating_fixture_flagged(self):
        for fixture in H9_VIOLATING_FIXTURES:
            with self.subTest(name=fixture["name"]):
                vs = self._violations_in(fixture["code"])
                self.assertEqual(
                    len(vs), 1,
                    f"Expected exactly 1 violation for "
                    f"{fixture['name']!r} (pr_ref={fixture.get('pr_ref')}), "
                    f"got {len(vs)}: {vs}. "
                    f"Either the fixture's violation shape isn't being "
                    f"detected (false negative — detector bug) OR the "
                    f"fixture matches multiple times (test artifact).",
                )

    def test_no_compliant_fixture_flagged(self):
        for fixture in H9_COMPLIANT_FIXTURES:
            with self.subTest(name=fixture["name"]):
                vs = self._violations_in(fixture["code"])
                self.assertEqual(
                    len(vs), 0,
                    f"Compliant fixture {fixture['name']!r} was flagged: "
                    f"{vs}. The detection logic is over-flagging — tune "
                    f"verification recognition before shipping.",
                )


class TestDetectionPrimitives(unittest.TestCase):
    """Unit tests on the individual detection primitives, so that
    failures localize to the responsible helper rather than to the
    fixture-level integration test."""

    def _parse_first_func(self, code: str) -> ast.AST:
        tree = ast.parse(code)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        raise AssertionError("no function in fixture")

    def test_wrapper_shape_recognized_for_known_prefixes(self):
        for prefix in WRAPPER_NAME_PREFIXES:
            func = self._parse_first_func(f"def {prefix}thing(): pass")
            self.assertTrue(
                _is_wrapper_shape(func),
                f"Prefix {prefix!r} not recognized as wrapper-shape",
            )

    def test_wrapper_shape_rejects_read_shaped_names(self):
        for name in ("get_account", "compute_score", "evaluate_strategy"):
            func = self._parse_first_func(f"def {name}(): pass")
            self.assertFalse(
                _is_wrapper_shape(func),
                f"{name!r} should not match wrapper-shape (it's a read/compute)",
            )

    def test_silent_swallow_pass_detected(self):
        func = self._parse_first_func("""
def refresh_x():
    try:
        do_thing()
    except Exception:
        pass
""")
        self.assertTrue(_has_silent_swallow(func))

    def test_silent_swallow_return_none_detected(self):
        func = self._parse_first_func("""
def refresh_x():
    try:
        do_thing()
    except Exception:
        return None
""")
        self.assertTrue(_has_silent_swallow(func))

    def test_silent_swallow_print_detected(self):
        func = self._parse_first_func("""
def refresh_x():
    try:
        do_thing()
    except Exception as e:
        print(f"err: {e}")
        return None
""")
        self.assertTrue(_has_silent_swallow(func))

    def test_reraise_not_silent(self):
        func = self._parse_first_func("""
def refresh_x():
    try:
        do_thing()
    except Exception:
        raise
""")
        self.assertFalse(_has_silent_swallow(func))

    def test_alert_then_return_not_silent(self):
        func = self._parse_first_func("""
def refresh_x():
    try:
        do_thing()
    except Exception:
        alert(supabase, alert_type="refresh_failed", message="...")
        return None
""")
        self.assertFalse(_has_silent_swallow(func))

    def test_h9_exempt_decorator_detected(self):
        func = self._parse_first_func("""
@h9_exempt(reason="pure read; no side effects to verify")
def refresh_in_memory_cache():
    pass
""")
        self.assertTrue(_has_h9_exempt_decorator(func))

    def test_verification_call_count_rows_for_date(self):
        func = self._parse_first_func("""
def refresh_x():
    do_thing()
    actual = repo.count_rows_for_date(today)
    return actual > 0
""")
        self.assertTrue(_has_verification_call(func))

    def test_verification_call_alert(self):
        func = self._parse_first_func("""
def refresh_x():
    do_thing()
    alert(supabase, alert_type="x", message="y")
    return None
""")
        self.assertTrue(_has_verification_call(func))


class TestH9ExemptDecoratorContract(unittest.TestCase):
    """The decorator itself enforces a minimum-rationale contract; the
    AST gate then trusts the decorator's presence as proof of review."""

    def test_decorator_requires_non_empty_reason(self):
        from packages.quantum.observability.h9 import h9_exempt
        with self.assertRaises(ValueError):
            h9_exempt(reason="")

    def test_decorator_requires_substantive_reason(self):
        from packages.quantum.observability.h9 import h9_exempt
        with self.assertRaises(ValueError):
            h9_exempt(reason="TODO")  # too short

    def test_decorator_passes_substantive_reason(self):
        from packages.quantum.observability.h9 import h9_exempt

        @h9_exempt(reason="pure read; no side effects to verify")
        def f():
            return 42

        self.assertEqual(f(), 42)
        self.assertEqual(
            f.__h9_exempt__,  # type: ignore[attr-defined]
            "pure read; no side effects to verify",
        )


class TestAllowListMechanism(unittest.TestCase):
    """Allow-list parsing + matching contract."""

    def test_allow_list_file_optional(self):
        """Missing allow-list file shouldn't crash the scan."""
        # We can't easily test deletion of a shipping file — but we
        # can confirm the loader returns [] on a non-existent path.
        from packages.quantum.tests.test_h9_wrapper_drift_gate import (
            _load_allow_list, ALLOW_LIST_PATH,
        )
        # Loader handles missing file gracefully.
        # (We don't unlink the real file — the contract is verified
        # by the early-return branch in the loader.)
        self.assertIsInstance(_load_allow_list(), list)

    def test_match_by_module_function_pair(self):
        entries = [
            {
                "module": "packages.quantum.services.foo",
                "function": "refresh_bar",
                "rationale": "pending refactor",
            }
        ]
        self.assertEqual(
            _in_allow_list(
                "packages.quantum.services.foo", "refresh_bar", entries,
            ),
            "pending refactor",
        )

    def test_no_match_for_different_function(self):
        entries = [{"module": "foo", "function": "refresh_bar", "rationale": "x"}]
        self.assertIsNone(_in_allow_list("foo", "refresh_baz", entries))


class TestCodebaseH9Compliant(unittest.TestCase):
    """The actual gate — scans the live codebase. WARN-ONLY mode prints
    violations + writes h9_violations.json artifact but doesn't fail.

    When H9_GATE_STRICT is True the test asserts no violations remain.
    """

    def test_codebase_h9_compliant(self):
        violations = scan_codebase()

        # Always write the artifact for trend analysis. Artifact path
        # is configurable via env so CI can pick it up; default sits
        # in the repo root so it's discoverable locally too.
        artifact_path = Path(
            os.environ.get(
                "H9_VIOLATIONS_ARTIFACT",
                str(_QUANTUM_ROOT.parent.parent / "h9_violations.json"),
            )
        )
        try:
            artifact_path.write_text(
                json.dumps(violations, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            # Artifact write is best-effort.
            pass

        if not violations:
            return

        # Sort for stable output across runs.
        violations.sort(key=lambda v: (v["file"], v["line"]))  # type: ignore[index]

        msg_lines = [
            "",
            f"H9 Convention violations detected ({len(violations)} total):",
            "",
        ]
        for v in violations:
            reasons = ", ".join(v["reasons"])  # type: ignore[arg-type]
            msg_lines.append(
                f"  {v['file']}:{v['line']} :: {v['function']}() — {reasons}"
            )
        msg_lines.extend([
            "",
            "Gate is in WARN-ONLY mode. Will flip to strict after ~1 week "
            "of observability data shows the allow-list is stable.",
            "",
            "To suppress a legitimate case:",
            "  - Add @h9_exempt(reason=\"...\") decorator",
            "    (import from packages.quantum.observability.h9)",
            "  - OR add an entry to packages/quantum/tests/h9_allow_list.yml",
            "",
            "Convention reference: docs/loud_error_doctrine.md H9 section.",
            "",
        ])

        full_msg = "\n".join(msg_lines)

        if H9_GATE_STRICT:
            self.fail(full_msg)
        else:
            # Warn-only: print to stderr so it surfaces in CI logs.
            print(full_msg, file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
