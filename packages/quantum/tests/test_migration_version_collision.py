"""CI linter + audit tests for duplicate migration-version prefixes.

Lane C. Enforces that supabase/migrations/ never grows a NEW duplicate 14-digit
prefix, while permitting the ONE reviewed legacy collision (three 2026-07-23
research/shadow-fleet lanes that shared version 20260723160000, each applied to
production by exact name with an independent receipt). See
scripts/migrations/migration_version_audit.py and
scripts/migrations/legacy_duplicate_version_allowlist.json.

The tests exercise the audit's PUBLIC entrypoints against synthetic migration
dirs (origin-to-top: a duplicate injected on disk must surface as a top-level
violation), plus one live gate over the real repository tree.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts.migrations import migration_version_audit as mva


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write(migrations_dir: Path, name: str, body: str = "SELECT 1;\n") -> Path:
    p = migrations_dir / name
    p.write_text(body, encoding="utf-8")
    return p


def _allowlist_for(version: str, files: list) -> dict:
    """Build an allowlist dict whose file entries carry all required receipt keys."""
    entries = []
    for name, sha in files:
        entries.append(
            {
                "filename": name,
                "sha256": sha,
                "applied_version": "20260723999999",
                "apply_receipt_risk_alert_id": "00000000-0000-0000-0000-000000000000",
                "applied_at": "2026-07-23T00:00:00Z",
                "never_reapply": True,
            }
        )
    return {"collisions": [{"version": version, "files": entries}]}


def _lint(migrations_dir: Path, allowlist: dict):
    files = mva.scan_migrations(migrations_dir)
    return mva.check_new_duplicates(files, allowlist)


# ---------------------------------------------------------------------------
# 1. THE CI GATE — the real repo tree must pass with the shipped allowlist.
# ---------------------------------------------------------------------------
def test_real_migrations_tree_passes_with_shipped_allowlist():
    migrations_dir = mva.default_migrations_dir()
    allowlist = mva.load_allowlist(mva.default_allowlist_path())
    files = mva.scan_migrations(migrations_dir)

    report = mva.audit(files, allowlist, migrations_dir=str(migrations_dir))
    assert report.clean, [
        (v.code, v.filename, v.detail) for v in report.violations
    ]

    # Exactly one duplicate group exists today, and it is the reviewed legacy one.
    groups = mva.find_duplicate_versions(files)
    assert [g.version for g in groups] == ["20260723160000"]
    assert len(groups[0].files) == 3


def test_all_real_migrations_have_canonical_14_digit_prefix():
    files = mva.scan_migrations(mva.default_migrations_dir())
    malformed = [f.filename for f in files if f.malformed]
    assert malformed == [], f"non-canonical migration filenames: {malformed}"


# ---------------------------------------------------------------------------
# 2. new duplicate prefix fails CI
# ---------------------------------------------------------------------------
def test_new_duplicate_prefix_fails(tmp_path):
    m = tmp_path / "migrations"
    m.mkdir()
    _write(m, "20260801000000_alpha.sql", "CREATE TABLE IF NOT EXISTS a();\n")
    _write(m, "20260801000000_beta.sql", "CREATE TABLE IF NOT EXISTS b();\n")

    violations = _lint(m, {"collisions": []})
    assert violations, "a brand-new duplicate prefix must fail the linter"
    assert all(v.code == "UNKNOWN_DUPLICATE" for v in violations)
    assert {v.filename for v in violations} == {
        "20260801000000_alpha.sql",
        "20260801000000_beta.sql",
    }


# ---------------------------------------------------------------------------
# 3. legacy allowlisted collision passes only with exact hashes
# ---------------------------------------------------------------------------
def test_legacy_allowlisted_collision_passes_with_exact_hashes(tmp_path):
    m = tmp_path / "migrations"
    m.mkdir()
    a = _write(m, "20260723160000_one.sql", "CREATE TABLE IF NOT EXISTS t_one();\n")
    b = _write(m, "20260723160000_two.sql", "CREATE TABLE IF NOT EXISTS t_two();\n")

    allowlist = _allowlist_for(
        "20260723160000",
        [
            (a.name, mva.sha256_bytes(a.read_bytes())),
            (b.name, mva.sha256_bytes(b.read_bytes())),
        ],
    )
    assert _lint(m, allowlist) == []


# ---------------------------------------------------------------------------
# 4. hash drift fails
# ---------------------------------------------------------------------------
def test_hash_drift_fails(tmp_path):
    m = tmp_path / "migrations"
    m.mkdir()
    a = _write(m, "20260723160000_one.sql", "CREATE TABLE IF NOT EXISTS t_one();\n")
    b = _write(m, "20260723160000_two.sql", "CREATE TABLE IF NOT EXISTS t_two();\n")

    allowlist = _allowlist_for(
        "20260723160000",
        [
            (a.name, mva.sha256_bytes(a.read_bytes())),
            (b.name, mva.sha256_bytes(b.read_bytes())),
        ],
    )
    # Drift one file's content after pinning the allowlist hash.
    a.write_text("CREATE TABLE IF NOT EXISTS t_one_DRIFTED();\n", encoding="utf-8")

    violations = _lint(m, allowlist)
    drift = [v for v in violations if v.code == "HASH_DRIFT"]
    assert len(drift) == 1
    assert drift[0].filename == "20260723160000_one.sql"


# ---------------------------------------------------------------------------
# 5. missing receipt entry fails
# ---------------------------------------------------------------------------
def test_missing_receipt_entry_fails(tmp_path):
    m = tmp_path / "migrations"
    m.mkdir()
    a = _write(m, "20260723160000_one.sql", "CREATE TABLE IF NOT EXISTS t_one();\n")
    b = _write(m, "20260723160000_two.sql", "CREATE TABLE IF NOT EXISTS t_two();\n")

    allowlist = _allowlist_for(
        "20260723160000",
        [
            (a.name, mva.sha256_bytes(a.read_bytes())),
            (b.name, mva.sha256_bytes(b.read_bytes())),
        ],
    )
    # Strip the durable apply receipt from one entry.
    del allowlist["collisions"][0]["files"][0]["apply_receipt_risk_alert_id"]

    violations = _lint(m, allowlist)
    missing = [v for v in violations if v.code == "MISSING_RECEIPT"]
    assert len(missing) == 1
    assert missing[0].filename == "20260723160000_one.sql"


def test_missing_applied_version_also_fails_receipt_check(tmp_path):
    m = tmp_path / "migrations"
    m.mkdir()
    a = _write(m, "20260723160000_one.sql", "CREATE TABLE IF NOT EXISTS t_one();\n")
    b = _write(m, "20260723160000_two.sql", "CREATE TABLE IF NOT EXISTS t_two();\n")
    allowlist = _allowlist_for(
        "20260723160000",
        [
            (a.name, mva.sha256_bytes(a.read_bytes())),
            (b.name, mva.sha256_bytes(b.read_bytes())),
        ],
    )
    allowlist["collisions"][0]["files"][1]["applied_version"] = None
    violations = _lint(m, allowlist)
    assert any(
        v.code == "MISSING_RECEIPT" and v.filename == "20260723160000_two.sql"
        for v in violations
    )


# ---------------------------------------------------------------------------
# 6. unknown duplicate fails (allowlist populated, but for a DIFFERENT version)
# ---------------------------------------------------------------------------
def test_unknown_duplicate_fails(tmp_path):
    m = tmp_path / "migrations"
    m.mkdir()
    _write(m, "20260901000000_x.sql", "CREATE TABLE IF NOT EXISTS x();\n")
    _write(m, "20260901000000_y.sql", "CREATE TABLE IF NOT EXISTS y();\n")
    # Allowlist knows only some OTHER version, so this duplicate is "unknown".
    allowlist = _allowlist_for("20260723160000", [("foo.sql", "deadbeef")])

    violations = _lint(m, allowlist)
    assert violations
    assert all(v.code == "UNKNOWN_DUPLICATE" for v in violations)
    assert all(v.version == "20260901000000" for v in violations)


def test_partial_allowlist_group_flags_unlisted_sibling(tmp_path):
    """A file sharing an allowlisted version but not itself listed must fail."""
    m = tmp_path / "migrations"
    m.mkdir()
    a = _write(m, "20260723160000_one.sql", "CREATE TABLE IF NOT EXISTS t_one();\n")
    b = _write(m, "20260723160000_two.sql", "CREATE TABLE IF NOT EXISTS t_two();\n")
    # Only 'one' is allowlisted; 'two' shares the version but is unlisted.
    allowlist = _allowlist_for(
        "20260723160000", [(a.name, mva.sha256_bytes(a.read_bytes()))]
    )
    violations = _lint(m, allowlist)
    assert any(
        v.code == "UNKNOWN_DUPLICATE" and v.filename == "20260723160000_two.sql"
        for v in violations
    )


def test_missing_allowlisted_file_fails(tmp_path):
    """An allowlisted collision file deleted/renamed on disk must fail."""
    m = tmp_path / "migrations"
    m.mkdir()
    a = _write(m, "20260723160000_one.sql", "CREATE TABLE IF NOT EXISTS t_one();\n")
    b = _write(m, "20260723160000_two.sql", "CREATE TABLE IF NOT EXISTS t_two();\n")
    allowlist = _allowlist_for(
        "20260723160000",
        [
            (a.name, mva.sha256_bytes(a.read_bytes())),
            (b.name, mva.sha256_bytes(b.read_bytes())),
            ("20260723160000_three.sql", "cafebabe"),  # allowlisted but not on disk
        ],
    )
    violations = _lint(m, allowlist)
    assert any(
        v.code == "MISSING_FILE" and v.filename == "20260723160000_three.sql"
        for v in violations
    )


# ---------------------------------------------------------------------------
# 7. unique migration passes
# ---------------------------------------------------------------------------
def test_unique_migrations_pass(tmp_path):
    m = tmp_path / "migrations"
    m.mkdir()
    _write(m, "20260101000000_a.sql")
    _write(m, "20260102000000_b.sql")
    _write(m, "20260103000000_c.sql")

    files = mva.scan_migrations(m)
    assert mva.find_duplicate_versions(files) == []
    assert _lint(m, {"collisions": []}) == []


# ---------------------------------------------------------------------------
# 8. no production DB write in audit mode (assert offline)
# ---------------------------------------------------------------------------
_FORBIDDEN_IMPORT_ROOTS = {
    "supabase",
    "postgrest",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "sqlalchemy",
    "requests",
    "httpx",
    "aiohttp",
    "urllib",
    "socket",
    "http",
    "boto3",
}


def _imported_roots(source: str) -> set:
    tree = ast.parse(source)
    roots: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_audit_module_imports_no_db_or_network():
    src = Path(mva.__file__).read_text(encoding="utf-8")
    roots = _imported_roots(src)
    leaked = roots & _FORBIDDEN_IMPORT_ROOTS
    assert not leaked, f"audit module imports forbidden network/db modules: {leaked}"
    assert mva.OFFLINE is True


def test_audit_with_remote_snapshot_is_pure_and_offline(tmp_path):
    """Providing a remote snapshot classifies state from the dict alone — no IO."""
    m = tmp_path / "migrations"
    m.mkdir()
    a = _write(m, "20260723160000_one.sql", "CREATE TABLE IF NOT EXISTS t_one();\n")
    b = _write(m, "20260723160000_two.sql", "CREATE TABLE IF NOT EXISTS t_two();\n")
    allowlist = _allowlist_for(
        "20260723160000",
        [
            (a.name, mva.sha256_bytes(a.read_bytes())),
            (b.name, mva.sha256_bytes(b.read_bytes())),
        ],
    )
    snapshot = {
        "schema_migrations": [
            {"version": "20260723232856", "name": "20260723160000_one"},
            # 'two' intentionally absent -> classified untracked, still offline.
        ]
    }
    files = mva.scan_migrations(m)
    report = mva.audit(
        files, allowlist, migrations_dir=str(m), remote_snapshot=snapshot
    )
    states = {r.filename: r.remote_state for r in report.file_rows}
    assert states["20260723160000_one.sql"] == "applied"
    assert states["20260723160000_two.sql"] == "untracked"
    assert report.offline is True


def test_audit_without_snapshot_reports_unknown_offline(tmp_path):
    m = tmp_path / "migrations"
    m.mkdir()
    a = _write(m, "20260723160000_one.sql", "CREATE TABLE IF NOT EXISTS t_one();\n")
    b = _write(m, "20260723160000_two.sql", "CREATE TABLE IF NOT EXISTS t_two();\n")
    allowlist = _allowlist_for(
        "20260723160000",
        [
            (a.name, mva.sha256_bytes(a.read_bytes())),
            (b.name, mva.sha256_bytes(b.read_bytes())),
        ],
    )
    files = mva.scan_migrations(m)
    report = mva.audit(files, allowlist, migrations_dir=str(m))
    assert {r.remote_state for r in report.file_rows} == {"unknown_offline"}


# ---------------------------------------------------------------------------
# 9. FRESH-INSTALL PARITY — colliding files create disjoint objects, so a
#    name-based bootstrap creates every required object exactly once.
# ---------------------------------------------------------------------------
def test_collision_files_create_disjoint_objects():
    migrations_dir = mva.default_migrations_dir()
    files = mva.scan_migrations(migrations_dir)
    groups = mva.find_duplicate_versions(files)
    assert groups, "expected the reviewed legacy collision to exist"

    # No two files in any collision group create the same table.
    parity_violations = mva.check_collision_object_parity(groups, migrations_dir)
    assert parity_violations == [], [
        (v.filename, v.detail) for v in parity_violations
    ]

    # And the specific 2026-07-23 group creates exactly its five known tables.
    group = next(g for g in groups if g.version == "20260723160000")
    union: set = set()
    per_file = {}
    for f in group.files:
        tables = mva.extract_created_tables(
            (migrations_dir / f.filename).read_text(encoding="utf-8")
        )
        per_file[f.filename] = tables
        union |= tables
    assert union == {
        "td_scan_envelopes",
        "td_scan_scores",
        "regime_v4_comparisons",
        "fleet_policy_decision_runs",
        "fleet_policy_decisions",
    }
    # Pairwise disjoint (each object created by exactly one file).
    all_lists = [t for tables in per_file.values() for t in tables]
    assert len(all_lists) == len(set(all_lists)) == 5


def test_object_parity_violation_detected_on_overlap(tmp_path):
    """If two colliding files DID create the same table, parity must flag it."""
    m = tmp_path / "migrations"
    m.mkdir()
    _write(m, "20260723160000_one.sql", "CREATE TABLE IF NOT EXISTS shared_t (id int);\n")
    _write(m, "20260723160000_two.sql", "CREATE TABLE IF NOT EXISTS shared_t (id int);\n")
    files = mva.scan_migrations(m)
    groups = mva.find_duplicate_versions(files)
    violations = mva.check_collision_object_parity(groups, m)
    assert any(v.code == "OBJECT_PARITY" for v in violations)


# ---------------------------------------------------------------------------
# parse_version mirrors the Supabase CLI's leading-digit-run identity.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name,expected",
    [
        ("20260723160000_td_scan_observe_tables.sql", "20260723160000"),
        ("20240101000000_initial_schema.sql", "20240101000000"),
        ("not_a_migration.sql", None),
        ("README.md", None),
        ("20260723160000_a.txt", None),  # non-.sql
    ],
)
def test_parse_version(name, expected):
    assert mva.parse_version(name) == expected


# ---------------------------------------------------------------------------
# CLI entrypoint returns the right exit codes.
# ---------------------------------------------------------------------------
def test_cli_main_clean_on_real_tree_returns_zero(capsys):
    rc = mva.main([])
    capsys.readouterr()
    assert rc == 0


def test_cli_main_json_is_valid_and_clean(capsys):
    rc = mva.main(["--format", "json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["clean"] is True
    assert payload["offline"] is True
    assert any(g["version"] == "20260723160000" for g in payload["collision_groups"])
