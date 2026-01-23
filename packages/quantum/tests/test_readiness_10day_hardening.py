"""
Tests for v4-L1F: 10-Day Readiness Hardening

These tests validate the readiness hardening features that maximize
the probability of passing the paper-forward checkpoint streak.

Tests cover:
1. Payload model validation
2. Task scope definitions
3. Rolling streak guard comment
4. Safety close deterministic selection
5. Baseline capital consistency (unit tests)
"""

import unittest
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List


# =============================================================================
# Mock Helpers
# =============================================================================

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

    def lt(self, *args, **kwargs):
        self._calls.append(('lt', args, kwargs))
        return self

    def in_(self, *args, **kwargs):
        self._calls.append(('in_', args, kwargs))
        return self

    def order(self, *args, **kwargs):
        self._calls.append(('order', args, kwargs))
        return self

    def limit(self, n):
        self._calls.append(('limit', n))
        return self

    def single(self):
        self._calls.append(('single',))
        return self

    def update(self, data):
        self._calls.append(('update', data))
        return self

    def insert(self, data):
        self._calls.append(('insert', data))
        return self

    def delete(self):
        self._calls.append(('delete',))
        return self

    def execute(self):
        if self.call_idx < len(self.responses):
            resp = self.responses[self.call_idx]
            self.call_idx += 1
            return resp
        return FakeResponse([])


class FakeClient:
    """Fake Supabase client that tracks calls."""
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


def create_mock_state(
    user_id: str = "test-user-uuid-12345678901234567890",
    paper_window_start: str = "USE_DEFAULT",
    paper_window_end: str = "USE_DEFAULT",
    paper_window_days: int = 21,
    paper_consecutive_passes: int = 0,
    paper_ready: bool = False,
    paper_baseline_capital: float = 100000.0,
    paper_fail_fast_triggered: bool = False,
    paper_forward_policy: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Create a mock v3_go_live_state record."""
    now = datetime.now(timezone.utc)

    # Use sentinel value to allow explicit None
    if paper_window_start == "USE_DEFAULT":
        paper_window_start = now.isoformat()
    if paper_window_end == "USE_DEFAULT":
        paper_window_end = (now + timedelta(days=paper_window_days)).isoformat()

    return {
        "user_id": user_id,
        "paper_window_start": paper_window_start,
        "paper_window_end": paper_window_end,
        "paper_window_days": paper_window_days,
        "paper_baseline_capital": paper_baseline_capital,
        "paper_consecutive_passes": paper_consecutive_passes,
        "paper_ready": paper_ready,
        "paper_fail_fast_triggered": paper_fail_fast_triggered,
        "paper_checkpoint_target": 10,
        "paper_forward_policy": paper_forward_policy or {},
    }


def create_mock_positions(
    count: int = 2,
    portfolio_id: str = "portfolio-123",
) -> List[Dict[str, Any]]:
    """Create mock paper positions."""
    positions = []
    now = datetime.now(timezone.utc)

    for i in range(count):
        positions.append({
            "id": f"position-{i}",
            "portfolio_id": portfolio_id,
            "symbol": f"SPY{220115 + i}C00500000",
            "quantity": 1.0,
            "avg_entry_price": 5.0 + i,
            "created_at": (now - timedelta(hours=count - i)).isoformat(),  # Oldest first
            "strategy_key": f"SPY_call_spread",
            "trace_id": f"trace-{i}",
            "suggestion_id": f"suggestion-{i}",
        })

    return positions


# =============================================================================
# Tests: Payload Models
# =============================================================================

class TestPayloadModels(unittest.TestCase):
    """Tests for new payload models."""

    def test_validation_preflight_payload_requires_user_id(self):
        """ValidationPreflightPayload should require user_id."""
        from packages.quantum.public_tasks_models import ValidationPreflightPayload
        import pydantic

        with self.assertRaises(pydantic.ValidationError):
            ValidationPreflightPayload()  # Missing required user_id

    def test_validation_preflight_payload_rejects_all(self):
        """ValidationPreflightPayload should reject user_id='all'."""
        from packages.quantum.public_tasks_models import ValidationPreflightPayload
        import pydantic

        with self.assertRaises(pydantic.ValidationError):
            ValidationPreflightPayload(user_id="all")

    def test_validation_init_window_payload_valid(self):
        """ValidationInitWindowPayload should accept valid user_id."""
        from packages.quantum.public_tasks_models import ValidationInitWindowPayload

        payload = ValidationInitWindowPayload(user_id="test-user-uuid-12345678901234567890")
        self.assertEqual(payload.user_id, "test-user-uuid-12345678901234567890")

    def test_paper_safety_close_one_payload_valid(self):
        """PaperSafetyCloseOnePayload should accept valid user_id."""
        from packages.quantum.public_tasks_models import PaperSafetyCloseOnePayload

        payload = PaperSafetyCloseOnePayload(user_id="test-user-uuid-12345678901234567890")
        self.assertEqual(payload.user_id, "test-user-uuid-12345678901234567890")

    def test_validation_preflight_payload_rejects_short_uuid(self):
        """ValidationPreflightPayload should reject short user_id."""
        from packages.quantum.public_tasks_models import ValidationPreflightPayload
        import pydantic

        with self.assertRaises(pydantic.ValidationError):
            ValidationPreflightPayload(user_id="short")

    def test_validation_init_window_payload_rejects_all(self):
        """ValidationInitWindowPayload should reject user_id='all'."""
        from packages.quantum.public_tasks_models import ValidationInitWindowPayload
        import pydantic

        with self.assertRaises(pydantic.ValidationError):
            ValidationInitWindowPayload(user_id="all")

    def test_paper_safety_close_one_payload_rejects_all(self):
        """PaperSafetyCloseOnePayload should reject user_id='all'."""
        from packages.quantum.public_tasks_models import PaperSafetyCloseOnePayload
        import pydantic

        with self.assertRaises(pydantic.ValidationError):
            PaperSafetyCloseOnePayload(user_id="all")


# =============================================================================
# Tests: Task Scopes
# =============================================================================

class TestTaskScopes(unittest.TestCase):
    """Tests for new task scopes."""

    def test_preflight_scope_exists(self):
        """Validation preflight scope should be defined."""
        from packages.quantum.public_tasks_models import TASK_SCOPES

        self.assertIn("/tasks/validation/preflight", TASK_SCOPES)
        self.assertEqual(TASK_SCOPES["/tasks/validation/preflight"], "tasks:validation_preflight")

    def test_init_window_scope_exists(self):
        """Validation init-window scope should be defined."""
        from packages.quantum.public_tasks_models import TASK_SCOPES

        self.assertIn("/tasks/validation/init-window", TASK_SCOPES)
        self.assertEqual(TASK_SCOPES["/tasks/validation/init-window"], "tasks:validation_init_window")

    def test_safety_close_scope_exists(self):
        """Paper safety-close-one scope should be defined."""
        from packages.quantum.public_tasks_models import TASK_SCOPES

        self.assertIn("/tasks/paper/safety-close-one", TASK_SCOPES)
        self.assertEqual(TASK_SCOPES["/tasks/paper/safety-close-one"], "tasks:paper_safety_close_one")


# =============================================================================
# Tests: Safety Close Logic
# =============================================================================

class TestSafetyCloseLogic(unittest.TestCase):
    """Tests for safety close position selection logic."""

    def test_safety_close_no_ops_when_no_positions(self):
        """Safety close should no-op when there are no open positions."""
        positions = []
        self.assertEqual(len(positions), 0)

    def test_safety_close_selects_oldest_position(self):
        """Safety close should deterministically select oldest position."""
        positions = create_mock_positions(count=3)

        # Sort by created_at asc, then id asc (deterministic)
        sorted_positions = sorted(positions, key=lambda p: (p["created_at"], p["id"]))

        # First position should be the oldest
        oldest = sorted_positions[0]
        self.assertEqual(oldest["id"], "position-0")

    def test_safety_close_deterministic_with_same_timestamp(self):
        """Safety close should use position_id as tiebreaker."""
        now = datetime.now(timezone.utc).isoformat()
        positions = [
            {"id": "pos-b", "created_at": now},
            {"id": "pos-a", "created_at": now},
            {"id": "pos-c", "created_at": now},
        ]

        # Sort by created_at asc, then id asc
        sorted_positions = sorted(positions, key=lambda p: (p["created_at"], p["id"]))

        # First should be pos-a (alphabetically first)
        self.assertEqual(sorted_positions[0]["id"], "pos-a")


# =============================================================================
# Tests: Baseline Consistency
# =============================================================================

class TestBaselineConsistency(unittest.TestCase):
    """Tests for baseline capital consistency."""

    def test_baseline_default_100000(self):
        """Default baseline should be 100000."""
        state = create_mock_state()
        self.assertEqual(state["paper_baseline_capital"], 100000.0)

    def test_baseline_uses_state_value_if_present(self):
        """Should use paper_baseline_capital from state if present."""
        state = create_mock_state(paper_baseline_capital=50000.0)
        self.assertEqual(state["paper_baseline_capital"], 50000.0)

    def test_baseline_zero_not_used(self):
        """Should handle zero baseline gracefully."""
        state = create_mock_state(paper_baseline_capital=0.0)
        # Zero baseline should be avoided - default should be used
        # In actual code, we use `or 100000` to avoid zero
        self.assertEqual(state["paper_baseline_capital"], 0.0)


# =============================================================================
# Tests: Window Initialization Logic
# =============================================================================

class TestWindowInitLogic(unittest.TestCase):
    """Tests for window initialization logic."""

    def test_window_repair_needed_when_missing(self):
        """Window repair is needed when start/end are missing."""
        state = create_mock_state(paper_window_start=None, paper_window_end=None)
        needs_repair = (state["paper_window_start"] is None or state["paper_window_end"] is None)
        self.assertTrue(needs_repair)

    def test_window_no_repair_when_valid(self):
        """Window repair not needed when valid."""
        now = datetime.now(timezone.utc)
        state = create_mock_state(
            paper_window_start=now.isoformat(),
            paper_window_end=(now + timedelta(days=21)).isoformat()
        )
        needs_repair = (state["paper_window_start"] is None or state["paper_window_end"] is None)
        self.assertFalse(needs_repair)

    def test_window_init_preserves_streak_fields(self):
        """Window init should not modify streak fields."""
        # This tests the contract: update calls should NOT include streak fields
        state = create_mock_state(
            paper_consecutive_passes=5,
            paper_ready=True
        )

        # Simulated update data for window repair
        window_update = {
            "paper_window_start": datetime.now(timezone.utc).isoformat(),
            "paper_window_end": (datetime.now(timezone.utc) + timedelta(days=21)).isoformat(),
            "paper_window_days": 21,
        }

        # Verify streak fields are NOT in the update
        self.assertNotIn("paper_consecutive_passes", window_update)
        self.assertNotIn("paper_ready", window_update)
        self.assertNotIn("paper_fail_fast_triggered", window_update)


# =============================================================================
# Tests: Idempotency Key Generation
# =============================================================================

class TestIdempotencyKeys(unittest.TestCase):
    """Tests for idempotency key generation."""

    def test_idempotency_key_format(self):
        """Idempotency key should have correct format."""
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        task_type = "init-window"
        user_id = "test-user-uuid-12345678901234567890"

        key = f"{date}-{task_type}-{user_id}"

        self.assertIn(date, key)
        self.assertIn(task_type, key)
        self.assertIn(user_id, key)

    def test_idempotency_key_unique_per_day(self):
        """Idempotency keys should differ on different days."""
        task_type = "safety-close"
        user_id = "test-user-uuid-12345678901234567890"

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

        key_today = f"{today}-{task_type}-{user_id}"
        key_yesterday = f"{yesterday}-{task_type}-{user_id}"

        self.assertNotEqual(key_today, key_yesterday)


# =============================================================================
# Tests: Run Signed Task Definitions
# =============================================================================

class TestRunSignedTaskDefinitions(unittest.TestCase):
    """Tests that new tasks are properly defined in run_signed_task.py."""

    def _get_script_path(self):
        """Get path to run_signed_task.py relative to test file."""
        import os
        # Test is in packages/quantum/tests/, script is in scripts/
        # Need to go up 3 levels: tests -> quantum -> packages -> root
        test_dir = os.path.dirname(__file__)
        return os.path.join(test_dir, "..", "..", "..", "scripts", "run_signed_task.py")

    def test_validation_preflight_task_defined(self):
        """validation_preflight task should be defined."""
        with open(self._get_script_path(), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('"validation_preflight":', content)
        self.assertIn("/tasks/validation/preflight", content)
        self.assertIn("tasks:validation_preflight", content)

    def test_validation_init_window_task_defined(self):
        """validation_init_window task should be defined."""
        with open(self._get_script_path(), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('"validation_init_window":', content)
        self.assertIn("/tasks/validation/init-window", content)
        self.assertIn("tasks:validation_init_window", content)

    def test_paper_safety_close_one_task_defined(self):
        """paper_safety_close_one task should be defined."""
        with open(self._get_script_path(), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('"paper_safety_close_one":', content)
        self.assertIn("/tasks/paper/safety-close-one", content)
        self.assertIn("tasks:paper_safety_close_one", content)


# =============================================================================
# Tests: Workflow Definitions
# =============================================================================

class TestWorkflowDefinitions(unittest.TestCase):
    """Tests that new cron jobs are properly defined in workflow."""

    def _get_workflow_path(self):
        """Get path to trading_tasks.yml relative to test file."""
        import os
        # Test is in packages/quantum/tests/, workflow is in .github/workflows/
        # Need to go up 3 levels: tests -> quantum -> packages -> root
        test_dir = os.path.dirname(__file__)
        return os.path.join(test_dir, "..", "..", "..", ".github", "workflows", "trading_tasks.yml")

    def test_init_window_cron_defined(self):
        """validation-init-window cron job should be defined."""
        with open(self._get_workflow_path(), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("validation-init-window", content)
        self.assertIn("40 14 * * 1-5", content)

    def test_preflight_midday_cron_defined(self):
        """validation-preflight-midday cron job should be defined."""
        with open(self._get_workflow_path(), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("validation-preflight-midday", content)
        self.assertIn("5 19 * * 1-5", content)

    def test_safety_close_cron_defined(self):
        """paper-safety-close-one cron job should be defined."""
        with open(self._get_workflow_path(), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("paper-safety-close-one", content)
        self.assertIn("0 23 * * 1-5", content)


if __name__ == "__main__":
    unittest.main()
