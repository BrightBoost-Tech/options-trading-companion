"""Deterministic offline/prequential evaluator tests (queue-⑤).

Pins:
1. EXACT hand-computed Brier / EV-RMSE / realized-net on a mini-fixture.
2. Censoring (open outcomes) and malformed resolved rows: excluded + counted.
3. Typed abstention drives coverage; never scored as a coin flip.
4. Calibration buckets: typed InsufficientSamples below the floor, exact
   bucket contents above it.
5. raw vs calibrated are SEPARATE reports (read-only multiplier application).
6. Determinism: input order cannot change the report.
7. Segment identity (strategy/regime/DTE bucket) metrics.
8. head_to_head compares on the JOINT scored set only.
9. records_from_rows: pure mapping, skips are explicit, never defaulted.
10. Seeded end-to-end fixture: frozen baseline (EV identically 0) vs
    lognormal challenger through the same evaluator.
"""

import math
import random

import pytest

from packages.quantum.analytics.terminal_distribution import (
    DistributionInputs,
    EvalRecord,
    LegSpec,
    OutcomeRecord,
    Provenance,
    SegmentKey,
    StrategyEvaluation,
    StructureSpec,
    Unavailable,
    baseline_credit_vertical,
    challenger_lognormal_evaluate,
    evaluate_model,
    head_to_head,
    records_from_rows,
    with_production_multipliers,
)

SEG_A = SegmentKey(strategy="credit_vertical", regime="bull", dte_bucket="21-45")
SEG_B = SegmentKey(strategy="credit_vertical", regime="bear", dte_bucket="0-20")


def valid_structure(credit: float = 1.0) -> StructureSpec:
    return StructureSpec(
        strategy="credit_vertical",
        legs=(
            LegSpec(action="sell", option_type="call", strike=105.0, iv=0.25, delta=0.30),
            LegSpec(action="buy", option_type="call", strike=110.0, iv=0.24, delta=0.15),
        ),
        net_premium=credit,
    )


def record(record_id, known_at, status="resolved", win=None, pnl=None, segment=SEG_A, spot=100.0):
    return EvalRecord(
        record_id=record_id,
        structure=valid_structure(),
        dist_inputs=DistributionInputs(spot=spot, dte_days=30.0, known_at=known_at),
        outcome=OutcomeRecord(status=status, realized_win=win, realized_pnl=pnl),
        segment=segment,
    )


def stub_model(table):
    """Model keyed by record_id: (pop, ev) tuples or Unavailable."""

    def fn(rec: EvalRecord):
        entry = table[rec.record_id]
        if isinstance(entry, Unavailable):
            return entry
        pop, ev = entry
        return StrategyEvaluation(
            strategy="credit_vertical",
            model="stub",
            pop=pop,
            expected_value=ev,
            basis="raw",
            max_gain=100.0,
            max_loss=100.0,
            breakevens=(),
            provenance=Provenance(source="stub", version="1", params_hash="0" * 16),
        )

    return fn


MINI_TABLE = {
    "r1": (0.8, 50.0),
    "r2": (0.6, 30.0),
    "r3": (0.3, -10.0),
    "r4": (0.5, 0.0),  # censored before the model is ever called
    "r5": Unavailable("missing_iv", "fixture abstention", "stub"),
}

MINI_RECORDS = [
    record("r1", "2026-06-01T15:00:00Z", win=True, pnl=40.0, segment=SEG_A),
    record("r2", "2026-06-02T15:00:00Z", win=False, pnl=-60.0, segment=SEG_A),
    record("r3", "2026-06-03T15:00:00Z", win=False, pnl=-20.0, segment=SEG_B),
    record("r4", "2026-06-04T15:00:00Z", status="open"),
    record("r5", "2026-06-05T15:00:00Z", win=True, pnl=10.0, segment=SEG_B),
]


class TestHandComputedMetrics:
    def test_exact_brier_rmse_net_and_counts(self):
        report = evaluate_model(stub_model(MINI_TABLE), MINI_RECORDS, model_label="stub")
        assert report.total == 5
        assert report.censored == 1
        assert report.malformed == 0
        assert report.abstained == 1
        assert report.scored == 3
        assert report.eligible == 4
        assert report.coverage == pytest.approx(0.75)
        # Brier = ((0.8-1)^2 + (0.6-0)^2 + (0.3-0)^2) / 3 = 0.49/3
        assert report.brier == pytest.approx(0.49 / 3, abs=1e-12)
        # EV-RMSE = sqrt(((50-40)^2 + (30+60)^2 + (-10+20)^2) / 3) = sqrt(8300/3)
        assert report.ev_rmse == pytest.approx(math.sqrt(8300.0 / 3.0), abs=1e-9)
        # Realized net over the SCORED set: 40 - 60 - 20 = -40
        assert report.realized_net == pytest.approx(-40.0)
        assert report.basis == "raw"

    def test_malformed_resolved_row_counted_not_coerced(self):
        records = MINI_RECORDS + [record("r6", "2026-06-06T15:00:00Z", win=True, pnl=None)]
        table = dict(MINI_TABLE)
        table["r6"] = (0.9, 5.0)
        report = evaluate_model(stub_model(table), records, model_label="stub")
        assert report.malformed == 1
        assert report.scored == 3  # r6 never scored

    def test_abstention_never_scored_as_coin_flip(self):
        report = evaluate_model(stub_model(MINI_TABLE), MINI_RECORDS, model_label="stub")
        r5 = next(r for r in report.predictions if r.record_id == "r5")
        assert r5.scored is False
        assert r5.pop is None
        assert r5.abstain_reason == "missing_iv"


class TestCalibrationBuckets:
    def test_insufficient_samples_is_typed(self):
        report = evaluate_model(
            stub_model(MINI_TABLE), MINI_RECORDS, model_label="stub", min_calibration_n=5
        )
        from packages.quantum.analytics.terminal_distribution.evaluator import InsufficientSamples

        assert isinstance(report.calibration, InsufficientSamples)
        assert report.calibration.n == 3
        assert report.calibration.required == 5

    def test_bucket_contents_when_n_permits(self):
        report = evaluate_model(
            stub_model(MINI_TABLE), MINI_RECORDS, model_label="stub", min_calibration_n=3
        )
        buckets = report.calibration
        assert isinstance(buckets, tuple)
        assert len(buckets) == 3
        by_lo = {b.lo: b for b in buckets}
        assert by_lo[0.2].n == 1 and by_lo[0.2].realized_rate == 0.0
        assert by_lo[0.2].mean_pop == pytest.approx(0.3)
        assert by_lo[0.6].n == 1 and by_lo[0.6].realized_rate == 0.0
        assert by_lo[0.8].n == 1 and by_lo[0.8].realized_rate == 1.0


class TestCalibratedBasisSeparation:
    def test_multipliers_produce_separate_calibrated_report(self):
        raw_report = evaluate_model(stub_model(MINI_TABLE), MINI_RECORDS, model_label="stub")
        calibrated_fn = with_production_multipliers(
            stub_model(MINI_TABLE), pop_multiplier=1.25, ev_multiplier=0.5
        )
        cal_report = evaluate_model(
            calibrated_fn, MINI_RECORDS, model_label="stub", basis="calibrated"
        )
        # Raw untouched.
        assert raw_report.basis == "raw"
        assert raw_report.brier == pytest.approx(0.49 / 3, abs=1e-12)
        # Calibrated pops: 0.8*1.25 -> clamp 1.0; 0.6*1.25 = 0.75; 0.3*1.25 = 0.375
        # Brier_cal = ((1-1)^2 + (0.75-0)^2 + (0.375-0)^2)/3 = (0.5625+0.140625)/3
        assert cal_report.basis == "calibrated"
        assert cal_report.brier == pytest.approx((0.5625 + 0.140625) / 3, abs=1e-12)
        # Calibrated EVs: 25, 15, -5 -> RMSE = sqrt((225 + 5625 + 225)/3)
        assert cal_report.ev_rmse == pytest.approx(math.sqrt(6075.0 / 3.0), abs=1e-9)
        # Abstentions pass through untouched.
        assert cal_report.abstained == 1

    def test_calibrated_result_objects_are_labeled(self):
        calibrated_fn = with_production_multipliers(
            stub_model(MINI_TABLE), pop_multiplier=1.25, ev_multiplier=0.5
        )
        out = calibrated_fn(MINI_RECORDS[0])
        assert isinstance(out, StrategyEvaluation)
        assert out.basis == "calibrated"
        assert out.model == "stub+calibrated"
        # And the raw model still emits raw.
        raw = stub_model(MINI_TABLE)(MINI_RECORDS[0])
        assert raw.basis == "raw"


class TestDeterminism:
    def test_input_order_cannot_change_the_report(self):
        fn = stub_model(MINI_TABLE)
        forward = evaluate_model(fn, MINI_RECORDS, model_label="stub")
        shuffled = evaluate_model(fn, list(reversed(MINI_RECORDS)), model_label="stub")
        assert forward == shuffled

    def test_predictions_in_prequential_order(self):
        report = evaluate_model(stub_model(MINI_TABLE), list(reversed(MINI_RECORDS)), model_label="stub")
        ids = [r.record_id for r in report.predictions]
        assert ids == ["r1", "r2", "r3", "r5"]  # known_at order; r4 censored


class TestSegments:
    def test_segment_metrics(self):
        report = evaluate_model(stub_model(MINI_TABLE), MINI_RECORDS, model_label="stub")
        segments = dict(report.segments)
        assert set(segments) == {SEG_A, SEG_B}
        assert segments[SEG_A].n_scored == 2
        assert segments[SEG_A].realized_net == pytest.approx(-20.0)  # 40 - 60
        assert segments[SEG_B].n_scored == 1
        assert segments[SEG_B].realized_net == pytest.approx(-20.0)
        # Segment A Brier = ((0.8-1)^2 + (0.6-0)^2)/2 = 0.4/2
        assert segments[SEG_A].brier == pytest.approx(0.2, abs=1e-12)


class TestHeadToHead:
    def test_joint_scored_set_only(self):
        table_b = dict(MINI_TABLE)
        table_b["r1"] = Unavailable("missing_iv", "model B abstains on r1", "stub")
        table_b["r5"] = (0.7, 20.0)
        report_a = evaluate_model(stub_model(MINI_TABLE), MINI_RECORDS, model_label="A")
        report_b = evaluate_model(stub_model(table_b), MINI_RECORDS, model_label="B")
        h2h = head_to_head(report_a, report_b)
        # A scored {r1,r2,r3}; B scored {r2,r3,r5} -> joint {r2,r3}
        assert h2h.n_joint == 2
        # Joint Brier A = ((0.6-0)^2 + (0.3-0)^2)/2 = 0.45/2
        assert h2h.brier_a == pytest.approx(0.225, abs=1e-12)
        assert h2h.realized_net_joint == pytest.approx(-80.0)

    def test_empty_joint_set_is_typed_none(self):
        table_b = {k: Unavailable("missing_iv", "always abstains", "stub") for k in MINI_TABLE}
        report_a = evaluate_model(stub_model(MINI_TABLE), MINI_RECORDS, model_label="A")
        report_b = evaluate_model(stub_model(table_b), MINI_RECORDS, model_label="B")
        h2h = head_to_head(report_a, report_b)
        assert h2h.n_joint == 0
        assert h2h.brier_a is None and h2h.brier_b is None


class TestRecordsFromRows:
    def test_good_row_maps_and_bad_row_skips_explicitly(self):
        rows = [
            {
                "record_id": "s1",
                "known_at": "2026-06-01T15:00:00Z",
                "strategy": "credit_vertical",
                "legs": [
                    {"action": "sell", "option_type": "call", "strike": 105.0, "iv": 0.25, "delta": 0.30},
                    {"action": "buy", "option_type": "call", "strike": 110.0, "iv": 0.24},
                ],
                "net_premium": 1.5,
                "spot": 100.0,
                "dte_days": 30,
                "outcome_status": "resolved",
                "realized_win": True,
                "realized_pnl": 42.0,
                "regime": "bull",
                "dte_bucket": "21-45",
            },
            {"record_id": "s2", "known_at": "2026-06-01T15:00:00Z"},  # missing required keys
        ]
        records, skipped = records_from_rows(rows)
        assert len(records) == 1
        assert records[0].record_id == "s1"
        assert records[0].structure.net_premium == 1.5
        assert records[0].structure.legs[1].delta is None  # absent stays absent
        assert records[0].outcome.realized_pnl == 42.0
        assert records[0].segment == SegmentKey("credit_vertical", "bull", "21-45")
        assert len(skipped) == 1
        assert skipped[0][0] == 1
        assert "missing required keys" in skipped[0][1]


class TestSeededEndToEnd:
    """Real models through the evaluator on a seeded deterministic fixture."""

    def _fixture(self, n=12):
        rng = random.Random(42)
        records = []
        for i in range(n):
            credit = round(rng.uniform(0.4, 3.4), 2)
            iv_s = round(rng.uniform(0.15, 0.45), 4)
            iv_l = round(rng.uniform(0.15, 0.45), 4)
            win = rng.random() < 0.6
            pnl = round(rng.uniform(20.0, 120.0), 2) if win else -round(rng.uniform(50.0, 300.0), 2)
            records.append(
                EvalRecord(
                    record_id=f"fx{i:02d}",
                    structure=StructureSpec(
                        strategy="credit_vertical",
                        legs=(
                            LegSpec(action="sell", option_type="call", strike=105.0, iv=iv_s, delta=0.30),
                            LegSpec(action="buy", option_type="call", strike=110.0, iv=iv_l, delta=0.15),
                        ),
                        net_premium=credit,
                    ),
                    dist_inputs=DistributionInputs(
                        spot=100.0, dte_days=30.0, known_at=f"2026-06-{(i % 28) + 1:02d}T15:00:00Z"
                    ),
                    outcome=OutcomeRecord(status="resolved", realized_win=win, realized_pnl=pnl),
                    segment=SEG_A,
                )
            )
        return records

    def test_baseline_vs_challenger_prequential(self):
        records = self._fixture()
        baseline_fn = lambda rec: baseline_credit_vertical(rec.structure, rec.dist_inputs)
        challenger_fn = lambda rec: challenger_lognormal_evaluate(rec.structure, rec.dist_inputs)
        base = evaluate_model(baseline_fn, records, model_label="baseline_credit_identity")
        chal = evaluate_model(challenger_fn, records, model_label="lognormal_v1")

        assert base.scored == 12 and chal.scored == 12
        assert base.coverage == 1.0 and chal.coverage == 1.0
        # The baseline defect is VISIBLE in the evaluator output: every EV is 0
        # (to float identity precision — pop*gain and (1-pop)*loss cancel).
        assert all(abs(r.expected_value) < 1e-9 for r in base.predictions if r.scored)
        # The challenger actually forecasts: nonzero EVs.
        assert all(abs(r.expected_value) > 1e-6 for r in chal.predictions if r.scored)

        h2h = head_to_head(base, chal)
        assert h2h.n_joint == 12
        assert h2h.brier_a is not None and h2h.brier_b is not None
        # Determinism of the full pipeline.
        base2 = evaluate_model(baseline_fn, self._fixture(), model_label="baseline_credit_identity")
        assert base == base2
