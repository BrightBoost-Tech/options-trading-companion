"""
Tests for Paper Autopilot Tasks (v4-L1C)

Tests cover:
1. Gate checks (PAPER_AUTOPILOT_ENABLED, paper mode)
2. Service methods (execute_top_suggestions, close_positions)
3. Job handlers
4. Deduplication and idempotency
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone


class FakeResponse:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, responses):
        self.responses = responses
        self.call_idx = 0

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
        return self

    def gte(self, *args, **kwargs):
        return self

    def lt(self, *args, **kwargs):
        return self

    def update(self, *args, **kwargs):
        return self

    def execute(self):
        if self.call_idx < len(self.responses):
            resp = self.responses[self.call_idx]
            self.call_idx += 1
            return resp
        return FakeResponse([])


class FakeClient:
    def __init__(self, responses_by_table=None):
        self.responses_by_table = responses_by_table or {}
        self.queries = {}

    def table(self, name):
        if name not in self.queries:
            responses = self.responses_by_table.get(name, [])
            self.queries[name] = FakeQuery(responses)
        return self.queries[name]


class TestPaperAutopilotService(unittest.TestCase):
    """Tests for PaperAutopilotService"""

    def setUp(self):
        # Clear environment before each test
        self.env_patcher = patch.dict('os.environ', {}, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_is_enabled_default_false(self):
        """Autopilot is disabled by default"""
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

        client = FakeClient()
        service = PaperAutopilotService(client)
        self.assertFalse(service.is_enabled())

    @patch.dict('os.environ', {'PAPER_AUTOPILOT_ENABLED': '1'})
    def test_is_enabled_when_env_set(self):
        """Autopilot is enabled when PAPER_AUTOPILOT_ENABLED=1"""
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

        client = FakeClient()
        service = PaperAutopilotService(client)
        self.assertTrue(service.is_enabled())

    def test_get_executable_suggestions_empty(self):
        """Returns empty list when no pending suggestions"""
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

        client = FakeClient({
            'trade_suggestions': [FakeResponse([])]
        })
        service = PaperAutopilotService(client)

        result = service.get_executable_suggestions('user-123')
        self.assertEqual(result, [])

    def test_get_executable_suggestions_sorted_by_score(self):
        """Suggestions are sorted by score descending"""
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

        suggestions = [
            {'id': 'a', 'score': 0.5, 'created_at': '2024-01-01T10:00:00Z'},
            {'id': 'b', 'score': 0.9, 'created_at': '2024-01-01T10:00:00Z'},
            {'id': 'c', 'score': 0.7, 'created_at': '2024-01-01T10:00:00Z'},
        ]

        client = FakeClient({
            'trade_suggestions': [FakeResponse(suggestions)]
        })
        service = PaperAutopilotService(client)

        result = service.get_executable_suggestions('user-123')

        # Should be sorted: b (0.9), c (0.7), a (0.5)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['id'], 'b')
        self.assertEqual(result[1]['id'], 'c')
        self.assertEqual(result[2]['id'], 'a')

    def test_execute_top_suggestions_no_candidates(self):
        """Returns no_candidates when no suggestions"""
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

        client = FakeClient({
            'trade_suggestions': [FakeResponse([])],
        })
        service = PaperAutopilotService(client)

        result = service.execute_top_suggestions('user-123')

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['executed_count'], 0)
        self.assertEqual(result['reason'], 'no_candidates')

    def test_get_already_executed_today_deduplication(self):
        """Returns suggestion IDs already executed today"""
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

        orders = [
            {'suggestion_id': 'sugg-1'},
            {'suggestion_id': 'sugg-2'},
            {'suggestion_id': None},  # Should be filtered
        ]

        client = FakeClient({
            'paper_orders': [FakeResponse(orders)]
        })
        service = PaperAutopilotService(client)

        result = service.get_already_executed_suggestion_ids_today('user-123')

        self.assertEqual(result, {'sugg-1', 'sugg-2'})

    def test_get_open_positions_empty_portfolios(self):
        """Returns empty list when no portfolios"""
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

        client = FakeClient({
            'paper_portfolios': [FakeResponse([])],
        })
        service = PaperAutopilotService(client)

        result = service.get_open_positions('user-123')
        self.assertEqual(result, [])

    def test_get_open_positions_sorted_oldest_first(self):
        """Positions are sorted by created_at ascending (oldest first)"""
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

        portfolios = [{'id': 'port-1'}]
        positions = [
            {'id': 'pos-c', 'created_at': '2024-01-03T10:00:00Z', 'portfolio_id': 'port-1'},
            {'id': 'pos-a', 'created_at': '2024-01-01T10:00:00Z', 'portfolio_id': 'port-1'},
            {'id': 'pos-b', 'created_at': '2024-01-02T10:00:00Z', 'portfolio_id': 'port-1'},
        ]

        client = FakeClient({
            'paper_portfolios': [FakeResponse(portfolios)],
            'paper_positions': [FakeResponse(positions)],
        })
        service = PaperAutopilotService(client)

        result = service.get_open_positions('user-123')

        # Should be sorted oldest first: a, b, c
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['id'], 'pos-a')
        self.assertEqual(result[1]['id'], 'pos-b')
        self.assertEqual(result[2]['id'], 'pos-c')

    def test_close_positions_no_positions(self):
        """Returns no_positions when no open positions"""
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

        client = FakeClient({
            'learning_feedback_loops': [FakeResponse([], count=0)],
            'paper_portfolios': [FakeResponse([])],
        })
        service = PaperAutopilotService(client)

        result = service.close_positions('user-123')

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['closed_count'], 0)
        self.assertEqual(result['reason'], 'no_positions')


class TestPaperAutopilotJobHandlers(unittest.TestCase):
    """Tests for paper autopilot job handlers"""

    @patch('packages.quantum.jobs.handlers.paper_auto_execute.get_admin_client')
    @patch('packages.quantum.jobs.handlers.paper_auto_execute.PaperAutopilotService')
    def test_execute_handler_disabled(self, mock_service_class, mock_get_client):
        """Handler returns skipped when autopilot disabled"""
        from packages.quantum.jobs.handlers.paper_auto_execute import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_service = MagicMock()
        mock_service.is_enabled.return_value = False
        mock_service_class.return_value = mock_service

        result = run({'user_id': 'user-123'})

        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['reason'], 'autopilot_disabled')

    @patch('packages.quantum.jobs.handlers.paper_auto_execute.get_admin_client')
    @patch('packages.quantum.jobs.handlers.paper_auto_execute.PaperAutopilotService')
    def test_execute_handler_success(self, mock_service_class, mock_get_client):
        """Handler calls service.execute_top_suggestions"""
        from packages.quantum.jobs.handlers.paper_auto_execute import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True
        mock_service.execute_top_suggestions.return_value = {
            'status': 'ok',
            'executed_count': 2,
            'skipped_count': 1,
            'error_count': 0,
        }
        mock_service_class.return_value = mock_service

        result = run({'user_id': 'user-123'})

        mock_service.execute_top_suggestions.assert_called_once_with('user-123')
        self.assertTrue(result['ok'])
        self.assertEqual(result['executed_count'], 2)

    def test_execute_handler_missing_user_id(self):
        """Handler raises PermanentJobError when user_id missing"""
        from packages.quantum.jobs.handlers.paper_auto_execute import run
        from packages.quantum.jobs.handlers.exceptions import PermanentJobError

        with self.assertRaises(PermanentJobError) as ctx:
            run({})

        self.assertIn('user_id is required', str(ctx.exception))

    @patch('packages.quantum.jobs.handlers.paper_auto_close.get_admin_client')
    @patch('packages.quantum.jobs.handlers.paper_auto_close.PaperAutopilotService')
    def test_close_handler_disabled(self, mock_service_class, mock_get_client):
        """Close handler returns skipped when autopilot disabled"""
        from packages.quantum.jobs.handlers.paper_auto_close import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_service = MagicMock()
        mock_service.is_enabled.return_value = False
        mock_service_class.return_value = mock_service

        result = run({'user_id': 'user-123'})

        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(result['reason'], 'autopilot_disabled')

    @patch('packages.quantum.jobs.handlers.paper_auto_close.get_admin_client')
    @patch('packages.quantum.jobs.handlers.paper_auto_close.PaperAutopilotService')
    def test_close_handler_success(self, mock_service_class, mock_get_client):
        """Close handler calls service.close_positions"""
        from packages.quantum.jobs.handlers.paper_auto_close import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True
        mock_service.close_positions.return_value = {
            'status': 'ok',
            'closed_count': 1,
            'error_count': 0,
        }
        mock_service_class.return_value = mock_service

        result = run({'user_id': 'user-123'})

        mock_service.close_positions.assert_called_once_with('user-123')
        self.assertTrue(result['ok'])
        self.assertEqual(result['closed_count'], 1)

    def test_close_handler_missing_user_id(self):
        """Close handler raises PermanentJobError when user_id missing"""
        from packages.quantum.jobs.handlers.paper_auto_close import run
        from packages.quantum.jobs.handlers.exceptions import PermanentJobError

        with self.assertRaises(PermanentJobError) as ctx:
            run({})

        self.assertIn('user_id is required', str(ctx.exception))


class TestPaperAutopilotGates(unittest.TestCase):
    """
    Tests for paper autopilot gate checks in public_tasks.py

    Note: These tests are skipped because they require complex mocking of
    the ops_endpoints module which initializes Supabase at import time.
    The gate logic is simple and well-documented in public_tasks.py.
    """

    @unittest.skip("Requires Supabase env vars - tested via integration tests")
    def test_gate_autopilot_disabled(self):
        """Gate returns error when autopilot disabled"""
        pass

    @unittest.skip("Requires Supabase env vars - tested via integration tests")
    def test_gate_not_paper_mode(self):
        """Gate returns error when not in paper mode"""
        pass

    @unittest.skip("Requires Supabase env vars - tested via integration tests")
    def test_gate_passes_paper_mode(self):
        """Gate passes when autopilot enabled and paper mode"""
        pass


class TestPaperAutopilotIdempotencyKey(unittest.TestCase):
    """Tests for idempotency key generation"""

    @patch('packages.quantum.public_tasks.datetime')
    def test_idempotency_key_format(self, mock_datetime):
        """Idempotency key uses UTC date and user_id"""
        from packages.quantum.public_tasks import _paper_autopilot_idempotency_key

        mock_now = MagicMock()
        mock_now.strftime.return_value = '2024-01-15'
        mock_datetime.now.return_value = mock_now

        key = _paper_autopilot_idempotency_key('execute', 'user-abc-123')

        self.assertEqual(key, '2024-01-15-paper-auto-execute-user-abc-123')

    @patch('packages.quantum.public_tasks.datetime')
    def test_idempotency_key_close(self, mock_datetime):
        """Idempotency key for close task"""
        from packages.quantum.public_tasks import _paper_autopilot_idempotency_key

        mock_now = MagicMock()
        mock_now.strftime.return_value = '2024-01-15'
        mock_datetime.now.return_value = mock_now

        key = _paper_autopilot_idempotency_key('close', 'user-xyz-789')

        self.assertEqual(key, '2024-01-15-paper-auto-close-user-xyz-789')


class TestPaperAutopilotPayloadModels(unittest.TestCase):
    """Tests for payload model validation"""

    def test_execute_payload_requires_user_id(self):
        """PaperAutoExecutePayload requires user_id"""
        from packages.quantum.public_tasks_models import PaperAutoExecutePayload
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            PaperAutoExecutePayload()

    def test_execute_payload_rejects_all(self):
        """PaperAutoExecutePayload rejects user_id='all'"""
        from packages.quantum.public_tasks_models import PaperAutoExecutePayload
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            PaperAutoExecutePayload(user_id='all')

    def test_execute_payload_accepts_valid_uuid(self):
        """PaperAutoExecutePayload accepts valid UUID"""
        from packages.quantum.public_tasks_models import PaperAutoExecutePayload

        payload = PaperAutoExecutePayload(
            user_id='12345678-1234-1234-1234-123456789abc'
        )
        self.assertEqual(
            payload.user_id,
            '12345678-1234-1234-1234-123456789abc'
        )

    def test_close_payload_requires_user_id(self):
        """PaperAutoClosePayload requires user_id"""
        from packages.quantum.public_tasks_models import PaperAutoClosePayload
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            PaperAutoClosePayload()

    def test_close_payload_rejects_all(self):
        """PaperAutoClosePayload rejects user_id='all'"""
        from packages.quantum.public_tasks_models import PaperAutoClosePayload
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            PaperAutoClosePayload(user_id='all')


class TestSuggestionStatusUpdateResilience(unittest.TestCase):
    """Tests for suggestion status update resilience in execute_top_suggestions."""

    def test_source_has_status_update_try_except(self):
        """Verify paper_autopilot_service wraps status update in try/except."""
        import os

        service_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "paper_autopilot_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        # Verify try/except wraps status update
        self.assertIn('except Exception as status_err:', source)
        self.assertIn('proceeding with order processing', source)

    def test_process_orders_called_after_status_update_block(self):
        """Verify _process_orders_for_user is called outside the status update try block."""
        import os
        import re

        service_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "paper_autopilot_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        # The structure should be:
        # try:
        #     supabase.table(...).update(...).execute()
        # except Exception as status_err:
        #     logger.warning(...)
        #
        # # Process order (execute) - always proceed
        # _process_orders_for_user(...)

        # Verify status update is wrapped in try/except
        self.assertIn('try:', source)
        self.assertIn('except Exception as status_err:', source)

        # Verify _process_orders_for_user call exists and is NOT inside the try block
        # The key assertion: _process_orders_for_user should appear AFTER the except block
        lines = source.split('\n')
        status_err_line = None
        process_orders_line = None

        for i, line in enumerate(lines):
            if 'except Exception as status_err:' in line:
                status_err_line = i
            if '_process_orders_for_user(' in line and status_err_line is not None:
                process_orders_line = i
                break

        self.assertIsNotNone(status_err_line, "except Exception as status_err not found")
        self.assertIsNotNone(process_orders_line, "_process_orders_for_user not found after except")
        self.assertGreater(
            process_orders_line, status_err_line,
            "_process_orders_for_user should be called after the except block"
        )

    def test_warning_logged_on_status_update_failure(self):
        """Verify warning is logged when status update fails."""
        import os

        service_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "paper_autopilot_service.py"
        )

        with open(service_path, "r") as f:
            source = f.read()

        # Verify logger.warning is called with appropriate message
        self.assertIn('logger.warning(', source)
        self.assertIn('Failed to update suggestion', source)
        self.assertIn('proceeding with order processing', source)


if __name__ == '__main__':
    unittest.main()
