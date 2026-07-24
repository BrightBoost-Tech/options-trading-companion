"""Real-PostgreSQL proofs for the fleet_shadow lifecycle RPCs (C2).

Collected only when a Postgres is reachable (see conftest.collect_ignore).
"""

FLEET = "11111111-1111-1111-1111-111111111111"
USER = "44444444-4444-4444-4444-444444444444"
MICRO = "55555555-5555-5555-5555-555555555555"
PF = "66666666-6666-6666-6666-666666666666"
RUN = "77777777-7777-7777-7777-777777777777"
DEC = "33333333-3333-3333-3333-333333333333"
CAND = "99999999-9999-9999-9999-999999999999"

# Iron condor: sell 690P / buy 685P / sell 772C / buy 777C. Width 500, credit
# 190 -> max loss 310. Normalized signed legs, 1 contract each.
LEGS = (
    '[{"option_type":"put","strike":690,"sign":-1,"contracts":1},'
    '{"option_type":"put","strike":685,"sign":1,"contracts":1},'
    '{"option_type":"call","strike":772,"sign":-1,"contracts":1},'
    '{"option_type":"call","strike":777,"sign":1,"contracts":1}]'
)
ENTRY_NET_COST = -190      # net credit received (executable side)
MAX_LOSS = 310             # width 500 - credit 190
EXPIRY = "2026-07-20"      # past date so now() can settle in-test


def _seed(cur, *, active):
    fleet_status = "active" if active else "pending_legacy_terminal"
    micro_state = "active" if active else "inactive"
    cur.execute(
        f"INSERT INTO paper_portfolios (id,user_id,cash_balance,net_liq,routing_mode) "
        f"VALUES ('{PF}','{USER}',2000,2000,'shadow_only')"
    )
    cur.execute(
        f"INSERT INTO shadow_fleets (id,user_id,epoch_name,status) "
        f"VALUES ('{FLEET}','{USER}','small_tier_v1','{fleet_status}')"
    )
    cur.execute(
        "INSERT INTO policy_registrations (policy_registration_id,effective_epoch,approval_status) "
        "VALUES ('pol_1','small_tier_v1','approved')"
    )
    cur.execute(
        f"INSERT INTO shadow_micro_accounts (id,fleet_id,slot_number,portfolio_id,policy_registration_id,state) "
        f"VALUES ('{MICRO}','{FLEET}',1,'{PF}','pol_1','{micro_state}')"
    )
    cur.execute(
        "INSERT INTO fleet_policy_decision_runs "
        "(run_id,fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " source_decision_id,source_job_run_id,user_id,as_of,status) "
        f"VALUES ('{RUN}','{FLEET}','small_tier_v1','{MICRO}','pol_1','{DEC}',"
        f"'{DEC}','{USER}', now(),'succeeded')"
    )
    cur.execute(
        "INSERT INTO fleet_policy_decisions "
        "(run_id,fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " decision_event_id,candidate_suggestion_id,disposition,rank_at_decision) "
        f"VALUES ('{RUN}','{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'{CAND}','{CAND}','selected',1)"
    )


def _open(cur, spot_reason="open"):
    cur.execute(
        "SELECT rpc_open_fleet_shadow_position_v1("
        f"'{RUN}','{MICRO}','pol_1','{PF}','{USER}','{CAND}','SPY',"
        f"'{LEGS}'::jsonb, 1, {ENTRY_NET_COST}, {MAX_LOSS}, '{EXPIRY}', now(), now())"
    )
    return cur.fetchone()[0]


def _cash(cur):
    cur.execute(f"SELECT cash_balance FROM paper_portfolios WHERE id='{PF}'")
    return float(cur.fetchone()[0])


def _fails(cur, sql, *needles):
    raised = ""
    try:
        cur.execute(sql)
    except Exception as exc:
        raised = str(exc).lower()
    assert raised, f"expected failure but statement succeeded: {sql[:80]}"
    assert any(n.lower() in raised for n in needles), (
        f"expected one of {needles} in error, got: {raised[:200]}"
    )


def test_open_rejected_while_inactive_cash_byte_identical(conn):
    cur = conn.cursor()
    _seed(cur, active=False)
    before = _cash(cur)
    _fails(
        cur,
        "SELECT rpc_open_fleet_shadow_position_v1("
        f"'{RUN}','{MICRO}','pol_1','{PF}','{USER}','{CAND}','SPY',"
        f"'{LEGS}'::jsonb, 1, {ENTRY_NET_COST}, {MAX_LOSS}, '{EXPIRY}', now(), now())",
        "not active", "unbound",
    )
    assert _cash(cur) == before  # byte-identical: zero writes on rejection


def test_open_reserves_collateral_and_is_idempotent(conn):
    cur = conn.cursor()
    _seed(cur, active=True)
    receipt = _open(cur)
    assert receipt["status"] == "filled_internal"
    assert receipt["idempotent_replay"] is False
    assert _cash(cur) == 2000 - MAX_LOSS  # 1690 reserved

    # Replay: same (run, candidate) -> idempotent no-op, cash unchanged.
    replay = _open(cur)
    assert replay["idempotent_replay"] is True
    assert _cash(cur) == 2000 - MAX_LOSS

    # Exactly one order + one open position + one entry cash event.
    cur.execute(f"SELECT count(*) FROM fleet_shadow_orders WHERE run_id='{RUN}'")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT count(*) FROM fleet_shadow_cash_events WHERE event_type='entry_reservation'")
    assert cur.fetchone()[0] == 1


def test_close_expiry_win_conserves_cash_to_pnl(conn):
    cur = conn.cursor()
    _seed(cur, active=True)
    receipt = _open(cur)
    pos = receipt["position_id"]
    # Terminal spot 730: every leg OTM -> payoff 0 -> pnl = 0 - (-190) = +190.
    cur.execute(f"SELECT rpc_close_fleet_shadow_position_v1('{pos}', 730, now(), 'expiry')")
    close = cur.fetchone()[0]
    assert float(close["terminal_payoff_total"]) == 0.0
    assert float(close["realized_pnl"]) == 190.0
    # cash = 2000 - 310 (reserve) + (310 + 190) (release) = 2190. Net = +pnl.
    assert _cash(cur) == 2190.0
    cur.execute(f"SELECT net_liq FROM paper_portfolios WHERE id='{PF}'")
    assert float(cur.fetchone()[0]) == 2190.0  # net_liq += pnl

    # Idempotent close replay: cash unchanged.
    cur.execute(f"SELECT rpc_close_fleet_shadow_position_v1('{pos}', 730, now(), 'expiry')")
    assert cur.fetchone()[0]["idempotent_replay"] is True
    assert _cash(cur) == 2190.0


def test_close_expiry_loss_caps_at_max_loss(conn):
    cur = conn.cursor()
    _seed(cur, active=True)
    receipt = _open(cur)
    pos = receipt["position_id"]
    # Terminal spot 780: call spread breached fully. sell 772C -> -8*100=-800,
    # buy 777C -> +3*100=+300 => payoff -500. pnl = -500 - (-190) = -310 = -max.
    cur.execute(f"SELECT rpc_close_fleet_shadow_position_v1('{pos}', 780, now(), 'expiry')")
    close = cur.fetchone()[0]
    assert float(close["terminal_payoff_total"]) == -500.0
    assert float(close["realized_pnl"]) == -310.0
    # cash = 2000 - 310 + (310 - 310) = 1690. Loss exactly the defined max.
    assert _cash(cur) == 1690.0


def test_open_rejects_unselected_candidate(conn):
    cur = conn.cursor()
    _seed(cur, active=True)
    other = "88888888-8888-8888-8888-888888888888"
    _fails(
        cur,
        "SELECT rpc_open_fleet_shadow_position_v1("
        f"'{RUN}','{MICRO}','pol_1','{PF}','{USER}','{other}','SPY',"
        f"'{LEGS}'::jsonb, 1, {ENTRY_NET_COST}, {MAX_LOSS}, '{EXPIRY}', now(), now())",
        "no selected decision",
    )


def test_close_before_expiry_rejected(conn):
    cur = conn.cursor()
    _seed(cur, active=True)
    pos = _open(cur)["position_id"]
    _fails(
        cur,
        f"SELECT rpc_close_fleet_shadow_position_v1('{pos}', 730, '2026-07-19T00:00:00Z', 'expiry')",
        "before expiry",
    )


def test_orders_and_outcomes_append_only(conn):
    cur = conn.cursor()
    _seed(cur, active=True)
    order_id = _open(cur)["order_id"]
    _fails(cur, f"UPDATE fleet_shadow_orders SET contracts=2 WHERE order_id='{order_id}'", "append-only")
    _fails(cur, f"DELETE FROM fleet_shadow_orders WHERE order_id='{order_id}'", "append-only")
