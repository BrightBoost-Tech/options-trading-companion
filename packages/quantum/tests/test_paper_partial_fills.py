
import pytest
from packages.quantum.paper_endpoints import _compute_fill_deltas

def test_compute_fill_deltas_step1_partial():
    # Step 1: Request 20, Fill 10
    order = {
        "requested_qty": 20.0,
        "filled_qty": 0.0, # previous
        "fees_usd": 0.0,   # previous
        "tcm": {"fees_usd": 2.0} # est total fees for 20
    }
    fill_res = {
        "status": "partial",
        "filled_qty": 10.0,
        "avg_fill_price": 1.50,
        "last_fill_qty": 10.0,
        "last_fill_price": 1.50
    }

    deltas = _compute_fill_deltas(order, fill_res)

    # fees_total = (10/20) * 2.0 = 1.0
    # fees_delta = 1.0 - 0.0 = 1.0

    assert deltas["this_fill_qty"] == 10.0
    assert deltas["this_fill_price"] == 1.50
    assert deltas["new_total_filled_qty"] == 10.0
    assert deltas["fees_total"] == 1.0
    assert deltas["fees_delta"] == 1.0

def test_compute_fill_deltas_step2_full():
    # Step 2: Fill remaining 10
    # The order state passed in reflects the state AFTER Step 1 commit
    order = {
        "requested_qty": 20.0,
        "filled_qty": 10.0, # from step 1
        "fees_usd": 1.0,    # from step 1
        "tcm": {"fees_usd": 2.0}
    }

    # TCM returns cumulative totals usually
    fill_res = {
        "status": "filled",
        "filled_qty": 20.0,        # total filled
        "avg_fill_price": 1.60,    # (10*1.5 + 10*1.7)/20 = 1.6
        "last_fill_qty": 10.0,     # this tick
        "last_fill_price": 1.70    # this tick price
    }

    deltas = _compute_fill_deltas(order, fill_res)

    # fees_total = (20/20) * 2.0 = 2.0
    # fees_delta = 2.0 - 1.0 = 1.0

    assert deltas["this_fill_qty"] == 10.0
    assert deltas["this_fill_price"] == 1.70
    assert deltas["new_total_filled_qty"] == 20.0
    assert deltas["new_avg_fill_price"] == 1.60
    assert deltas["fees_total"] == 2.0
    assert deltas["fees_delta"] == 1.0

def test_compute_fill_deltas_no_new_fill():
    # Rerun logic with no changes
    order = {
        "requested_qty": 20.0,
        "filled_qty": 20.0,
        "fees_usd": 2.0,
        "tcm": {"fees_usd": 2.0}
    }
    fill_res = {
        "status": "filled",
        "filled_qty": 20.0,
        "avg_fill_price": 1.60,
        "last_fill_qty": 0.0,   # No new fill
        "last_fill_price": 0.0
    }

    deltas = _compute_fill_deltas(order, fill_res)

    assert deltas["this_fill_qty"] == 0.0
    assert deltas["fees_delta"] == 0.0
    assert deltas["new_total_filled_qty"] == 20.0
