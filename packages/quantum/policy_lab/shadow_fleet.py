"""Prospective small-tier shadow-fleet contract.

This module is deliberately side-effect free. It describes and validates the
operator-authorized small_tier_v1 fleet, but it does not create portfolios,
activate policies, change controls, or write to Supabase.

Evidence doctrine: accounts may evaluate the same source candidate in parallel,
but the statistical sampling unit is the immutable decision event, not the
number of micro-account evaluations.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Optional, Tuple
from uuid import UUID


FLEET_EPOCH = "small_tier_v1"
LEGACY_EPOCH = "legacy_100k"
CAPITAL_BASIS = "fixed_small_tier"
MICRO_ACCOUNT_COUNT = 50
CAPITAL_PER_ACCOUNT = 2_000.0
AGGREGATE_ADMINISTRATIVE_CAPITAL = (
    MICRO_ACCOUNT_COUNT * CAPITAL_PER_ACCOUNT
)
DECISION_EVENT_BASIS = "source_suggestion_id"


class FleetContractError(ValueError):
    """The requested fleet state violates the operator-authorized contract."""


@dataclass(frozen=True)
class MicroAccountSpec:
    """One isolated fleet slot.

    policy_registration_id assigns a pre-registered policy to the slot.
    Assignment is not activation: every slot remains inactive until a clean
    legacy boundary and an explicit effective timestamp are supplied.
    """

    slot_number: int
    initial_net_liq: float = CAPITAL_PER_ACCOUNT
    initial_cash: float = CAPITAL_PER_ACCOUNT
    policy_registration_id: Optional[str] = None
    state: str = "inactive"

    def __post_init__(self) -> None:
        if not 1 <= self.slot_number <= MICRO_ACCOUNT_COUNT:
            raise FleetContractError("slot_number_out_of_range")
        if self.initial_net_liq != CAPITAL_PER_ACCOUNT:
            raise FleetContractError("initial_net_liq_must_equal_2000")
        if self.initial_cash != CAPITAL_PER_ACCOUNT:
            raise FleetContractError("initial_cash_must_equal_2000")
        if self.state not in {"inactive", "active", "retired"}:
            raise FleetContractError("invalid_micro_account_state")
        if self.state == "active" and not self.policy_registration_id:
            raise FleetContractError("active_account_requires_registered_policy")
        if (
            self.policy_registration_id is not None
            and not str(self.policy_registration_id).strip()
        ):
            raise FleetContractError("empty_policy_registration_id")


@dataclass(frozen=True)
class SmallTierFleetPlan:
    """Validated fleet plan; still inert until activate is called."""

    accounts: Tuple[MicroAccountSpec, ...]
    legacy_open_positions: int
    legacy_working_orders: int
    epoch_name: str = FLEET_EPOCH
    legacy_epoch_name: str = LEGACY_EPOCH
    capital_basis: str = CAPITAL_BASIS
    decision_event_basis: str = DECISION_EVENT_BASIS
    effective_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if len(self.accounts) != MICRO_ACCOUNT_COUNT:
            raise FleetContractError("fleet_must_have_exactly_50_accounts")
        slots = [account.slot_number for account in self.accounts]
        if slots != list(range(1, MICRO_ACCOUNT_COUNT + 1)):
            raise FleetContractError("fleet_slots_must_be_contiguous_1_to_50")
        registrations = [
            account.policy_registration_id
            for account in self.accounts
            if account.policy_registration_id is not None
        ]
        if len(registrations) != len(set(registrations)):
            raise FleetContractError("policy_registration_must_be_unique")
        if self.legacy_open_positions < 0 or self.legacy_working_orders < 0:
            raise FleetContractError("legacy_counts_must_be_nonnegative")
        if self.epoch_name != FLEET_EPOCH:
            raise FleetContractError("invalid_fleet_epoch")
        if self.legacy_epoch_name != LEGACY_EPOCH:
            raise FleetContractError("invalid_legacy_epoch")
        if self.capital_basis != CAPITAL_BASIS:
            raise FleetContractError("invalid_capital_basis")
        if self.decision_event_basis != DECISION_EVENT_BASIS:
            raise FleetContractError("invalid_decision_event_basis")

    @property
    def aggregate_administrative_capital(self) -> float:
        """Reporting total only; never a sizing or loss-recovery balance."""

        return sum(account.initial_net_liq for account in self.accounts)

    @property
    def clean_legacy_boundary(self) -> bool:
        return (
            self.legacy_open_positions == 0
            and self.legacy_working_orders == 0
        )

    @property
    def activation_status(self) -> str:
        if self.effective_at is not None:
            return "active"
        if self.clean_legacy_boundary:
            return "ready_for_operator_activation"
        return "pending_legacy_terminal"

    @property
    def assigned_accounts(self) -> Tuple[MicroAccountSpec, ...]:
        return tuple(
            account
            for account in self.accounts
            if account.policy_registration_id is not None
        )

    def activate(self, effective_at: datetime) -> "SmallTierFleetPlan":
        """Return the explicitly activated plan.

        The caller owns the durable transaction. This function refuses to
        cross the legacy boundary, invent a timestamp, or activate an
        unregistered slot.
        """

        if not self.clean_legacy_boundary:
            raise FleetContractError("legacy_positions_or_orders_not_terminal")
        if effective_at.tzinfo is None:
            raise FleetContractError("effective_at_must_be_timezone_aware")
        if not self.assigned_accounts:
            raise FleetContractError("no_preregistered_policies")

        activated = tuple(
            MicroAccountSpec(
                slot_number=account.slot_number,
                initial_net_liq=account.initial_net_liq,
                initial_cash=account.initial_cash,
                policy_registration_id=account.policy_registration_id,
                state=(
                    "active"
                    if account.policy_registration_id is not None
                    else "inactive"
                ),
            )
            for account in self.accounts
        )
        return SmallTierFleetPlan(
            accounts=activated,
            legacy_open_positions=0,
            legacy_working_orders=0,
            effective_at=effective_at,
        )


def build_small_tier_fleet_plan(
    policy_registrations: Optional[Mapping[int, str]] = None,
    *,
    legacy_open_positions: int,
    legacy_working_orders: int,
) -> SmallTierFleetPlan:
    """Build all 50 isolated slots; only pre-registered slots are assigned."""

    registrations = dict(policy_registrations or {})
    invalid_slots = sorted(
        slot
        for slot in registrations
        if not isinstance(slot, int)
        or isinstance(slot, bool)
        or not 1 <= slot <= MICRO_ACCOUNT_COUNT
    )
    if invalid_slots:
        raise FleetContractError(
            f"registration_slot_out_of_range:{invalid_slots}"
        )

    accounts = tuple(
        MicroAccountSpec(
            slot_number=slot,
            policy_registration_id=registrations.get(slot),
        )
        for slot in range(1, MICRO_ACCOUNT_COUNT + 1)
    )
    return SmallTierFleetPlan(
        accounts=accounts,
        legacy_open_positions=legacy_open_positions,
        legacy_working_orders=legacy_working_orders,
    )


def normalize_decision_event_id(source_suggestion_id: object) -> str:
    """Return the canonical UUID used by every account evaluation."""

    if source_suggestion_id is None or isinstance(source_suggestion_id, bool):
        raise FleetContractError("missing_decision_event_id")
    try:
        return str(UUID(str(source_suggestion_id)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise FleetContractError("invalid_decision_event_id") from exc


def count_unique_decision_events(event_ids: Iterable[object]) -> int:
    """Evidence n: unique market decisions, never account-row count."""

    return len({normalize_decision_event_id(event_id) for event_id in event_ids})
