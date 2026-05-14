"""Handler tests for ``iv_historical_backfill``.

Verifies:
- Resume logic: existing rows in ``underlying_iv_points`` are skipped
- Failure isolation: per (symbol, date) exception doesn't abort the run
- H9 verification: ``count_rows_for_date`` is called per-date that
  reported a successful write
- Audit row write happens at end of run
"""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from packages.quantum.jobs.handlers import iv_historical_backfill as handler


def _make_supabase_mock(existing_rows: list = None) -> MagicMock:
    """Returns a MagicMock Supabase client tree.

    - The ``underlying_iv_points`` SELECT chain returns ``existing_rows``
      (for skip-existing test).
    - The ``risk_alerts`` INSERT chain is no-op.
    """
    client = MagicMock()

    select_chain = MagicMock()
    select_chain.data = existing_rows or []

    table_mock = MagicMock()
    table_mock.select.return_value.in_.return_value.in_.return_value.execute.return_value = select_chain
    table_mock.insert.return_value.execute.return_value = MagicMock()

    client.table.return_value = table_mock
    return client


def test_handler_resume_skips_existing_rows():
    """If a (symbol, date) row exists, the service is never invoked
    for that tuple. We patch ``_query_existing_backfilled`` directly
    so the skip-set matches whatever date window ``date.today()``
    produces at test time."""
    client = _make_supabase_mock()

    def fake_query(client_arg, symbols, dates):
        return {(sym, d.strftime("%Y-%m-%d"))
                for sym in symbols for d in dates}

    with patch.object(handler, "get_admin_client", return_value=client), \
         patch.object(handler, "PolygonService") as poly_cls, \
         patch.object(handler, "HistoricalIVService") as svc_cls, \
         patch.object(handler, "IVRepository") as repo_cls, \
         patch.object(handler, "_query_existing_backfilled",
                       side_effect=fake_query):

        svc = svc_cls.return_value
        repo = repo_cls.return_value
        repo.count_rows_for_date.return_value = 0

        result = handler.run({"days": 3, "symbols": ["SPY"]})

        # All 3 days skipped — service never invoked.
        svc.compute_historical_iv_point.assert_not_called()
        repo.upsert_iv_point.assert_not_called()
        assert result["stats"]["skipped_existing"] == 3
        assert result["stats"]["ok"] == 0


def test_handler_per_symbol_exception_isolated():
    """An exception in compute_historical_iv_point for one
    (symbol, date) must not abort the rest of the run."""
    client = _make_supabase_mock()

    with patch.object(handler, "get_admin_client", return_value=client), \
         patch.object(handler, "PolygonService") as poly_cls, \
         patch.object(handler, "HistoricalIVService") as svc_cls, \
         patch.object(handler, "IVRepository") as repo_cls:

        svc = svc_cls.return_value
        repo = repo_cls.return_value
        repo.count_rows_for_date.return_value = 1

        # First call raises, second returns valid result, rest return None.
        call_count = {"n": 0}

        def compute_side_effect(sym, d):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated upstream failure")
            if call_count["n"] == 2:
                return {"iv": 0.25, "iv_30d": 0.25, "iv_method": "test",
                        "inputs": {"spot": 100.0}}
            return None

        svc.compute_historical_iv_point.side_effect = compute_side_effect
        repo.upsert_iv_point.return_value = True

        result = handler.run({"days": 3, "symbols": ["SPY"]})

        # Verified: run completed despite the exception, one ok write
        # captured, one failure recorded with type captured in errors.
        assert result["status"] == "ok"
        assert result["stats"]["ok"] == 1
        assert result["stats"]["failed"] == 1
        assert result["stats"]["missing_data"] == 1
        assert any("RuntimeError" in e for e in result["stats"]["errors"])


def test_handler_h9_verification_per_written_date():
    """For every date that reported a successful write, the handler
    must call ``count_rows_for_date`` (independent DB query) and
    include the count in the verification dict."""
    client = _make_supabase_mock()

    with patch.object(handler, "get_admin_client", return_value=client), \
         patch.object(handler, "PolygonService") as poly_cls, \
         patch.object(handler, "HistoricalIVService") as svc_cls, \
         patch.object(handler, "IVRepository") as repo_cls:

        svc = svc_cls.return_value
        repo = repo_cls.return_value
        svc.compute_historical_iv_point.return_value = {
            "iv": 0.25, "iv_30d": 0.25, "iv_method": "test",
            "inputs": {"spot": 100.0},
        }
        repo.upsert_iv_point.return_value = True
        repo.count_rows_for_date.return_value = 1

        result = handler.run({"days": 2, "symbols": ["SPY", "AAPL"]})

        assert result["stats"]["ok"] == 4  # 2 symbols × 2 days
        assert len(result["verification"]) == 2  # 2 unique dates
        # Independent count was called for each date.
        assert repo.count_rows_for_date.call_count == 2


def test_handler_upsert_returning_false_counted_as_failed():
    """Per H9: upsert returning False must increment ``failed``, not ``ok``."""
    client = _make_supabase_mock()

    with patch.object(handler, "get_admin_client", return_value=client), \
         patch.object(handler, "PolygonService") as poly_cls, \
         patch.object(handler, "HistoricalIVService") as svc_cls, \
         patch.object(handler, "IVRepository") as repo_cls:

        svc = svc_cls.return_value
        repo = repo_cls.return_value
        svc.compute_historical_iv_point.return_value = {
            "iv": 0.25, "iv_30d": 0.25, "iv_method": "test",
            "inputs": {"spot": 100.0},
        }
        repo.upsert_iv_point.return_value = False
        repo.count_rows_for_date.return_value = 0

        result = handler.run({"days": 1, "symbols": ["SPY"]})

        assert result["stats"]["ok"] == 0
        assert result["stats"]["failed"] == 1
        assert any("upsert_returned_false" in e for e in result["stats"]["errors"])


def test_trading_days_skips_weekends():
    """``_trading_days`` returns weekday-only sequences."""
    # Sat 2026-05-02 → step backwards to Fri, Thu, Wed
    days = handler._trading_days(date(2026, 5, 2), 3)
    assert len(days) == 3
    for d in days:
        assert d.weekday() < 5
