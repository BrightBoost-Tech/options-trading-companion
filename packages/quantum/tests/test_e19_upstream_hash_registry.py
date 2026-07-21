"""Tests for the E19 upstream-hash registry + stale-protocol detection.

These prove the governance mechanism specified in
`docs/specs/e19_protocol_supersession_governance.md`:

  1. The immutable v3 (and v2) protocol doc hashes still BITE — the registry
     work did not touch the frozen science.
  2. The registry is a FAITHFUL mirror of the frozen v3 §12 pins (parsed from
     the real doc, never re-derived), so it can't silently diverge.
  3. STALE-DETECTION honestly records the current KNOWN drift with the EXACT
     differing modules, and FIRES on a simulated upstream change.
  4. The EXECUTION-REFUSAL gate fails closed on drift and on a missing module,
     and passes only when every §12 module is byte-identical to freeze.

#1126-safe by construction: every assertion drives the REAL registry code and
the REAL files on disk (or an explicit injected reader for simulation); none
reimplement or paraphrase the mechanism under test.
"""

import hashlib
import re
from pathlib import Path

from packages.quantum.tests import e19_upstream_registry as reg

# repo_root/packages/quantum/tests/<this file> -> parents[3] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]

# The immutable protocol doc pins (LF-normalized SHA-256) — these MUST NOT
# change. Asserted directly against the real docs so this test bites if either
# frozen protocol is edited.
V2_DOC = _REPO_ROOT / "docs" / "specs" / "e19_2b_preregistered_protocol.md"
V3_DOC = _REPO_ROOT / "docs" / "specs" / "e19_2b_preregistered_protocol_v3.md"
V2_FROZEN_LF_SHA256 = (
    "50e7e237436f1bc43d9679c1081eb1e8218048640fb1b325885fd2cf0bc3b76c"
)
V3_FROZEN_LF_SHA256 = (
    "cfdcfc9e7fc7c4d1fd56a5b3ec98d910c5093c2d8e39e4ac7121c51a847903c6"
)


def _lf_bytes(p: Path) -> bytes:
    raw = p.read_bytes()
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _lf_text(p: Path) -> str:
    return _lf_bytes(p).decode("utf-8")


def _parse_section12_module_pins(doc_text: str) -> dict:
    """Extract the §12 module -> hash pins from the real frozen v3 doc.
    Each pinned line is '<logical_name>.py   <64-hex>'. Non-module 64-hex lines
    (manifest sha256, fingerprint) do not match because their first token does
    not end in .py."""
    pat = re.compile(r"^\s*([\w./]+\.py)\s+([0-9a-f]{64})\b", re.M)
    return {m.group(1): m.group(2) for m in pat.finditer(doc_text)}


# ---------------------------------------------------------------------------
# 1. The immutable v3/v2 doc hashes still bite.
# ---------------------------------------------------------------------------


def test_v3_frozen_doc_hash_unchanged():
    actual = hashlib.sha256(_lf_bytes(V3_DOC)).hexdigest()
    assert actual == V3_FROZEN_LF_SHA256, (
        "The frozen v3 protocol doc changed — the governance work must NOT edit "
        f"the immutable protocol.\n  expected {V3_FROZEN_LF_SHA256}\n  actual   {actual}"
    )


def test_v2_frozen_doc_hash_unchanged():
    actual = hashlib.sha256(_lf_bytes(V2_DOC)).hexdigest()
    assert actual == V2_FROZEN_LF_SHA256, (
        "The frozen v2 protocol doc changed — it must remain immutable.\n"
        f"  expected {V2_FROZEN_LF_SHA256}\n  actual   {actual}"
    )


# ---------------------------------------------------------------------------
# 2. The registry faithfully mirrors the frozen v3 §12 pins.
# ---------------------------------------------------------------------------


def test_registry_covers_exactly_section12_modules():
    """The registry's module set == the §12 pinned-artifacts module set parsed
    from the real frozen v3 doc — no module dropped, none invented."""
    doc_pins = _parse_section12_module_pins(_lf_text(V3_DOC))
    registry_names = {p.logical_name for p in reg.E19_2B_V3_UPSTREAM_REGISTRY}
    assert registry_names == set(doc_pins), (
        f"registry {sorted(registry_names)} != §12 {sorted(doc_pins)}"
    )
    # exactly the 8 known §12 upstream modules
    assert len(reg.E19_2B_V3_UPSTREAM_REGISTRY) == 8


def test_registry_freeze_hashes_equal_doc_section12():
    """Each registry freeze hash EQUALS the value pinned in the real frozen v3
    §12 — the registry mirrors the immutable doc, never a second source of
    truth. If the doc and registry ever diverge, this fails."""
    doc_pins = _parse_section12_module_pins(_lf_text(V3_DOC))
    for pin in reg.E19_2B_V3_UPSTREAM_REGISTRY:
        assert pin.logical_name in doc_pins
        assert pin.freeze_hash == doc_pins[pin.logical_name], (
            f"{pin.logical_name}: registry {pin.freeze_hash} != §12 "
            f"{doc_pins[pin.logical_name]}"
        )


def test_registry_provenance_constants_recorded():
    assert reg.PROTOCOL_VERSION == "e19_2b_protocol_v3"
    assert reg.FREEZE_BASE_SHA == "79f4ba76"
    assert reg.REGISTRY_AUTHORING_BASE_SHA == "04b376b5"


# ---------------------------------------------------------------------------
# 3. Stale-detection: honest KNOWN drift + fires on simulated change.
# ---------------------------------------------------------------------------


def test_current_upstream_is_stale_with_exact_known_modules():
    """At the current base the active protocol IS stale, and detection names the
    EXACT differing modules — the honest KNOWN stale delta, nothing more."""
    report = reg.evaluate_staleness()
    assert report.is_stale is True
    # the exact differing modules, no more and no fewer
    assert set(report.drifted) == set(reg.KNOWN_STALE_MODULES)
    assert report.missing == ()
    # nothing beyond the recorded known-stale set drifted
    assert set(report.drifted) == set(reg.known_stale_logical_names())


def test_known_stale_current_hashes_match_recorded_snapshot():
    """Each drifted module's live hash equals the recorded KNOWN_STALE snapshot —
    so a NEW change (drift beyond the recorded delta) fails loudly here."""
    report = reg.evaluate_staleness()
    by_name = {r.logical_name: r for r in report.results}
    for name, recorded_hash in reg.KNOWN_STALE_MODULES.items():
        r = by_name[name]
        assert r.status is reg.ModuleHashStatus.DRIFTED
        assert r.current_hash == recorded_hash, (
            f"{name} drifted BEYOND the recorded known-stale snapshot — a NEW "
            f"upstream change. recorded {recorded_hash} != live {r.current_hash}"
        )


def test_unchanged_section12_modules_still_match_freeze():
    """The §12 modules NOT in the known-stale set are byte-identical to their
    freeze hash — proof the freeze pins are real and CRLF-normalization
    reproduces §12 exactly on this platform."""
    report = reg.evaluate_staleness()
    unchanged = [
        r for r in report.results if r.logical_name not in reg.KNOWN_STALE_MODULES
    ]
    assert len(unchanged) == 6
    for r in unchanged:
        assert r.status is reg.ModuleHashStatus.MATCH
        assert r.current_hash == r.expected_freeze_hash


def test_stale_detection_fires_on_simulated_upstream_change():
    """Mutating a currently-MATCHING real module's bytes (via an injected
    reader) is detected as DRIFTED — the mechanism is not hardcoded to the
    known-2."""
    target = "evaluator.py"  # currently matches freeze
    real_reader = reg._default_reader(_REPO_ROOT)

    def mutating_reader(rel_path):
        raw = real_reader(rel_path)
        if raw is not None and rel_path.endswith("evaluator.py"):
            return raw + b"\n# simulated upstream science change\n"
        return raw

    report = reg.evaluate_staleness(reader=mutating_reader)
    assert report.is_stale is True
    assert target in report.drifted
    # and the previously-known drift is still present (superset, not replaced)
    assert set(reg.KNOWN_STALE_MODULES).issubset(set(report.drifted))


# ---------------------------------------------------------------------------
# 4. Execution-refusal gate.
# ---------------------------------------------------------------------------


def test_execution_gate_refuses_on_real_stale_state():
    """The gate fails CLOSED on the current (stale) upstream — it raises and the
    error names the drifted modules. This is the contract the (unbuilt) E19
    executor must call in addition to EXECUTION_STATUS: BLOCKED."""
    try:
        reg.assert_upstream_fresh_for_execution()
    except reg.E19UpstreamStaleError as e:
        assert set(e.report.drifted) == set(reg.KNOWN_STALE_MODULES)
        assert "REFUSED" in str(e)
        assert "contract.py" in str(e)
    else:
        raise AssertionError("gate did NOT refuse on a stale upstream state")


def test_execution_gate_passes_only_when_fully_fresh():
    """A synthetic registry whose modules all match their freeze hash passes the
    gate and returns a FRESH report — proving the gate is not a hardcoded raise."""
    body_a = b"module a content\n"
    body_b = b"module b content\r\n"  # CRLF input, same logical content basis
    reg_syn = (
        reg.UpstreamModulePin("a", "syn/a.py", reg.content_hash(body_a)),
        reg.UpstreamModulePin("b", "syn/b.py", reg.content_hash(body_b)),
    )
    fresh_reader = {"syn/a.py": body_a, "syn/b.py": body_b}.get

    report = reg.assert_upstream_fresh_for_execution(
        reg_syn, reader=fresh_reader
    )
    assert report.is_stale is False
    assert set(report.matched) == {"a", "b"}
    assert report.drifted == () and report.missing == ()


def test_execution_gate_refuses_on_simulated_drift():
    """Same synthetic registry, one module's bytes changed -> gate refuses and
    names the drifted module."""
    body_a = b"module a content\n"
    reg_syn = (
        reg.UpstreamModulePin("a", "syn/a.py", reg.content_hash(body_a)),
    )
    drift_reader = {"syn/a.py": b"module a content CHANGED\n"}.get
    try:
        reg.assert_upstream_fresh_for_execution(reg_syn, reader=drift_reader)
    except reg.E19UpstreamStaleError as e:
        assert e.report.drifted == ("a",)
    else:
        raise AssertionError("gate did NOT refuse on simulated drift")


def test_missing_module_is_typed_and_fails_closed():
    """An unreadable §12 module is TYPED MISSING (distinct from DRIFTED) and the
    gate fails closed — a read failure can never masquerade as fresh (H9)."""
    reg_syn = (
        reg.UpstreamModulePin("gone", "syn/gone.py", "deadbeef" * 8),
    )
    missing_reader = lambda rel: None  # noqa: E731 - read always fails

    report = reg.evaluate_staleness(reg_syn, reader=missing_reader)
    assert report.missing == ("gone",)
    assert report.drifted == ()
    assert report.is_stale is True
    r = report.results[0]
    assert r.status is reg.ModuleHashStatus.MISSING
    assert r.current_hash is None

    try:
        reg.assert_upstream_fresh_for_execution(reg_syn, reader=missing_reader)
    except reg.E19UpstreamStaleError as e:
        assert "missing" in str(e).lower()
    else:
        raise AssertionError("gate did NOT refuse on a missing module")


# ---------------------------------------------------------------------------
# 5. Hash basis is platform-independent and reproduces §12.
# ---------------------------------------------------------------------------


def test_content_hash_is_crlf_platform_independent():
    """LF and CRLF checkouts of identical content hash to the same value — the
    registry is reproducible on Linux CI (LF) and Windows (CRLF)."""
    lf = b"x\ny\nz\n"
    crlf = b"x\r\ny\r\nz\r\n"
    assert reg.content_hash(lf) == reg.content_hash(crlf)


def test_content_hash_reproduces_a_section12_pin():
    """The registry's CRLF-normalized basis reproduces a §12 pin from raw bytes,
    independent of the checkout's line endings — proving the basis matches the
    frozen doc's."""
    evaluator = (
        _REPO_ROOT
        / "packages/quantum/analytics/terminal_distribution/evaluator.py"
    )
    raw = evaluator.read_bytes()
    expected = next(
        p.freeze_hash
        for p in reg.E19_2B_V3_UPSTREAM_REGISTRY
        if p.logical_name == "evaluator.py"
    )
    assert reg.content_hash(raw) == expected


# ---------------------------------------------------------------------------
# 6. The governance doc exists and states the load-bearing contract.
# ---------------------------------------------------------------------------


def test_governance_doc_exists_and_names_the_contract():
    doc = _REPO_ROOT / "docs" / "specs" / "e19_protocol_supersession_governance.md"
    assert doc.is_file(), f"missing governance doc: {doc}"
    text = _lf_text(doc)
    # the load-bearing governance clauses
    assert "STALE" in text
    assert "supersession" in text.lower()
    assert "never edit the frozen" in text.lower() or "never edited in place" in text.lower()
    assert "e19_upstream_registry" in text
    assert "assert_upstream_fresh_for_execution" in text
    # the immutable pins are named so a reader can verify they are unchanged
    assert "cfdcfc9e" in text  # v3 pin
    assert "50e7e237" in text  # v2 pin
