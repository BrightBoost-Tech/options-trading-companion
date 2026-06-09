"""Historical-mode learning quarantine (BUILD 1) — helper behavior + AST backstop.

Two layers:
- **Enforcement point** — ``analytics/learning_read_filter.py``: the fail-closed
  ``outcome_type`` allowlist that the two live-affecting readers route through.
- **Backstop** — the AST gate below, which fails if ANY function in a
  live-affecting module pulls ``learning_feedback_loops`` *data* without routing
  through the helper (or carrying an equivalent trusted ``outcome_type``
  constraint). This is what catches a FUTURE unfiltered reader, not just the two
  known sites.

Compliance model (per function that reads the table):
- Skipped (not a data read): the function only WRITES (insert/update/upsert/
  delete present), OR every ``.select(...)`` is an existence/metric read
  (``select("id")`` or a ``count=`` read).
- Compliant data read: references the helper
  (``partition_trusted_rows`` / ``apply_trusted_outcome_filter`` /
  ``TRUSTED_LEARNING_OUTCOME_TYPES``) OR carries a trusted ``outcome_type``
  constraint (``.in_("outcome_type", L)`` with ``L ⊆`` trusted, or
  ``.eq("outcome_type", v)`` with ``v ∈`` trusted).
- Violation: a data read with neither.

Mirrors the H9 AST gate (``test_h9_wrapper_drift_gate.py``) in shape.
"""

import ast
import os
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from unittest import mock

from packages.quantum.analytics.learning_read_filter import (
    TRUSTED_LEARNING_OUTCOME_TYPES,
    REALIZED_TRADE_OUTCOME_TYPES,
    FLAG_ENV,
    is_quarantine_enabled,
    partition_trusted_rows,
    apply_trusted_outcome_filter,
)


# ─────────────────────────────────────────────────────────────────────
# Helper behavior
# ─────────────────────────────────────────────────────────────────────


def _row(outcome_type, **extra):
    d = {"outcome_type": outcome_type}
    d.update(extra)
    return d


class TestQuarantineFlag(unittest.TestCase):
    def test_default_on_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(FLAG_ENV, None)
            self.assertTrue(is_quarantine_enabled())

    def test_default_on_when_empty(self):
        with mock.patch.dict(os.environ, {FLAG_ENV: ""}):
            self.assertTrue(is_quarantine_enabled())

    def test_default_on_when_whitespace(self):
        with mock.patch.dict(os.environ, {FLAG_ENV: "   "}):
            self.assertTrue(is_quarantine_enabled())

    def test_explicit_off_values_disable(self):
        for val in ("0", "false", "FALSE", "no", "off", "Off"):
            with mock.patch.dict(os.environ, {FLAG_ENV: val}):
                self.assertFalse(is_quarantine_enabled(), f"{val!r} should disable")

    def test_truthy_values_enable(self):
        for val in ("1", "true", "yes", "on", "anything-else"):
            with mock.patch.dict(os.environ, {FLAG_ENV: val}):
                self.assertTrue(is_quarantine_enabled(), f"{val!r} should enable")


class TestPartitionTrustedRows(unittest.TestCase):
    def setUp(self):
        # Force default-ON regardless of the runner's env.
        self._env = mock.patch.dict(os.environ, {FLAG_ENV: "1"})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_trade_closed_flows_through(self):
        rows = [_row("trade_closed", pnl_realized=10), _row("trade_closed")]
        out = partition_trusted_rows(rows, reader="t")
        self.assertEqual(len(out), 2)

    def test_individual_trade_allowlisted(self):
        out = partition_trusted_rows([_row("individual_trade")], reader="t")
        self.assertEqual(len(out), 1)

    def test_historical_markers_excluded(self):
        rows = [
            _row("trade_closed"),
            _row("historical_win", pnl_realized=16),
            _row("historical_loss", pnl_realized=-14),
            _row("aggregate", total_trades=31),
        ]
        out = partition_trusted_rows(rows, reader="t")
        self.assertEqual([r["outcome_type"] for r in out], ["trade_closed"])

    def test_unknown_mode_excluded_by_default(self):
        # Fail-closed: a brand-new synthetic outcome_type is dropped without
        # anyone having to add it to a denylist.
        rows = [_row("trade_closed"), _row("some_future_synthetic_source")]
        out = partition_trusted_rows(rows, reader="t")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["outcome_type"], "trade_closed")

    def test_missing_outcome_type_excluded(self):
        out = partition_trusted_rows([{"pnl_realized": 5}], reader="t")
        self.assertEqual(out, [])

    def test_empty_and_none(self):
        self.assertEqual(partition_trusted_rows([], reader="t"), [])
        self.assertEqual(partition_trusted_rows(None, reader="t"), [])

    def test_excluded_count_logged(self):
        rows = [_row("trade_closed"), _row("historical_win"), _row("aggregate")]
        with self.assertLogs("packages.quantum.analytics.learning_read_filter", level="INFO") as cm:
            partition_trusted_rows(rows, reader="my_reader")
        joined = "\n".join(cm.output)
        self.assertIn("excluded 2/3", joined)
        self.assertIn("my_reader", joined)

    def test_realized_set_keeps_live_win_loss_breakeven(self):
        # autotune's set: live-ingest win/loss/breakeven are REAL outcomes and
        # must survive; the historical_* twins must not.
        rows = [
            _row("trade_closed"), _row("individual_trade"),
            _row("win"), _row("loss"), _row("breakeven"),
            _row("historical_win"), _row("historical_loss"), _row("aggregate"),
        ]
        out = partition_trusted_rows(rows, reader="autotune", allowed=REALIZED_TRADE_OUTCOME_TYPES)
        self.assertEqual(
            {r["outcome_type"] for r in out},
            {"trade_closed", "individual_trade", "win", "loss", "breakeven"},
        )

    def test_realized_set_is_superset_of_view_grade(self):
        self.assertTrue(TRUSTED_LEARNING_OUTCOME_TYPES.issubset(REALIZED_TRADE_OUTCOME_TYPES))
        self.assertNotIn("historical_win", REALIZED_TRADE_OUTCOME_TYPES)
        self.assertNotIn("aggregate", REALIZED_TRADE_OUTCOME_TYPES)

    def test_view_grade_excludes_win_loss(self):
        # conviction's view-grade set deliberately does NOT include win/loss —
        # that's fine because conviction's legacy path skips per-trade rows on
        # the total_trades gate anyway (zero-delta).
        out = partition_trusted_rows([_row("win"), _row("trade_closed")], reader="conv")
        self.assertEqual([r["outcome_type"] for r in out], ["trade_closed"])

    def test_kill_switch_off_is_loud_noop(self):
        with mock.patch.dict(os.environ, {FLAG_ENV: "0"}):
            rows = [_row("trade_closed"), _row("historical_win")]
            with self.assertLogs("packages.quantum.analytics.learning_read_filter", level="WARNING") as cm:
                out = partition_trusted_rows(rows, reader="r")
            self.assertEqual(len(out), 2, "OFF → no filtering (rollback path)")
            self.assertIn("DISABLED", "\n".join(cm.output))


class TestApplyTrustedOutcomeFilter(unittest.TestCase):
    class _Q:
        def __init__(self):
            self.calls = []

        def in_(self, col, vals):
            self.calls.append((col, list(vals)))
            return self

    def test_chains_in_filter_when_enabled(self):
        with mock.patch.dict(os.environ, {FLAG_ENV: "1"}):
            q = self._Q()
            apply_trusted_outcome_filter(q)
            self.assertEqual(len(q.calls), 1)
            col, vals = q.calls[0]
            self.assertEqual(col, "outcome_type")
            self.assertEqual(set(vals), TRUSTED_LEARNING_OUTCOME_TYPES)

    def test_noop_when_disabled(self):
        with mock.patch.dict(os.environ, {FLAG_ENV: "off"}):
            q = self._Q()
            self.assertIs(apply_trusted_outcome_filter(q), q)
            self.assertEqual(q.calls, [])


# ─────────────────────────────────────────────────────────────────────
# AST backstop
# ─────────────────────────────────────────────────────────────────────

TABLE = "learning_feedback_loops"
HELPER_NAMES = frozenset(
    {"partition_trusted_rows", "apply_trusted_outcome_filter", "TRUSTED_LEARNING_OUTCOME_TYPES"}
)
_WRITE_CALLS = frozenset({"insert", "update", "upsert", "delete"})

_QUANTUM_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS: Tuple[Path, ...] = (
    _QUANTUM_ROOT / "analytics",
    _QUANTUM_ROOT / "jobs" / "handlers",
    _QUANTUM_ROOT / "services",
)

# (module-suffix, function) → rationale. Legitimate non-quarantine data reads.
# Expected empty after the fix; an entry forces explicit review.
ALLOW_LIST: Dict[Tuple[str, str], str] = {}


def _call_name(call: ast.Call) -> Optional[str]:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _const_str(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _trusted_outcome_constraint(call: ast.Call) -> bool:
    """``.eq("outcome_type", v)`` with v ∈ trusted, or ``.in_("outcome_type", L)``
    with L ⊆ trusted."""
    name = _call_name(call)
    if name not in ("eq", "in_") or len(call.args) < 2:
        return False
    if _const_str(call.args[0]) != "outcome_type":
        return False
    if name == "eq":
        v = _const_str(call.args[1])
        return v in TRUSTED_LEARNING_OUTCOME_TYPES
    # in_: second arg a list/tuple/set of string constants
    seq = call.args[1]
    if not isinstance(seq, (ast.List, ast.Tuple, ast.Set)):
        return False
    vals: Set[str] = set()
    for el in seq.elts:
        s = _const_str(el)
        if s is None:
            return False  # dynamic element → cannot prove ⊆ trusted
        vals.add(s)
    return bool(vals) and vals.issubset(TRUSTED_LEARNING_OUTCOME_TYPES)


def _select_is_existence_only(args: List[ast.expr], keywords: List[ast.keyword]) -> bool:
    """A ``.select(...)`` that reads only ``id`` or is a ``count=`` read —
    existence / metric, not learning-data consumption."""
    if any(k.arg == "count" for k in keywords):
        return True
    cols: Set[str] = set()
    for a in args:
        s = _const_str(a)
        if s is None:
            return False  # non-literal select → treat as data read (conservative)
        for part in s.split(","):
            p = part.strip()
            if p:
                cols.add(p)
    return cols == {"id"} or cols == set()


def _analyze_function(func: ast.AST, module: str) -> Optional[Dict[str, object]]:
    if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None

    table_ref = False
    writes = False
    data_select = False
    trusted_filter = False
    helper_ref = False

    for node in ast.walk(func):
        if isinstance(node, ast.Name) and node.id in HELPER_NAMES:
            helper_ref = True
        if isinstance(node, ast.Attribute) and node.attr in HELPER_NAMES:
            helper_ref = True
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name in ("table", "from_"):
            for a in node.args:
                if _const_str(a) == TABLE:
                    table_ref = True
        elif name in _WRITE_CALLS:
            writes = True
        elif name == "select":
            if not _select_is_existence_only(node.args, node.keywords):
                data_select = True
        elif _trusted_outcome_constraint(node):
            trusted_filter = True

    if not table_ref or not data_select:
        return None  # doesn't read the table, or only existence/metric reads
    if writes:
        return None  # writer function (e.g. the historical writer, ingest)
    if (module, func.name) in ALLOW_LIST:
        return None
    if helper_ref or trusted_filter:
        return None

    return {"module": module, "function": func.name, "line": func.lineno}


def _relative_module(path: Path) -> str:
    parts = path.with_suffix("").parts
    try:
        idx = parts.index("packages")
        return ".".join(parts[idx:])
    except ValueError:
        return path.stem


def scan() -> List[Dict[str, object]]:
    violations: List[Dict[str, object]] = []
    for root in SCAN_DIRS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (UnicodeDecodeError, SyntaxError):
                continue
            module = _relative_module(path)
            for node in ast.walk(tree):
                v = _analyze_function(node, module)
                if v is not None:
                    violations.append(v)
    return violations


# Fixtures: a future bypassing reader (must be flagged) + compliant shapes.
_VIOLATING = """
def get_perf_multipliers(supabase, user_id):
    res = supabase.table("learning_feedback_loops").select("*").eq("user_id", user_id).execute()
    rows = res.data or []
    return {r["strategy"]: r["avg_return"] for r in rows}
"""

_COMPLIANT_HELPER = """
def get_perf_multipliers(supabase, user_id):
    res = supabase.table("learning_feedback_loops").select("*").eq("user_id", user_id).execute()
    rows = partition_trusted_rows(res.data or [], reader="x")
    return rows
"""

_COMPLIANT_INLINE = """
def get_closes(supabase, user_id):
    return supabase.table("learning_feedback_loops").select("pnl_realized, strategy") \\
        .in_("outcome_type", ["trade_closed", "individual_trade"]).eq("user_id", user_id).execute()
"""

_SKIP_EXISTENCE = """
def insert_outcome(supabase, outcome):
    existing = supabase.table("learning_feedback_loops").select("id").eq("trace_id", outcome["trace_id"]).execute()
    if existing.data:
        return False
    supabase.table("learning_feedback_loops").insert(outcome).execute()
    return True
"""

_SKIP_COUNT = """
def closed_today(supabase, user_id):
    return supabase.table("learning_feedback_loops").select("id", count="exact").eq("user_id", user_id).execute().count
"""


class TestBackstopFixtures(unittest.TestCase):
    def _violations(self, code: str):
        tree = ast.parse(code)
        out = []
        for node in ast.walk(tree):
            v = _analyze_function(node, "fixture")
            if v is not None:
                out.append(v)
        return out

    def test_unfiltered_reader_flagged(self):
        self.assertEqual(len(self._violations(_VIOLATING)), 1)

    def test_helper_routed_not_flagged(self):
        self.assertEqual(self._violations(_COMPLIANT_HELPER), [])

    def test_inline_trusted_filter_not_flagged(self):
        self.assertEqual(self._violations(_COMPLIANT_INLINE), [])

    def test_existence_check_not_flagged(self):
        self.assertEqual(self._violations(_SKIP_EXISTENCE), [])

    def test_count_read_not_flagged(self):
        self.assertEqual(self._violations(_SKIP_COUNT), [])

    def test_untrusted_eq_still_flagged(self):
        # An outcome_type constraint that is NOT a subset of trusted must not
        # count as compliant (closes the "filter to a synthetic type" hole).
        code = """
def reader(supabase, user_id):
    return supabase.table("learning_feedback_loops").select("avg_return") \\
        .eq("outcome_type", "historical_win").eq("user_id", user_id).execute()
"""
        self.assertEqual(len(self._violations(code)), 1)


class TestCodebaseClean(unittest.TestCase):
    """The live scan — must be clean (helper is wired at both known sites)."""

    def test_no_unquarantined_live_readers(self):
        violations = scan()
        if violations:
            lines = "\n".join(
                f"  {v['module']}.{v['function']} (line {v['line']})" for v in violations
            )
            self.fail(
                "Live-affecting learning_feedback_loops data read(s) bypass the "
                "quarantine helper:\n" + lines +
                "\n\nRoute through analytics/learning_read_filter."
                "partition_trusted_rows (or apply_trusted_outcome_filter), or add "
                "an ALLOW_LIST entry with rationale."
            )


# ─────────────────────────────────────────────────────────────────────
# Source pins — the two known sites stay wired
# ─────────────────────────────────────────────────────────────────────


class TestKnownSitesWired(unittest.TestCase):
    def test_conviction_legacy_routes_through_helper(self):
        src = (_QUANTUM_ROOT / "analytics" / "conviction_service.py").read_text(encoding="utf-8")
        self.assertIn("partition_trusted_rows", src)
        self.assertIn("conviction_legacy_multipliers", src)

    def test_autotune_routes_through_helper(self):
        src = (_QUANTUM_ROOT / "jobs" / "handlers" / "strategy_autotune.py").read_text(encoding="utf-8")
        self.assertIn("partition_trusted_rows", src)


if __name__ == "__main__":
    unittest.main()
