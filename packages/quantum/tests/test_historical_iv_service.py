"""Unit tests for ``HistoricalIVService`` with a mocked PolygonService.

Verifies:
- Chain reconstruction produces the dict shape that
  ``IVPointService.compute_atm_iv_target_from_chain`` expects
- IV interpolation runs end-to-end against the reconstructed chain
- Per-(symbol, date) failures (no spot, no contracts, no prices) are
  isolated and return None cleanly
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from packages.quantum.services.bs_inversion import bs_call_price, bs_put_price
from packages.quantum.services.historical_iv_service import HistoricalIVService


def _build_fake_polygon(spot: float, sigma: float, as_of: date) -> MagicMock:
    """Return a MagicMock PolygonService that:
    - returns ``spot`` from ``get_historical_spot_price``
    - returns a small chain of calls + puts around the ATM strike
      from ``get_option_contract_candidates``
    - returns BS-priced (with σ=``sigma``) historical close from
      ``get_option_historical_prices``

    Round-trip: prices generated from σ should invert back to σ in the
    service, which then interpolates through IVPointService and yields
    an IV30 ≈ σ.
    """
    poly = MagicMock()

    # Build a chain spanning ATM ±10% strike, two expiries (21d + 49d).
    contracts_by_right: Dict[str, List[Dict[str, Any]]] = {"call": [], "put": []}
    strikes = [round(spot * m, 0) for m in [0.92, 0.96, 1.00, 1.04, 1.08]]
    expiries = [as_of + timedelta(days=21), as_of + timedelta(days=49)]

    for right in ("call", "put"):
        for K in strikes:
            for exp in expiries:
                occ = f"O:FAKE{exp.strftime('%y%m%d')}{right[0].upper()}{int(K*1000):08d}"
                contracts_by_right[right].append({
                    "ticker": occ,
                    "strike": K,
                    "expiration": exp.isoformat(),
                    "type": right,
                    "underlying": "FAKE",
                })

    def fake_candidates(
        underlying, as_of_date, right, exp_start, exp_end,
        strike_min, strike_max, limit=1000,
    ):
        return [
            c for c in contracts_by_right[right]
            if strike_min <= c["strike"] <= strike_max
        ]

    def fake_historical_prices(option_symbol, start_date, end_date):
        # Parse contract details from the OCC symbol we constructed
        # above. Layout: O:FAKE{yymmdd}{C|P}{strike*1000 in 8 digits}
        s = option_symbol.replace("O:FAKE", "")
        yy, mm, dd = int(s[0:2]), int(s[2:4]), int(s[4:6])
        right_char = s[6]
        strike = int(s[7:15]) / 1000.0
        exp = date(2000 + yy, mm, dd)
        right = "call" if right_char == "C" else "put"
        T = max((exp - as_of).days / 365.0, 1e-6)
        pricer = bs_call_price if right == "call" else bs_put_price
        price = pricer(spot, strike, T, 0.045, 0.0, sigma)
        return {
            "symbol": option_symbol,
            "dates": [as_of.isoformat()],
            "prices": [price],
            "opens": [price],
            "highs": [price],
            "lows": [price],
            "volumes": [100],
        }

    poly.get_historical_spot_price.return_value = spot
    poly.get_option_contract_candidates.side_effect = fake_candidates
    poly.get_option_historical_prices.side_effect = fake_historical_prices
    return poly


def test_reconstruct_chain_produces_iv_point_service_shape():
    as_of = date(2026, 4, 1)
    poly = _build_fake_polygon(spot=100.0, sigma=0.25, as_of=as_of)
    svc = HistoricalIVService(polygon_service=poly, risk_free_rate=0.045)

    chain = svc.reconstruct_chain_at_date("FAKE", as_of, spot=100.0)

    assert chain, "chain reconstruction should produce some contracts"

    for c in chain:
        assert "details" in c
        assert "strike_price" in c["details"]
        assert "contract_type" in c["details"]
        assert "expiration_date" in c["details"]
        assert c["details"]["contract_type"] in ("call", "put")
        assert "implied_volatility" in c
        assert 0.20 < c["implied_volatility"] < 0.30, (
            f"recovered IV {c['implied_volatility']} out of expected band "
            f"around input σ=0.25"
        )


def test_compute_historical_iv_point_full_pipeline():
    as_of = date(2026, 4, 1)
    poly = _build_fake_polygon(spot=100.0, sigma=0.25, as_of=as_of)
    svc = HistoricalIVService(polygon_service=poly, risk_free_rate=0.045)

    result = svc.compute_historical_iv_point("FAKE", as_of)

    assert result is not None
    assert result.get("iv") is not None
    # IV30 from a constant-σ chain should be very close to that σ.
    assert abs(result["iv"] - 0.25) < 0.02, f"got iv={result['iv']}"
    assert result["inputs"]["backfill"] is True
    assert result["inputs"]["risk_free_rate"] == 0.045


def test_compute_historical_iv_point_no_spot_returns_none():
    poly = MagicMock()
    poly.get_historical_spot_price.return_value = None
    svc = HistoricalIVService(polygon_service=poly)
    assert svc.compute_historical_iv_point("FAKE", date(2026, 4, 1)) is None


def test_compute_historical_iv_point_no_contracts_returns_none():
    poly = MagicMock()
    poly.get_historical_spot_price.return_value = 100.0
    poly.get_option_contract_candidates.return_value = []
    svc = HistoricalIVService(polygon_service=poly)
    assert svc.compute_historical_iv_point("FAKE", date(2026, 4, 1)) is None


def test_compute_historical_iv_point_no_prices_returns_none():
    """Contracts exist but daily-aggregate returns None for each →
    chain stays empty → result is None."""
    as_of = date(2026, 4, 1)
    poly = _build_fake_polygon(spot=100.0, sigma=0.25, as_of=as_of)
    poly.get_option_historical_prices.side_effect = lambda *a, **kw: None
    svc = HistoricalIVService(polygon_service=poly)
    assert svc.compute_historical_iv_point("FAKE", as_of) is None
