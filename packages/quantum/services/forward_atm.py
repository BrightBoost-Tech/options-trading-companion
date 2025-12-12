from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple
import math

@dataclass
class ForwardATMResult:
    forward_price: Optional[float]
    atm_strike: Optional[float]
    method: str  # "regression" | "zero_cross" | "min_abs" | "fallback_spot"
    diagnostics: Dict[str, Any]

def _safe_mid(bid, ask) -> Optional[float]:
    try:
        if bid is None or ask is None:
            return None
        bid = float(bid)
        ask = float(ask)
        if ask <= 0 or bid < 0:
            return None
        if bid > ask:  # crossed
            return None
        return (bid + ask) / 2.0
    except Exception:
        return None

def compute_forward_atm_from_parity(
    calls: List[Dict[str, Any]],
    puts: List[Dict[str, Any]],
    spot: float,
    *,
    near_pct: float = 0.10,
    max_spread_ratio: float = 0.35,  # drop very wide quotes
    min_points: int = 4,
) -> ForwardATMResult:
    """
    Uses same-strike put-call parity on mids:
      diff(K) = callMid(K) - putMid(K)
    Forward is where diff(K) crosses 0 (or via regression).
    """
    # 1) index by strike
    c_by_k = {}
    for c in calls:
        k = c.get("strike")
        if k is None:
            continue
        q = c.get("quote") or {}
        mid = q.get("mid")
        if mid is None:
            mid = _safe_mid(q.get("bid"), q.get("ask"))
        if mid is None:
            continue
        c_by_k[float(k)] = {"mid": float(mid), "bid": q.get("bid"), "ask": q.get("ask")}

    p_by_k = {}
    for p in puts:
        k = p.get("strike")
        if k is None:
            continue
        q = p.get("quote") or {}
        mid = q.get("mid")
        if mid is None:
            mid = _safe_mid(q.get("bid"), q.get("ask"))
        if mid is None:
            continue
        p_by_k[float(k)] = {"mid": float(mid), "bid": q.get("bid"), "ask": q.get("ask")}

    strikes = sorted(set(c_by_k.keys()).intersection(set(p_by_k.keys())))
    if not strikes:
        return ForwardATMResult(None, None, "fallback_spot", {"reason": "no_overlap_strikes"})

    # 2) near-ATM filter around spot
    lo = spot * (1.0 - near_pct)
    hi = spot * (1.0 + near_pct)
    strikes = [k for k in strikes if lo <= k <= hi]
    if len(strikes) < 2:
        return ForwardATMResult(None, None, "fallback_spot", {"reason": "too_few_near_points", "count": len(strikes)})

    # 3) build points with spread filtering
    pts = []
    for k in strikes:
        cm = c_by_k[k]["mid"]
        pm = p_by_k[k]["mid"]
        diff = cm - pm

        # crude spread ratio filter (optional but helpful)
        def spr_ratio(side):
            bid = side.get("bid")
            ask = side.get("ask")
            m = side.get("mid")
            if bid is None or ask is None or m is None or m <= 0:
                return 0.0
            try:
                bid = float(bid)
                ask = float(ask)
                return max(0.0, (ask - bid) / m)
            except Exception:
                return 0.0

        sr = max(spr_ratio(c_by_k[k]), spr_ratio(p_by_k[k]))
        if sr > max_spread_ratio:
            continue

        w = 1.0 / (abs(k - spot) + 1e-6)  # weight closer strikes more
        pts.append((k, diff, w))

    if len(pts) < 2:
        return ForwardATMResult(None, None, "fallback_spot", {"reason": "too_few_points_after_filters", "count": len(pts)})

    # 4A) regression diff = a + b*K (weighted)
    # Solve weighted least squares for a,b
    sw = sum(w for _,_,w in pts)
    sx = sum(w*k for k,_,w in pts)
    sy = sum(w*y for _,y,w in pts)
    sxx = sum(w*k*k for k,_,w in pts)
    sxy = sum(w*k*y for k,y,w in pts)

    denom = (sw * sxx - sx * sx)
    if abs(denom) > 1e-12:
        b = (sw * sxy - sx * sy) / denom
        a = (sy - b * sx) / sw
        if b < -1e-9:
            f = -a / b
            atm = min([k for k,_,_ in pts], key=lambda kk: abs(kk - f))
            return ForwardATMResult(float(f), float(atm), "regression", {"a": a, "b": b, "points": len(pts)})

    # 4B) zero-cross interpolation
    pts_sorted = sorted(pts, key=lambda t: t[0])
    for (k1, d1, _), (k2, d2, _) in zip(pts_sorted, pts_sorted[1:]):
        if d1 == 0:
            return ForwardATMResult(float(k1), float(k1), "zero_cross", {"points": len(pts)})
        if (d1 < 0 and d2 > 0) or (d1 > 0 and d2 < 0):
            f = k1 + (0 - d1) * (k2 - k1) / (d2 - d1)
            atm = min([k for k,_,_ in pts], key=lambda kk: abs(kk - f))
            return ForwardATMResult(float(f), float(atm), "zero_cross", {"points": len(pts)})

    # 4C) min abs diff fallback
    k_best, d_best, _ = min(pts, key=lambda t: abs(t[1]))
    return ForwardATMResult(float(k_best), float(k_best), "min_abs", {"best_diff": d_best, "points": len(pts)})
