import unittest
from unittest.mock import MagicMock, patch
from packages.quantum.jobs.job_runs import JobRunStore

class FakeResponse:
    def __init__(self, data):
        self.data = data

class FakeQuery:
    def __init__(self, execute_responses):
        self.responses = execute_responses
        self.call_count = 0

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def maybe_single(self):
        return self

    def upsert(self, *args, **kwargs):
        return self

    def update(self, *args, **kwargs):
        return self

    def execute(self):
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return None

class FakeClient:
    def __init__(self, execute_responses):
        self.query = FakeQuery(execute_responses)

    def table(self, name):
        return self.query

class TestJobRunStoreCreateOrGet(unittest.TestCase):
    @patch('packages.quantum.jobs.job_runs.create_supabase_admin_client')
    def setUp(self, mock_create_client):
        # Mock client creation to avoid real env checks and connection
        mock_create_client.return_value = MagicMock()
        self.store = JobRunStore()

    def test_existing_select_returns_none_upsert_returns_row(self):
        # Scenario 1: existing.execute() returns None (failure), upsert works

        # Responses sequence:
        # 1. existing check -> None
        # 2. upsert -> FakeResponse(data=[row])

        expected_row = {"id": "123", "job_name": "test", "status": "queued"}

        mock_client = FakeClient([
            None, # existing check fails/returns None
            FakeResponse([expected_row]) # upsert succeeds
        ])
        self.store.client = mock_client

        result = self.store.create_or_get("test", "key", {})
        self.assertEqual(result, expected_row)

    def test_existing_select_returns_row(self):
        # Scenario 2: existing check returns data

        expected_row = {"id": "123", "job_name": "test", "status": "queued"}

        mock_client = FakeClient([
            FakeResponse(expected_row) # existing check succeeds
        ])
        self.store.client = mock_client

        result = self.store.create_or_get("test", "key", {})
        self.assertEqual(result, expected_row)

    def test_existing_none_upsert_none_retry_returns_row(self):
        # Scenario 3: existing -> None, upsert -> None (duplicate), retry -> row

        expected_row = {"id": "123", "job_name": "test", "status": "queued"}

        mock_client = FakeClient([
            None, # existing check fails
            None, # upsert returns None
            FakeResponse(expected_row) # retry succeeds
        ])
        self.store.client = mock_client

        result = self.store.create_or_get("test", "key", {})
        self.assertEqual(result, expected_row)

    def test_all_none_raises_runtime_error(self):
        # Scenario 4: all return None -> RuntimeError

        mock_client = FakeClient([
            None, # existing
            None, # upsert
            None  # retry
        ])
        self.store.client = mock_client

        with self.assertRaises(RuntimeError) as cm:
            self.store.create_or_get("test", "key", {})

        self.assertIn("Supabase returned None/empty response", str(cm.exception))

    def test_get_job_returns_data(self):
        expected_row = {"id": "123", "status": "queued"}
        mock_client = FakeClient([
            FakeResponse(expected_row)
        ])
        self.store.client = mock_client

        result = self.store.get_job("123")
        self.assertEqual(result, expected_row)

    def test_get_job_returns_none(self):
        mock_client = FakeClient([
            None
        ])
        self.store.client = mock_client

        result = self.store.get_job("123")
        self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main()
