"""Lane A — the 50-policy fleet design (3 anchors + 47 bounded variants).

Pins the deterministic design generator AND the two committed artifacts it
produces (the review manifest + the seed transaction) to each other, so a hand
edit of either file — or a drift in the generator — breaks the build, not the
fleet. The DB is runtime truth; these tests guard the provenance.
"""

import hashlib
import json
from pathlib import Path

import pytest

from packages.quantum.policy_lab import fleet_policy_design as design
from packages.quantum.policy_lab.shadow_fleet import FLEET_EPOCH

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPO_ROOT / "docs" / "specs" / "fleet_policy_design_50.md"
SEED = (REPO_ROOT / "supabase" / "seed-transactions"
        / "policy_registrations_seed_50.sql")

# The three anchor configs EXACTLY as queried from policy_lab_cohorts (DB truth,
# 2026-07-18). This test is the anchor's independent witness — if the module's
# ANCHORS drift from the DB values, it fails.
DB_ANCHORS = {
    "aggressive": {
        "sizing_method": "budget_proportional", "stop_loss_pct": 0.30,
        "budget_cap_pct": 0.35, "min_dte_to_exit": 7, "risk_multiplier": 1.2,
        "max_dte_to_enter": 45, "target_profit_pct": 0.50,
        "max_positions_open": 4, "min_score_threshold": 30,
        "max_risk_pct_per_trade": 0.035, "max_suggestions_per_day": 4,
    },
    "conservative": {
        "sizing_method": "budget_proportional", "stop_loss_pct": 0.15,
        "budget_cap_pct": 0.25, "min_dte_to_exit": 14, "risk_multiplier": 0.8,
        "max_dte_to_enter": 45, "target_profit_pct": 0.25,
        "max_positions_open": 2, "min_score_threshold": 70,
        "max_risk_pct_per_trade": 0.015, "max_suggestions_per_day": 2,
    },
    "neutral": {
        "sizing_method": "budget_proportional", "stop_loss_pct": 0.20,
        "budget_cap_pct": 0.30, "min_dte_to_exit": 10, "risk_multiplier": 1.0,
        "max_dte_to_enter": 45, "target_profit_pct": 0.35,
        "max_positions_open": 3, "min_score_threshold": 50,
        "max_risk_pct_per_trade": 0.025, "max_suggestions_per_day": 3,
    },
}


@pytest.fixture(scope="module")
def rows():
    return design.build_registrations()


# ── Count / identity ─────────────────────────────────────────────────────────

def test_exactly_50_rows(rows):
    assert len(rows) == 50


def test_three_anchors_present_and_verbatim(rows):
    anchors = {r["policy_registration_id"]: r for r in rows
               if not r["changed_axes"]}
    assert set(anchors) == {
        "aggressive_anchor", "neutral_anchor", "conservative_anchor"}
    for fam in ("aggressive", "neutral", "conservative"):
        cfg = anchors[f"{fam}_anchor"]["policy_config"]
        # values equal the DB anchor (semantic equality across int/float)
        assert set(cfg) == set(DB_ANCHORS[fam])
        for k, v in DB_ANCHORS[fam].items():
            if isinstance(v, str):
                assert cfg[k] == v, (fam, k)
            else:
                assert float(cfg[k]) == float(v), (fam, k)


def test_all_ids_distinct_and_nonblank(rows):
    ids = [r["policy_registration_id"] for r in rows]
    assert len(set(ids)) == 50
    assert all(i and i.strip() for i in ids)


# ── Canonical serialization determinism ──────────────────────────────────────

def test_canonical_is_deterministic_sorted_compact(rows):
    for r in rows:
        cfg = r["policy_config"]
        c1 = design.canonical_config(cfg)
        c2 = design.canonical_config(dict(reversed(list(cfg.items()))))
        assert c1 == c2 == r["config_canonical"]      # order-independent
        # sorted keys + compact separators
        parsed = json.loads(c1)
        assert list(parsed) == sorted(parsed)
        assert ", " not in c1 and ": " not in c1


def test_canonical_round_trips_to_typed_config(rows):
    for r in rows:
        parsed = json.loads(r["config_canonical"])
        for f in design.FLOAT_FIELDS:
            assert isinstance(parsed[f], float)
        for f in design.INT_FIELDS:
            assert isinstance(parsed[f], int) and not isinstance(parsed[f], bool)
        assert isinstance(parsed[design.STR_FIELDS[0]], str)


# ── Hash distinctness + derivation ───────────────────────────────────────────

def test_all_50_hashes_distinct(rows):
    hashes = [r["config_hash"] for r in rows]
    assert len(set(hashes)) == 50


def test_all_50_canonicals_distinct(rows):
    assert len({r["config_canonical"] for r in rows}) == 50


def test_hash_is_sha256_of_canonical(rows):
    for r in rows:
        expect = hashlib.sha256(r["config_canonical"].encode("utf-8")).hexdigest()
        assert r["config_hash"] == expect


# ── Bounds / consumed-axes discipline ────────────────────────────────────────

def test_only_consumed_axes_varied(rows):
    for r in rows:
        assert len(r["changed_axes"]) <= 2
        for axis in r["changed_axes"]:
            assert axis in design.CONSUMERS
            assert axis not in design.HELD_AXES


def test_held_axes_verbatim_on_every_row(rows):
    for r in rows:
        anchor = design.ANCHORS[r["policy_family"]]
        for axis in design.HELD_AXES:
            assert r["policy_config"][axis] == anchor[axis]


def test_every_varied_value_within_hull(rows):
    for r in rows:
        for axis in r["changed_axes"]:
            lo, hi = design.HULL[axis]
            assert lo <= float(r["policy_config"][axis]) <= hi


def test_stop_never_looser_than_loosest_anchor(rows):
    # loosest anchor stop = aggressive 0.30 == config._TIGHT_STOP_CEILING
    for r in rows:
        assert float(r["policy_config"]["stop_loss_pct"]) <= 0.30


def test_epoch_matches_fleet_epoch(rows):
    assert all(r["effective_epoch"] == FLEET_EPOCH for r in rows)
    assert all(r["approval_status"] == "approved" for r in rows)


def test_balanced_anchor_coverage(rows):
    cov = design.coverage_summary(rows)
    # every anchor lineage carries a comparable share (no anchor starved)
    assert min(cov["per_anchor"].values()) >= 16
    # every consumed axis is exercised at least once
    assert all(v >= 1 for v in cov["per_axis"].values())


# ── Drift-lock: committed artifacts == generator output ──────────────────────

def test_manifest_file_matches_generator():
    committed = MANIFEST.read_text(encoding="utf-8")
    assert committed == design.render_manifest(), (
        "docs/specs/fleet_policy_design_50.md is stale — regenerate with "
        "`py -3.11 -m packages.quantum.policy_lab.fleet_policy_design`")


def test_seed_file_matches_generator():
    committed = SEED.read_text(encoding="utf-8")
    assert committed == design.render_seed_sql(), (
        "supabase/seed-transactions/policy_registrations_seed_50.sql is stale — "
        "regenerate with the module's __main__")


def test_seed_contains_every_id_and_canonical(rows):
    seed = SEED.read_text(encoding="utf-8")
    for r in rows:
        assert f"'{r['policy_registration_id']}'" in seed
        assert r["config_canonical"] in seed
    # config_hash is DERIVED in-SQL, never embedded as a literal.
    for r in rows:
        assert r["config_hash"] not in seed
    # hash derivation + integrity assertions present.
    assert "extensions.digest(v.config_canonical, 'sha256')" in seed
    assert "expected 50 distinct config_hash" in seed
    assert seed.count("_v1'") + 3 >= 47  # 47 variant ids carry the _v1 suffix
