"""Lane A — migration-contract drift-lock for policy_registrations.

Parses the MIGRATION FILE TEXT (20260719000000) — not the live DB — so a
contract change (table shape, immutability trigger, RLS) breaks the build. The
migration is UNAPPLIED by this PR; this is the only guard on its shape until an
operator applies it.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (REPO_ROOT / "supabase" / "migrations"
             / "20260719000000_policy_registrations.sql")


@pytest.fixture(scope="module")
def sql():
    return MIGRATION.read_text(encoding="utf-8")


def test_creates_table(sql):
    assert "CREATE TABLE IF NOT EXISTS policy_registrations" in sql


def test_all_columns_present(sql):
    for col in (
        "policy_registration_id text PRIMARY KEY",
        "policy_family text NOT NULL",
        "anchor_lineage text NOT NULL",
        "policy_config jsonb NOT NULL",
        "config_canonical text NOT NULL",
        "config_hash text NOT NULL",
        "schema_version integer NOT NULL DEFAULT 1",
        "approval_status text NOT NULL DEFAULT 'draft'",
        "effective_epoch text NOT NULL",
        "changed_axes jsonb",
        "design_rationale text",
        "created_at timestamptz NOT NULL DEFAULT now()",
        "approved_at timestamptz",
        "created_by text",
    ):
        assert col in sql, f"migration lost column: {col}"


def test_pk_nonblank_check(sql):
    assert "CHECK (btrim(policy_registration_id) <> '')" in sql


def test_approval_status_check_enum(sql):
    assert (
        "CHECK (approval_status IN ('draft', 'approved', 'retired', 'revoked'))"
        in sql
    )


def test_unique_epoch_hash(sql):
    assert "UNIQUE (effective_epoch, config_hash)" in sql


def test_immutability_trigger_present(sql):
    assert ("CREATE OR REPLACE FUNCTION "
            "policy_registrations_immutable_after_approval()") in sql
    assert "BEFORE UPDATE ON policy_registrations" in sql
    assert "trg_policy_registrations_immutable" in sql
    # the frozen columns are all named in the guard
    guard = sql[sql.index("policy_registrations_immutable_after_approval()"):]
    for col in ("policy_registration_id", "policy_config", "config_canonical",
                "config_hash", "schema_version"):
        assert f"NEW.{col}" in guard and f"OLD.{col}" in guard
    assert "RAISE EXCEPTION" in guard
    # only fires while the row IS approved
    assert "OLD.approval_status = 'approved'" in guard


def test_rls_enabled_and_service_role_only(sql):
    assert "ALTER TABLE policy_registrations ENABLE ROW LEVEL SECURITY" in sql
    assert re.search(
        r"CREATE POLICY .+ ON policy_registrations\s+FOR ALL", sql, re.S)
    assert "auth.role() = 'service_role'" in sql


def test_documented(sql):
    assert "COMMENT ON TABLE policy_registrations IS" in sql
    assert "COMMENT ON COLUMN policy_registrations.config_hash IS" in sql
    assert "COMMENT ON COLUMN policy_registrations.approval_status IS" in sql


def test_not_applied_and_derivation_noted(sql):
    assert "NOT APPLIED BY THIS PR" in sql
    # config_hash is documented as derived (seed computes the digest)
    assert "DERIVED" in sql
    assert "digest(config_canonical" in sql
