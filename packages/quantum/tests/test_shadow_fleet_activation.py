"""F-SHADOW-CAPITAL-PARITY (Lane 3A) — provisioning/activation transaction.

Drives the SERVICE entrypoints (`evaluate_readiness`, `plan_*`,
`execute_*`) — the exact seam the /tasks/shadow-fleet/activation route
calls — against a behavioral fake supabase that actually filters rows, so
the allowlist semantics are exercised, not restated. Failures are injected
at their ORIGIN (the DB rows / the failing read / the raising RPC) and the
truth asserted at the TOP (typed outcome, zero writes, RPC payload shape).

The drift-lock class pins the service's expectations against the MIGRATION
FILE TEXT (20260716060000 schema + 20260717090000 RPCs) — not the live DB —
so a contract change in either place breaks the build, not the fleet.
"""

import re
from pathlib import Path

import pytest

from packages.quantum.services import shadow_fleet_activation as sfa

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_MIGRATION = (
    REPO_ROOT / "supabase" / "migrations"
    / "20260716060000_small_tier_shadow_fleet.sql"
)
RPC_MIGRATION = (
    REPO_ROOT / "supabase" / "migrations"
    / "20260717090000_shadow_fleet_activation_rpc.sql"
)

USER = "user-1"
FLEET_ID = "fleet-1"


# ── Behavioral fake supabase (repo _FakeClient convention) ──────────────────

class _Result:
    def __init__(self, data):
        self.data = data


class _NotProxy:
    def __init__(self, query):
        self._query = query

    def in_(self, col, vals):
        self._query._filters.append(("not_in", col, list(vals)))
        return self._query


class _FakeQuery:
    def __init__(self, fake, table):
        self._fake = fake
        self._table = table
        self._filters = []
        self._limit = None

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals)))
        return self

    @property
    def not_(self):
        return _NotProxy(self)

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, payload):
        self._fake.writes.append(
            {"table": self._table, "op": "insert", "payload": payload})
        return self

    def update(self, payload):
        self._fake.writes.append(
            {"table": self._table, "op": "update", "payload": payload})
        return self

    def delete(self):
        self._fake.writes.append({"table": self._table, "op": "delete"})
        return self

    def execute(self):
        if self._table in self._fake.fail_tables:
            raise RuntimeError(f"read failed: {self._table}")
        rows = list(self._fake.tables.get(self._table, []))
        for kind, col, val in self._filters:
            if kind == "eq":
                rows = [r for r in rows if r.get(col) == val]
            elif kind == "in":
                rows = [r for r in rows if r.get(col) in val]
            elif kind == "not_in":
                rows = [r for r in rows if r.get(col) not in val]
        if self._limit is not None:
            rows = rows[: self._limit]
        return _Result(rows)


class _FakeRpc:
    def __init__(self, fake, fn, params):
        self._fake = fake
        self._fn = fn
        self._params = params

    def execute(self):
        self._fake.rpc_calls.append({"fn": self._fn, "params": self._params})
        if self._fake.rpc_handler is not None:
            return _Result(self._fake.rpc_handler(self._fn, self._params))
        return _Result({"status": "rpc_ok"})


class FakeSupabase:
    def __init__(self, fleets=None, micro_accounts=None, orders=None,
                 positions=None, registrations=None, receipts=None,
                 fail_tables=(), rpc_handler=None):
        self.tables = {
            "shadow_fleets": list(fleets or []),
            "shadow_micro_accounts": list(micro_accounts or []),
            "paper_orders": list(orders or []),
            "paper_positions": list(positions or []),
            "policy_registrations": list(registrations or []),
            "fleet_reconciliation_receipts": list(receipts or []),
        }
        self.fail_tables = set(fail_tables)
        self.rpc_handler = rpc_handler
        self.writes = []
        self.rpc_calls = []

    def table(self, name):
        return _FakeQuery(self, name)

    def rpc(self, fn, params):
        return _FakeRpc(self, fn, params)


# ── Row builders ────────────────────────────────────────────────────────────

def _fleet_row(status="pending_legacy_terminal", **overrides):
    row = {
        "id": FLEET_ID,
        "user_id": USER,
        "epoch_name": "small_tier_v1",
        "micro_account_count": 50,
        "capital_per_account": 2000,
        "shared_capital_enabled": False,
        "status": status,
        "legacy_terminal_verified_at": None,
        "effective_at": None,
    }
    row.update(overrides)
    return row


def _micro_rows(n=50, **overrides):
    rows = []
    for slot in range(1, n + 1):
        row = {
            "id": f"sma-{slot}",
            "fleet_id": FLEET_ID,
            "slot_number": slot,
            "portfolio_id": f"pf-{slot}",
            "policy_registration_id": None,
            "state": "inactive",
            "initial_net_liq": 2000,
            "initial_cash": 2000,
        }
        row.update(overrides)
        rows.append(row)
    return rows


def _stale_submitted_orders(n=6):
    """The six stale 2026-04-09 'submitted' rows (live-DB confirmed)."""
    return [
        {"id": f"stale-{i}", "status": "submitted",
         "portfolio_id": "legacy-pf", "created_at": "2026-04-09T13:00:11+00:00"}
        for i in range(1, n + 1)
    ]


def _terminal_orders():
    return [
        {"id": "t-1", "status": "filled", "portfolio_id": "legacy-pf",
         "created_at": "2026-02-11T22:07:20+00:00"},
        {"id": "t-2", "status": "cancelled", "portfolio_id": "legacy-pf",
         "created_at": "2026-02-11T22:36:55+00:00"},
        {"id": "t-3", "status": "watchdog_cancelled", "portfolio_id": "legacy-pf",
         "created_at": "2026-04-06T16:30:06+00:00"},
    ]


def _closed_positions():
    return [{"id": "pos-1", "status": "closed", "portfolio_id": "legacy-pf",
             "created_at": "2026-03-01T00:00:00+00:00"}]


def _registrations(n=50):
    return {slot: f"pol-{slot:02d}" for slot in range(1, n + 1)}


def _approved_registry_rows(reg_map, epoch="small_tier_v1", status="approved"):
    """Registry rows (policy_registrations) for the ids in reg_map, all with the
    given epoch + approval status. Mirrors the seed shape (id/status/epoch)."""
    return [
        {"policy_registration_id": rid,
         "approval_status": status,
         "effective_epoch": epoch}
        for rid in sorted(set(reg_map.values()))
    ]


# Deterministic 64-char content fingerprints for the two prerequisite receipts.
_STALE_ORDER_RECEIPT_FP = "04317fc1" + "a" * 56
_MANUAL_REVIEW_RECEIPT_FP = "5d5cd9fc" + "b" * 56


def _reconciliation_receipts():
    """A structurally-valid receipt bundle covering both REQUIRED_RECEIPT_KINDS
    (scenario 5). STRUCTURE only — the RPC enforces EXISTENCE."""
    return [
        {"receipt_id": "recon:stale_order:small_tier_v1",
         "receipt_kind": "stale_order",
         "content_fingerprint": _STALE_ORDER_RECEIPT_FP},
        {"receipt_id": "recon:manual_review:small_tier_v1",
         "receipt_kind": "manual_review",
         "content_fingerprint": _MANUAL_REVIEW_RECEIPT_FP},
    ]


def _receipt_rows(user=USER, epoch="small_tier_v1"):
    """fleet_reconciliation_receipts rows matching _reconciliation_receipts()."""
    return [
        {"receipt_id": "recon:stale_order:small_tier_v1", "user_id": user,
         "receipt_kind": "stale_order", "content_fingerprint": _STALE_ORDER_RECEIPT_FP,
         "effective_epoch": epoch, "source_table": "paper_orders",
         "source_row_id": "04317fc1", "source_alert_id": None},
        {"receipt_id": "recon:manual_review:small_tier_v1", "user_id": user,
         "receipt_kind": "manual_review", "content_fingerprint": _MANUAL_REVIEW_RECEIPT_FP,
         "effective_epoch": epoch, "source_table": "paper_orders",
         "source_row_id": "5d5cd9fc", "source_alert_id": None},
    ]


def _attestation():
    return {
        "stale_order_reconciliation_receipt": "risk_alerts:receipt-abc123",
        "legacy_terminal_verified_at": "2026-07-17T02:00:00+00:00",
        "attested_by": "operator",
        # The default fixture registry (_approved_registry_rows(_registrations()))
        # has ids pol-01..pol-50, so the server-derived binding is exactly
        # _registrations() and its fingerprint is the value the operator attests.
        "expected_binding_fingerprint": sfa.binding_manifest_fingerprint(
            _registrations()),
        # Typed reconciliation-receipt bundle (scenario 5). Both required kinds.
        "reconciliation_receipts": _reconciliation_receipts(),
    }


def _clean_activatable_fake(**kw):
    # Registry seeded APPROVED for the default 50 ids so the happy path reaches
    # READY_TO_ACTIVATE (the Lane-A registry gate). Callers override via
    # registrations=... to exercise the not-registered / not-approved cases.
    kw.setdefault("registrations", _approved_registry_rows(_registrations()))
    return FakeSupabase(
        fleets=[_fleet_row()],
        micro_accounts=_micro_rows(),
        orders=_terminal_orders(),
        positions=_closed_positions(),
        **kw,
    )


def _authorize(monkeypatch):
    monkeypatch.setenv(sfa.AUTHORIZATION_ENV, "1")


# ── Readiness: legacy-terminal gates ────────────────────────────────────────

class TestLegacyTerminalGates:
    def test_six_stale_submitted_rows_block_activation(self):
        """The 6 stale 2026-04-09 'submitted' rows MUST trip the evaluator."""
        fake = FakeSupabase(
            fleets=[_fleet_row()], micro_accounts=_micro_rows(),
            orders=_terminal_orders() + _stale_submitted_orders(6),
            positions=_closed_positions(),
        )
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations(),
        )
        assert report.outcome == sfa.LEGACY_ORDERS_NOT_TERMINAL
        assert report.detail["legacy_nonterminal_orders"] == 6
        assert report.detail["legacy_nonterminal_order_statuses"] == {
            "submitted": 6}

    def test_ambiguous_order_status_blocks(self):
        """Allowlist semantics: unknown/ambiguous statuses block, not just
        the known-nonterminal ones."""
        fake = FakeSupabase(
            fleets=[_fleet_row()], micro_accounts=_micro_rows(),
            orders=_terminal_orders() + [
                {"id": "amb-1", "status": "needs_manual_review",
                 "portfolio_id": "legacy-pf", "created_at": "2026-05-11"},
                {"id": "amb-2", "status": "some_future_status",
                 "portfolio_id": "legacy-pf", "created_at": "2026-07-01"},
            ],
            positions=_closed_positions(),
        )
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations(),
        )
        assert report.outcome == sfa.LEGACY_ORDERS_NOT_TERMINAL
        assert report.detail["legacy_nonterminal_orders"] == 2

    def test_open_legacy_position_blocks(self):
        fake = FakeSupabase(
            fleets=[_fleet_row()], micro_accounts=_micro_rows(),
            orders=_terminal_orders(),
            positions=_closed_positions() + [
                {"id": "pos-open", "status": "open",
                 "portfolio_id": "legacy-pf", "created_at": "2026-07-01"},
            ],
        )
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations(),
        )
        assert report.outcome == sfa.LEGACY_POSITIONS_NOT_TERMINAL
        assert report.detail["legacy_open_positions"] == 1

    def test_fleet_slot_orders_do_not_block(self):
        """A nonterminal order INSIDE a fleet portfolio is not legacy scope."""
        fake = _clean_activatable_fake()
        fake.tables["paper_orders"].append(
            {"id": "fleet-o", "status": "staged", "portfolio_id": "pf-7",
             "created_at": "2026-07-17"})
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations(),
        )
        assert report.outcome == sfa.READY_TO_ACTIVATE


# ── Readiness: schema/contract/registration gates ───────────────────────────

class TestContractGates:
    def test_schema_unavailable_on_failed_order_read(self):
        """A failed read is NEVER ready (E8-3 []-sentinel lesson)."""
        fake = _clean_activatable_fake(fail_tables={"paper_orders"})
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations(),
        )
        assert report.outcome == sfa.SCHEMA_UNAVAILABLE
        assert "paper_orders" in report.detail["error"]

    def test_schema_unavailable_on_failed_fleet_read(self):
        fake = _clean_activatable_fake(fail_tables={"shadow_fleets"})
        report = sfa.evaluate_readiness(fake, USER, step="provision")
        assert report.outcome == sfa.SCHEMA_UNAVAILABLE

    def test_slot_count_enforced(self):
        fake = FakeSupabase(
            fleets=[_fleet_row()], micro_accounts=_micro_rows(49),
            orders=_terminal_orders(), positions=_closed_positions(),
        )
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations(),
        )
        assert report.outcome == sfa.SLOT_COUNT_INVALID

    def test_duplicate_slot_numbers_invalid(self):
        rows = _micro_rows(50)
        rows[10]["slot_number"] = 5  # duplicate slot, still 50 rows
        fake = FakeSupabase(
            fleets=[_fleet_row()], micro_accounts=rows,
            orders=_terminal_orders(), positions=_closed_positions(),
        )
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations(),
        )
        assert report.outcome == sfa.SLOT_COUNT_INVALID

    def test_capital_contract_enforced_per_slot(self):
        rows = _micro_rows(50)
        rows[3]["initial_net_liq"] = 2500
        fake = FakeSupabase(
            fleets=[_fleet_row()], micro_accounts=rows,
            orders=_terminal_orders(), positions=_closed_positions(),
        )
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations(),
        )
        assert report.outcome == sfa.CAPITAL_CONTRACT_INVALID

    def test_capital_contract_enforced_on_fleet_row(self):
        fake = FakeSupabase(
            fleets=[_fleet_row(capital_per_account=2500)],
            micro_accounts=_micro_rows(),
            orders=_terminal_orders(), positions=_closed_positions(),
        )
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations(),
        )
        assert report.outcome == sfa.CAPITAL_CONTRACT_INVALID

    def test_shared_capital_blocks(self):
        fake = FakeSupabase(
            fleets=[_fleet_row(shared_capital_enabled=True)],
            micro_accounts=_micro_rows(),
            orders=_terminal_orders(), positions=_closed_positions(),
        )
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations(),
        )
        assert report.outcome == sfa.CAPITAL_CONTRACT_INVALID

    def test_missing_policy_registrations_block(self):
        fake = _clean_activatable_fake()
        for regs in (None, {}, _registrations(49)):
            report = sfa.evaluate_readiness(
                fake, USER, step="activate", policy_registrations=regs)
            assert report.outcome == sfa.POLICY_REGISTRATION_MISSING, regs

    def test_blank_policy_registration_blocks(self):
        regs = _registrations()
        regs[17] = "   "
        report = sfa.evaluate_readiness(
            _clean_activatable_fake(), USER, step="activate",
            policy_registrations=regs)
        assert report.outcome == sfa.POLICY_REGISTRATION_MISSING

    def test_duplicate_policy_registration_blocks(self):
        regs = _registrations()
        regs[50] = regs[1]  # same policy id on two slots
        report = sfa.evaluate_readiness(
            _clean_activatable_fake(), USER, step="activate",
            policy_registrations=regs)
        assert report.outcome == sfa.POLICY_REGISTRATION_DUPLICATE
        assert report.detail["duplicates"][0]["policy_registration_id"] == "pol-01"

    def test_ready_to_activate_when_clean(self):
        report = sfa.evaluate_readiness(
            _clean_activatable_fake(), USER, step="activate",
            policy_registrations=_registrations())
        assert report.outcome == sfa.READY_TO_ACTIVATE
        assert report.detail["registered_slots"] == 50

    def test_activate_without_fleet_points_to_provision(self):
        fake = FakeSupabase(orders=_terminal_orders(),
                            positions=_closed_positions())
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations())
        assert report.outcome == sfa.READY_TO_PROVISION

    def test_provision_outcomes(self):
        # No fleet → ready (even with a dirty legacy book: rows are inert).
        fake = FakeSupabase(orders=_stale_submitted_orders())
        assert sfa.evaluate_readiness(
            fake, USER, step="provision").outcome == sfa.READY_TO_PROVISION
        # Fleet present → already_provisioned; active → already_active.
        assert sfa.evaluate_readiness(
            FakeSupabase(fleets=[_fleet_row()]), USER,
            step="provision").outcome == sfa.ALREADY_PROVISIONED
        assert sfa.evaluate_readiness(
            FakeSupabase(fleets=[_fleet_row(status="active")]), USER,
            step="provision").outcome == sfa.ALREADY_ACTIVE


# ── Dry-run writes NOTHING ──────────────────────────────────────────────────

class TestDryRun:
    def test_plan_provision_zero_writes(self):
        fake = FakeSupabase(orders=_stale_submitted_orders())
        plan = sfa.plan_provision(fake, USER, idempotency_key="k-1")
        assert plan["mode"] == "dry_run"
        assert plan["writes_performed"] == 0
        assert fake.writes == []
        assert fake.rpc_calls == []
        assert plan["plan"]["portfolios"]["routing_mode"] == "shadow_only"
        assert plan["plan"]["portfolios"]["cash_balance"] == 2000.0
        assert plan["receipt_spec"]["alert_type"] == "shadow_fleet_provisioned"
        assert plan["receipt_spec"]["severity"] == "info"

    def test_plan_activation_zero_writes_and_reports_attestation(self):
        fake = _clean_activatable_fake()
        plan = sfa.plan_activation(
            fake, USER, idempotency_key="k-2",
            policy_registrations=_registrations(),
            attestation=_attestation(),
        )
        assert plan["mode"] == "dry_run"
        assert fake.writes == [] and fake.rpc_calls == []
        assert plan["attestation_valid"] is True
        assert plan["would_execute"] is True
        assert plan["plan"]["effective_at"] == "db_now_in_rpc_transaction"
        assert plan["plan"]["legacy_terminal_verified_at"] == "from_attestation_only"

    def test_plan_activation_without_attestation_cannot_execute(self):
        plan = sfa.plan_activation(
            _clean_activatable_fake(), USER,
            policy_registrations=_registrations())
        assert plan["attestation_valid"] is False
        assert plan["attestation_error"] == "attestation_not_supplied"
        assert plan["would_execute"] is False


# ── Execution gates (env opt-in, confirm, idempotency key, attestation) ─────

class TestExecutionGates:
    def test_execute_refused_without_env(self, monkeypatch):
        monkeypatch.delenv(sfa.AUTHORIZATION_ENV, raising=False)
        fake = FakeSupabase()
        with pytest.raises(sfa.ActivationNotAuthorized):
            sfa.execute_provision(
                fake, USER, idempotency_key="k",
                confirm=sfa.CONFIRM_LITERAL)
        assert fake.rpc_calls == [] and fake.writes == []

    def test_execute_refused_on_lenient_truthy_env(self, monkeypatch):
        """Behavioral flag polarity: strict '=1' only — 'true' is refused."""
        monkeypatch.setenv(sfa.AUTHORIZATION_ENV, "true")
        fake = FakeSupabase()
        with pytest.raises(sfa.ActivationNotAuthorized):
            sfa.execute_provision(
                fake, USER, idempotency_key="k",
                confirm=sfa.CONFIRM_LITERAL)
        assert fake.rpc_calls == []

    def test_execute_refused_without_confirm_literal(self, monkeypatch):
        _authorize(monkeypatch)
        fake = FakeSupabase()
        with pytest.raises(sfa.OperatorConfirmationMissing):
            sfa.execute_provision(fake, USER, idempotency_key="k",
                                  confirm="yes please")
        assert fake.rpc_calls == []

    def test_execute_refused_without_idempotency_key(self, monkeypatch):
        _authorize(monkeypatch)
        fake = FakeSupabase()
        with pytest.raises(sfa.ShadowFleetActivationError):
            sfa.execute_provision(fake, USER, idempotency_key="  ",
                                  confirm=sfa.CONFIRM_LITERAL)
        assert fake.rpc_calls == []

    def test_activation_impossible_without_attestation(self, monkeypatch):
        _authorize(monkeypatch)
        fake = _clean_activatable_fake()
        with pytest.raises(sfa.AttestationInvalid):
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=None, confirm=sfa.CONFIRM_LITERAL)
        assert fake.rpc_calls == [] and fake.writes == []

    def test_attestation_requires_receipt_reference(self, monkeypatch):
        _authorize(monkeypatch)
        att = _attestation()
        att["stale_order_reconciliation_receipt"] = ""
        with pytest.raises(sfa.AttestationInvalid):
            sfa.execute_activation(
                _clean_activatable_fake(), USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=att, confirm=sfa.CONFIRM_LITERAL)

    def test_attestation_requires_tz_aware_verified_at(self, monkeypatch):
        _authorize(monkeypatch)
        att = _attestation()
        att["legacy_terminal_verified_at"] = "2026-07-17T02:00:00"  # naive
        with pytest.raises(sfa.AttestationInvalid):
            sfa.execute_activation(
                _clean_activatable_fake(), USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=att, confirm=sfa.CONFIRM_LITERAL)

    def test_stale_orders_block_execution_end_to_end(self, monkeypatch):
        """Route-level truth: full valid operator payload, failure injected
        at the ORIGIN (the six stale DB rows) → typed refusal at the TOP,
        zero RPC calls, zero writes."""
        _authorize(monkeypatch)
        fake = FakeSupabase(
            fleets=[_fleet_row()], micro_accounts=_micro_rows(),
            orders=_terminal_orders() + _stale_submitted_orders(6),
            positions=_closed_positions(),
        )
        with pytest.raises(sfa.ReadinessBlocked) as exc_info:
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert exc_info.value.outcome == sfa.LEGACY_ORDERS_NOT_TERMINAL
        assert fake.rpc_calls == [] and fake.writes == []


# ── Execution: atomic RPC, idempotency, no client-side writes ───────────────

class TestExecutionTransaction:
    def test_provision_calls_rpc_once_no_table_writes(self, monkeypatch):
        _authorize(monkeypatch)
        fake = FakeSupabase(orders=_terminal_orders(),
                            positions=_closed_positions())
        result = sfa.execute_provision(
            fake, USER, idempotency_key="prov-key-1",
            confirm=sfa.CONFIRM_LITERAL)
        assert result["status"] == "rpc_complete"
        assert len(fake.rpc_calls) == 1
        call = fake.rpc_calls[0]
        assert call["fn"] == sfa.PROVISION_RPC
        assert call["params"] == {
            "p_user_id": USER, "p_idempotency_key": "prov-key-1"}
        # The service NEVER writes tables directly — atomicity lives in the RPC.
        assert fake.writes == []

    def test_second_provision_invocation_is_idempotent(self, monkeypatch):
        _authorize(monkeypatch)
        fake = FakeSupabase(fleets=[_fleet_row()],
                            micro_accounts=_micro_rows(),
                            orders=_terminal_orders(),
                            positions=_closed_positions())
        result = sfa.execute_provision(
            fake, USER, idempotency_key="prov-key-2",
            confirm=sfa.CONFIRM_LITERAL)
        assert result["status"] == sfa.ALREADY_PROVISIONED
        assert result["writes_performed"] == 0
        assert fake.rpc_calls == [] and fake.writes == []

    def test_activation_already_active_is_idempotent(self, monkeypatch):
        _authorize(monkeypatch)
        fake = FakeSupabase(
            fleets=[_fleet_row(status="active",
                               effective_at="2026-07-17T15:00:00+00:00")],
            micro_accounts=_micro_rows(state="active"),
            orders=_terminal_orders(), positions=_closed_positions())
        result = sfa.execute_activation(
            fake, USER, idempotency_key="act-key-2",
            policy_registrations=_registrations(),
            attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert result["status"] == sfa.ALREADY_ACTIVE
        assert result["writes_performed"] == 0
        assert fake.rpc_calls == [] and fake.writes == []

    def test_activation_happy_path_rpc_payload_shape(self, monkeypatch):
        """The RPC payload carries the operator's registrations + attestation
        and NO client-side effective timestamp — the effective boundary is
        DB now() inside the RPC transaction."""
        _authorize(monkeypatch)
        fake = _clean_activatable_fake()
        result = sfa.execute_activation(
            fake, USER, idempotency_key="act-key-1",
            policy_registrations=_registrations(),
            attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert result["status"] == "rpc_complete"
        assert len(fake.rpc_calls) == 1
        call = fake.rpc_calls[0]
        assert call["fn"] == sfa.ACTIVATE_RPC
        params = call["params"]
        assert params["p_user_id"] == USER
        assert params["p_idempotency_key"] == "act-key-1"
        regs = params["p_policy_registrations"]
        assert len(regs) == 50
        assert set(regs) == {str(s) for s in range(1, 51)}
        assert len(set(regs.values())) == 50
        att = params["p_attestation"]
        assert att["stale_order_reconciliation_receipt"] == \
            "risk_alerts:receipt-abc123"
        assert att["attested_by"] == "operator"
        # The operator-attested binding fingerprint is threaded to the RPC as a
        # top-level param and equals the server-derived binding fingerprint.
        assert params["p_expected_binding_fingerprint"] == \
            sfa.binding_manifest_fingerprint(_registrations())
        # DB-derived effective time: no client timestamp of any kind.
        assert not any("effective" in key for key in params)
        assert fake.writes == []

    def test_rpc_failure_propagates_without_partial_client_writes(
            self, monkeypatch):
        """Failure injected at the DEEPEST callee (the RPC raises) → the
        error propagates and the service has performed ZERO table writes:
        there is no client-side compensation path that could leave a
        partially-visible activation."""
        _authorize(monkeypatch)

        def _boom(fn, params):
            raise RuntimeError("connection reset mid-RPC")

        fake = _clean_activatable_fake(rpc_handler=_boom)
        with pytest.raises(RuntimeError, match="mid-RPC"):
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert fake.writes == []
        # Fleet row is untouched — still pending, never active.
        assert fake.tables["shadow_fleets"][0]["status"] == \
            "pending_legacy_terminal"

    def test_legacy_rows_never_rewritten(self, monkeypatch):
        """No path — readiness, plan, execute — writes paper_orders or
        paper_positions."""
        _authorize(monkeypatch)
        fake = _clean_activatable_fake()
        sfa.evaluate_readiness(fake, USER, step="activate",
                               policy_registrations=_registrations())
        sfa.plan_provision(fake, USER, idempotency_key="k")
        sfa.plan_activation(fake, USER, idempotency_key="k",
                            policy_registrations=_registrations(),
                            attestation=_attestation())
        sfa.execute_activation(
            fake, USER, idempotency_key="k",
            policy_registrations=_registrations(),
            attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        legacy_writes = [w for w in fake.writes
                        if w["table"] in ("paper_orders", "paper_positions")]
        assert legacy_writes == []
        assert fake.writes == []  # stronger: the service writes nothing at all


# ── Drift-lock: service expectations vs the MIGRATION FILE TEXT ─────────────

def _strip_sql_comments(sql: str) -> str:
    return "\n".join(
        line.split("--", 1)[0] for line in sql.splitlines()
    )


class TestMigrationDriftLock:
    @pytest.fixture(scope="class")
    def schema_sql(self):
        return SCHEMA_MIGRATION.read_text(encoding="utf-8")

    @pytest.fixture(scope="class")
    def rpc_sql(self):
        return RPC_MIGRATION.read_text(encoding="utf-8")

    def test_schema_migration_pins_the_contract(self, schema_sql):
        for check in (
            "CHECK (micro_account_count = 50)",
            "CHECK (capital_per_account = 2000)",
            "CHECK (shared_capital_enabled = false)",
            "CHECK (slot_number BETWEEN 1 AND 50)",
            "CHECK (initial_net_liq = 2000)",
            "CHECK (initial_cash = 2000)",
            "idx_shadow_micro_accounts_fleet_policy_registration",
        ):
            assert check in schema_sql, f"schema migration lost: {check}"
        assert "'pending_legacy_terminal', 'ready', 'active', 'retired'" \
            in schema_sql

    def test_rpc_functions_match_service_names(self, rpc_sql):
        assert f"CREATE OR REPLACE FUNCTION {sfa.PROVISION_RPC}(" in rpc_sql
        assert f"CREATE OR REPLACE FUNCTION {sfa.ACTIVATE_RPC}(" in rpc_sql

    def test_order_terminal_allowlist_matches_service(self, rpc_sql):
        code = _strip_sql_comments(rpc_sql)
        match = re.search(r"o\.status\s+NOT\s+IN\s*\(([^)]*)\)", code, re.S)
        assert match, "order terminality allowlist missing from RPC migration"
        sql_allowlist = set(re.findall(r"'([a-z_]+)'", match.group(1)))
        assert sql_allowlist == set(sfa.TERMINAL_ORDER_STATUSES)

    def test_position_terminal_allowlist_matches_service(self, rpc_sql):
        code = _strip_sql_comments(rpc_sql)
        match = re.search(r"p\.status\s+NOT\s+IN\s*\(([^)]*)\)", code, re.S)
        assert match
        sql_allowlist = set(re.findall(r"'([a-z_]+)'", match.group(1)))
        assert sql_allowlist == set(sfa.TERMINAL_POSITION_STATUSES)

    def test_effective_time_is_db_now_never_a_parameter(self, rpc_sql):
        code = _strip_sql_comments(rpc_sql)
        assert "v_effective_at := now()" in code
        assert "p_effective" not in code  # no client-supplied effective time

    def test_verified_at_comes_only_from_attestation(self, rpc_sql):
        code = _strip_sql_comments(rpc_sql)
        assert "p_attestation->>'legacy_terminal_verified_at'" in code
        # The only assignment to legacy_terminal_verified_at is v_verified_at.
        assigns = re.findall(
            r"legacy_terminal_verified_at\s*=\s*([a-z_]+)", code)
        assert assigns and set(assigns) == {"v_verified_at"}

    def test_legacy_rows_never_rewritten_in_sql(self, rpc_sql):
        code = _strip_sql_comments(rpc_sql)
        assert not re.search(r"UPDATE\s+paper_orders", code, re.I)
        assert not re.search(r"DELETE\s+FROM\s+paper_orders", code, re.I)
        assert not re.search(r"UPDATE\s+paper_positions", code, re.I)
        assert not re.search(r"DELETE\s+FROM\s+paper_positions", code, re.I)

    def test_fleet_portfolios_shadow_only_never_live_eligible(self, rpc_sql):
        code = _strip_sql_comments(rpc_sql)
        assert "'shadow_only'" in code
        # live_eligible may appear in comments; never in executable SQL.
        assert "'live_eligible'" not in code

    def test_all_or_nothing_guards_present(self, rpc_sql):
        code = _strip_sql_comments(rpc_sql)
        # 50-slot activation count check → RAISE aborts the transaction.
        assert "GET DIAGNOSTICS v_updated = ROW_COUNT" in code
        assert "v_updated <> 50" in code
        # plpgsql function bodies are single transactions: no COMMIT inside.
        assert not re.search(r"^\s*COMMIT\s*;", code, re.M)

    def test_operator_only_grants(self, rpc_sql):
        code = _strip_sql_comments(rpc_sql)
        assert re.search(
            r"REVOKE\s+ALL\s+ON\s+FUNCTION\s+rpc_shadow_fleet_provision",
            code)
        assert re.search(
            r"REVOKE\s+ALL\s+ON\s+FUNCTION\s+rpc_shadow_fleet_activate",
            code)
        assert code.count("TO service_role") == 2

    def test_receipt_alert_types_match_service(self, rpc_sql):
        assert f"'{sfa.PROVISION_RECEIPT_ALERT_TYPE}'" in rpc_sql
        assert f"'{sfa.ACTIVATION_RECEIPT_ALERT_TYPE}'" in rpc_sql


# ── Registry-approval gates (Lane A: exists + approved + epoch) ─────────────

class TestRegistryApprovalGates:
    """The structurally-valid 50-id map must ALSO be approved rows in
    policy_registrations for the fleet epoch. Additive gate — it only ever
    BLOCKS after the structural + legacy + contract gates pass. Failure
    injected at the ORIGIN (the registry rows / the failing read), truth
    asserted at the TOP (typed outcome, zero writes/RPCs on execute)."""

    def test_all_approved_reaches_ready(self):
        report = sfa.evaluate_readiness(
            _clean_activatable_fake(), USER, step="activate",
            policy_registrations=_registrations())
        assert report.outcome == sfa.READY_TO_ACTIVATE
        assert report.detail["registry_approved_count"] == 50
        assert report.detail["registry_epoch"] == "small_tier_v1"

    def test_draft_registration_blocks(self):
        rows = _approved_registry_rows(_registrations())
        rows[7]["approval_status"] = "draft"
        fake = _clean_activatable_fake(registrations=rows)
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations())
        assert report.outcome == sfa.POLICY_NOT_APPROVED
        assert report.detail["unapproved_count"] == 1
        assert report.detail["unapproved"][0]["approval_status"] == "draft"

    def test_retired_and_revoked_can_never_newly_bind(self):
        for bad in ("retired", "revoked"):
            rows = _approved_registry_rows(_registrations())
            rows[0]["approval_status"] = bad
            fake = _clean_activatable_fake(registrations=rows)
            report = sfa.evaluate_readiness(
                fake, USER, step="activate",
                policy_registrations=_registrations())
            assert report.outcome == sfa.POLICY_NOT_APPROVED, bad
            assert report.detail["unapproved"][0]["approval_status"] == bad

    def test_missing_registration_blocks(self):
        rows = _approved_registry_rows(_registrations())[:-1]  # drop pol-50
        fake = _clean_activatable_fake(registrations=rows)
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations())
        assert report.outcome == sfa.POLICY_NOT_REGISTERED
        assert report.detail["missing_count"] == 1
        assert report.detail["missing_registration_ids"] == ["pol-50"]

    def test_wrong_epoch_is_not_registered(self):
        rows = _approved_registry_rows(_registrations(), epoch="other_epoch")
        fake = _clean_activatable_fake(registrations=rows)
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations())
        assert report.outcome == sfa.POLICY_NOT_REGISTERED
        assert report.detail["missing_count"] == 50

    def test_registry_read_failure_is_schema_unavailable(self):
        """A failed registry read is NEVER ready (E8-3 []-sentinel lesson)."""
        fake = _clean_activatable_fake(fail_tables={"policy_registrations"})
        report = sfa.evaluate_readiness(
            fake, USER, step="activate",
            policy_registrations=_registrations())
        assert report.outcome == sfa.SCHEMA_UNAVAILABLE

    def test_execute_blocks_on_unapproved_zero_writes(self, monkeypatch):
        _authorize(monkeypatch)
        rows = _approved_registry_rows(_registrations())
        rows[3]["approval_status"] = "draft"
        fake = _clean_activatable_fake(registrations=rows)
        with pytest.raises(sfa.ReadinessBlocked) as exc_info:
            sfa.execute_activation(
                fake, USER, idempotency_key="k",
                policy_registrations=_registrations(),
                attestation=_attestation(), confirm=sfa.CONFIRM_LITERAL)
        assert exc_info.value.outcome == sfa.POLICY_NOT_APPROVED
        assert fake.rpc_calls == [] and fake.writes == []

    def test_fetch_approved_policy_ids_returns_exact_set(self):
        rows = _approved_registry_rows(_registrations())
        rows[0]["approval_status"] = "draft"          # excluded (not approved)
        rows.append({"policy_registration_id": "other-epoch-pol",
                     "approval_status": "approved",
                     "effective_epoch": "other_epoch"})  # excluded (epoch)
        fake = FakeSupabase(registrations=rows)
        ids = sfa.fetch_approved_policy_ids(fake, "small_tier_v1")
        assert ids == sorted(f"pol-{s:02d}" for s in range(2, 51))
        assert "pol-01" not in ids and "other-epoch-pol" not in ids


# ── Outcome vocabulary is closed ────────────────────────────────────────────

def test_readiness_outcome_vocabulary_is_closed():
    """The typed outcome set is exactly the spec (11 Lane-3A + 2 Lane-A
    registry-existence outcomes)."""
    assert sfa.READINESS_OUTCOMES == {
        "schema_unavailable",
        "legacy_positions_not_terminal",
        "legacy_orders_not_terminal",
        "policy_registration_missing",
        "policy_registration_duplicate",
        "policy_not_registered",
        "policy_not_approved",
        "slot_count_invalid",
        "capital_contract_invalid",
        "already_provisioned",
        "already_active",
        "ready_to_provision",
        "ready_to_activate",
    }
