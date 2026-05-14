"""Manual validation harness for α historical IV backfill.

NOT run by CI. Operator runs this against a live Polygon API key to
sanity-check a few reconstructed IV30 points against an independent
source (barchart.com / TradingView / a manual BS calculation).

Pass criterion (per α design spec): ≥ 2/3 reference symbols must
produce a reconstructed IV30 within ±10 IV percentile points of the
operator-supplied reference value. Exit code 0 on pass, 1 on fail.

Usage:
    POLYGON_API_KEY=... python -m packages.quantum.tests.validate_alpha_backfill

The harness prompts for each reference value rather than baking them
in, because IV percentiles drift weekly. The operator looks up the
target on barchart.com (or equivalent) at validation time.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

from packages.quantum.market_data import PolygonService
from packages.quantum.services.historical_iv_service import HistoricalIVService

# Reference symbols per α design spec.
REFERENCE_SYMBOLS = ["SPY", "AAPL", "AMD"]

# Allowed deviation in IV percentile points (raw IV * 100).
TOLERANCE_PCT_POINTS = 10.0


def _prompt_float(label: str) -> float:
    while True:
        raw = input(f"{label}: ").strip()
        try:
            return float(raw)
        except ValueError:
            print("  (please enter a number, e.g. 0.18 or 18.5)")


def main() -> int:
    if not os.getenv("POLYGON_API_KEY"):
        print("ERROR: POLYGON_API_KEY not set in environment.")
        return 1

    polygon = PolygonService()
    svc = HistoricalIVService(polygon_service=polygon, risk_free_rate=0.045)

    # Pick a recent past Friday (markets always open) as the reference
    # date. Operator can override via CLI if needed.
    today = date.today()
    while today.weekday() != 4:  # 4 = Friday
        today -= timedelta(days=1)
    reference_date = today - timedelta(days=7)

    print(f"Validating reconstructed IV30 for {reference_date}\n")
    print("For each symbol, look up the historical IV30 on")
    print("  barchart.com → Options → Volatility & Greeks → IV (30d)")
    print("at the same date, and enter as a decimal (e.g. 0.18 for 18%).\n")

    results = []
    for sym in REFERENCE_SYMBOLS:
        print(f"\n--- {sym} ---")
        reconstructed = svc.compute_historical_iv_point(sym, reference_date)
        if reconstructed is None or reconstructed.get("iv") is None:
            print(f"  ✗ {sym}: reconstruction returned no IV")
            results.append((sym, None, None, False))
            continue

        recon_iv = reconstructed["iv"]
        print(f"  reconstructed IV30: {recon_iv:.4f} ({recon_iv*100:.2f}%)")

        reference = _prompt_float(f"  barchart IV30 for {sym} on {reference_date}")
        delta_pct_points = abs(recon_iv - reference) * 100.0
        passed = delta_pct_points <= TOLERANCE_PCT_POINTS

        marker = "✓" if passed else "✗"
        print(
            f"  {marker} delta = {delta_pct_points:.2f} pct-points "
            f"(tolerance ±{TOLERANCE_PCT_POINTS})"
        )
        results.append((sym, recon_iv, reference, passed))

    passes = sum(1 for r in results if r[3])
    print(f"\n=== Result: {passes}/{len(REFERENCE_SYMBOLS)} symbols passed ===")
    return 0 if passes >= 2 else 1


if __name__ == "__main__":
    sys.exit(main())
