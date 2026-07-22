"""Independent one-contract single-leg shadow scan child job.

This module wires the already-existing dark selector/generator to the append-only
experiment evidence foundation.  It is deliberately isolated from
``trade_suggestions``, broker routing, fleet activation, and champion risk
budgets.

Natural flow::

    suggestions_open commits a complete decision tape
    -> maybe_enqueue_single_leg_shadow_scan()
    -> single_leg_shadow_scan job
    -> approved opt-in policies bound to enabled shadow-only portfolios
    -> replay the source decision's durable market data
    -> persist typed attempts / generated-candidate lifecycle evidence

The child uses the source decision tape only.  It performs no live provider
fetches, and a missing chain or feature is a typed rejection rather than an
invented value.  Disabled epochs, non-scheduler parents, and zero approved
opt-ins are true no-ops: zero child job, zero provider calls, zero evidence
writes.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import date
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from packages.quantum.brokers.execution_router import SHADOW_ONLY_ROUTING
from packages.quantum.services.replay.replay_truth_layer import ReplayTruthLayer
from packages.quantum.services.single_leg_shadow_evidence import (
    EPOCH,
    SingleLegShadowEvidenceWriter,
    candidate_fingerprint,
)
from packages.quantum.strategies.single_leg_experiment import experiment_enabled
from packages.quantum.strategies.single_leg_selection import (
    SelectedContract,
    SingleLegSelectionResult,
    select_and_generate_single_leg,
)

logger = logging.getLogger(__name__)

JOB_NAME = "single_leg_shadow_scan"
EXECUTION_MODE = "internal_paper"
EXPERIMENTAL_ROLE = "experimental"
NATURAL_PARENT_ORIGIN = "scheduler"
DEFAULT_MAX_SYMBOLS = 100


def _safe_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else default


def _max_symbols() -> int:
    return _safe_int(os.getenv("SINGLE_LEG_SHADOW_MAX_SYMBOLS"), DEFAULT_MAX_SYMBOLS)


def _rows(result: Any) -> List[Dict[str, Any]]:
    rows = getattr(result, "data", None)
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def _load_epoch(client: Any, epoch: str = EPOCH) -> Optional[Dict[str, Any]]:
    result = (
        client.table("single_leg_experiment_epochs")
        .select(
            "epoch_name,state,routing_mode,max_contracts,"
            "live_submit_allowed,config_hash,version"
        )
        .eq("epoch_name", epoch)
        .limit(1)
        .execute()
    )
    rows = _rows(result)
    return rows[0] if rows else None


def _load_enabled_experimental_bindings(
    client: Any,
    user_id: str,
    *,
    epoch: str = EPOCH,
) -> Dict[str, Any]:
    """Return current, DB-authoritative experiment readiness.

    This is intentionally queried both at the parent enqueue seam and inside the
    child handler.  The second read closes a race where an operator pauses the
    epoch after enqueue but before the worker claims the job.
    """

    try:
        epoch_row = _load_epoch(client, epoch)
    except Exception as exc:
        return {
            "status": "epoch_read_failed",
            "ready": False,
            "errors": 1,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "bindings": [],
        }

    if not epoch_row:
        return {
            "status": "epoch_absent",
            "ready": False,
            "errors": 0,
            "bindings": [],
        }

    invariant_ok = (
        epoch_row.get("state") == "enabled"
        and epoch_row.get("routing_mode") == SHADOW_ONLY_ROUTING
        and epoch_row.get("max_contracts") == 1
        and epoch_row.get("live_submit_allowed") is False
    )
    if not invariant_ok:
        return {
            "status": "epoch_not_enabled",
            "ready": False,
            "errors": 0,
            "epoch_state": epoch_row.get("state"),
            "bindings": [],
        }

    try:
        binding_result = (
            client.table("single_leg_experiment_bindings")
            .select(
                "policy_registration_id,epoch_name,portfolio_id,user_id,role,"
                "routing_mode,execution_mode,enabled"
            )
            .eq("epoch_name", epoch)
            .eq("user_id", user_id)
            .eq("role", EXPERIMENTAL_ROLE)
            .eq("routing_mode", SHADOW_ONLY_ROUTING)
            .eq("execution_mode", EXECUTION_MODE)
            .eq("enabled", True)
            .execute()
        )
        bindings = _rows(binding_result)
    except Exception as exc:
        return {
            "status": "binding_read_failed",
            "ready": False,
            "errors": 1,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "bindings": [],
        }

    if not bindings:
        return {
            "status": "no_enabled_experimental_bindings",
            "ready": False,
            "errors": 0,
            "bindings": [],
        }

    policy_ids = sorted(
        {
            str(row.get("policy_registration_id") or "").strip()
            for row in bindings
            if str(row.get("policy_registration_id") or "").strip()
        }
    )
    if not policy_ids:
        return {
            "status": "binding_identity_missing",
            "ready": False,
            "errors": 1,
            "bindings": [],
        }

    try:
        policy_result = (
            client.table("policy_registrations")
            .select(
                "policy_registration_id,effective_epoch,approval_status,"
                "policy_config,config_hash,schema_version"
            )
            .in_("policy_registration_id", policy_ids)
            .eq("effective_epoch", epoch)
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
            "bindings": [],
        }

    qualified: List[Dict[str, Any]] = []
    for binding in bindings:
        policy_id = str(binding.get("policy_registration_id") or "")
        policy = policies.get(policy_id)
        config = policy.get("policy_config") if policy else None
        if not policy or not isinstance(config, Mapping):
            continue
        if not experiment_enabled(config):
            # Controls and un-opted policies never generate single-leg attempts.
            continue
        qualified.append(
            {
                **binding,
                "policy_config": dict(config),
                "config_hash": policy.get("config_hash"),
                "schema_version": policy.get("schema_version"),
            }
        )

    if not qualified:
        return {
            "status": "no_approved_opt_in_policies",
            "ready": False,
            "errors": 0,
            "bindings": [],
        }

    return {
        "status": "ready",
        "ready": True,
        "errors": 0,
        "epoch": epoch_row,
        "bindings": sorted(
            qualified, key=lambda row: str(row.get("policy_registration_id"))
        ),
    }


def maybe_enqueue_single_leg_shadow_scan(
    client: Any,
    *,
    user_id: str,
    source_job_run_id: Optional[str],
    source_decision_id: Optional[str],
    source_code_sha: Optional[str],
    as_of: Optional[str],
    parent_origin: Optional[str],
    epoch: str = EPOCH,
    readiness_loader: Callable[..., Dict[str, Any]] = _load_enabled_experimental_bindings,
    enqueue_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    origin_builder: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Enqueue one child job for a complete natural parent decision.

    The readiness read happens before validating source ids so a dark deployment
    remains a true no-op even when replay is disabled.  Only the scheduler origin
    is admitted; operator-forced scans cannot manufacture experiment evidence.
    """

    readiness = readiness_loader(client, user_id, epoch=epoch)
    if not readiness.get("ready"):
        return {
            "status": readiness.get("status", "not_ready"),
            "enqueued": False,
            "errors": int(readiness.get("errors") or 0),
        }

    if str(parent_origin or "") != NATURAL_PARENT_ORIGIN:
        return {
            "status": "non_natural_parent",
            "enqueued": False,
            "errors": 0,
        }

    required = {
        "source_job_run_id": source_job_run_id,
        "source_decision_id": source_decision_id,
        "user_id": user_id,
        "as_of": as_of,
    }
    missing = sorted(key for key, value in required.items() if not str(value or "").strip())
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
        "policy_epoch": epoch,
    }
    try:
        from packages.quantum.jobs.rq_enqueue import BACKGROUND_QUEUE

        enqueued = enqueue_fn(
            job_name=JOB_NAME,
            idempotency_key=f"{JOB_NAME}:{source_decision_id}:{epoch}",
            payload=payload,
            queue_name=BACKGROUND_QUEUE,
            origin=origin_builder(
                "single_leg_shadow_after_decision",
                parent_job_run_id=str(source_job_run_id),
            ),
        )
    except Exception as exc:
        logger.exception("single-leg shadow child enqueue failed")
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


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _extract_closes(payload: Any) -> List[float]:
    if not isinstance(payload, list):
        return []
    closes: List[float] = []
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        value = row.get("close")
        if value is None:
            value = row.get("c")
        parsed = _finite(value)
        if parsed is not None and parsed > 0:
            closes.append(parsed)
    return closes


def _quote_spot(payload: Any) -> Optional[float]:
    if not isinstance(payload, Mapping):
        return None
    candidates: List[Any] = []
    quote = payload.get("quote")
    if isinstance(quote, Mapping):
        candidates.extend([quote.get("last"), quote.get("mid")])
    for key in ("latestTrade", "dailyBar", "prevDailyBar", "day"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            candidates.extend(
                [
                    nested.get("p"),
                    nested.get("c"),
                    nested.get("close"),
                    nested.get("last"),
                ]
            )
    candidates.extend([payload.get("last"), payload.get("price"), payload.get("close")])
    for value in candidates:
        parsed = _finite(value)
        if parsed is not None and parsed > 0:
            return parsed
    return None


def _expiry_of(contract: Mapping[str, Any]) -> Optional[str]:
    raw = contract.get("expiry") or contract.get("expiration")
    if not raw:
        return None
    return str(raw)[:10]


def _contract_identity(contract: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        contract.get("contract") or contract.get("occ_symbol") or contract.get("ticker"),
        _expiry_of(contract),
        contract.get("strike"),
        contract.get("right") or contract.get("type") or contract.get("option_type"),
    )


class StoredDecisionTruthLayer:
    """Selector-compatible view over option chains captured in a decision tape."""

    def __init__(self, replay: ReplayTruthLayer):
        self.replay = replay

    def option_chain(
        self,
        underlying: str,
        *,
        min_expiry: Optional[str] = None,
        max_expiry: Optional[str] = None,
        spot: Optional[float] = None,
        **_: Any,
    ) -> List[Dict[str, Any]]:
        del spot  # selection receives spot separately; no live fetch is allowed.
        prefix = f"{underlying}:chain"
        contracts: List[Dict[str, Any]] = []
        seen: set = set()
        for (key, snapshot_type) in sorted(self.replay.inputs_map):
            if snapshot_type != "chain" or not str(key).startswith(prefix):
                continue
            stored = self.replay.get_stored_input(key, snapshot_type)
            payload = stored.get("payload") if isinstance(stored, Mapping) else None
            if not isinstance(payload, list):
                continue
            for raw in payload:
                if not isinstance(raw, Mapping):
                    continue
                expiry = _expiry_of(raw)
                if min_expiry and (not expiry or expiry < str(min_expiry)[:10]):
                    continue
                if max_expiry and (not expiry or expiry > str(max_expiry)[:10]):
                    continue
                identity = _contract_identity(raw)
                if identity in seen:
                    continue
                seen.add(identity)
                contracts.append(dict(raw))
        return contracts


def _input_payloads(
    replay: ReplayTruthLayer,
    *,
    snapshot_type: str,
) -> Iterable[Tuple[str, Any, Mapping[str, Any]]]:
    for (key, kind) in sorted(replay.inputs_map):
        if kind != snapshot_type:
            continue
        stored = replay.get_stored_input(key, kind)
        if not isinstance(stored, Mapping):
            continue
        yield str(key), stored.get("payload"), stored.get("metadata") or {}


def build_underlying_contexts(
    replay: ReplayTruthLayer,
    *,
    max_symbols: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Build generator contexts only from the committed source tape."""

    max_symbols = max_symbols or _max_symbols()
    decision = replay.decision_run or {}
    known_at = str(decision.get("as_of_ts") or "")

    symbol_features: Dict[str, Dict[str, Any]] = {}
    for (symbol, namespace), record in replay.features_map.items():
        if namespace != "symbol_features" or str(symbol).startswith("__"):
            continue
        features = record.get("features") if isinstance(record, Mapping) else None
        if isinstance(features, Mapping):
            symbol_features[str(symbol)] = dict(features)

    surfaces: Dict[str, Dict[str, Any]] = {}
    for key, payload, _metadata in _input_payloads(replay, snapshot_type="surface"):
        if not isinstance(payload, Mapping):
            continue
        symbol = str(payload.get("symbol") or key.split(":", 1)[0])
        surfaces[symbol] = dict(payload)

    closes_by_symbol: Dict[str, List[float]] = {}
    for key, payload, metadata in _input_payloads(replay, snapshot_type="bars"):
        symbol = str((metadata or {}).get("symbol") or key.split(":", 1)[0])
        closes = _extract_closes(payload)
        if len(closes) > len(closes_by_symbol.get(symbol, [])):
            closes_by_symbol[symbol] = closes

    spot_by_symbol: Dict[str, float] = {}
    for key, payload, metadata in _input_payloads(replay, snapshot_type="quote"):
        symbol = str(
            (metadata or {}).get("canon_symbol")
            or key.split(":", 1)[0]
        )
        spot = _quote_spot(payload)
        if spot is not None:
            spot_by_symbol[symbol] = spot

    chain_symbols = {
        str(key).split(":", 1)[0]
        for (key, kind) in replay.inputs_map
        if kind == "chain" and ":chain" in str(key)
    }
    observed_symbols = (
        chain_symbols
        | set(symbol_features)
        | set(surfaces)
        | set(closes_by_symbol)
        | set(spot_by_symbol)
    )
    # Option-leg quote inputs also live in the parent tape. When at least one
    # underlying chain was captured, restrict the experiment universe to those
    # underlyings so an OCC quote cannot masquerade as a new underlying.
    symbols = sorted(chain_symbols or observed_symbols)[:max_symbols]

    contexts: List[Dict[str, Any]] = []
    for symbol in symbols:
        feature = symbol_features.get(symbol, {})
        surface = surfaces.get(symbol, {})
        raw_features = (
            feature.get("raw_features")
            if isinstance(feature.get("raw_features"), Mapping)
            else {}
        )
        closes = closes_by_symbol.get(symbol, [])
        spot = (
            _finite(feature.get("spot"))
            or _finite(surface.get("spot"))
            or spot_by_symbol.get(symbol)
            or (closes[-1] if closes else None)
        )
        iv_rank = feature.get("iv_rank")
        if iv_rank is None:
            iv_rank = surface.get("iv_rank")
        iv_rv_spread = feature.get("iv_rv_spread")
        if iv_rv_spread is None:
            iv_rv_spread = surface.get("iv_rv_spread")

        market_data: Dict[str, Any] = {}
        for source in (raw_features, feature, surface):
            if isinstance(source, Mapping) and source.get("earnings_date"):
                market_data["earnings_date"] = source.get("earnings_date")
                break

        momentum = raw_features.get("momentum")
        if not isinstance(momentum, Mapping):
            momentum = None

        contexts.append(
            {
                "symbol": symbol,
                "iv_rank": iv_rank,
                "iv_rv_spread": iv_rv_spread,
                "closes": closes,
                "momentum": momentum,
                "spot": spot,
                "known_at": known_at,
                "market_data": market_data,
            }
        )
    return contexts


def _selection_evidence(
    selection: Optional[SelectedContract],
    candidate: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if selection is not None:
        out.update(
            {
                "selection_dte_days": selection.dte_days,
                "selection_delta": selection.delta,
                "selection_ev_source": selection.ev_source,
                "selection_ev_version": selection.ev_version,
                "selection_tie_breaker": selection.tie_breaker,
                "selection_chain_source": selection.chain_source,
            }
        )
    if candidate:
        out.update(
            {
                "vrp_iv_rv_spread": candidate.get("vrp_iv_rv_spread"),
                "vrp_multiplier": candidate.get("vrp_multiplier"),
                "vrp_source": candidate.get("vrp_source"),
                "iv": candidate.get("iv"),
                "spot": candidate.get("spot"),
                "dte_days": candidate.get("dte_days"),
            }
        )
    return out


def run_single_leg_shadow_scan(
    payload: Mapping[str, Any],
    *,
    client: Any,
    readiness_loader: Callable[..., Dict[str, Any]] = _load_enabled_experimental_bindings,
    replay_factory: Callable[..., Optional[ReplayTruthLayer]] = ReplayTruthLayer.from_decision_id,
    context_builder: Callable[..., List[Dict[str, Any]]] = build_underlying_contexts,
    selector: Callable[..., SingleLegSelectionResult] = select_and_generate_single_leg,
    writer_factory: Callable[..., SingleLegShadowEvidenceWriter] = SingleLegShadowEvidenceWriter,
    estimator: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Execute the child job against one complete source decision tape."""

    counts = {
        "policies": 0,
        "symbols": 0,
        "selection_rejected": 0,
        "gate_rejected": 0,
        "candidates_generated": 0,
        "runs_started": 0,
        "attempts_written": 0,
        "events_written": 0,
        "table_missing_noops": 0,
        "errors": 0,
    }
    errors: List[Dict[str, Any]] = []

    user_id = str(payload.get("user_id") or "").strip()
    source_job_run_id = str(payload.get("source_job_run_id") or "").strip()
    source_decision_id = str(payload.get("source_decision_id") or "").strip()
    epoch = str(payload.get("policy_epoch") or EPOCH).strip()
    if not user_id or not source_job_run_id or not source_decision_id:
        counts["errors"] = 1
        return {
            "ok": False,
            "status": "source_identity_missing",
            "counts": counts,
            "error_details": [
                {
                    "stage": "validate_payload",
                    "error": "user_id/source_job_run_id/source_decision_id required",
                }
            ],
        }

    readiness = readiness_loader(client, user_id, epoch=epoch)
    if not readiness.get("ready"):
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

    replay = replay_factory(client, source_decision_id)
    if replay is None:
        counts["errors"] = 1
        return {
            "ok": False,
            "status": "source_decision_unavailable",
            "counts": counts,
            "error_details": [
                {"stage": "load_source_decision", "source_decision_id": source_decision_id}
            ],
        }

    decision = replay.decision_run or {}
    tape_integrity = decision.get("tape_integrity")
    if tape_integrity not in (None, "complete"):
        counts["errors"] = 1
        return {
            "ok": False,
            "status": "source_tape_incomplete",
            "counts": counts,
            "error_details": [
                {
                    "stage": "validate_source_tape",
                    "tape_integrity": tape_integrity,
                }
            ],
        }
    if decision.get("user_id") and str(decision.get("user_id")) != user_id:
        counts["errors"] = 1
        return {
            "ok": False,
            "status": "source_user_mismatch",
            "counts": counts,
            "error_details": [{"stage": "validate_source_user"}],
        }

    contexts = context_builder(replay, max_symbols=_max_symbols())
    counts["symbols"] = len(contexts)
    if estimator is None:
        # Kept outside packages/quantum so the observe-only import lock remains
        # one-way while the approved experiment consumes the adapter via DI.
        from scripts.analytics.single_leg_shadow_runtime import (
            evaluate_request as estimator,
        )

    truth_layer = StoredDecisionTruthLayer(replay)
    policy_results: List[Dict[str, Any]] = []

    for binding in readiness.get("bindings") or []:
        policy_id = str(binding.get("policy_registration_id") or "")
        portfolio_id = str(binding.get("portfolio_id") or "")
        policy_config = binding.get("policy_config")
        if not policy_id or not portfolio_id or not isinstance(policy_config, Mapping):
            counts["errors"] += 1
            errors.append(
                {
                    "stage": "binding_invalid",
                    "policy_registration_id": policy_id or None,
                }
            )
            continue

        writer = writer_factory(
            client,
            source_job_run_id=source_job_run_id,
            source_decision_id=source_decision_id,
            user_id=user_id,
            policy_registration_id=policy_id,
            portfolio_id=portfolio_id,
            policy_epoch=epoch,
            source_code_sha=(
                payload.get("source_code_sha")
                or decision.get("git_sha")
                or "unknown"
            ),
            as_of=payload.get("source_as_of") or decision.get("as_of_ts"),
        )
        run_id = writer.begin_run()
        if not run_id:
            counters = writer.counters_dict()
            counts["errors"] += max(
                1,
                int(counters.get("write_failures") or 0)
                + int(counters.get("table_missing_noops") or 0),
            )
            errors.append(
                {
                    "stage": "begin_run",
                    "policy_registration_id": policy_id,
                }
            )
            continue

        counts["policies"] += 1
        try:
            result = selector(
                contexts,
                policy_config,
                routing_mode=SHADOW_ONLY_ROUTING,
                truth_layer=truth_layer,
                ev_estimator=estimator,
            )
        except Exception as exc:
            logger.exception("single-leg shadow policy scan failed: %s", policy_id)
            errors.append(
                {
                    "stage": "policy_scan",
                    "policy_registration_id": policy_id,
                    "error_class": type(exc).__name__,
                    "error": str(exc)[:200],
                }
            )
            writer.finish_run(status="failed", counts={}, error_details=errors[-1:])
            counters = writer.counters_dict()
            counts["errors"] += 1 + int(counters.get("write_failures") or 0)
            for key in (
                "runs_started",
                "attempts_written",
                "events_written",
                "table_missing_noops",
            ):
                counts[key] += int(counters.get(key) or 0)
            continue

        selections = {selection.symbol: selection for selection in result.selections}
        policy_counts = {
            "symbols": len(contexts),
            "selection_rejected": 0,
            "gate_rejected": 0,
            "candidates_generated": 0,
        }

        for rejection in result.selection_rejections:
            ok = writer.record_attempt(
                symbol=rejection.symbol,
                stage="selection_rejected",
                reason_code=rejection.reason_code,
                detail=rejection.detail,
                known_at=payload.get("source_as_of") or decision.get("as_of_ts"),
            )
            policy_counts["selection_rejected"] += 1
            if not ok:
                errors.append(
                    {
                        "stage": "write_selection_rejection",
                        "policy_registration_id": policy_id,
                        "symbol": rejection.symbol,
                    }
                )

        for rejection in result.generation.rejections:
            selection = selections.get(rejection.symbol)
            direction = None
            strategy_type = None
            if selection is not None:
                direction = "bullish" if selection.option_type == "call" else "bearish"
                strategy_type = (
                    "long_call" if selection.option_type == "call" else "long_put"
                )
            ok = writer.record_attempt(
                symbol=rejection.symbol,
                stage="gate_rejected",
                reason_code=rejection.reason_code,
                detail=rejection.detail,
                direction=direction,
                strategy_type=strategy_type,
                considered_contracts=(selection.considered if selection else None),
                viable_contracts=(selection.viable if selection else None),
                provider=(selection.chain_source if selection else None),
                known_at=payload.get("source_as_of") or decision.get("as_of_ts"),
                evidence=_selection_evidence(selection),
            )
            policy_counts["gate_rejected"] += 1
            if not ok:
                errors.append(
                    {
                        "stage": "write_gate_rejection",
                        "policy_registration_id": policy_id,
                        "symbol": rejection.symbol,
                    }
                )

        for candidate_obj in result.generation.candidates:
            candidate = candidate_obj.as_dict()
            candidate["policy_registration_id"] = policy_id
            selection = selections.get(candidate_obj.symbol)
            fp = candidate_fingerprint(candidate)
            attempt_ok = writer.record_attempt(
                symbol=candidate_obj.symbol,
                stage="candidate_generated",
                direction=(
                    "bullish" if candidate_obj.option_type == "call" else "bearish"
                ),
                strategy_type=candidate_obj.strategy_type,
                candidate=candidate,
                considered_contracts=(selection.considered if selection else None),
                viable_contracts=(selection.viable if selection else None),
                provider=(selection.chain_source if selection else None),
                known_at=candidate_obj.known_at,
                evidence=_selection_evidence(selection, candidate),
            )
            event_ok = writer.record_event(
                event_type="candidate_generated",
                entity_type="candidate",
                entity_id=fp,
                candidate_fingerprint_value=fp,
                payload={
                    "symbol": candidate_obj.symbol,
                    "strategy_type": candidate_obj.strategy_type,
                    "occ_symbol": candidate_obj.occ_symbol,
                    "contracts": candidate_obj.contracts,
                    "routing": candidate_obj.routing,
                    "lifecycle_state": candidate_obj.lifecycle_state,
                    "experiment": candidate_obj.experiment,
                },
                occurred_at=candidate_obj.known_at,
            )
            policy_counts["candidates_generated"] += 1
            if not attempt_ok or not event_ok:
                errors.append(
                    {
                        "stage": "write_candidate",
                        "policy_registration_id": policy_id,
                        "symbol": candidate_obj.symbol,
                    }
                )

        counters = writer.counters_dict()
        writer_errors = int(counters.get("write_failures") or 0)
        table_missing = int(counters.get("table_missing_noops") or 0)
        status = "partial" if writer_errors or table_missing else "succeeded"
        writer.finish_run(
            status=status,
            counts={**policy_counts, **counters},
            error_details=[
                item for item in errors
                if item.get("policy_registration_id") == policy_id
            ][:10],
        )

        for key in (
            "selection_rejected",
            "gate_rejected",
            "candidates_generated",
        ):
            counts[key] += policy_counts[key]
        for key in (
            "runs_started",
            "attempts_written",
            "events_written",
            "table_missing_noops",
        ):
            counts[key] += int(counters.get(key) or 0)
        counts["errors"] += writer_errors + table_missing

        policy_results.append(
            {
                "policy_registration_id": policy_id,
                "run_id": run_id,
                "status": status,
                "counts": policy_counts,
            }
        )

    status = "partial" if counts["errors"] else "succeeded"
    return {
        "ok": counts["errors"] == 0,
        "status": status,
        "source_decision_id": source_decision_id,
        "policy_epoch": epoch,
        "counts": counts,
        "policy_results": policy_results,
        "error_details": errors[:20],
    }
