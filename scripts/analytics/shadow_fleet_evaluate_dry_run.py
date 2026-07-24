"""No-write replay for the recurring independent shadow-fleet evaluator.

The mandatory readiness proof between a merged-but-dark evaluator and any future
fleet activation. It loads the 50 APPROVED small_tier_v1 policies and the shared
candidate universe for one stored decision event, simulates every policy against
that universe with writes disabled, and emits per-policy typed dispositions plus
a distinct-config-hash count. It never creates a job, calls a provider, opens a
position, invokes an RPC, or writes a single row.

The no-write claim is enforced, not asserted after the fact: the Supabase client
is wrapped in a read-only capability that exposes SELECT builders only and raises
before any insert/update/upsert/delete/RPC can execute (mirrors
single_leg_shadow_dry_run.py). Fleet activation state is IRRELEVANT here — the
dry-run proves what the 50 approved policies WOULD decide, independent of whether
any slot is bound/active; it authorizes nothing.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from packages.quantum.policy_lab.shadow_fleet import CAPITAL_PER_ACCOUNT, FLEET_EPOCH
from packages.quantum.services.shadow_fleet_evaluate import (
    UniverseUnavailable,
    build_candidate_universe,
    evaluate_policy,
)
from packages.quantum.supabase_env import get_sanitized_supabase_env


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
                    f"fleet dry-run blocked query mutation: {name}"
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
    blocked before delegation. Unknown client surfaces fail closed.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.write_attempts = 0

    def table(self, name: str) -> _ReadOnlyQuery:
        return _ReadOnlyQuery(self._inner.table(name), self)

    def rpc(self, *_args: Any, **_kwargs: Any) -> Any:
        self.write_attempts += 1
        raise ReadOnlyViolation("fleet dry-run blocked RPC invocation")

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(
            f"fleet dry-run read-only client does not expose {name!r}"
        )


def _rows(response: Any) -> List[Dict[str, Any]]:
    rows = getattr(response, "data", None)
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def _load_approved_policies(client: Any, *, fleet_epoch: str) -> List[Dict[str, Any]]:
    response = (
        client.table("policy_registrations")
        .select(
            "policy_registration_id,effective_epoch,approval_status,"
            "policy_config,config_hash,schema_version"
        )
        .eq("effective_epoch", fleet_epoch)
        .eq("approval_status", "approved")
        .execute()
    )
    rows = _rows(response)
    policies = [
        row
        for row in rows
        if isinstance(row.get("policy_config"), Mapping)
        and str(row.get("policy_registration_id") or "").strip()
    ]
    return sorted(policies, key=lambda row: str(row.get("policy_registration_id")))


def run_fleet_dry_replay(
    client: Any,
    *,
    decision_id: str,
    user_id: str,
    fleet_epoch: str = FLEET_EPOCH,
    deployable_capital: float = CAPITAL_PER_ACCOUNT,
    universe_builder: Callable[..., List[Dict[str, Any]]] = build_candidate_universe,
) -> Dict[str, Any]:
    """Simulate all approved policies against one stored universe, zero writes.

    The universe resolves the champion (get_current_champion) exactly as the live
    evaluator does, so it reflects the fork-tagged emitted set for the event.
    """

    read_only = ReadOnlySupabase(client)
    policies = _load_approved_policies(read_only, fleet_epoch=fleet_epoch)
    if not policies:
        raise ValueError(f"no approved {fleet_epoch} policies to simulate")

    try:
        universe = universe_builder(read_only, decision_id, user_id)
    except UniverseUnavailable as exc:
        raise ValueError(f"universe unavailable for {decision_id}: {exc}") from exc

    policy_results: List[Dict[str, Any]] = []
    disposition_totals: Counter = Counter()
    for policy in policies:
        policy_id = str(policy["policy_registration_id"])
        decisions = evaluate_policy(
            universe,
            policy["policy_config"],
            open_positions=0,
            deployable_capital=deployable_capital,
        )
        per_policy: Counter = Counter(d.disposition for d in decisions)
        disposition_totals.update(per_policy)
        # Invariant: exactly one typed disposition per candidate.
        assert len(decisions) == len(universe), (
            f"disposition coverage mismatch {policy_id}: "
            f"universe={len(universe)} decisions={len(decisions)}"
        )
        for d in decisions:
            assert d.disposition in ("selected", "policy_rejected", "capital_rejected"), (
                f"untyped disposition {d.disposition} for {policy_id}"
            )
        policy_results.append(
            {
                "policy_registration_id": policy_id,
                "config_hash": policy.get("config_hash"),
                "candidates_seen": len(universe),
                "selected": per_policy.get("selected", 0),
                "policy_rejected": per_policy.get("policy_rejected", 0),
                "capital_rejected": per_policy.get("capital_rejected", 0),
            }
        )

    distinct_hashes = len({r["config_hash"] for r in policy_results})
    if read_only.write_attempts != 0:
        raise ReadOnlyViolation(
            f"fleet dry-run observed {read_only.write_attempts} write attempt(s)"
        )

    return {
        "status": "HONEST-EMPTY" if not universe else "EVALUATED",
        "write_mode": "NO-WRITE",
        "database_write_attempts": read_only.write_attempts,
        "provider_calls": 0,
        "broker_calls": 0,
        "data_source": "durable_trade_suggestions_universe",
        "fleet_epoch": fleet_epoch,
        "source_decision_id": str(decision_id),
        "deployable_capital_per_account": deployable_capital,
        "policies_evaluated": len(policy_results),
        "distinct_config_hashes": distinct_hashes,
        "candidates_universe": len(universe),
        "disposition_totals": dict(disposition_totals),
        "policy_results": policy_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--fleet-epoch", default=FLEET_EPOCH)
    parser.add_argument("--json-out")
    args = parser.parse_args()

    url, key = get_sanitized_supabase_env()
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    from supabase import create_client

    client = create_client(url, key)
    result = run_fleet_dry_replay(
        client,
        decision_id=args.decision_id,
        user_id=args.user_id,
        fleet_epoch=args.fleet_epoch,
    )
    text = json.dumps(result, sort_keys=True, indent=2, default=str) + "\n"
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
