"""
Tests for the paired alert-write resilience + A4 silent-failure detector
(loss-protection runbook, Phase 1, 2026-06-30).

Two additive behaviors under test:

1a/1b ── alert() risk_alerts insert RETRY on transient stale-keepalive
    disconnects (httpx/httpcore RemoteProtocolError / "Server disconnected").
    - throws twice then succeeds → the write is RETRIED and the row lands
      (no loss);
    - throws forever → retries EXHAUST, the caller does NOT raise, a DISTINCT
      ``alert_lost_after_retries`` loss marker is logged, and the best-effort
      egress is still attempted (so a dropped row is at least visible).

1c ── ops-health A4 silent-failure detector: a job_runs row with
    status='succeeded' AND result.counts.errors > 0 (the masking class that
    hid paper_learning_ingest's 6-day silent errors) fires a
    ``job_succeeded_with_errors`` (severity=high) alert that egresses; a clean
    job (errors=0) fires nothing. Plus ``learning_feedback_loops`` registered
    in OUTPUT_FRESHNESS → stale flagged, fresh ok.

The webhook SENDER and the supabase CLIENT are always MOCKED — no real
network egress and no real DB writes ever occur.
"""

import logging
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from packages.quantum.observability import alerts
from packages.quantum.observability.alerts import alert
from packages.quantum.services import ops_health_service as ohs

_ALERTS_LOGGER = "packages.quantum.observability.alerts"
_SLEEP_PATH = "packages.quantum.observability.alerts.time.sleep"
_SENDER_PATH = "packages.quantum.services.ops_health_service.send_ops_alert_v2"
_HANDLER = "packages.quantum.jobs.handlers.ops_health_check"


def _disconnect(msg="Server disconnected without sending a response."):
    """A transient stale-keepalive disconnect (message-matched path)."""
    return Exception(msg)


# ── minimal chainable supabase stub ──────────────────────────────────────
class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def filter(self, *a, **k):
        # Filter-IGNORING by design: the durable-dedup identity match is
        # re-verified in Python inside find_prior_silent_failure_alert, so the
        # stub can return every seeded row and the production code still keys
        # correctly on (run_id, detector_version, failure_signature).
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Result(list(self._rows))


class _Client:
    def __init__(self, tables=None):
        self._tables = tables or {}

    def table(self, name):
        # NB: the SAME underlying list object is handed to each _Query, so a
        # test that appends to self._tables["risk_alerts"] (e.g. via a stateful
        # _alert side-effect) makes that row visible to the next poll's lookup.
        return _Query(self._tables.setdefault(name, []))


def _iso(dt):
    return dt.isoformat()


# =========================================================================
# 1a/1b — alert() insert retry on transient disconnects
# =========================================================================
class TestAlertInsertRetry(unittest.TestCase):
    def test_retries_on_disconnect_twice_then_succeeds_no_loss(self):
        """Insert raises a transient disconnect twice, then succeeds on the
        third attempt: the write is RETRIED and the row lands — no loss, no
        loss-marker logged."""
        supabase = MagicMock()
        execute = supabase.table.return_value.insert.return_value.execute
        execute.side_effect = [
            _disconnect(),
            _disconnect(),
            MagicMock(name="ok_result"),
        ]

        with patch(_SLEEP_PATH) as sleep, self.assertNoLogs(
            _ALERTS_LOGGER, level="ERROR"
        ):
            # Non-allowlisted type → no egress involved here.
            alert(
                supabase,
                alert_type="some_check_event",
                message="retry then succeed",
                severity="warning",
            )

        # Retried: three execute attempts (first + two retries).
        self.assertEqual(execute.call_count, 3)
        # Backoff was applied on each of the two retries.
        self.assertEqual(sleep.call_count, 2)
        # Row written on the surviving attempt (chain reached execute thrice).
        self.assertEqual(
            supabase.table.return_value.insert.return_value.execute.call_count,
            3,
        )

    def test_retries_exhausted_logs_loss_marker_egress_attempted_no_raise(self):
        """Insert raises forever: retries EXHAUST, the caller does NOT raise, a
        distinct ``alert_lost_after_retries`` marker is logged, AND the
        best-effort egress is still attempted for an allowlisted high/critical
        type (so a fully-dropped row is at least visible)."""
        supabase = MagicMock()
        supabase.table.return_value.insert.return_value.execute.side_effect = (
            _disconnect()
        )

        with patch(_SLEEP_PATH), patch(_SENDER_PATH) as sender, patch.dict(
            "os.environ", {"OPS_ALERT_WEBHOOK_URL": "https://hooks.test/x"}
        ), self.assertLogs(_ALERTS_LOGGER, level="ERROR") as cm:
            sender.return_value = {"sent": True, "webhook_sent": True}
            # MUST NOT raise.
            alert(
                supabase,
                alert_type="force_close",  # allowlisted → egress eligible
                message="brake fired but DB keepalive dropped",
                severity="critical",
                symbol="AAPL",
            )

        # Three attempts then give up.
        self.assertEqual(
            supabase.table.return_value.insert.return_value.execute.call_count,
            3,
        )
        # Distinct loss marker present (alongside the unchanged
        # alert_write_failed fallback).
        msgs = [r.getMessage() for r in cm.records]
        self.assertTrue(
            any("alert_lost_after_retries" in m for m in msgs),
            f"loss marker missing from {msgs}",
        )
        self.assertTrue(
            any("alert_write_failed" in m for m in msgs),
            "existing fallback should still fire",
        )
        # Egress still attempted despite the lost insert (1b).
        sender.assert_called_once()

    def test_non_transient_error_is_not_retried(self):
        """A non-transient error (e.g. a real PostgREST/schema failure) must
        NOT be retried — it falls straight through to the unchanged fallback
        with a single attempt and no loss marker."""
        supabase = MagicMock()
        supabase.table.return_value.insert.return_value.execute.side_effect = (
            RuntimeError("PGRST205 relation does not exist")
        )

        with patch(_SLEEP_PATH) as sleep, self.assertLogs(
            _ALERTS_LOGGER, level="ERROR"
        ) as cm:
            alert(
                supabase,
                alert_type="some_check_event",
                message="schema error",
                severity="warning",
            )

        # Exactly one attempt, no backoff sleeps.
        self.assertEqual(
            supabase.table.return_value.insert.return_value.execute.call_count,
            1,
        )
        self.assertEqual(sleep.call_count, 0)
        msgs = [r.getMessage() for r in cm.records]
        self.assertTrue(any("alert_write_failed" in m for m in msgs))
        # No retries attempted → no loss marker.
        self.assertFalse(any("alert_lost_after_retries" in m for m in msgs))

    def test_is_transient_disconnect_classifier(self):
        """Classifier matches RemoteProtocolError by class name and the message
        substrings; rejects unrelated errors and None."""

        class RemoteProtocolError(Exception):
            pass

        self.assertTrue(alerts._is_transient_disconnect(RemoteProtocolError()))
        self.assertTrue(
            alerts._is_transient_disconnect(Exception("Server disconnected"))
        )
        self.assertTrue(
            alerts._is_transient_disconnect(Exception("RemoteProtocol drop"))
        )
        self.assertFalse(
            alerts._is_transient_disconnect(ValueError("bad value"))
        )
        self.assertFalse(alerts._is_transient_disconnect(None))


# =========================================================================
# 1c — A4 silent-failure detector (service-level detection)
# =========================================================================
class TestSilentFailureDetection(unittest.TestCase):
    def _row(self, job_name, errors, status="succeeded", run_id="r"):
        return {
            "id": run_id,
            "job_name": job_name,
            "status": status,
            "finished_at": _iso(datetime.now(timezone.utc)),
            "result": {"ok": True, "counts": {"errors": errors}},
        }

    def test_succeeded_with_errors_is_an_offender(self):
        client = _Client(
            {
                "job_runs": [
                    self._row("paper_learning_ingest", 1, run_id="r1"),
                    self._row("calibration_update", 0, run_id="r2"),
                ]
            }
        )
        offenders = ohs.get_silent_job_failures(client)
        self.assertEqual(len(offenders), 1)
        self.assertEqual(offenders[0]["job_name"], "paper_learning_ingest")
        self.assertEqual(offenders[0]["error_count"], 1)
        self.assertEqual(offenders[0]["run_id"], "r1")

    def test_clean_jobs_yield_no_offenders(self):
        client = _Client(
            {
                "job_runs": [
                    self._row("paper_learning_ingest", 0),
                    self._row("calibration_update", 0),
                ]
            }
        )
        self.assertEqual(ohs.get_silent_job_failures(client), [])

    def test_missing_or_malformed_counts_skipped(self):
        client = _Client(
            {
                "job_runs": [
                    {"id": "a", "job_name": "j", "result": {"ok": True}},
                    {"id": "b", "job_name": "j", "result": None},
                    {
                        "id": "c",
                        "job_name": "j",
                        "result": {"counts": {"errors": "oops"}},
                    },
                ]
            }
        )
        self.assertEqual(ohs.get_silent_job_failures(client), [])

    def test_query_failure_is_swallowed(self):
        client = MagicMock()
        client.table.side_effect = RuntimeError("db down")
        # Must not raise — detector is best-effort.
        self.assertEqual(ohs.get_silent_job_failures(client), [])

    def test_new_alert_type_is_in_egress_allowlist(self):
        self.assertIn(
            "job_succeeded_with_errors", alerts._RISK_EGRESS_ALERT_TYPES
        )


# =========================================================================
# 1c — A4 detector wired through the ops_health_check handler (fires alert())
# =========================================================================
class TestSilentFailureHandlerWiring(unittest.TestCase):
    def _patched(self, stack, client):
        """Patch the heavy ops-health deps so only the silent-failure path is
        exercised, and return the mocked observability alert()."""
        fresh = SimpleNamespace(
            is_stale=False,
            as_of=None,
            age_seconds=None,
            universe_size=1,
            stale_symbols=[],
            source="MarketDataTruthLayer",
            reason="ok",
        )
        job_fresh = SimpleNamespace(
            is_stale=False,
            as_of=None,
            age_seconds=None,
            reason=None,
            source="job_runs",
        )
        stack.enter_context(
            patch(f"{_HANDLER}.get_admin_client", return_value=client)
        )
        stack.enter_context(
            patch(f"{_HANDLER}.build_freshness_universe", return_value=["SPY"])
        )
        stack.enter_context(
            patch(
                f"{_HANDLER}.compute_market_data_freshness", return_value=fresh
            )
        )
        stack.enter_context(
            patch(
                f"{_HANDLER}.compute_data_freshness", return_value=job_fresh
            )
        )
        stack.enter_context(
            patch(f"{_HANDLER}.get_expected_jobs", return_value=[])
        )
        stack.enter_context(
            patch(f"{_HANDLER}.get_output_freshness", return_value=[])
        )
        stack.enter_context(
            patch(f"{_HANDLER}.get_recent_failures", return_value=[])
        )
        stack.enter_context(
            patch(
                f"{_HANDLER}.should_suppress_alert", return_value=(False, None)
            )
        )
        stack.enter_context(
            patch(f"{_HANDLER}.get_suggestions_stats", return_value={})
        )
        stack.enter_context(
            patch(f"{_HANDLER}.get_integrity_stats", return_value={})
        )
        stack.enter_context(patch(f"{_HANDLER}.AuditLogService"))
        return stack.enter_context(patch(f"{_HANDLER}._alert"))

    def _job_run_row(self, errors, run_id="r1"):
        return {
            "id": run_id,
            "job_name": "paper_learning_ingest",
            "status": "succeeded",
            "finished_at": _iso(datetime.now(timezone.utc)),
            "result": {"ok": True, "counts": {"errors": errors}},
        }

    def test_offending_row_fires_high_alert(self):
        from packages.quantum.jobs.handlers import ops_health_check as handler

        client = _Client({"job_runs": [self._job_run_row(1)]})
        with ExitStack() as stack:
            mock_alert = self._patched(stack, client)
            result = handler.run({}, ctx=None)

        mock_alert.assert_called_once()
        kwargs = mock_alert.call_args.kwargs
        self.assertEqual(kwargs["alert_type"], "job_succeeded_with_errors")
        self.assertEqual(kwargs["severity"], "high")
        self.assertEqual(kwargs["metadata"]["job_name"], "paper_learning_ingest")
        self.assertEqual(kwargs["metadata"]["error_count"], 1)
        # The handler surfaces the issue: F-A4-1 moved the health signal from
        # `ok` (now always True — the CHECK ran) to `healthy`.
        self.assertFalse(result["healthy"])
        self.assertTrue(
            any("Silent failure" in i for i in result["issues_found"])
        )

    def test_clean_row_fires_no_silent_alert(self):
        from packages.quantum.jobs.handlers import ops_health_check as handler

        client = _Client({"job_runs": [self._job_run_row(0)]})
        with ExitStack() as stack:
            mock_alert = self._patched(stack, client)
            result = handler.run({}, ctx=None)

        mock_alert.assert_not_called()
        self.assertTrue(result["ok"])


# =========================================================================
# 1c — learning_feedback_loops registered in OUTPUT_FRESHNESS
# =========================================================================
class TestLearningOutputFreshness(unittest.TestCase):
    def _client(self, lfl_age_days):
        return _Client(
            {
                "calibration_adjustments": [
                    {
                        "computed_at": _iso(
                            datetime.now(timezone.utc) - timedelta(hours=20)
                        )
                    }
                ],
                "learning_feedback_loops": [
                    {
                        "created_at": _iso(
                            datetime.now(timezone.utc)
                            - timedelta(days=lfl_age_days)
                        )
                    }
                ],
            }
        )

    def _lfl(self, results):
        return next(
            o for o in results if o.table == "learning_feedback_loops"
        )

    def test_registered_in_output_freshness(self):
        self.assertTrue(
            any(t == "learning_feedback_loops" for t, _, _ in ohs.OUTPUT_FRESHNESS)
        )

    def test_stale_learning_output_flagged(self):
        # Default max age is 336h (14 days); 20 days old → stale.
        out = ohs.get_output_freshness(self._client(lfl_age_days=20))
        entry = self._lfl(out)
        self.assertEqual(entry.status, "stale")
        self.assertGreater(entry.age_hours, entry.max_age_hours)

    def test_fresh_learning_output_ok(self):
        out = ohs.get_output_freshness(self._client(lfl_age_days=1))
        entry = self._lfl(out)
        self.assertEqual(entry.status, "ok")


# =========================================================================
# Durable A4 re-fire dedup (2026-07-20): first emits, repeats suppressed-typed
# — driven END-TO-END through the ops_health_check handler with the failure
# injected at its data source (job_runs) and the prior state in risk_alerts.
# =========================================================================
def _patch_ops_health(stack, client):
    """Patch the heavy ops-health deps so ONLY the silent-failure path runs,
    returning the mocked observability alert(). Mirrors
    TestSilentFailureHandlerWiring._patched (the detector itself,
    get_silent_job_failures + find_prior_silent_failure_alert, is NOT patched —
    it reads the stub's job_runs / risk_alerts, so the failure is injected at
    its true origin)."""
    fresh = SimpleNamespace(
        is_stale=False, as_of=None, age_seconds=None, universe_size=1,
        stale_symbols=[], source="MarketDataTruthLayer", reason="ok",
    )
    job_fresh = SimpleNamespace(
        is_stale=False, as_of=None, age_seconds=None, reason=None,
        source="job_runs",
    )
    stack.enter_context(patch(f"{_HANDLER}.get_admin_client", return_value=client))
    stack.enter_context(
        patch(f"{_HANDLER}.build_freshness_universe", return_value=["SPY"])
    )
    stack.enter_context(
        patch(f"{_HANDLER}.compute_market_data_freshness", return_value=fresh)
    )
    stack.enter_context(
        patch(f"{_HANDLER}.compute_data_freshness", return_value=job_fresh)
    )
    stack.enter_context(patch(f"{_HANDLER}.get_expected_jobs", return_value=[]))
    stack.enter_context(patch(f"{_HANDLER}.get_output_freshness", return_value=[]))
    stack.enter_context(patch(f"{_HANDLER}.get_recent_failures", return_value=[]))
    stack.enter_context(
        patch(f"{_HANDLER}.should_suppress_alert", return_value=(False, None))
    )
    stack.enter_context(patch(f"{_HANDLER}.get_suggestions_stats", return_value={}))
    stack.enter_context(patch(f"{_HANDLER}.get_integrity_stats", return_value={}))
    stack.enter_context(patch(f"{_HANDLER}.AuditLogService"))
    return stack.enter_context(patch(f"{_HANDLER}._alert"))


def _job_run(errors, run_id="r1", job_name="paper_learning_ingest"):
    return {
        "id": run_id,
        "job_name": job_name,
        "status": "succeeded",
        "finished_at": _iso(datetime.now(timezone.utc)),
        "result": {"ok": True, "counts": {"errors": errors}},
    }


def _prior_alert_row(
    *, run_id, job_name="paper_learning_ingest", error_count=1,
    detector_version=None, failure_signature=None, alert_id="prior-1",
):
    """A durable risk_alerts row as it lives in the table. detector_version /
    failure_signature default to None to model a HISTORICAL row written before
    those fields existed (the real 6-open-HIGH case)."""
    meta = {
        "source": "ops_health_check",
        "job_name": job_name,
        "error_count": error_count,
        "run_id": run_id,
    }
    if detector_version is not None:
        meta["detector_version"] = detector_version
    if failure_signature is not None:
        meta["failure_signature"] = failure_signature
    return {
        "id": alert_id,
        "created_at": _iso(datetime.now(timezone.utc)),
        "metadata": meta,
    }


class TestSilentFailureRefireDedup(unittest.TestCase):
    def _run_once(self, job_runs, risk_alerts, alert_side_effect=None):
        from packages.quantum.jobs.handlers import ops_health_check as handler

        client = _Client({"job_runs": job_runs, "risk_alerts": risk_alerts})
        with ExitStack() as stack:
            mock_alert = _patch_ops_health(stack, client)
            if alert_side_effect is not None:
                mock_alert.side_effect = alert_side_effect
            result = handler.run({}, ctx=None)
        return mock_alert, result

    def test_first_valid_alert_still_emits(self):
        """No prior row for this identity → the FIRST alert emits (req 1)."""
        mock_alert, result = self._run_once([_job_run(1, run_id="rNEW")], [])
        mock_alert.assert_called_once()
        md = mock_alert.call_args.kwargs["metadata"]
        self.assertEqual(md["run_id"], "rNEW")
        self.assertEqual(md["detector_version"], "v1")
        self.assertEqual(md["failure_signature"], "paper_learning_ingest|errors=1")
        self.assertFalse(result["healthy"])

    def test_repeat_poll_same_identity_suppressed_typed(self):
        """A prior EXPLICIT-identity row for the same run → suppressed_duplicate
        (typed), NO new _alert / egress (req 2)."""
        prior = _prior_alert_row(
            run_id="r1", error_count=1, detector_version="v1",
            failure_signature="paper_learning_ingest|errors=1",
        )
        mock_alert, result = self._run_once([_job_run(1, run_id="r1")], [prior])
        mock_alert.assert_not_called()
        dups = [
            s for s in result["alerts_suppressed"]
            if s.get("reason") == "duplicate"
        ]
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["run_id"], "r1")
        self.assertEqual(dups[0]["prior_alert_id"], "prior-1")
        # Still SURFACED as an issue — suppression is anti-noise, not blindness.
        self.assertTrue(any("Silent failure" in i for i in result["issues_found"]))

    def test_historical_null_version_row_suppresses_known_incident(self):
        """The REAL 6-open-HIGH case: a prior row with NO detector_version /
        failure_signature (pre-versioning) is matched by DERIVING them from its
        own job_name + error_count (stored as a string) → suppressed, ZERO new
        row (req 2 + no historical mutation)."""
        prior = _prior_alert_row(
            run_id="df3c56e9", job_name="suggestions_open", error_count="1",
        )  # detector_version / failure_signature absent (NULL); error_count str
        mock_alert, result = self._run_once(
            [_job_run(1, run_id="df3c56e9", job_name="suggestions_open")],
            [prior],
        )
        mock_alert.assert_not_called()
        self.assertTrue(
            any(s.get("reason") == "duplicate" for s in result["alerts_suppressed"])
        )

    def test_new_incident_different_run_emits(self):
        """A prior row for a DIFFERENT run must NOT suppress a genuinely new
        incident (req 3). The stub ignores the SQL run_id filter, so this also
        proves the Python-side identity match rejects the wrong run."""
        prior = _prior_alert_row(run_id="rOLD", detector_version="v1")
        mock_alert, _ = self._run_once([_job_run(1, run_id="rNEW")], [prior])
        mock_alert.assert_called_once()
        self.assertEqual(mock_alert.call_args.kwargs["metadata"]["run_id"], "rNEW")

    def test_changed_failure_signature_same_run_emits(self):
        """Same run_id but a MATERIALLY changed failure (error_count 1 → 3) →
        different signature → re-emits (req 3)."""
        prior = _prior_alert_row(
            run_id="r1", error_count=1, detector_version="v1",
            failure_signature="paper_learning_ingest|errors=1",
        )
        mock_alert, _ = self._run_once([_job_run(3, run_id="r1")], [prior])
        mock_alert.assert_called_once()
        self.assertEqual(
            mock_alert.call_args.kwargs["metadata"]["failure_signature"],
            "paper_learning_ingest|errors=3",
        )

    def test_detector_version_bump_emits(self):
        """A prior v1 row does NOT suppress once the live detector is bumped to
        v2 — a new detector version is allowed to re-emit exactly once (req 3).
        The NULL-version baseline stays 'v1' so a legacy row cannot masquerade
        as v2."""
        prior = _prior_alert_row(
            run_id="r1", detector_version="v1",
            failure_signature="paper_learning_ingest|errors=1",
        )
        from packages.quantum.jobs.handlers import ops_health_check as handler

        client = _Client({"job_runs": [_job_run(1, run_id="r1")],
                          "risk_alerts": [prior]})
        with ExitStack() as stack:
            mock_alert = _patch_ops_health(stack, client)
            stack.enter_context(patch(f"{_HANDLER}.A4_DETECTOR_VERSION", "v2"))
            handler.run({}, ctx=None)
        mock_alert.assert_called_once()
        self.assertEqual(
            mock_alert.call_args.kwargs["metadata"]["detector_version"], "v2"
        )

    def test_double_poll_yields_exactly_one_alert(self):
        """Two sequential detector polls over the SAME durable store (the
        production model: one otc worker, 30-min cadence) emit EXACTLY ONE alert
        — the first poll's row makes the second poll a suppressed_duplicate
        (race requirement, serialized). The _alert side-effect writes the
        emitted row back into risk_alerts, exactly as the real alert() insert
        would."""
        from packages.quantum.jobs.handlers import ops_health_check as handler

        risk_alerts: list = []
        job_runs = [_job_run(2, run_id="rDP")]

        emitted: list = []

        def _persist(_client, **kwargs):
            emitted.append(kwargs)
            risk_alerts.append({
                "id": f"emitted-{len(emitted)}",
                "created_at": _iso(datetime.now(timezone.utc)),
                "metadata": dict(kwargs["metadata"]),
            })

        total_alert_calls = 0
        for _poll in range(2):
            client = _Client({"job_runs": job_runs, "risk_alerts": risk_alerts})
            with ExitStack() as stack:
                mock_alert = _patch_ops_health(stack, client)
                mock_alert.side_effect = _persist
                handler.run({}, ctx=None)
                total_alert_calls += mock_alert.call_count

        self.assertEqual(total_alert_calls, 1, "double-poll must emit once")
        self.assertEqual(len(risk_alerts), 1)
        self.assertEqual(len(emitted), 1)


class TestFindPriorSilentFailureAlert(unittest.TestCase):
    """Service-level unit coverage for the durable dedup lookup + signature."""

    def test_signature_is_int_string_stable(self):
        # A historical string error_count hashes identically to a live int.
        self.assertEqual(
            ohs.a4_failure_signature("j", "5"), ohs.a4_failure_signature("j", 5)
        )
        self.assertNotEqual(
            ohs.a4_failure_signature("j", 5), ohs.a4_failure_signature("j", 6)
        )
        self.assertEqual(ohs.a4_failure_signature(None, None), "unknown|errors=None")

    def test_lookup_matches_historical_null_version_row(self):
        prior = _prior_alert_row(run_id="r1", job_name="j", error_count="2")
        client = _Client({"risk_alerts": [prior]})
        hit = ohs.find_prior_silent_failure_alert(
            client, run_id="r1", detector_version="v1",
            failure_signature=ohs.a4_failure_signature("j", 2),
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["id"], "prior-1")

    def test_lookup_rejects_wrong_run_id_in_python(self):
        prior = _prior_alert_row(run_id="rOLD", job_name="j", error_count="2")
        client = _Client({"risk_alerts": [prior]})  # stub ignores SQL filter
        self.assertIsNone(
            ohs.find_prior_silent_failure_alert(
                client, run_id="rNEW", detector_version="v1",
                failure_signature=ohs.a4_failure_signature("j", 2),
            )
        )

    def test_lookup_none_run_id_fails_open(self):
        client = _Client({"risk_alerts": [_prior_alert_row(run_id="r1")]})
        self.assertIsNone(
            ohs.find_prior_silent_failure_alert(
                client, run_id=None, detector_version="v1",
                failure_signature="x",
            )
        )

    def test_lookup_query_error_fails_open_none(self):
        client = MagicMock()
        client.table.side_effect = RuntimeError("db down")
        # Fail-OPEN: a lookup error must return None (emit), never suppress.
        self.assertIsNone(
            ohs.find_prior_silent_failure_alert(
                client, run_id="r1", detector_version="v1",
                failure_signature="x",
            )
        )


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()
