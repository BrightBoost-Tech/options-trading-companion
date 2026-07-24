"""Recurring independent shadow-fleet policy evaluator (C1).

For each natural source decision event, evaluate the ONE shared, champion-
independent candidate universe under every approved, bound micro-account policy
and persist typed per-policy dispositions. Decision evidence ONLY — this module
writes no ``trade_suggestions``, no orders, no broker call, and never touches a
live control, flag, threshold, or champion row.

Natural flow (sibling to ``maybe_enqueue_single_leg_shadow_scan``)::

    suggestions_open commits a COMPLETE decision tape
      -> maybe_enqueue_fleet_policy_eval()          # event-driven child enqueue
         - fleet readiness read FIRST (inactive/unbound -> true no-op, 0 writes)
         - scheduler-origin only; source-identity required
         - enqueue on the BACKGROUND queue, idempotent
      -> run_fleet_policy_eval(payload)             # child handler body
         - fleet readiness RE-READ (enqueue->claim race / operator retire)
         - load the ACTIVE bound micro-accounts (EMPTY while inactive)
         - build the SHARED candidate universe ONCE from the durable tape
         - for each active micro-account: policy filter/rank/size -> typed rows
      -> (C2, separate/gated) internal-paper lifecycle per micro-account

Isolation contract (doctrine §7, small-tier evidence contract): while the fleet
is not ``active`` the enqueue seam returns ``fleet_inactive`` before touching the
DB beyond a single status read; the child, if somehow invoked, re-reads status
and independently finds the active-micro-account set empty. Two guards, zero
business writes, zero provider calls, zero broker path.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from typing import Any, Callable, Dict, List, Mapping, Optional

from packages.quantum.brokers.execution_router import SHADOW_ONLY_ROUTING
from packages.quantum.policy_lab.config import PolicyConfig
from packages.quantum.policy_lab.shadow_fleet import FLEET_EPOCH
from packages.quantum.services.options_utils import compute_legs_fingerprint
from packages.quantum.services.td_scan_capture import (
    ENVELOPE_TABLE as SCAN_ENVELOPE_TABLE,
    scan_candidate_capture_enabled,
)

logger = logging.getLogger(__name__)

JOB_NAME = "shadow_fleet_evaluate"
EVALUATOR_VERSION = "fleet_policy_eval@2"  # v2: complete scan-envelope universe
NATURAL_PARENT_ORIGIN = "scheduler"
ACTIVE_FLEET_STATUS = "active"
ACTIVE_MICRO_STATE = "active"

# The v2 universe reads the champion-emitted enrichment from trade_suggestions
# (routing score + canonical max-loss basis) but is DEFINED by the complete
# immutable scan-envelope set. trade_suggestions is NEVER the primary universe.
ENRICHMENT_TABLE = "trade_suggestions"

# Score basis label mirrored from fork.py:580 (`sizing_metadata.score`), the
# canonical 0-100 routing quantity. Dollar `ev` is NEVER a routing input.
SCORE_BASIS = "sizing_metadata.score"


def _rows(result: Any) -> List[Dict[str, Any]]:
    rows = getattr(result, "data", None)
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


# ─────────────────────────────────────────────────────────────────────────────
# Readiness (queried at BOTH the enqueue seam and the child; the second read
# closes the enqueue->claim race and the operator-retire window).
# ─────────────────────────────────────────────────────────────────────────────
def load_fleet_readiness(
    client: Any,
    user_id: str,
    *,
    fleet_epoch: str = FLEET_EPOCH,
    capture_gate: Callable[[], bool] = scan_candidate_capture_enabled,
) -> Dict[str, Any]:
    """DB-authoritative fleet readiness. The fleet status read happens FIRST so a
    dark (inactive) deployment is a true no-op — a non-active status returns
    before any micro-account / policy / suggestion read.

    v2: an ACTIVE, bound, approved fleet is additionally gated on the shared
    candidate-CAPTURE surface (``capture_gate``). The fleet consumes the complete
    scan-envelope universe (``td_scan_envelopes``); if capture is disabled the
    current event has no envelopes, so readiness returns ``capture_surface_disabled``
    (ready=False, errors=0) rather than silently evaluating an empty universe or
    falling back to champion rows. This gate is decoupled from the terminal-
    distribution SCORING flag: capture is ON if the stable capture opt-in OR the
    legacy td-observe flag is truthy. The check runs LAST (only for a fleet that
    would otherwise evaluate), so the dark-state no-op is untouched.
    """

    try:
        fleet_result = (
            client.table("shadow_fleets")
            .select("id,user_id,epoch_name,status")
            .eq("epoch_name", fleet_epoch)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        fleets = _rows(fleet_result)
    except Exception as exc:
        # A FAILED read is never an empty/absent fleet — fail closed (no enqueue,
        # no loop). Propagating errors>0 makes the parent cycle partial.
        return {
            "status": "fleet_read_failed",
            "ready": False,
            "errors": 1,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "accounts": [],
        }

    if not fleets:
        return {"status": "fleet_absent", "ready": False, "errors": 0, "accounts": []}

    fleet = fleets[0]
    if str(fleet.get("status")) != ACTIVE_FLEET_STATUS:
        # THE no-op path: pending_legacy_terminal / ready / retired all return
        # here with zero further reads and zero writes.
        return {
            "status": "fleet_inactive",
            "ready": False,
            "errors": 0,
            "fleet_status": fleet.get("status"),
            "accounts": [],
        }

    fleet_id = str(fleet.get("id"))
    try:
        micro_result = (
            client.table("shadow_micro_accounts")
            .select("id,fleet_id,slot_number,portfolio_id,policy_registration_id,state,initial_cash")
            .eq("fleet_id", fleet_id)
            .eq("state", ACTIVE_MICRO_STATE)
            .order("slot_number")
            .execute()
        )
        micro_accounts = _rows(micro_result)
    except Exception as exc:
        return {
            "status": "micro_account_read_failed",
            "ready": False,
            "errors": 1,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "accounts": [],
        }

    # Defense in depth: even under an 'active' fleet, an unbound/blank policy id
    # is a corrupt activation — skip it (never fabricate a policy binding).
    bound = [
        row
        for row in micro_accounts
        if str(row.get("policy_registration_id") or "").strip()
    ]
    if not bound:
        # Active fleet but zero bound slots -> nothing to evaluate, still no-op.
        return {
            "status": "no_active_bound_accounts",
            "ready": False,
            "errors": 0,
            "fleet_id": fleet_id,
            "accounts": [],
        }

    policy_ids = sorted(
        {str(row.get("policy_registration_id")).strip() for row in bound}
    )
    try:
        policy_result = (
            client.table("policy_registrations")
            .select("policy_registration_id,effective_epoch,approval_status,policy_config,config_hash,schema_version")
            .in_("policy_registration_id", policy_ids)
            .eq("effective_epoch", fleet_epoch)
            .eq("approval_status", "approved")
            .execute()
        )
        policies = {
            str(row.get("policy_registration_id")): row
            for row in _rows(policy_result)
        }
    except Exception as exc:
        return {
            "status": "policy_read_failed",
            "ready": False,
            "errors": 1,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "accounts": [],
        }

    qualified: List[Dict[str, Any]] = []
    for account in bound:
        policy_id = str(account.get("policy_registration_id")).strip()
        policy = policies.get(policy_id)
        config = policy.get("policy_config") if policy else None
        if not policy or not isinstance(config, Mapping):
            # Bound to a non-approved / missing policy: skip this slot, never
            # invent a config. This slot contributes no evidence.
            continue
        qualified.append(
            {
                "shadow_micro_account_id": str(account.get("id")),
                "fleet_id": fleet_id,
                "slot_number": account.get("slot_number"),
                "portfolio_id": account.get("portfolio_id"),
                "policy_registration_id": policy_id,
                "policy_config": dict(config),
                "config_hash": policy.get("config_hash"),
                "schema_version": policy.get("schema_version"),
                "deployable_capital": _finite(account.get("initial_cash")),
            }
        )

    if not qualified:
        return {
            "status": "no_approved_bound_policies",
            "ready": False,
            "errors": 0,
            "fleet_id": fleet_id,
            "accounts": [],
        }

    # v2 capture-surface gate (LAST — only for a fleet that would evaluate). The
    # fleet's universe is the complete scan-envelope set; without capture ON the
    # current event carries no envelopes. Fail SAFE to not-ready (config gate,
    # errors=0) — never a silent empty universe, never a champion-row fallback.
    try:
        capture_on = bool(capture_gate())
    except Exception:
        # A gate-read fault is treated as capture OFF (fail-closed to not-ready).
        capture_on = False
    if not capture_on:
        return {
            "status": "capture_surface_disabled",
            "ready": False,
            "errors": 0,
            "fleet_id": fleet_id,
            "accounts": [],
        }

    return {
        "status": "ready",
        "ready": True,
        "errors": 0,
        "fleet_id": fleet_id,
        "accounts": sorted(qualified, key=lambda row: (row["slot_number"], row["policy_registration_id"])),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Enqueue seam
# ─────────────────────────────────────────────────────────────────────────────
def maybe_enqueue_fleet_policy_eval(
    client: Any,
    *,
    user_id: str,
    source_job_run_id: Optional[str],
    source_decision_id: Optional[str],
    source_code_sha: Optional[str],
    as_of: Optional[str],
    parent_origin: Optional[str],
    fleet_epoch: str = FLEET_EPOCH,
    readiness_loader: Callable[..., Dict[str, Any]] = load_fleet_readiness,
    enqueue_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    origin_builder: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Enqueue one fleet-evaluator child for a complete natural parent decision.

    The readiness read happens BEFORE validating source ids so a dark (inactive)
    fleet stays a true no-op. Only the scheduler origin is admitted; an operator-
    forced scan cannot manufacture fleet evidence.
    """

    readiness = readiness_loader(client, user_id, fleet_epoch=fleet_epoch)
    if not readiness.get("ready"):
        return {
            "status": readiness.get("status", "not_ready"),
            "enqueued": False,
            "errors": int(readiness.get("errors") or 0),
        }

    if str(parent_origin or "") != NATURAL_PARENT_ORIGIN:
        return {"status": "non_natural_parent", "enqueued": False, "errors": 0}

    required = {
        "source_job_run_id": source_job_run_id,
        "source_decision_id": source_decision_id,
        "user_id": user_id,
        "as_of": as_of,
    }
    missing = sorted(k for k, v in required.items() if not str(v or "").strip())
    if missing:
        return {
            "status": "source_identity_missing",
            "enqueued": False,
            "errors": 1,
            "missing": missing,
        }

    if enqueue_fn is None:
        from packages.quantum.public_tasks import enqueue_job_run as enqueue_fn
    if origin_builder is None:
        from packages.quantum.jobs.origin import build_event_origin as origin_builder

    payload = {
        "source_job_run_id": str(source_job_run_id),
        "source_decision_id": str(source_decision_id),
        "source_code_sha": source_code_sha,
        "source_as_of": str(as_of),
        "user_id": str(user_id),
        "fleet_epoch": fleet_epoch,
    }
    try:
        from packages.quantum.jobs.rq_enqueue import BACKGROUND_QUEUE

        enqueued = enqueue_fn(
            job_name=JOB_NAME,
            idempotency_key=f"{JOB_NAME}:{source_decision_id}:{fleet_epoch}",
            payload=payload,
            queue_name=BACKGROUND_QUEUE,
            origin=origin_builder(
                "fleet_policy_eval_after_decision",
                parent_job_run_id=str(source_job_run_id),
            ),
        )
    except Exception as exc:
        logger.exception("fleet policy-eval child enqueue failed")
        return {
            "status": "enqueue_failed",
            "enqueued": False,
            "errors": 1,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }

    result = enqueued if isinstance(enqueued, dict) else {}
    terminal_skip = bool(result.get("skipped"))
    actually_queued = bool(result.get("rq_job_id")) and not terminal_skip
    return {
        "status": result.get("status", "queued"),
        "enqueued": actually_queued,
        "errors": 0,
        "job_run_id": result.get("job_run_id"),
        "rq_job_id": result.get("rq_job_id"),
        "skipped": terminal_skip,
    }


# ─────────────────────────────────────────────────────────────────────────────
# The ONE shared candidate universe (§4), v2. Built once, read-only across all 50
# policies. Champion-INDEPENDENT membership: the COMPLETE immutable scan-envelope
# set (every fully-constructed candidate — emitted AND rejected-before-
# persistence). Never re-scanned, never a live fetch.
# ─────────────────────────────────────────────────────────────────────────────
class UniverseUnavailable(RuntimeError):
    """A failed universe read — never an empty universe (E8-3 []-sentinel)."""


def _default_champion_resolver(client: Any, user_id: str) -> str:
    from packages.quantum.policy_lab.champion import get_current_champion

    return get_current_champion(user_id, client)


def _envelope_fingerprint(env: Mapping[str, Any]) -> Optional[str]:
    """Immutable candidate identity. Prefer the envelope's stored
    ``candidate_fingerprint`` (compute_legs_fingerprint, structure-only, == the
    trade_suggestions.legs_fingerprint by construction); defensively re-derive
    from the envelope legs if a stub omitted it. Never invents an id-based
    fingerprint (that would break the enrichment join)."""
    fp = env.get("candidate_fingerprint")
    if fp:
        return str(fp)
    blob = env.get("envelope") if isinstance(env.get("envelope"), Mapping) else {}
    legs = blob.get("legs")
    if isinstance(legs, list) and legs:
        try:
            return compute_legs_fingerprint({"legs": legs})
        except Exception:
            return None
    return None


def _load_scan_envelopes(client: Any, source_decision_id: str) -> List[Dict[str, Any]]:
    """The complete immutable candidate set for one cycle from ``td_scan_envelopes``
    (cycle_id == source_decision_id). Any read error — including the table being
    absent (migration unapplied) — raises ``UniverseUnavailable`` (fail-closed
    data_unavailable for every policy), NEVER a silent empty universe or a
    champion-row fallback."""
    try:
        result = (
            client.table(SCAN_ENVELOPE_TABLE)
            .select(
                "candidate_fingerprint,emitted,reject_reason,reject_gate,"
                "symbol,strategy,envelope"
            )
            .eq("cycle_id", source_decision_id)
            .execute()
        )
    except Exception as exc:
        raise UniverseUnavailable(
            f"scan-envelope read failed (surface absent or unreadable): "
            f"{type(exc).__name__}: {str(exc)[:200]}"
        ) from exc
    return _rows(result)


def _load_emitted_enrichment(
    client: Any, source_decision_id: str, champion: str
) -> Dict[str, Dict[str, Any]]:
    """Routing evidence for the EMITTED subset, keyed by legs_fingerprint. The
    fork tags the emitted rows to the champion cohort IN PLACE (fork.py:150-156),
    so the champion/NULL cohort read is exactly the champion-emitted set. This is
    ENRICHMENT, not the universe: it supplies the real ``sizing_metadata.score``
    (0-100 routing quantity) and ``max_loss_total`` (canonical per-contract
    max-loss basis) that live ONLY on persisted suggestions and are genuinely
    absent for pre-persistence rejects. Never fabricates either field."""
    query = (
        client.table(ENRICHMENT_TABLE)
        .select("id,decision_id,cohort_name,legs_fingerprint,sizing_metadata,order_json,ev,ev_raw")
        .eq("decision_id", source_decision_id)
    )
    if champion:
        query = query.or_(f"cohort_name.is.null,cohort_name.eq.{champion}")
    else:
        query = query.is_("cohort_name", "null")
    rows = _rows(query.execute())
    index: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        fp = row.get("legs_fingerprint")
        if not fp:
            continue
        # The champion tag is an in-place UPDATE, so one row per structure; first
        # writer wins on the rare transient NULL+champion pair (same evidence).
        index.setdefault(str(fp), row)
    return index


def build_candidate_universe(
    client: Any,
    source_decision_id: str,
    user_id: str,
    *,
    champion_resolver: Callable[[Any, str], str] = _default_champion_resolver,
    envelope_loader: Optional[Callable[[Any, str], List[Dict[str, Any]]]] = None,
    enrichment_loader: Optional[Callable[[Any, str, str], Dict[str, Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    """The COMPLETE, immutable candidate universe for one decision event (v2).

    Membership is DEFINED by ``td_scan_envelopes`` (cycle_id == source_decision_id)
    — every fully-constructed candidate the scanner built this cycle, EMITTED and
    REJECTED-before-persistence. The EMITTED subset is then enriched with its real
    routing score + canonical max-loss basis from ``trade_suggestions``, joined by
    ``candidate_fingerprint == legs_fingerprint`` (both compute_legs_fingerprint)
    within the champion/NULL cohort. A rejected candidate carries NO routing
    evidence (empty ``sizing_metadata``) — the policy returns ``data_unavailable``
    (never a fabricated score/max-loss, never a champion-row shortcut). The
    ``emitted`` flag is retained as PROVENANCE, never an eligibility shortcut.

    ``trade_suggestions`` is enrichment ONLY; it is NEVER the primary universe.
    A failed envelope read, enrichment read, or champion resolve raises
    ``UniverseUnavailable`` (fail-closed data_unavailable for every policy). A
    successful zero-envelope result is an honest-empty universe (no_candidate).
    """
    env_loader = envelope_loader or _load_scan_envelopes
    enrich_loader = enrichment_loader or _load_emitted_enrichment

    # 1. Complete immutable candidate set (PRIMARY universe).
    try:
        envelopes = env_loader(client, source_decision_id)
    except UniverseUnavailable:
        raise
    except Exception as exc:
        raise UniverseUnavailable(
            f"scan-envelope read failed: {type(exc).__name__}: {str(exc)[:200]}"
        ) from exc

    # 2. Champion-emitted enrichment (routing score + max-loss basis).
    try:
        champion = str(champion_resolver(client, user_id) or "").strip()
    except Exception as exc:
        raise UniverseUnavailable(
            f"champion resolve failed: {type(exc).__name__}: {str(exc)[:200]}"
        ) from exc
    try:
        enrichment = enrich_loader(client, source_decision_id, champion)
    except Exception as exc:
        raise UniverseUnavailable(
            f"enrichment read failed: {type(exc).__name__}: {str(exc)[:200]}"
        ) from exc

    # 3. Join by immutable candidate fingerprint + dedupe (distinct structures
    #    preserved; identical structures collapse to one).
    universe: List[Dict[str, Any]] = []
    seen: set = set()
    for env in envelopes:
        fp = _envelope_fingerprint(env)
        if not fp or fp in seen:
            continue
        seen.add(fp)
        match = enrichment.get(fp)
        blob = env.get("envelope") if isinstance(env.get("envelope"), Mapping) else {}
        if match:
            sizing_metadata = dict(match.get("sizing_metadata") or {})
            order_json = dict(match.get("order_json") or {})
            ev = match.get("ev")
            ev_raw = match.get("ev_raw")
            suggestion_id = str(match.get("id")) if match.get("id") else None
        else:
            # Rejected / unmatched: NO routing evidence (never fabricated).
            sizing_metadata = {}
            order_json = {
                "legs": blob.get("legs") or [],
                "contracts": blob.get("contracts") or 1,
            }
            ev = blob.get("production_ev")
            ev_raw = None
            suggestion_id = None
        universe.append(
            {
                "candidate_fingerprint": fp,
                "suggestion_id": suggestion_id,
                "emitted": bool(env.get("emitted")),
                "matched_emitted": bool(match),
                "sizing_metadata": sizing_metadata,
                "order_json": order_json,
                "ev": ev,
                "ev_raw": ev_raw,
                "symbol": env.get("symbol"),
                "strategy": env.get("strategy"),
                "reject_reason": env.get("reject_reason"),
                "reject_gate": env.get("reject_gate"),
            }
        )
    # Deterministic order: scored candidates by score desc (routing quantity),
    # unscored (rejected) last, then fingerprint — stable rank_at_decision across
    # the 50 policies and across retries.
    universe.sort(
        key=lambda s: (
            -(_finite((s["sizing_metadata"] or {}).get("score")) or float("-inf")),
            s["candidate_fingerprint"],
        )
    )
    return universe


def _legacy_candidate_fingerprint(row: Mapping[str, Any]) -> str:
    """(LEGACY) Structural identity used by the pre-v2 trade_suggestions-only
    universe. Kept only for ``build_trade_suggestions_universe`` — the v2 universe
    dedupes on the envelope's ``candidate_fingerprint`` (compute_legs_fingerprint)
    so it joins the enrichment surface."""
    order_json = row.get("order_json") or {}
    legs = order_json.get("legs")
    if isinstance(legs, list) and legs:
        key = {
            "underlying": order_json.get("underlying"),
            "strategy": order_json.get("strategy"),
            "legs": sorted(
                [str(leg.get("symbol")), str(leg.get("side")), leg.get("quantity")]
                for leg in legs
                if isinstance(leg, Mapping)
            ),
        }
        canonical = json.dumps(key, sort_keys=True, separators=(",", ":"), default=str)
        return "s:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "id:" + str(row.get("id"))


def build_trade_suggestions_universe(
    client: Any,
    source_decision_id: str,
    user_id: str,
    *,
    champion_resolver: Callable[[Any, str], str] = _default_champion_resolver,
) -> List[Dict[str, Any]]:
    """LEGACY (pre-v2) champion-emitted universe from ``trade_suggestions`` ONLY.

    ⚠ ACTIVATION-BLOCKED COMPATIBILITY FALLBACK. This reads ONLY the persisted
    (emitted) champion/NULL cohort rows — it CANNOT see candidates rejected before
    trade_suggestions, so it is NOT the complete universe and is NEVER wired into
    ``run_fleet_policy_eval`` (the active fleet path uses
    ``build_candidate_universe``). Retained for the dry-run's optional
    v1-vs-v2 comparison and to preserve the pre-v2 semantics. Producing fleet
    activation evidence from this surface is forbidden by the small-tier evidence
    contract (an experiment may claim only what it observes)."""
    try:
        champion = str(champion_resolver(client, user_id) or "").strip()
    except Exception as exc:
        raise UniverseUnavailable(
            f"champion resolve failed: {type(exc).__name__}: {str(exc)[:200]}"
        ) from exc

    try:
        query = (
            client.table(ENRICHMENT_TABLE)
            .select("id,decision_id,cohort_name,sizing_metadata,order_json,ev,ev_raw")
            .eq("decision_id", source_decision_id)
        )
        if champion:
            query = query.or_(f"cohort_name.is.null,cohort_name.eq.{champion}")
        else:
            query = query.is_("cohort_name", "null")
        result = query.execute()
    except Exception as exc:
        raise UniverseUnavailable(
            f"universe read failed: {type(exc).__name__}: {str(exc)[:200]}"
        ) from exc

    rows = _rows(result)
    universe: List[Dict[str, Any]] = []
    seen: set = set()
    for row in rows:
        sid = row.get("id")
        if not sid:
            continue
        fingerprint = _legacy_candidate_fingerprint(row)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        universe.append(
            {
                "candidate_fingerprint": fingerprint,
                "suggestion_id": str(sid),
                "emitted": True,
                "matched_emitted": True,
                "sizing_metadata": dict(row.get("sizing_metadata") or {}),
                "order_json": dict(row.get("order_json") or {}),
                "ev": row.get("ev"),
                "ev_raw": row.get("ev_raw"),
            }
        )
    universe.sort(
        key=lambda s: (
            -(_finite((s["sizing_metadata"] or {}).get("score")) or float("-inf")),
            s["candidate_fingerprint"],
        )
    )
    return universe


# ─────────────────────────────────────────────────────────────────────────────
# Per-policy evaluation — pure functions mirroring fork.py's canonical
# precedence + sizing arithmetic (fork.py:594-653 + 702-745), WITHOUT cloning
# trade_suggestions and WITHOUT champion contamination.
# ─────────────────────────────────────────────────────────────────────────────
class PolicyDecision:
    """One candidate's typed disposition under one policy (candidate-grain).

    v2 identity: ``candidate_fingerprint`` is the immutable candidate identity
    (present for EVERY candidate — emitted and rejected). ``suggestion_id`` is the
    source suggestion UUID, present ONLY for an emitted candidate matched to a
    persisted row (NULL for a pre-persistence reject)."""

    __slots__ = (
        "candidate_fingerprint",
        "suggestion_id",
        "disposition",
        "reason_codes",
        "rank_at_decision",
        "score_value",
        "sizing",
    )

    def __init__(
        self,
        candidate_fingerprint: str,
        suggestion_id: Optional[str],
        disposition: str,
        reason_codes: List[str],
        rank_at_decision: int,
        score_value: Optional[float],
        sizing: Dict[str, Any],
    ) -> None:
        self.candidate_fingerprint = candidate_fingerprint
        self.suggestion_id = suggestion_id
        self.disposition = disposition
        self.reason_codes = reason_codes
        self.rank_at_decision = rank_at_decision
        self.score_value = score_value
        self.sizing = sizing

    @property
    def candidate_id(self) -> str:
        """Back-compat label: the suggestion UUID when emitted, else the immutable
        fingerprint. Never the fabricated identity of an unscored candidate."""
        return self.suggestion_id or self.candidate_fingerprint


def _size_candidate(
    candidate: Mapping[str, Any],
    config: PolicyConfig,
    deployable_capital: float,
) -> Dict[str, Any]:
    """Micro-account sizing arithmetic mirroring fork._clone_suggestion_for_cohort
    (fork.py:702-745), with ONE deliberate divergence: fork forces
    ``max(1, ...)`` because the champion already decided to trade the structure;
    the fleet must report ``capital_rejected`` honestly when the $2k micro tier
    affords < 1 contract. It also NEVER fabricates a size when the per-contract
    max-loss basis is missing (H9 / doctrine §10 canonical-payoff): that is a
    typed capital-rejection, never a premium/zero/scaled fallback.

    Returns a dict with ``affordable`` bool + the sizing evidence.
    """

    order_json = candidate.get("order_json") or {}
    sizing_meta = candidate.get("sizing_metadata") or {}

    original_contracts = 1
    try:
        original_contracts = int(order_json.get("contracts") or 1)
    except (TypeError, ValueError):
        original_contracts = 1
    original_contracts = max(original_contracts, 1)

    max_loss_total = _finite(sizing_meta.get("max_loss_total"))
    budget = deployable_capital * config.budget_cap_pct
    max_risk = deployable_capital * config.max_risk_pct_per_trade * config.risk_multiplier
    effective_risk = min(budget, max_risk)

    if max_loss_total is None or max_loss_total <= 0:
        # No canonical per-contract max-loss => cannot size at the micro tier
        # without fabricating risk. Typed non-green (doctrine §10).
        return {
            "affordable": False,
            "reason": "max_loss_basis_unavailable",
            "contracts": 0,
            "budget": round(budget, 2),
            "max_risk": round(max_risk, 2),
            "effective_risk": round(effective_risk, 2),
            "per_contract_max_loss": None,
            "max_loss_total": None,
        }

    max_loss_per = max_loss_total / original_contracts
    affordable_contracts = int(math.floor(effective_risk / max_loss_per)) if max_loss_per > 0 else 0

    sizing: Dict[str, Any] = {
        "budget": round(budget, 2),
        "max_risk": round(max_risk, 2),
        "effective_risk": round(effective_risk, 2),
        "per_contract_max_loss": round(max_loss_per, 2),
        "deployable_capital": round(deployable_capital, 2),
    }
    if affordable_contracts < 1:
        sizing.update({"affordable": False, "reason": "insufficient_risk_budget", "contracts": 0})
        return sizing
    sizing.update(
        {
            "affordable": True,
            "contracts": affordable_contracts,
            "max_loss_total": round(max_loss_per * affordable_contracts, 2),
        }
    )
    return sizing


def evaluate_policy(
    universe: List[Mapping[str, Any]],
    policy_config: Mapping[str, Any],
    *,
    open_positions: int = 0,
    deployable_capital: float,
) -> List[PolicyDecision]:
    """Evaluate the shared universe under one policy. Precedence mirrors
    fork._evaluate_cohort_policy EXACTLY (fork.py:594-653): capacity binds first,
    then missing-score, then score < threshold; survivors are sized against the
    micro-account's own capital. Each candidate gets exactly one typed
    disposition. Pure function — no I/O.
    """

    config = PolicyConfig.from_dict(dict(policy_config))
    available_slots = max(0, config.max_positions_open - open_positions)
    max_new = min(config.max_suggestions_per_day, available_slots)

    decisions: List[PolicyDecision] = []
    accepted = 0
    for rank, candidate in enumerate(universe, start=1):
        fp = str(candidate.get("candidate_fingerprint") or "")
        suggestion_id = candidate.get("suggestion_id")
        sizing_meta = candidate.get("sizing_metadata") or {}
        score_f = _finite(sizing_meta.get("score"))

        # 1) NO routing score -> the candidate was never scored (rejected before
        #    persistence, or corrupt). We CANNOT rank/filter it: typed
        #    ``data_unavailable`` (never fabricated, never folded into a merit
        #    rejection). An unscored candidate consumes NO capacity slot — the
        #    universe sorts it last, so scored candidates bind capacity first.
        if score_f is None:
            decisions.append(
                PolicyDecision(
                    fp, suggestion_id, "data_unavailable",
                    ["routing_score_unavailable"], rank, None, {}
                )
            )
            continue

        # 2) Capacity binds FIRST among SCORED candidates (fork parity: the
        #    accepted set is byte-identical because an unscored candidate never
        #    consumes a slot in either path).
        if accepted >= max_new:
            reason = (
                "max_positions_reached"
                if open_positions >= config.max_positions_open
                else "daily_limit_reached"
            )
            decisions.append(
                PolicyDecision(fp, suggestion_id, "policy_rejected", [reason], rank, score_f, {})
            )
            continue

        # 3) Score below the policy bar (0-100 vs 0-100).
        if score_f < config.min_score_threshold:
            decisions.append(
                PolicyDecision(fp, suggestion_id, "policy_rejected", ["score_below_min"], rank, score_f, {})
            )
            continue

        # 4) Survived the policy filter -> size against the micro-account's $2k.
        sizing = _size_candidate(candidate, config, deployable_capital)
        # 4a) NO canonical max-loss basis -> cannot size without fabricating risk
        #     (doctrine §10 canonical-payoff). This is a MEASUREMENT gap, not a
        #     merit capital-rejection: typed ``data_unavailable``.
        if str(sizing.get("reason") or "") == "max_loss_basis_unavailable":
            decisions.append(
                PolicyDecision(
                    fp, suggestion_id, "data_unavailable",
                    ["max_loss_basis_unavailable"], rank, score_f, sizing
                )
            )
            continue
        # 4b) Real basis, but the $2k tier affords < 1 contract -> capital_rejected.
        if not sizing.get("affordable"):
            decisions.append(
                PolicyDecision(
                    fp, suggestion_id, "capital_rejected",
                    [str(sizing.get("reason") or "insufficient_risk_budget")],
                    rank, score_f, sizing,
                )
            )
            continue

        accepted += 1
        decisions.append(PolicyDecision(fp, suggestion_id, "selected", [], rank, score_f, sizing))

    return decisions


# ─────────────────────────────────────────────────────────────────────────────
# Evidence writer (two-grain run/decision; table-missing = typed no-op count,
# never a crash — mirrors SingleLegShadowEvidenceWriter).
# ─────────────────────────────────────────────────────────────────────────────
RUNS_TABLE = "fleet_policy_decision_runs"
DECISIONS_TABLE = "fleet_policy_decisions"

_TABLE_MISSING_MARKERS = (
    "pgrst205",
    "42p01",
    "could not find the table",
    "schema cache",
)


def _is_table_missing_error(exc: BaseException, table: str) -> bool:
    msg = str(exc).lower()
    if any(marker in msg for marker in _TABLE_MISSING_MARKERS):
        return True
    return "does not exist" in msg and table.lower() in msg


def _is_unique_violation(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "23505" in msg or "duplicate key" in msg or "already exists" in msg


def _utcnow_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class FleetPolicyEvidenceWriter:
    """Idempotent writer for ONE micro-account policy's evaluation of one event.

    The run row is UPDATE-able for status/counts (begin-run -> finish-run); the
    per-candidate decision rows are strictly append-only. A missing migration is
    surfaced as ``table_missing_noops`` (typed no-op), never a crash.
    """

    def __init__(
        self,
        supabase: Any,
        *,
        fleet_id: str,
        fleet_epoch: str,
        shadow_micro_account_id: str,
        policy_registration_id: str,
        source_decision_id: str,
        source_job_run_id: str,
        user_id: str,
        source_code_sha: Optional[str] = None,
        evaluator_version: str = EVALUATOR_VERSION,
        as_of: Optional[str] = None,
    ) -> None:
        self._sb = supabase
        self.fleet_id = str(fleet_id)
        self.fleet_epoch = str(fleet_epoch)
        self.shadow_micro_account_id = str(shadow_micro_account_id)
        self.policy_registration_id = str(policy_registration_id)
        self.source_decision_id = str(source_decision_id)
        self.source_job_run_id = str(source_job_run_id)
        self.user_id = str(user_id)
        self.source_code_sha = source_code_sha or "unknown"
        self.evaluator_version = evaluator_version
        self.as_of = as_of or _utcnow_iso()
        self.run_id: Optional[str] = None
        self._counters = {
            "runs_started": 0,
            "decisions_written": 0,
            "write_failures": 0,
            "table_missing_noops": 0,
            "duplicate_acks": 0,
        }

    def _execute(self, table: str, operation, *, allow_unique: bool = False) -> Optional[Any]:
        try:
            return operation().execute()
        except Exception as exc:
            if allow_unique and _is_unique_violation(exc):
                return "duplicate"
            if _is_table_missing_error(exc, table):
                self._counters["table_missing_noops"] += 1
                logger.error("fleet evidence table missing: %s (migration not applied)", table)
                return None
            self._counters["write_failures"] += 1
            logger.exception("fleet evidence write failed: table=%s", table)
            return None

    def begin_run(self) -> Optional[str]:
        payload = {
            "fleet_id": self.fleet_id,
            "fleet_epoch": self.fleet_epoch,
            "shadow_micro_account_id": self.shadow_micro_account_id,
            "policy_registration_id": self.policy_registration_id,
            "source_decision_id": self.source_decision_id,
            "source_job_run_id": self.source_job_run_id,
            "source_code_sha": self.source_code_sha,
            "evaluator_version": self.evaluator_version,
            "user_id": self.user_id,
            "as_of": self.as_of,
            "status": "running",
            "counts": {},
            "error_details": [],
            "started_at": _utcnow_iso(),
        }
        result = self._execute(
            RUNS_TABLE, lambda: self._sb.table(RUNS_TABLE).insert(payload), allow_unique=True
        )
        rows = getattr(result, "data", None) if result not in (None, "duplicate") else None
        if rows:
            self.run_id = str(rows[0]["run_id"])
        else:
            # Idempotent replay (run already exists) or the insert returned no
            # representation — fetch the durable run id by its unique key.
            fetched = self._execute(
                RUNS_TABLE,
                lambda: self._sb.table(RUNS_TABLE)
                .select("run_id")
                .eq("source_decision_id", self.source_decision_id)
                .eq("fleet_epoch", self.fleet_epoch)
                .eq("shadow_micro_account_id", self.shadow_micro_account_id)
                .limit(1),
            )
            fetched_rows = getattr(fetched, "data", None) if fetched is not None else None
            if fetched_rows:
                self.run_id = str(fetched_rows[0]["run_id"])
        if self.run_id:
            self._counters["runs_started"] += 1
        return self.run_id

    def record_decision(
        self,
        decision: "PolicyDecision",
        *,
        features_snapshot: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        if not self.run_id:
            return False
        # v2: the immutable candidate identity is the fingerprint (present for
        # EVERY candidate). The source suggestion UUID is present ONLY for an
        # emitted candidate matched to a persisted row — NULL for a pre-persistence
        # reject (never fabricated). decision_event_id == candidate_suggestion_id
        # (both the suggestion UUID or both NULL) to satisfy the table CHECK.
        fingerprint = str(decision.candidate_fingerprint or "")
        suggestion_id = decision.suggestion_id
        payload = {
            "run_id": self.run_id,
            "fleet_id": self.fleet_id,
            "fleet_epoch": self.fleet_epoch,
            "shadow_micro_account_id": self.shadow_micro_account_id,
            "policy_registration_id": self.policy_registration_id,
            "candidate_fingerprint": fingerprint,
            "decision_event_id": suggestion_id,
            "candidate_suggestion_id": suggestion_id,
            "disposition": decision.disposition,
            "rank_at_decision": decision.rank_at_decision,
            "reason_codes": list(decision.reason_codes or []),
            "features_snapshot": dict(features_snapshot or {}),
            "sizing": dict(decision.sizing or {}),
        }
        result = self._execute(
            DECISIONS_TABLE,
            lambda: self._sb.table(DECISIONS_TABLE).insert(payload),
            allow_unique=True,
        )
        if result is None:
            return False
        if result == "duplicate":
            self._counters["duplicate_acks"] += 1
        else:
            self._counters["decisions_written"] += 1
        return True

    def finish_run(
        self,
        *,
        status: str,
        counts: Optional[Mapping[str, Any]] = None,
        error_details: Optional[list] = None,
    ) -> bool:
        if not self.run_id:
            return False
        row = {
            "status": str(status),
            "counts": dict(counts or {}),
            "error_details": list(error_details or []),
            "finished_at": _utcnow_iso(),
        }
        result = self._execute(
            RUNS_TABLE,
            lambda: self._sb.table(RUNS_TABLE).update(row).eq("run_id", self.run_id),
        )
        return result is not None

    def counters_dict(self) -> Dict[str, int]:
        return dict(self._counters)


# ─────────────────────────────────────────────────────────────────────────────
# Child handler body
# ─────────────────────────────────────────────────────────────────────────────
def run_fleet_policy_eval(
    payload: Mapping[str, Any],
    *,
    client: Any,
    readiness_loader: Callable[..., Dict[str, Any]] = load_fleet_readiness,
    universe_builder: Callable[..., List[Dict[str, Any]]] = build_candidate_universe,
    writer_factory: Callable[..., FleetPolicyEvidenceWriter] = FleetPolicyEvidenceWriter,
    open_positions_loader: Optional[Callable[[Any, str], int]] = None,
) -> Dict[str, Any]:
    """Evaluate the shared universe under every active bound micro-account policy.

    Fleet readiness is RE-READ here (the enqueue->claim race / operator retire).
    While the fleet is inactive both guards hold: the re-read returns
    ``fleet_inactive`` AND the active-bound account set is empty, so no run, no
    decision, and no business write is ever produced.
    """

    counts: Dict[str, int] = {
        "policies": 0,
        "candidates_universe": 0,
        "candidates_emitted": 0,
        "candidates_rejected": 0,
        "selected": 0,
        "policy_rejected": 0,
        "capital_rejected": 0,
        "data_unavailable": 0,
        "runs_written": 0,
        "decisions_written": 0,
        "no_candidate_runs": 0,
        "data_unavailable_runs": 0,
        "evaluator_failed_runs": 0,
        "table_missing_noops": 0,
        "errors": 0,
    }
    errors: List[Dict[str, Any]] = []

    user_id = str(payload.get("user_id") or "").strip()
    source_job_run_id = str(payload.get("source_job_run_id") or "").strip()
    source_decision_id = str(payload.get("source_decision_id") or "").strip()
    fleet_epoch = str(payload.get("fleet_epoch") or FLEET_EPOCH).strip()
    if not user_id or not source_job_run_id or not source_decision_id:
        counts["errors"] = 1
        return {
            "ok": False,
            "status": "source_identity_missing",
            "counts": counts,
            "error_details": [
                {"stage": "validate_payload", "error": "user_id/source_job_run_id/source_decision_id required"}
            ],
        }

    readiness = readiness_loader(client, user_id, fleet_epoch=fleet_epoch)
    if not readiness.get("ready"):
        # No-op (fleet_inactive et al.) or a fail-closed read error.
        counts["errors"] = int(readiness.get("errors") or 0)
        return {
            "ok": counts["errors"] == 0,
            "status": readiness.get("status", "not_ready"),
            "counts": counts,
            "error_details": (
                [{"stage": "readiness", "error": readiness.get("error")}]
                if readiness.get("error")
                else []
            ),
        }

    accounts = readiness.get("accounts") or []
    fleet_id = str(readiness.get("fleet_id"))
    source_code_sha = payload.get("source_code_sha") or "unknown"
    as_of = payload.get("source_as_of")

    # Build the ONE shared universe. A failed read is data_unavailable for every
    # account (fail-closed) — never a silent empty universe.
    universe_unavailable = False
    try:
        universe = universe_builder(client, source_decision_id, user_id)
    except UniverseUnavailable as exc:
        universe = []
        universe_unavailable = True
        errors.append({"stage": "build_universe", "error": str(exc)[:200]})
        counts["errors"] += 1
    counts["candidates_universe"] = len(universe)
    counts["candidates_emitted"] = sum(1 for c in universe if c.get("matched_emitted"))
    counts["candidates_rejected"] = len(universe) - counts["candidates_emitted"]

    # Per-candidate PROVENANCE (emitted/rejected status is evidence, NOT an
    # eligibility shortcut) — stamped into each decision's features_snapshot.
    provenance: Dict[str, Dict[str, Any]] = {
        str(c.get("candidate_fingerprint")): {
            "emitted": bool(c.get("emitted")),
            "matched_emitted": bool(c.get("matched_emitted")),
            "symbol": c.get("symbol"),
            "strategy": c.get("strategy"),
            "reject_reason": c.get("reject_reason"),
            "reject_gate": c.get("reject_gate"),
            "score_basis": SCORE_BASIS,
        }
        for c in universe
    }

    for account in accounts:
        policy_id = str(account.get("policy_registration_id"))
        micro_id = str(account.get("shadow_micro_account_id"))
        writer = writer_factory(
            client,
            fleet_id=fleet_id,
            fleet_epoch=fleet_epoch,
            shadow_micro_account_id=micro_id,
            policy_registration_id=policy_id,
            source_decision_id=source_decision_id,
            source_job_run_id=source_job_run_id,
            user_id=user_id,
            source_code_sha=source_code_sha,
            as_of=as_of,
        )
        run_id = writer.begin_run()
        if not run_id:
            wc = writer.counters_dict()
            counts["table_missing_noops"] += int(wc.get("table_missing_noops") or 0)
            counts["errors"] += max(
                1, int(wc.get("write_failures") or 0) + int(wc.get("table_missing_noops") or 0)
            )
            errors.append({"stage": "begin_run", "policy_registration_id": policy_id})
            continue
        counts["policies"] += 1

        # data_unavailable: universe unreadable -> typed run-grain status, no rows.
        if universe_unavailable:
            writer.finish_run(status="data_unavailable", counts={"candidates_seen": None})
            counts["data_unavailable_runs"] += 1
            counts["runs_written"] += 1
            continue

        # no_candidate: universe successfully read but EMPTY (run-grain).
        if not universe:
            writer.finish_run(status="no_candidate", counts={"candidates_seen": 0})
            counts["no_candidate_runs"] += 1
            counts["runs_written"] += 1
            continue

        capital = account.get("deployable_capital")
        capital_f = _finite(capital)
        if capital_f is None or capital_f <= 0:
            # A failed/absent capital basis creates no score — fail closed.
            writer.finish_run(
                status="data_unavailable",
                counts={"candidates_seen": len(universe), "reason": "capital_basis_unavailable"},
            )
            counts["data_unavailable_runs"] += 1
            counts["runs_written"] += 1
            counts["errors"] += 1
            errors.append({"stage": "capital_basis", "policy_registration_id": policy_id})
            continue

        try:
            # C2 supplies a FAIL-CLOSED loader; a read failure raises and lands
            # as THIS policy's evaluator_failed (never a silent 0, never a crash
            # of the other 49). The call is INSIDE the per-policy try so its
            # failure is isolated. While inactive this branch is unreachable.
            open_positions = 0
            if open_positions_loader is not None:
                open_positions = int(open_positions_loader(client, micro_id))
            decisions = evaluate_policy(
                universe,
                account.get("policy_config") or {},
                open_positions=open_positions,
                deployable_capital=capital_f,
            )
        except Exception as exc:
            logger.exception("fleet policy evaluation failed: %s", policy_id)
            writer.finish_run(
                status="evaluator_failed",
                counts={"candidates_seen": len(universe)},
                error_details=[
                    {"stage": "evaluate_policy", "error_class": type(exc).__name__, "error": str(exc)[:200]}
                ],
            )
            counts["evaluator_failed_runs"] += 1
            counts["runs_written"] += 1
            counts["errors"] += 1
            errors.append(
                {"stage": "evaluate_policy", "policy_registration_id": policy_id, "error": str(exc)[:200]}
            )
            continue

        policy_counts = {
            "selected": 0,
            "policy_rejected": 0,
            "capital_rejected": 0,
            "data_unavailable": 0,
            "candidates_seen": len(universe),
        }
        for decision in decisions:
            ok = writer.record_decision(
                decision,
                features_snapshot=provenance.get(str(decision.candidate_fingerprint)),
            )
            policy_counts[decision.disposition] = policy_counts.get(decision.disposition, 0) + 1
            if not ok:
                errors.append(
                    {
                        "stage": "record_decision",
                        "policy_registration_id": policy_id,
                        "candidate": decision.candidate_id,
                    }
                )

        wc = writer.counters_dict()
        writer_errors = int(wc.get("write_failures") or 0)
        table_missing = int(wc.get("table_missing_noops") or 0)
        status = "partial" if (writer_errors or table_missing) else "succeeded"
        writer.finish_run(
            status=status,
            counts={**policy_counts, **wc},
            error_details=[e for e in errors if e.get("policy_registration_id") == policy_id][:10],
        )
        counts["runs_written"] += 1
        counts["selected"] += policy_counts["selected"]
        counts["policy_rejected"] += policy_counts["policy_rejected"]
        counts["capital_rejected"] += policy_counts["capital_rejected"]
        counts["data_unavailable"] += policy_counts["data_unavailable"]
        counts["decisions_written"] += int(wc.get("decisions_written") or 0)
        counts["table_missing_noops"] += table_missing
        counts["errors"] += writer_errors + table_missing

    status = "partial" if counts["errors"] else "succeeded"
    return {
        "ok": counts["errors"] == 0,
        "status": status,
        "source_decision_id": source_decision_id,
        "fleet_epoch": fleet_epoch,
        "counts": counts,
        "error_details": errors[:20],
    }
