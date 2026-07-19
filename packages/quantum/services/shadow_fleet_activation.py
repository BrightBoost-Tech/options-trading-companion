"""Shadow-fleet provisioning/activation service (F-SHADOW-CAPITAL-PARITY, 3A).

Operator-only service for the 50 x $2,000 small_tier_v1 shadow fleet.

Design contract (mirrored by supabase/migrations/
20260717090000_shadow_fleet_activation_rpc.sql — the drift-lock test pins
the two together):

* PURE readiness evaluator (`evaluate_readiness`) returning typed outcomes.
  Every read failure is `schema_unavailable` — a failed read NEVER reads as
  ready (the E8-3 []-sentinel lesson).
* Dry-run is the DEFAULT surface (`plan_provision` / `plan_activation`):
  full plan + readiness + receipt spec, zero writes of any kind.
* Execution (`execute_provision` / `execute_activation`) is fail-closed
  behind ALL of: the FLEET_ACTIVATION_AUTHORIZED env opt-in (strict '=1',
  behavioral-flag polarity per project doctrine section 3), the explicit
  operator confirm literal, an idempotency key, and — for activation — the
  operator-supplied policy-registration payload (never invented or
  defaulted) plus an attestation payload referencing the stale-order
  reconciliation receipt.
* Atomicity: each execute step is ONE `supabase.rpc(...)` call — a single
  server-side plpgsql transaction. supabase-py has no client transactions,
  so this service performs NO direct table writes anywhere; a failure
  before/inside the RPC leaves zero rows behind and no partially-visible
  activation.
* Legacy scope is membership-based, not timestamp-based: legacy = every
  paper_orders / paper_positions row whose portfolio_id is not one of THIS
  fleet's micro-account portfolios (NULL portfolio_id counts as legacy).
  Everything predating the fleet epoch is legacy by construction.
* Order terminality is an ALLOWLIST (`TERMINAL_ORDER_STATUSES`); any other
  status — the six stale 2026-04-09 'submitted' rows, 'needs_manual_review',
  unknown future statuses — blocks activation.
"""

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from packages.quantum.policy_lab.shadow_fleet import (
    CAPITAL_PER_ACCOUNT,
    FLEET_EPOCH,
    MICRO_ACCOUNT_COUNT,
)

logger = logging.getLogger(__name__)


# ── Typed readiness outcomes ────────────────────────────────────────────────
SCHEMA_UNAVAILABLE = "schema_unavailable"
LEGACY_POSITIONS_NOT_TERMINAL = "legacy_positions_not_terminal"
LEGACY_ORDERS_NOT_TERMINAL = "legacy_orders_not_terminal"
POLICY_REGISTRATION_MISSING = "policy_registration_missing"
POLICY_REGISTRATION_DUPLICATE = "policy_registration_duplicate"
# Registry-existence gates (Lane A): a structurally-valid id that is not an
# approved row in policy_registrations for the fleet epoch can never bind.
POLICY_NOT_REGISTERED = "policy_not_registered"
POLICY_NOT_APPROVED = "policy_not_approved"
SLOT_COUNT_INVALID = "slot_count_invalid"
CAPITAL_CONTRACT_INVALID = "capital_contract_invalid"
ALREADY_PROVISIONED = "already_provisioned"
ALREADY_ACTIVE = "already_active"
READY_TO_PROVISION = "ready_to_provision"
READY_TO_ACTIVATE = "ready_to_activate"

READINESS_OUTCOMES = frozenset({
    SCHEMA_UNAVAILABLE,
    LEGACY_POSITIONS_NOT_TERMINAL,
    LEGACY_ORDERS_NOT_TERMINAL,
    POLICY_REGISTRATION_MISSING,
    POLICY_REGISTRATION_DUPLICATE,
    POLICY_NOT_REGISTERED,
    POLICY_NOT_APPROVED,
    SLOT_COUNT_INVALID,
    CAPITAL_CONTRACT_INVALID,
    ALREADY_PROVISIONED,
    ALREADY_ACTIVE,
    READY_TO_PROVISION,
    READY_TO_ACTIVATE,
})

# Registry table + status contract (mirrors migration 20260719000000).
POLICY_REGISTRATIONS_TABLE = "policy_registrations"
APPROVED_STATUS = "approved"

# ── Fail-closed terminality allowlists (mirrored in the RPC migration) ──────
TERMINAL_ORDER_STATUSES = frozenset({
    "filled",
    "cancelled",
    "watchdog_cancelled",
    "expired",
    "rejected",
    "manual_close_complete",
})
TERMINAL_POSITION_STATUSES = frozenset({"closed"})

# ── Contract constants ──────────────────────────────────────────────────────
FLEET_ROUTING_MODE = "shadow_only"  # NEVER live_eligible
PROVISION_RPC = "rpc_shadow_fleet_provision"
ACTIVATE_RPC = "rpc_shadow_fleet_activate"
CONFIRM_LITERAL = "EXECUTE-SHADOW-FLEET"
AUTHORIZATION_ENV = "FLEET_ACTIVATION_AUTHORIZED"
PROVISION_RECEIPT_ALERT_TYPE = "shadow_fleet_provisioned"
ACTIVATION_RECEIPT_ALERT_TYPE = "shadow_fleet_activated"

ATTESTATION_REQUIRED_KEYS = (
    "stale_order_reconciliation_receipt",
    "legacy_terminal_verified_at",
    "attested_by",
    "expected_binding_fingerprint",
)


# ── Binding-manifest canonical serialization (client↔SQL, ONE definition) ────
# The activation binding is the slot→policy_registration_id map DERIVED
# server-side by `ORDER BY policy_registration_id ASC` over the 50 approved
# registry rows (slot N ← the Nth id). This ONE canonical serialization is
# mirrored byte-for-byte inside the hardened activation RPC (migration
# 20260719020000) so the client fingerprint and the SQL fingerprint are taken
# over identical bytes. Ids are constrained to a charset that json.dumps never
# escapes and the SQL `format('[%s,"%s"]', slot, id)` builder emits verbatim,
# guaranteeing byte parity (no quote/backslash/unicode escaping divergence).
BINDING_ID_CHARSET = re.compile(r"^[A-Za-z0-9_-]+$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _canonical_policy_id(rid: Any) -> str:
    text = str(rid).strip()
    if not text or not BINDING_ID_CHARSET.match(text):
        raise ValueError(
            f"policy_registration_id outside the canonical binding charset "
            f"[A-Za-z0-9_-]: {rid!r}"
        )
    return text


def canonical_binding_manifest(mapping: Mapping[Any, Any]) -> str:
    """Deterministic canonical JSON for the slot→policy binding.

    A compact JSON array of ``[slot_number, policy_registration_id]`` pairs
    ordered by slot ascending: ``[[1,"id1"],[2,"id2"],...]``. The hardened
    activation RPC builds the byte-identical string, so the SQL fingerprint is
    over the same bytes. Keys may be int or str; ids are charset-guarded.
    """
    normalized = {int(k): v for k, v in mapping.items()}
    pairs = [[slot, _canonical_policy_id(normalized[slot])]
             for slot in sorted(normalized)]
    return json.dumps(pairs, separators=(",", ":"))


def binding_manifest_fingerprint(mapping: Mapping[Any, Any]) -> str:
    """SHA-256 hex of ``canonical_binding_manifest`` (mirrors the RPC's
    ``encode(extensions.digest(<canonical>,'sha256'),'hex')``)."""
    return hashlib.sha256(
        canonical_binding_manifest(mapping).encode("utf-8")
    ).hexdigest()


def derive_binding_manifest(approved_ids) -> Dict[int, str]:
    """Server-authoritative slot→id binding: slot N ← the Nth approved id in
    ``ORDER BY policy_registration_id ASC``.

    Requires exactly ``MICRO_ACCOUNT_COUNT`` distinct approved ids (the fleet
    has exactly 50 slots; an ambiguous count can never bind) — raises otherwise.
    """
    ordered = sorted(set(approved_ids))
    if len(ordered) != MICRO_ACCOUNT_COUNT:
        raise ShadowFleetActivationError(
            f"registry_not_exactly_50_approved: {len(ordered)} approved ids "
            f"(need {MICRO_ACCOUNT_COUNT})"
        )
    return {slot: ordered[slot - 1]
            for slot in range(1, MICRO_ACCOUNT_COUNT + 1)}


class ShadowFleetActivationError(Exception):
    """Base error for the provisioning/activation surface."""


class ActivationNotAuthorized(ShadowFleetActivationError):
    """FLEET_ACTIVATION_AUTHORIZED is not the strict opt-in value '1'."""


class OperatorConfirmationMissing(ShadowFleetActivationError):
    """The explicit confirm literal was not supplied."""


class AttestationInvalid(ShadowFleetActivationError):
    """The operator attestation payload is missing or malformed."""


class ReadinessBlocked(ShadowFleetActivationError):
    """Execution refused because readiness is not READY_TO_*."""

    def __init__(self, outcome: str, detail: Dict[str, Any]):
        self.outcome = outcome
        self.detail = detail
        super().__init__(f"readiness_blocked:{outcome}")


class BindingManifestMismatch(ShadowFleetActivationError):
    """The operator payload / attested fingerprint does not match the
    server-derived binding (ORDER BY policy_registration_id ASC). Defense in
    depth — the SQL RPC re-derives and is the final authority."""


@dataclass(frozen=True)
class ReadinessReport:
    """Typed readiness verdict; `detail` carries the evidence counts."""

    step: str
    outcome: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"step": self.step, "outcome": self.outcome, "detail": dict(self.detail)}


# ── Authorization / confirmation gates ──────────────────────────────────────

def activation_authorized() -> bool:
    """Strict behavioral opt-in: only the exact value '1' authorizes.

    Absent/empty -> refused (safe). A non-empty non-'1' value logs an
    explicit WARNING (project doctrine section 3) and is still refused.
    """
    raw = os.environ.get(AUTHORIZATION_ENV, "")
    value = raw.strip()
    if value == "1":
        return True
    if value:
        logger.warning(
            "[SHADOW_FLEET] %s=%r is not the strict opt-in '1' — execution refused",
            AUTHORIZATION_ENV, raw,
        )
    return False


def _require_authorized() -> None:
    if not activation_authorized():
        raise ActivationNotAuthorized(
            f"{AUTHORIZATION_ENV} is not '1' — shadow-fleet execution is "
            "prohibited (dry-run remains available)"
        )


def _require_confirm(confirm: Optional[str]) -> None:
    if confirm != CONFIRM_LITERAL:
        raise OperatorConfirmationMissing(
            f"explicit operator confirm={CONFIRM_LITERAL!r} is required"
        )


def _require_idempotency_key(idempotency_key: Optional[str]) -> str:
    if not idempotency_key or not str(idempotency_key).strip():
        raise ShadowFleetActivationError("idempotency_key is required")
    return str(idempotency_key).strip()


# ── Attestation validation (never defaulted) ────────────────────────────────

def validate_attestation(attestation: Any) -> Dict[str, Any]:
    """Validate the operator attestation; raise AttestationInvalid otherwise.

    Required keys:
      * stale_order_reconciliation_receipt — non-blank reference to the
        reconciliation receipt for the stale legacy orders. NOTE (scenario 5):
        only NON-BLANK is checked; existence is not validated (no durable typed
        receipt contract yet — see the prerequisite packet). OPEN by design.
      * legacy_terminal_verified_at — timezone-aware ISO-8601 timestamp;
        becomes shadow_fleets.legacy_terminal_verified_at verbatim.
      * attested_by — non-blank operator identity.
      * expected_binding_fingerprint — the operator-attested binding-manifest
        fingerprint (SHA-256 hex). The RPC re-derives and must match it.
    """
    if not isinstance(attestation, Mapping):
        raise AttestationInvalid("attestation_payload_required")
    receipt = str(attestation.get("stale_order_reconciliation_receipt") or "").strip()
    if not receipt:
        raise AttestationInvalid("attestation_missing_stale_order_reconciliation_receipt")
    attested_by = str(attestation.get("attested_by") or "").strip()
    if not attested_by:
        raise AttestationInvalid("attestation_missing_attested_by")
    raw_ts = attestation.get("legacy_terminal_verified_at")
    if not raw_ts:
        raise AttestationInvalid("attestation_missing_legacy_terminal_verified_at")
    try:
        parsed = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AttestationInvalid("attestation_unparseable_legacy_terminal_verified_at") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AttestationInvalid("attestation_legacy_terminal_verified_at_must_be_tz_aware")
    fingerprint = str(
        attestation.get("expected_binding_fingerprint") or ""
    ).strip().lower()
    if not fingerprint:
        raise AttestationInvalid("attestation_missing_expected_binding_fingerprint")
    if not SHA256_HEX.match(fingerprint):
        raise AttestationInvalid(
            "attestation_expected_binding_fingerprint_must_be_sha256_hex")
    return {
        "stale_order_reconciliation_receipt": receipt,
        "legacy_terminal_verified_at": parsed.isoformat(),
        "attested_by": attested_by,
        "expected_binding_fingerprint": fingerprint,
    }


# ── Policy-registration validation (never invented/defaulted) ───────────────

def _validate_policy_registrations(
    policy_registrations: Optional[Mapping[Any, Any]],
) -> tuple:
    """Return (outcome_or_None, normalized {int slot: str id}, detail)."""
    detail: Dict[str, Any] = {}
    if not policy_registrations:
        detail["reason"] = "no policy registrations supplied"
        return POLICY_REGISTRATION_MISSING, {}, detail

    normalized: Dict[int, str] = {}
    for key, value in policy_registrations.items():
        try:
            slot = int(str(key))
        except (TypeError, ValueError):
            detail["reason"] = f"non-integer slot key: {key!r}"
            return POLICY_REGISTRATION_MISSING, {}, detail
        if isinstance(key, bool) or not 1 <= slot <= MICRO_ACCOUNT_COUNT:
            detail["reason"] = f"slot key out of range: {key!r}"
            return POLICY_REGISTRATION_MISSING, {}, detail
        if slot in normalized:
            detail["reason"] = f"duplicate slot key: {slot}"
            return POLICY_REGISTRATION_MISSING, {}, detail
        rid = str(value or "").strip()
        if not rid:
            detail["reason"] = f"blank policy id for slot {slot}"
            return POLICY_REGISTRATION_MISSING, {}, detail
        normalized[slot] = rid

    if set(normalized) != set(range(1, MICRO_ACCOUNT_COUNT + 1)):
        missing = sorted(set(range(1, MICRO_ACCOUNT_COUNT + 1)) - set(normalized))
        detail["reason"] = f"slots without a registration: {missing[:10]}"
        detail["registered_count"] = len(normalized)
        return POLICY_REGISTRATION_MISSING, {}, detail

    if len(set(normalized.values())) != MICRO_ACCOUNT_COUNT:
        seen: Dict[str, int] = {}
        dupes = []
        for slot, rid in sorted(normalized.items()):
            if rid in seen:
                dupes.append({"policy_registration_id": rid,
                              "slots": [seen[rid], slot]})
            else:
                seen[rid] = slot
        detail["reason"] = "duplicate policy registration ids"
        detail["duplicates"] = dupes[:10]
        return POLICY_REGISTRATION_DUPLICATE, {}, detail

    return None, normalized, detail


# ── Registry-approval validation (Lane A: exists + approved + epoch) ─────────

def _validate_registry_approvals(
    supabase, unique_ids, epoch: str,
) -> tuple:
    """Revalidate structurally-valid policy ids against the registry.

    Returns (outcome_or_None, detail). Additive gate — it can only BLOCK, never
    loosen. Each id must be a row in `policy_registrations` whose
    `effective_epoch` == the fleet epoch AND `approval_status` == 'approved'.

    * an id absent for this epoch            -> POLICY_NOT_REGISTERED
    * an id present but not 'approved'
      (draft / retired / revoked)            -> POLICY_NOT_APPROVED
    * the registry read fails (incl. the
      table not existing yet)                -> SCHEMA_UNAVAILABLE (fail-closed;
      a failed read is NEVER ready — the E8-3 []-sentinel lesson).
    """
    ids = sorted(set(unique_ids))
    try:
        res = (
            supabase.table(POLICY_REGISTRATIONS_TABLE)
            .select("policy_registration_id,approval_status,effective_epoch")
            .in_("policy_registration_id", ids)
            .eq("effective_epoch", epoch)
            .execute()
        )
        rows = list(res.data or [])
    except Exception as exc:  # fail-closed: a failed read is never ready
        logger.warning("[SHADOW_FLEET] registry read failed: %s", exc)
        return SCHEMA_UNAVAILABLE, {
            "error": f"{type(exc).__name__}: {exc}",
            "registry_epoch": epoch,
        }

    by_id = {r.get("policy_registration_id"): r for r in rows}
    missing = [rid for rid in ids if rid not in by_id]
    if missing:
        return POLICY_NOT_REGISTERED, {
            "registry_epoch": epoch,
            "missing_registration_ids": missing[:10],
            "missing_count": len(missing),
        }
    not_approved = [
        rid for rid in ids
        if str(by_id[rid].get("approval_status")) != APPROVED_STATUS
    ]
    if not_approved:
        return POLICY_NOT_APPROVED, {
            "registry_epoch": epoch,
            "unapproved": [
                {"policy_registration_id": rid,
                 "approval_status": by_id[rid].get("approval_status")}
                for rid in not_approved[:10]
            ],
            "unapproved_count": len(not_approved),
        }
    return None, {
        "registry_epoch": epoch,
        "registry_approved_count": len(ids),
    }


def fetch_approved_policy_ids(supabase, epoch: str) -> List[str]:
    """Provisioning-acceptance helper: the EXACT set of approved policy ids
    registered for `epoch`, sorted. Read-only.

    Fail-closed: raises on a read/shape failure rather than returning an empty
    list (which a caller could misread as 'zero approved policies'). Fable's
    provisioning step consumes this to know which ids exist to bind.
    """
    res = (
        supabase.table(POLICY_REGISTRATIONS_TABLE)
        .select("policy_registration_id,approval_status,effective_epoch")
        .eq("effective_epoch", epoch)
        .eq("approval_status", APPROVED_STATUS)
        .execute()
    )
    rows = res.data
    if rows is None:
        raise ShadowFleetActivationError(
            "policy_registrations read returned no data attribute")
    return sorted({
        r["policy_registration_id"] for r in rows
        if r.get("policy_registration_id")
    })


# ── Fleet-contract validation ───────────────────────────────────────────────

def _validate_fleet_contract(
    fleet: Mapping[str, Any], micro_rows: List[Mapping[str, Any]],
) -> Optional[tuple]:
    """Return (outcome, detail) when the provisioned rows violate the
    50-slot / $2k contract, else None."""
    slots = sorted(
        row.get("slot_number") for row in micro_rows
        if row.get("slot_number") is not None
    )
    if len(micro_rows) != MICRO_ACCOUNT_COUNT or slots != list(
        range(1, MICRO_ACCOUNT_COUNT + 1)
    ):
        return SLOT_COUNT_INVALID, {
            "slot_rows": len(micro_rows),
            "expected": MICRO_ACCOUNT_COUNT,
        }

    try:
        fleet_count = int(fleet.get("micro_account_count"))
        fleet_capital = float(fleet.get("capital_per_account"))
    except (TypeError, ValueError):
        return CAPITAL_CONTRACT_INVALID, {"reason": "fleet contract fields unreadable"}
    if (
        fleet_count != MICRO_ACCOUNT_COUNT
        or fleet_capital != CAPITAL_PER_ACCOUNT
        or bool(fleet.get("shared_capital_enabled"))
    ):
        return CAPITAL_CONTRACT_INVALID, {
            "micro_account_count": fleet_count,
            "capital_per_account": fleet_capital,
            "shared_capital_enabled": bool(fleet.get("shared_capital_enabled")),
        }

    bad_slots = []
    for row in micro_rows:
        try:
            net_liq = float(row.get("initial_net_liq"))
            cash = float(row.get("initial_cash"))
        except (TypeError, ValueError):
            bad_slots.append(row.get("slot_number"))
            continue
        if net_liq != CAPITAL_PER_ACCOUNT or cash != CAPITAL_PER_ACCOUNT:
            bad_slots.append(row.get("slot_number"))
    if bad_slots:
        return CAPITAL_CONTRACT_INVALID, {"bad_slots": bad_slots[:10]}
    return None


# ── PURE readiness evaluator ────────────────────────────────────────────────

def evaluate_readiness(
    supabase,
    user_id: str,
    *,
    step: str,
    policy_registrations: Optional[Mapping[Any, Any]] = None,
) -> ReadinessReport:
    """Read-only readiness verdict for `step` in {'provision', 'activate'}.

    Any read failure -> schema_unavailable (fail-closed): a failed read is
    never 'ready'. Legacy scope and terminality allowlists are documented in
    the module docstring.
    """
    if step not in ("provision", "activate"):
        raise ValueError(f"unknown step: {step!r}")

    detail: Dict[str, Any] = {}
    try:
        fleet_res = (
            supabase.table("shadow_fleets")
            .select("*")
            .eq("user_id", user_id)
            .eq("epoch_name", FLEET_EPOCH)
            .limit(1)
            .execute()
        )
        fleet = (fleet_res.data or [None])[0]
        detail["fleet_status"] = fleet.get("status") if fleet else None

        micro_rows: List[Dict[str, Any]] = []
        fleet_portfolio_ids: List[str] = []
        if fleet:
            micro_res = (
                supabase.table("shadow_micro_accounts")
                .select(
                    "id,slot_number,state,portfolio_id,"
                    "policy_registration_id,initial_net_liq,initial_cash"
                )
                .eq("fleet_id", fleet["id"])
                .execute()
            )
            micro_rows = list(micro_res.data or [])
            fleet_portfolio_ids = [
                row["portfolio_id"] for row in micro_rows
                if row.get("portfolio_id")
            ]

        # Legacy scope: every row NOT belonging to a fleet portfolio.
        # Server-side allowlist negation; unknown statuses are returned
        # (and therefore block) by construction.
        orders_res = (
            supabase.table("paper_orders")
            .select("id,status,portfolio_id,created_at")
            .not_.in_("status", sorted(TERMINAL_ORDER_STATUSES))
            .execute()
        )
        legacy_orders = [
            row for row in (orders_res.data or [])
            if row.get("portfolio_id") not in fleet_portfolio_ids
            or row.get("portfolio_id") is None
        ]
        positions_res = (
            supabase.table("paper_positions")
            .select("id,status,portfolio_id,created_at")
            .not_.in_("status", sorted(TERMINAL_POSITION_STATUSES))
            .execute()
        )
        legacy_positions = [
            row for row in (positions_res.data or [])
            if row.get("portfolio_id") not in fleet_portfolio_ids
            or row.get("portfolio_id") is None
        ]
    except Exception as exc:  # fail-closed: a failed read is never ready
        logger.warning("[SHADOW_FLEET] readiness read failed: %s", exc)
        return ReadinessReport(
            step=step,
            outcome=SCHEMA_UNAVAILABLE,
            detail={"error": f"{type(exc).__name__}: {exc}"},
        )

    order_status_counts: Dict[str, int] = {}
    for row in legacy_orders:
        status = str(row.get("status"))
        order_status_counts[status] = order_status_counts.get(status, 0) + 1
    detail["legacy_nonterminal_orders"] = len(legacy_orders)
    detail["legacy_nonterminal_order_statuses"] = order_status_counts
    detail["legacy_open_positions"] = len(legacy_positions)
    detail["terminal_order_allowlist"] = sorted(TERMINAL_ORDER_STATUSES)

    if step == "provision":
        if fleet and fleet.get("status") == "active":
            return ReadinessReport(step, ALREADY_ACTIVE, detail)
        if fleet:
            detail["fleet_id"] = fleet.get("id")
            return ReadinessReport(step, ALREADY_PROVISIONED, detail)
        # Provisioning creates inert pending_legacy_terminal rows, so a dirty
        # legacy book does not block it (the migration's own design).
        return ReadinessReport(step, READY_TO_PROVISION, detail)

    # step == "activate"
    if not fleet:
        detail["reason"] = "fleet_not_provisioned; run the provision step first"
        return ReadinessReport(step, READY_TO_PROVISION, detail)
    detail["fleet_id"] = fleet.get("id")
    if fleet.get("status") == "active":
        return ReadinessReport(step, ALREADY_ACTIVE, detail)

    contract_violation = _validate_fleet_contract(fleet, micro_rows)
    if contract_violation is not None:
        outcome, extra = contract_violation
        detail.update(extra)
        return ReadinessReport(step, outcome, detail)

    if legacy_positions:
        detail["sample_position_ids"] = [
            row.get("id") for row in legacy_positions[:10]
        ]
        return ReadinessReport(step, LEGACY_POSITIONS_NOT_TERMINAL, detail)
    if legacy_orders:
        detail["sample_order_ids"] = [row.get("id") for row in legacy_orders[:10]]
        return ReadinessReport(step, LEGACY_ORDERS_NOT_TERMINAL, detail)

    reg_outcome, normalized, reg_detail = _validate_policy_registrations(
        policy_registrations
    )
    detail.update(reg_detail)
    if reg_outcome is not None:
        return ReadinessReport(step, reg_outcome, detail)

    # Registry-existence gate (Lane A): every structurally-valid id must be an
    # approved policy_registrations row for THIS fleet epoch. Additive gate,
    # fail-closed (registry read failure / absent table -> schema_unavailable).
    # retired/revoked -> POLICY_NOT_APPROVED, so they can never newly bind.
    registry_outcome, registry_detail = _validate_registry_approvals(
        supabase, set(normalized.values()), FLEET_EPOCH,
    )
    detail.update(registry_detail)
    if registry_outcome is not None:
        return ReadinessReport(step, registry_outcome, detail)

    detail["registered_slots"] = len(normalized)
    return ReadinessReport(step, READY_TO_ACTIVATE, detail)


# ── Receipt specs (returned in dry-run; WRITTEN only by the RPCs) ───────────

def build_receipt_spec(
    step: str,
    user_id: str,
    idempotency_key: Optional[str],
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """risk_alerts info-row spec for the audit receipt. The service only
    RETURNS this; the actual insert happens inside the execute RPC."""
    alert_type = (
        PROVISION_RECEIPT_ALERT_TYPE if step == "provision"
        else ACTIVATION_RECEIPT_ALERT_TYPE
    )
    metadata: Dict[str, Any] = {
        "step": step,
        "idempotency_key": idempotency_key or "<required-at-execute>",
        "epoch_name": FLEET_EPOCH,
        "micro_account_count": MICRO_ACCOUNT_COUNT,
        "capital_per_account": CAPITAL_PER_ACCOUNT,
        "shared_capital": False,
        "routing_mode": FLEET_ROUTING_MODE,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return {
        "user_id": user_id,
        "alert_type": alert_type,
        "severity": "info",
        "message": f"Shadow fleet {FLEET_EPOCH} {step} receipt "
                   f"(50 x $2,000 isolated shadow_only slots)",
        "resolved": False,
        "metadata": metadata,
    }


# ── Dry-run / plan mode (DEFAULT; zero writes) ──────────────────────────────

def plan_provision(
    supabase, user_id: str, *, idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Full provision plan + readiness. Performs zero writes."""
    readiness = evaluate_readiness(supabase, user_id, step="provision")
    return {
        "mode": "dry_run",
        "step": "provision",
        "writes_performed": 0,
        "readiness": readiness.as_dict(),
        "would_execute": readiness.outcome == READY_TO_PROVISION,
        "authorization_env": AUTHORIZATION_ENV,
        "authorized": activation_authorized(),
        "plan": {
            "rpc": PROVISION_RPC,
            "fleet_row": {
                "epoch_name": FLEET_EPOCH,
                "status": "pending_legacy_terminal",
                "micro_account_count": MICRO_ACCOUNT_COUNT,
                "capital_per_account": CAPITAL_PER_ACCOUNT,
                "shared_capital_enabled": False,
            },
            "portfolios": {
                "count": MICRO_ACCOUNT_COUNT,
                "routing_mode": FLEET_ROUTING_MODE,
                "cash_balance": CAPITAL_PER_ACCOUNT,
                "net_liq": CAPITAL_PER_ACCOUNT,
            },
            "slots": {
                "count": MICRO_ACCOUNT_COUNT,
                "state": "inactive",
            },
        },
        "receipt_spec": build_receipt_spec("provision", user_id, idempotency_key),
    }


def plan_activation(
    supabase,
    user_id: str,
    *,
    idempotency_key: Optional[str] = None,
    policy_registrations: Optional[Mapping[Any, Any]] = None,
    attestation: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Full activation plan + readiness. Performs zero writes.

    Attestation is VALIDATED and reported here but only required at execute.
    """
    readiness = evaluate_readiness(
        supabase, user_id, step="activate",
        policy_registrations=policy_registrations,
    )
    attestation_valid = False
    attestation_error: Optional[str] = None
    if attestation is not None:
        try:
            validate_attestation(attestation)
            attestation_valid = True
        except AttestationInvalid as exc:
            attestation_error = str(exc)
    else:
        attestation_error = "attestation_not_supplied"

    # Server-derived binding fingerprint (zero-write; best-effort). The operator
    # attests this exact value; the RPC re-derives and is the final authority.
    derived_fingerprint: Optional[str] = None
    binding_fingerprint_matches: Optional[bool] = None
    try:
        derived_fingerprint = binding_manifest_fingerprint(
            derive_binding_manifest(fetch_approved_policy_ids(supabase, FLEET_EPOCH))
        )
    except Exception as exc:  # fail-closed: unknown fingerprint never executes
        logger.warning("[SHADOW_FLEET] binding fingerprint derivation failed: %s", exc)
        derived_fingerprint = None
    if attestation is not None and derived_fingerprint is not None:
        supplied = str(
            (attestation or {}).get("expected_binding_fingerprint") or ""
        ).strip().lower()
        binding_fingerprint_matches = bool(supplied) and supplied == derived_fingerprint

    return {
        "mode": "dry_run",
        "step": "activate",
        "writes_performed": 0,
        "readiness": readiness.as_dict(),
        "attestation_valid": attestation_valid,
        "attestation_error": attestation_error,
        "derived_binding_fingerprint": derived_fingerprint,
        "binding_fingerprint_matches": binding_fingerprint_matches,
        "would_execute": (
            readiness.outcome == READY_TO_ACTIVATE
            and attestation_valid
            and binding_fingerprint_matches is True
        ),
        "authorization_env": AUTHORIZATION_ENV,
        "authorized": activation_authorized(),
        "plan": {
            "rpc": ACTIVATE_RPC,
            "effective_at": "db_now_in_rpc_transaction",
            "legacy_terminal_verified_at": "from_attestation_only",
            "binding_rule": "server_derived_order_by_policy_registration_id_asc",
            "expected_binding_fingerprint": derived_fingerprint,
            "slots_to_activate": MICRO_ACCOUNT_COUNT,
        },
        "receipt_spec": build_receipt_spec("activate", user_id, idempotency_key),
    }


# ── Execution (blocked without env opt-in + confirm + payload) ──────────────

def execute_provision(
    supabase,
    user_id: str,
    *,
    idempotency_key: str,
    confirm: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute the provision step via the atomic RPC (single transaction)."""
    _require_authorized()
    _require_confirm(confirm)
    key = _require_idempotency_key(idempotency_key)

    readiness = evaluate_readiness(supabase, user_id, step="provision")
    if readiness.outcome in (ALREADY_PROVISIONED, ALREADY_ACTIVE):
        # Idempotent no-op — no RPC call, no writes.
        return {
            "mode": "execute",
            "step": "provision",
            "status": readiness.outcome,
            "writes_performed": 0,
            "readiness": readiness.as_dict(),
        }
    if readiness.outcome != READY_TO_PROVISION:
        raise ReadinessBlocked(readiness.outcome, readiness.detail)

    res = supabase.rpc(
        PROVISION_RPC,
        {"p_user_id": user_id, "p_idempotency_key": key},
    ).execute()
    logger.info("[SHADOW_FLEET] provision RPC result: %s", res.data)
    return {
        "mode": "execute",
        "step": "provision",
        "status": "rpc_complete",
        "result": res.data,
        "readiness": readiness.as_dict(),
    }


def execute_activation(
    supabase,
    user_id: str,
    *,
    idempotency_key: str,
    policy_registrations: Mapping[Any, Any],
    attestation: Mapping[str, Any],
    confirm: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute the activation step via the atomic RPC (single transaction).

    Requires the operator payload in full: unique pre-registered policy ids
    for all 50 slots and the attestation referencing the stale-order
    reconciliation receipt. The effective boundary is DB now() captured
    inside the RPC transaction — never passed from here.
    """
    _require_authorized()
    _require_confirm(confirm)
    key = _require_idempotency_key(idempotency_key)
    normalized_attestation = validate_attestation(attestation)

    readiness = evaluate_readiness(
        supabase, user_id, step="activate",
        policy_registrations=policy_registrations,
    )
    if readiness.outcome == ALREADY_ACTIVE:
        return {
            "mode": "execute",
            "step": "activate",
            "status": ALREADY_ACTIVE,
            "writes_performed": 0,
            "readiness": readiness.as_dict(),
        }
    if readiness.outcome != READY_TO_ACTIVATE:
        raise ReadinessBlocked(readiness.outcome, readiness.detail)

    _, normalized_registrations, _ = _validate_policy_registrations(
        policy_registrations
    )

    # ── Server-authoritative binding + defense-in-depth (SQL RPC is final) ───
    # Derive the binding from the registry (ORDER BY policy_registration_id ASC)
    # and cross-check BOTH the operator-attested fingerprint AND the operator's
    # slot map against it. On any mismatch the RPC is never called (zero writes).
    # The RPC re-derives inside its own transaction and is the final authority.
    derived_manifest = derive_binding_manifest(
        fetch_approved_policy_ids(supabase, FLEET_EPOCH)
    )
    derived_fingerprint = binding_manifest_fingerprint(derived_manifest)
    attested_fingerprint = normalized_attestation["expected_binding_fingerprint"]
    if attested_fingerprint != derived_fingerprint:
        raise BindingManifestMismatch(
            f"binding_fingerprint_mismatch: attested {attested_fingerprint} != "
            f"server-derived {derived_fingerprint}"
        )
    if normalized_registrations != derived_manifest:
        raise BindingManifestMismatch(
            "payload_binding_mismatch: operator slot map does not equal the "
            "server-derived ORDER BY policy_registration_id ASC binding"
        )

    res = supabase.rpc(
        ACTIVATE_RPC,
        {
            "p_user_id": user_id,
            "p_idempotency_key": key,
            "p_policy_registrations": {
                str(slot): rid
                for slot, rid in sorted(normalized_registrations.items())
            },
            "p_attestation": normalized_attestation,
            "p_expected_binding_fingerprint": attested_fingerprint,
        },
    ).execute()
    logger.info("[SHADOW_FLEET] activation RPC result: %s", res.data)
    return {
        "mode": "execute",
        "step": "activate",
        "status": "rpc_complete",
        "result": res.data,
        "readiness": readiness.as_dict(),
    }
