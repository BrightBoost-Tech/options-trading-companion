"""Canonical durable reconciliation-receipt WRITER wrapper (Lane A).

The SINGLE entry point that future reconciliation code / operator scripts call to
mint a durable, immutable ``fleet_reconciliation_receipts`` row — the receipts the
hardened activation RPC (``rpc_shadow_fleet_activate``, migration 20260720150000)
validates for scenario-5 EXISTENCE. Nothing else should INSERT that table.

Two responsibilities, both non-fabricating:

  * ``build_reconciliation_marker`` — the ONE canonical shape a reconciliation
    producer stamps onto its source row's jsonb column at COMPLETION time
    (``<source jsonb col>->'reconciliation_receipt'``). The writer RPC PROVES this
    exact marker before it will mint a receipt, so producer and RPC share one
    contract. Producers merge this dict into their existing jsonb (risk_alerts
    ``metadata`` / paper_orders ``broker_response`` / paper_ledger ``metadata``);
    they do NOT invent a receipt id, kind, or fingerprint the source lacks.

  * ``issue_reconciliation_receipt`` — validates the call STRUCTURE (kind
    allowlist, FULL >= 32 fingerprint, non-blank epoch, exactly one durable
    provenance form, job_runs rejected as user-scopeless) and then makes ONE
    ``supabase.rpc(...)`` call. EXISTENCE + user-scope + completed-state + full-
    fingerprint match are enforced SERVER-SIDE by the RPC (the final authority);
    this wrapper never queries the source, never fabricates a receipt, and — on a
    structural failure — raises before any RPC call (zero writes).

WIRING NOTE (why no live producer is modified here): the three receipt kinds map
to the fleet-prerequisite reconciliations {stale_order, manual_review,
orphan_run}. A read of the codebase (2026-07-20) finds NO standing code producer
that completes these kinds — the four 07-18 reconciliations were operator-run
(SQL) during the weekend activation-blocker sweep, and ``census_fingerprint`` has
zero code writers. So there is no live producer to route through today; this
module IS the canonical path those future producers / operator scripts call, and
wiring it into an unrelated live trading path would fabricate a producer that
does not exist (and risk a behavior change). No receipt is issued by importing or
merging this module — a receipt is minted only when a caller invokes
``issue_reconciliation_receipt`` with a durable, marker-stamped source.

Activation remains FORBIDDEN and operator-only; this module authorizes no flag,
gate, threshold, stop, universe, cadence, or broker action.
"""

import logging
from typing import Any, Dict, Mapping, Optional

# Single source of truth for the kind allowlist + fingerprint floor (shared with
# the activation-side attestation validator; do not re-define divergently).
from packages.quantum.services.shadow_fleet_activation import (
    MIN_CONTENT_FINGERPRINT_LEN,
    RECONCILIATION_RECEIPT_KINDS,
)

logger = logging.getLogger(__name__)

# ── RPC + marker contract (mirrors migration 20260721010000) ─────────────────
RECEIPT_WRITER_RPC = "rpc_issue_fleet_reconciliation_receipt_v1"

# The typed marker key a producer stamps on its source jsonb column, and the
# durable completed-state value the RPC requires.
RECONCILIATION_MARKER_KEY = "reconciliation_receipt"
MARKER_COMPLETED_STATE = "completed"

# Durable domain-table sources that carry BOTH a user_id column AND a jsonb
# column for the marker. job_runs is DELIBERATELY excluded — it has no user_id
# column, so a reconciliation recorded only there is not user-attributable and
# the RPC rejects it (H9: RAISE, never fabricate a user scope). The value is the
# jsonb column the marker lives in for that table.
SOURCE_MARKER_COLUMN: Dict[str, str] = {
    "risk_alerts": "metadata",
    "paper_orders": "broker_response",
    "paper_ledger": "metadata",
}
RECEIPT_SOURCE_TABLES = frozenset(SOURCE_MARKER_COLUMN)


class ReconciliationReceiptError(Exception):
    """Base error for the reconciliation-receipt writer surface."""


class ReceiptStructureInvalid(ReconciliationReceiptError):
    """The call structure is invalid (bad kind / short fingerprint / blank epoch
    / bad provenance form). Raised BEFORE any RPC call — zero writes."""


def build_reconciliation_marker(
    *, receipt_kind: str, content_fingerprint: str, effective_epoch: str,
) -> Dict[str, Any]:
    """Return the canonical marker a producer stamps on its source jsonb column.

    The producer merges the returned ``{"reconciliation_receipt": {...}}`` dict
    into its source row's jsonb column (risk_alerts.metadata /
    paper_orders.broker_response / paper_ledger.metadata) at reconciliation
    COMPLETION. The writer RPC proves this exact object (kind + status
    ``completed`` + FULL content_fingerprint + effective_epoch) before minting a
    receipt. Structure is validated here so a producer cannot stamp a malformed
    marker the RPC would later reject.
    """
    kind = str(receipt_kind or "").strip()
    if kind not in RECONCILIATION_RECEIPT_KINDS:
        raise ReceiptStructureInvalid(f"receipt_kind_invalid:{receipt_kind!r}")
    fingerprint = str(content_fingerprint or "").strip().lower()
    if len(fingerprint) < MIN_CONTENT_FINGERPRINT_LEN:
        raise ReceiptStructureInvalid("content_fingerprint_not_full")
    epoch = str(effective_epoch or "").strip()
    if not epoch:
        raise ReceiptStructureInvalid("effective_epoch_required")
    return {
        RECONCILIATION_MARKER_KEY: {
            "kind": kind,
            "status": MARKER_COMPLETED_STATE,
            "content_fingerprint": fingerprint,
            "effective_epoch": epoch,
        }
    }


def _validate_call(
    *,
    user_id: Any,
    receipt_kind: str,
    effective_epoch: str,
    content_fingerprint: str,
    source_alert_id: Optional[str],
    source_table: Optional[str],
    source_row_id: Optional[str],
    actor_class: str,
) -> Dict[str, Any]:
    """Validate the call STRUCTURE; return the normalized RPC params. Raises
    ReceiptStructureInvalid (before any RPC call) on any structural problem —
    the RPC re-validates and is the final authority."""
    if not user_id or not str(user_id).strip():
        raise ReceiptStructureInvalid("user_id_required")

    kind = str(receipt_kind or "").strip()
    if kind not in RECONCILIATION_RECEIPT_KINDS:
        raise ReceiptStructureInvalid(f"receipt_kind_invalid:{receipt_kind!r}")

    epoch = str(effective_epoch or "").strip()
    if not epoch:
        raise ReceiptStructureInvalid("effective_epoch_required")

    fingerprint = str(content_fingerprint or "").strip().lower()
    if len(fingerprint) < MIN_CONTENT_FINGERPRINT_LEN:
        raise ReceiptStructureInvalid("content_fingerprint_not_full")

    if not str(actor_class or "").strip():
        raise ReceiptStructureInvalid("actor_class_required")

    has_alert = bool(source_alert_id and str(source_alert_id).strip())
    tbl = str(source_table or "").strip()
    row = str(source_row_id or "").strip()
    has_ref = bool(tbl and row)
    if has_alert and (tbl or row):
        raise ReceiptStructureInvalid("provenance_ambiguous")
    if not has_alert and not has_ref:
        raise ReceiptStructureInvalid("provenance_missing")
    if has_ref:
        if tbl == "job_runs":
            # No user_id column on job_runs -> not user-attributable. The RPC
            # rejects this too; fail here first (zero RPC call).
            raise ReceiptStructureInvalid("source_user_scope_unavailable:job_runs")
        if tbl not in RECEIPT_SOURCE_TABLES:
            raise ReceiptStructureInvalid(f"source_table_unsupported:{tbl}")

    return {
        "p_user_id": str(user_id).strip(),
        "p_receipt_kind": kind,
        "p_effective_epoch": epoch,
        "p_content_fingerprint": fingerprint,
        "p_source_alert_id": str(source_alert_id).strip() if has_alert else None,
        "p_source_table": tbl if has_ref else None,
        "p_source_row_id": row if has_ref else None,
        "p_actor_class": str(actor_class).strip(),
    }


def issue_reconciliation_receipt(
    supabase,
    *,
    user_id: str,
    receipt_kind: str,
    effective_epoch: str,
    content_fingerprint: str,
    actor_class: str,
    source_alert_id: Optional[str] = None,
    source_table: Optional[str] = None,
    source_row_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Mint (or idempotently return) a durable reconciliation receipt via the
    atomic writer RPC — the single canonical path.

    Provenance is EXACTLY ONE of:
      * ``source_alert_id`` (a risk_alerts row carrying the typed marker), or
      * ``source_table`` + ``source_row_id`` (risk_alerts / paper_orders /
        paper_ledger; job_runs is rejected — no user scope).

    The source row must belong to ``user_id`` and carry the typed
    ``reconciliation_receipt`` completed-state marker (see
    ``build_reconciliation_marker``) whose kind/epoch/full-fingerprint match —
    all enforced SERVER-SIDE. Returns the RPC's typed receipt dict
    (``receipt_id`` + fields + ``idempotent_replay``). Raises
    ReceiptStructureInvalid on a structural problem (before any RPC call).
    """
    params = _validate_call(
        user_id=user_id,
        receipt_kind=receipt_kind,
        effective_epoch=effective_epoch,
        content_fingerprint=content_fingerprint,
        source_alert_id=source_alert_id,
        source_table=source_table,
        source_row_id=source_row_id,
        actor_class=actor_class,
    )
    res = supabase.rpc(RECEIPT_WRITER_RPC, params).execute()
    logger.info(
        "[RECON_RECEIPT] issue kind=%s epoch=%s -> %s",
        params["p_receipt_kind"], params["p_effective_epoch"],
        (res.data or {}).get("receipt_id") if isinstance(res.data, Mapping) else res.data,
    )
    return res.data
