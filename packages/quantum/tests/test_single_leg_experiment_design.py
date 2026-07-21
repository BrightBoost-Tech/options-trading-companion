"""Single-leg experiment policy manifest — draft-only, matched-control design.

Pins the deterministic design generator AND its two committed artifacts (the
review manifest + the UNAPPLIED seed) to each other, and proves:
  * every row is DRAFT (never approved) — the opt-in never seeds approved;
  * the config_hash rule is the registry's own (SHA-256 of config_canonical),
    deterministic + pinned;
  * each experimental differs from its matched control on EXACTLY the studied
    axis (the single-leg opt-in block), the base 11 fields byte-identical;
  * each control's config_hash EQUALS its fleet anchor's — a cross-provenance
    witness that the control is the anchor config verbatim;
  * the experimental config is REALLY consumed by the production single-leg
    generator (anti-costume: drive the entrypoint, assert the OUTPUT), and the
    control is DARK by absence of the flag;
  * the independent terminal-distribution EV binding is typed-required and
    carries NO fabricated scalar EV.
"""

import hashlib
import json
from pathlib import Path

import pytest

from packages.quantum.brokers.execution_router import (
    LIVE_ROUTING_MODE,
    SHADOW_ONLY_ROUTING,
)
from packages.quantum.policy_lab import fleet_policy_design as fleet
from packages.quantum.policy_lab import single_leg_experiment_design as design
from packages.quantum.strategies import single_leg_experiment as sl
from packages.quantum.tests.test_single_leg_experiment_generation import (
    passing_context,
    real_estimator,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPO_ROOT / "docs" / "specs" / "single_leg_experiment_policy_manifest.md"
SEED = (REPO_ROOT / "supabase" / "seed-transactions"
        / "policy_registrations_single_leg_experiment.sql")

# Pinned deterministic hashes (regenerate the module's __main__ if these move —
# a moved hash means the design changed, which must be intentional + reviewed).
PINNED_HASHES = {
    "sl_exp_throughput_v1": "71e854a6e9f098d561748b49161c5997459b4f2a7a19e27eebcb741c1987db5e",
    "sl_ctrl_throughput_v1": "441ace2f5dc5b7842f6ae41db30db3dcd32ffbb1afa5585794659b04421fb310",
    "sl_exp_conviction_v1": "59e02e8f09b3030f7fa5f3cd6f281ee42e80100e73f2a6e8fdcfe1e56374cf09",
    "sl_ctrl_conviction_v1": "5f74bffe2d819d850f9c74be992b82f353a0ff15d5d2912abd9fb96502fc7de0",
}


@pytest.fixture(scope="module")
def rows():
    return design.build_registrations()


# ── Count / identity ─────────────────────────────────────────────────────────

def test_exactly_four_rows(rows):
    assert len(rows) == 4


def test_two_experimental_two_control(rows):
    roles = sorted(r["role"] for r in rows)
    assert roles == ["control", "control", "experimental", "experimental"]


def test_all_ids_distinct_and_nonblank(rows):
    ids = [r["policy_registration_id"] for r in rows]
    assert len(set(ids)) == 4
    assert all(i and i.strip() for i in ids)
    assert set(ids) == set(PINNED_HASHES)


# ── DRAFT-only / never approved (requirement 1 + 7) ──────────────────────────

def test_every_row_is_draft(rows):
    for r in rows:
        assert r["approval_status"] == "draft", r["policy_registration_id"]


def test_no_row_is_approved(rows):
    assert all(r["approval_status"] != "approved" for r in rows)
    assert all(r["approval_status"] in ("draft",) for r in rows)


def test_no_runtime_opt_in_because_none_approved(rows):
    cov = design.coverage_summary(rows)
    # two DEFINITIONS carry the flag, but zero are approved -> 0 opt in at runtime.
    assert cov["opt_in_enabled"] == 2
    assert cov["approved"] == 0
    assert cov["draft"] == 4


def test_distinct_experiment_epoch(rows):
    # NOT the fleet epoch -> no UNIQUE(epoch, hash) collision with small_tier_v1.
    assert design.EXPERIMENT_EPOCH != fleet.EFFECTIVE_EPOCH
    assert all(r["effective_epoch"] == design.EXPERIMENT_EPOCH for r in rows)


# ── Canonical serialization + hashing (same rule as the registry) ────────────

def test_canonical_is_deterministic_sorted_compact(rows):
    for r in rows:
        cfg = r["policy_config"]
        c1 = design.canonical_config(cfg)
        c2 = design.canonical_config(dict(reversed(list(cfg.items()))))
        assert c1 == c2 == r["config_canonical"]      # order-independent
        parsed = json.loads(c1)
        assert list(parsed) == sorted(parsed)         # sorted keys
        assert ", " not in c1 and ": " not in c1      # compact separators


def test_hash_is_sha256_of_canonical(rows):
    for r in rows:
        expect = hashlib.sha256(r["config_canonical"].encode("utf-8")).hexdigest()
        assert r["config_hash"] == expect


def test_hashes_are_pinned(rows):
    got = {r["policy_registration_id"]: r["config_hash"] for r in rows}
    assert got == PINNED_HASHES


def test_all_hashes_and_canonicals_distinct(rows):
    assert len({r["config_hash"] for r in rows}) == 4
    assert len({r["config_canonical"] for r in rows}) == 4


def test_base_fields_type_coerced_in_canonical(rows):
    for r in rows:
        parsed = json.loads(r["config_canonical"])
        for f in fleet.FLOAT_FIELDS:
            assert isinstance(parsed[f], float)
        for f in fleet.INT_FIELDS:
            assert isinstance(parsed[f], int) and not isinstance(parsed[f], bool)
        assert isinstance(parsed[fleet.STR_FIELDS[0]], str)


# ── Control == fleet anchor (cross-provenance witness) ───────────────────────

def test_control_hash_equals_fleet_anchor_hash(rows):
    fleet_rows = {r["policy_registration_id"]: r for r in fleet.build_registrations()}
    pairs = {
        "sl_ctrl_throughput_v1": "aggressive_anchor",
        "sl_ctrl_conviction_v1": "conservative_anchor",
    }
    ctrl = {r["policy_registration_id"]: r for r in rows if r["role"] == "control"}
    for ctrl_id, anchor_id in pairs.items():
        assert ctrl[ctrl_id]["config_hash"] == fleet_rows[anchor_id]["config_hash"]
        # and byte-identical canonical config (the anchor verbatim)
        assert ctrl[ctrl_id]["config_canonical"] == fleet_rows[anchor_id]["config_canonical"]


def test_control_is_pure_anchor_no_single_leg_keys(rows):
    for r in rows:
        if r["role"] != "control":
            continue
        assert set(r["policy_config"]) == set(fleet.ALL_FIELDS)
        assert not (set(r["policy_config"]) & design.SINGLE_LEG_BLOCK_KEYS)
        assert r["terminal_ev"] is None
        assert r["changed_axes"] == []


# ── Matched-pair isolation: differ on EXACTLY the studied axis ───────────────

def test_matched_pair_differs_only_on_optin_block(rows):
    by_id = {r["policy_registration_id"]: r for r in rows}
    for e in [r for r in rows if r["role"] == "experimental"]:
        c = by_id[e["matched_id"]]
        assert c["role"] == "control"
        assert c["matched_id"] == e["policy_registration_id"]
        assert e["base_family"] == c["base_family"]
        # base 11 fields byte-identical
        for f in fleet.ALL_FIELDS:
            assert e["policy_config"][f] == c["policy_config"][f], f
        # the ONLY key difference is the single-leg opt-in block
        diff = set(e["policy_config"]) ^ set(c["policy_config"])
        assert diff == set(design.SINGLE_LEG_BLOCK_KEYS)
        assert e["changed_axes"] == [design.AXIS_OPTIN]


def test_experimental_arms_differ_only_on_family(rows):
    exp = [r for r in rows if r["role"] == "experimental"]
    assert {r["base_family"] for r in exp} == {"aggressive", "conservative"}
    # identical opt-in block across arms -> arm contrast isolates axis B (family)
    blocks = [{k: r["policy_config"][k] for k in design.SINGLE_LEG_BLOCK_KEYS} for r in exp]
    assert blocks[0] == blocks[1]


# ── Conditions structured (requirement 4) ────────────────────────────────────

def test_experimental_conditions_structured(rows):
    for r in rows:
        if r["role"] != "experimental":
            continue
        names = {c["name"] for c in r["conditions"]}
        assert names == {"debit_cap", "low_iv_rank", "low_iv_vrp",
                         "directional", "earnings", "liquidity"}
        tunable = {c["name"] for c in r["conditions"] if c["kind"] == "policy_tunable"}
        fixed = {c["name"] for c in r["conditions"] if c["kind"] == "generator_fixed"}
        assert tunable == {"debit_cap", "low_iv_rank", "low_iv_vrp", "directional"}
        assert fixed == {"earnings", "liquidity"}
        # every tunable condition names a real policy_config key that IS in config
        for c in r["conditions"]:
            if c["kind"] == "policy_tunable":
                assert c["config_key"] in r["policy_config"]


# ── Independent terminal-distribution EV (requirement 3) ─────────────────────

def test_experimental_carries_independent_terminal_ev(rows):
    for r in rows:
        if r["role"] != "experimental":
            continue
        ev = r["terminal_ev"]
        assert ev is not None
        # typed-required fields present
        for f in design.REQUIRED_TERMINAL_EV_FIELDS:
            assert ev.get(f) not in (None, ""), f
        assert ev["independent"] is True
        # bound to the REAL independent probability source module
        assert "terminal_distribution.single_leg" in ev["source"]
        assert ev["model"] == "lognormal_v1"
        assert ev["basis"] == "raw"
        assert ev["evaluation"] == "per_candidate_runtime"


def test_terminal_ev_carries_no_fabricated_scalar(rows):
    for r in rows:
        if r["role"] != "experimental":
            continue
        ev = r["terminal_ev"]
        for banned in ("expected_value", "ev", "ev_expected_value", "pop"):
            assert banned not in ev
    # validator rejects a fabricated scalar
    with pytest.raises(ValueError):
        design._validate_terminal_ev({**design.TERMINAL_EV_BINDING, "expected_value": 42.0})


# ── WIRING: the experimental config is REALLY consumed (anti-costume) ────────

def test_generator_consumes_experimental_thresholds(rows):
    exp = next(r for r in rows if r["role"] == "experimental")
    cfg = exp["policy_config"]
    # the generator's own bounded readers pull the manifest's flat keys
    assert sl._max_iv_rank(cfg) == 20.0
    assert sl._max_vrp_spread(cfg) == 0.0
    assert sl._min_directional_run(cfg) == 0.03
    assert sl._max_debit_per_contract(cfg) == 150.0
    assert sl.experiment_enabled(cfg) is True


def test_generator_emits_candidate_for_experimental_config(rows):
    exp = next(r for r in rows if r["role"] == "experimental")
    res = sl.generate_single_leg_candidates(
        [passing_context()],
        policy_config=exp["policy_config"],
        routing_mode=SHADOW_ONLY_ROUTING,
        ev_estimator=real_estimator,
    )
    assert res.enabled is True
    assert len(res.candidates) == 1
    cand = res.candidates[0]
    assert cand.contracts == 1                       # one-contract invariant
    assert cand.routing == SHADOW_ONLY_ROUTING       # shadow-only invariant


def test_generator_is_dark_for_control_config(rows):
    ctrl = next(r for r in rows if r["role"] == "control")
    res = sl.generate_single_leg_candidates(
        [passing_context()],
        policy_config=ctrl["policy_config"],
        routing_mode=SHADOW_ONLY_ROUTING,
        ev_estimator=real_estimator,
    )
    # opt-in absent -> dark no-op (not a rejection)
    assert res.enabled is False
    assert res.candidates == [] and res.rejections == []


def test_experimental_config_refuses_live_routing(rows):
    # NO broker eligibility (requirement 2): a live_eligible routing refuses the
    # whole batch even with the flag set.
    exp = next(r for r in rows if r["role"] == "experimental")
    res = sl.generate_single_leg_candidates(
        [passing_context()],
        policy_config=exp["policy_config"],
        routing_mode=LIVE_ROUTING_MODE,
        ev_estimator=real_estimator,
    )
    assert res.enabled is True
    assert res.candidates == []
    assert res.rejections and all(
        rj.reason_code == sl.LIVE_ROUTING_FORBIDDEN for rj in res.rejections
    )


# ── Drift-lock: committed artifacts == generator output ──────────────────────

def test_manifest_file_matches_generator():
    committed = MANIFEST.read_text(encoding="utf-8")
    assert committed == design.render_manifest(), (
        "docs/specs/single_leg_experiment_policy_manifest.md is stale — "
        "regenerate with `py -3.11 -m "
        "packages.quantum.policy_lab.single_leg_experiment_design`")


def test_seed_file_matches_generator():
    committed = SEED.read_text(encoding="utf-8")
    assert committed == design.render_seed_sql(), (
        "supabase/seed-transactions/policy_registrations_single_leg_experiment.sql "
        "is stale — regenerate with the module's __main__")


def test_seed_is_draft_only_and_hash_derived(rows):
    seed = SEED.read_text(encoding="utf-8")
    for r in rows:
        assert f"'{r['policy_registration_id']}'" in seed
        assert r["config_canonical"] in seed
        # config_hash is DERIVED in-SQL, never embedded as a literal
        assert r["config_hash"] not in seed
    assert "extensions.digest(v.config_canonical, 'sha256')" in seed
    assert "'draft'" in seed
    # no INSERT ever stamps approved/retired/revoked
    for status in ("'approved'", "'retired'", "'revoked'"):
        assert status not in seed
    # integrity assertions present, incl. the zero-non-draft guard
    assert "expected 4 distinct config_hash" in seed
    assert "rows are not draft" in seed
