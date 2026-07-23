"""Real-PostgreSQL DDL proofs for the fleet decision-evidence foundation.

Collected only when a Postgres is reachable (see conftest.collect_ignore). Proves
against a LIVE server: both idempotency UNIQUE keys reject duplicates, the
decision table is append-only (UPDATE/DELETE blocked), the run identity is
immutable while status stays updatable, and the disposition/identity CHECKs bind.
"""

FLEET = "11111111-1111-1111-1111-111111111111"
USER = "44444444-4444-4444-4444-444444444444"
MICRO = "55555555-5555-5555-5555-555555555555"
DEC = "33333333-3333-3333-3333-333333333333"
JOB = "22222222-2222-2222-2222-222222222222"
CAND = "99999999-9999-9999-9999-999999999999"


def _seed(cur):
    cur.execute(
        f"INSERT INTO shadow_fleets (id,user_id,epoch_name,status) "
        f"VALUES ('{FLEET}','{USER}','small_tier_v1','active')"
    )
    cur.execute(
        "INSERT INTO policy_registrations "
        "(policy_registration_id,effective_epoch,approval_status) "
        "VALUES ('pol_1','small_tier_v1','approved')"
    )
    cur.execute(
        f"INSERT INTO shadow_micro_accounts "
        f"(id,fleet_id,slot_number,policy_registration_id,state) "
        f"VALUES ('{MICRO}','{FLEET}',1,'pol_1','active')"
    )


def _new_run(cur):
    cur.execute(
        "INSERT INTO fleet_policy_decision_runs "
        "(fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " source_decision_id,source_job_run_id,user_id,as_of,status) "
        f"VALUES ('{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'{DEC}','{JOB}','{USER}', now(),'running') RETURNING run_id"
    )
    return cur.fetchone()[0]


def _new_decision(cur, run_id, disposition="selected", event_id=CAND, cand_id=CAND):
    cur.execute(
        "INSERT INTO fleet_policy_decisions "
        "(run_id,fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " decision_event_id,candidate_suggestion_id,disposition,rank_at_decision) "
        f"VALUES ('{run_id}','{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'{event_id}','{cand_id}','{disposition}',1) RETURNING id"
    )
    return cur.fetchone()[0]


def _fails(cur, sql, *needles):
    raised = ""
    try:
        cur.execute(sql)
    except Exception as exc:  # pg8000 DatabaseError
        raised = str(exc).lower()
    assert raised, f"expected failure but statement succeeded: {sql[:80]}"
    assert any(n.lower() in raised for n in needles), (
        f"expected one of {needles} in error, got: {raised[:200]}"
    )


def test_run_unique_key_rejects_duplicate(conn):
    cur = conn.cursor()
    _seed(cur)
    _new_run(cur)
    # Second run for the SAME (source_decision_id, fleet_epoch, micro-account).
    _fails(
        cur,
        "INSERT INTO fleet_policy_decision_runs "
        "(fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " source_decision_id,source_job_run_id,user_id,as_of,status) "
        f"VALUES ('{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'{DEC}','{JOB}','{USER}', now(),'running')",
        "23505",
        "duplicate key",
    )


def test_decision_unique_key_and_append_only(conn):
    cur = conn.cursor()
    _seed(cur)
    run_id = _new_run(cur)
    dec_id = _new_decision(cur, run_id)

    # (decision_event_id, fleet_epoch, micro-account) is unique.
    _fails(
        cur,
        "INSERT INTO fleet_policy_decisions "
        "(run_id,fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " decision_event_id,candidate_suggestion_id,disposition,rank_at_decision) "
        f"VALUES ('{run_id}','{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'{CAND}','{CAND}','policy_rejected',2)",
        "23505",
        "duplicate key",
    )

    # Append-only: UPDATE and DELETE both raise.
    _fails(
        cur,
        f"UPDATE fleet_policy_decisions SET disposition='policy_rejected' WHERE id='{dec_id}'",
        "append-only",
    )
    _fails(
        cur,
        f"DELETE FROM fleet_policy_decisions WHERE id='{dec_id}'",
        "append-only",
    )


def test_decision_identity_and_disposition_checks(conn):
    cur = conn.cursor()
    _seed(cur)
    run_id = _new_run(cur)

    # candidate_suggestion_id must equal decision_event_id.
    _fails(
        cur,
        "INSERT INTO fleet_policy_decisions "
        "(run_id,fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " decision_event_id,candidate_suggestion_id,disposition,rank_at_decision) "
        f"VALUES ('{run_id}','{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'{CAND}','{DEC}','selected',1)",
        "check",
    )
    # disposition must be one of the three candidate-grain values.
    _fails(
        cur,
        "INSERT INTO fleet_policy_decisions "
        "(run_id,fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " decision_event_id,candidate_suggestion_id,disposition,rank_at_decision) "
        f"VALUES ('{run_id}','{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'{CAND}','{CAND}','no_candidate',1)",
        "check",
    )


def test_run_status_updatable_but_identity_immutable(conn):
    cur = conn.cursor()
    _seed(cur)
    run_id = _new_run(cur)

    # begin-run -> finish-run: status/counts UPDATE is allowed.
    cur.execute(
        f"UPDATE fleet_policy_decision_runs SET status='succeeded', "
        f"counts='{{\"selected\":1}}'::jsonb, finished_at=now() WHERE run_id='{run_id}'"
    )
    cur.execute(f"SELECT status FROM fleet_policy_decision_runs WHERE run_id='{run_id}'")
    assert cur.fetchone()[0] == "succeeded"

    # Identity columns are immutable; DELETE is blocked.
    _fails(
        cur,
        f"UPDATE fleet_policy_decision_runs SET source_decision_id='{CAND}' WHERE run_id='{run_id}'",
        "immutable",
    )
    _fails(
        cur,
        f"DELETE FROM fleet_policy_decision_runs WHERE run_id='{run_id}'",
        "not deletable",
    )


def test_run_status_enum_binds(conn):
    cur = conn.cursor()
    _seed(cur)
    _fails(
        cur,
        "INSERT INTO fleet_policy_decision_runs "
        "(fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " source_decision_id,source_job_run_id,user_id,as_of,status) "
        f"VALUES ('{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'{DEC}','{JOB}','{USER}', now(),'bogus_status')",
        "check",
    )
