"""Edge-trigger breaker amendment (2026-07-07) — the required matrix.

The breaker re-trips only when the trailing loss WINDOW CHANGES. Identity
is CONTENT-based (sorted outcome row ids), stamped at trip time into
ops_control.streak_breaker_state. Suppression needs a POSITIVE match;
every uncertainty path trips (fail-toward-tripping). Flag
STREAK_BREAKER_EDGE_TRIGGER_ENABLED default-ON; explicit falsy → legacy
level-trigger, byte-identical.
"""

import sys
from unittest.mock import MagicMock, patch

for _key in ("packages.quantum.risk.streak_breaker",):
    if isinstance(sys.modules.get(_key), MagicMock):
        del sys.modules[_key]

from packages.quantum.risk import streak_breaker as sb


def _outcome(rid, pnl, sym="QQQ"):
    return {"id": rid, "pnl_realized": pnl,
            "details_json": {"symbol": sym},
            "created_at": "2026-07-07T21:20:00+00:00"}


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeClient:
    """Routes .table() by name; carries a streak_breaker_state; records
    ops_control updates and risk_alerts inserts."""

    def __init__(self, outcomes=None, paused=False, state=None,
                 state_read_raises=False):
        self.outcomes = outcomes or []
        self.paused = paused
        self.state = state  # ops_control.streak_breaker_state value
        self.state_read_raises = state_read_raises
        self.updates = []

    def table(self, name):
        fake = self

        class _Q:
            def __init__(self):
                self._update_payload = None
                self._selected = None

            def select(self, cols):
                self._selected = cols
                return self

            def eq(self, col, val):
                return self

            def order(self, col, desc=False):
                return self

            def limit(self, n):
                return self

            def update(self, payload):
                self._update_payload = payload
                return self

            def insert(self, record):
                fake.updates.append({"table": name, "insert": record})
                return self

            def execute(self):
                if self._update_payload is not None:
                    fake.updates.append(
                        {"table": name, "update": self._update_payload}
                    )
                    # simulate the durable stamp for subsequent reads
                    if "streak_breaker_state" in self._update_payload:
                        fake.state = self._update_payload["streak_breaker_state"]
                    return _Result(None)
                if name == "learning_feedback_loops":
                    return _Result(list(fake.outcomes))
                if name == "ops_control":
                    if (
                        self._selected
                        and "streak_breaker_state" in self._selected
                        and fake.state_read_raises
                    ):
                        raise RuntimeError("state read down")
                    return _Result([{
                        "entries_paused": fake.paused,
                        "entries_pause_reason": None,
                        "streak_breaker_state": fake.state,
                    }])
                return _Result([])

        return _Q()


def _pause_writes(c):
    return [u for u in c.updates if u["table"] == "ops_control"
            and "update" in u and "entries_paused" in u["update"]]


def _stamp_writes(c):
    return [u for u in c.updates if u["table"] == "ops_control"
            and "update" in u and "streak_breaker_state" in u["update"]]


def _criticals(c):
    return [u["insert"] for u in c.updates
            if u["table"] == "risk_alerts" and "insert" in u]


_LOSSES = [_outcome("r-mara", -15), _outcome("r-qqq73", -73),
           _outcome("r-qqq15", -15)]
_FP = sorted(["r-mara", "r-qqq73", "r-qqq15"])


class TestMatrix:
    def test_1_new_loss_on_empty_state_trips(self):
        """Case 1: no stamp has ever been written → any full loss window
        trips (tonight-compatible: the pre-amendment trip left no stamp)."""
        c = _FakeClient(outcomes=list(_LOSSES), state=None)
        out = sb.evaluate_and_trip(c)
        assert out["tripped"] is True
        assert len(_pause_writes(c)) == 1
        assert len(_stamp_writes(c)) == 1
        assert sorted(
            _stamp_writes(c)[0]["update"]["streak_breaker_state"]
            ["last_tripped_fingerprint"]
        ) == _FP

    def test_2_new_loss_extending_window_trips(self):
        """Case 2: stamp exists for the OLD window; one row is new →
        different row-set → trips + re-stamps the new fingerprint."""
        c = _FakeClient(
            outcomes=[_outcome("r-NEW", -20), _outcome("r-mara", -15),
                      _outcome("r-qqq73", -73)],
            state={"last_tripped_fingerprint": _FP,
                   "tripped_at": "2026-07-07T21:20:03+00:00"},
        )
        out = sb.evaluate_and_trip(c)
        assert out["tripped"] is True
        assert out.get("suppressed_standing_window") is None
        new_fp = sorted(["r-NEW", "r-mara", "r-qqq73"])
        assert sorted(
            _stamp_writes(c)[0]["update"]["streak_breaker_state"]
            ["last_tripped_fingerprint"]
        ) == new_fp

    def test_3_standing_reviewed_window_does_not_repause(self):
        """Case 3 — THE amendment: same rows as the last trip, operator
        un-paused (entries_paused=false), no new close → no re-pause, no
        duplicate critical, nothing written."""
        c = _FakeClient(
            outcomes=list(_LOSSES), paused=False,
            state={"last_tripped_fingerprint": _FP,
                   "tripped_at": "2026-07-07T21:20:03+00:00"},
        )
        out = sb.evaluate_and_trip(c)
        assert out["tripped"] is False
        assert out["suppressed_standing_window"] is True
        assert out["reason"].startswith("standing_window_already_reviewed")
        assert _pause_writes(c) == []
        assert _criticals(c) == []
        assert _stamp_writes(c) == []  # stamp only moves on a trip

    def test_4_unpause_then_new_loss_retrips(self):
        """Case 4: after the operator clears the old window, a NEW loss
        forms a different row-set → trips again."""
        c = _FakeClient(
            outcomes=[_outcome("r-fresh-loss", -30), _outcome("r-qqq73", -73),
                      _outcome("r-qqq15", -15)],
            paused=False,
            state={"last_tripped_fingerprint": _FP,
                   "tripped_at": "2026-07-07T21:20:03+00:00"},
        )
        out = sb.evaluate_and_trip(c)
        assert out["tripped"] is True
        assert len(_pause_writes(c)) == 1
        assert any(a["alert_type"] == "streak_breaker_tripped"
                   for a in _criticals(c))

    def test_5_evaluation_error_still_fails_closed(self):
        """Case 5: unchanged — an outcomes-query error pauses, never skips."""
        class _Boom(_FakeClient):
            def table(self, name):
                if name == "learning_feedback_loops":
                    raise RuntimeError("outcomes query down")
                return super().table(name)

        c = _Boom(state={"last_tripped_fingerprint": _FP})
        out = sb.evaluate_and_trip(c)  # must not raise
        assert out["tripped"] is False
        assert "error" in out
        assert len(_pause_writes(c)) == 1
        assert _pause_writes(c)[0]["update"]["entries_paused"] is True

    def test_6_fingerprint_is_content_based(self):
        """Case 6: same rows (any order) → identical fingerprint; one row
        different → different fingerprint. Count/time never enter it."""
        rows = list(_LOSSES)
        assert sb._window_fingerprint(rows) == _FP
        assert sb._window_fingerprint(list(reversed(rows))) == _FP
        swapped = [_outcome("r-other", -9)] + rows[1:]
        assert sb._window_fingerprint(swapped) != _FP
        # same COUNT, same symbols, different rows → different identity
        assert len(swapped) == len(rows)

    def test_7_flag_off_is_legacy_level_trigger(self):
        """Case 7: explicit falsy → the standing reviewed window re-trips
        exactly as before the amendment (byte-identical legacy path)."""
        c = _FakeClient(
            outcomes=list(_LOSSES), paused=False,
            state={"last_tripped_fingerprint": _FP,
                   "tripped_at": "2026-07-07T21:20:03+00:00"},
        )
        with patch.dict("os.environ",
                        {"STREAK_BREAKER_EDGE_TRIGGER_ENABLED": "0"}):
            out = sb.evaluate_and_trip(c)
        assert out["tripped"] is True
        assert out["edge_trigger"] is False
        assert len(_pause_writes(c)) == 1

    def test_8_state_read_failure_fails_toward_tripping(self):
        """Suppression requires a POSITIVE match: a state-read error must
        trip, never suppress."""
        c = _FakeClient(
            outcomes=list(_LOSSES),
            state={"last_tripped_fingerprint": _FP},
            state_read_raises=True,
        )
        out = sb.evaluate_and_trip(c)
        assert out["tripped"] is True
        assert len(_pause_writes(c)) == 1


class TestPolarityAndWiring:
    def test_default_on_when_unset(self):
        import os
        os.environ.pop("STREAK_BREAKER_EDGE_TRIGGER_ENABLED", None)
        assert sb._edge_trigger_enabled() is True

    def test_explicit_falsy_disables(self):
        for v in ("0", "false", "no", "off", "OFF"):
            with patch.dict("os.environ",
                            {"STREAK_BREAKER_EDGE_TRIGGER_ENABLED": v}):
                assert sb._edge_trigger_enabled() is False

    def test_production_call_path_is_wired(self):
        """The 9a2cef1/#1126 rule: default-ON means the wiring must be IN
        evaluate_and_trip — not an orphan helper with green tests."""
        import inspect

        src = inspect.getsource(sb.evaluate_and_trip)
        assert "_edge_trigger_enabled()" in src
        assert "_read_last_tripped_fingerprint(" in src
        assert "_stamp_tripped_fingerprint(" in src

    def test_stamp_failure_never_breaks_the_trip(self):
        """A failed stamp degrades to legacy re-trip behavior — it must not
        raise or retract the pause/alert that already happened."""
        class _StampBoom(_FakeClient):
            def table(self, name):
                q = super().table(name)
                if name == "ops_control":
                    orig_execute = q.execute

                    def execute():
                        if (
                            q._update_payload is not None
                            and "streak_breaker_state" in q._update_payload
                        ):
                            raise RuntimeError("stamp write down")
                        return orig_execute()

                    q.execute = execute
                return q

        c = _StampBoom(outcomes=list(_LOSSES), state=None)
        out = sb.evaluate_and_trip(c)  # must not raise
        assert out["tripped"] is True
        assert len(_pause_writes(c)) == 1
        assert "fingerprint_stamp_error" in out

    def test_no_code_path_writes_entries_paused_false(self):
        import inspect

        src = inspect.getsource(sb)
        assert '"entries_paused": False' not in src
        assert "'entries_paused': False" not in src
