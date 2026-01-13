import sys
import unittest
from unittest.mock import MagicMock
from datetime import datetime, date
from uuid import UUID, uuid4
from decimal import Decimal
from enum import Enum
import json

# Mock supabase BEFORE importing jobs.db
sys.modules['supabase'] = MagicMock()
sys.modules['supabase.client'] = MagicMock()

# Import the module to test
# We need to make sure we can import packages.quantum.jobs.db
# Assuming we run pytest from repo root, this import should work.
from packages.quantum.jobs import db as jobs_db
from pydantic import BaseModel

class DummyEnum(Enum):
    A = "value_a"
    B = "value_b"

class DummyModel(BaseModel):
    x: int
    y: str

class TestJobsDbJsonable(unittest.TestCase):
    def test_primitives(self):
        self.assertEqual(jobs_db._to_jsonable(1), 1)
        self.assertEqual(jobs_db._to_jsonable(1.5), 1.5)
        self.assertEqual(jobs_db._to_jsonable("string"), "string")
        self.assertEqual(jobs_db._to_jsonable(True), True)
        self.assertEqual(jobs_db._to_jsonable(None), None)

    def test_complex_types(self):
        dt = datetime(2023, 1, 1, 12, 0, 0)
        d = date(2023, 1, 1)
        u = uuid4()
        dec = Decimal("10.5")

        self.assertEqual(jobs_db._to_jsonable(dt), dt.isoformat())
        self.assertEqual(jobs_db._to_jsonable(d), d.isoformat())
        self.assertEqual(jobs_db._to_jsonable(u), str(u))
        self.assertEqual(jobs_db._to_jsonable(dec), 10.5)
        self.assertEqual(jobs_db._to_jsonable(DummyEnum.A), "value_a")

    def test_pydantic_model(self):
        m = DummyModel(x=1, y="test")
        self.assertEqual(jobs_db._to_jsonable(m), {"x": 1, "y": "test"})

    def test_nested_structures(self):
        u = uuid4()
        data = {
            "list": [1, datetime(2023, 1, 1), DummyModel(x=2, y="nested")],
            "tuple": (Decimal("1.1"),),
            "set": {DummyEnum.B},
            "uuid": u
        }

        converted = jobs_db._to_jsonable(data)

        # Check if serialization works
        json_str = json.dumps(converted)
        reloaded = json.loads(json_str)

        self.assertEqual(reloaded["list"][0], 1)
        self.assertTrue("2023-01-01" in reloaded["list"][1])
        self.assertEqual(reloaded["list"][2], {"x": 2, "y": "nested"})
        self.assertEqual(reloaded["tuple"][0], 1.1)
        # set becomes list, order unknown if multiple elements, but here only 1
        self.assertEqual(reloaded["set"][0], "value_b")
        self.assertEqual(reloaded["uuid"], str(u))

    def test_complete_job_run_serialization(self):
        mock_client = MagicMock()
        mock_execute = MagicMock()
        mock_client.rpc.return_value.execute = mock_execute

        job_id = "job-123"
        result = {
            "config": DummyModel(x=10, y="conf"),
            "timestamp": datetime(2023, 1, 1)
        }

        jobs_db.complete_job_run(mock_client, job_id, result)

        mock_client.rpc.assert_called_once()
        args, kwargs = mock_client.rpc.call_args
        rpc_name = args[0]
        rpc_params = args[1]

        self.assertEqual(rpc_name, 'complete_job_run')
        self.assertEqual(rpc_params['job_id'], job_id)

        # Verify serializability
        try:
            json.dumps(rpc_params['result'])
        except TypeError:
            self.fail("complete_job_run result is not JSON serializable")

    def test_requeue_job_run_serialization(self):
        mock_client = MagicMock()
        mock_execute = MagicMock()
        mock_client.rpc.return_value.execute = mock_execute

        job_id = "job-123"
        error = {"detail": Decimal("500.50"), "trace": [1, 2, 3]}
        run_after = "2023-01-02T00:00:00"

        jobs_db.requeue_job_run(mock_client, job_id, run_after, error)

        mock_client.rpc.assert_called_once()
        args, kwargs = mock_client.rpc.call_args
        rpc_params = args[1]

        self.assertEqual(rpc_params['job_id'], job_id)
        self.assertEqual(rpc_params['run_after'], run_after)
        try:
            json.dumps(rpc_params['error'])
        except TypeError:
            self.fail("requeue_job_run error is not JSON serializable")

    def test_dead_letter_job_run_serialization(self):
        mock_client = MagicMock()
        mock_execute = MagicMock()
        mock_client.rpc.return_value.execute = mock_execute

        job_id = "job-123"
        error = {"exception": Exception("test"), "enum": DummyEnum.A}

        jobs_db.dead_letter_job_run(mock_client, job_id, error)

        mock_client.rpc.assert_called_once()
        args, kwargs = mock_client.rpc.call_args
        rpc_params = args[1]

        # Exception should be converted to string fallback
        self.assertEqual(rpc_params['error']['exception'], "test")
        self.assertEqual(rpc_params['error']['enum'], "value_a")
