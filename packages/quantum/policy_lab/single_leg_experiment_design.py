"""Single-leg experiment policy manifest — 2 experimental + 2 matched controls.

PROVENANCE MODULE (mirrors packages/quantum/policy_lab/fleet_policy_design.py).
This is the single, reproducible source of truth that PRODUCES two committed,
UNAPPLIED artifacts:

  * docs/specs/single_leg_experiment_policy_manifest.md — the human review
    manifest.
  * supabase/seed-transactions/policy_registrations_single_leg_experiment.sql —
    the UNAPPLIED seed transaction that WOULD insert the 4 DRAFT registry rows.

Regenerate the artifacts with:

    py -3.11 -m packages.quantum.policy_lab.single_leg_experiment_design

NOTHING here is applied and NO production registry row is written by this PR.
``approval_status`` is ``'draft'`` on EVERY row (asserted). 0 policies opt in
until an operator explicitly authors + approves a draft row (the future
registry-write authorization is described in
docs/review/single-leg-seed-prompt-2026-07-21.md — a separate operator-gated
step). This module mints DEFINITIONS only.

Design contract (owner packet 4, RATIFIED 2026-07-19, owner-packet-4-
single-leg-optin.md):
  * The single-leg (long_call / long_put) experiment is DARK by construction
    (packages/quantum/strategies/single_leg_experiment.py): a candidate is
    emitted only when the policy's RAW ``policy_config`` carries
    ``single_leg_experiment_enabled=true`` AND routing is shadow_only AND all
    entry conditions pass AND exactly one contract.
  * The registry is IMMUTABLE post-approval (20260719000000_policy_registrations
    trigger), so an opt-in CANNOT edit an existing approved row — it requires a
    NEW row. This manifest authors the two experimental opt-in rows plus two
    matched controls.
  * A 2x2 factorial isolates the studied effect on ONE axis at a time:
        axis A (single_leg_optin_block) : present  vs absent
        axis B (base_family)            : aggressive vs conservative
    Each experimental differs from its matched control on EXACTLY axis A (the
    opt-in block); the base 11 PolicyConfig fields are byte-identical within a
    matched pair. The two experimental arms differ on EXACTLY axis B; the two
    controls differ on EXACTLY axis B.
  * DISTINCT EPOCH: these rows live in ``single_leg_experiment_v1``, NOT the
    fleet epoch ``small_tier_v1``. The registry's UNIQUE(effective_epoch,
    config_hash) means a control config (byte-identical to an approved
    small_tier_v1 anchor, hence identical config_hash) never collides with the
    seeded fleet — the two epochs are separate hash namespaces. The control's
    config_hash EQUALS its fleet anchor's config_hash BY CONSTRUCTION (a
    cross-provenance witness, asserted below and in the tests).
  * config_canonical + config_hash use the SAME rule as the registry / fleet
    design: each base field type-coerced via ``fleet_policy_design._coerce``,
    the single-leg block coerced to bool/float, then
    json.dumps(sort_keys=True, separators=(",",":")); config_hash is the
    SHA-256 hex of that canonical string (identical to the SQL
    ``encode(extensions.digest(config_canonical,'sha256'),'hex')`` the seed
    derives server-side). The hashing FUNCTION is imported verbatim from
    fleet_policy_design so the two manifests can never drift on the rule.
  * INDEPENDENT terminal-distribution EV: each EXPERIMENTAL row binds the
    independent probability source — the ⑤ observe-only single-leg challenger
    adapter ``single_leg.evaluate_single_leg_from_inputs`` (the v1 lognormal
    challenger integrated over the exact one-leg payoff). The scalar EV is a
    PER-CANDIDATE RUNTIME quantity computed by the INJECTED estimator at scan
    time (H9: unpriceable inputs abstain via a typed abstention); a per-policy
    constant EV would be FABRICATED, so none is stored — the manifest carries
    the typed-REQUIRED source/model/contract binding instead.

    OBSERVE-ONLY IMPORT LOCK: like the generator (single_leg_experiment.py),
    this provenance module NEVER imports or names the analytics ⑤ package token
    — the adapter is consumed only via dependency injection. The EV identity
    literals below are referenced by name and drift-locked against the real
    module in packages/quantum/tests/test_single_leg_experiment_design.py (the
    test suite is exempt from the lock and imports the real constants).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping

# ── Registry hash rule + base anchors — IMPORTED VERBATIM (no drift) ──────────
from packages.quantum.policy_lab.fleet_policy_design import (
    ALL_FIELDS,
    AGGRESSIVE_ANCHOR,
    CONSERVATIVE_ANCHOR,
    STR_FIELDS,
    _coerce,
    config_hash,
)

# ── Single-leg generator surface — IMPORTED so the manifest's consumed keys and
#    threshold VALUES are exactly what the production generator reads (a costume
#    knob is impossible: the wiring test drives the generator with these rows). ─
from packages.quantum.strategies.single_leg_experiment import (
    DEFAULT_MAX_DEBIT_PER_CONTRACT,
    DEFAULT_MAX_IV_RANK,
    DEFAULT_MAX_VRP_SPREAD,
    DEFAULT_MIN_DIRECTIONAL_RUN,
    OPT_IN_KEY,
)

# ── Independent EV source identity — referenced by NAME ONLY (import lock) ────
# The analytics ⑤ single-leg challenger adapter is OBSERVE-ONLY: no production
# module may import OR name its package token (the ⑤ import-lock test enforces
# the ABSENCE full-text). Like the generator, this module cites the adapter by
# function/model/contract identity and never imports it — the real estimator is
# consumed via dependency injection at runtime. These literals are drift-locked
# against the real module in the (exempt) test suite.
EV_ADAPTER = "single_leg_adapter"          # == single_leg.SINGLE_LEG_SOURCE
EV_ADAPTER_VERSION = "single_leg@1.0.0"    # == single_leg.SINGLE_LEG_VERSION
EV_MODEL = "lognormal_v1"                  # == challenger_lognormal.MODEL_NAME
EV_CONTRACT_VERSION = "1.0.0"              # == contract.CONTRACT_VERSION
EV_SOURCE = "single_leg.evaluate_single_leg_from_inputs (⑤ observe-only challenger adapter; injected)"

# ── Constants ─────────────────────────────────────────────────────────────────
EXPERIMENT_EPOCH = "single_leg_experiment_v1"   # distinct from FLEET_EPOCH
SCHEMA_VERSION = 1
CREATED_BY = "single_leg_experiment_design"
APPROVAL_STATUS = "draft"                        # invariant: never 'approved'
STUDIED_AXIS = "single_leg_optin_block"

# The two axes of the 2x2.
AXIS_OPTIN = "single_leg_optin_block"   # present (experimental) vs absent (control)
AXIS_FAMILY = "base_family"             # aggressive vs conservative

# Flat generator-consumed keys (the RAW jsonb keys single_leg_experiment.py reads
# straight off policy_config — NOT PolicyConfig's 11 dataclass fields).
KEY_MAX_IV_RANK = "single_leg_max_iv_rank"
KEY_MAX_VRP_SPREAD = "single_leg_max_vrp_spread"
KEY_MIN_DIRECTIONAL_RUN = "single_leg_min_directional_run"
KEY_MAX_DEBIT = "single_leg_max_debit_per_contract"

SINGLE_LEG_BOOL_FIELDS = (OPT_IN_KEY,)
SINGLE_LEG_FLOAT_FIELDS = (
    KEY_MAX_IV_RANK,
    KEY_MAX_VRP_SPREAD,
    KEY_MIN_DIRECTIONAL_RUN,
    KEY_MAX_DEBIT,
)
SINGLE_LEG_BLOCK_KEYS = frozenset(SINGLE_LEG_BOOL_FIELDS + SINGLE_LEG_FLOAT_FIELDS)

# The opt-in block — VALUES sourced from the generator's own bounded defaults so
# the manifest can never state a threshold the generator does not consume. Both
# experimental arms carry the IDENTICAL block, so arm-vs-arm isolates axis B.
SINGLE_LEG_BLOCK: Dict[str, Any] = {
    OPT_IN_KEY: True,
    KEY_MAX_IV_RANK: DEFAULT_MAX_IV_RANK,               # 20.0 (low-IV gate a)
    KEY_MAX_VRP_SPREAD: DEFAULT_MAX_VRP_SPREAD,          # 0.0  (low-IV gate b / VRP)
    KEY_MIN_DIRECTIONAL_RUN: DEFAULT_MIN_DIRECTIONAL_RUN,  # 0.03 (directional)
    KEY_MAX_DEBIT: DEFAULT_MAX_DEBIT_PER_CONTRACT,       # 150.0 (debit cap)
}

# ── Independent terminal-distribution EV binding (typed-REQUIRED, experimental) ─
# NO scalar EV: the number is per-candidate/runtime and would be fabricated here.
TERMINAL_EV_BINDING: Dict[str, Any] = {
    "source": EV_SOURCE,
    "adapter": EV_ADAPTER,                    # single_leg_adapter
    "adapter_version": EV_ADAPTER_VERSION,    # single_leg@1.0.0
    "model": EV_MODEL,                        # lognormal_v1
    "contract_version": EV_CONTRACT_VERSION,  # 1.0.0
    "basis": "raw",                          # no calibration in this layer
    "evaluation": "per_candidate_runtime",   # NOT a manifest constant
    "injection": "dependency_injected",      # generator never imports the estimator
    "independent": True,
    "note": (
        "Scalar EV is computed per candidate at scan time by the INJECTED "
        "estimator; unpriceable inputs abstain (typed Unavailable, H9). A "
        "per-policy constant EV would be fabricated, so none is stored."
    ),
}
REQUIRED_TERMINAL_EV_FIELDS = (
    "source", "adapter", "model", "contract_version", "basis",
    "evaluation", "independent",
)

# ── Conditions taxonomy (structured; experimental rows) ───────────────────────
# Three conditions are POLICY-TUNABLE (real flat keys the generator reads); two
# (earnings, liquidity) are GENERATOR-FIXED (no policy knob — documented as such,
# never faked as a tunable field, so no costume knob is invented).
def _conditions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "debit_cap",
            "kind": "policy_tunable",
            "config_key": KEY_MAX_DEBIT,
            "value": SINGLE_LEG_BLOCK[KEY_MAX_DEBIT],
            "unit": "usd_per_contract",
            "consumer": "single_leg_experiment._max_debit_per_contract -> DEBIT_EXCEEDS_MAX",
        },
        {
            "name": "low_iv_rank",
            "kind": "policy_tunable",
            "config_key": KEY_MAX_IV_RANK,
            "value": SINGLE_LEG_BLOCK[KEY_MAX_IV_RANK],
            "unit": "iv_rank_percentile_ceiling",
            "consumer": "single_leg_experiment._max_iv_rank -> IV_NOT_LOW (guardrails BUY convention iv_rank<20)",
        },
        {
            "name": "low_iv_vrp",
            "kind": "policy_tunable",
            "config_key": KEY_MAX_VRP_SPREAD,
            "value": SINGLE_LEG_BLOCK[KEY_MAX_VRP_SPREAD],
            "unit": "iv_rv_spread_ceiling",
            "consumer": "single_leg_experiment._max_vrp_spread -> IV_NOT_CHEAP_VS_REALIZED (opportunity_scorer.vrp_score_multiplier)",
        },
        {
            "name": "directional",
            "kind": "policy_tunable",
            "config_key": KEY_MIN_DIRECTIONAL_RUN,
            "value": SINGLE_LEG_BLOCK[KEY_MIN_DIRECTIONAL_RUN],
            "unit": "signed_20d_run_up_floor",
            "consumer": "single_leg_experiment._min_directional_run -> DIRECTIONAL_SIGNAL_WEAK (momentum_signals)",
        },
        {
            "name": "earnings",
            "kind": "generator_fixed",
            "config_key": None,
            "value": "14_day_window",
            "unit": "days",
            "consumer": "guardrails.is_earnings_safe -> EARNINGS_PROXIMITY (NOT policy-tunable)",
        },
        {
            "name": "liquidity",
            "kind": "generator_fixed",
            "config_key": None,
            "value": "spread_guardrail + oi/volume_floor",
            "unit": "mixed",
            "consumer": "guardrails.apply_slippage_guardrail + check_liquidity -> ILLIQUID_CONTRACT (NOT policy-tunable)",
        },
    ]


# ── The two experimental arms (owner packet 4 §3) ─────────────────────────────
ARMS: List[Dict[str, Any]] = [
    {
        "arm": "throughput",
        "base_family": "aggressive",
        "anchor": AGGRESSIVE_ANCHOR,
        "anchor_note": "live champion (policy_lab_cohorts.promoted_at 2026-05-18)",
        "rationale": (
            "highest slot count (max_positions_open=4, max_suggestions_per_day=4) "
            "+ lowest score gate (min_score_threshold=30) => maximum single-leg "
            "SAMPLE THROUGHPUT; base is the most-vetted (live-champion) config"
        ),
    },
    {
        "arm": "conviction",
        "base_family": "conservative",
        "anchor": CONSERVATIVE_ANCHOR,
        "anchor_note": "shadow-only (never promoted)",
        "rationale": (
            "high-conviction low-volume contrast (max_positions_open=2, "
            "max_suggestions_per_day=2, min_score_threshold=70) => tests whether "
            "the surrounding cohort's score gate starves single-leg candidates"
        ),
    },
]


# ── Canonicalization + hashing (SAME rule as the registry / fleet design) ─────

def _coerce_single_leg(field: str, value: Any) -> Any:
    if field in SINGLE_LEG_BOOL_FIELDS:
        if not isinstance(value, bool):
            raise ValueError(f"{field} must be a bool, got {value!r}")
        return value
    if field in SINGLE_LEG_FLOAT_FIELDS:
        return float(value)
    raise ValueError(f"unknown single-leg field {field}")


def canonical_config(config: Mapping[str, Any]) -> str:
    """Deterministic canonical JSON for a single-leg-experiment policy_config.

    Base 11 PolicyConfig fields are ALWAYS present and coerced by the registry's
    own ``fleet_policy_design._coerce``. The single-leg opt-in block, when
    present, must be ALL-OR-NONE (the whole {flag + 4 bounded knobs}). No other
    keys are allowed. Sorted keys + compact separators => byte-identical for
    equal semantic configs regardless of input numeric type (0.30 vs 0.3)."""
    keys = set(config)
    base = set(ALL_FIELDS)
    missing = sorted(base - keys)
    if missing:
        raise ValueError(f"missing base PolicyConfig fields: {missing}")
    extra = keys - base
    unknown = extra - SINGLE_LEG_BLOCK_KEYS
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")
    if extra and extra != set(SINGLE_LEG_BLOCK_KEYS):
        raise ValueError(
            f"partial single-leg block {sorted(extra)} — the opt-in block is "
            f"all-or-none {sorted(SINGLE_LEG_BLOCK_KEYS)}"
        )
    normalized: Dict[str, Any] = {}
    for k in config:
        normalized[k] = _coerce(k, config[k]) if k in base else _coerce_single_leg(k, config[k])
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _validate_terminal_ev(ev: Mapping[str, Any]) -> None:
    if not isinstance(ev, Mapping):
        raise ValueError("terminal_ev must be a mapping")
    for f in REQUIRED_TERMINAL_EV_FIELDS:
        if ev.get(f) in (None, ""):
            raise ValueError(f"terminal_ev missing required field {f!r}")
    if ev.get("independent") is not True:
        raise ValueError("terminal_ev.independent must be True")
    # A per-policy scalar EV would be fabricated — forbidden.
    for banned in ("expected_value", "ev", "ev_expected_value", "pop"):
        if banned in ev:
            raise ValueError(f"terminal_ev must NOT carry a fabricated scalar {banned!r}")


# ── Row construction ──────────────────────────────────────────────────────────

def _experimental_row(arm_spec: Mapping[str, Any]) -> Dict[str, Any]:
    family = arm_spec["base_family"]
    arm = arm_spec["arm"]
    config = dict(arm_spec["anchor"])
    config.update(SINGLE_LEG_BLOCK)
    canonical = canonical_config(config)
    _validate_terminal_ev(TERMINAL_EV_BINDING)
    reg_id = f"sl_exp_{arm}_v1"
    control_id = f"sl_ctrl_{arm}_v1"
    rationale = (
        f"EXPERIMENTAL {arm} arm: {family}_anchor config + single-leg opt-in "
        f"block ({OPT_IN_KEY}=true; iv_rank<={SINGLE_LEG_BLOCK[KEY_MAX_IV_RANK]:g}, "
        f"vrp_spread<={SINGLE_LEG_BLOCK[KEY_MAX_VRP_SPREAD]:g}, "
        f"min_run>={SINGLE_LEG_BLOCK[KEY_MIN_DIRECTIONAL_RUN]:g}, "
        f"max_debit<=${SINGLE_LEG_BLOCK[KEY_MAX_DEBIT]:g}/contract). "
        f"{arm_spec['rationale']}. Matched control: {control_id} (differs on "
        f"axis A={AXIS_OPTIN} only). Independent EV: "
        f"{EV_ADAPTER}@{EV_MODEL}/{EV_CONTRACT_VERSION} "
        f"(per-candidate runtime; H9-abstains; no scalar stored)."
    )
    return {
        "policy_registration_id": reg_id,
        "policy_family": family,
        "anchor_lineage": f"{family}_anchor",
        "role": "experimental",
        "arm": arm,
        "base_family": family,
        "studied_axis": STUDIED_AXIS,
        "matched_id": control_id,
        "policy_config": config,
        "config_canonical": canonical,
        "config_hash": config_hash(canonical),
        "schema_version": SCHEMA_VERSION,
        "approval_status": APPROVAL_STATUS,
        "effective_epoch": EXPERIMENT_EPOCH,
        "changed_axes": [AXIS_OPTIN],
        "conditions": _conditions(),
        "terminal_ev": dict(TERMINAL_EV_BINDING),
        "design_rationale": rationale,
        "created_by": CREATED_BY,
    }


def _control_row(arm_spec: Mapping[str, Any]) -> Dict[str, Any]:
    family = arm_spec["base_family"]
    arm = arm_spec["arm"]
    config = dict(arm_spec["anchor"])   # PURE anchor — no single-leg keys
    canonical = canonical_config(config)
    reg_id = f"sl_ctrl_{arm}_v1"
    exp_id = f"sl_exp_{arm}_v1"
    rationale = (
        f"CONTROL {arm} arm: {family}_anchor config VERBATIM, NO single-leg "
        f"opt-in block (the generator emits nothing for it — dark by absence). "
        f"Matched experimental: {exp_id} (differs on axis A={AXIS_OPTIN} only). "
        f"config_hash equals the seeded {family}_anchor hash by construction "
        f"(byte-identical config, distinct epoch)."
    )
    return {
        "policy_registration_id": reg_id,
        "policy_family": family,
        "anchor_lineage": f"{family}_anchor",
        "role": "control",
        "arm": arm,
        "base_family": family,
        "studied_axis": STUDIED_AXIS,
        "matched_id": exp_id,
        "policy_config": config,
        "config_canonical": canonical,
        "config_hash": config_hash(canonical),
        "schema_version": SCHEMA_VERSION,
        "approval_status": APPROVAL_STATUS,
        "effective_epoch": EXPERIMENT_EPOCH,
        "changed_axes": [],
        "conditions": [],
        "terminal_ev": None,
        "design_rationale": rationale,
        "created_by": CREATED_BY,
    }


def build_registrations() -> List[Dict[str, Any]]:
    """Return the exactly-4 DRAFT rows, deterministically ordered so matched
    pairs are adjacent: (exp_throughput, ctrl_throughput, exp_conviction,
    ctrl_conviction)."""
    rows: List[Dict[str, Any]] = []
    for arm_spec in ARMS:
        rows.append(_experimental_row(arm_spec))
        rows.append(_control_row(arm_spec))
    _assert_invariants(rows)
    return rows


def _pure_anchor_hash(anchor: Mapping[str, Any]) -> str:
    return config_hash(canonical_config(dict(anchor)))


def _assert_invariants(rows: List[Dict[str, Any]]) -> None:
    assert len(rows) == 4, f"expected 4 rows, got {len(rows)}"
    ids = [r["policy_registration_id"] for r in rows]
    assert len(set(ids)) == 4, "duplicate registration ids"
    assert all(i and i.strip() for i in ids), "blank registration id"

    hashes = [r["config_hash"] for r in rows]
    assert len(set(hashes)) == 4, "duplicate config_hash"
    canons = [r["config_canonical"] for r in rows]
    assert len(set(canons)) == 4, "duplicate config_canonical"

    for r in rows:
        # NEVER approved — draft-only manifest.
        assert r["approval_status"] == "draft", (
            f"{r['policy_registration_id']} is {r['approval_status']!r}, must be draft"
        )
        assert r["effective_epoch"] == EXPERIMENT_EPOCH
        # hash matches canonical (same rule as the registry).
        assert r["config_hash"] == config_hash(r["config_canonical"])

    by_id = {r["policy_registration_id"]: r for r in rows}

    # Roles: exactly two experimental + two control.
    exp = [r for r in rows if r["role"] == "experimental"]
    ctrl = [r for r in rows if r["role"] == "control"]
    assert len(exp) == 2 and len(ctrl) == 2

    for r in exp:
        cfg = r["policy_config"]
        # opt-in block fully present (all 5 keys, flag True).
        assert cfg.get(OPT_IN_KEY) is True
        for k in SINGLE_LEG_BLOCK_KEYS:
            assert k in cfg, f"{r['policy_registration_id']} missing {k}"
        # terminal EV typed-required + independent + no fabricated scalar.
        _validate_terminal_ev(r["terminal_ev"])
        # exactly the studied axis is 'changed'.
        assert r["changed_axes"] == [AXIS_OPTIN]
        # all five conditions structured; three tunable + two generator-fixed.
        names = {c["name"] for c in r["conditions"]}
        assert names == {"debit_cap", "low_iv_rank", "low_iv_vrp",
                         "directional", "earnings", "liquidity"}
        tunable = {c["name"] for c in r["conditions"] if c["kind"] == "policy_tunable"}
        assert tunable == {"debit_cap", "low_iv_rank", "low_iv_vrp", "directional"}

    for r in ctrl:
        cfg = r["policy_config"]
        # NO single-leg keys at all — pure anchor.
        assert not (set(cfg) & SINGLE_LEG_BLOCK_KEYS), (
            f"{r['policy_registration_id']} carries single-leg keys — not a pure control"
        )
        assert set(cfg) == set(ALL_FIELDS)
        assert r["terminal_ev"] is None
        assert r["changed_axes"] == []
        # control config_hash == the fleet anchor's hash (cross-provenance link).
        anchor = AGGRESSIVE_ANCHOR if r["base_family"] == "aggressive" else CONSERVATIVE_ANCHOR
        assert r["config_hash"] == _pure_anchor_hash(anchor)

    # Matched-pair isolation: within a pair, base 11 fields are byte-identical
    # and the ONLY difference is the single-leg opt-in block (axis A).
    for e in exp:
        c = by_id[e["matched_id"]]
        assert c["role"] == "control" and c["matched_id"] == e["policy_registration_id"]
        assert e["base_family"] == c["base_family"]
        for f in ALL_FIELDS:
            assert e["policy_config"][f] == c["policy_config"][f], (
                f"matched pair {e['policy_registration_id']}/{c['policy_registration_id']} "
                f"differ on base field {f} — not a clean axis-A isolation"
            )
        diff_keys = set(e["policy_config"]) ^ set(c["policy_config"])
        assert diff_keys == set(SINGLE_LEG_BLOCK_KEYS), (
            f"matched pair differs on {sorted(diff_keys)}, expected exactly the opt-in block"
        )

    # Family isolation: the two experimentals share the IDENTICAL opt-in block
    # (only axis B, base_family, differs); ditto the two controls.
    exp_blocks = [{k: r["policy_config"][k] for k in SINGLE_LEG_BLOCK_KEYS} for r in exp]
    assert exp_blocks[0] == exp_blocks[1], "experimental arms differ inside the opt-in block"
    assert {r["base_family"] for r in exp} == {"aggressive", "conservative"}
    assert {r["base_family"] for r in ctrl} == {"aggressive", "conservative"}


# ── Coverage summary (for the manifest) ───────────────────────────────────────

def coverage_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "total": len(rows),
        "experimental": sum(1 for r in rows if r["role"] == "experimental"),
        "control": sum(1 for r in rows if r["role"] == "control"),
        "approved": sum(1 for r in rows if r["approval_status"] == "approved"),
        "draft": sum(1 for r in rows if r["approval_status"] == "draft"),
        "opt_in_enabled": sum(
            1 for r in rows if r["policy_config"].get(OPT_IN_KEY) is True
        ),
    }


# ── Artifact generators (manifest md + seed sql) ──────────────────────────────

def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return "%g" % float(value)


def render_manifest() -> str:
    rows = build_registrations()
    cov = coverage_summary(rows)
    out: List[str] = []
    out.append("# Single-leg experiment policy manifest — 2 experimental + 2 matched controls")
    out.append("")
    out.append(
        "Generated by `packages/quantum/policy_lab/single_leg_experiment_design.py` "
        "(`py -3.11 -m packages.quantum.policy_lab.single_leg_experiment_design`). "
        "These are **DRAFT DEFINITIONS ONLY** — nothing is applied, no production "
        "registry row is written, and **0 policies opt in** until an operator "
        "authors + approves a draft row (see "
        "`docs/review/single-leg-seed-prompt-2026-07-21.md`). Do not hand-edit — "
        "regenerate."
    )
    out.append("")
    out.append(
        "Owner authority: `owner-packet-4-single-leg-optin.md` (RATIFIED "
        "2026-07-19). The single-leg (long_call / long_put) experiment is DARK "
        "by construction (`packages/quantum/strategies/single_leg_experiment.py`): "
        "a candidate is emitted only when `policy_config` carries "
        "`single_leg_experiment_enabled=true`, routing is `shadow_only`, every "
        "entry condition passes, and exactly one contract is staged. Shadow-only, "
        "one contract, NO broker eligibility."
    )
    out.append("")
    out.append("## Design — 2x2 factorial (one studied axis at a time)")
    out.append("")
    out.append(
        "The registry is IMMUTABLE post-approval "
        "(`20260719000000_policy_registrations` trigger), so an opt-in cannot "
        "edit an approved row — it requires NEW rows. This manifest authors the "
        "two experimental opt-in rows plus their matched controls:"
    )
    out.append("")
    out.append(f"- **axis A** (`{AXIS_OPTIN}`): opt-in block **present** (experimental) vs **absent** (control)")
    out.append(f"- **axis B** (`{AXIS_FAMILY}`): **aggressive** (throughput arm) vs **conservative** (conviction arm)")
    out.append("")
    out.append("| role \\ family | aggressive (throughput) | conservative (conviction) |")
    out.append("|---|---|---|")
    out.append("| **experimental** (opt-in present) | `sl_exp_throughput_v1` | `sl_exp_conviction_v1` |")
    out.append("| **control** (opt-in absent) | `sl_ctrl_throughput_v1` | `sl_ctrl_conviction_v1` |")
    out.append("")
    out.append(
        "Each experimental differs from its matched control on **axis A only** "
        "(the base 11 PolicyConfig fields are byte-identical within a pair); the "
        "two experimentals differ on **axis B only** (identical opt-in block). So "
        "a single-leg result is attributable to the flag (matched-pair contrast) "
        "or to throughput/conviction (arm contrast), never confounded."
    )
    out.append("")
    out.append("## Epoch & non-collision")
    out.append("")
    out.append(
        f"All four rows live in `effective_epoch = {EXPERIMENT_EPOCH}` — DISTINCT "
        "from the fleet epoch `small_tier_v1`. The registry's "
        "`UNIQUE(effective_epoch, config_hash)` means a control config "
        "(byte-identical to an approved `small_tier_v1` anchor, hence identical "
        "`config_hash`) never collides with the seeded 50-policy fleet: the two "
        "epochs are separate hash namespaces. Each control's `config_hash` EQUALS "
        "its fleet anchor's `config_hash` by construction — a cross-provenance "
        "witness that the control is the anchor config verbatim (asserted in "
        "`test_single_leg_experiment_design.py`)."
    )
    out.append("")
    out.append("## Base anchors (from `docs/specs/fleet_policy_design_50.md`, VERIFIED-DB)")
    out.append("")
    out.append("| anchor | " + " | ".join(ALL_FIELDS) + " | note |")
    out.append("|" + "---|" * (len(ALL_FIELDS) + 2))
    for spec in ARMS:
        a = spec["anchor"]
        out.append(
            "| " + f"{spec['base_family']}_anchor" + " | "
            + " | ".join(_fmt(a[f]) if f not in STR_FIELDS else str(a[f])
                         for f in ALL_FIELDS)
            + f" | {spec['anchor_note']} |"
        )
    out.append("")
    out.append("## Single-leg opt-in block (generator-consumed keys)")
    out.append("")
    out.append(
        "The RAW `policy_config` keys `single_leg_experiment.py` reads directly "
        "(NOT PolicyConfig's 11 dataclass fields — `from_dict` drops these). "
        "VALUES are the generator's own bounded defaults, so the manifest can "
        "never state a threshold the generator does not consume. Both "
        "experimental arms carry the IDENTICAL block."
    )
    out.append("")
    out.append("| key | value | type | consumer |")
    out.append("|---|---|---|---|")
    out.append(f"| `{OPT_IN_KEY}` | true | bool | `experiment_enabled` (opt-in gate) |")
    out.append(f"| `{KEY_MAX_IV_RANK}` | {_fmt(SINGLE_LEG_BLOCK[KEY_MAX_IV_RANK])} | float | `_max_iv_rank` -> IV_NOT_LOW |")
    out.append(f"| `{KEY_MAX_VRP_SPREAD}` | {_fmt(SINGLE_LEG_BLOCK[KEY_MAX_VRP_SPREAD])} | float | `_max_vrp_spread` -> IV_NOT_CHEAP_VS_REALIZED |")
    out.append(f"| `{KEY_MIN_DIRECTIONAL_RUN}` | {_fmt(SINGLE_LEG_BLOCK[KEY_MIN_DIRECTIONAL_RUN])} | float | `_min_directional_run` -> DIRECTIONAL_SIGNAL_WEAK |")
    out.append(f"| `{KEY_MAX_DEBIT}` | {_fmt(SINGLE_LEG_BLOCK[KEY_MAX_DEBIT])} | float | `_max_debit_per_contract` -> DEBIT_EXCEEDS_MAX |")
    out.append("")
    out.append("## Conditions (structured — debit cap, low-IV, directional, earnings, liquidity)")
    out.append("")
    out.append(
        "Three conditions are **policy-tunable** (real flat keys above); two "
        "(earnings, liquidity) are **generator-fixed** (no policy knob — "
        "documented as such, never faked as a tunable field)."
    )
    out.append("")
    out.append("| condition | kind | config_key | value | consumer |")
    out.append("|---|---|---|---|---|")
    for c in _conditions():
        out.append(
            f"| {c['name']} | {c['kind']} | "
            f"{('`' + c['config_key'] + '`') if c['config_key'] else '—'} | "
            f"{_fmt(c['value']) if isinstance(c['value'], (int, float)) and not isinstance(c['value'], bool) else c['value']} | "
            f"{c['consumer']} |"
        )
    out.append("")
    out.append("## Independent terminal-distribution EV (typed-required, experimental rows)")
    out.append("")
    out.append(
        "Each experimental row binds the INDEPENDENT probability source — the "
        "v1 lognormal challenger integrated over the exact one-leg payoff "
        "(unbounded call upside is never a fabricated cap; put capped at "
        "strike - debit; H9 abstention on unpriceable inputs). The scalar EV is "
        "a **per-candidate runtime** quantity produced by the INJECTED estimator "
        "at scan time — a per-policy constant would be FABRICATED, so none is "
        "stored. The binding is typed-REQUIRED (a missing/invalid binding fails "
        "`build_registrations()`)."
    )
    out.append("")
    out.append("| field | value |")
    out.append("|---|---|")
    for k in ("source", "adapter", "adapter_version", "model", "contract_version",
              "basis", "evaluation", "injection", "independent"):
        out.append(f"| `{k}` | `{TERMINAL_EV_BINDING[k]}` |")
    out.append("")
    out.append("## Rows")
    out.append("")
    out.append("| # | id | role | arm | family | approval | epoch | changed_axes | matched | config_hash |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, start=1):
        axes = ", ".join(r["changed_axes"]) or "(none — control)"
        out.append(
            f"| {i} | `{r['policy_registration_id']}` | {r['role']} | {r['arm']} | "
            f"{r['base_family']} | **{r['approval_status']}** | {r['effective_epoch']} | "
            f"{axes} | `{r['matched_id']}` | `{r['config_hash']}` |"
        )
    out.append("")
    out.append("### Row rationales")
    out.append("")
    for r in rows:
        out.append(f"- `{r['policy_registration_id']}` — {r['design_rationale']}")
    out.append("")
    out.append("## Coverage & safety summary")
    out.append("")
    out.append(
        f"- Total rows: **{cov['total']}** (experimental {cov['experimental']}, "
        f"control {cov['control']})"
    )
    out.append(f"- approval_status: **draft {cov['draft']} / approved {cov['approved']}** (never approved)")
    out.append(
        f"- opt-in ENABLED rows: {cov['opt_in_enabled']} definitions carry the "
        "flag, but 0 are approved => **0 policies opt in at runtime** (the "
        "generator stays dark until an operator approves a draft row)"
    )
    out.append("- shadow-only, one contract, NO broker eligibility (generator invariants + execution-seam veto #1292)")
    out.append("")
    out.append("## config_hash (SHA-256 of config_canonical — same rule as the registry)")
    out.append("")
    out.append("| id | config_hash |")
    out.append("|---|---|")
    for r in rows:
        out.append(f"| `{r['policy_registration_id']}` | `{r['config_hash']}` |")
    out.append("")
    return "\n".join(out)


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_seed_sql() -> str:
    rows = build_registrations()
    out: List[str] = []
    out.append("-- =============================================================================")
    out.append("-- Seed transaction: 4 DRAFT single-leg experiment policy_registrations")
    out.append(f"-- (effective_epoch = {EXPERIMENT_EPOCH})")
    out.append("-- =============================================================================")
    out.append("-- NOT APPLIED BY THIS PR. approval_status = 'draft' on EVERY row. No policy")
    out.append("-- opts in until an operator approves a draft row (a separate, explicit,")
    out.append("-- registry-write step — see docs/review/single-leg-seed-prompt-2026-07-21.md).")
    out.append("--")
    out.append("-- Generated from packages/quantum/policy_lab/single_leg_experiment_design.py")
    out.append("-- (py -3.11 -m packages.quantum.policy_lab.single_leg_experiment_design). Requires")
    out.append("-- the 20260719000000_policy_registrations migration to be applied first.")
    out.append("--")
    out.append("-- config_hash is DERIVED here (never client-invented): the INSERT computes")
    out.append("-- encode(extensions.digest(config_canonical,'sha256'),'hex') inside the")
    out.append("-- transaction. The in-transaction (pre-commit) DO block re-asserts: exactly 4")
    out.append("-- rows for the epoch, 4 distinct hashes, 4 distinct canonical strings,")
    out.append("-- hash==sha256(canonical) for every row, and ZERO non-draft rows — any")
    out.append("-- failure RAISEs and rolls the whole seed back.")
    out.append("--")
    out.append("-- Distinct epoch => UNIQUE(effective_epoch, config_hash) never collides with")
    out.append("-- the seeded small_tier_v1 fleet, even though each control's config (and")
    out.append("-- config_hash) is byte-identical to its approved anchor.")
    out.append("-- =============================================================================")
    out.append("")
    out.append("BEGIN;")
    out.append("")
    out.append("INSERT INTO policy_registrations (")
    out.append("    policy_registration_id, policy_family, anchor_lineage,")
    out.append("    policy_config, config_canonical, config_hash,")
    out.append("    schema_version, approval_status, effective_epoch,")
    out.append("    changed_axes, design_rationale, created_at, approved_at, created_by")
    out.append(")")
    out.append("SELECT")
    out.append("    v.policy_registration_id, v.policy_family, v.anchor_lineage,")
    out.append("    v.config_canonical::jsonb, v.config_canonical,")
    out.append("    encode(extensions.digest(v.config_canonical, 'sha256'), 'hex'),")
    out.append(f"    {SCHEMA_VERSION}, 'draft', v.effective_epoch,")
    out.append("    v.changed_axes::jsonb, v.design_rationale, now(), NULL, v.created_by")
    out.append("FROM (VALUES")
    value_lines = []
    for r in rows:
        changed_axes_json = json.dumps(r["changed_axes"], separators=(",", ":"))
        value_lines.append(
            "    ("
            + _sql_str(r["policy_registration_id"]) + ", "
            + _sql_str(r["policy_family"]) + ", "
            + _sql_str(r["anchor_lineage"]) + ", "
            + _sql_str(r["config_canonical"]) + ", "
            + _sql_str(r["effective_epoch"]) + ", "
            + _sql_str(changed_axes_json) + ", "
            + _sql_str(r["design_rationale"]) + ", "
            + _sql_str(r["created_by"])
            + ")"
        )
    out.append(",\n".join(value_lines))
    out.append(") AS v(")
    out.append("    policy_registration_id, policy_family, anchor_lineage,")
    out.append("    config_canonical, effective_epoch, changed_axes,")
    out.append("    design_rationale, created_by")
    out.append(");")
    out.append("")
    out.append("-- Post-insert integrity assertions (fail -> ROLLBACK).")
    out.append("DO $$")
    out.append("DECLARE")
    out.append("    v_count int;")
    out.append("    v_distinct_hash int;")
    out.append("    v_distinct_canonical int;")
    out.append("    v_hash_mismatch int;")
    out.append("    v_non_draft int;")
    out.append("BEGIN")
    out.append(f"    SELECT count(*) INTO v_count")
    out.append(f"      FROM policy_registrations WHERE effective_epoch = '{EXPERIMENT_EPOCH}';")
    out.append("    IF v_count <> 4 THEN")
    out.append("        RAISE EXCEPTION 'single-leg seed: expected 4 rows, got %', v_count;")
    out.append("    END IF;")
    out.append("    SELECT count(DISTINCT config_hash) INTO v_distinct_hash")
    out.append(f"      FROM policy_registrations WHERE effective_epoch = '{EXPERIMENT_EPOCH}';")
    out.append("    IF v_distinct_hash <> 4 THEN")
    out.append("        RAISE EXCEPTION 'single-leg seed: expected 4 distinct config_hash, got %', v_distinct_hash;")
    out.append("    END IF;")
    out.append("    SELECT count(DISTINCT config_canonical) INTO v_distinct_canonical")
    out.append(f"      FROM policy_registrations WHERE effective_epoch = '{EXPERIMENT_EPOCH}';")
    out.append("    IF v_distinct_canonical <> 4 THEN")
    out.append("        RAISE EXCEPTION 'single-leg seed: expected 4 distinct config_canonical, got %', v_distinct_canonical;")
    out.append("    END IF;")
    out.append("    SELECT count(*) INTO v_hash_mismatch")
    out.append("      FROM policy_registrations")
    out.append(f"     WHERE effective_epoch = '{EXPERIMENT_EPOCH}'")
    out.append("       AND config_hash <> encode(extensions.digest(config_canonical, 'sha256'), 'hex');")
    out.append("    IF v_hash_mismatch <> 0 THEN")
    out.append("        RAISE EXCEPTION 'single-leg seed: % rows have config_hash != sha256(config_canonical)', v_hash_mismatch;")
    out.append("    END IF;")
    out.append("    SELECT count(*) INTO v_non_draft")
    out.append("      FROM policy_registrations")
    out.append(f"     WHERE effective_epoch = '{EXPERIMENT_EPOCH}' AND approval_status <> 'draft';")
    out.append("    IF v_non_draft <> 0 THEN")
    out.append("        RAISE EXCEPTION 'single-leg seed: % rows are not draft (opt-in must never seed approved)', v_non_draft;")
    out.append("    END IF;")
    out.append("END $$;")
    out.append("")
    out.append("COMMIT;")
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    manifest_path = os.path.join(
        repo_root, "docs", "specs", "single_leg_experiment_policy_manifest.md")
    seed_path = os.path.join(
        repo_root, "supabase", "seed-transactions",
        "policy_registrations_single_leg_experiment.sql")
    os.makedirs(os.path.dirname(seed_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_manifest())
    with open(seed_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_seed_sql())
    _rows = build_registrations()
    print(f"wrote {manifest_path}")
    print(f"wrote {seed_path}")
    print(f"rows={len(_rows)} distinct_hashes={len({r['config_hash'] for r in _rows})}")
    for _r in _rows:
        print(f"  {_r['policy_registration_id']:24s} {_r['role']:12s} "
              f"{_r['approval_status']:6s} {_r['config_hash']}")
