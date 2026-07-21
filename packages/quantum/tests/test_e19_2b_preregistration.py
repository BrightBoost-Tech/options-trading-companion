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
    "50e7e237436f1bc43d9679c1081eb1e8218048640fb1b325885fd2cf0bc3b76c"
)

PROTOCOL_VERSION = "e19_2b_protocol_v2"

# Arm B (the 50 fleet policies) is pinned by CONTENT in v2 after #1279 merged.
# These are the two upstream pins carried in §12 of the frozen doc.
FLEET_MANIFEST_SHA256 = (
    "5cb76f9981ee12a34204dec63368c918de802f71a99f5766410aa34638d8922c"
)
FLEET_CONFIG_HASH_SET_FINGERPRINT = (
    "18766a1e882e36a46d708add8d3e5c258ea117607954210a8d142fc8844a9a39"
)

# ---------------------------------------------------------------------------
# v3 re-freeze (2026-07-20): the §7 minimum is DEFINED = 8 (owner-ratified
# 2026-07-19, owner-packet-3). v3 is a NEW versioned artifact ALONGSIDE the
# immutable v2 file — v2 above is preserved byte-for-byte (its pin, version, and
# every v2 test are UNCHANGED). Both hashes are pinned; a change to EITHER fails.
# ---------------------------------------------------------------------------
PROTOCOL_DOC_V3 = (
    _REPO_ROOT / "docs" / "specs" / "e19_2b_preregistered_protocol_v3.md"
)

# The frozen v3 protocol's LF-normalized content hash. THE v3 drift lock.
FROZEN_PROTOCOL_V3_SHA256 = (
    "cfdcfc9e7fc7c4d1fd56a5b3ec98d910c5093c2d8e39e4ac7121c51a847903c6"
)

PROTOCOL_VERSION_V3 = "e19_2b_protocol_v3"

# The one number v3 defines (owner-packet-3, RATIFIED). Nothing else changed.
MINIMUM_DISTINCT_SOURCE_EVENTS_V3 = 8

# Arm B is UNCHANGED in v3 — the same manifest + fingerprint are carried
# verbatim. (Re-verified at the v3 authoring base: both reproduce identically.)
FLEET_MANIFEST_SHA256_V3 = FLEET_MANIFEST_SHA256
FLEET_CONFIG_HASH_SET_FINGERPRINT_V3 = FLEET_CONFIG_HASH_SET_FINGERPRINT


def _normalized_bytes() -> bytes:
    """Read the doc and normalize CRLF/CR -> LF so the hash is EOL-independent
    (exact-content, platform-independent)."""
    raw = PROTOCOL_DOC.read_bytes()
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _text() -> str:
    return _normalized_bytes().decode("utf-8")


def _normalized_bytes_v3() -> bytes:
    """LF-normalized bytes of the frozen v3 protocol (same convention as v2)."""
    raw = PROTOCOL_DOC_V3.read_bytes()
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _text_v3() -> str:
    return _normalized_bytes_v3().decode("utf-8")


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


def test_arm_b_pinned_by_content():
    """v2: arm B (the 50 fleet policies) is pinned by CONTENT — the manifest
    file hash and the config-hash-set fingerprint — not by SHAPE. The former
    'NOT YET PINNABLE' PENDING block must be gone."""
    text = _text()
    assert FLEET_MANIFEST_SHA256 in text
    assert FLEET_CONFIG_HASH_SET_FINGERPRINT in text
    assert "fleet_policy_design_50.md" in text
    assert "NOT YET PINNABLE" not in text


# ===========================================================================
# v3 re-freeze — the §7 minimum is DEFINED = 8. v3 is a NEW frozen artifact
# alongside the immutable v2 file. These are the v3 drift locks + the load-
# bearing semantic invariants + the cross-version guards proving v2 is
# preserved. Each mirrors its v2 counterpart so a change to EITHER version's
# frozen bytes fails.
# ===========================================================================


def test_v3_protocol_doc_exists():
    assert PROTOCOL_DOC_V3.is_file(), f"missing frozen v3 protocol: {PROTOCOL_DOC_V3}"


def test_v3_protocol_doc_frozen_hash():
    """THE v3 immutability pin. Any byte change to the frozen v3 protocol fails
    here — the same re-version discipline that governs v2."""
    actual = hashlib.sha256(_normalized_bytes_v3()).hexdigest()
    assert actual == FROZEN_PROTOCOL_V3_SHA256, (
        "E19-2B preregistered protocol v3 changed but its frozen hash was not "
        "updated. A frozen preregistration may only change via a deliberate "
        "re-version: bump PROTOCOL_VERSION in the doc AND update "
        "FROZEN_PROTOCOL_V3_SHA256 in this test, in one reviewed commit.\n"
        f"  expected {FROZEN_PROTOCOL_V3_SHA256}\n"
        f"  actual   {actual}"
    )


def test_v3_protocol_version_matches_pin():
    """The version string in the v3 doc and the test move together."""
    assert f"PROTOCOL_VERSION:   {PROTOCOL_VERSION_V3}" in _text_v3()


def test_v3_execution_remains_blocked():
    """v3 changes the §7 threshold VALUE only, not the block."""
    text = _text_v3()
    assert "EXECUTION_STATUS:   BLOCKED" in text
    assert "EXECUTE_E19_2B:      false" in text


def test_v3_minimum_source_events_defined_at_8():
    """The single substantive v2 -> v3 change: the minimum is now DEFINED = 8,
    owner-ratified — NOT invented, and NOT the v2 'UNDEFINED' verdict."""
    text = _text_v3()
    assert "MINIMUM_DISTINCT_SOURCE_EVENTS" in text
    assert f"MINIMUM_DISTINCT_SOURCE_EVENTS = {MINIMUM_DISTINCT_SOURCE_EVENTS_V3}" in text
    assert "VERDICT: DEFINED = 8" in text
    # provenance: the number is the owner's recorded decision, not invented here
    assert "owner-packet-3" in text
    assert "owner-ratifications-2026-07-19.md" in text
    # v3 is NOT the v2 'undefined' verdict — the differentiation is crisp
    assert "UNDEFINED in E19 doctrine" not in text


def test_v3_execution_still_blocked_on_fleet_and_threshold():
    """The block is preserved: fleet-epoch gate (1) + capital parity (3) + the
    gate-4 threshold-met condition are all still open. Defining the value does
    not unblock execution."""
    text = _text_v3()
    # gate 1 (fleet activation) + gate 3 (capital parity) explicitly not clear
    assert "NOT YET CLEAR" in text
    # gate 4: defining the value does not unblock execution
    assert "does NOT unblock execution" in text
    assert "stays BLOCKED" in text


def test_v3_promotion_prohibition_present():
    assert "E19-2B NEVER promotes anything by itself." in _text_v3()


def test_v3_decision_event_unit_basis_pinned():
    """The experimental unit is UNCHANGED from v2 — the immutable decision
    event, not account rows."""
    text = _text_v3()
    assert "decision_event_id" in text
    assert 'DECISION_EVENT_BASIS = "source_suggestion_id"' in text


def test_v3_fleet_epoch_identity_pinned():
    """Cohort/epoch separation is UNCHANGED from v2."""
    text = _text_v3()
    assert "small_tier_v1" in text
    assert "legacy_100k" in text


def test_v3_arm_b_pinned_by_content():
    """Arm B is carried VERBATIM from v2 — same manifest hash + fingerprint,
    still by CONTENT, never SHAPE."""
    text = _text_v3()
    assert FLEET_MANIFEST_SHA256_V3 in text
    assert FLEET_CONFIG_HASH_SET_FINGERPRINT_V3 in text
    assert "fleet_policy_design_50.md" in text
    assert "NOT YET PINNABLE" not in text


def test_v3_carries_v2_science_unchanged():
    """The v2 -> v3 delta is the §7 minimum ONLY. Spot-check that the frozen
    metric/censoring/stopping vocabulary is carried verbatim (the whole-file
    hash pins it; these name the load-bearing clauses so a silent science change
    is visible at review)."""
    text = _text_v3()
    # metrics vocabulary (§4)
    assert "EVALUATOR_VERSION = evaluator@1.0.0" in text
    assert "Brier score" in text and "EV-RMSE" in text
    # censoring (§5)
    assert "abstention is a result" in text.lower() or "Abstained" in text
    assert "Prequential discipline" in text
    # stopping rule (§8) — no optional stopping
    assert "No optional stopping." in text
    # experiment version (§6 / §12) unchanged
    assert 'EXPERIMENT_VERSION =\n  "e19_prerejection_v1"' in text or \
        "e19_prerejection_v1" in text
    # §12 science-freeze base is UNCHANGED (not re-pinned at the v3 base)
    assert "science-freeze base" in text
    assert "79f4ba76" in text


def test_v3_references_v2_as_immutable_predecessor():
    """v3 names v2 as its immutable predecessor and carries the v2 pin — the
    lineage is explicit and the immutability convention preserved."""
    text = _text_v3()
    assert PROTOCOL_VERSION in text  # "e19_2b_protocol_v2"
    assert FROZEN_PROTOCOL_SHA256 in text  # v2's own pin quoted in the lineage
    assert "IMMUTABLE" in text


# ---- cross-version guards: v2 is PRESERVED and the two are DISTINCT ----


def test_v2_still_frozen_and_untouched():
    """v3 must NOT edit or delete v2. The v2 doc's LF-normalized hash still
    equals its original pin — proof v2 is byte-for-byte preserved."""
    actual = hashlib.sha256(_normalized_bytes()).hexdigest()
    assert actual == FROZEN_PROTOCOL_SHA256, (
        "v2 frozen protocol was modified — v2 must remain immutable when v3 is "
        "added alongside it."
    )
    assert PROTOCOL_DOC.is_file() and PROTOCOL_DOC != PROTOCOL_DOC_V3


def test_v2_and_v3_are_distinct_files_and_hashes():
    """Two versioned artifacts, two distinct pins. Neither collapses onto the
    other."""
    assert PROTOCOL_DOC != PROTOCOL_DOC_V3
    assert FROZEN_PROTOCOL_SHA256 != FROZEN_PROTOCOL_V3_SHA256
    assert PROTOCOL_VERSION != PROTOCOL_VERSION_V3
    assert _normalized_bytes() != _normalized_bytes_v3()


def test_v2_minimum_still_undefined_v3_minimum_defined():
    """The versions differ on exactly the §7 minimum: v2 UNDEFINED, v3 = 8."""
    assert "UNDEFINED in E19 doctrine" in _text()          # v2 unchanged
    assert "VERDICT: DEFINED = 8" in _text_v3()            # v3 defined
