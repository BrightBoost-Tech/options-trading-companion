"""Gap-1 (2026-07-02) — consecutive-loss streak breaker (NoFx pattern).

Contract under pin (operator-specified):
- trigger: N consecutive live losing round-trips → ops_control.entries_paused
  = true + structured reason + critical alert (egress-allowlisted);
- non-trigger: a win inside the window → NO write of any kind;
- FAIL-CLOSED: an evaluation error → entries PAUSED (never check-skipped) +
  critical alert; evaluate_and_trip never raises;
- idempotency: an existing pause is never cleared or clobbered;
- recovery is operator-only: no code path writes entries_paused = false;
- polarity: default-ON (unset/empty → enabled); explicit falsy disables;
- N is env-config (STREAK_BREAKER_N).
"""

from unittest.mock import MagicMock, patch

from packages.quantum.risk import streak_breaker as sb


def _outcome(pnl, sym="SOFI"):
    # symbol rides inside details_json — the table has no typed symbol column
    # (selecting one would 42703; pinned by the module's select list).
    return {"id": f"o-{sym}-{pnl}", "pnl_realized": pnl,
            "details_json": {"symbol": sym},
            "created_at": "2026-07-01T21:20:00+00:00"}


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeClient:
    """Routes .table() by name; records ops_control updates."""

    def __init__(self, outcomes=None, paused=False, pause_reason=None,
                 outcomes_raise=False, control_raise=False):
        self.outcomes = outcomes or []
        self.paused = paused
        self.pause_reason = pause_reason
        self.outcomes_raise = outcomes_raise
        self.control_raise = control_raise
        self.updates = []
        self.limits = []

    def table(self, name):
        fake = self

        class _Q:
            def __init__(self):
                self._update_payload = None

            def select(self, cols):
                return self

            def eq(self, col, val):
                return self

            def order(self, col, desc=False):
                return self

            def limit(self, n):
                if name == "learning_feedback_loops":
                    fake.limits.append(n)
                return self

            def update(self, payload):
                self._update_payload = payload
                return self

            def insert(self, record):  # alert() writes risk_alerts
                fake.updates.append({"table": name, "insert": record})
                return self

            def execute(self):
                if self._update_payload is not None:
                    if fake.control_raise:
                        raise RuntimeError("control write down")
                    fake.updates.append(
                        {"table": name, "update": self._update_payload}
                    )
                    return _Result(None)
                if name == "learning_feedback_loops":
                    if fake.outcomes_raise:
                        raise RuntimeError("outcomes query down")
                    return _Result(list(fake.outcomes))
                if name == "ops_control":
                    if fake.control_raise:
                        raise RuntimeError("control read down")
                    return _Result([{
                        "entries_paused": fake.paused,
                        "entries_pause_reason": fake.pause_reason,
                    }])
                return _Result([])

        return _Q()


def _pause_writes(client):
    return [u for u in client.updates
            if u["table"] == "ops_control" and "update" in u]


def _alerts(client):
    return [u["insert"] for u in client.updates
            if u["table"] == "risk_alerts" and "insert" in u]


class TestTrigger:
    def test_three_losses_trips_pauses_and_alerts(self):
        client = _FakeClient(outcomes=[_outcome(-40), _outcome(-15), _outcome(-88)])
        out = sb.evaluate_and_trip(client)
        assert out["tripped"] is True
        assert out["paused_written"] is True
        writes = _pause_writes(client)
        assert len(writes) == 1
        assert writes[0]["update"]["entries_paused"] is True
        assert "streak_breaker" in writes[0]["update"]["entries_pause_reason"]
        alerts = _alerts(client)
        assert any(a["alert_type"] == "streak_breaker_tripped"
                   and a["severity"] == "critical" for a in alerts)

    def test_zero_pnl_is_not_a_loss(self):
        client = _FakeClient(outcomes=[_outcome(-40), _outcome(0.0), _outcome(-88)])
        out = sb.evaluate_and_trip(client)
        assert out["tripped"] is False
        assert _pause_writes(client) == []


class TestNonTrigger:
    def test_win_breaks_streak_no_writes_at_all(self):
        client = _FakeClient(outcomes=[_outcome(-40), _outcome(25), _outcome(-88)])
        out = sb.evaluate_and_trip(client)
        assert out["tripped"] is False
        assert out["reason"] == "streak_broken_by_win"
        assert client.updates == []  # no pause write, no alert — nothing

    def test_insufficient_history_no_trip(self):
        client = _FakeClient(outcomes=[_outcome(-40), _outcome(-15)])
        out = sb.evaluate_and_trip(client)
        assert out["tripped"] is False
        assert out["reason"].startswith("insufficient_history")
        assert client.updates == []


class TestFailClosed:
    def test_evaluation_error_pauses_entries_and_alerts(self):
        client = _FakeClient(outcomes_raise=True)
        out = sb.evaluate_and_trip(client)  # must not raise
        assert out["tripped"] is False
        assert "error" in out
        writes = _pause_writes(client)
        assert len(writes) == 1, "fail-closed: evaluation error must PAUSE, not skip"
        assert writes[0]["update"]["entries_paused"] is True
        assert "evaluation_error" in writes[0]["update"]["entries_pause_reason"]
        alerts = _alerts(client)
        assert any(a["alert_type"] == "streak_breaker_error"
                   and a["severity"] == "critical" for a in alerts)

    def test_pause_write_failure_still_alerts_never_raises(self):
        client = _FakeClient(
            outcomes=[_outcome(-40), _outcome(-15), _outcome(-88)],
            control_raise=True,
        )
        out = sb.evaluate_and_trip(client)  # must not raise
        assert out["tripped"] is True
        assert out["paused_written"] is False
        assert "pause_write_error" in out
        alerts = _alerts(client)
        assert any(a["alert_type"] == "streak_breaker_error" for a in alerts)


class TestIdempotency:
    def test_existing_pause_never_clobbered(self):
        client = _FakeClient(
            outcomes=[_outcome(-40), _outcome(-15), _outcome(-88)],
            paused=True, pause_reason="operator: manual halt",
        )
        out = sb.evaluate_and_trip(client)
        assert out["tripped"] is True
        assert out["already_paused"] is True
        assert _pause_writes(client) == []  # reason preserved, nothing written
        assert out["existing_reason"] == "operator: manual halt"

    def test_no_code_path_writes_entries_paused_false(self):
        import inspect

        src = inspect.getsource(sb)
        assert '"entries_paused": False' not in src
        assert "'entries_paused': False" not in src


class TestPolarityAndConfig:
    def test_default_on_when_unset(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("STREAK_BREAKER_ENABLED", None)
            assert sb._is_enabled() is True

    def test_empty_string_is_on(self):
        with patch.dict("os.environ", {"STREAK_BREAKER_ENABLED": "  "}):
            assert sb._is_enabled() is True

    def test_explicit_falsy_disables(self):
        for v in ("0", "false", "no", "off", "FALSE"):
            with patch.dict("os.environ", {"STREAK_BREAKER_ENABLED": v}):
                assert sb._is_enabled() is False

    def test_disabled_does_nothing(self):
        client = _FakeClient(outcomes=[_outcome(-1), _outcome(-2), _outcome(-3)])
        with patch.dict("os.environ", {"STREAK_BREAKER_ENABLED": "0"}):
            out = sb.evaluate_and_trip(client)
        assert out["reason"] == "disabled_by_env"
        assert client.updates == []

    def test_n_is_env_config(self):
        client = _FakeClient(outcomes=[_outcome(-1)] * 5)
        with patch.dict("os.environ", {"STREAK_BREAKER_N": "5"}):
            out = sb.evaluate_and_trip(client)
        assert out["n"] == 5
        assert client.limits == [5]
        assert out["tripped"] is True

    def test_bad_n_falls_back_to_3(self):
        with patch.dict("os.environ", {"STREAK_BREAKER_N": "banana"}):
            assert sb._n() == 3


class TestEgressAllowlist:
    def test_streak_alert_types_egress_immediately(self):
        from packages.quantum.observability.alerts import _RISK_EGRESS_ALERT_TYPES

        assert "streak_breaker_tripped" in _RISK_EGRESS_ALERT_TYPES
        assert "streak_breaker_error" in _RISK_EGRESS_ALERT_TYPES


class TestNoPhantomColumns:
    def test_select_list_matches_real_schema(self):
        """learning_feedback_loops has NO typed symbol column (verified against
        the live schema 07-02). A phantom column in this select would 42703 in
        production and — under fail-closed semantics — pause entries on every
        run (#1098 class). Pin the exact select list."""
        import inspect

        src = inspect.getsource(sb.evaluate_and_trip)
        assert '"id, pnl_realized, created_at, details_json"' in src
