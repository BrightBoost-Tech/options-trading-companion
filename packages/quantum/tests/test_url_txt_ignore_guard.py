"""Regression guard: `url.txt` (an operator-local DSN/URL secret-at-rest) must
stay .gitignored and must never become tracked.

Context (2026-07-20, chore/url-txt-ignore-guard): an untracked ``url.txt`` — a
DSN/URL-shaped secret — sat at the operator-checkout repo root matched by NO
ignore rule, one ``git add`` from being committed. A full history + tracked-file
audit proved ``url.txt`` was NEVER tracked in git history, and that every
credential-SHAPED string in the repo is the security masking/detection tooling
(``packages/quantum/security/masking.py`` regex patterns,
``secrets_audit.py`` placeholder ``example_format`` strings) plus synthetic test
fixtures (AWS's documented ``AKIAIOSFODNN7EXAMPLE`` example key, ``hunter2``,
``SUPER_SECRET_PASSWORD``) — no real leaked secret, no ``.env`` ever committed.
The ``.gitignore`` guard added alongside this test closes the exposure window;
this test locks it so a future ``.gitignore`` edit or a stray ``git add`` cannot
silently regress the protection.

Deliberately tiny and self-contained: it shells out to the repo's own git to
ask the two questions that matter (is the path ignored? is it tracked?). It does
NOT import the module-skipped ``secrets_audit`` scanner (tracked in #766) and it
does NOT build a new scanner — per the Lane G scope.
"""

import subprocess
from pathlib import Path

import pytest


def _repo_root() -> Path:
    """Nearest ancestor holding a ``.git`` entry (dir in a normal checkout, a
    gitdir-pointer file in a worktree — ``exists()`` is true for both)."""
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    pytest.skip("not inside a git checkout (.git not found)")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, OSError):  # pragma: no cover - git absent
        pytest.skip("git executable not available in this environment")


def test_url_txt_is_gitignored():
    """`git check-ignore url.txt` must exit 0 (the path IS matched by an ignore
    rule). Exit 1 means the secret-at-rest guard regressed."""
    root = _repo_root()
    res = _git(root, "check-ignore", "url.txt")
    assert res.returncode == 0, (
        "url.txt is NOT gitignored — the secret-at-rest guard regressed. "
        "Expected a matching rule (e.g. '/url.txt') in .gitignore."
    )


def test_url_txt_is_not_tracked():
    """`url.txt` must never be a tracked path. If it is, a DSN-shaped
    secret-at-rest was committed — rotate credentials and purge history."""
    root = _repo_root()
    # `ls-files --error-unmatch` exits non-zero when the path is NOT tracked,
    # which is the state we require.
    res = _git(root, "ls-files", "--error-unmatch", "url.txt")
    assert res.returncode != 0, (
        "url.txt is TRACKED in git — a DSN/URL secret-at-rest was committed. "
        "Rotate the exposed credential and purge it from history."
    )
