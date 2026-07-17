"""F-REBAL-COMPUTE — /rebalance/execute + /rebalance/preview contract regression.

Adjudicated 2026-07-16 (worktree @ b3cf45b): the 07-17 caller-trace claim
("compute(spread_positions, total_equity) against compute(user_id,
deployable_capital, regime_input, positions, ...) → guaranteed TypeError")
is CONFIRMED — and understated. Pre-fix, BOTH routes were dead on EVERY
input, via four independent contract breaks:

  1. non-empty book — ``Spread(**s)`` over the SpreadPosition OBJECTS that
     group_spread_positions actually returns raised
     ``TypeError: ... argument after ** must be a mapping`` (pydantic
     models are not mappings);
  2. empty book — ``RiskBudgetEngine.compute(spread_positions,
     total_equity)`` raised ``TypeError: ... missing 2 required positional
     arguments: 'regime_input' and 'positions'``;
  3. execute only — ``_compute_portfolio_weights(...,
     external_risk_scaler=...)``: no such parameter (the optimizer's kwarg
     is ``external_regime_snapshot``) → TypeError inside the optimizer
     thread → blanket 500;
  4. non-empty trades — ``t["ticker"]`` on generate_trades output, whose
     pinned contract is ``{"symbol", ...}`` → KeyError.

Shapes 1 and 2 are pinned below as named regression tests. Shape 3 is
pinned structurally: the endpoint tests drive the execute route through an
AUTOSPEC'd ``_compute_portfolio_weights`` (signature-enforcing — the old
kwarg would TypeError). Shape 4 is pinned by asserting the persisted /
returned rows carry the grouped tickers.

Doctrine: failures are injected at their ORIGIN (the DB rows / compute /
the optimizer callee) and truth asserted at the TOP (the HTTP response and
the recorded supabase operations). The REAL RiskBudgetEngine.compute and
the REAL RebalanceEngine.generate_trades run in the happy paths — fakes
exist only at the DB (supabase), regime/conviction service, and
market-data/optimizer boundaries.
"""

import contextlib
import os
import sys
import types
from types import SimpleNamespace
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Environment BEFORE importing the app module (same pattern as
# test_security_exception_leaks.py).
# ---------------------------------------------------------------------------
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault(
    "ENCRYPTION_KEY", "ke2AXS883XK_QFY9uLNGUiQlce1MifOaZNmmn06eoC8="
)
os.environ.setdefault("TASK_SIGNING_SECRET", "test-task-secret")
os.environ.setdefault("POLYGON_API_KEY", "test-polygon-key")

# Windows-local shim: rq's import raises ValueError (no 'fork' context) so
# packages.quantum.api — which transitively imports rq_enqueue at module
# level — is unimportable locally (the known 9-file fork class). CI (Linux)
# imports the real rq; the shim only engages where rq itself cannot load.
# Pattern copied from test_ops_health_q30_dedup.py.
try:  # pragma: no cover - environment-dependent
    import rq  # noqa: F401
except Exception:
    _rq_stub = types.ModuleType("rq")
    _rq_stub.Queue = type("Queue", (), {"__init__": lambda self, *a, **k: None})
    sys.modules["rq"] = _rq_stub

from fastapi.testclient import TestClient  # noqa: E402

from packages.quantum.api import app  # noqa: E402
from packages.quantum.core.rate_limiter import limiter  # noqa: E402
from packages.quantum.models import Spread, SpreadPosition  # noqa: E402
from packages.quantum.security import (  # noqa: E402
    get_current_user,
    get_supabase_user_client,
)
from packages.quantum.services.risk_budget_engine import (  # noqa: E402
    RiskBudgetEngine,
)

# The routes are 5/minute rate-limited; this module drives each more than
# five times. Determinism > exercising slowapi (not under test here).
limiter.enabled = False

client = TestClient(app)

def _route_auth_targets():
    """Resolve the ACTUAL dependency callables bound into the rebalance
    routes at request time. CI proved the module-level `from security
    import get_current_user` can bind a transient mock leaked by an
    earlier module's collection-time patch (route id != imported id,
    overrides keyed on the stale symbol never match). Route-resolved
    keys are immune to reload/patch timing by construction."""
    targets = set()
    for r in app.routes:
        if getattr(r, "path", "") in ("/rebalance/execute", "/rebalance/preview"):
            for d in r.dependant.dependencies:
                if d.call.__qualname__ in ("get_current_user",
                                           "get_supabase_user_client"):
                    targets.add(d.call)
    return targets


def _apply_auth_overrides(fake_sb):
    async def _fake_user():
        return USER_ID

    for call in _route_auth_targets():
        if call.__qualname__ == "get_current_user":
            app.dependency_overrides[call] = _fake_user
        else:
            app.dependency_overrides[call] = lambda: fake_sb
    # Belt-and-braces: also key the module-imported symbols (harmless
    # duplicates when identical; covers a hypothetical future where the
    # routes themselves are re-registered from fresh symbols).
    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_supabase_user_client] = lambda: fake_sb


def _diag(resp):
    """CI-truth diagnostic: why did the request not take the override path?"""
    import packages.quantum.api as _api
    from packages.quantum import security as _sec
    route_dep = None
    for r in _api.app.routes:
        if getattr(r, "path", "") == "/rebalance/execute":
            names = [(d.call.__module__, d.call.__qualname__, id(d.call))
                     for d in r.dependant.dependencies]
            route_dep = names
            break
    return (
        f"body={resp.text[:300]!r} "
        f"same_app={_api.app is app} "
        f"override_keys={[getattr(k, '__qualname__', k) for k in app.dependency_overrides]} "
        f"gcu_id={id(get_current_user)} sec_gcu_id={id(_sec.get_current_user)} "
        f"route_deps={route_dep}"
    )



USER_ID = "test-user-rebalance"
VERTICAL_TICKER = "SPY 2026-12-18 Call Debit Spread"
CONDOR_TICKER = "QQQ 2026-12-18"


# ---------------------------------------------------------------------------
# Fakes at the DB boundary
# ---------------------------------------------------------------------------
class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, ops_log, table_name, select_data):
        self._ops_log = ops_log
        self._table = table_name
        self._select_data = select_data
        self._op = "select"
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def eq(self, *a, **k):
        return self

    def delete(self, *a, **k):
        self._op = "delete"
        return self

    def insert(self, rows):
        self._op = "insert"
        self._payload = rows
        return self

    def execute(self):
        self._ops_log.append((self._table, self._op, self._payload))
        if self._op == "select":
            return _FakeResult(list(self._select_data.get(self._table, [])))
        if self._op == "insert":
            return _FakeResult(self._payload)
        return _FakeResult([])


class FakeSupabase:
    """Records every (table, op, payload) executed against it."""

    def __init__(self, positions_rows):
        self.ops = []
        self._data = {"positions": positions_rows}

    def table(self, name):
        return _FakeQuery(self.ops, name, self._data)


# ---------------------------------------------------------------------------
# Fakes at the regime / conviction / market-data boundaries
# ---------------------------------------------------------------------------
class _FakeGlobalSnap:
    def __init__(self):
        self.state = SimpleNamespace(value="normal")
        self.risk_score = 5.0
        self.risk_scaler = 1.0

    def to_dict(self):
        return {"state": "normal", "risk_score": self.risk_score}


class _FakeRegimeEngine:
    def __init__(self, *a, **k):
        pass

    def compute_global_snapshot(self, now, universe_symbols=None):
        return _FakeGlobalSnap()

    def compute_symbol_snapshot(self, ticker, global_snap):
        return SimpleNamespace(iv_rank=50.0)

    def get_effective_regime(self, sym_snap, global_snap):
        return SimpleNamespace(value="normal")

    def map_to_scoring_regime(self, state):
        return "normal"


class _FakeConvictionService:
    def __init__(self, *a, **k):
        pass

    def get_portfolio_conviction(self, *a, **k):
        return {}


class _ExplodingRiskBudgetEngine:
    """compute() failure injected at its origin (the engine itself)."""

    SECRET = "SECRET_COMPUTE_DETAIL_XYZ"

    def __init__(self, *a, **k):
        pass

    def compute(self, *a, **k):
        raise RuntimeError(self.SECRET)


def _portfolio_inputs_stub(unique_underlyings):
    n = len(unique_underlyings)
    return {
        "expected_returns": [0.05] * n,
        "covariance_matrix": [
            [0.04 if i == j else 0.01 for j in range(n)] for i in range(n)
        ],
    }


OPT_SECRET = "SECRET_OPT_DETAIL_XYZ"


# ---------------------------------------------------------------------------
# Position fixtures — representative defined-risk book:
# a SPY debit-call vertical + a QQQ 4-leg condor + a cash row.
# ---------------------------------------------------------------------------
def _book_rows():
    return [
        # SPY vertical (grouped -> spread_type "debit_call", value 200)
        {"symbol": "O:SPY261218C00600000", "quantity": 1, "cost_basis": 500.0,
         "current_price": 6.0, "current_value": 600.0, "user_id": USER_ID},
        {"symbol": "O:SPY261218C00610000", "quantity": -1, "cost_basis": -300.0,
         "current_price": 4.0, "current_value": -400.0, "user_id": USER_ID},
        # QQQ condor (4 legs, same expiry -> grouped structure, value 50)
        {"symbol": "O:QQQ261218P00470000", "quantity": 1, "cost_basis": 100.0,
         "current_price": 1.2, "current_value": 120.0, "user_id": USER_ID},
        {"symbol": "O:QQQ261218P00480000", "quantity": -1, "cost_basis": -60.0,
         "current_price": 0.8, "current_value": -80.0, "user_id": USER_ID},
        {"symbol": "O:QQQ261218C00520000", "quantity": -1, "cost_basis": -70.0,
         "current_price": 0.9, "current_value": -90.0, "user_id": USER_ID},
        {"symbol": "O:QQQ261218C00530000", "quantity": 1, "cost_basis": 80.0,
         "current_price": 1.0, "current_value": 100.0, "user_id": USER_ID},
        # Cash row (deployable basis for the rebalance context)
        {"symbol": "CUR:USD", "quantity": 1000.0, "current_price": 1.0,
         "current_value": 1000.0, "user_id": USER_ID},
    ]


# ---------------------------------------------------------------------------
# Harness: wire the ACTUAL routes with fakes only at the boundaries.
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _wired(fake_sb, weights=None, opt_exc=None, compute_explodes=False):
    _apply_auth_overrides(fake_sb)

    def _weights_side_effect(*a, **k):
        if opt_exc is not None:
            raise opt_exc
        tickers = a[3]
        w = weights or {}
        return (
            {t: w.get(t, 0.0) for t in tickers},
            {}, "slsqp", "trace-test-0001", "balanced", None, None, None,
        )

    try:
        with contextlib.ExitStack() as stack:
            handles = {}
            stack.enter_context(
                mock.patch("packages.quantum.api.RegimeEngineV3",
                           _FakeRegimeEngine))
            stack.enter_context(
                mock.patch("packages.quantum.api.ConvictionService",
                           _FakeConvictionService))
            stack.enter_context(
                mock.patch("packages.quantum.api.PolygonService",
                           mock.MagicMock()))
            stack.enter_context(
                mock.patch("packages.quantum.api.MarketDataTruthLayer",
                           mock.MagicMock()))
            stack.enter_context(
                mock.patch("packages.quantum.api.IVRepository",
                           mock.MagicMock()))
            stack.enter_context(
                mock.patch("packages.quantum.api.IVPointService",
                           mock.MagicMock()))
            handles["emit"] = stack.enter_context(
                mock.patch("packages.quantum.api.emit_trade_event"))
            stack.enter_context(
                mock.patch(
                    "packages.quantum.market_data.calculate_portfolio_inputs",
                    side_effect=_portfolio_inputs_stub))
            # autospec=True enforces the REAL _compute_portfolio_weights
            # signature — the pre-fix external_risk_scaler kwarg would
            # TypeError here (regression shape 3).
            handles["opt"] = stack.enter_context(
                mock.patch(
                    "packages.quantum.optimizer._compute_portfolio_weights",
                    autospec=True, side_effect=_weights_side_effect))
            if compute_explodes:
                stack.enter_context(
                    mock.patch("packages.quantum.api.RiskBudgetEngine",
                               _ExplodingRiskBudgetEngine))
            _apply_auth_overrides(fake_sb)  # re-apply post-patch-entry
            yield handles
    finally:
        for k in list(app.dependency_overrides):
            if getattr(k, "__qualname__", "") in (
                "get_current_user", "get_supabase_user_client"):
                del app.dependency_overrides[k]


def _tables_touched(fake_sb):
    return {t for (t, _op, _payload) in fake_sb.ops}


# ===========================================================================
# 1/2. Pre-fix TypeError shapes, pinned by name
# ===========================================================================
def test_regression_prefix_compute_call_shape_spread_positions_total_equity_raises_typeerror():
    """Pre-fix api.py called compute(spread_positions, total_equity).

    Against the real signature compute(user_id, deployable_capital,
    regime_input, positions, ...) that call is a guaranteed TypeError —
    the failure shape both /rebalance routes died with on an empty book.
    """
    engine = RiskBudgetEngine(mock.MagicMock())
    with pytest.raises(TypeError, match=r"missing 2 required positional arguments"):
        engine.compute([], 1250.0)


def test_regression_prefix_spread_kwargs_unpack_of_spreadposition_raises_typeerror():
    """Pre-fix api.py did `Spread(**s)` over group_spread_positions output.

    group_spread_positions returns SpreadPosition OBJECTS (options_utils),
    and pydantic models are not mappings — the failure shape both routes
    died with on any non-empty book, upstream of the compute call.
    """
    sp = SpreadPosition(
        id="x", user_id=USER_ID, spread_type="other", underlying="QQQ",
        ticker=CONDOR_TICKER, legs=[], net_cost=0.0, current_value=0.0,
        delta=0.0, gamma=0.0, vega=0.0, theta=0.0, quantity=1.0,
    )
    with pytest.raises(TypeError, match=r"must be a mapping"):
        Spread(**sp)


# ===========================================================================
# 3. Empty positions — both routes answer honestly, read-only
#    (pre-fix this exact input raised regression shape 2)
# ===========================================================================
def test_preview_empty_positions_ok_and_read_only():
    fake_sb = FakeSupabase([])
    with _wired(fake_sb):
        resp = client.post("/rebalance/preview")
    assert resp.status_code == 200, _diag(resp)
    body = resp.json()
    assert body["status"] == "ok"
    assert body["count"] == 0
    assert body["trades"] == []
    assert body["message"] == "No assets to rebalance"
    assert fake_sb.ops == [("positions", "select", None)]


def test_execute_empty_positions_ok_and_read_only():
    fake_sb = FakeSupabase([])
    with _wired(fake_sb):
        resp = client.post("/rebalance/execute")
    assert resp.status_code == 200, _diag(resp)
    body = resp.json()
    assert body["status"] == "ok"
    assert body["count"] == 0
    assert body["message"] == "No assets to rebalance"
    # No suggestion writes on the empty path
    assert fake_sb.ops == [("positions", "select", None)]


# ===========================================================================
# 4. Representative defined-risk book (vertical + condor), end-to-end
# ===========================================================================
def test_preview_vertical_and_condor_returns_trades_without_side_effects():
    fake_sb = FakeSupabase(_book_rows())
    weights = {VERTICAL_TICKER: 0.4, CONDOR_TICKER: 0.0}
    with _wired(fake_sb, weights=weights):
        resp = client.post("/rebalance/preview")

    assert resp.status_code == 200, _diag(resp)
    body = resp.json()
    assert body["status"] == "ok"
    assert body["count"] == 2
    tickers = {t["ticker"] for t in body["trades"]}
    assert tickers == {VERTICAL_TICKER, CONDOR_TICKER}

    # The REAL RiskBudgetEngine.compute ran with the corrected contract and
    # its report threads through to the response.
    rs = body["risk_summary"]
    assert rs["user_id"] == USER_ID
    assert rs["regime"] == "NORMAL"
    assert rs["deployable_capital"] == 1000.0
    assert "global_allocation" in rs

    # Preview is side-effect free at the DB boundary: reads only.
    assert fake_sb.ops == [("positions", "select", None)]


def test_execute_vertical_and_condor_persists_suggestions_no_broker_path():
    fake_sb = FakeSupabase(_book_rows())
    weights = {VERTICAL_TICKER: 0.4, CONDOR_TICKER: 0.0}
    with _wired(fake_sb, weights=weights) as handles:
        resp = client.post("/rebalance/execute")

    assert resp.status_code == 200, _diag(resp)
    body = resp.json()
    assert body["status"] == "ok"
    assert body["count"] == 2

    # Side-effect boundary: execute's ONLY write path is trade_suggestions
    # (delete stale rebalance window, insert pending suggestions). It never
    # touches a broker — that shape predates the breakage and is preserved.
    assert _tables_touched(fake_sb) == {"positions", "trade_suggestions"}
    ops = [(t, op) for (t, op, _p) in fake_sb.ops]
    assert ("trade_suggestions", "delete") in ops
    inserts = [p for (t, op, p) in fake_sb.ops
               if t == "trade_suggestions" and op == "insert"]
    assert len(inserts) == 1
    rows = inserts[0]
    assert len(rows) == 2
    assert {r["symbol"] for r in rows} == {VERTICAL_TICKER, CONDOR_TICKER}
    for r in rows:
        assert r["user_id"] == USER_ID
        assert r["window"] == "rebalance"
        assert r["status"] == "pending"
        assert r["trace_id"]  # v3 traceability stamped

    # Telemetry emitted once per persisted suggestion
    assert handles["emit"].call_count == 2


# ===========================================================================
# 5. Failure truth — compute failure => explicit typed error, no leak,
#    no silent empty success
# ===========================================================================
def test_execute_compute_failure_returns_typed_500_no_leak():
    fake_sb = FakeSupabase(_book_rows())
    with _wired(fake_sb, compute_explodes=True):
        with mock.patch.dict(os.environ, {"APP_ENV": "production"}):
            resp = client.post("/rebalance/execute")
    assert resp.status_code == 500, _diag(resp)
    assert resp.json()["detail"] == "Risk budget computation failed"
    assert _ExplodingRiskBudgetEngine.SECRET not in resp.text
    # Failure never reaches the write path
    assert _tables_touched(fake_sb) == {"positions"}


def test_preview_compute_failure_returns_typed_error_payload_no_leak():
    fake_sb = FakeSupabase(_book_rows())
    with _wired(fake_sb, compute_explodes=True):
        with mock.patch.dict(os.environ, {"APP_ENV": "production"}):
            resp = client.post("/rebalance/preview")
    assert resp.status_code == 200, _diag(resp)
    body = resp.json()
    assert body["status"] == "error"
    assert body["message"] == "Risk budget computation failed"
    assert body["trades"] == []
    assert _ExplodingRiskBudgetEngine.SECRET not in resp.text
    assert fake_sb.ops == [("positions", "select", None)]


# ===========================================================================
# 6. Failure truth — optimizer failure => explicit typed error, no leak
#    (failure injected at the deepest callee the route reaches)
# ===========================================================================
def test_execute_optimizer_failure_returns_typed_500_no_leak():
    fake_sb = FakeSupabase(_book_rows())
    with _wired(fake_sb, opt_exc=RuntimeError(OPT_SECRET)):
        with mock.patch.dict(os.environ, {"APP_ENV": "production"}):
            resp = client.post("/rebalance/execute")
    assert resp.status_code == 500, _diag(resp)
    assert resp.json()["detail"] == "Optimization failed"
    assert OPT_SECRET not in resp.text
    assert _tables_touched(fake_sb) == {"positions"}


def test_preview_optimizer_failure_returns_typed_error_payload_no_leak():
    fake_sb = FakeSupabase(_book_rows())
    with _wired(fake_sb, opt_exc=RuntimeError(OPT_SECRET)):
        with mock.patch.dict(os.environ, {"APP_ENV": "production"}):
            resp = client.post("/rebalance/preview")
    assert resp.status_code == 200, _diag(resp)
    body = resp.json()
    assert body["status"] == "error"
    assert body["message"] == "Optimization failed"
    assert body["trades"] == []
    assert OPT_SECRET not in resp.text
    assert fake_sb.ops == [("positions", "select", None)]
