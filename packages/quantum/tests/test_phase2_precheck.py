"""
Tests for packages/quantum/jobs/handlers/phase2_precheck.py — the
recurring verification handler that runs every 6 hours for 48 hours
post PR #6 deploy.

Covers the five behavioral paths specified in the micro-PR scope:
  (a) No-op path when observation window has expired (>48h post deploy)
  (b) Warning path when PR6_DEPLOY_TIMESTAMP env var is unset
  (c) Pass path when all 4 verification queries return zero
  (d) Critical path when any Q1/Q2/Q3 returns rows (hard-gate failure)
  (e) Metadata structure in written risk_alert matches spec

Also covers the parse-error and clock-skew warning paths to lock in
loud-failure behavior on bad config.
"""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from packages.quantum.jobs.handlers import phase2_precheck


# Trading account owner UUID (CLAUDE.md §Identity & Repo).
# Used as the USER_ID env var stand-in for happy-path tests and
# asserted in the metadata-structure test to verify the handler
# attaches risk_alerts rows to a real user (FK to users).
_TEST_USER_ID = "75ee12ad-b119-4f32-aeea-19b4ef55d587"


def _env(deploy_ts_iso=None, user_id=_TEST_USER_ID):
    """Build the env-var dict for tests. USER_ID defaults to the
    trading owner UUID so the handler's FK gate passes; individual
    tests override (e.g. pass user_id=None) to exercise the
    missing-USER_ID path."""
    env = {}
    if deploy_ts_iso is not None:
        env["PR6_DEPLOY_TIMESTAMP"] = deploy_ts_iso
    if user_id is not None:
        env["USER_ID"] = user_id
    return env


def _fresh_supabase_mock(query_counts=None):
    """Build a supabase mock that lets each verification query return
    a configurable row count.

    `query_counts` keys (all ints, default 0):
      q1  — legacy close_reason writes
      q2  — missing fill_source
      q3  — non-canonical close_reason
      q4  — close_path_anomaly critical alerts

    Also captures inserts into risk_alerts via the `inserts` list
    on the returned mock (`supabase.inserts`).
    """
    counts = {"q1": 0, "q2": 0, "q3": 0, "q4": 0}
    if query_counts:
        counts.update(query_counts)

    inserts: list = []

    supabase = MagicMock()

    def table_side_effect(name):
        chain = MagicMock()

        if name == "paper_positions":
            # Distinguish Q1/Q2/Q3 by chaining behavior. Simplest:
            # each invocation returns a result that we rotate through
            # via call order — but tests care about count per
            # variant, not strict ordering. So: every paper_positions
            # chain's .execute() checks the previously-called method
            # names to disambiguate.
            #
            # The 3 queries differ by the unique method chain:
            #   Q1: .in_("close_reason", LEGACY)
            #   Q2: .is_("fill_source", "null")
            #   Q3: .not_.in_("close_reason", CANONICAL)
            #
            # We capture which filter was applied and return the
            # matching count.
            flags = {"q1": False, "q2": False, "q3": False}

            def in_(col, values):
                if col == "close_reason" and "target_profit" in values:
                    flags["q1"] = True
                return chain

            def is_(col, val):
                if col == "fill_source":
                    flags["q2"] = True
                return chain

            not_obj = MagicMock()

            def not_in_(col, values):
                if col == "close_reason":
                    flags["q3"] = True
                return chain

            not_obj.in_.side_effect = not_in_
            chain.not_ = not_obj

            chain.in_.side_effect = in_
            chain.is_.side_effect = is_
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.gt.return_value = chain

            def exec_():
                if flags["q1"]:
                    n = counts["q1"]
                    data = [{"id": f"pp-{i}"} for i in range(n)]
                    return MagicMock(data=data)
                if flags["q2"]:
                    n = counts["q2"]
                    return MagicMock(data=[{"id": f"pp-{i}"} for i in range(n)])
                if flags["q3"]:
                    n = counts["q3"]
                    return MagicMock(data=[
                        {"id": f"pp-{i}", "close_reason": "typo_value"}
                        for i in range(n)
                    ])
                return MagicMock(data=[])

            chain.execute.side_effect = exec_

        elif name == "risk_alerts":
            # Q4 reads: select().eq(alert_type).eq(severity).gt(created_at).execute()
            # Writes: insert(payload).execute()
            select_chain = MagicMock()
            select_chain.eq.return_value = select_chain
            select_chain.gt.return_value = select_chain

            def select_exec():
                n = counts["q4"]
                return MagicMock(data=[{"id": f"ra-{i}"} for i in range(n)])

            select_chain.execute.side_effect = select_exec
            chain.select.return_value = select_chain

            def capture_insert(payload):
                inserts.append(payload)
                insert_chain = MagicMock()
                insert_chain.execute.return_value = MagicMock(data=None)
                return insert_chain

            chain.insert.side_effect = capture_insert

        return chain

    supabase.table.side_effect = table_side_effect
    supabase.inserts = inserts  # exposed to tests
    return supabase


class TestPhase2Precheck(unittest.TestCase):

    def _iso(self, dt: datetime) -> str:
        return dt.astimezone(timezone.utc).isoformat()

    # ── (b) Warning path: PR6_DEPLOY_TIMESTAMP unset ──────────────

    def test_missing_env_writes_warning_and_exits(self):
        """PR6_DEPLOY_TIMESTAMP unset but USER_ID set — should reach
        the deploy-timestamp gate and write a warning alert."""
        supabase = _fresh_supabase_mock()
        with patch.dict(os.environ, _env(deploy_ts_iso=None), clear=False):
            os.environ.pop("PR6_DEPLOY_TIMESTAMP", None)
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                result = phase2_precheck.run({})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "config_missing")
        self.assertEqual(len(supabase.inserts), 1)
        alert = supabase.inserts[0]
        self.assertEqual(alert["severity"], "warning")
        self.assertEqual(alert["alert_type"], "phase2_precheck")
        self.assertEqual(alert["metadata"]["status"], "config_missing")
        self.assertEqual(
            alert["metadata"]["verification_type"], "phase2_precheck"
        )

    def test_malformed_env_writes_warning(self):
        supabase = _fresh_supabase_mock()
        with patch.dict(os.environ, _env(deploy_ts_iso="not-a-date")):
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                result = phase2_precheck.run({})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "config_parse_error")
        self.assertEqual(len(supabase.inserts), 1)
        self.assertEqual(supabase.inserts[0]["severity"], "warning")

    def test_naive_timestamp_rejected(self):
        """ISO 8601 without tz info cannot be interpreted as UTC. Reject."""
        supabase = _fresh_supabase_mock()
        with patch.dict(os.environ, _env(deploy_ts_iso="2026-04-22T12:00:00")):
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                result = phase2_precheck.run({})
        self.assertEqual(result["status"], "config_parse_error")

    # ── (f) USER_ID gate — FK-constraint defense ───────────────────

    def test_missing_user_id_returns_noop_without_writing(self):
        """USER_ID unset → handler logs warning and exits before
        attempting any write. Prevents FK violation on risk_alerts."""
        supabase = _fresh_supabase_mock()
        deploy_ts = datetime.now(timezone.utc) - timedelta(hours=6)
        # Note: _env(user_id=None) omits USER_ID from the dict, but
        # os.environ may still carry it from the test venv. Clear
        # explicitly.
        with patch.dict(os.environ, {"PR6_DEPLOY_TIMESTAMP": self._iso(deploy_ts)}, clear=False):
            os.environ.pop("USER_ID", None)
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                result = phase2_precheck.run({})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "user_id_missing")
        # Critical: no alert row written. Silent exit via log would
        # be bad — but here we're asserting the FK-defense path exits
        # cleanly, and the warning surfaces in handler logs, not
        # risk_alerts.
        self.assertEqual(supabase.inserts, [])

    def test_empty_user_id_returns_noop_without_writing(self):
        """USER_ID set to empty string (deploy misconfiguration) —
        treated identically to missing."""
        supabase = _fresh_supabase_mock()
        deploy_ts = datetime.now(timezone.utc) - timedelta(hours=6)
        with patch.dict(os.environ, {
            "PR6_DEPLOY_TIMESTAMP": self._iso(deploy_ts),
            "USER_ID": "",
        }):
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                result = phase2_precheck.run({})

        self.assertEqual(result["status"], "user_id_missing")
        self.assertEqual(supabase.inserts, [])

    def test_whitespace_only_user_id_returns_noop(self):
        """Defensive: USER_ID='   ' (whitespace) is treated as unset."""
        supabase = _fresh_supabase_mock()
        deploy_ts = datetime.now(timezone.utc) - timedelta(hours=6)
        with patch.dict(os.environ, {
            "PR6_DEPLOY_TIMESTAMP": self._iso(deploy_ts),
            "USER_ID": "   ",
        }):
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                result = phase2_precheck.run({})

        self.assertEqual(result["status"], "user_id_missing")
        self.assertEqual(supabase.inserts, [])

    # ── (a) No-op path: observation window expired ────────────────

    def test_window_expired_returns_noop_no_alert(self):
        supabase = _fresh_supabase_mock()
        # Deploy 60h ago → past the 48h window.
        deploy_ts = datetime.now(timezone.utc) - timedelta(hours=60)
        with patch.dict(os.environ, _env(self._iso(deploy_ts))):
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                result = phase2_precheck.run({})

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "window_expired")
        # No-op: no risk_alert written.
        self.assertEqual(supabase.inserts, [])

    def test_future_timestamp_writes_clock_skew_warning(self):
        supabase = _fresh_supabase_mock()
        deploy_ts = datetime.now(timezone.utc) + timedelta(hours=4)
        with patch.dict(os.environ, _env(self._iso(deploy_ts))):
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                result = phase2_precheck.run({})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "clock_skew")
        self.assertEqual(len(supabase.inserts), 1)
        self.assertEqual(supabase.inserts[0]["severity"], "warning")

    # ── (c) Pass path: all 4 queries return zero ──────────────────

    def test_all_queries_zero_writes_info_alert(self):
        supabase = _fresh_supabase_mock()  # default: all counts 0
        deploy_ts = datetime.now(timezone.utc) - timedelta(hours=12)
        with patch.dict(os.environ, _env(self._iso(deploy_ts))):
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                result = phase2_precheck.run({})

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "all_checks_passed")
        self.assertEqual(len(supabase.inserts), 1)
        alert = supabase.inserts[0]
        self.assertEqual(alert["severity"], "info")
        self.assertTrue(alert["metadata"]["all_checks_passed"])

    def test_anomaly_only_writes_warning_not_critical(self):
        """Q1/Q2/Q3 clean + Q4 non-zero = warning (informational).
        Q4 alone does NOT hard-gate Phase 2; operator reviews the
        underlying alerts before deciding."""
        supabase = _fresh_supabase_mock({"q4": 3})
        deploy_ts = datetime.now(timezone.utc) - timedelta(hours=12)
        with patch.dict(os.environ, _env(self._iso(deploy_ts))):
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                result = phase2_precheck.run({})

        self.assertTrue(result["ok"])  # hard-gate passed
        self.assertEqual(result["status"], "anomalies_present")
        alert = supabase.inserts[0]
        self.assertEqual(alert["severity"], "warning")
        self.assertTrue(alert["metadata"]["all_checks_passed"])

    # ── (d) Critical path: Q1/Q2/Q3 non-zero ──────────────────────

    def test_q1_legacy_writes_fires_critical(self):
        supabase = _fresh_supabase_mock({"q1": 2})
        deploy_ts = datetime.now(timezone.utc) - timedelta(hours=12)
        with patch.dict(os.environ, _env(self._iso(deploy_ts))):
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                result = phase2_precheck.run({})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "hard_gate_failed")
        alert = supabase.inserts[0]
        self.assertEqual(alert["severity"], "critical")
        self.assertFalse(alert["metadata"]["all_checks_passed"])
        self.assertEqual(
            alert["metadata"]["query_results"]["q1_legacy_reason_writes"]["count"],
            2,
        )

    def test_q2_missing_fill_source_fires_critical(self):
        supabase = _fresh_supabase_mock({"q2": 1})
        deploy_ts = datetime.now(timezone.utc) - timedelta(hours=24)
        with patch.dict(os.environ, _env(self._iso(deploy_ts))):
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                result = phase2_precheck.run({})

        self.assertEqual(result["status"], "hard_gate_failed")
        self.assertEqual(supabase.inserts[0]["severity"], "critical")

    def test_q3_non_canonical_reason_fires_critical(self):
        supabase = _fresh_supabase_mock({"q3": 1})
        deploy_ts = datetime.now(timezone.utc) - timedelta(hours=24)
        with patch.dict(os.environ, _env(self._iso(deploy_ts))):
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                result = phase2_precheck.run({})

        self.assertEqual(result["status"], "hard_gate_failed")
        self.assertEqual(supabase.inserts[0]["severity"], "critical")

    # ── (e) Metadata structure ────────────────────────────────────

    def test_metadata_structure_matches_spec(self):
        """One full happy-path run with an explicit metadata audit
        to lock in the field names the Phase 2 PR description will
        reference. Also verifies risk_alerts.user_id matches the
        USER_ID env var (the FK-gate fix)."""
        supabase = _fresh_supabase_mock()
        deploy_ts = datetime.now(timezone.utc) - timedelta(hours=6)
        with patch.dict(os.environ, _env(self._iso(deploy_ts))):
            with patch(
                "packages.quantum.jobs.handlers.phase2_precheck.get_admin_client",
                return_value=supabase,
            ):
                phase2_precheck.run({})

        alert = supabase.inserts[0]
        self.assertEqual(alert["alert_type"], "phase2_precheck")
        self.assertEqual(alert["user_id"], _TEST_USER_ID)
        md = alert["metadata"]
        for field in (
            "verification_type",
            "status",
            "all_checks_passed",
            "run_timestamp",
            "deploy_timestamp",
            "hours_since_deploy",
            "query_results",
        ):
            self.assertIn(field, md, f"metadata missing {field!r}")
        # query_results carries all 4 sub-dicts with at minimum 'count'.
        for qkey in (
            "q1_legacy_reason_writes",
            "q2_missing_fill_source",
            "q3_non_canonical_reason",
            "q4_anomaly_alerts_in_window",
        ):
            self.assertIn(qkey, md["query_results"])
            self.assertIn("count", md["query_results"][qkey])

    def test_parse_iso_utc_accepts_z_and_offset(self):
        """_parse_iso_utc handles both 'Z' and '+00:00' variants.
        Lock in so the deploy-checklist field accepts either format."""
        z = phase2_precheck._parse_iso_utc("2026-04-22T12:00:00Z")
        off = phase2_precheck._parse_iso_utc("2026-04-22T12:00:00+00:00")
        self.assertEqual(z, off)
        self.assertEqual(z.tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()
