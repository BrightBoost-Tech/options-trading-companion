"""
Tests for Shadow Checkpoints + Cohort Runner (v4-L1D)

Tests cover:
1. Shadow evaluation does not mutate streak state
2. Shadow evaluation returns correct fields (would_pass, target_return_now, etc.)
3. Cohort runner returns deterministic ordering
4. Cohort runner does not mutate state
5. Gating checks (disabled, pause, non-paper mode)
"""

import unittest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone, timedelta


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

    def gte(self, *args, **kwargs):
        self._calls.append(('gte', args, kwargs))
        return self

    def lte(self, *args, **kwargs):
        self._calls.append(('lte', args, kwargs))
        return self

    def order(self, *args, **kwargs):
        self._calls.append(('order', args, kwargs))
        return self

    def single(self):
        self._calls.append(('single',))
        return self

    def limit(self, n):
        self._calls.append(('limit', n))
        return self

    def insert(self, data):
        self._calls.append(('insert', data))
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
        self.insert_calls = []

    def table(self, name):
        if name not in self.queries:
            responses = self.responses_by_table.get(name, [])
            self.queries[name] = FakeQuery(responses)
        return TrackedTableProxy(name, self.queries[name], self)


class TrackedTableProxy:
    """Proxy that tracks update/insert calls for verification."""
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
        elif name == 'insert':
            def tracked_insert(data):
                self.client.insert_calls.append((self.table_name, data))
                return self.query.insert(data)
            return tracked_insert
        return getattr(self.query, name)


class TestShadowEvalNoStateMutation(unittest.TestCase):
    """Tests that shadow evaluation does NOT mutate v3_go_live_state."""

    def test_shadow_eval_does_not_update_state(self):
        """Shadow eval must NOT call update on v3_go_live_state."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        # Setup fake state
        state = {
            "user_id": "test-user-123",
            "paper_window_start": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
            "paper_window_end": (datetime.now(timezone.utc) + timedelta(days=11)).isoformat(),
            "paper_baseline_capital": 100000,
            "paper_consecutive_passes": 5,
            "paper_ready": False,
            "paper_window_days": 21,
            "paper_checkpoint_target": 10,
            "paper_fail_fast_triggered": False,
        }

        # Setup outcomes
        outcomes = [
            {"closed_at": datetime.now(timezone.utc).isoformat(), "pnl_realized": 500.0},
            {"closed_at": datetime.now(timezone.utc).isoformat(), "pnl_realized": 300.0},
        ]

        client = FakeClient({
            "v3_go_live_state": [FakeResponse(state)],
            "learning_trade_outcomes_v3": [FakeResponse(outcomes)],
            "v3_go_live_runs": [FakeResponse([])],
        })

        service = GoLiveValidationService(client)
        result = service.eval_paper_forward_checkpoint_shadow(
            user_id="test-user-123",
            cadence="intraday"
        )

        # Verify shadow tag is present
        self.assertTrue(result.get("shadow"))

        # Verify NO update calls were made to v3_go_live_state
        state_updates = [c for c in client.update_calls if c[0] == "v3_go_live_state"]
        self.assertEqual(
            len(state_updates), 0,
            f"Shadow eval must NOT update v3_go_live_state, but found {len(state_updates)} update calls"
        )

    def test_shadow_eval_does_not_reset_streak(self):
        """Shadow eval must NOT reset paper_consecutive_passes even on 'fail'."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        # State with existing streak
        state = {
            "user_id": "test-user-123",
            "paper_window_start": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
            "paper_window_end": (datetime.now(timezone.utc) + timedelta(days=11)).isoformat(),
            "paper_baseline_capital": 100000,
            "paper_consecutive_passes": 7,  # Has a streak
            "paper_ready": False,
            "paper_window_days": 21,
            "paper_checkpoint_target": 10,
        }

        # Negative outcomes that would normally trigger fail
        outcomes = [
            {"closed_at": datetime.now(timezone.utc).isoformat(), "pnl_realized": -5000.0},
        ]

        client = FakeClient({
            "v3_go_live_state": [FakeResponse(state)],
            "learning_trade_outcomes_v3": [FakeResponse(outcomes)],
            "v3_go_live_runs": [FakeResponse([])],
        })

        service = GoLiveValidationService(client)
        result = service.eval_paper_forward_checkpoint_shadow(
            user_id="test-user-123",
            cadence="intraday"
        )

        # Result should indicate a fail condition (would_fail_fast or below target)
        # The exact reason depends on thresholds, but it should not be "on_pace"
        reason = result.get("reason", "")
        self.assertTrue(
            reason != "on_pace" and reason is not None,
            f"Expected failure reason, got: {reason}"
        )

        # But NO state updates should have occurred
        state_updates = [c for c in client.update_calls if c[0] == "v3_go_live_state"]
        self.assertEqual(
            len(state_updates), 0,
            "Shadow eval must NOT update state even when would_fail_fast is True"
        )


class TestShadowEvalReturnsCorrectFields(unittest.TestCase):
    """Tests that shadow evaluation returns the required fields."""

    def test_shadow_eval_returns_required_fields(self):
        """Shadow eval must return would_pass, target_return_now, etc."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        state = {
            "user_id": "test-user-123",
            "paper_window_start": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
            "paper_window_end": (datetime.now(timezone.utc) + timedelta(days=11)).isoformat(),
            "paper_baseline_capital": 100000,
            "paper_consecutive_passes": 3,
            "paper_ready": False,
            "paper_window_days": 21,
            "paper_checkpoint_target": 10,
        }

        outcomes = [
            {"closed_at": datetime.now(timezone.utc).isoformat(), "pnl_realized": 1000.0},
        ]

        client = FakeClient({
            "v3_go_live_state": [FakeResponse(state)],
            "learning_trade_outcomes_v3": [FakeResponse(outcomes)],
            "v3_go_live_runs": [FakeResponse([])],
        })

        service = GoLiveValidationService(client)
        result = service.eval_paper_forward_checkpoint_shadow(
            user_id="test-user-123",
            cadence="intraday"
        )

        # Check required fields exist
        required_fields = [
            "status",
            "return_pct",
            "max_drawdown_pct",
            "progress",
            "target_return_now",
            "would_pass",
            "would_fail_fast",
            "reason",
            "shadow",
            "cadence",
        ]

        for field in required_fields:
            self.assertIn(
                field, result,
                f"Shadow eval must return '{field}' field"
            )

        # Verify shadow is True
        self.assertTrue(result["shadow"])

    def test_shadow_eval_with_overrides(self):
        """Shadow eval respects override thresholds."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        state = {
            "user_id": "test-user-123",
            "paper_window_start": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
            "paper_window_end": (datetime.now(timezone.utc) + timedelta(days=11)).isoformat(),
            "paper_baseline_capital": 100000,
            "paper_consecutive_passes": 3,
            "paper_window_days": 21,
        }

        outcomes = [
            {"closed_at": datetime.now(timezone.utc).isoformat(), "pnl_realized": 500.0},
        ]

        client = FakeClient({
            "v3_go_live_state": [FakeResponse(state)],
            "learning_trade_outcomes_v3": [FakeResponse(outcomes)],
            "v3_go_live_runs": [FakeResponse([])],
        })

        service = GoLiveValidationService(client)

        # Run with custom overrides
        result = service.eval_paper_forward_checkpoint_shadow(
            user_id="test-user-123",
            cadence="daily",
            cohort_name="test_cohort",
            overrides={
                "paper_window_days": 14,
                "target_return_pct": 0.05,
                "fail_fast_drawdown_pct": -0.02,
            }
        )

        # Verify cohort name is included
        self.assertEqual(result.get("cohort"), "test_cohort")

        # Verify thresholds in result
        thresholds = result.get("thresholds", {})
        self.assertEqual(thresholds.get("target_return_pct"), 5.0)
        self.assertEqual(thresholds.get("fail_fast_drawdown_pct"), -2.0)


class TestCohortRunnerDeterministicOrdering(unittest.TestCase):
    """Tests that cohort runner returns deterministically ordered results."""

    def test_cohort_results_ordered_correctly(self):
        """Results should be sorted by (would_pass desc, margin_to_target desc, max_drawdown_pct desc, cohort asc)."""
        # Test the sorting logic directly
        results = [
            {"cohort": "c1", "would_pass": False, "margin_to_target": 1.0, "max_drawdown_pct": -1.0},
            {"cohort": "c2", "would_pass": True, "margin_to_target": 0.5, "max_drawdown_pct": -2.0},
            {"cohort": "c3", "would_pass": True, "margin_to_target": 1.0, "max_drawdown_pct": -1.0},
            {"cohort": "c4", "would_pass": True, "margin_to_target": 1.0, "max_drawdown_pct": -0.5},
        ]

        # Apply the same sorting as in the task
        results.sort(key=lambda r: (
            -int(r["would_pass"]),  # True first
            -r["margin_to_target"],  # Higher margin first
            -r["max_drawdown_pct"],  # Less negative (closer to 0) first
            r["cohort"]  # Alphabetical tiebreaker
        ))

        # Expected order:
        # 1. c4: would_pass=True, margin=1.0, drawdown=-0.5 (least negative)
        # 2. c3: would_pass=True, margin=1.0, drawdown=-1.0
        # 3. c2: would_pass=True, margin=0.5, drawdown=-2.0
        # 4. c1: would_pass=False, margin=1.0, drawdown=-1.0

        self.assertEqual(results[0]["cohort"], "c4")
        self.assertEqual(results[1]["cohort"], "c3")
        self.assertEqual(results[2]["cohort"], "c2")
        self.assertEqual(results[3]["cohort"], "c1")

    def test_cohort_runner_no_state_mutation(self):
        """Cohort runner must not mutate v3_go_live_state for any cohort."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        state = {
            "user_id": "test-user-123",
            "paper_window_start": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
            "paper_window_end": (datetime.now(timezone.utc) + timedelta(days=11)).isoformat(),
            "paper_baseline_capital": 100000,
            "paper_consecutive_passes": 5,
            "paper_window_days": 21,
        }

        outcomes = [
            {"closed_at": datetime.now(timezone.utc).isoformat(), "pnl_realized": 500.0},
        ]

        client = FakeClient({
            "v3_go_live_state": [FakeResponse(state)] * 10,  # Multiple reads
            "learning_trade_outcomes_v3": [FakeResponse(outcomes)] * 10,
            "v3_go_live_runs": [FakeResponse([])] * 10,
        })

        service = GoLiveValidationService(client)

        # Run multiple cohort evaluations
        cohorts = [
            {"name": "cohort1", "target_return_pct": 0.10},
            {"name": "cohort2", "target_return_pct": 0.08},
            {"name": "cohort3", "target_return_pct": 0.05},
        ]

        for cohort in cohorts:
            service.eval_paper_forward_checkpoint_shadow(
                user_id="test-user-123",
                cadence="intraday",
                cohort_name=cohort["name"],
                overrides={"target_return_pct": cohort["target_return_pct"]}
            )

        # Verify NO update calls were made to v3_go_live_state
        state_updates = [c for c in client.update_calls if c[0] == "v3_go_live_state"]
        self.assertEqual(
            len(state_updates), 0,
            f"Cohort runner must NOT update v3_go_live_state, but found {len(state_updates)} calls"
        )


class TestShadowCheckpointGating(unittest.TestCase):
    """Tests for shadow checkpoint gating logic."""

    @patch.dict('os.environ', {'SHADOW_CHECKPOINT_ENABLED': '0'})
    @patch('packages.quantum.ops_endpoints.get_global_ops_control')
    def test_gate_disabled_returns_skipped(self, mock_get_ops):
        """Gate returns skipped when SHADOW_CHECKPOINT_ENABLED=0."""
        from packages.quantum.public_tasks import _check_shadow_checkpoint_gates

        result = _check_shadow_checkpoint_gates('user-123')

        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['reason'], 'shadow_disabled')

    @patch.dict('os.environ', {'SHADOW_CHECKPOINT_ENABLED': '1'})
    @patch('packages.quantum.ops_endpoints.get_global_ops_control')
    def test_gate_non_paper_mode_returns_cancelled(self, mock_get_ops):
        """Gate returns cancelled when not in paper mode."""
        from packages.quantum.public_tasks import _check_shadow_checkpoint_gates

        mock_get_ops.return_value = {'mode': 'live'}

        result = _check_shadow_checkpoint_gates('user-123')

        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['reason'], 'mode_is_paper_only')

    @patch.dict('os.environ', {'SHADOW_CHECKPOINT_ENABLED': '1'})
    @patch('packages.quantum.ops_endpoints.get_global_ops_control')
    def test_gate_passes_when_enabled_and_paper(self, mock_get_ops):
        """Gate passes when enabled and in paper mode."""
        from packages.quantum.public_tasks import _check_shadow_checkpoint_gates

        mock_get_ops.return_value = {'mode': 'paper'}

        result = _check_shadow_checkpoint_gates('user-123')

        self.assertIsNone(result)  # None = gates passed


class TestShadowIdempotencyKey(unittest.TestCase):
    """Tests for shadow idempotency key generation."""

    @patch('packages.quantum.public_tasks.datetime')
    def test_intraday_key_includes_hour(self, mock_datetime):
        """Intraday key includes hour component."""
        from packages.quantum.public_tasks import _validation_shadow_idempotency_key

        mock_now = MagicMock()
        mock_now.strftime.side_effect = lambda fmt: {
            "%Y-%m-%d-%H": "2024-01-15-14",
            "%Y-%m-%d": "2024-01-15"
        }.get(fmt, "")
        mock_datetime.now.return_value = mock_now

        key = _validation_shadow_idempotency_key('user-abc', 'intraday', 'baseline')

        self.assertEqual(key, '2024-01-15-14-shadow-baseline-user-abc')
        self.assertIn('shadow', key)  # Must include shadow to avoid collision

    @patch('packages.quantum.public_tasks.datetime')
    def test_daily_key_no_hour(self, mock_datetime):
        """Daily key does not include hour component."""
        from packages.quantum.public_tasks import _validation_shadow_idempotency_key

        mock_now = MagicMock()
        mock_now.strftime.side_effect = lambda fmt: {
            "%Y-%m-%d-%H": "2024-01-15-14",
            "%Y-%m-%d": "2024-01-15"
        }.get(fmt, "")
        mock_datetime.now.return_value = mock_now

        key = _validation_shadow_idempotency_key('user-xyz', 'daily', None)

        self.assertEqual(key, '2024-01-15-shadow-single-user-xyz')
        self.assertIn('shadow', key)


class TestShadowPayloadModels(unittest.TestCase):
    """Tests for shadow checkpoint payload model validation."""

    def test_shadow_eval_payload_requires_user_id(self):
        """ValidationShadowEvalPayload requires user_id."""
        from packages.quantum.public_tasks_models import ValidationShadowEvalPayload
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ValidationShadowEvalPayload()

    def test_shadow_eval_payload_rejects_all(self):
        """ValidationShadowEvalPayload rejects user_id='all'."""
        from packages.quantum.public_tasks_models import ValidationShadowEvalPayload
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ValidationShadowEvalPayload(user_id='all')

    def test_cohort_eval_payload_requires_user_id(self):
        """ValidationCohortEvalPayload requires user_id."""
        from packages.quantum.public_tasks_models import ValidationCohortEvalPayload
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ValidationCohortEvalPayload()

    def test_cohort_eval_payload_accepts_valid_uuid(self):
        """ValidationCohortEvalPayload accepts valid UUID."""
        from packages.quantum.public_tasks_models import ValidationCohortEvalPayload

        payload = ValidationCohortEvalPayload(
            user_id='12345678-1234-1234-1234-123456789abc'
        )
        self.assertEqual(
            payload.user_id,
            '12345678-1234-1234-1234-123456789abc'
        )


class TestDefaultCohorts(unittest.TestCase):
    """Tests for default cohort configuration."""

    def test_default_cohorts_loaded(self):
        """Default cohorts are available when env var not set."""
        from packages.quantum.public_tasks import DEFAULT_SHADOW_COHORTS

        self.assertIsInstance(DEFAULT_SHADOW_COHORTS, list)
        self.assertGreater(len(DEFAULT_SHADOW_COHORTS), 0)

        # Verify structure
        for cohort in DEFAULT_SHADOW_COHORTS:
            self.assertIn('name', cohort)
            self.assertIn('paper_window_days', cohort)
            self.assertIn('target_return_pct', cohort)

    @patch.dict('os.environ', {'SHADOW_COHORTS_JSON': '[]'})
    def test_get_shadow_cohorts_empty_falls_back(self):
        """Empty JSON falls back to defaults."""
        from packages.quantum.public_tasks import _get_shadow_cohorts, DEFAULT_SHADOW_COHORTS

        result = _get_shadow_cohorts()

        self.assertEqual(result, DEFAULT_SHADOW_COHORTS)

    @patch.dict('os.environ', {
        'SHADOW_COHORTS_JSON': '[{"name":"custom","paper_window_days":7,"target_return_pct":0.05}]'
    })
    def test_get_shadow_cohorts_parses_env(self):
        """Custom JSON is parsed correctly."""
        from packages.quantum.public_tasks import _get_shadow_cohorts

        result = _get_shadow_cohorts()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'custom')
        self.assertEqual(result[0]['paper_window_days'], 7)


class TestShadowLogging(unittest.TestCase):
    """Tests that shadow evaluation logs with shadow tag."""

    def test_shadow_eval_logs_with_tag(self):
        """Shadow eval should log run with shadow=True in details."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        state = {
            "user_id": "test-user-123",
            "paper_window_start": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
            "paper_window_end": (datetime.now(timezone.utc) + timedelta(days=11)).isoformat(),
            "paper_baseline_capital": 100000,
            "paper_consecutive_passes": 3,
            "paper_window_days": 21,
        }

        outcomes = [
            {"closed_at": datetime.now(timezone.utc).isoformat(), "pnl_realized": 500.0},
        ]

        client = FakeClient({
            "v3_go_live_state": [FakeResponse(state)],
            "learning_trade_outcomes_v3": [FakeResponse(outcomes)],
            "v3_go_live_runs": [FakeResponse([])],
        })

        service = GoLiveValidationService(client)
        service.eval_paper_forward_checkpoint_shadow(
            user_id="test-user-123",
            cadence="intraday",
            cohort_name="test_cohort"
        )

        # Verify insert was called on v3_go_live_runs
        runs_inserts = [c for c in client.insert_calls if c[0] == "v3_go_live_runs"]
        self.assertGreater(
            len(runs_inserts), 0,
            "Shadow eval should log run to v3_go_live_runs"
        )

        # Verify shadow tag in details
        if runs_inserts:
            insert_data = runs_inserts[0][1]
            self.assertEqual(insert_data.get("mode"), "paper_checkpoint_shadow")
            details = insert_data.get("details_json", {})
            self.assertTrue(details.get("shadow"))
            self.assertEqual(details.get("cohort"), "test_cohort")


if __name__ == '__main__':
    unittest.main()
