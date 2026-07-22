"""No-write replay for the single-leg shadow experiment.

This is the mandatory bridge between disabled setup and policy approval. It
loads the exact four seeded policy rows and a complete natural decision tape,
runs only the two experimental policies through the independent selector and EV
adapter, and emits redacted counts/candidates. It never creates a job, calls a
provider, writes evidence, opens a position, or invokes an RPC.

The no-write claim is enforced, not asserted after the fact: the Supabase client
is wrapped in a read-only capability that exposes SELECT builders only and raises
before any insert/update/upsert/delete/RPC attempt can execute.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from packages.quantum.policy_lab.single_leg_experiment_design import (
    EXPERIMENT_EPOCH,
    build_registrations,
)
from packages.quantum.services.replay.replay_truth_layer import ReplayTruthLayer
from packages.quantum.services.single_leg_shadow_scan import (
    StoredDecisionTruthLayer,
    build_underlying_contexts,
)
from packages.quantum.strategies.single_leg_selection import (
    SingleLegSelectionResult,
    select_and_generate_single_leg,
)
from packages.quantum.supabase_env import get_sanitized_supabase_env
from scripts.analytics.single_leg_shadow_runtime import evaluate_request


class ReadOnlyViolation(RuntimeError):
    """Raised before a dry-run database mutation or RPC can execute."""


class _ReadOnlyQuery:
    _MUTATING = frozenset({"insert", "update", "upsert", "delete"})

    def __init__(self, inner: Any, owner: "ReadOnlySupabase") -> None:
        self._inner = inner
        self._owner = owner

    def __getattr__(self, name: str) -> Any:
        if name in self._MUTATING:
            def blocked(*_args: Any, **_kwargs: Any) -> Any:
                self._owner.write_attempts += 1
                raise ReadOnlyViolation(
                    f"single-leg dry-run blocked query mutation: {name}"
                )

            return blocked

        attribute = getattr(self._inner, name)
        if not callable(attribute):
            return attribute

        def delegated(*args: Any, **kwargs: Any) -> Any:
            result = attribute(*args, **kwargs)
            if result is self._inner:
                return self
            if hasattr(result, "execute"):
                return _ReadOnlyQuery(result, self._owner)
            return result

        return delegated


class ReadOnlySupabase:
    """Minimal read-only capability for the mandatory replay.

    Only ``table()`` is exposed. Query-builder mutations and all RPC calls are
    blocked before delegation. Unknown client surfaces fail closed rather than
    exposing a future storage/auth/function path accidentally.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.write_attempts = 0

    def table(self, name: str) -> _ReadOnlyQuery:
        return _ReadOnlyQuery(self._inner.table(name), self)

    def rpc(self, *_args: Any, **_kwargs: Any) -> Any:
        self.write_attempts += 1
        raise ReadOnlyViolation("single-leg dry-run blocked RPC invocation")

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(
            f"single-leg dry-run read-only client does not expose {name!r}"
        )


def _rows(response: Any) -> List[Dict[str, Any]]:
    rows = getattr(response, "data", None)
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def _counter(counter: Counter) -> List[Dict[str, Any]]:
    return [
        {"reason_code": reason, "count": counter[reason]}
        for reason in sorted(counter)
    ]


def _load_exact_experimental_policies(client: Any) -> List[Dict[str, Any]]:
    expected = {
        row["policy_registration_id"]: row for row in build_registrations()
    }
    response = (
        client.table("policy_registrations")
        .select(
            "policy_registration_id,effective_epoch,approval_status,"
            "policy_config,config_hash,schema_version"
        )
        .eq("effective_epoch", EXPERIMENT_EPOCH)
        .execute()
    )
    rows = _rows(response)
    by_id = {
        str(row.get("policy_registration_id")): row
        for row in rows
        if row.get("policy_registration_id")
    }
    if set(by_id) != set(expected):
        raise ValueError(
            "single-leg dry-run requires exactly the four manifest policy rows"
        )

    experimental: List[Dict[str, Any]] = []
    for policy_id in sorted(expected):
        row = by_id[policy_id]
        manifest = expected[policy_id]
        if row.get("config_hash") != manifest["config_hash"]:
            raise ValueError(f"policy hash mismatch: {policy_id}")
        if row.get("schema_version") != manifest["schema_version"]:
            raise ValueError(f"policy schema-version mismatch: {policy_id}")
        if row.get("approval_status") not in ("draft", "approved"):
            raise ValueError(
                f"unsupported policy state {policy_id}: "
                f"{row.get('approval_status')}"
            )
        config = row.get("policy_config")
        if not isinstance(config, Mapping):
            raise ValueError(f"policy config missing: {policy_id}")
        if dict(config) != dict(manifest["policy_config"]):
            raise ValueError(f"policy config mismatch: {policy_id}")
        if manifest["role"] == "experimental":
            if config.get("single_leg_experiment_enabled") is not True:
                raise ValueError(f"experimental opt-in missing: {policy_id}")
            experimental.append(row)
        elif "single_leg_experiment_enabled" in config:
            raise ValueError(f"control carries single-leg opt-in: {policy_id}")
    return experimental


def _validate_candidate(policy_id: str, candidate: Any) -> None:
    violations: List[str] = []
    if getattr(candidate, "contracts", None) != 1:
        violations.append("contracts")
    if getattr(candidate, "routing", None) != "shadow_only":
        violations.append("routing")
    if getattr(candidate, "lifecycle_state", None) != "experimental":
        violations.append("lifecycle_state")
    if getattr(candidate, "strategy_type", None) not in ("long_call", "long_put"):
        violations.append("strategy_type")
    if violations:
        raise ValueError(
            f"candidate invariant violation {policy_id}: {','.join(violations)}"
        )


def run_single_leg_shadow_dry_replay(
    client: Any,
    *,
    user_id: str,
    decision_id: str,
    replay_factory: Callable[..., Optional[ReplayTruthLayer]] = (
        ReplayTruthLayer.from_decision_id
    ),
    context_builder: Callable[..., List[Dict[str, Any]]] = (
        build_underlying_contexts
    ),
    selector: Callable[..., SingleLegSelectionResult] = (
        select_and_generate_single_leg
    ),
    estimator: Callable[..., Any] = evaluate_request,
) -> Dict[str, Any]:
    """Run the experiment against durable source data with enforced zero writes."""

    read_only = ReadOnlySupabase(client)
    policies = _load_exact_experimental_policies(read_only)
    replay = replay_factory(read_only, decision_id)
    if replay is None:
        raise ValueError("source decision not found")
    decision = replay.decision_run or {}
    if decision.get("tape_integrity") != "complete":
        raise ValueError(
            f"source tape is not complete: {decision.get('tape_integrity')}"
        )
    if decision.get("status") != "ok":
        raise ValueError(f"source decision status is not ok: {decision.get('status')}")
    if decision.get("strategy_name") != "suggestions_open":
        raise ValueError(
            "source decision is not a suggestions_open decision: "
            f"{decision.get('strategy_name')}"
        )
    if decision.get("decision_id") and str(decision.get("decision_id")) != str(
        decision_id
    ):
        raise ValueError("source decision identity mismatch")
    if decision.get("user_id") and str(decision.get("user_id")) != str(user_id):
        raise ValueError("source decision belongs to a different user")

    contexts = context_builder(replay)
    if not isinstance(contexts, list):
        raise ValueError("source context builder returned a non-list")
    if not contexts:
        raise ValueError("source decision produced zero replayable contexts")

    truth = StoredDecisionTruthLayer(replay)
    policy_results: List[Dict[str, Any]] = []
    total_candidates = 0
    total_attempts = 0

    for policy in sorted(
        policies, key=lambda row: str(row.get("policy_registration_id"))
    ):
        policy_id = str(policy["policy_registration_id"])
        result = selector(
            contexts,
            policy["policy_config"],
            routing_mode="shadow_only",
            truth_layer=truth,
            ev_estimator=estimator,
        )
        if result.generation.enabled is not True:
            raise ValueError(f"experimental policy unexpectedly disabled: {policy_id}")
        if result.generation.routing_mode != "shadow_only":
            raise ValueError(f"generation routing mismatch: {policy_id}")

        selection_rejections = Counter(
            rejection.reason_code for rejection in result.selection_rejections
        )
        gate_rejections = Counter(
            rejection.reason_code for rejection in result.generation.rejections
        )
        candidate_objects = list(result.generation.candidates)
        for candidate in candidate_objects:
            _validate_candidate(policy_id, candidate)

        outcomes = (
            len(result.selection_rejections)
            + len(result.generation.rejections)
            + len(candidate_objects)
        )
        if outcomes != len(contexts):
            raise ValueError(
                f"outcome coverage mismatch {policy_id}: "
                f"contexts={len(contexts)} outcomes={outcomes}"
            )

        candidates = [
            {
                "symbol": candidate.symbol,
                "strategy_type": candidate.strategy_type,
                "occ_symbol": candidate.occ_symbol,
                "strike": candidate.strike,
                "expiry": candidate.expiry,
                "debit_per_contract": candidate.debit_per_contract,
                "ev_expected_value": candidate.ev_expected_value,
                "ev_pop": candidate.ev_pop,
                "ev_basis": candidate.ev_basis,
                "ev_model": candidate.ev_model,
                "contracts": candidate.contracts,
                "routing": candidate.routing,
                "lifecycle_state": candidate.lifecycle_state,
            }
            for candidate in candidate_objects
        ]
        total_attempts += outcomes
        total_candidates += len(candidates)
        policy_results.append(
            {
                "policy_registration_id": policy_id,
                "approval_status": policy.get("approval_status"),
                "config_hash": policy.get("config_hash"),
                "contexts": len(contexts),
                "attempts": outcomes,
                "selection_rejections": _counter(selection_rejections),
                "gate_rejections": _counter(gate_rejections),
                "candidates": candidates,
            }
        )

    policy_ids = [row["policy_registration_id"] for row in policy_results]
    if policy_ids != ["sl_exp_conviction_v1", "sl_exp_throughput_v1"]:
        raise ValueError(f"unexpected experimental policy set: {policy_ids}")
    if read_only.write_attempts != 0:
        raise ReadOnlyViolation(
            f"single-leg dry-run observed {read_only.write_attempts} write attempt(s)"
        )

    return {
        "status": "HONEST-EMPTY" if total_candidates == 0 else "CANDIDATES_FOUND",
        "write_mode": "NO-WRITE",
        "database_write_attempts": read_only.write_attempts,
        "provider_calls": 0,
        "broker_calls": 0,
        "data_source": "stored_decision_tape",
        "source_decision_id": str(decision_id),
        "source_code_sha": decision.get("git_sha"),
        "tape_integrity": decision.get("tape_integrity"),
        "policy_epoch": EXPERIMENT_EPOCH,
        "policies_evaluated": len(policy_results),
        "contexts": len(contexts),
        "attempts": total_attempts,
        "candidates": total_candidates,
        "policy_results": policy_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--json-out")
    args = parser.parse_args()

    url, key = get_sanitized_supabase_env()
    if not url or not key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required"
        )
    from supabase import create_client

    client = create_client(url, key)
    result = run_single_leg_shadow_dry_replay(
        client,
        user_id=args.user_id,
        decision_id=args.decision_id,
    )
    text = json.dumps(result, sort_keys=True, indent=2, default=str) + "\n"
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
