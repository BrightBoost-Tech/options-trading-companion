"""Contract tests for the prospective small_tier_v1 shadow fleet."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from packages.quantum.policy_lab.shadow_fleet import (
    AGGREGATE_ADMINISTRATIVE_CAPITAL,
    CAPITAL_PER_ACCOUNT,
    FleetContractError,
    MICRO_ACCOUNT_COUNT,
    build_small_tier_fleet_plan,
    count_unique_decision_events,
    normalize_decision_event_id,
)


def test_builds_exactly_fifty_isolated_two_thousand_dollar_slots():
    plan = build_small_tier_fleet_plan(
        {1: "champion:v1", 2: "neutral:v1"},
        legacy_open_positions=0,
        legacy_working_orders=0,
    )

    assert len(plan.accounts) == MICRO_ACCOUNT_COUNT == 50
    assert [account.slot_number for account in plan.accounts] == list(
        range(1, 51)
    )
    assert all(
        account.initial_net_liq == CAPITAL_PER_ACCOUNT
        and account.initial_cash == CAPITAL_PER_ACCOUNT
        for account in plan.accounts
    )
    assert plan.aggregate_administrative_capital == (
        AGGREGATE_ADMINISTRATIVE_CAPITAL
    )
    assert plan.aggregate_administrative_capital == 100_000
    assert all(account.state == "inactive" for account in plan.accounts)


def test_only_preregistered_slots_activate_and_unassigned_slots_stay_inactive():
    plan = build_small_tier_fleet_plan(
        {1: "champion:v1", 7: "conservative:v1"},
        legacy_open_positions=0,
        legacy_working_orders=0,
    )

    activated = plan.activate(datetime(2026, 7, 16, 6, 30, tzinfo=timezone.utc))

    assert activated.activation_status == "active"
    assert [
        account.slot_number
        for account in activated.accounts
        if account.state == "active"
    ] == [1, 7]
    assert all(
        account.state == "inactive"
        for account in activated.accounts
        if account.slot_number not in {1, 7}
    )


@pytest.mark.parametrize(
    "open_positions,working_orders",
    [(1, 0), (0, 1), (2, 3)],
)
def test_legacy_positions_or_orders_block_activation(
    open_positions, working_orders
):
    plan = build_small_tier_fleet_plan(
        {1: "champion:v1"},
        legacy_open_positions=open_positions,
        legacy_working_orders=working_orders,
    )

    assert plan.activation_status == "pending_legacy_terminal"
    with pytest.raises(
        FleetContractError,
        match="legacy_positions_or_orders_not_terminal",
    ):
        plan.activate(datetime.now(timezone.utc))


def test_clean_boundary_without_policy_is_not_activation_authority():
    plan = build_small_tier_fleet_plan(
        legacy_open_positions=0,
        legacy_working_orders=0,
    )

    assert plan.activation_status == "ready_for_operator_activation"
    with pytest.raises(FleetContractError, match="no_preregistered_policies"):
        plan.activate(datetime.now(timezone.utc))


def test_effective_at_must_be_explicit_and_timezone_aware():
    plan = build_small_tier_fleet_plan(
        {1: "champion:v1"},
        legacy_open_positions=0,
        legacy_working_orders=0,
    )

    with pytest.raises(
        FleetContractError,
        match="effective_at_must_be_timezone_aware",
    ):
        plan.activate(datetime(2026, 7, 16, 6, 30))


def test_policy_registration_ids_are_unique_not_identical_clones():
    with pytest.raises(
        FleetContractError,
        match="policy_registration_must_be_unique",
    ):
        build_small_tier_fleet_plan(
            {1: "same-policy:v1", 2: "same-policy:v1"},
            legacy_open_positions=0,
            legacy_working_orders=0,
        )


@pytest.mark.parametrize("slot", [0, 51, -1, True])
def test_registration_slot_must_be_an_exact_integer_in_range(slot):
    with pytest.raises(
        FleetContractError,
        match="registration_slot_out_of_range",
    ):
        build_small_tier_fleet_plan(
            {slot: "policy:v1"},
            legacy_open_positions=0,
            legacy_working_orders=0,
        )


def test_decision_event_is_source_suggestion_uuid_and_is_canonicalized():
    event_id = uuid4()

    assert normalize_decision_event_id(event_id) == str(event_id)
    assert normalize_decision_event_id(str(event_id).upper()) == str(event_id)


@pytest.mark.parametrize("bad", [None, True, "", "not-a-uuid", 123])
def test_invalid_decision_event_fails_closed(bad):
    with pytest.raises(FleetContractError):
        normalize_decision_event_id(bad)


def test_identical_account_outcomes_count_as_one_market_observation():
    first = uuid4()
    second = uuid4()

    assert count_unique_decision_events(
        [first, str(first), str(first).upper(), second]
    ) == 2


@pytest.mark.parametrize(
    "open_positions,working_orders",
    [(True, 0), (0, False), (1.5, 0), (0, "0"), (-1, 0)],
)
def test_legacy_counts_must_be_exact_nonnegative_integers(
    open_positions, working_orders
):
    with pytest.raises(
        FleetContractError,
        match="legacy_counts_must_be_nonnegative_integers",
    ):
        build_small_tier_fleet_plan(
            {1: "champion:v1"},
            legacy_open_positions=open_positions,
            legacy_working_orders=working_orders,
        )


def test_active_epoch_cannot_be_reactivated_with_a_new_timestamp():
    plan = build_small_tier_fleet_plan(
        {1: "champion:v1"},
        legacy_open_positions=0,
        legacy_working_orders=0,
    )
    active = plan.activate(
        datetime(2026, 7, 16, 6, 30, tzinfo=timezone.utc)
    )

    with pytest.raises(FleetContractError, match="fleet_epoch_already_active"):
        active.activate(
            datetime(2026, 7, 16, 7, 30, tzinfo=timezone.utc)
        )
