"""Append-only evidence writer for the one-contract single-leg shadow experiment.

This module is deliberately isolated from ``trade_suggestions`` and all live routing
surfaces. It records experiment-run, per-symbol attempt, and lifecycle evidence in
three dedicated tables created by
``20260721190000_single_leg_shadow_experiment_foundation.sql``.

The writer is fail-loud but trading-safe: it never calls a broker and it never
mutates champion/default suggestion rows. A missing migration is surfaced through
``table_missing_noops``; other write failures increment ``write_failures`` and are
returned to the owning job so the job can become partial.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

RUNS_TABLE = "single_leg_shadow_runs"
ATTEMPTS_TABLE = "single_leg_shadow_attempts"
EVENTS_TABLE = "single_leg_shadow_lifecycle_events"
EPOCH = "single_leg_experiment_v1"

_TABLE_MISSING_MARKERS = (
    "pgrst205",
    "42p01",
    "could not find the table",
    "schema cache",
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_table_missing_error(exc: BaseException, table: str) -> bool:
    msg = str(exc).lower()
    if any(marker in msg for marker in _TABLE_MISSING_MARKERS):
        return True
    return "does not exist" in msg and table.lower() in msg


def _is_unique_violation(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "23505" in msg or "duplicate key" in msg or "already exists" in msg


def _jsonable(value: Any) -> Any:
    """Return a deterministic JSON-compatible value without fabricating data."""
    try:
        return json.loads(json.dumps(value, default=str, sort_keys=True))
    except Exception:
        return str(value)


def candidate_fingerprint(candidate: Mapping[str, Any]) -> str:
    """Stable identity for one selected contract and its experiment policy.

    Price, EV and timestamps are intentionally excluded so the same exact contract
    under the same policy/source decision is idempotent across retries while its
    changing economics remain in evidence columns.
    """
    payload = {
        "policy_registration_id": candidate.get("policy_registration_id"),
        "symbol": candidate.get("symbol"),
        "strategy_type": candidate.get("strategy_type"),
        "occ_symbol": candidate.get("occ_symbol"),
        "strike": candidate.get("strike"),
        "expiry": candidate.get("expiry"),
        "option_type": candidate.get("option_type"),
        "contracts": candidate.get("contracts", 1),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SingleLegShadowEvidenceWriter:
    """Idempotent writer for a single policy's child experiment run."""

    def __init__(
        self,
        supabase: Any,
        *,
        source_job_run_id: str,
        source_decision_id: str,
        user_id: str,
        policy_registration_id: str,
        portfolio_id: str,
        policy_epoch: str = EPOCH,
        source_code_sha: Optional[str] = None,
        as_of: Optional[str] = None,
    ) -> None:
        self._sb = supabase
        self.source_job_run_id = str(source_job_run_id)
        self.source_decision_id = str(source_decision_id)
        self.user_id = str(user_id)
        self.policy_registration_id = str(policy_registration_id)
        self.portfolio_id = str(portfolio_id)
        self.policy_epoch = str(policy_epoch)
        self.source_code_sha = source_code_sha or "unknown"
        self.as_of = as_of or _utcnow_iso()
        self.run_id: Optional[str] = None
        self._counters = {
            "runs_started": 0,
            "attempts_written": 0,
            "events_written": 0,
            "write_failures": 0,
            "table_missing_noops": 0,
        }

    def _execute(
        self,
        table: str,
        operation,
        *,
        allow_unique: bool = False,
    ) -> Optional[Any]:
        try:
            return operation().execute()
        except Exception as exc:
            if allow_unique and _is_unique_violation(exc):
                return "duplicate"
            if _is_table_missing_error(exc, table):
                self._counters["table_missing_noops"] += 1
                logger.error(
                    "single-leg shadow evidence table missing: %s (migration not applied)",
                    table,
                )
                return None
            self._counters["write_failures"] += 1
            logger.exception("single-leg shadow evidence write failed: table=%s", table)
            return None

    def begin_run(self) -> Optional[str]:
        payload = {
            "source_job_run_id": self.source_job_run_id,
            "source_decision_id": self.source_decision_id,
            "source_code_sha": self.source_code_sha,
            "policy_epoch": self.policy_epoch,
            "policy_registration_id": self.policy_registration_id,
            "portfolio_id": self.portfolio_id,
            "user_id": self.user_id,
            "as_of": self.as_of,
            "status": "running",
            "started_at": _utcnow_iso(),
            "counts": {},
            "error_details": [],
        }
        result = self._execute(
            RUNS_TABLE,
            lambda: self._sb.table(RUNS_TABLE).insert(payload),
            allow_unique=True,
        )
        rows = getattr(result, "data", None) if result not in (None, "duplicate") else None
        if rows:
            self.run_id = str(rows[0]["run_id"])
        else:
            fetched = self._execute(
                RUNS_TABLE,
                lambda: self._sb.table(RUNS_TABLE)
                .select("run_id")
                .eq("source_decision_id", self.source_decision_id)
                .eq("policy_registration_id", self.policy_registration_id)
                .limit(1),
            )
            fetched_rows = getattr(fetched, "data", None) if fetched is not None else None
            if fetched_rows:
                self.run_id = str(fetched_rows[0]["run_id"])
        if self.run_id:
            self._counters["runs_started"] += 1
        return self.run_id

    def record_attempt(
        self,
        *,
        symbol: str,
        stage: str,
        reason_code: Optional[str] = None,
        detail: Optional[str] = None,
        direction: Optional[str] = None,
        strategy_type: Optional[str] = None,
        candidate: Optional[Mapping[str, Any]] = None,
        evidence: Optional[Mapping[str, Any]] = None,
        considered_contracts: Optional[int] = None,
        viable_contracts: Optional[int] = None,
        provider: Optional[str] = None,
        known_at: Optional[str] = None,
    ) -> bool:
        if not self.run_id:
            return False
        candidate_dict: Dict[str, Any] = dict(candidate or {})
        candidate_dict.setdefault("policy_registration_id", self.policy_registration_id)
        fp = candidate_fingerprint(candidate_dict) if candidate_dict else ""
        payload = {
            "run_id": self.run_id,
            "policy_registration_id": self.policy_registration_id,
            "user_id": self.user_id,
            "symbol": str(symbol),
            "direction": direction,
            "strategy_type": strategy_type,
            "stage": str(stage),
            "reason_code": reason_code,
            "detail": detail,
            "candidate_fingerprint": fp,
            "occ_symbol": candidate_dict.get("occ_symbol"),
            "strike": candidate_dict.get("strike"),
            "expiry": candidate_dict.get("expiry"),
            "debit_per_contract": candidate_dict.get("debit_per_contract"),
            "ev_expected_value": candidate_dict.get("ev_expected_value"),
            "ev_pop": candidate_dict.get("ev_pop"),
            "ev_basis": candidate_dict.get("ev_basis"),
            "ev_model": candidate_dict.get("ev_model"),
            "considered_contracts": considered_contracts,
            "viable_contracts": viable_contracts,
            "provider": provider,
            "known_at": known_at or candidate_dict.get("known_at") or self.as_of,
            "evidence": _jsonable(dict(evidence or {})),
        }
        result = self._execute(
            ATTEMPTS_TABLE,
            lambda: self._sb.table(ATTEMPTS_TABLE).insert(payload),
            allow_unique=True,
        )
        if result is None:
            return False
        if result != "duplicate":
            self._counters["attempts_written"] += 1
        return True

    def record_event(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        candidate_fingerprint_value: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
        occurred_at: Optional[str] = None,
    ) -> bool:
        if not self.run_id:
            return False
        row = {
            "run_id": self.run_id,
            "policy_registration_id": self.policy_registration_id,
            "user_id": self.user_id,
            "event_type": str(event_type),
            "entity_type": str(entity_type),
            "entity_id": str(entity_id),
            "candidate_fingerprint": candidate_fingerprint_value,
            "payload": _jsonable(dict(payload or {})),
            "occurred_at": occurred_at or _utcnow_iso(),
        }
        result = self._execute(
            EVENTS_TABLE,
            lambda: self._sb.table(EVENTS_TABLE).insert(row),
            allow_unique=True,
        )
        if result is None:
            return False
        if result != "duplicate":
            self._counters["events_written"] += 1
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
            "counts": _jsonable(dict(counts or {})),
            "error_details": _jsonable(list(error_details or [])),
            "finished_at": _utcnow_iso(),
        }
        result = self._execute(
            RUNS_TABLE,
            lambda: self._sb.table(RUNS_TABLE).update(row).eq("run_id", self.run_id),
        )
        return result is not None

    def counters_dict(self) -> Dict[str, int]:
        return dict(self._counters)
