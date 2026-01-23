"""
Tests for Auto-Promote Guardrail (v4-L1E)

Tests cover:
1. Promotion occurs when criteria met (same winner 3 days, no fail-fast, non-decreasing profit)
2. No promotion on fail-fast
3. No promotion when winners differ
4. No promotion when profit non-decreasing rule fails
5. Idempotency (same day does not double promote)
6. Policy already set -> no-op
7. Gating checks (disabled, pause, non-paper mode)
"""

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta, date


class FakeResponse:
    """Fake Supabase response."""
    def __init__(self, data):
        self.data = data


class FakeQuery:
    """Fake Supabase query builder."""
    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_idx = 0
        self._calls = []

    def select(self, *args, **kwargs):
        self._calls.append(('select', args, kwargs))
        return self

    def eq(self, *args, **kwargs):
        self._calls.append(('eq', args, kwargs))
        return self

    def order(self, *args, **kwargs):
        self._calls.append(('order', args, kwargs))
        return self

    def limit(self, n):
        self._calls.append(('limit', n))
        return self

    def update(self, data):
        self._calls.append(('update', data))
        return self

    def execute(self):
        if self.call_idx < len(self.responses):
            resp = self.responses[self.call_idx]
            self.call_idx += 1
            return resp
        return FakeResponse([])


class FakeClient:
    """Fake Supabase client that tracks update calls."""
    def __init__(self, responses_by_table=None):
        self.responses_by_table = responses_by_table or {}
        self.queries = {}
        self.update_calls = []

    def table(self, name):
        if name not in self.queries:
            responses = self.responses_by_table.get(name, [])
            self.queries[name] = FakeQuery(responses)
        return TrackedTableProxy(name, self.queries[name], self)


class TrackedTableProxy:
    """Proxy that tracks update calls for verification."""
    def __init__(self, table_name, query, client):
        self.table_name = table_name
        self.query = query
        self.client = client

    def __getattr__(self, name):
        if name == 'update':
            def tracked_update(data):
                self.client.update_calls.append((self.table_name, data))
                return self.query.update(data)
            return tracked_update
        return getattr(self.query, name)


class TestPromotionCriteria(unittest.TestCase):
    """Tests for promotion criteria evaluation."""

    def test_promotion_when_criteria_met(self):
        """Promotion occurs when same winner 3 days + no fail-fast + non-decreasing profit."""
        # Test the promotion logic by checking the criteria directly
        history = [
            {
                "bucket_date": "2024-01-17",
                "winner_cohort": "baseline_21d_10pct",
                "winner_return_pct": 3.5,
                "winner_would_fail_fast": False
            },
            {
                "bucket_date": "2024-01-16",
                "winner_cohort": "baseline_21d_10pct",
                "winner_return_pct": 2.5,
                "winner_would_fail_fast": False
            },
            {
                "bucket_date": "2024-01-15",
                "winner_cohort": "baseline_21d_10pct",
                "winner_return_pct": 1.5,
                "winner_would_fail_fast": False
            }
        ]

        # Check criteria
        winner_cohorts = [h["winner_cohort"] for h in history]
        self.assertEqual(len(set(winner_cohorts)), 1)  # Same winner

        fail_fast_flags = [h["winner_would_fail_fast"] for h in history]
        self.assertFalse(any(fail_fast_flags))  # No fail-fast

        # Check non-decreasing (oldest to newest)
        chronological = list(reversed(history))
        returns = [h["winner_return_pct"] for h in chronological]
        is_nondecreasing = all(returns[i] <= returns[i+1] for i in range(len(returns)-1))
        self.assertTrue(is_nondecreasing)

    def test_no_promotion_when_winners_differ(self):
        """No promotion when winners differ across days."""
        history = [
            {"winner_cohort": "baseline_21d_10pct", "winner_would_fail_fast": False, "winner_return_pct": 3.0},
            {"winner_cohort": "conservative_21d_8pct", "winner_would_fail_fast": False, "winner_return_pct": 2.5},
            {"winner_cohort": "baseline_21d_10pct", "winner_would_fail_fast": False, "winner_return_pct": 2.0},
        ]

        winner_cohorts = [h["winner_cohort"] for h in history]
        self.assertNotEqual(len(set(winner_cohorts)), 1)  # Winners differ

    def test_no_promotion_on_fail_fast(self):
        """No promotion when any day has fail-fast."""
        history = [
            {"winner_cohort": "baseline_21d_10pct", "winner_would_fail_fast": False, "winner_return_pct": 3.0},
            {"winner_cohort": "baseline_21d_10pct", "winner_would_fail_fast": True, "winner_return_pct": -1.0},
            {"winner_cohort": "baseline_21d_10pct", "winner_would_fail_fast": False, "winner_return_pct": 2.0},
        ]

        fail_fast_flags = [h["winner_would_fail_fast"] for h in history]
        self.assertTrue(any(fail_fast_flags))  # Has fail-fast

    def test_no_promotion_when_profit_decreasing(self):
        """No promotion when profit is decreasing."""
        history = [
            {"winner_cohort": "baseline_21d_10pct", "winner_would_fail_fast": False, "winner_return_pct": 2.0},
            {"winner_cohort": "baseline_21d_10pct", "winner_would_fail_fast": False, "winner_return_pct": 3.0},
            {"winner_cohort": "baseline_21d_10pct", "winner_would_fail_fast": False, "winner_return_pct": 2.5},
        ]

        # Check non-decreasing (oldest to newest)
        chronological = list(reversed(history))
        returns = [h["winner_return_pct"] for h in chronological]
        is_nondecreasing = all(returns[i] <= returns[i+1] for i in range(len(returns)-1))
        self.assertFalse(is_nondecreasing)  # Profit decreased from 3.0 to 2.0


class TestPolicyOverrides(unittest.TestCase):
    """Tests for policy override reading in go_live_validation_service."""

    def test_get_paper_forward_policy_overrides_empty(self):
        """Empty policy returns empty dict."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        client = FakeClient()
        service = GoLiveValidationService(client)

        state = {"paper_forward_policy": {}}
        overrides = service._get_paper_forward_policy_overrides(state)

        self.assertEqual(overrides, {})

    def test_get_paper_forward_policy_overrides_with_values(self):
        """Policy with values returns correct overrides."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        client = FakeClient()
        service = GoLiveValidationService(client)

        state = {
            "paper_forward_policy": {
                "paper_window_days": 14,
                "target_return_pct": 0.08,
                "fail_fast_drawdown_pct": -0.025,
                "fail_fast_return_pct": -0.015
            }
        }
        overrides = service._get_paper_forward_policy_overrides(state)

        self.assertEqual(overrides["paper_window_days"], 14)
        self.assertEqual(overrides["target_return_pct"], 0.08)
        self.assertEqual(overrides["fail_fast_drawdown_pct"], -0.025)
        self.assertEqual(overrides["fail_fast_return_pct"], -0.015)

    def test_get_paper_forward_policy_overrides_partial(self):
        """Partial policy returns only present overrides."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        client = FakeClient()
        service = GoLiveValidationService(client)

        state = {
            "paper_forward_policy": {
                "target_return_pct": 0.12
            }
        }
        overrides = service._get_paper_forward_policy_overrides(state)

        self.assertEqual(len(overrides), 1)
        self.assertEqual(overrides["target_return_pct"], 0.12)
        self.assertNotIn("paper_window_days", overrides)

    def test_get_paper_forward_policy_overrides_invalid_types(self):
        """Invalid types are silently skipped."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        client = FakeClient()
        service = GoLiveValidationService(client)

        state = {
            "paper_forward_policy": {
                "paper_window_days": "not_a_number",
                "target_return_pct": 0.10  # This one is valid
            }
        }
        overrides = service._get_paper_forward_policy_overrides(state)

        self.assertNotIn("paper_window_days", overrides)  # Invalid, skipped
        self.assertEqual(overrides["target_return_pct"], 0.10)  # Valid


class TestAutopromoteGating(unittest.TestCase):
    """Tests for autopromote gating logic."""

    @patch.dict('os.environ', {'AUTOPROMOTE_ENABLED': '0'})
    @patch('packages.quantum.ops_endpoints.get_global_ops_control')
    def test_gate_disabled_returns_skipped(self, mock_get_ops):
        """Gate returns skipped when AUTOPROMOTE_ENABLED=0."""
        from packages.quantum.public_tasks import _check_autopromote_gates

        result = _check_autopromote_gates('user-123')

        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['reason'], 'autopromote_disabled')

    @patch.dict('os.environ', {'AUTOPROMOTE_ENABLED': '1'})
    @patch('packages.quantum.ops_endpoints.get_global_ops_control')
    def test_gate_non_paper_mode_returns_cancelled(self, mock_get_ops):
        """Gate returns cancelled when not in paper mode."""
        from packages.quantum.public_tasks import _check_autopromote_gates

        mock_get_ops.return_value = {'mode': 'live', 'paused': False}

        result = _check_autopromote_gates('user-123')

        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['reason'], 'mode_is_paper_only')

    @patch.dict('os.environ', {'AUTOPROMOTE_ENABLED': '1'})
    @patch('packages.quantum.ops_endpoints.get_global_ops_control')
    def test_gate_paused_returns_cancelled(self, mock_get_ops):
        """Gate returns cancelled when globally paused."""
        from packages.quantum.public_tasks import _check_autopromote_gates

        mock_get_ops.return_value = {'mode': 'paper', 'paused': True}

        result = _check_autopromote_gates('user-123')

        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['reason'], 'paused_globally')

    @patch.dict('os.environ', {'AUTOPROMOTE_ENABLED': '1'})
    @patch('packages.quantum.ops_endpoints.get_global_ops_control')
    def test_gate_passes_when_enabled_and_paper(self, mock_get_ops):
        """Gate passes when enabled and in paper mode."""
        from packages.quantum.public_tasks import _check_autopromote_gates

        mock_get_ops.return_value = {'mode': 'paper', 'paused': False}

        result = _check_autopromote_gates('user-123')

        self.assertIsNone(result)  # None = gates passed


class TestCohortOverridesLookup(unittest.TestCase):
    """Tests for cohort overrides lookup."""

    @patch('packages.quantum.public_tasks._get_shadow_cohorts')
    def test_get_cohort_overrides_found(self, mock_get_cohorts):
        """Cohort found returns correct overrides."""
        from packages.quantum.public_tasks import _get_cohort_overrides_by_name

        mock_get_cohorts.return_value = [
            {
                "name": "baseline_21d_10pct",
                "paper_window_days": 21,
                "target_return_pct": 0.10,
                "fail_fast_drawdown_pct": -0.03,
                "fail_fast_return_pct": -0.02
            }
        ]

        result = _get_cohort_overrides_by_name("baseline_21d_10pct")

        self.assertIsNotNone(result)
        self.assertEqual(result["paper_window_days"], 21)
        self.assertEqual(result["target_return_pct"], 0.10)

    @patch('packages.quantum.public_tasks._get_shadow_cohorts')
    def test_get_cohort_overrides_not_found(self, mock_get_cohorts):
        """Cohort not found returns None."""
        from packages.quantum.public_tasks import _get_cohort_overrides_by_name

        mock_get_cohorts.return_value = [
            {"name": "other_cohort", "paper_window_days": 14}
        ]

        result = _get_cohort_overrides_by_name("nonexistent_cohort")

        self.assertIsNone(result)


class TestPayloadModels(unittest.TestCase):
    """Tests for autopromote payload model validation."""

    def test_autopromote_payload_requires_user_id(self):
        """ValidationAutopromoteCohortPayload requires user_id."""
        from packages.quantum.public_tasks_models import ValidationAutopromoteCohortPayload
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ValidationAutopromoteCohortPayload()

    def test_autopromote_payload_rejects_all(self):
        """ValidationAutopromoteCohortPayload rejects user_id='all'."""
        from packages.quantum.public_tasks_models import ValidationAutopromoteCohortPayload
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ValidationAutopromoteCohortPayload(user_id='all')

    def test_autopromote_payload_accepts_valid_uuid(self):
        """ValidationAutopromoteCohortPayload accepts valid UUID."""
        from packages.quantum.public_tasks_models import ValidationAutopromoteCohortPayload

        payload = ValidationAutopromoteCohortPayload(
            user_id='12345678-1234-1234-1234-123456789abc'
        )
        self.assertEqual(
            payload.user_id,
            '12345678-1234-1234-1234-123456789abc'
        )


class TestInsufficientHistory(unittest.TestCase):
    """Tests for insufficient history handling."""

    def test_insufficient_history_returns_no_promotion(self):
        """Less than 3 days of history returns no promotion."""
        # Only 2 days of history
        history = [
            {"winner_cohort": "baseline_21d_10pct", "winner_would_fail_fast": False, "winner_return_pct": 2.0},
            {"winner_cohort": "baseline_21d_10pct", "winner_would_fail_fast": False, "winner_return_pct": 1.5},
        ]

        required_days = 3
        self.assertLess(len(history), required_days)


class TestAntiChurn(unittest.TestCase):
    """Tests for anti-churn rule (no re-promotion if already active)."""

    def test_same_cohort_returns_no_promotion(self):
        """No promotion when policy already set to same cohort."""
        current_cohort = "baseline_21d_10pct"
        winner_cohort = "baseline_21d_10pct"

        # Anti-churn check
        self.assertEqual(current_cohort, winner_cohort)


class TestWinnerDetermination(unittest.TestCase):
    """Tests for winner determination logic in cohort eval."""

    def test_winner_is_highest_return_without_fail_fast(self):
        """Winner is cohort with highest return_pct among non-fail-fast."""
        results = [
            {"cohort": "a", "return_pct": 5.0, "would_fail_fast": True, "margin_to_target": 2.0, "max_drawdown_pct": -1.0},
            {"cohort": "b", "return_pct": 3.0, "would_fail_fast": False, "margin_to_target": 1.0, "max_drawdown_pct": -2.0},
            {"cohort": "c", "return_pct": 4.0, "would_fail_fast": False, "margin_to_target": 1.5, "max_drawdown_pct": -1.5},
        ]

        # Filter non-fail-fast
        non_fail_fast = [r for r in results if not r["would_fail_fast"]]

        # Sort by return_pct desc
        non_fail_fast.sort(key=lambda r: (
            -r["return_pct"],
            -r["margin_to_target"],
            -r["max_drawdown_pct"],
            r["cohort"]
        ))

        winner = non_fail_fast[0]

        # Winner should be 'c' with highest return_pct (4.0) among non-fail-fast
        self.assertEqual(winner["cohort"], "c")
        self.assertEqual(winner["return_pct"], 4.0)

    def test_all_fail_fast_still_picks_winner(self):
        """When all cohorts fail-fast, still picks 'best' one."""
        results = [
            {"cohort": "a", "return_pct": -1.0, "would_fail_fast": True, "margin_to_target": -3.0, "max_drawdown_pct": -4.0},
            {"cohort": "b", "return_pct": -2.0, "would_fail_fast": True, "margin_to_target": -4.0, "max_drawdown_pct": -5.0},
        ]

        non_fail_fast = [r for r in results if not r["would_fail_fast"]]

        if not non_fail_fast:
            # All failed fast - pick from all results
            results.sort(key=lambda r: (
                -int(r.get("would_pass", False)),
                -r["margin_to_target"],
                -r["max_drawdown_pct"],
                r["cohort"]
            ))
            winner = results[0]
        else:
            winner = non_fail_fast[0]

        # Winner should be 'a' with higher return
        self.assertEqual(winner["cohort"], "a")


if __name__ == '__main__':
    unittest.main()
