"""Real-PostgreSQL DDL proofs for the fleet candidate-universe v2 identity.

Applied on top of the C1 foundation by the shared conftest migration chain
(foundation -> 20260724010000 candidate-fingerprint identity). Proves against a
LIVE server that the additive evolution binds: the data_unavailable candidate
disposition is accepted, a rejected candidate (NULL suggestion UUID + fingerprint)
is insertable, the (run_id, candidate_fingerprint) dedup and the identity-present
CHECK both fire, and the append-only trigger still holds for the new rows.

Collected only when a Postgres is reachable (see conftest.collect_ignore).
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


def test_data_unavailable_disposition_is_accepted(conn):
    cur = conn.cursor()
    _seed(cur)
    run_id = _new_run(cur)
    # data_unavailable is a valid candidate-grain disposition in v2.
    cur.execute(
        "INSERT INTO fleet_policy_decisions "
        "(run_id,fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " candidate_fingerprint,decision_event_id,candidate_suggestion_id,"
        " disposition,rank_at_decision) "
        f"VALUES ('{run_id}','{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'s:rejfp',NULL,NULL,'data_unavailable',5) RETURNING id"
    )
    assert cur.fetchone()[0]
    # no_candidate is still NOT a candidate-grain disposition.
    _fails(
        cur,
        "INSERT INTO fleet_policy_decisions "
        "(run_id,fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " candidate_fingerprint,disposition,rank_at_decision) "
        f"VALUES ('{run_id}','{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'s:other','no_candidate',1)",
        "check",
    )


def test_rejected_candidate_null_suggestion_is_insertable(conn):
    cur = conn.cursor()
    _seed(cur)
    run_id = _new_run(cur)
    # A rejected candidate carries only the fingerprint; both suggestion-UUID
    # columns NULL (they satisfy the preserved candidate_suggestion_id =
    # decision_event_id CHECK, and the identity-present CHECK via the fingerprint).
    cur.execute(
        "INSERT INTO fleet_policy_decisions "
        "(run_id,fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " candidate_fingerprint,decision_event_id,candidate_suggestion_id,"
        " disposition,rank_at_decision) "
        f"VALUES ('{run_id}','{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'s:rej1',NULL,NULL,'data_unavailable',9) RETURNING id"
    )
    assert cur.fetchone()[0]


def test_run_fingerprint_unique_rejects_duplicate(conn):
    cur = conn.cursor()
    _seed(cur)
    run_id = _new_run(cur)
    cur.execute(
        "INSERT INTO fleet_policy_decisions "
        "(run_id,fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " candidate_fingerprint,decision_event_id,candidate_suggestion_id,"
        " disposition,rank_at_decision) "
        f"VALUES ('{run_id}','{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'s:dup',NULL,NULL,'data_unavailable',1)"
    )
    # Same (run_id, candidate_fingerprint) -> 23505 (dedup on the immutable id).
    _fails(
        cur,
        "INSERT INTO fleet_policy_decisions "
        "(run_id,fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " candidate_fingerprint,decision_event_id,candidate_suggestion_id,"
        " disposition,rank_at_decision) "
        f"VALUES ('{run_id}','{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'s:dup',NULL,NULL,'policy_rejected',2)",
        "23505",
        "duplicate key",
    )


def test_identity_present_check_rejects_both_null(conn):
    cur = conn.cursor()
    _seed(cur)
    run_id = _new_run(cur)
    # Neither a fingerprint nor a suggestion UUID -> no durable identity -> reject.
    _fails(
        cur,
        "INSERT INTO fleet_policy_decisions "
        "(run_id,fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " candidate_fingerprint,decision_event_id,candidate_suggestion_id,"
        " disposition,rank_at_decision) "
        f"VALUES ('{run_id}','{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"NULL,NULL,NULL,'data_unavailable',1)",
        "check",
    )


def test_emitted_candidate_still_append_only(conn):
    cur = conn.cursor()
    _seed(cur)
    run_id = _new_run(cur)
    cur.execute(
        "INSERT INTO fleet_policy_decisions "
        "(run_id,fleet_id,fleet_epoch,shadow_micro_account_id,policy_registration_id,"
        " candidate_fingerprint,decision_event_id,candidate_suggestion_id,"
        " disposition,rank_at_decision) "
        f"VALUES ('{run_id}','{FLEET}','small_tier_v1','{MICRO}','pol_1',"
        f"'s:emit','{CAND}','{CAND}','selected',1) RETURNING id"
    )
    dec_id = cur.fetchone()[0]
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
