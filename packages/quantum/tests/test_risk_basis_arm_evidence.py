"""Durable arm evidence for the P0-B observe→enforce decision
(F-A4-RISKBASIS-SILENT, 2026-07-19) — OBSERVE-ONLY.

These drive the REAL natural-cycle comparison seams (``RiskBudgetEngine.compute``
open-book + ``utilization_gate.evaluate_entry`` candidate), with failures
injected at the DEEPEST callee, and assert on the top-level durable output — not
on source strings and not on a re-implemented copy of the logic.

Contract pinned:
- empty book → an EXPLICIT ``not_applicable_empty_book`` row (never silence);
- readable book, no flip / would flip → typed ``would_flip`` against the REAL
  threshold in play (deployable×2 dollars for the RBE, the % cap for the gate);
- partial max_loss_total coverage → counted + typed ``partial_max_loss_coverage``;
- a DB/read failure at the deepest read → fail-closed, decision unchanged, and
  NO fabricated flat-book arm row (H9 / "empty data is not a failed read");
- a durable-write (persist) fault → folds to ``counts.errors`` so the runner
  classifies the run ``partial`` (never silent);
- BOTH consumers record in one cycle;
- instrumentation ON vs OFF is byte-identical on the DECISION outputs.
"""
import pytest

from packages.quantum.services import risk_basis_shadow as rbs
from packages.quantum.risk import utilization_gate as ug
from packages.quantum.services.risk_budget_engine import RiskBudgetEngine
from packages.quantum.jobs.runner import _classify_handler_return


class _MockSB:  # RiskBudgetEngine only stores it; compute never touches it here
    pass


def _long_opt(cost_basis, qty=1, max_loss_total=None, **extra):
    p = {"asset_type": "OPTION", "quantity": qty, "cost_basis": cost_basis,
         "current_price": 1.0}
    if max_loss_total is not None:
        p["max_loss_total"] = max_loss_total
    p.update(extra)
    return p


def _rbe_row(collector):
    rows = [r for r in collector.rows if r["consumer"] == "rbe_open_book"]
    assert rows, "expected an rbe_open_book row"
    return rows[-1]


# ── RBE open-book consumer (real compute) ────────────────────────────────────

class TestRbeOpenBook:
    def test_empty_book_is_explicit_not_applicable(self):
        eng = RiskBudgetEngine(_MockSB())
        with rbs.arm_evidence_scope("c") as c:
            eng.compute("u", 10000.0, "normal", [])
        row = _rbe_row(c)
        assert row["status"] == "not_applicable_empty_book"
        assert row["unavailable_reason"] == "empty_book"
        assert row["position_count"] == 0
        assert row["would_flip"] is None
        assert row["honest_usd"] is None
        # never silence: the drained payload always exists
        payload = rbs._build_arm_payload(c.cycle_id, c.rows, c.errors)
        assert payload["consumers"]["rbe_open_book"] == 1

    def test_readable_book_no_flip(self):
        eng = RiskBudgetEngine(_MockSB())
        # deployable 10k → threshold 20k; honest 750 ≪ 20k → no flip.
        pos = _long_opt(-1.25, qty=2, max_loss_total=750.0,
                        max_loss_per_contract=375.0)
        with rbs.arm_evidence_scope("c") as c:
            eng.compute("u", 10000.0, "normal", [pos])
        row = _rbe_row(c)
        assert row["status"] == "ok"
        assert row["would_flip"] is False
        assert row["threshold_usd"] == 20000.0
        assert row["threshold_kind"] == "dollars"
        assert (row["coverage_readable"], row["coverage_total"]) == (1, 1)
        assert row["honest_basis"] == "max_loss_total"
        assert row["current_basis"] == "premium"

    def test_readable_book_would_flip(self):
        eng = RiskBudgetEngine(_MockSB())
        # deployable 1000 → threshold 2000. Current (legacy/premium) risk sum
        # 50 (≤2000), honest max_loss_total 3000 (>2000) → arming WOULD cross
        # the capital-mismatch trip. (The ~$0-book vs defined-risk gap is the
        # real P0-B shape the module was built to observe.)
        pos = _long_opt(1.0, qty=1, max_loss_total=3000.0,
                        max_loss_per_contract=50.0)
        with rbs.arm_evidence_scope("c") as c:
            eng.compute("u", 1000.0, "normal", [pos])
        row = _rbe_row(c)
        assert row["current_usd"] == 50.0
        assert row["honest_usd"] == 3000.0
        assert row["threshold_usd"] == 2000.0
        assert row["would_flip"] is True

    def test_incomplete_coverage_counted_and_typed(self):
        eng = RiskBudgetEngine(_MockSB())
        # two positions; only one carries max_loss_total → partial basis.
        priced = _long_opt(1.0, qty=1, max_loss_total=400.0)
        unpriced = _long_opt(1.0, qty=1)   # no max_loss_total
        with rbs.arm_evidence_scope("c") as c:
            eng.compute("u", 10000.0, "normal", [priced, unpriced])
        row = _rbe_row(c)
        assert (row["coverage_readable"], row["coverage_total"]) == (1, 2)
        assert row["position_count"] == 2
        assert row["status"] == "ok"
        assert row["unavailable_reason"] == "partial_max_loss_coverage"

    def test_zero_coverage_book_is_unavailable_not_fabricated(self):
        eng = RiskBudgetEngine(_MockSB())
        # positions exist but none carry max_loss_total → honest basis is
        # unavailable, NEVER fabricated to a number.
        with rbs.arm_evidence_scope("c") as c:
            eng.compute("u", 10000.0, "normal", [_long_opt(1.0), _long_opt(2.0)])
        row = _rbe_row(c)
        assert row["status"] == "unavailable"
        assert row["unavailable_reason"] == "no_usable_max_loss_total"
        assert row["honest_usd"] is None
        assert row["coverage_readable"] == 0
        assert row["coverage_total"] == 2

    def test_compute_decision_byte_identical_with_and_without_scope(self):
        eng = RiskBudgetEngine(_MockSB())
        pos = _long_opt(1.0, qty=1, max_loss_total=500.0)
        off = eng.compute("u", 10000.0, "normal", [pos])
        with rbs.arm_evidence_scope("c"):
            on = eng.compute("u", 10000.0, "normal", [pos])
        # the DECISION (report) is unchanged by observation
        assert on.regime == off.regime
        assert on.global_allocation == off.global_allocation


# ── utilization-gate candidate consumer (real evaluate_entry) ────────────────

@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setenv(ug.FLAG_ENV, "1")
    monkeypatch.setenv(ug.THRESHOLD_ENV, "0.85")


class _FakeAlpaca:
    def __init__(self, positions=None, raise_on_positions=None):
        self._positions = positions or []
        self._raise = raise_on_positions

    def get_positions(self):
        if self._raise is not None:
            raise self._raise
        return self._positions


class TestUtilizationCandidate:
    def _wire(self, monkeypatch, committed, obp):
        # committed capital is derived; short-circuit it for a deterministic gate
        monkeypatch.setattr(ug, "fetch_committed_capital", lambda: committed)
        monkeypatch.setattr(ug, "_get_obp", lambda uid, supabase=None: obp)

    def _ug_row(self, collector):
        rows = [r for r in collector.rows
                if r["consumer"] == "utilization_gate_candidate"]
        assert rows, "expected a utilization_gate_candidate row"
        return rows[-1]

    def test_allow_records_would_flip_true_against_real_cap(
        self, monkeypatch, gate_on
    ):
        # committed 600, obp 400, pool 1000, cap 0.85.
        # premium 250 → 0.85 ALLOW; honest 300 → 0.90 BLOCK → arming FLIPS.
        self._wire(monkeypatch, 600.0, 400.0)
        with rbs.arm_evidence_scope("c") as c:
            res = ug.evaluate_entry(
                "u", "QQQ", 250.0,
                arm_bases={"premium_usd": 250.0, "honest_usd": 300.0,
                           "context": {"symbol": "QQQ"}},
            )
        assert res["allowed"] is True
        row = self._ug_row(c)
        assert row["would_flip"] is True
        assert row["threshold_pct"] == 0.85
        assert row["threshold_kind"] == "utilization_pct"
        assert (row["coverage_readable"], row["coverage_total"]) == (1, 1)
        assert row["context"]["allowed"] is True

    def test_no_flip_when_honest_stays_under_cap(self, monkeypatch, gate_on):
        # premium 250 → 0.85 ALLOW; honest 240 → 0.84 ALLOW → no flip.
        self._wire(monkeypatch, 600.0, 400.0)
        with rbs.arm_evidence_scope("c") as c:
            ug.evaluate_entry(
                "u", "QQQ", 250.0,
                arm_bases={"premium_usd": 250.0, "honest_usd": 240.0},
            )
        assert self._ug_row(c)["would_flip"] is False

    def test_block_branch_still_records(self, monkeypatch, gate_on):
        # premium 900 → 0.90 BLOCK. Arm evidence records BEFORE the raise.
        self._wire(monkeypatch, 1500.0, 500.0)
        with rbs.arm_evidence_scope("c") as c:
            with pytest.raises(ug.EntryUtilizationBlocked):
                ug.evaluate_entry(
                    "u", "QQQ", 300.0,
                    arm_bases={"premium_usd": 300.0, "honest_usd": 300.0},
                )
        row = self._ug_row(c)
        assert row["context"]["allowed"] is False

    def test_honest_absent_is_unavailable(self, monkeypatch, gate_on):
        self._wire(monkeypatch, 600.0, 400.0)
        with rbs.arm_evidence_scope("c") as c:
            ug.evaluate_entry(
                "u", "QQQ", 250.0,
                arm_bases={"premium_usd": 250.0, "honest_usd": None},
            )
        row = self._ug_row(c)
        assert row["status"] == "unavailable"
        assert row["would_flip"] is None
        assert row["coverage_readable"] == 0

    def test_decision_byte_identical_with_and_without_arm_bases(
        self, monkeypatch, gate_on
    ):
        # instrumentation must not perturb the gate decision.
        self._wire(monkeypatch, 600.0, 400.0)
        base = ug.evaluate_entry("u", "QQQ", 250.0)  # no arm_bases, no scope
        with rbs.arm_evidence_scope("c"):
            instr = ug.evaluate_entry(
                "u", "QQQ", 250.0,
                arm_bases={"premium_usd": 250.0, "honest_usd": 300.0},
            )
        assert instr == base

    def test_deep_read_failure_is_fail_closed_no_fabricated_row(
        self, monkeypatch, gate_on
    ):
        # Inject at the DEEPEST callee: the OBP read raises. The gate must
        # fail-closed (decision unchanged — the entry is NOT waved through) and
        # NO arm row may be fabricated from the failed read.
        def _boom(uid, supabase=None):
            raise RuntimeError("obp provider down")

        monkeypatch.setattr(ug, "fetch_committed_capital", lambda: 600.0)
        monkeypatch.setattr(ug, "_get_obp", _boom)
        with rbs.arm_evidence_scope("c") as c:
            with pytest.raises(RuntimeError):
                ug.evaluate_entry(
                    "u", "QQQ", 250.0,
                    arm_bases={"premium_usd": 250.0, "honest_usd": 300.0},
                )
        ug_rows = [r for r in c.rows
                   if r["consumer"] == "utilization_gate_candidate"]
        assert ug_rows == []   # a failed read produced NO evidence, not a lie


# ── both consumers in one cycle ──────────────────────────────────────────────

class TestBothConsumersOneCycle:
    def test_rbe_and_utilization_both_recorded(self, monkeypatch):
        monkeypatch.setenv(ug.FLAG_ENV, "1")
        monkeypatch.setenv(ug.THRESHOLD_ENV, "0.85")
        monkeypatch.setattr(ug, "fetch_committed_capital", lambda: 600.0)
        monkeypatch.setattr(ug, "_get_obp", lambda uid, supabase=None: 400.0)
        eng = RiskBudgetEngine(_MockSB())
        with rbs.arm_evidence_scope("one-cycle") as c:
            eng.compute("u", 10000.0, "normal",
                        [_long_opt(1.0, max_loss_total=400.0)])
            ug.evaluate_entry(
                "u", "QQQ", 250.0,
                arm_bases={"premium_usd": 250.0, "honest_usd": 300.0},
            )
        consumers = {r["consumer"] for r in c.rows}
        assert consumers == {"rbe_open_book", "utilization_gate_candidate"}
        assert all(r["cycle_id"] == "one-cycle" for r in c.rows)
        # every row carries the full identity contract
        for r in c.rows:
            assert r["known_at"] and r["code_sha"]


# ── persistence into the durable sink + partial on write failure ─────────────

class TestPersistence:
    def test_merge_into_cycle_metadata_without_clobber(self):
        result = {"cycle_metadata": {"tier_taper": {"x": 1}}, "counts": {"errors": 0}}
        rows = [rbs.build_arm_evidence_row(
            "rbe_open_book", "c", current_usd=100.0, honest_usd=300.0,
            threshold_usd=200.0, position_count=1,
            coverage_readable=1, coverage_total=1)]
        out = rbs.persist_arm_evidence(result, rows, [], cycle_id="c")
        # sibling key preserved; ours added; no error folded on a clean run
        assert out["cycle_metadata"]["tier_taper"] == {"x": 1}
        assert out["cycle_metadata"]["risk_basis_arm_evidence"]["status"] == "ok"
        assert out["counts"]["errors"] == 0
        assert _classify_handler_return(out) == "succeeded"

    def test_empty_payload_is_explicit_not_silent(self):
        out = rbs.persist_arm_evidence({}, [], [], cycle_id="c")
        payload = out["cycle_metadata"]["risk_basis_arm_evidence"]
        assert payload["status"] == "empty"   # measured-empty marker, not absent
        assert payload["rows"] == []

    def test_durable_write_failure_folds_to_partial(self, monkeypatch):
        # Inject at the deepest persist callee: payload build raises.
        def _boom(cycle_id, rows, errors):
            raise RuntimeError("serialize failed")

        monkeypatch.setattr(rbs, "_build_arm_payload", _boom)
        result = {"executed_count": 3, "counts": {"errors": 0}}
        out = rbs.persist_arm_evidence(result, [{"consumer": "x"}], [], cycle_id="c")
        # never silent: folded to a typed error → runner classifies 'partial'
        assert out["counts"]["errors"] == 1
        assert _classify_handler_return(out) == "partial"
        # the DECISION output is untouched by the persistence fault
        assert out["executed_count"] == 3
        assert out["cycle_metadata"]["risk_basis_arm_evidence"]["status"] == "error"

    def test_seam_build_error_surfaces_at_drain(self, monkeypatch):
        # a build fault at the seam is captured as a typed collector error and
        # folds to partial at drain (never swallowed).
        def _boom(consumer, cycle_id, **kw):
            raise ValueError("bad row")

        with rbs.arm_evidence_scope("c") as c:
            monkeypatch.setattr(rbs, "build_arm_evidence_row", _boom)
            rbs.record_arm_evidence("rbe_open_book", current_usd=1.0, honest_usd=2.0)
        assert c.rows == []
        assert c.errors and "arm_evidence_build_failed" in c.errors[0]
        out = rbs.persist_arm_evidence({"counts": {"errors": 0}}, c.rows, c.errors, cycle_id="c")
        assert out["counts"]["errors"] == 1
        assert _classify_handler_return(out) == "partial"

    def test_no_active_scope_is_noop(self):
        # non-cycle callers (api / dev / morning) record nothing, never raise.
        assert rbs.record_arm_evidence("rbe_open_book", current_usd=1.0,
                                       honest_usd=2.0) is None


# ── handler wiring (drive the REAL paper_auto_execute.run entrypoint) ─────────

class TestHandlerWiring:
    """The handler must open the scope the buried seam records into, and drain
    it into job_runs.result.cycle_metadata. Driven end-to-end through the real
    run() entrypoint with the real utilization seam; only the service's heavy
    DB internals (out of scope) are stubbed."""

    def _install_fake_service(self, monkeypatch, exec_body):
        import packages.quantum.jobs.handlers.paper_auto_execute as pae

        class _FakeService:
            def __init__(self, client):
                pass

            def is_enabled(self):
                return True

            def execute_top_suggestions(self, user_id):
                return exec_body()

        monkeypatch.setattr(pae, "get_admin_client", lambda: object())
        monkeypatch.setattr(pae, "PaperAutopilotService", _FakeService)
        return pae

    def _run_real_seam(self, monkeypatch):
        # the real utilization seam, wired deterministically, executed WHILE the
        # handler's arm_evidence_scope is active.
        monkeypatch.setenv(ug.FLAG_ENV, "1")
        monkeypatch.setenv(ug.THRESHOLD_ENV, "0.85")
        monkeypatch.setattr(ug, "fetch_committed_capital", lambda: 600.0)
        monkeypatch.setattr(ug, "_get_obp", lambda uid, supabase=None: 400.0)

        def _body():
            ug.evaluate_entry(
                "u", "QQQ", 250.0,
                arm_bases={"premium_usd": 250.0, "honest_usd": 300.0,
                           "context": {"symbol": "QQQ"}},
            )
            return {"status": "ok", "executed_count": 1}

        return _body

    def test_run_drains_seam_evidence_into_cycle_metadata(self, monkeypatch):
        pae = self._install_fake_service(monkeypatch, self._run_real_seam(monkeypatch))
        out = pae.run({"user_id": "u"})
        payload = out["cycle_metadata"]["risk_basis_arm_evidence"]
        assert payload["consumers"].get("utilization_gate_candidate") == 1
        assert payload["rows"][0]["would_flip"] is True
        assert out["ok"] is True   # clean run stays green
        assert _classify_handler_return(out) == "succeeded"

    def test_run_persist_failure_makes_job_partial(self, monkeypatch):
        pae = self._install_fake_service(monkeypatch, self._run_real_seam(monkeypatch))

        def _boom(cycle_id, rows, errors):
            raise RuntimeError("serialize failed")

        monkeypatch.setattr(rbs, "_build_arm_payload", _boom)
        out = pae.run({"user_id": "u"})
        # never silent: folded to counts.errors → runner classifies 'partial'
        assert int(out["counts"]["errors"]) >= 1
        assert _classify_handler_return(out) == "partial"
        assert out["ok"] is False
        # the DECISION output is untouched by the persistence fault
        assert out["executed_count"] == 1

    def test_midday_run_drains_rbe_evidence_through_async(self, monkeypatch):
        # Proves contextvar propagation survives run_async(asyncio.run): the RBE
        # seam buried in the awaited run_midday_cycle records into the scope the
        # (sync) handler opened, and the drain reaches cycle_metadata.
        import packages.quantum.jobs.handlers.midday_scan as ms

        eng = RiskBudgetEngine(_MockSB())

        async def _fake_cycle(client, uid):
            eng.compute("u", 100.0, "normal",
                        [_long_opt(1.0, max_loss_total=5000.0,
                                   max_loss_per_contract=10.0)])
            return {"counts": {}}

        monkeypatch.setattr(ms, "get_admin_client", lambda: object())
        monkeypatch.setattr(ms, "get_active_user_ids", lambda c: ["u"])
        monkeypatch.setattr(ms, "run_midday_cycle", _fake_cycle)
        out = ms.run({})
        payload = out["cycle_metadata"]["risk_basis_arm_evidence"]
        assert payload["consumers"].get("rbe_open_book") == 1
        assert payload["rows"][0]["would_flip"] is True   # honest 5000 > thr 200
        assert out["ok"] is True
        assert _classify_handler_return(out) == "succeeded"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
