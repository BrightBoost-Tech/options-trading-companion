"""
Tests for get_current_champion — the integration-seam closure for
#62a-D1 (H12 — Parallel architectures without integration).

Coverage:
- Normal path: aggressive is promoted; helper returns "aggressive"
- Fallback path: no cohort promoted; helper logs warning + returns
  "aggressive"
- Multi-promoted path: multiple cohorts have promoted_at set; helper
  returns the most recent (ORDER BY promoted_at DESC LIMIT 1)
- Exception path: DB query raises; helper logs warning + returns
  "aggressive" (defensive)
- is_active filter: inactive promoted cohort ignored
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py so imports resolve in the test venv.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.policy_lab.champion import get_current_champion  # noqa: E402


class _SupabaseChain:
    """Captures the fluent-query chain built by get_current_champion
    and returns the configured row set on execute()."""

    def __init__(self, rows=None, raise_on_execute=None):
        self._rows = rows or []
        self._raise = raise_on_execute
        self.calls = []  # records (method, args) tuples

    def table(self, name):
        self.calls.append(("table", name))
        return self

    def select(self, *args, **kwargs):
        self.calls.append(("select", args, kwargs))
        return self

    def eq(self, col, val):
        self.calls.append(("eq", col, val))
        return self

    @property
    def not_(self):
        return _NotPrefix(self)

    def order(self, *args, **kwargs):
        self.calls.append(("order", args, kwargs))
        return self

    def limit(self, n):
        self.calls.append(("limit", n))
        return self

    def execute(self):
        if self._raise:
            raise self._raise
        return MagicMock(data=self._rows)


class _NotPrefix:
    def __init__(self, parent):
        self.parent = parent

    def is_(self, col, val):
        self.parent.calls.append(("not_.is_", col, val))
        return self.parent


class TestNormalPath(unittest.TestCase):
    """Aggressive is the promoted champion → return 'aggressive'."""

    def test_returns_promoted_cohort_name(self):
        sb = _SupabaseChain(rows=[{"cohort_name": "aggressive"}])
        result = get_current_champion("user-1", sb)
        self.assertEqual(result, "aggressive")

    def test_query_filters_by_user_id(self):
        sb = _SupabaseChain(rows=[{"cohort_name": "aggressive"}])
        get_current_champion("user-xyz", sb)
        user_filter = [c for c in sb.calls if c[0] == "eq" and c[1] == "user_id"]
        self.assertEqual(len(user_filter), 1)
        self.assertEqual(user_filter[0][2], "user-xyz")

    def test_query_filters_by_is_active(self):
        sb = _SupabaseChain(rows=[{"cohort_name": "aggressive"}])
        get_current_champion("user-1", sb)
        active_filter = [c for c in sb.calls if c[0] == "eq" and c[1] == "is_active"]
        self.assertEqual(len(active_filter), 1)
        self.assertEqual(active_filter[0][2], True)

    def test_query_excludes_null_promoted_at(self):
        sb = _SupabaseChain(rows=[{"cohort_name": "aggressive"}])
        get_current_champion("user-1", sb)
        not_null_filter = [c for c in sb.calls if c[0] == "not_.is_"]
        self.assertEqual(len(not_null_filter), 1)
        self.assertEqual(not_null_filter[0][1], "promoted_at")

    def test_query_orders_promoted_at_desc(self):
        sb = _SupabaseChain(rows=[{"cohort_name": "aggressive"}])
        get_current_champion("user-1", sb)
        order_calls = [c for c in sb.calls if c[0] == "order"]
        self.assertEqual(len(order_calls), 1)
        args = order_calls[0][1]
        self.assertEqual(args[0], "promoted_at")
        kwargs = order_calls[0][2]
        self.assertIs(kwargs.get("desc"), True)


class TestFallbackPath(unittest.TestCase):
    """No promoted cohort → log warning + return 'aggressive'."""

    def test_empty_result_returns_aggressive(self):
        sb = _SupabaseChain(rows=[])
        result = get_current_champion("user-1", sb)
        self.assertEqual(result, "aggressive")

    def test_empty_result_logs_warning(self):
        sb = _SupabaseChain(rows=[])
        with self.assertLogs(
            "packages.quantum.policy_lab.champion", level="WARNING"
        ) as cm:
            get_current_champion("user-1", sb)
        self.assertTrue(
            any("No promoted cohort found" in msg for msg in cm.output),
            f"Expected fallback warning; got {cm.output}",
        )

    def test_row_with_empty_cohort_name_falls_back(self):
        # Row exists but cohort_name is empty → still fall back.
        sb = _SupabaseChain(rows=[{"cohort_name": ""}])
        result = get_current_champion("user-1", sb)
        self.assertEqual(result, "aggressive")

    def test_row_missing_cohort_name_field_falls_back(self):
        # Row exists but no cohort_name key → fall back.
        sb = _SupabaseChain(rows=[{"other_col": "x"}])
        result = get_current_champion("user-1", sb)
        self.assertEqual(result, "aggressive")


class TestMultiPromoted(unittest.TestCase):
    """Multiple cohorts have promoted_at set → return most recent
    (the SQL `ORDER BY promoted_at DESC LIMIT 1` handles this; we
    verify the helper relies on the DB ordering and doesn't re-sort
    or take the first inserted)."""

    def test_returns_first_row_from_ordered_result(self):
        # Caller passes back the rows in DESC order; helper returns
        # the first. (Sort discipline lives in the SQL clause, asserted
        # in TestNormalPath.test_query_orders_promoted_at_desc.)
        sb = _SupabaseChain(
            rows=[
                {"cohort_name": "neutral"},  # would be most recent
                {"cohort_name": "aggressive"},
            ]
        )
        result = get_current_champion("user-1", sb)
        self.assertEqual(result, "neutral")

    def test_limit_one_in_query(self):
        sb = _SupabaseChain(rows=[{"cohort_name": "aggressive"}])
        get_current_champion("user-1", sb)
        limit_calls = [c for c in sb.calls if c[0] == "limit"]
        self.assertEqual(len(limit_calls), 1)
        self.assertEqual(limit_calls[0][1], 1)


class TestExceptionPath(unittest.TestCase):
    """DB raises → log warning + return aggressive (fail-closed for
    pipeline liveness; same defensive shape as fallback)."""

    def test_raises_returns_aggressive(self):
        sb = _SupabaseChain(raise_on_execute=ConnectionError("boom"))
        result = get_current_champion("user-1", sb)
        self.assertEqual(result, "aggressive")

    def test_raises_logs_warning_with_error_class(self):
        sb = _SupabaseChain(raise_on_execute=RuntimeError("simulated"))
        with self.assertLogs(
            "packages.quantum.policy_lab.champion", level="WARNING"
        ) as cm:
            get_current_champion("user-1", sb)
        combined = "\n".join(cm.output)
        self.assertIn("lookup failed", combined)
        self.assertIn("RuntimeError", combined)
        self.assertIn("falling back", combined)


class TestForkUsesPromotedCohort(unittest.TestCase):
    """Integration-shape test: fork.py:67 calls get_current_champion
    rather than hardcoding 'aggressive'. Verified via import-time
    inspection and source-level guards — the inline import in fork.py
    confirms the integration seam closure (#62a-D1)."""

    def test_fork_imports_get_current_champion(self):
        from packages.quantum.policy_lab import fork
        self.assertTrue(
            hasattr(fork, "get_current_champion"),
            "fork.py must import get_current_champion (the integration "
            "seam closure for #62a-D1).",
        )

    def test_fork_does_not_hardcode_cohort_name_assignment(self):
        """The pre-PR shape assigned `cohort_name = "aggressive"` inline
        in the tag-update payload. Post-PR uses a `champion_name`
        variable populated by the helper."""
        from pathlib import Path
        src = (
            Path(__file__).resolve().parent.parent
            / "policy_lab" / "fork.py"
        ).read_text(encoding="utf-8")
        # The dict literal `{"cohort_name": "aggressive",` was the
        # hardcoded shape; post-PR uses `{"cohort_name": champion_name,`.
        self.assertNotIn('"cohort_name": "aggressive"', src)
        self.assertIn('"cohort_name": champion_name', src)

    def test_fork_calls_get_current_champion_with_user_id(self):
        from pathlib import Path
        src = (
            Path(__file__).resolve().parent.parent
            / "policy_lab" / "fork.py"
        ).read_text(encoding="utf-8")
        self.assertIn("get_current_champion(user_id, supabase)", src)


if __name__ == "__main__":
    unittest.main()
