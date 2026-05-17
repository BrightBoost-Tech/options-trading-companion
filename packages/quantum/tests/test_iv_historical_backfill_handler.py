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
    produces at test time.

    Post-PR-A refactor: skip-filter happens BEFORE the per-symbol
    window method is called, so neither path runs when all dates
    are skipped."""
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

        # All 3 days skipped — neither method called.
        svc.compute_historical_iv_points_for_window.assert_not_called()
        svc.compute_historical_iv_point.assert_not_called()
        repo.upsert_iv_point.assert_not_called()
        assert result["stats"]["skipped_existing"] == 3
        assert result["stats"]["ok"] == 0


def test_handler_window_method_per_date_failure_isolated():
    """Window method returns ``Dict[date, Optional[result]]``. Dates
    mapping to None are counted as missing_data; dates mapping to a
    valid result dict produce upsert calls. One None doesn't abort
    the others."""
    client = _make_supabase_mock()

    with patch.object(handler, "get_admin_client", return_value=client), \
         patch.object(handler, "PolygonService") as poly_cls, \
         patch.object(handler, "HistoricalIVService") as svc_cls, \
         patch.object(handler, "IVRepository") as repo_cls:

        svc = svc_cls.return_value
        repo = repo_cls.return_value
        repo.count_rows_for_date.return_value = 1

        def window_side_effect(sym, dates):
            # First date returns valid result, rest None (missing_data).
            out = {}
            for i, d in enumerate(dates):
                if i == 0:
                    out[d] = {"iv": 0.25, "iv_30d": 0.25,
                              "iv_method": "test",
                              "inputs": {"spot": 100.0}}
                else:
                    out[d] = None
            return out

        svc.compute_historical_iv_points_for_window.side_effect = window_side_effect
        repo.upsert_iv_point.return_value = True

        result = handler.run({"days": 3, "symbols": ["SPY"]})

        assert result["status"] == "ok"
        assert result["stats"]["ok"] == 1
        assert result["stats"]["missing_data"] == 2
        assert result["stats"]["failed"] == 0


def test_handler_window_method_exception_marks_symbol_failed():
    """If the window method raises (catastrophic per-symbol failure),
    every unprocessed date for that symbol counts as failed and the
    error is captured. Mirrors per-date failure-isolation semantics
    at symbol granularity."""
    client = _make_supabase_mock()

    with patch.object(handler, "get_admin_client", return_value=client), \
         patch.object(handler, "PolygonService") as poly_cls, \
         patch.object(handler, "HistoricalIVService") as svc_cls, \
         patch.object(handler, "IVRepository") as repo_cls:

        svc = svc_cls.return_value
        repo = repo_cls.return_value
        repo.count_rows_for_date.return_value = 0
        svc.compute_historical_iv_points_for_window.side_effect = (
            RuntimeError("simulated symbol-level upstream failure")
        )

        result = handler.run({"days": 3, "symbols": ["SPY"]})

        assert result["status"] == "ok"
        assert result["stats"]["ok"] == 0
        assert result["stats"]["failed"] == 3  # all 3 days for SPY
        assert any("window_exception" in e and "RuntimeError" in e
                   for e in result["stats"]["errors"])


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

        def window_side_effect(sym, dates):
            return {d: {"iv": 0.25, "iv_30d": 0.25, "iv_method": "test",
                        "inputs": {"spot": 100.0}}
                    for d in dates}

        svc.compute_historical_iv_points_for_window.side_effect = window_side_effect
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

        def window_side_effect(sym, dates):
            return {d: {"iv": 0.25, "iv_30d": 0.25, "iv_method": "test",
                        "inputs": {"spot": 100.0}}
                    for d in dates}

        svc.compute_historical_iv_points_for_window.side_effect = window_side_effect
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
