"""Job handler: backfill ATM IV30 points for a historical window.

Walks ``BACKFILL_DAYS`` trading days backwards from yesterday for each
symbol in ``BACKFILL_REFERENCE_SYMBOLS`` (default SPY/AAPL/AMD per α
design spec). Skips weekends and any (symbol, date) tuple already
present in ``underlying_iv_points``.

For each (symbol, date) tuple this handler:
1. Reconstructs the option chain via ``HistoricalIVService``
   (Polygon contracts + historical aggregates + BS inversion)
2. Hands the chain to ``IVPointService.compute_atm_iv_target_from_chain``
3. Writes the resulting IV point via ``IVRepository.upsert_iv_point``
4. Verifies the write succeeded (return-value check, then post-loop
   row count) per H9 convention

Designed to be safely re-runnable: the per-row idempotency comes from
the ``(underlying, as_of_date)`` UNIQUE constraint on
``underlying_iv_points``; the per-symbol/date resume comes from the
existing-rows check before each call.

Failure isolation: per-symbol/date exceptions go into ``stats["errors"]``
and are NOT re-raised. A single bad day on one symbol must not abort
the rest of the backfill.
"""
from __future__ import annotations

import os
import traceback
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Set, Tuple

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.market_data import PolygonService
from packages.quantum.services.historical_iv_service import HistoricalIVService
from packages.quantum.services.iv_repository import IVRepository

JOB_NAME = "iv_historical_backfill"

# α design spec defaults — overridable via env or payload.
DEFAULT_BACKFILL_DAYS = int(os.getenv("BACKFILL_DAYS", "60"))
DEFAULT_RISK_FREE_RATE = float(os.getenv("BACKFILL_RISK_FREE_RATE", "0.045"))
DEFAULT_REFERENCE_SYMBOLS = os.getenv(
    "BACKFILL_REFERENCE_SYMBOLS", "SPY,AAPL,AMD",
).split(",")


def _trading_days(end: date, count: int) -> List[date]:
    """Return ``count`` weekdays (Mon-Fri) ending at ``end`` (inclusive
    if it's a weekday, else stepping back). Approximate — does not
    skip US market holidays. Holiday-falling rows produce empty chains
    and are skipped at the inversion layer, which is acceptable for a
    one-shot 60-day backfill."""
    days: List[date] = []
    cur = end
    while len(days) < count:
        # Mon-Fri only (0..4); skip 5=Sat, 6=Sun.
        if cur.weekday() < 5:
            days.append(cur)
        cur -= timedelta(days=1)
    return list(reversed(days))


def _query_existing_backfilled(
    client, symbols: List[str], dates: List[date],
) -> Set[Tuple[str, str]]:
    """Return the set of ``(symbol, as_of_date_str)`` tuples that
    already have rows in ``underlying_iv_points``. Used to skip work
    on resume / re-run.

    Uses Supabase's ``.in_`` over both filter columns. Single query
    bounded by len(symbols) * len(dates) ≤ 3 * 60 = 180 rows.
    """
    if not symbols or not dates:
        return set()
    date_strs = [d.strftime("%Y-%m-%d") for d in dates]
    try:
        res = (
            client.table("underlying_iv_points")
            .select("underlying, as_of_date")
            .in_("underlying", symbols)
            .in_("as_of_date", date_strs)
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        print(f"[{JOB_NAME}] existing-rows query failed: {e}")
        return set()

    return {(r["underlying"], r["as_of_date"]) for r in (res.data or [])}


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    print(f"[{JOB_NAME}] Starting with payload: {payload}")

    days = int(payload.get("days") or DEFAULT_BACKFILL_DAYS)
    risk_free_rate = float(
        payload.get("risk_free_rate") or DEFAULT_RISK_FREE_RATE,
    )
    symbols: List[str] = [
        s.strip().upper() for s in (
            payload.get("symbols") or DEFAULT_REFERENCE_SYMBOLS
        )
        if s and s.strip()
    ]

    try:
        client = get_admin_client()
        polygon = PolygonService()
        service = HistoricalIVService(
            polygon_service=polygon,
            risk_free_rate=risk_free_rate,
        )
        iv_repo = IVRepository(client)

        # Walk back from yesterday so today's snapshot-path data is
        # never accidentally overwritten by a backfill row.
        end_date = date.today() - timedelta(days=1)
        target_days = _trading_days(end_date, days)

        skip_set = _query_existing_backfilled(client, symbols, target_days)

        stats = {
            "ok": 0,
            "failed": 0,
            "skipped_existing": 0,
            "missing_data": 0,
            "errors": [],
        }
        rows_written_dates: Set[str] = set()

        for sym in symbols:
            # Filter target_days to the dates this symbol still needs.
            # Skip-existing happens here (pre-Polygon-call) so we avoid
            # paying the per-symbol contract+OHLC fetch cost for symbols
            # whose entire window is already populated.
            sym_unprocessed_days: List[date] = []
            for d in target_days:
                d_str = d.strftime("%Y-%m-%d")
                if (sym, d_str) in skip_set:
                    stats["skipped_existing"] += 1
                else:
                    sym_unprocessed_days.append(d)

            if not sym_unprocessed_days:
                continue

            # Window method: one chain-listing call per right per symbol +
            # one OHLC range call per contract per symbol (instead of
            # per-date × per-contract). See PR-A description for the
            # ~46x API call count reduction.
            try:
                results = service.compute_historical_iv_points_for_window(
                    sym, sym_unprocessed_days,
                )
            except Exception as e:  # noqa: BLE001
                # Catastrophic per-symbol failure. Mark every date in
                # this window's unprocessed set as failed and continue.
                # Mirrors the per-date method's per-failure isolation
                # at symbol granularity (catastrophic chain fetch
                # failure can't be locally isolated).
                stats["failed"] += len(sym_unprocessed_days)
                stats["errors"].append(
                    f"{sym}: window_exception:{type(e).__name__}:{e}"
                )
                continue

            # Per-date results processing. Same upsert / verify / stats
            # accounting as the per-date method had; mirroring its
            # failure-isolation pattern at per-date granularity.
            for d in sym_unprocessed_days:
                d_str = d.strftime("%Y-%m-%d")
                result = results.get(d)

                if not result or result.get("iv") is None:
                    stats["missing_data"] += 1
                    continue

                as_of_ts = datetime.combine(d, datetime.min.time())
                try:
                    wrote = iv_repo.upsert_iv_point(sym, result, as_of_ts)
                except Exception as e:  # noqa: BLE001
                    stats["failed"] += 1
                    stats["errors"].append(
                        f"{sym}/{d_str}: upsert_exception:{type(e).__name__}:{e}"
                    )
                    continue

                if wrote:
                    stats["ok"] += 1
                    rows_written_dates.add(d_str)
                else:
                    stats["failed"] += 1
                    stats["errors"].append(f"{sym}/{d_str}: upsert_returned_false")

        # H9 verification: independent count per date this run touched.
        # Cannot use a single ``count_rows_for_date`` because the
        # backfill spans many dates; aggregate counts per date and
        # compare against handler-side stats.
        verification: Dict[str, int] = {}
        for d_str in sorted(rows_written_dates):
            try:
                verification[d_str] = iv_repo.count_rows_for_date(d_str)
            except Exception as e:  # noqa: BLE001
                # Treat as unverifiable rather than fatal.
                verification[d_str] = -1
                stats["errors"].append(f"verify {d_str}: {e}")

        # Audit row: success/failure + parameters for forensic
        # reconstruction. Mirrors the ``migration_apply`` pattern from
        # CLAUDE.md so future drift analysis can query backfill runs
        # the same way.
        try:
            client.table("risk_alerts").insert({
                "alert_type": "iv_historical_backfill",
                "severity": "info",
                "message": (
                    f"backfill: symbols={','.join(symbols)} days={days} "
                    f"ok={stats['ok']} failed={stats['failed']} "
                    f"skipped_existing={stats['skipped_existing']} "
                    f"missing_data={stats['missing_data']}"
                ),
                "metadata": {
                    "symbols": symbols,
                    "days": days,
                    "risk_free_rate": risk_free_rate,
                    "stats": {k: v for k, v in stats.items() if k != "errors"},
                    "verification": verification,
                    "errors_sample": stats["errors"][:20],
                    "doctrine_ref": "H9 verified-write across wrapper chains",
                },
            }).execute()
        except Exception as audit_err:  # noqa: BLE001
            print(f"[{JOB_NAME}] audit row write failed: {audit_err}")

        print(
            f"[{JOB_NAME}] Finished. stats={ {k:v for k,v in stats.items() if k!='errors'} } "
            f"verification_dates={len(verification)}"
        )
        return {
            "status": "ok",
            "stats": stats,
            "verification": verification,
            "symbols": symbols,
            "days": days,
            "risk_free_rate": risk_free_rate,
        }

    except Exception as e:
        print(f"[{JOB_NAME}] Job failed: {e}")
        traceback.print_exc()
        raise
