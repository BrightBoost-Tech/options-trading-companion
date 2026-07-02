"""Pin tests for the heartbeat dead-man's-switch ping (A1, 2026-07-02).

Contract under pin: run()'s return value and job side-effects are
byte-identical across ping-success / ping-failure / unset. A provider
(healthchecks) outage can NEVER fail the heartbeat job. Unset or empty
HEARTBEAT_PING_URL is a silent no-op — zero HTTP calls, zero log spam.
The ping URL embeds the provider check token and must never be logged.
"""

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from packages.quantum.jobs.handlers import heartbeat

FROZEN = datetime(2026, 7, 2, 14, 0, 0, tzinfo=timezone.utc)
PING_URL = "https://hc-ping.example.com/secret-check-token"


def _run_frozen():
    """Run the handler with a frozen clock so results compare byte-identical."""
    fake_dt = MagicMock(wraps=datetime)
    fake_dt.now.return_value = FROZEN
    with patch.object(heartbeat, "datetime", fake_dt):
        return heartbeat.run({})


def test_unset_url_is_silent_noop(monkeypatch, caplog):
    monkeypatch.delenv("HEARTBEAT_PING_URL", raising=False)
    with patch("requests.get") as mock_get:
        with caplog.at_level(logging.DEBUG):
            result = _run_frozen()
    mock_get.assert_not_called()
    assert result == {"ok": True, "timestamp": FROZEN.isoformat()}
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_empty_url_is_silent_noop(monkeypatch, caplog):
    monkeypatch.setenv("HEARTBEAT_PING_URL", "   ")
    with patch("requests.get") as mock_get:
        with caplog.at_level(logging.DEBUG):
            result = _run_frozen()
    mock_get.assert_not_called()
    assert result == {"ok": True, "timestamp": FROZEN.isoformat()}
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_ping_success_calls_once_with_timeout(monkeypatch, caplog):
    monkeypatch.setenv("HEARTBEAT_PING_URL", PING_URL)
    with patch("requests.get") as mock_get:
        with caplog.at_level(logging.DEBUG):
            result = _run_frozen()
    mock_get.assert_called_once_with(PING_URL, timeout=5)
    assert result == {"ok": True, "timestamp": FROZEN.isoformat()}
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_ping_timeout_never_fails_job(monkeypatch, caplog):
    import requests as requests_mod

    monkeypatch.setenv("HEARTBEAT_PING_URL", PING_URL)
    with patch("requests.get", side_effect=requests_mod.exceptions.Timeout(PING_URL)):
        with caplog.at_level(logging.DEBUG):
            result = _run_frozen()
    assert result == {"ok": True, "timestamp": FROZEN.isoformat()}
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "[HEARTBEAT]" in warnings[0].getMessage()


def test_ping_arbitrary_exception_never_fails_job(monkeypatch, caplog):
    monkeypatch.setenv("HEARTBEAT_PING_URL", PING_URL)
    with patch("requests.get", side_effect=RuntimeError("provider exploded")):
        with caplog.at_level(logging.DEBUG):
            result = _run_frozen()
    assert result == {"ok": True, "timestamp": FROZEN.isoformat()}
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_results_byte_identical_across_all_ping_outcomes(monkeypatch):
    monkeypatch.delenv("HEARTBEAT_PING_URL", raising=False)
    with patch("requests.get"):
        r_unset = _run_frozen()

    monkeypatch.setenv("HEARTBEAT_PING_URL", PING_URL)
    with patch("requests.get"):
        r_success = _run_frozen()
    with patch("requests.get", side_effect=RuntimeError("down")):
        r_failure = _run_frozen()

    assert r_unset == r_success == r_failure


def test_failure_log_never_leaks_the_url(monkeypatch, caplog):
    monkeypatch.setenv("HEARTBEAT_PING_URL", PING_URL)
    with patch(
        "requests.get", side_effect=ConnectionError(f"failed reaching {PING_URL}")
    ):
        with caplog.at_level(logging.DEBUG):
            _run_frozen()
    for record in caplog.records:
        assert PING_URL not in record.getMessage()
        assert "secret-check-token" not in record.getMessage()
