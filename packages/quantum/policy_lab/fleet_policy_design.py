"""Deterministic 50-policy fleet design — 3 anchors + 47 bounded variants.

PROVENANCE MODULE (Lane A). This module is the single, reproducible source of
truth that PRODUCES two committed artifacts:

  * docs/specs/fleet_policy_design_50.md  — the human review manifest.
  * supabase/seed-transactions/policy_registrations_seed_50.sql — the seed
    transaction (UNAPPLIED) that inserts the 50 approved registry rows.

The DATABASE (`policy_registrations`, migration 20260719000000) is the runtime
truth; this module is provenance. Regenerate the artifacts with:

    py -3.11 -m packages.quantum.policy_lab.fleet_policy_design

Design contract:
  * The 3 anchors are the VERIFIED-DB `policy_lab_cohorts.policy_config` rows,
    verbatim (values identical to the DB; DB is authoritative — note code
    AGGRESSIVE stop 0.65 != DB 0.30, and DB wins). config verbatim, no axis
    changed.
  * 47 variants each vary ONE axis (a few vary two), holding every other field
    at the base anchor. Only axes with a REAL production consumer are varied
    (see CONSUMERS). Two axes are NEVER varied because they have no cohort-level
    consumer: `sizing_method` and `max_dte_to_enter` (grep-verified). They are
    carried verbatim from the anchor on every row.
  * Every varied value lies within the 3-anchor CONVEX HULL [min_anchor,
    max_anchor] for that axis (see HULL). No variant is looser than the loosest
    anchor nor tighter than the tightest anchor. For stop_loss_pct the hull max
    is 0.30 — the live champion's stop AND config._TIGHT_STOP_CEILING — so no
    variant ever widens the live stop.
  * config_canonical is a deterministic serialization: each field coerced to its
    declared PolicyConfig type (float / int / str), then
    json.dumps(sort_keys=True, separators=(",", ":")). config_hash is the
    SHA-256 hex of config_canonical. All 50 canonical strings (and hashes) are
    distinct (asserted here and in the seed's post-commit DO block).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Tuple

EFFECTIVE_EPOCH = "small_tier_v1"  # must match shadow_fleet.FLEET_EPOCH
SCHEMA_VERSION = 1
CREATED_BY = "fable_orchestrator_lane_a"

# ── PolicyConfig field types (packages/quantum/policy_lab/config.py:18-36) ────
# Canonical serialization coerces each field to its declared dataclass type so
# the DB's int-vs-float JSON artifact (neutral risk_multiplier stored as `1`,
# aggressive as `1.2`; min_score as `30`) can never perturb the hash.
FLOAT_FIELDS = (
    "max_risk_pct_per_trade",
    "risk_multiplier",
    "budget_cap_pct",
    "min_score_threshold",
    "stop_loss_pct",
    "target_profit_pct",
)
INT_FIELDS = (
    "max_suggestions_per_day",
    "max_positions_open",
    "max_dte_to_enter",
    "min_dte_to_exit",
)
STR_FIELDS = ("sizing_method",)
ALL_FIELDS = tuple(sorted(FLOAT_FIELDS + INT_FIELDS + STR_FIELDS))

# ── The three anchors — VERBATIM from policy_lab_cohorts.policy_config ─────────
# Queried live 2026-07-18 (etdlladeorfgdmsopzmz). DB is the anchor truth.
AGGRESSIVE_ANCHOR: Dict[str, Any] = {
    "max_risk_pct_per_trade": 0.035,
    "risk_multiplier": 1.2,
    "sizing_method": "budget_proportional",
    "budget_cap_pct": 0.35,
    "max_suggestions_per_day": 4,
    "min_score_threshold": 30.0,
    "max_positions_open": 4,
    "stop_loss_pct": 0.30,
    "target_profit_pct": 0.50,
    "max_dte_to_enter": 45,
    "min_dte_to_exit": 7,
}
NEUTRAL_ANCHOR: Dict[str, Any] = {
    "max_risk_pct_per_trade": 0.025,
    "risk_multiplier": 1.0,
    "sizing_method": "budget_proportional",
    "budget_cap_pct": 0.30,
    "max_suggestions_per_day": 3,
    "min_score_threshold": 50.0,
    "max_positions_open": 3,
    "stop_loss_pct": 0.20,
    "target_profit_pct": 0.35,
    "max_dte_to_enter": 45,
    "min_dte_to_exit": 10,
}
CONSERVATIVE_ANCHOR: Dict[str, Any] = {
    "max_risk_pct_per_trade": 0.015,
    "risk_multiplier": 0.8,
    "sizing_method": "budget_proportional",
    "budget_cap_pct": 0.25,
    "max_suggestions_per_day": 2,
    "min_score_threshold": 70.0,
    "max_positions_open": 2,
    "stop_loss_pct": 0.15,
    "target_profit_pct": 0.25,
    "max_dte_to_enter": 45,
    "min_dte_to_exit": 14,
}
ANCHORS: Dict[str, Dict[str, Any]] = {
    "aggressive": AGGRESSIVE_ANCHOR,
    "neutral": NEUTRAL_ANCHOR,
    "conservative": CONSERVATIVE_ANCHOR,
}
ANCHOR_META = {
    "aggressive": "live champion (policy_lab_cohorts.promoted_at 2026-05-18)",
    "neutral": "shadow-only (never promoted)",
    "conservative": "shadow-only (never promoted)",
}

# ── Axes varied, with their REAL production consumers (file:line) ─────────────
# Only axes in this map are ever varied. sizing_method + max_dte_to_enter are
# absent BY DESIGN: grep found no cohort-level consumer (both appear only in
# config.py declarations), so varying them would be a no-op costume.
CONSUMERS: Dict[str, str] = {
    "stop_loss_pct": (
        "paper_exit_evaluator.py:1197 (cfg.stop_loss_pct -> _check_stop_loss "
        ":552) + intraday_risk_monitor.py:1094 (#1048 cohort stop) + "
        "paper_shadow_executor.py:570"
    ),
    "target_profit_pct": (
        "paper_exit_evaluator.py:1196 (cfg.target_profit_pct) + "
        "gtc_profit_exit.py:103 (resting TP) + intraday_risk_monitor.py:1093 "
        "(#1048) + paper_shadow_executor.py:570"
    ),
    "min_dte_to_exit": (
        "paper_exit_evaluator.py:1198,557 (days_to_expiry(pos) <= dte_min) + "
        "paper_shadow_executor.py:571"
    ),
    "max_positions_open": (
        "fork.py:610 (available_slots = max(0, max_positions_open - open)) + "
        "fork.py:625 capacity rejection"
    ),
    "max_suggestions_per_day": (
        "fork.py:611 (max_new = min(max_suggestions_per_day, slots)) + "
        "paper_autopilot_service.py:904"
    ),
    "min_score_threshold": (
        "fork.py:642 (score_value < config.min_score_threshold) + fork.py:1046"
    ),
    "budget_cap_pct": (
        "fork.py:723 (budget = deployable_capital * config.budget_cap_pct)"
    ),
    "max_risk_pct_per_trade": (
        "fork.py:724 (max_risk = capital * max_risk_pct_per_trade * "
        "risk_multiplier) + sizing_engine.py:164"
    ),
    "risk_multiplier": (
        "fork.py:724 (same sizing line) + sizing_engine.py:98,144,164"
    ),
}

# ── Convex hull per axis = [min anchor value, max anchor value] ───────────────
# Bounds derivation: the endpoints ARE existing anchor values, so a variant can
# never be looser than the loosest anchor or tighter than the tightest.
HULL: Dict[str, Tuple[float, float]] = {
    "stop_loss_pct": (0.15, 0.30),
    "target_profit_pct": (0.25, 0.50),
    "min_score_threshold": (30.0, 70.0),
    "risk_multiplier": (0.8, 1.2),
    "max_risk_pct_per_trade": (0.015, 0.035),
    "budget_cap_pct": (0.25, 0.35),
    "max_positions_open": (2, 4),
    "max_suggestions_per_day": (2, 4),
    "min_dte_to_exit": (7, 14),
}
HELD_AXES = ("sizing_method", "max_dte_to_enter")  # NEVER varied (no consumer)

AXIS_CODE: Dict[str, str] = {
    "stop_loss_pct": "stop",
    "target_profit_pct": "tp",
    "min_score_threshold": "score",
    "risk_multiplier": "mult",
    "max_risk_pct_per_trade": "riskpct",
    "budget_cap_pct": "budget",
    "max_positions_open": "pos",
    "max_suggestions_per_day": "sugg",
    "min_dte_to_exit": "dteexit",
}
FAMILY_PREFIX = {"aggressive": "agg", "neutral": "neu", "conservative": "con"}

# ── The design grid (deterministic, reviewable) ──────────────────────────────
# PRIMARY axes get two probes per anchor (spanning the hull away from the
# anchor's own value); SECONDARY axes get one probe. 4*2 + 5*1 = 13 single-axis
# variants per anchor -> 39; plus 8 documented two-axis "dial" combos -> 47.
SINGLE_AXIS_PROBES: Dict[str, Dict[str, List[Any]]] = {
    "aggressive": {
        # primary (2 probes)
        "stop_loss_pct": [0.15, 0.20],
        "target_profit_pct": [0.25, 0.35],
        "min_score_threshold": [50.0, 70.0],
        "risk_multiplier": [0.8, 1.0],
        # secondary (1 probe)
        "max_risk_pct_per_trade": [0.025],
        "budget_cap_pct": [0.25],
        "max_positions_open": [2],
        "max_suggestions_per_day": [2],
        "min_dte_to_exit": [10],
    },
    "neutral": {
        "stop_loss_pct": [0.15, 0.30],
        "target_profit_pct": [0.25, 0.50],
        "min_score_threshold": [30.0, 70.0],
        "risk_multiplier": [0.8, 1.2],
        "max_risk_pct_per_trade": [0.035],
        "budget_cap_pct": [0.35],
        "max_positions_open": [4],
        "max_suggestions_per_day": [4],
        "min_dte_to_exit": [14],
    },
    "conservative": {
        "stop_loss_pct": [0.20, 0.30],
        "target_profit_pct": [0.35, 0.50],
        "min_score_threshold": [30.0, 50.0],
        "risk_multiplier": [1.0, 1.2],
        "max_risk_pct_per_trade": [0.025],
        "budget_cap_pct": [0.35],
        "max_positions_open": [3],
        "max_suggestions_per_day": [3],
        "min_dte_to_exit": [10],
    },
}

# 8 two-axis combos: naturally-coupled dials (exit-tightness, sizing, entry).
TWO_AXIS_COMBOS: List[Tuple[str, Dict[str, Any]]] = [
    ("aggressive", {"stop_loss_pct": 0.25, "target_profit_pct": 0.40}),
    ("aggressive", {"budget_cap_pct": 0.30, "risk_multiplier": 1.0}),
    ("aggressive", {"min_score_threshold": 50.0, "max_positions_open": 3}),
    ("neutral", {"stop_loss_pct": 0.15, "target_profit_pct": 0.25}),
    ("neutral", {"budget_cap_pct": 0.35, "risk_multiplier": 1.2}),
    ("neutral", {"max_risk_pct_per_trade": 0.035, "budget_cap_pct": 0.35}),
    ("conservative", {"stop_loss_pct": 0.20, "target_profit_pct": 0.35}),
    ("conservative", {"min_score_threshold": 50.0, "max_positions_open": 3}),
]


# ── Canonicalization + hashing ────────────────────────────────────────────────

def _coerce(field: str, value: Any) -> Any:
    if field in FLOAT_FIELDS:
        return float(value)
    if field in INT_FIELDS:
        return int(value)
    return str(value)


def canonical_config(config: Dict[str, Any]) -> str:
    """Deterministic canonical JSON: type-coerced fields, sorted keys, compact
    separators. Byte-identical for equal semantic configs regardless of input
    numeric type (0.30 vs 0.3, 1 vs 1.0)."""
    if set(config) != set(ALL_FIELDS):
        missing = sorted(set(ALL_FIELDS) - set(config))
        extra = sorted(set(config) - set(ALL_FIELDS))
        raise ValueError(f"config field mismatch: missing={missing} extra={extra}")
    normalized = {k: _coerce(k, config[k]) for k in config}
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def config_hash(canonical: str) -> str:
    """SHA-256 hex of the canonical string (matches SQL
    encode(digest(config_canonical,'sha256'),'hex'))."""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _token(axis: str, value: Any) -> str:
    if axis == "min_score_threshold":
        return str(int(round(float(value))))
    if axis in ("risk_multiplier", "stop_loss_pct", "target_profit_pct",
                "budget_cap_pct"):
        return f"{int(round(float(value) * 100)):03d}"
    if axis == "max_risk_pct_per_trade":
        return f"{int(round(float(value) * 1000)):03d}"
    if axis == "min_dte_to_exit":
        return f"{int(value):02d}"
    # max_positions_open, max_suggestions_per_day
    return str(int(value))


def _direction(axis: str, base: Any, new: Any) -> str:
    if float(new) == float(base):
        return "same"
    return "raised" if float(new) > float(base) else "lowered"


def _variant_row(family: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    anchor = ANCHORS[family]
    config = dict(anchor)
    for axis, val in changes.items():
        config[axis] = val
    changed_axes = sorted(changes)
    # id
    prefix = FAMILY_PREFIX[family]
    parts = [f"{AXIS_CODE[axis]}{_token(axis, changes[axis])}"
             for axis in changed_axes]
    reg_id = f"{prefix}_{'_'.join(parts)}_v1"
    # rationale
    frags = []
    for axis in changed_axes:
        lo, hi = HULL[axis]
        frags.append(
            f"{axis} {_fmt(anchor[axis])}->{_fmt(changes[axis])} "
            f"({_direction(axis, anchor[axis], changes[axis])}; "
            f"hull [{_fmt(lo)},{_fmt(hi)}])"
        )
    rationale = f"{family} anchor with " + "; ".join(frags)
    canonical = canonical_config(config)
    return {
        "policy_registration_id": reg_id,
        "policy_family": family,
        "anchor_lineage": f"{family}_anchor",
        "policy_config": config,
        "config_canonical": canonical,
        "config_hash": config_hash(canonical),
        "schema_version": SCHEMA_VERSION,
        "approval_status": "approved",
        "effective_epoch": EFFECTIVE_EPOCH,
        "changed_axes": changed_axes,
        "design_rationale": rationale,
        "created_by": CREATED_BY,
    }


def _anchor_row(family: str) -> Dict[str, Any]:
    config = dict(ANCHORS[family])
    canonical = canonical_config(config)
    return {
        "policy_registration_id": f"{family}_anchor",
        "policy_family": family,
        "anchor_lineage": f"{family}_anchor",
        "policy_config": config,
        "config_canonical": canonical,
        "config_hash": config_hash(canonical),
        "schema_version": SCHEMA_VERSION,
        "approval_status": "approved",
        "effective_epoch": EFFECTIVE_EPOCH,
        "changed_axes": [],
        "design_rationale": (
            f"Anchor: verbatim policy_lab_cohorts.policy_config for the "
            f"{family} cohort ({ANCHOR_META[family]}); no axis varied."
        ),
        "created_by": CREATED_BY,
    }


def _fmt(value: Any) -> str:
    """Human-readable value for ids/manifest: ints render bare (45), floats via
    %g (0.3, 1.2, 1)."""
    if isinstance(value, int):
        return str(value)
    return "%g" % float(value)


def build_registrations() -> List[Dict[str, Any]]:
    """Return the exactly-50 registry rows, deterministically ordered:
    3 anchors, then 39 single-axis variants, then 8 two-axis combos."""
    rows: List[Dict[str, Any]] = []
    for family in ("aggressive", "neutral", "conservative"):
        rows.append(_anchor_row(family))
    for family in ("aggressive", "neutral", "conservative"):
        probes = SINGLE_AXIS_PROBES[family]
        for axis in [a for a in ALL_FIELDS if a in probes]:
            for value in probes[axis]:
                rows.append(_variant_row(family, {axis: value}))
    for family, changes in TWO_AXIS_COMBOS:
        rows.append(_variant_row(family, changes))

    _assert_invariants(rows)
    return rows


def _assert_invariants(rows: List[Dict[str, Any]]) -> None:
    assert len(rows) == 50, f"expected 50 rows, got {len(rows)}"
    ids = [r["policy_registration_id"] for r in rows]
    assert len(set(ids)) == 50, "duplicate registration ids"
    assert all(i and i.strip() for i in ids), "blank registration id"
    hashes = [r["config_hash"] for r in rows]
    assert len(set(hashes)) == 50, "duplicate config_hash (near-duplicate configs)"
    canons = [r["config_canonical"] for r in rows]
    assert len(set(canons)) == 50, "duplicate config_canonical"
    for r in rows:
        # held axes are always the anchor's verbatim value
        anchor = ANCHORS[r["policy_family"]]
        for axis in HELD_AXES:
            assert r["policy_config"][axis] == anchor[axis], (
                f"{r['policy_registration_id']} altered held axis {axis}"
            )
        # every changed axis is a consumed axis, within hull
        assert len(r["changed_axes"]) <= 2
        for axis in r["changed_axes"]:
            assert axis in CONSUMERS, f"varied non-consumed axis {axis}"
            lo, hi = HULL[axis]
            assert lo <= float(r["policy_config"][axis]) <= hi, (
                f"{r['policy_registration_id']} {axis} out of hull"
            )
        # stop is never looser than the loosest anchor (0.30 ceiling)
        assert float(r["policy_config"]["stop_loss_pct"]) <= 0.30
        # hash matches canonical
        assert r["config_hash"] == config_hash(r["config_canonical"])


# ── Coverage summary (for the manifest) ───────────────────────────────────────

def coverage_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    per_anchor: Dict[str, int] = {"aggressive": 0, "neutral": 0, "conservative": 0}
    per_axis: Dict[str, int] = {a: 0 for a in AXIS_CODE}
    anchors = 0
    single = 0
    combo = 0
    for r in rows:
        per_anchor[r["policy_family"]] += 1
        n = len(r["changed_axes"])
        if n == 0:
            anchors += 1
        elif n == 1:
            single += 1
        else:
            combo += 1
        for axis in r["changed_axes"]:
            per_axis[axis] += 1
    return {
        "total": len(rows),
        "anchors": anchors,
        "single_axis_variants": single,
        "two_axis_variants": combo,
        "per_anchor": per_anchor,
        "per_axis": per_axis,
    }


# ── Artifact generators (manifest md + seed sql) ──────────────────────────────

def render_manifest() -> str:
    rows = build_registrations()
    cov = coverage_summary(rows)
    out: List[str] = []
    out.append("# Fleet policy design — 3 anchors + 47 variants (50 total)")
    out.append("")
    out.append(
        "Generated by `packages/quantum/policy_lab/fleet_policy_design.py` "
        "(`py -3.11 -m packages.quantum.policy_lab.fleet_policy_design`). "
        "The DATABASE (`policy_registrations`) is runtime truth; this manifest "
        "is provenance. Do not hand-edit — regenerate."
    )
    out.append("")
    out.append("## Anchors (VERIFIED-DB, verbatim)")
    out.append("")
    out.append(
        "Queried live from `policy_lab_cohorts.policy_config` (2026-07-18). "
        "DB wins as anchor truth (note: code `AGGRESSIVE.stop_loss_pct=0.65` "
        "diverges from DB `0.30` — the DB value is used)."
    )
    out.append("")
    out.append("| anchor | " + " | ".join(ALL_FIELDS) + " |")
    out.append("|" + "---|" * (len(ALL_FIELDS) + 1))
    for fam in ("aggressive", "neutral", "conservative"):
        a = ANCHORS[fam]
        out.append("| " + fam + " | "
                   + " | ".join(_fmt(a[f]) if f not in STR_FIELDS else str(a[f])
                                for f in ALL_FIELDS) + " |")
    out.append("")
    out.append("## Axes varied + REAL consumers (file:line)")
    out.append("")
    out.append("| axis | hull [min,max] | consumer(s) |")
    out.append("|---|---|---|")
    for axis in AXIS_CODE:
        lo, hi = HULL[axis]
        out.append(f"| `{axis}` | [{_fmt(lo)}, {_fmt(hi)}] | {CONSUMERS[axis]} |")
    out.append("")
    out.append(
        "**Held verbatim (NOT varied — no cohort-level consumer, grep-verified):"
        "** `sizing_method` (only `budget_proportional` is ever consumed; "
        "fork.py:723-726 sizes on budget_cap/max_risk directly, never branching "
        "on the string) and `max_dte_to_enter` (declared in config.py only; the "
        "scanner produces the shared opportunity set before any cohort config is "
        "read). Varying either would be an inert costume, so both carry the "
        "anchor value on all 50 rows."
    )
    out.append("")
    out.append("## Bounds derivation")
    out.append("")
    out.append(
        "Every varied value lies inside the 3-anchor CONVEX HULL "
        "`[min_anchor, max_anchor]`. The endpoints are themselves existing "
        "anchor values, so no variant is looser than the loosest anchor nor "
        "tighter than the tightest. For `stop_loss_pct` the hull max is `0.30` "
        "— the live champion's stop and `config.py:_TIGHT_STOP_CEILING` — so no "
        "variant widens the live loss stop (doctrine section 5 / NEVER-DO)."
    )
    out.append("")
    out.append("## Coverage summary")
    out.append("")
    out.append(
        f"- Total rows: **{cov['total']}** "
        f"(anchors {cov['anchors']}, single-axis {cov['single_axis_variants']}, "
        f"two-axis {cov['two_axis_variants']})"
    )
    out.append(
        "- Per anchor lineage (incl. the anchor row): "
        + ", ".join(f"{k}={v}" for k, v in cov["per_anchor"].items())
    )
    out.append("- Axis coverage (times each axis is varied across all rows): "
               + ", ".join(f"{k}={v}" for k, v in cov["per_axis"].items()))
    out.append(
        "- Hash distinctness: all **50** `config_canonical` strings and all "
        "**50** `config_hash` values are distinct (asserted here and in the "
        "seed's post-commit `DO` block)."
    )
    out.append("")
    out.append("## Full grid")
    out.append("")
    out.append("| # | id | anchor | changed_axes | changed values | rationale |")
    out.append("|---|---|---|---|---|---|")
    for i, r in enumerate(rows, start=1):
        anchor = ANCHORS[r["policy_family"]]
        if r["changed_axes"]:
            vals = "; ".join(
                f"{ax}: {_fmt(anchor[ax])}->{_fmt(r['policy_config'][ax])}"
                for ax in r["changed_axes"]
            )
        else:
            vals = "(verbatim)"
        axes = ", ".join(r["changed_axes"]) or "(none — anchor)"
        out.append(
            f"| {i} | `{r['policy_registration_id']}` | "
            f"{r['anchor_lineage']} | {axes} | {vals} | "
            f"{r['design_rationale']} |"
        )
    out.append("")
    out.append("## config_hash (SHA-256 of config_canonical)")
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
    out.append("-- Seed transaction: 50 approved policy_registrations (small_tier_v1)")
    out.append("-- =============================================================================")
    out.append("-- NOT APPLIED BY THIS PR. Operator applies via the migration procedure.")
    out.append("--")
    out.append("-- Generated from packages/quantum/policy_lab/fleet_policy_design.py")
    out.append("-- (py -3.11 -m packages.quantum.policy_lab.fleet_policy_design). Requires")
    out.append("-- the 20260719000000_policy_registrations migration to be applied first.")
    out.append("--")
    out.append("-- config_hash is DERIVED here (never client-invented): the INSERT computes")
    out.append("-- encode(extensions.digest(config_canonical,'sha256'),'hex') inside the")
    out.append("-- transaction. pgcrypto is installed (schema `extensions`, verified via MCP).")
    out.append("-- The post-commit DO block re-asserts: exactly 50 rows, 50 distinct hashes,")
    out.append("-- 50 distinct canonical strings, and hash==sha256(canonical) for every row —")
    out.append("-- any failure RAISEs and rolls the whole seed back.")
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
    out.append(f"    {SCHEMA_VERSION}, 'approved', v.effective_epoch,")
    out.append("    v.changed_axes::jsonb, v.design_rationale, now(), now(), v.created_by")
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
    out.append("BEGIN")
    out.append("    SELECT count(*) INTO v_count")
    out.append("      FROM policy_registrations WHERE effective_epoch = 'small_tier_v1';")
    out.append("    IF v_count <> 50 THEN")
    out.append("        RAISE EXCEPTION 'policy_registrations seed: expected 50 rows, got %', v_count;")
    out.append("    END IF;")
    out.append("    SELECT count(DISTINCT config_hash) INTO v_distinct_hash")
    out.append("      FROM policy_registrations WHERE effective_epoch = 'small_tier_v1';")
    out.append("    IF v_distinct_hash <> 50 THEN")
    out.append("        RAISE EXCEPTION 'policy_registrations seed: expected 50 distinct config_hash, got %', v_distinct_hash;")
    out.append("    END IF;")
    out.append("    SELECT count(DISTINCT config_canonical) INTO v_distinct_canonical")
    out.append("      FROM policy_registrations WHERE effective_epoch = 'small_tier_v1';")
    out.append("    IF v_distinct_canonical <> 50 THEN")
    out.append("        RAISE EXCEPTION 'policy_registrations seed: expected 50 distinct config_canonical, got %', v_distinct_canonical;")
    out.append("    END IF;")
    out.append("    SELECT count(*) INTO v_hash_mismatch")
    out.append("      FROM policy_registrations")
    out.append("     WHERE effective_epoch = 'small_tier_v1'")
    out.append("       AND config_hash <> encode(extensions.digest(config_canonical, 'sha256'), 'hex');")
    out.append("    IF v_hash_mismatch <> 0 THEN")
    out.append("        RAISE EXCEPTION 'policy_registrations seed: % rows have config_hash != sha256(config_canonical)', v_hash_mismatch;")
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
        repo_root, "docs", "specs", "fleet_policy_design_50.md")
    seed_path = os.path.join(
        repo_root, "supabase", "seed-transactions",
        "policy_registrations_seed_50.sql")
    os.makedirs(os.path.dirname(seed_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_manifest())
    with open(seed_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_seed_sql())
    _rows = build_registrations()
    print(f"wrote {manifest_path}")
    print(f"wrote {seed_path}")
    print(f"rows={len(_rows)} distinct_hashes={len({r['config_hash'] for r in _rows})}")
