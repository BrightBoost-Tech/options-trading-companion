"""Redaction / typing contract for the signed status-route projection
(``packages/quantum/jobs/job_status_projection.py``).

The projection is an ALLOWLIST: only curated columns + an allowlisted result
sub-summary are surfaced. The raw ``payload`` (may carry user_id / origin),
``error`` internals, lock fields, and ``idempotency_key`` must NEVER appear —
even if a handler stashes a secret in ``result``.
"""

import json
import unittest

from packages.quantum.jobs.job_status_projection import (
    TERMINAL_STATES,
    RESULT_SAFE_KEYS,
    project_job_status,
)


class TestProjectJobStatus(unittest.TestCase):

    def _full_row(self, **overrides):
        row = {
            "id": "11111111-1111-1111-1111-111111111111",
            "job_name": "paper_learning_ingest",
            "status": "succeeded",
            "created_at": "2026-07-20T00:00:00Z",
            "started_at": "2026-07-20T00:00:01Z",
            "finished_at": "2026-07-20T00:00:03Z",
            "completed_at": "2026-07-20T00:00:03Z",
            "duration_ms": 2000,
            "attempt": 1,
            "cancelled_reason": None,
            "cancelled_detail": None,
            # --- fields that must NEVER be surfaced ---
            "idempotency_key": "2026-07-20-paper-learning-all",
            "locked_by": "worker-7",
            "locked_at": "2026-07-20T00:00:01Z",
            "payload": {
                "user_id": "SECRET-USER-UUID",
                "origin": {"actor_class": "run_signed_task_cli"},
                "api_key": "sk-should-never-leak",
            },
            "error": {"trace": "sensitive traceback here", "token": "tok-leak"},
            "result": {
                "status": "ok",
                "counts": {"processed": 3, "skipped": 1},
                "reason": "done",
                "errors": ["boom"],
                "secret": "sk-inner-leak",
                "token": "tok-inner-leak",
                "internal_debug": "verbose internals",
            },
        }
        row.update(overrides)
        return row

    def test_allowlisted_fields_present(self):
        out = project_job_status(self._full_row())
        self.assertEqual(out["status"], "succeeded")
        self.assertTrue(out["terminal"])
        self.assertEqual(out["duration_ms"], 2000)
        self.assertEqual(out["attempt"], 1)
        self.assertEqual(out["result"]["counts"], {"processed": 3, "skipped": 1})
        self.assertEqual(out["result"]["reason"], "done")
        self.assertEqual(out["result"]["errors_count"], 1)
        self.assertEqual(out["reason"], "done")

    def test_withholds_payload_error_locks_and_secrets(self):
        out = project_job_status(self._full_row())
        # Whole-blob string scan: no sensitive value anywhere in the output.
        flat = json.dumps(out)
        for leaked in (
            "SECRET-USER-UUID",
            "sk-should-never-leak",
            "sensitive traceback here",
            "tok-leak",
            "sk-inner-leak",
            "tok-inner-leak",
            "verbose internals",
            "2026-07-20-paper-learning-all",  # idempotency_key
            "worker-7",  # locked_by
        ):
            self.assertNotIn(leaked, flat)
        # Structural: withheld top-level keys absent.
        for key in ("payload", "error", "idempotency_key", "locked_by", "locked_at"):
            self.assertNotIn(key, out)
        # Result summary carries ONLY allowlisted keys (+ derived errors_count).
        allowed = set(RESULT_SAFE_KEYS) | {"errors_count"}
        self.assertTrue(set(out["result"]).issubset(allowed))

    def test_running_is_not_terminal(self):
        out = project_job_status({"id": "x", "status": "running"})
        self.assertFalse(out["terminal"])
        self.assertEqual(out["status"], "running")

    def test_all_terminal_states_flagged(self):
        for state in TERMINAL_STATES:
            out = project_job_status({"id": "x", "status": state})
            self.assertTrue(out["terminal"], state)

    def test_reason_falls_back_to_cancelled_reason(self):
        out = project_job_status({
            "id": "x", "status": "cancelled",
            "cancelled_reason": "global_ops_pause",
            "cancelled_detail": "streak_breaker_tripped",
        })
        self.assertEqual(out["reason"], "global_ops_pause")
        self.assertEqual(out["cancelled_detail"], "streak_breaker_tripped")

    def test_blocked_reason_surfaced(self):
        out = project_job_status({
            "id": "x", "status": "failed",
            "result": {"blocked_reason": "ev_below_roundtrip_cost"},
        })
        self.assertEqual(out["reason"], "ev_below_roundtrip_cost")

    def test_result_summary_none_when_no_safe_keys(self):
        out = project_job_status({
            "id": "x", "status": "queued",
            "result": {"internal": "x", "payload_dump": "y"},
        })
        self.assertIsNone(out["result"])

    def test_finished_at_prefers_finished_then_completed(self):
        only_completed = project_job_status({
            "id": "x", "status": "succeeded", "completed_at": "c"})
        self.assertEqual(only_completed["finished_at"], "c")
        both = project_job_status({
            "id": "x", "status": "succeeded", "finished_at": "f", "completed_at": "c"})
        self.assertEqual(both["finished_at"], "f")

    def test_non_dict_result_is_safe(self):
        out = project_job_status({"id": "x", "status": "succeeded", "result": None})
        self.assertIsNone(out["result"])
        out2 = project_job_status({"id": "x", "status": "succeeded", "result": "weird"})
        self.assertIsNone(out2["result"])


if __name__ == "__main__":
    unittest.main()
