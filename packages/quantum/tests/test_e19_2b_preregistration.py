"""Immutability contract for the E19-2B preregistered analysis protocol.

The protocol doc (docs/specs/e19_2b_preregistered_protocol.md) is FROZEN once
merged: its byte content is pinned by the SHA-256 constant below. Changing the
doc changes this hash and FAILS this test — a deliberate, reviewable diff in the
SAME commit (new hash + new PROTOCOL_VERSION) is the only sanctioned way to
alter a frozen preregistration. This is preregistration in the scientific sense:
the analysis plan cannot be silently reshaped after the data is seen.

#1126-safe by construction: this test hashes the REAL doc file on disk — it does
not reimplement, paraphrase, or re-derive the protocol content. The wired
artifact (the file) is exercised directly; a green test here is a green closure
on the actual frozen bytes, not on a copy.

Cross-platform note: the repo sets core.autocrlf=true and ships no
.gitattributes, so a Windows checkout materializes CRLF while git stores (and
Linux CI checks out) LF. We normalize CRLF->LF before hashing so the pin is an
exact-CONTENT lock that is identical on every platform. The pinned value is the
LF-normalized SHA-256.
"""

import hashlib
from pathlib import Path

# repo_root/packages/quantum/tests/<this file>
# parents: [0]=tests [1]=quantum [2]=packages [3]=repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_DOC = _REPO_ROOT / "docs" / "specs" / "e19_2b_preregistered_protocol.md"

# The frozen protocol's LF-normalized content hash. To change the protocol:
# re-version it, then update this constant in the SAME reviewed commit.
FROZEN_PROTOCOL_SHA256 = (
    "45dbf257f0a8336dbc48c016fd4e4c7c2a9d429d67674ebcb381c9e884567587"
)

PROTOCOL_VERSION = "e19_2b_protocol_v1"


def _normalized_bytes() -> bytes:
    """Read the doc and normalize CRLF/CR -> LF so the hash is EOL-independent
    (exact-content, platform-independent)."""
    raw = PROTOCOL_DOC.read_bytes()
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _text() -> str:
    return _normalized_bytes().decode("utf-8")


def test_protocol_doc_exists():
    assert PROTOCOL_DOC.is_file(), f"missing frozen protocol: {PROTOCOL_DOC}"


def test_protocol_doc_frozen_hash():
    """THE immutability pin. Any byte change to the frozen protocol fails here."""
    actual = hashlib.sha256(_normalized_bytes()).hexdigest()
    assert actual == FROZEN_PROTOCOL_SHA256, (
        "E19-2B preregistered protocol changed but its frozen hash was not "
        "updated. A frozen preregistration may only change via a deliberate "
        "re-version: bump PROTOCOL_VERSION in the doc AND update "
        "FROZEN_PROTOCOL_SHA256 in this test, in one reviewed commit.\n"
        f"  expected {FROZEN_PROTOCOL_SHA256}\n"
        f"  actual   {actual}"
    )


def test_protocol_version_matches_pin():
    """The version string in the doc and the test move together."""
    assert f"PROTOCOL_VERSION:   {PROTOCOL_VERSION}" in _text()


# ---------------------------------------------------------------------------
# Load-bearing semantic invariants. The whole-file hash already pins these; the
# asserts below make the "someone regenerated the hash without reading" failure
# mode visible at review time by naming the load-bearing clauses explicitly.
# ---------------------------------------------------------------------------


def test_execution_remains_blocked():
    text = _text()
    assert "EXECUTION_STATUS:   BLOCKED" in text
    assert "EXECUTE_E19_2B:      false" in text


def test_minimum_source_events_undefined_and_owner_packet_present():
    text = _text()
    # The minimum distinct source-event count is NOT invented; execution stays
    # blocked on it and an owner packet states the missing number.
    assert "UNDEFINED in E19 doctrine" in text
    assert "OWNER PACKET" in text
    assert "MINIMUM_DISTINCT_SOURCE_EVENTS" in text


def test_promotion_prohibition_present():
    assert "E19-2B NEVER promotes anything by itself." in _text()


def test_decision_event_unit_basis_pinned():
    text = _text()
    # The experimental unit is the immutable decision event, not account rows.
    assert "decision_event_id" in text
    assert 'DECISION_EVENT_BASIS = "source_suggestion_id"' in text


def test_fleet_epoch_identity_pinned():
    text = _text()
    assert "small_tier_v1" in text
    assert "legacy_100k" in text
