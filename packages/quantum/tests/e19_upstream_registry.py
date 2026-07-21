"""E19 upstream-hash registry + stale-protocol detection (governance mechanism).

This module is the MACHINE-CHECKABLE mirror of §12 ("Pinned artifacts") of the
frozen E19-2B preregistered analysis protocol
(`docs/specs/e19_2b_preregistered_protocol_v3.md`). It exists to close a gap the
frozen doc cannot close by itself:

  §12 pins the content hash of every upstream module the protocol's identity,
  metrics, and dedup depend on. But the doc is FROZEN — its own hash is pinned in
  `test_e19_2b_preregistration.py`, so §12 can never be re-pinned in place. The
  §12 hashes therefore only bind TRANSITIVELY (via the doc's overall SHA): the
  protocol asserts the modules had those hashes AT FREEZE TIME, but nothing
  RE-CHECKS the live modules against those hashes. When the upstream science
  drifts, the frozen doc keeps asserting the OLD hashes — silently stale.

This module makes the check EXPLICIT and TYPED. It is side-effect free: it reads
files and hashes bytes; it creates nothing, activates nothing, writes nothing,
and changes no control.

Design (see `docs/specs/e19_protocol_supersession_governance.md`):

- The registry records the §12 freeze-time hash of each upstream module VERBATIM
  — the registry is a faithful reflection of the immutable doc, never a second
  source of truth. `test_e19_upstream_hash_registry.py` asserts the registry's
  freeze hashes EQUAL the values parsed from the real frozen v3 doc §12, so the
  registry can never silently diverge from the doc it mirrors.
- Staleness is computed by re-hashing the LIVE modules and comparing to the
  freeze hashes. Any difference (drift) or unreadable module (missing) yields a
  TYPED non-fresh result — never a silent pass (H9).
- A frozen protocol whose upstream hashes have drifted is STALE. Per the
  supersession governance, a stale protocol is NEVER edited; a NEW protocol
  version (v4…) must be frozen that re-pins §12 at the new base. This module
  DETECTS staleness and DEFINES the execution-refusal gate; it does not author a
  successor and it does not unblock anything (E19 execution stays BLOCKED).

Location — verification tooling, deliberately in the tests tree.
    This module names the paths of the observe-only terminal_distribution
    package (to hash them). The import-lock guardrail
    (`test_terminal_distribution_import_lock.py`) forbids ANY production module
    under `packages/quantum` from even referencing the string
    `terminal_distribution`, and excludes the tests tree precisely because
    preregistration/integrity verification legitimately references it. This
    registry is that verification tooling — it imports nothing from the package,
    it only reads bytes — so it lives here, honestly, rather than obfuscating the
    path in a production module. The execution-refusal gate it defines is a
    contract for the (unbuilt, BLOCKED) E19 executor, which is itself
    observe-only experiment tooling, not a live-economics module.

Hash basis — CRLF-normalized, platform-independent (matches §12 exactly).
    The §12 pins were authored on a Windows checkout (core.autocrlf=true), so
    they are the SHA-256 of each module's bytes with CRLF line endings. To be a
    directly-comparable, byte-exact mirror of those pins — and to reproduce them
    IDENTICALLY on a Linux CI checkout (LF) and a Windows checkout (CRLF) — the
    registry canonicalizes every module to CRLF before hashing
    (`_crlf_normalized`). This is the same "exact-content, EOL-independent"
    discipline the doc-hash test uses (it normalizes to LF); we normalize to CRLF
    solely because that is the basis §12 was pinned on. The normalization is
    idempotent, so a CRLF or an LF checkout of identical content yields the same
    hash.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# Provenance — which frozen protocol this registry mirrors.
# ---------------------------------------------------------------------------

#: The active frozen protocol whose §12 this registry mirrors.
PROTOCOL_VERSION = "e19_2b_protocol_v3"

#: The science-freeze base at which §12's hashes were computed (§12 / §0).
#: The frozen doc pins the hashes "at the science-freeze base 79f4ba76"; the v2
#: authoring base (ed5d6f48) carried byte-identical upstream content, so both
#: reproduce the §12 pins.
FREEZE_BASE_SHA = "79f4ba76"

#: The base at which THIS registry recorded the live-drift snapshot below.
#: Provenance only — the freeze hashes are the contract; this documents when the
#: KNOWN-stale delta was observed.
REGISTRY_AUTHORING_BASE_SHA = "04b376b5"

#: The frozen v3 protocol doc (source of the §12 pins this registry mirrors).
PROTOCOL_DOC_RELPATH = "docs/specs/e19_2b_preregistered_protocol_v3.md"


# ---------------------------------------------------------------------------
# The registry: each §12 upstream module -> (repo-relative path, freeze hash).
#
# `logical_name` is the shorthand §12 uses in its pinned-artifacts block. The
# `freeze_hash` values are the §12 pins VERBATIM (CRLF-normalized SHA-256 at
# FREEZE_BASE_SHA). Do not edit these to "fix" a drift — a drift is DETECTED
# here and RESOLVED by a new protocol version, never by re-pinning in place.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UpstreamModulePin:
    """One §12 upstream module and its freeze-time content hash."""

    logical_name: str
    repo_relative_path: str
    freeze_hash: str  # CRLF-normalized SHA-256 at FREEZE_BASE_SHA == §12 pin


E19_2B_V3_UPSTREAM_REGISTRY: Tuple[UpstreamModulePin, ...] = (
    UpstreamModulePin(
        "contract.py",
        "packages/quantum/analytics/terminal_distribution/contract.py",
        "4523a81c220bbfc4b534249ff7bd428b59cf9556084f83c27edb1e96bc970cd0",
    ),
    UpstreamModulePin(
        "evaluator.py",
        "packages/quantum/analytics/terminal_distribution/evaluator.py",
        "d0ecb19ed70b96801e30a77c1541d719bf2e3a081cc6e6ed69de4e5fc292b49f",
    ),
    UpstreamModulePin(
        "payoff.py",
        "packages/quantum/analytics/terminal_distribution/payoff.py",
        "6e119d0b1551b0099a1665d8010d7afc165394f8600658f8ef53a91a80ac7cb6",
    ),
    UpstreamModulePin(
        "challenger_lognormal.py",
        "packages/quantum/analytics/terminal_distribution/challenger_lognormal.py",
        "0c5cc23de8f7b320847a2c32ac51cdf6701657cc2e6383b5d654caf837b5d572",
    ),
    UpstreamModulePin(
        "baselines.py",
        "packages/quantum/analytics/terminal_distribution/baselines.py",
        "c3f2977b05836c5bb48016080650fa631e670ffc6b2296ea59881caf2ca42bcc",
    ),
    UpstreamModulePin(
        "terminal_distribution/__init__.py",
        "packages/quantum/analytics/terminal_distribution/__init__.py",
        "b983a31e7419086dd51e92ae02f4fd7fc75776ad469641f8152aecac70169575",
    ),
    UpstreamModulePin(
        "policy_lab/shadow_fleet.py",
        "packages/quantum/policy_lab/shadow_fleet.py",
        "670e8f34be67982f995d3f9f936cb3b3b0822bc1732d380c4b25a51df2bb9b46",
    ),
    UpstreamModulePin(
        "policy_lab/fork.py",
        "packages/quantum/policy_lab/fork.py",
        "1f1d238682efb2889a4699413d7082fc7690be0ad2640f1479d07e119c67cdeb",
    ),
)

#: The two §12 pins the frozen doc ALSO carries for arm B (fleet policy design).
#: These are content pins of docs/artifacts, verified reproducible in the doc's
#: own preregistration test; recorded here so the governance narrative is
#: complete. They are not module-content pins, so they are not part of the
#: module drift scan.
FLEET_MANIFEST_SHA256 = (
    "5cb76f9981ee12a34204dec63368c918de802f71a99f5766410aa34638d8922c"
)
FLEET_CONFIG_HASH_SET_FINGERPRINT = (
    "18766a1e882e36a46d708add8d3e5c258ea117607954210a8d142fc8844a9a39"
)


# ---------------------------------------------------------------------------
# KNOWN-stale delta (honest record).
#
# At REGISTRY_AUTHORING_BASE_SHA, the following §12 modules ALREADY DRIFTED from
# their freeze hash — they changed after the v2/v3 science-freeze base and v3
# carried §12 VERBATIM (deliberately, to not mutate frozen science). This is the
# recorded, expected staleness the governance names explicitly. A drift that is
# NOT in this map is a NEW, unrecorded change and must fail loudly.
#
# Provenance of the recorded drift: PR #1287 (squash 9b63dcc1, single-leg
# generation) added surface to the terminal_distribution contract and package
# __init__ between the v2 authoring base (ed5d6f48) and the v3 authoring base
# (94aa6528). Additive though it is, it is a change to the frozen science's
# contract module — exactly the class of upstream drift this registry exists to
# surface.
# ---------------------------------------------------------------------------

KNOWN_STALE_MODULES: Mapping[str, str] = {
    # logical_name -> current CRLF-normalized hash at REGISTRY_AUTHORING_BASE_SHA
    "contract.py": (
        "fd1a7098a42e1f9fa5d8fce12d79ebd433b910db7a71b6a7fb5a3251e74ca121"
    ),
    "terminal_distribution/__init__.py": (
        "216f1ca8c56920247c315f15452d1926bfd2409b25e440901a74072f86e20550"
    ),
}


# ---------------------------------------------------------------------------
# Typed results.
# ---------------------------------------------------------------------------


class ModuleHashStatus(str, Enum):
    """Per-module comparison outcome. Never a bare bool — MISSING is distinct
    from DRIFTED so an unreadable module can never masquerade as 'fresh' or as a
    content change (H9 / loud-error doctrine)."""

    MATCH = "match"
    DRIFTED = "drifted"
    MISSING = "missing"


@dataclass(frozen=True)
class ModuleHashResult:
    logical_name: str
    repo_relative_path: str
    expected_freeze_hash: str
    current_hash: Optional[str]  # None iff MISSING
    status: ModuleHashStatus


@dataclass(frozen=True)
class StalenessReport:
    """The typed staleness verdict for a protocol's §12 upstream set."""

    protocol_version: str
    freeze_base_sha: str
    results: Tuple[ModuleHashResult, ...]
    matched: Tuple[str, ...]
    drifted: Tuple[str, ...]
    missing: Tuple[str, ...]

    @property
    def is_stale(self) -> bool:
        """STALE iff any module drifted OR any module could not be read.
        Fresh requires EVERY §12 module present and byte-identical to freeze."""
        return bool(self.drifted) or bool(self.missing)

    def summary(self) -> str:
        return (
            f"{self.protocol_version} upstream vs §12 freeze "
            f"({self.freeze_base_sha}): "
            f"{len(self.matched)} match, {len(self.drifted)} drifted "
            f"{list(self.drifted)}, {len(self.missing)} missing "
            f"{list(self.missing)} -> "
            f"{'STALE' if self.is_stale else 'FRESH'}"
        )


class E19UpstreamStaleError(RuntimeError):
    """Raised by the execution-refusal gate when the active protocol's §12
    upstream modules have drifted (or are unreadable). A frozen protocol whose
    science changed is STALE and MUST NOT execute until a NEW protocol version
    re-pins §12."""

    def __init__(self, report: StalenessReport):
        self.report = report
        super().__init__(
            "E19 execution REFUSED: the active protocol "
            f"{report.protocol_version} is STALE against its §12 upstream "
            f"registry. drifted={list(report.drifted)} "
            f"missing={list(report.missing)}. A frozen protocol whose upstream "
            "science has changed may not execute; freeze a NEW protocol version "
            "(v4…) that re-pins §12 at the new base — never edit the frozen one."
        )


# ---------------------------------------------------------------------------
# Hashing (CRLF-normalized, platform-independent — see module docstring).
# ---------------------------------------------------------------------------


def _crlf_normalized(raw: bytes) -> bytes:
    """Collapse any CRLF/CR/LF to LF, then expand to CRLF. Idempotent: a CRLF
    checkout and an LF checkout of identical content hash to the same value.
    This is the exact basis §12 was pinned on."""
    lf = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return lf.replace(b"\n", b"\r\n")


def content_hash(raw: bytes) -> str:
    """CRLF-normalized SHA-256 hex of the given bytes (the registry's basis)."""
    return hashlib.sha256(_crlf_normalized(raw)).hexdigest()


def repo_root() -> Path:
    """Repo root, derived from this module's location.
    parents: [0]=tests [1]=quantum [2]=packages [3]=repo root."""
    return Path(__file__).resolve().parents[3]


def _default_reader(root: Path) -> Callable[[str], Optional[bytes]]:
    def _read(rel_path: str) -> Optional[bytes]:
        p = root / rel_path
        try:
            return p.read_bytes()
        except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
            return None

    return _read


# ---------------------------------------------------------------------------
# Stale-protocol detection.
# ---------------------------------------------------------------------------


def evaluate_staleness(
    registry: Tuple[UpstreamModulePin, ...] = E19_2B_V3_UPSTREAM_REGISTRY,
    *,
    protocol_version: str = PROTOCOL_VERSION,
    freeze_base_sha: str = FREEZE_BASE_SHA,
    root: Optional[Path] = None,
    reader: Optional[Callable[[str], Optional[bytes]]] = None,
) -> StalenessReport:
    """Re-hash each registry module from disk (or the injected `reader`) and
    compare to its freeze hash. Returns a typed report.

    `reader` (path -> bytes|None) overrides file access — the seam that lets a
    test SIMULATE an upstream change (mutate one module's bytes) or a fresh state
    (return freeze content) without touching the working tree. When omitted, a
    default reader reads real files under `root` (default: `repo_root()`).
    """
    if reader is None:
        reader = _default_reader(root if root is not None else repo_root())

    results = []
    matched, drifted, missing = [], [], []
    for pin in registry:
        raw = reader(pin.repo_relative_path)
        if raw is None:
            results.append(
                ModuleHashResult(
                    pin.logical_name,
                    pin.repo_relative_path,
                    pin.freeze_hash,
                    None,
                    ModuleHashStatus.MISSING,
                )
            )
            missing.append(pin.logical_name)
            continue
        cur = content_hash(raw)
        if cur == pin.freeze_hash:
            status = ModuleHashStatus.MATCH
            matched.append(pin.logical_name)
        else:
            status = ModuleHashStatus.DRIFTED
            drifted.append(pin.logical_name)
        results.append(
            ModuleHashResult(
                pin.logical_name,
                pin.repo_relative_path,
                pin.freeze_hash,
                cur,
                status,
            )
        )

    return StalenessReport(
        protocol_version=protocol_version,
        freeze_base_sha=freeze_base_sha,
        results=tuple(results),
        matched=tuple(matched),
        drifted=tuple(drifted),
        missing=tuple(missing),
    )


def assert_upstream_fresh_for_execution(
    registry: Tuple[UpstreamModulePin, ...] = E19_2B_V3_UPSTREAM_REGISTRY,
    *,
    protocol_version: str = PROTOCOL_VERSION,
    freeze_base_sha: str = FREEZE_BASE_SHA,
    root: Optional[Path] = None,
    reader: Optional[Callable[[str], Optional[bytes]]] = None,
) -> StalenessReport:
    """Execution-refusal gate (the contract the E19 executor MUST call).

    This is an ADDITIONAL, independent gate on top of the protocol's own
    `EXECUTION_STATUS: BLOCKED` and its §10 gates. It answers ONE question: does
    the live upstream science still match what the active protocol froze? If not,
    the protocol is scientifically stale and execution is REFUSED — fail-closed,
    by raising `E19UpstreamStaleError`. It never returns a "run anyway" path.

    The real E19 executor is unbuilt/BLOCKED; this defines the gate it must wire
    at its entrypoint. Returns the fresh `StalenessReport` only when EVERY §12
    module is present and byte-identical to freeze.
    """
    report = evaluate_staleness(
        registry,
        protocol_version=protocol_version,
        freeze_base_sha=freeze_base_sha,
        root=root,
        reader=reader,
    )
    if report.is_stale:
        raise E19UpstreamStaleError(report)
    return report


def known_stale_logical_names() -> Tuple[str, ...]:
    """The §12 modules recorded as KNOWN-stale at REGISTRY_AUTHORING_BASE_SHA,
    sorted for deterministic comparison."""
    return tuple(sorted(KNOWN_STALE_MODULES))
