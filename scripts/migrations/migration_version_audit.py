#!/usr/bin/env python3
"""Deterministic, offline migration-version collision audit + linter (stdlib-only).

WHY THIS EXISTS
---------------
The Supabase CLI parses a local migration's identity from the *leading digit run*
of the filename (everything before the first ``_``) - NOT from the file name as a
whole. Three files that share the same 14-digit prefix therefore collapse to a
single CLI "version". VERIFIED-RUNTIME (supabase CLI 2.72.7,
``supabase migration list --local``): the three ``20260723160000_*`` files render
as the identical version ``20260723160000`` three times, and the local
``supabase_migrations.schema_migrations`` table's PRIMARY KEY is ``version`` alone
- so a CLI bootstrap (``db push`` / ``db reset``) cannot record all three (PK
collision). Production is unaffected because this repo applies migrations by exact
NAME via ``mcp__supabase__apply_migration`` (see docs/migration_procedure.md), which
assigns each file its own apply-timestamp ``version`` and stores the file name in
``name``. So the collision hazard is strictly REPO-SIDE / CLI-bootstrap.

WHAT THIS MODULE DOES
---------------------
* Scans flat, lowercase ``*.sql`` files directly under ``supabase/migrations/``
  (non-recursive, mirroring the Supabase CLI's discovery) and parses each file's
  CLI version.
* Detects duplicate versions (two+ files sharing one parsed version).
* Fingerprints every file with SHA-256 over CRLF->LF-normalized bytes, so the
  digest is identical on Windows (``core.autocrlf`` CRLF checkout) and Linux CI
  (LF checkout) alike. The allowlist pins are on this normalized-LF basis.
* Reconciles duplicates against a reviewed *legacy allowlist* of PROVEN collisions,
  each pinned to exact hashes + an apply receipt + a never-reapply marker.
* Optionally compares against an OFFLINE JSON snapshot of remote history
  (``schema_migrations`` rows) to classify applied / untracked state. It NEVER
  makes a live DB or network call - CI safety is structural (stdlib-only imports).

The linter gate (``check_new_duplicates``) fails on:
  * a NEW duplicate version not present in the allowlist ("unknown duplicate");
  * an allowlisted collision whose on-disk file hash drifted from the pinned hash;
  * an allowlisted collision file that is missing on disk;
  * a malformed allowlist entry (missing receipt/applied_version - "missing receipt").
It PASSES a duplicate only when every file in the group is allowlisted with an
exact hash match and a durable apply receipt.

Run:
    python -m scripts.migrations.migration_version_audit --format text
    python -m scripts.migrations.migration_version_audit \
        --remote-snapshot scripts/migrations/remote_history_snapshot.example.json \
        --format json

Exit code 0 = clean; 1 = collision-policy violation; 2 = usage/IO error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Offline guarantee. This module imports ONLY the Python standard library. No
# supabase / psycopg / requests / httpx / socket-level client is imported, so the
# audit provably cannot touch a live database. test_migration_version_collision.py
# asserts this by AST-scanning this file's imports.
# ---------------------------------------------------------------------------
OFFLINE = True

# The repo convention: a 14-digit UTC timestamp prefix, then ``_<slug>.sql``.
_FULL_NAME_RE = re.compile(r"^(?P<version>\d+)_(?P<slug>.+)\.sql$")
_CANONICAL_VERSION_LEN = 14


@dataclass(frozen=True)
class MigrationFile:
    """One on-disk migration file and its parsed identity."""

    filename: str
    version: Optional[str]  # leading digit-run before first '_'; None if malformed
    slug: Optional[str]
    sha256: str
    size_bytes: int
    malformed: bool = False


@dataclass
class CollisionGroup:
    """A set of 2+ files that the CLI would treat as one version."""

    version: str
    files: List[MigrationFile]


@dataclass
class Violation:
    code: str  # e.g. UNKNOWN_DUPLICATE, HASH_DRIFT, MISSING_FILE, MISSING_RECEIPT
    version: str
    filename: Optional[str]
    detail: str


@dataclass
class FileAuditRow:
    filename: str
    version: str
    sha256: str
    allowlisted: bool
    hash_matches_allowlist: Optional[bool]
    applied_version: Optional[str]  # from allowlist / remote snapshot
    remote_state: str  # applied | untracked | unknown_offline
    recommended_action: str


@dataclass
class AuditReport:
    migrations_dir: str
    file_count: int
    collision_groups: List[CollisionGroup] = field(default_factory=list)
    violations: List[Violation] = field(default_factory=list)
    file_rows: List[FileAuditRow] = field(default_factory=list)
    offline: bool = True
    remote_snapshot_used: bool = False

    @property
    def clean(self) -> bool:
        return not self.violations


# ---------------------------------------------------------------------------
# Parsing / scanning
# ---------------------------------------------------------------------------
def parse_version(filename: str) -> Optional[str]:
    """Return the CLI-parsed version (leading digit-run before first ``_``).

    Mirrors the Supabase CLI, which keys a local migration on the leading numeric
    portion of the filename. Returns None if the filename does not match the
    ``<digits>_<slug>.sql`` shape.
    """
    m = _FULL_NAME_RE.match(filename)
    if not m:
        return None
    return m.group("version")


def is_canonical_version(version: Optional[str]) -> bool:
    return bool(version) and len(version) == _CANONICAL_VERSION_LEN and version.isdigit()


def normalize_line_endings(data: bytes) -> bytes:
    """Canonicalize CRLF -> LF so a file's hash is identical on every platform.

    Git stores blobs LF-normalized; a checkout on a machine with
    ``core.autocrlf=true`` (Windows) smudges them to CRLF in the working tree,
    while Linux CI (ubuntu-latest, actions/checkout default) checks out LF. Hashing
    the raw working-tree bytes therefore yields platform-dependent digests. Hashing
    CRLF->LF-normalized bytes yields the SAME digest as the LF git blob CI sees,
    with no .gitattributes dependency.
    """
    return data.replace(b"\r\n", b"\n")


def sha256_normalized(data: bytes) -> str:
    """SHA-256 over CRLF->LF-normalized bytes (platform-independent).

    This is the canonical hashing basis for the allowlist pins.
    """
    return hashlib.sha256(normalize_line_endings(data)).hexdigest()


def scan_migrations(migrations_dir: Path) -> List[MigrationFile]:
    """Fingerprint every migration in ``migrations_dir`` (sorted by name).

    Scan scope: flat, lowercase ``*.sql`` files DIRECTLY under
    ``supabase/migrations/`` (non-recursive), mirroring the Supabase CLI's own
    migration discovery. Subdirectories (e.g. the gated ``pg/`` real-pg suite) and
    non-``.sql`` files are ignored. Hash and size are on the CRLF->LF-normalized
    basis so they are identical regardless of checkout smudging.
    """
    files: List[MigrationFile] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        normalized = normalize_line_endings(path.read_bytes())
        version = parse_version(path.name)
        m = _FULL_NAME_RE.match(path.name)
        slug = m.group("slug") if m else None
        malformed = version is None or not is_canonical_version(version)
        files.append(
            MigrationFile(
                filename=path.name,
                version=version,
                slug=slug,
                sha256=sha256_normalized(normalized),
                size_bytes=len(normalized),
                malformed=malformed,
            )
        )
    return files


def find_duplicate_versions(files: List[MigrationFile]) -> List[CollisionGroup]:
    """Group files by parsed version; return only versioned groups of size >= 2."""
    by_version: Dict[str, List[MigrationFile]] = {}
    for f in files:
        if f.version is None:
            continue
        by_version.setdefault(f.version, []).append(f)
    groups = [
        CollisionGroup(version=v, files=sorted(fs, key=lambda x: x.filename))
        for v, fs in by_version.items()
        if len(fs) >= 2
    ]
    return sorted(groups, key=lambda g: g.version)


# ---------------------------------------------------------------------------
# Object parity (two colliding files must not CREATE the same relation)
# ---------------------------------------------------------------------------
_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r'(?:"?(?P<schema>[a-zA-Z_][\w]*)"?\.)?'
    r'"?(?P<name>[a-zA-Z_][\w]*)"?',
    re.IGNORECASE,
)


def extract_created_tables(sql: str) -> set:
    """Return the set of table identifiers a migration CREATEs.

    Used to prove object parity: two files that collide on version must create
    disjoint relations, so that applying each exactly once (the repo's name-based
    bootstrap) creates every object exactly once. Comment lines are stripped first
    so a table named only in an explanatory ``--`` comment is not counted.
    """
    code_lines = [ln for ln in sql.splitlines() if not ln.lstrip().startswith("--")]
    code = "\n".join(code_lines)
    return {m.group("name") for m in _CREATE_TABLE_RE.finditer(code)}


def check_collision_object_parity(
    groups: List[CollisionGroup], migrations_dir: Path
) -> List[Violation]:
    """Flag any two files in a collision group that CREATE the same table.

    A shared version is tolerable only because the files are disjoint; two colliding
    files creating the same relation is a real double-apply hazard, not cosmetic.
    """
    violations: List[Violation] = []
    for group in groups:
        seen: Dict[str, str] = {}  # table -> first filename that created it
        for f in group.files:
            sql = (migrations_dir / f.filename).read_text(encoding="utf-8")
            for table in extract_created_tables(sql):
                if table in seen and seen[table] != f.filename:
                    violations.append(
                        Violation(
                            code="OBJECT_PARITY",
                            version=group.version,
                            filename=f.filename,
                            detail=(
                                f"table '{table}' is CREATEd by both {seen[table]} and "
                                f"{f.filename}, which share version {group.version}; "
                                f"colliding files must create disjoint objects."
                            ),
                        )
                    )
                else:
                    seen[table] = f.filename
    return violations


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------
# Required keys on every allowlisted collision file. Absence of a receipt or
# applied_version is a MISSING_RECEIPT violation (an allowlist entry must prove the
# file is durably applied and must never be reapplied).
_REQUIRED_FILE_KEYS = (
    "filename",
    "sha256",
    "applied_version",
    "apply_receipt_risk_alert_id",
    "never_reapply",
)


def load_allowlist(path: Path) -> dict:
    if not path.exists():
        return {"collisions": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _allowlist_index(allowlist: dict) -> Dict[str, Dict[str, dict]]:
    """version -> {filename -> file_entry}."""
    index: Dict[str, Dict[str, dict]] = {}
    for group in allowlist.get("collisions", []):
        version = group.get("version")
        if not version:
            continue
        index.setdefault(version, {})
        for fe in group.get("files", []):
            fn = fe.get("filename")
            if fn:
                index[version][fn] = fe
    return index


def _entry_missing_receipt(entry: dict) -> Optional[str]:
    """Return a human reason if the allowlist entry lacks required receipt fields."""
    for key in _REQUIRED_FILE_KEYS:
        if key not in entry or entry[key] in (None, ""):
            return f"allowlist entry missing required field '{key}'"
    if entry.get("never_reapply") is not True:
        return "allowlist entry must set never_reapply=true"
    return None


# ---------------------------------------------------------------------------
# Core reconciliation / linter
# ---------------------------------------------------------------------------
def check_new_duplicates(
    files: List[MigrationFile], allowlist: dict
) -> List[Violation]:
    """The CI gate. Return violations; empty list == PASS."""
    violations: List[Violation] = []
    index = _allowlist_index(allowlist)
    groups = find_duplicate_versions(files)

    for group in groups:
        version = group.version
        allowed_files = index.get(version)
        if allowed_files is None:
            # Whole duplicate version is unknown to the allowlist.
            for f in group.files:
                violations.append(
                    Violation(
                        code="UNKNOWN_DUPLICATE",
                        version=version,
                        filename=f.filename,
                        detail=(
                            f"version {version} is shared by {len(group.files)} files "
                            f"but is not in the reviewed legacy allowlist. A NEW "
                            f"duplicate prefix must be renamed to a unique prefix "
                            f"BEFORE it is applied (never rename an applied file)."
                        ),
                    )
                )
            continue

        # Every file in the on-disk group must be allowlisted with a matching hash.
        for f in group.files:
            entry = allowed_files.get(f.filename)
            if entry is None:
                violations.append(
                    Violation(
                        code="UNKNOWN_DUPLICATE",
                        version=version,
                        filename=f.filename,
                        detail=(
                            f"{f.filename} shares allowlisted version {version} but is "
                            f"not itself an allowlisted file in that group."
                        ),
                    )
                )
                continue
            missing = _entry_missing_receipt(entry)
            if missing:
                violations.append(
                    Violation(
                        code="MISSING_RECEIPT",
                        version=version,
                        filename=f.filename,
                        detail=missing,
                    )
                )
                continue
            if entry.get("sha256", "").lower() != f.sha256.lower():
                violations.append(
                    Violation(
                        code="HASH_DRIFT",
                        version=version,
                        filename=f.filename,
                        detail=(
                            f"on-disk sha256 {f.sha256} != allowlisted "
                            f"{entry.get('sha256')}. An applied migration file must "
                            f"never change content; reconcile before proceeding."
                        ),
                    )
                )

        # Every allowlisted file for this version must still exist on disk.
        on_disk = {f.filename for f in group.files}
        for fn, entry in allowed_files.items():
            if fn not in on_disk:
                violations.append(
                    Violation(
                        code="MISSING_FILE",
                        version=version,
                        filename=fn,
                        detail=(
                            f"allowlisted collision file {fn} is missing on disk; an "
                            f"applied migration must not be deleted/renamed."
                        ),
                    )
                )

    return violations


def _remote_names(remote_snapshot: Optional[dict]) -> Optional[set]:
    if remote_snapshot is None:
        return None
    return {row.get("name") for row in remote_snapshot.get("schema_migrations", [])}


def audit(
    files: List[MigrationFile],
    allowlist: dict,
    migrations_dir: str,
    remote_snapshot: Optional[dict] = None,
) -> AuditReport:
    """Produce the full deterministic audit report."""
    groups = find_duplicate_versions(files)
    violations = check_new_duplicates(files, allowlist)
    violations += check_collision_object_parity(groups, Path(migrations_dir))
    index = _allowlist_index(allowlist)
    remote_names = _remote_names(remote_snapshot)

    rows: List[FileAuditRow] = []
    for group in groups:
        allowed = index.get(group.version, {})
        for f in group.files:
            entry = allowed.get(f.filename)
            allowlisted = entry is not None
            hash_matches = (
                (entry.get("sha256", "").lower() == f.sha256.lower())
                if entry
                else None
            )
            applied_version = entry.get("applied_version") if entry else None
            # Production tracks by NAME. Snapshot name is the file name WITHOUT .sql.
            expected_name = f.filename[:-4] if f.filename.endswith(".sql") else f.filename
            if remote_names is None:
                remote_state = "unknown_offline"
            elif expected_name in remote_names:
                remote_state = "applied"
            else:
                remote_state = "untracked"

            if allowlisted and hash_matches and _entry_missing_receipt(entry) is None:
                action = (
                    "NONE - proven legacy collision; NEVER reapply, rename, or squash. "
                    "Applied by exact name; production has no version collision."
                )
            elif not allowlisted:
                action = (
                    "REVIEW - if unapplied, rename to a unique 14-digit prefix before "
                    "applying. If applied, add a reviewed allowlist entry with hash + "
                    "receipt; never rename the applied file."
                )
            elif hash_matches is False:
                action = "RECONCILE - file content drifted from the pinned hash."
            else:
                action = "FIX ALLOWLIST - entry is missing a durable apply receipt."

            rows.append(
                FileAuditRow(
                    filename=f.filename,
                    version=group.version,
                    sha256=f.sha256,
                    allowlisted=allowlisted,
                    hash_matches_allowlist=hash_matches,
                    applied_version=applied_version,
                    remote_state=remote_state,
                    recommended_action=action,
                )
            )

    return AuditReport(
        migrations_dir=migrations_dir,
        file_count=len(files),
        collision_groups=groups,
        violations=violations,
        file_rows=rows,
        offline=True,
        remote_snapshot_used=remote_snapshot is not None,
    )


# ---------------------------------------------------------------------------
# Paths / CLI
# ---------------------------------------------------------------------------
def find_repo_root(start: Optional[Path] = None) -> Path:
    """Walk up from this file (or ``start``) until ``supabase/migrations`` exists."""
    here = (start or Path(__file__)).resolve()
    for parent in [here, *here.parents]:
        if (parent / "supabase" / "migrations").is_dir():
            return parent
    raise FileNotFoundError("could not locate supabase/migrations from " + str(here))


def default_migrations_dir() -> Path:
    return find_repo_root() / "supabase" / "migrations"


def default_allowlist_path() -> Path:
    return (
        find_repo_root()
        / "scripts"
        / "migrations"
        / "legacy_duplicate_version_allowlist.json"
    )


def _report_to_dict(report: AuditReport) -> dict:
    return {
        "migrations_dir": report.migrations_dir,
        "file_count": report.file_count,
        "offline": report.offline,
        "remote_snapshot_used": report.remote_snapshot_used,
        "clean": report.clean,
        "collision_groups": [
            {
                "version": g.version,
                "files": [f.filename for f in g.files],
            }
            for g in report.collision_groups
        ],
        "violations": [asdict(v) for v in report.violations],
        "file_rows": [asdict(r) for r in report.file_rows],
    }


def _format_text(report: AuditReport) -> str:
    lines: List[str] = []
    lines.append("Migration version-collision audit (OFFLINE, stdlib-only)")
    lines.append(f"  migrations_dir : {report.migrations_dir}")
    lines.append(f"  files scanned  : {report.file_count}")
    lines.append(
        f"  remote source  : "
        + ("offline JSON snapshot" if report.remote_snapshot_used else "none (offline)")
    )
    lines.append("")
    if not report.collision_groups:
        lines.append("Duplicate versions : NONE")
    else:
        lines.append(f"Duplicate versions : {len(report.collision_groups)}")
        for g in report.collision_groups:
            lines.append(f"  [{g.version}] ({len(g.files)} files)")
            for r in report.file_rows:
                if r.version != g.version:
                    continue
                mark = "OK " if (r.allowlisted and r.hash_matches_allowlist) else "!! "
                lines.append(
                    f"    {mark}{r.filename}"
                    f"  applied_version={r.applied_version or '-'}"
                    f"  remote={r.remote_state}"
                )
                lines.append(f"        sha256 {r.sha256}")
                lines.append(f"        action {r.recommended_action}")
    lines.append("")
    if report.clean:
        lines.append("RESULT: CLEAN - no collision-policy violations.")
    else:
        lines.append(f"RESULT: {len(report.violations)} VIOLATION(S):")
        for v in report.violations:
            lines.append(f"  - {v.code} [{v.version}] {v.filename or ''}: {v.detail}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic offline audit + linter for duplicate migration versions. "
            "Never performs a live DB or network call."
        )
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=None,
        help="Path to supabase/migrations (default: auto-detected repo root).",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=None,
        help="Path to the reviewed legacy duplicate-version allowlist JSON.",
    )
    parser.add_argument(
        "--remote-snapshot",
        type=Path,
        default=None,
        help=(
            "Optional OFFLINE JSON snapshot of schema_migrations "
            "({'schema_migrations':[{'version','name'},...]}). Read from disk only; "
            "never a live DB call."
        ),
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    try:
        migrations_dir = args.migrations_dir or default_migrations_dir()
        allowlist_path = args.allowlist or default_allowlist_path()
        if not migrations_dir.is_dir():
            print(f"error: migrations dir not found: {migrations_dir}", file=sys.stderr)
            return 2
        allowlist = load_allowlist(allowlist_path)
        remote_snapshot = (
            json.loads(args.remote_snapshot.read_text(encoding="utf-8"))
            if args.remote_snapshot
            else None
        )
    except (OSError, json.JSONDecodeError) as exc:  # usage / IO error
        print(f"error: {exc}", file=sys.stderr)
        return 2

    files = scan_migrations(migrations_dir)
    report = audit(
        files,
        allowlist,
        migrations_dir=str(migrations_dir),
        remote_snapshot=remote_snapshot,
    )

    if args.format == "json":
        print(json.dumps(_report_to_dict(report), indent=2))
    else:
        print(_format_text(report))

    return 0 if report.clean else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
