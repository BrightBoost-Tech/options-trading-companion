"""job_runs.status CHECK — 'partial' contract (ledgered latent HIGH, 2026-07-18).

Three closures around ONE finding: the F-A4-1 runner writes status='partial'
for a succeeded-with-errors run, but the live job_runs_status_check CHECK never
allowed it, so the write 23514-fails and is swallowed into a wrong retry.

  (a) TestMigrationFileContract  — parse the (UNAPPLIED) migration FILE: it
      drops+re-adds the SAME constraint name, preserves EVERY pre-existing
      status EXACTLY, adds ONLY 'partial', and touches nothing else.
  (b) TestPartialRoute           — drive the PRODUCTION entrypoint run_job_run
      end-to-end (real _classify_handler_return + real mark_partial_failure),
      inject the failure at ORIGIN (a handler that returns counts.errors>0),
      and assert the top-level truth: a status='partial' UPDATE is emitted; and
      — with the failure injected at the DB origin (a 23514 on 'partial', i.e.
      the pre-migration constraint) — the run is swallowed into a retry, which
      is exactly the harm the migration removes.
  (c) TestLiveStatusCoverage     — every DISTINCT status observed live is in the
      new allowlist (so the widened constraint rejects no existing row).

Doctrine: no source-string wiring; inject at the deepest callee, assert at the
top; never mock the function under test (mark_partial_failure / the classifier
run for real — only the DB boundary and the registry lookup are faked).
"""

import re
import unittest
from pathlib import Path
from unittest.mock import patch

_Q = Path(__file__).resolve().parent.parent            # packages/quantum
MIGRATION = (
    Path(__file__).resolve().parents[3]                # repo root
    / "supabase" / "migrations"
    / "20260718150000_job_runs_status_check_partial.sql"
)

# The six statuses the LIVE job_runs_status_check CHECK allowed BEFORE this
# migration (read verbatim 2026-07-18 from
#   pg_get_constraintdef('job_runs_status_check') =
#   CHECK (status = ANY (ARRAY['queued','running','succeeded',
#                              'failed_retryable','dead_lettered','cancelled'])) ).
# The migration must preserve every one of these unchanged.
PRE_EXISTING_ALLOWED = {
    "queued",
    "running",
    "succeeded",
    "failed_retryable",
    "dead_lettered",
    "cancelled",
}

# DISTINCT status values actually PRESENT in job_runs, observed 2026-07-18 via
#   SELECT status, COUNT(*) FROM job_runs GROUP BY status;
#   succeeded=14441, cancelled=66, dead_lettered=32, running=4, queued=1.
# (No 'partial' and no 'failed_retryable' rows exist yet — the finding is
#  latent.) Every one of these must remain valid under the widened constraint.
LIVE_OBSERVED_STATUSES = {
    "succeeded",
    "cancelled",
    "dead_lettered",
    "running",
    "queued",
}


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _sql_no_comments() -> str:
    return "\n".join(
        line for line in _sql().splitlines()
        if not line.strip().startswith("--")
    )


def _migration_allowed_statuses() -> set:
    """The status set inside the ADD CONSTRAINT ... CHECK (status IN (...))."""
    body = _sql_no_comments()
    m = re.search(r"CHECK\s*\(\s*status\s+IN\s*\((.*?)\)\s*\)", body, re.S | re.I)
    assert m is not None, "CHECK (status IN (...)) not found in migration"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


# --------------------------------------------------------------------------- #
# (a) migration file contract
# --------------------------------------------------------------------------- #
class TestMigrationFileContract(unittest.TestCase):
    def test_file_exists_with_expected_name(self):
        self.assertTrue(MIGRATION.is_file(), MIGRATION)

    def test_drops_and_readds_same_constraint_name(self):
        body = _sql_no_comments()
        self.assertRegex(
            body,
            r"ALTER TABLE\s+job_runs\s+DROP CONSTRAINT\s+IF EXISTS\s+job_runs_status_check",
        )
        self.assertRegex(
            body,
            r"ADD CONSTRAINT\s+job_runs_status_check",
        )

    def test_preserves_every_pre_existing_status(self):
        allowed = _migration_allowed_statuses()
        missing = PRE_EXISTING_ALLOWED - allowed
        self.assertEqual(missing, set(), f"migration dropped statuses: {missing}")

    def test_adds_partial(self):
        self.assertIn("partial", _migration_allowed_statuses())

    def test_adds_only_partial_nothing_else(self):
        # set-equal: exactly the pre-existing six plus 'partial'.
        self.assertEqual(
            _migration_allowed_statuses(),
            PRE_EXISTING_ALLOWED | {"partial"},
        )

    def test_no_other_ddl_only_job_runs_constraint(self):
        body = _sql_no_comments()
        # Every CREATE/ALTER TABLE targets only job_runs.
        for tbl in re.findall(
            r"(?:CREATE TABLE(?: IF NOT EXISTS)?|ALTER TABLE)\s+(\w+)", body, re.I
        ):
            self.assertEqual(tbl, "job_runs", f"unexpected table touched: {tbl}")
        # No table create/drop or data rewrite.
        for forbidden in ("CREATE TABLE", "DROP TABLE", "UPDATE ", "DELETE ", "INSERT "):
            self.assertNotIn(forbidden, body.upper(), forbidden)


# --------------------------------------------------------------------------- #
# (b) production route: run_job_run emits status='partial'
# --------------------------------------------------------------------------- #
_ROW = {
    "id": "jr-partial-1",
    "job_name": "test_partial_job",
    "status": "queued",
    "attempt": 0,
    "max_attempts": 5,
    "started_at": "2026-07-18T12:00:00+00:00",
    "payload": {},
}


def _succeeded_with_errors_handler(payload=None, ctx=None):
    """Failure injected at ORIGIN: the handler RAN to completion but reports
    failed units (counts.errors>0) — the exact shape the F-A4-1 classifier maps
    to a terminal 'partial'. Not a raise: a return."""
    return {"ok": True, "counts": {"errors": 2}, "processed": 5}


class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, client, name):
        self._c = client
        self._name = name
        self._mode = None
        self._payload = None

    def select(self, *a, **k):
        self._mode = "select"
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._mode == "update":
            status = (self._payload or {}).get("status")
            self._c.updates.append((self._name, dict(self._payload)))
            # Simulate the DB CHECK constraint at the origin: a forbidden status
            # raises 23514, exactly as the pre-migration constraint does.
            if status in self._c.reject_statuses:
                raise RuntimeError(
                    'new row for relation "job_runs" violates check constraint '
                    '"job_runs_status_check" (23514)'
                )
            return _Resp([{"id": self._c.row["id"]}])
        return _Resp([dict(self._c.row)])


class _FakeRpc:
    def __init__(self, client, name, params):
        self._c = client
        self._name = name
        self._params = params

    def execute(self):
        self._c.rpc_calls.append((self._name, self._params))
        return _Resp(None)


class _FakeClient:
    """In-memory stand-in for the Supabase admin client — the DB boundary only.
    Records every UPDATE payload and RPC call; optionally rejects a status set
    the way the CHECK constraint would."""

    def __init__(self, row, reject_statuses=None):
        self.row = row
        self.reject_statuses = set(reject_statuses or [])
        self.updates = []
        self.rpc_calls = []

    def table(self, name):
        return _FakeTable(self, name)

    def rpc(self, name, params):
        return _FakeRpc(self, name, params)


class TestPartialRoute(unittest.TestCase):
    def _drive(self, reject_statuses=None):
        fake = _FakeClient(_ROW, reject_statuses=reject_statuses)
        with patch(
            "packages.quantum.jobs.job_runs.create_supabase_admin_client",
            return_value=fake,
        ), patch(
            "packages.quantum.jobs.runner.discover_handlers",
            return_value={"test_partial_job": _succeeded_with_errors_handler},
        ):
            from packages.quantum.jobs.runner import run_job_run
            result = run_job_run({"job_run_id": "jr-partial-1"})
        return result, fake

    def test_route_emits_partial_status_update(self):
        # Fix applied (DB accepts 'partial'): the run terminates 'partial' and a
        # status='partial' UPDATE reaches the job_runs table.
        result, fake = self._drive(reject_statuses=None)
        self.assertEqual(result["status"], "partial")
        partial_updates = [
            p for (t, p) in fake.updates
            if t == "job_runs" and p.get("status") == "partial"
        ]
        self.assertEqual(
            len(partial_updates), 1,
            f"expected one status='partial' UPDATE, got {fake.updates}",
        )
        # A partial run must NOT be re-queued.
        self.assertEqual(fake.rpc_calls, [], "partial run must not requeue")

    def test_pre_migration_constraint_swallows_partial_into_retry(self):
        # DB rejects 'partial' (the pre-migration constraint). The production
        # route attempts the 'partial' UPDATE, the 23514 is swallowed by the
        # runner's generic except, and the run is wrongly re-queued — the exact
        # latent harm this migration removes.
        result, fake = self._drive(reject_statuses={"partial"})
        attempted_partial = [
            p for (t, p) in fake.updates
            if t == "job_runs" and p.get("status") == "partial"
        ]
        self.assertEqual(len(attempted_partial), 1, "route must attempt 'partial'")
        self.assertNotEqual(
            result["status"], "partial",
            "with the constraint forbidding 'partial', the run cannot terminate partial",
        )
        self.assertEqual(result["status"], "retryable")
        self.assertTrue(
            any(name == "requeue_job_run" for name, _ in fake.rpc_calls),
            "the swallowed 23514 wrongly re-queues the run",
        )


# --------------------------------------------------------------------------- #
# (c) live-observed statuses all survive the widened constraint
# --------------------------------------------------------------------------- #
class TestLiveStatusCoverage(unittest.TestCase):
    def test_every_live_status_is_allowed(self):
        allowed = _migration_allowed_statuses()
        for status in LIVE_OBSERVED_STATUSES:
            self.assertIn(
                status, allowed,
                f"live status {status!r} would be rejected by the new constraint",
            )

    def test_live_statuses_are_subset_of_pre_existing(self):
        # Sanity: nothing live was outside the old allowlist either (the widen
        # is purely additive, it never rescues an already-illegal live row).
        self.assertTrue(LIVE_OBSERVED_STATUSES <= PRE_EXISTING_ALLOWED)


if __name__ == "__main__":
    unittest.main()
