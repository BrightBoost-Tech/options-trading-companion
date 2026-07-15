"""
Documentation consistency tests — audit/ledger.md + docs/backlog.md.

SCOPE NOTE (read before extending): these are STRING assertions over documents,
which is the correct instrument here because a document has no runtime route to
drive. This is deliberately NOT the CLAUDE.md §9 / #1126 "costume" class — that
rule forbids source-string assertions standing in for a PRODUCTION CALL PATH.
These tests make no claim about code behavior; every code-behavior claim in the
07-14 docs was verified against the DB/Railway/broker at authorship time and is
falsifiable by its own live falsifier, not by this file.

What these pin (the 2026-07-14 post-merge reconciliation):
  1. queue ①-④ PR→SHA identity agrees across both documents
  2. #1201 is never presented as deployed AT its own SHA (it rides `bef2cdd`)
  3. #1200's narrow claim + non-goals survive retelling
  4. the INCONCLUSIVE rule for #1200's falsifier is stated
  5. E19-2B exists as a SEPARATE dependency (③ shipped narrow)
  6. F-WINDOW-1's reused identifier stays split (1a CLOSED / 1b OPEN)
  7. F-A9-5 stays DRAFT while Lane A is open
  8. prequential's no-production-caller fact is recorded
  9. the four new findings are present and defined exactly once (dedupe)
 10. preserved counts/triggers are not silently dropped
 11. no credential-shaped value ever lands in the audit docs

Origin: 2026-07-14 post-close docs reconciliation lane.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER_PATH = REPO_ROOT / "audit" / "ledger.md"
BACKLOG_PATH = REPO_ROOT / "docs" / "backlog.md"
REPORT_PATH = REPO_ROOT / "audit" / "reports" / "2026-07-14.md"


@pytest.fixture(scope="module")
def ledger() -> str:
    return LEDGER_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def backlog() -> str:
    return BACKLOG_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def both(ledger: str, backlog: str) -> str:
    return ledger + "\n" + backlog


# --------------------------------------------------------------------------
# 0. the documents exist (the §7 sweep convention: an untracked report hides
#    findings from the committed view)
# --------------------------------------------------------------------------

def test_audit_docs_exist():
    assert LEDGER_PATH.is_file(), f"missing {LEDGER_PATH}"
    assert BACKLOG_PATH.is_file(), f"missing {BACKLOG_PATH}"


def test_nightly_report_is_committed_not_untracked():
    """§7 sweep convention: the loop never commits, so every build session
    sweeps untracked audit/reports/*.md into its PR."""
    assert REPORT_PATH.is_file(), (
        "audit/reports/2026-07-14.md must be swept into the repo — an untracked "
        "report hides its findings from the committed view (§7, meta-audit gap #9)"
    )


# --------------------------------------------------------------------------
# 1. queue ①-④ PR -> squash SHA identity
# --------------------------------------------------------------------------

QUEUE = {
    "#1195": "af1c5be",   # ① E8-3 typed sentinel
    "#1199": "f34d5cd",   # ② E16-3 + F-REPLAY-FK
    "#1200": "bef2cdd",   # ③ E19-2A
    "#1201": "9670712",   # ④ F-A3-4
}


@pytest.mark.parametrize("pr,sha", sorted(QUEUE.items()))
def test_queue_pr_and_sha_present_in_ledger(ledger: str, pr: str, sha: str):
    assert pr in ledger, f"{pr} absent from the ledger"
    assert sha in ledger, f"{pr}'s squash SHA {sha} absent from the ledger"


@pytest.mark.parametrize("pr,sha", sorted(QUEUE.items()))
def test_queue_pr_and_sha_present_in_backlog(backlog: str, pr: str, sha: str):
    assert pr in backlog, f"{pr} absent from the backlog"
    assert sha in backlog, f"{pr}'s squash SHA {sha} absent from the backlog"


def test_queue_items_marked_resolved(backlog: str):
    """①-④ are cleared; the 07-12 section keeps them only as history."""
    assert "QUEUE ①–④ CLEARED" in backlog or "①–④ ALL RESOLVED" in backlog
    for marker in ("RESOLVED — #1195", "RESOLVED — #1199",
                   "RESOLVED-NARROW — #1200", "RESOLVED — #1201"):
        assert marker in backlog, f"queue item not marked resolved: {marker}"


# --------------------------------------------------------------------------
# 2. #1201 deployed WITHIN bef2cdd — never at its own SHA
# --------------------------------------------------------------------------

def test_1201_never_presented_as_deployed_at_its_own_sha(both: str):
    """`9670712` deployed at 22:28:05Z but is REMOVED — superseded 37min later
    by #1200. Its code is live only *within* bef2cdd. A future reader must never
    take 9670712 for a running deployment (H8 squash-merge class)."""
    assert "9670712" in both
    # every mention of the SHA must sit in a context that names bef2cdd
    for m in re.finditer(r"9670712", both):
        window = both[max(0, m.start() - 400): m.end() + 400]
        assert "bef2cdd" in window, (
            "a `9670712` mention lacks the `bef2cdd` qualifier within +/-400 chars; "
            "#1201 must never read as deployed at its own SHA"
        )


def test_1201_deploy_status_recorded_in_its_own_definition_block(ledger: str):
    """Anchored on ④'s DEFINITION block, not on the document at large.

    A whole-document search is too loose to be a guard: `bef2cdd` and 'deployed
    within' occur all over this entry, so stripping the qualifier from ④'s own
    line still leaves those strings present elsewhere and a document-wide check
    stays green. The invariant belongs to the block that defines ④.
    """
    m = re.search(r"\*\*④ F-A3-4 #1201[^\n]*(?:\n[^\n]*){0,6}", ledger)
    assert m, "④ needs a definition block naming #1201"
    block = m.group(0)
    assert "9670712" in block, "④'s squash SHA belongs in its definition"
    assert "WITHIN" in block.upper(), (
        "④'s definition must state the code is deployed WITHIN bef2cdd — not at "
        "its own SHA"
    )
    assert "NOT AT ITS" in block.upper(), (
        "④'s definition must say explicitly that it did NOT deploy at its own SHA"
    )
    assert "REMOVED" in block, (
        "the superseded 9670712 deployment status is load-bearing: a future "
        "deployment-SHA search returns REMOVED and reads as 'never shipped'"
    )


# --------------------------------------------------------------------------
# 3. #1200's narrow claim survives retelling
# --------------------------------------------------------------------------

def test_1200_narrow_claim_scope_string(both: str):
    assert "raw_candidate_eligibility_only" in both


NON_GOALS = ["selection", "execution", "fill", "P&L", "thesis", "capacity"]


def test_1200_non_goals_preserved(ledger: str):
    """NOT selection, execution, fill, P&L, thesis, capacity, or joint-ranking."""
    for token in NON_GOALS:
        assert token in ledger, f"#1200 non-goal dropped from the ledger: {token}"
    assert "joint" in ledger.lower() and "rank" in ledger.lower()


def test_1200_narrow_contract_fields_recorded(ledger: str):
    for field in ("selected_for_entry=false", "capacity_evaluated=false",
                  "joint_rank_evaluated=false", "execution_state='not_executed'"):
        assert field in ledger, f"#1200 scope-contract field dropped: {field}"


# --------------------------------------------------------------------------
# 4. the live falsifier stays pending; a quiet day is INCONCLUSIVE
# --------------------------------------------------------------------------

def test_no_qualifying_candidate_is_inconclusive(both: str):
    assert "INCONCLUSIVE" in both, "the INCONCLUSIVE rule must not be dropped"
    m = re.search(r"NO QUALIFYING CANDIDATE = INCONCLUSIVE", both, re.IGNORECASE)
    assert m, "the rule must be stated explicitly, not implied"
    window = both[m.start(): m.end() + 200]
    assert "not PASS" in window and "not FAIL" in window, (
        "INCONCLUSIVE must be spelled out as neither PASS nor FAIL — a quiet day "
        "must never be recorded as a passing falsifier"
    )


# --------------------------------------------------------------------------
# 5. E19-2B is a SEPARATE dependency (③ shipped narrow)
# --------------------------------------------------------------------------

def test_e19_2b_split_out_as_separate_item(both: str):
    assert "E19-2B" in both, "the full counterfactual selector must be split out"


def test_e19_2b_is_the_full_counterfactual_selector(backlog: str):
    m = re.search(r"E19-2B[^\n]*\n(?:[^\n]*\n){0,6}", backlog)
    assert m, "E19-2B needs a definition block in the backlog"
    block = m.group(0).lower()
    assert "counterfactual" in block and "selector" in block


def test_full_experiment_stamp_moved_off_1200(both: str):
    """The 07-12 line '③'s SHA stamps the FULL experiment' is superseded:
    ③ shipped as E19-2A, so bef2cdd does NOT stamp the full experiment."""
    assert "superseded" in both.lower()
    assert "PARTIAL" in both, "D②'s un-mute stays PARTIAL until E19-2B"


# --------------------------------------------------------------------------
# 6. F-WINDOW-1 identifier collision stays resolved
# --------------------------------------------------------------------------

def test_f_window_1_split_into_1a_and_1b(both: str):
    assert "F-WINDOW-1a" in both, "the EMISSION half must be named 1a"
    assert "F-WINDOW-1b" in both, "the COVERAGE+JOINABILITY half must be named 1b"


def test_f_window_1a_closed_and_1b_open(ledger: str):
    a = re.search(r"F-WINDOW-1a[^\n]*(?:\n[^\n]*){0,5}", ledger)
    b = re.search(r"F-WINDOW-1b[^\n]*(?:\n[^\n]*){0,5}", ledger)
    assert a and b, "both halves need definition blocks"
    assert "CLOSED" in a.group(0), "1a (emission) is closed at 1386834/#1198"
    assert "1386834" in a.group(0), "1a's closing SHA is load-bearing"
    assert "OPEN" in b.group(0), "1b (coverage+joinability) remains open"


def test_f_window_1b_still_blocks_arm_decisions(both: str):
    """A live channel is not a correlation ID — 1a's closure does not release
    the ARM decisions, which wait on JOINABLE evidence."""
    assert "joinable" in both.lower()
    m = re.search(r"ARM decisions[^\n]*(?:\n[^\n]*){0,3}", both)
    assert m, "the ARM-decisions dependency must survive the split"


def test_arm_evidence_clock_third_restart_preserved(both: str):
    """Doctrine that the split must not lose: the clock restarted at 1386834 —
    the THIRD restart (d5edd50's evidence never existed; the channel was dead)."""
    assert "THIRD restart" in both or "third restart" in both
    assert "d5edd50" in both


# --------------------------------------------------------------------------
# 7. F-A9-5 is DRAFT while Lane A is open
# --------------------------------------------------------------------------

def test_f_a9_5_marked_draft_not_shipped(both: str):
    assert "F-A9-5" in both
    m = re.search(r"F-A9-5[^\n]*(?:\n[^\n]*){0,3}", both)
    assert m and "DRAFT" in m.group(0), "F-A9-5 must be marked DRAFT"


def test_f_a9_5_not_claimed_shipped(both: str):
    for m in re.finditer(r"F-A9-5", both):
        window = both[m.start(): m.end() + 260]
        assert "status:shipped" not in window, (
            "F-A9-5 must not be marked shipped — Lane A has zero commits vs origin/main"
        )


# --------------------------------------------------------------------------
# 8. prequential: repaired, but nothing calls it
# --------------------------------------------------------------------------

def test_prequential_no_production_caller_recorded(both: str):
    assert "prequential_validator" in both
    assert re.search(r"(ZERO|no)\s+production\s+callers?", both, re.IGNORECASE), (
        "the no-production-caller fact must be recorded so 'prequential parity "
        "shipped' is never read as 'prequential validation runs'"
    )


def test_prequential_scheduling_is_operator_decision(both: str):
    assert re.search(r"SCHEDULING IS AN OPERATOR DECISION", both, re.IGNORECASE), (
        "wiring the falsifier to a schedule is live-adjacent — operator-gated"
    )


# --------------------------------------------------------------------------
# 9. new findings present, and defined exactly once (dedupe)
# --------------------------------------------------------------------------

NEW_FINDINGS = [
    "F-SHADOW-CAPITAL-PARITY",
    "F-POLICY-CAPITAL-FALLBACK",
    "GIT-SHA-DECISION-PROVENANCE",
]


@pytest.mark.parametrize("finding", NEW_FINDINGS)
def test_new_finding_recorded_in_both_docs(ledger: str, backlog: str, finding: str):
    assert finding in ledger, f"{finding} absent from the ledger (exclusion memory)"
    assert finding in backlog, f"{finding} absent from the backlog (build queue)"


@pytest.mark.parametrize("finding", NEW_FINDINGS)
def test_new_finding_defined_exactly_once_per_doc(ledger: str, backlog: str, finding: str):
    """Dedupe guard: a finding gets exactly ONE *graded* definition per document.
    Re-finding a ledger item is a wasted audit slot; duplicate definitions cause
    exactly that. A definition is the identifier followed by its severity grade
    — `X (HIGH, ...)`. Section headings and cross-references naming the finding
    are NOT definitions and are expected to recur."""
    graded = re.escape(finding) + r"\s*\((?:HIGH|MED|LOW),"
    for name, doc in (("ledger", ledger), ("backlog", backlog)):
        defs = len(re.findall(graded, doc))
        assert defs == 1, (
            f"{finding} has {defs} graded definition blocks in the {name} "
            f"(expected exactly 1)"
        )


def test_capital_findings_share_a_root(both: str):
    """F-SHADOW-CAPITAL-PARITY (DB values) and F-POLICY-CAPITAL-FALLBACK (code
    defaults) share init_lab's seeding origin — fix as a family, not ad hoc."""
    assert "init_lab.py:12" in both
    assert "INITIAL_CAPITAL" in both
    assert "family" in both.lower()


def test_policy_capital_fallback_names_both_sites(both: str):
    """#1200's PR body disclosed only the fork site; the evaluator site is the
    second, un-named one. Fixing only the disclosed site leaves fabrication."""
    assert "fork.py:210" in both, "the disclosed fork site"
    assert "evaluator.py:251" in both, "the SECOND, un-named evaluator site"


def test_shadow_capital_parity_scope_is_honest(both: str):
    """This is the policy-lab EVIDENCE surface, not live sizing — the claim must
    not widen into a live-capital bug it is not."""
    assert "NOT live sizing" in both or "not live sizing" in both.lower()
    assert "2,067.86" in both, "the broker-truth basis is load-bearing"
    assert "100000" in both or "100,000" in both or "$100k" in both


def test_git_sha_provenance_is_empirically_grounded(both: str):
    """9/9 decision_runs stamp the literal 'unknown' across four deployed SHAs."""
    assert "decision_runs.git_sha" in both or "git_sha" in both
    assert "unknown" in both
    assert "api.py:154-157" in both, "the healthcheck already resolves this — cite the fix shape"


def test_prequential_operationalization_recorded(both: str):
    assert re.search(r"prequential operationaliz", both, re.IGNORECASE), (
        "the prequential operationalization item must be filed"
    )


# --------------------------------------------------------------------------
# 10. preserved triggers / counts / doctrine (do-not-relitigate)
# --------------------------------------------------------------------------

PRESERVED = [
    "8/8",            # post-epoch pool (1W/7L)
    "3/10–15",        # close-fill-gap counter
    "1W/7L",
]


@pytest.mark.parametrize("token", PRESERVED)
def test_preserved_counts_survive(ledger: str, token: str):
    assert token in ledger, f"preserved count dropped from the ledger: {token}"


def test_retirement_counters_preserved(ledger: str):
    for counter in ("A1=6", "A2=4", "A3=6", "A4=2", "A5=4", "A6=6",
                    "A8=5", "A9=2", "A10=6"):
        assert counter in ledger, f"retirement counter dropped: {counter}"


def test_retirement_recommendation_preserved(ledger: str):
    """The honest read: quiet-regime artifact, NOT territory coverage —
    recommend KEEP all four. Owner-gated, never unattended."""
    assert "quiet-regime artifact" in ledger
    assert "KEEP all four" in ledger


def test_calibration_floor_settled_not_relitigated(ledger: str):
    assert "SETTLED" in ledger
    assert "×0.5" in ledger or "x0.5" in ledger


def test_breaker_recovery_operator_only_preserved(ledger: str):
    assert "OPERATOR-ONLY" in ledger, "the breaker's recovery contract is doctrine"
    assert "entries_paused=false" in ledger


def test_1199_falsifier_recorded_as_passed(ledger: str):
    """The 07-14 pending disposition #1 resolved: first blob ever at 13:00:08Z."""
    assert "data_blobs" in ledger
    assert "blob_never_persisted" in ledger
    assert "PASSED" in ledger


# --------------------------------------------------------------------------
# 11. credential hygiene — no values, fragments, or fingerprints in the docs
# --------------------------------------------------------------------------

# Deliberately shaped to catch credential-LOOKING strings. Each pattern is a
# format, never a value. Git SHAs / UUIDs / decision ids are NOT credentials.
SECRET_SHAPES = [
    (r"sb_secret_[A-Za-z0-9_-]{8,}", "supabase secret key"),
    (r"sb_publishable_[A-Za-z0-9_-]{8,}", "supabase publishable key"),
    (r"\bsk-[A-Za-z0-9]{20,}", "openai-style secret key"),
    (r"\bPK[A-Z0-9]{16,}\b", "alpaca key id"),
    (r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "JWT"),
    (r"(?i)\b(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]",
     "assigned credential literal"),
]


@pytest.mark.parametrize("pattern,label", SECRET_SHAPES)
def test_audit_docs_contain_no_credential_values(pattern: str, label: str):
    """The audit docs are committed and world-readable in the repo. Credential
    CLASSES and NAMES only — never values, fragments, or fingerprints."""
    for path in (LEDGER_PATH, BACKLOG_PATH, REPORT_PATH):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        hit = re.search(pattern, text)
        assert hit is None, (
            f"{path.name} contains a {label}-shaped string at offset "
            f"{hit.start() if hit else -1} — audit docs carry credential "
            f"classes/names only, never values"
        )


def test_credential_incident_not_fabricated(ledger: str):
    """H9: a value you cannot source must REJECT or flag, never fabricate.
    The incident could not be identified from any authoritative source, so the
    entry records the gap + an operator ask rather than inventing classes/dates.
    A false security record would EXCLUDE a real incident from future audit slots."""
    m = re.search(r"CREDENTIAL INCIDENT[^\n]*(?:\n[^\n]*){0,4}", ledger)
    assert m, "the credential-incident disposition must be recorded"
    block = m.group(0)
    assert "OPERATOR INPUT REQUIRED" in block or "NOT RECORDED" in block, (
        "the incident is unidentified — it must be flagged, not invented"
    )


def test_f_free_1_disposition_not_retitled(ledger: str):
    """F-FREE-1 (07-04) was adjudicated LOCAL-ONLY-FAKE / no rotation warranted.
    It must not be silently retitled as ROTATED_AND_REVOKED — that would convert
    a 'no action needed' verdict into a 'handled' one for a different incident.

    Anchors on F-FREE-1's own DEFINITION block (the P0-1 CREDENTIAL heading), not
    on any mention — the 07-14 credential paragraph legitimately names F-FREE-1
    and ROTATED_AND_REVOKED together to state that they are distinct dispositions.
    """
    m = re.search(r"P0-1 CREDENTIAL \(F-FREE-1\)[^\n]*(?:\n[^\n]*){0,8}", ledger)
    if not m:
        pytest.skip("F-FREE-1 definition block not in this ledger revision")
    block = m.group(0)
    assert "LOCAL-ONLY-FAKE" in block, "F-FREE-1's verdict must survive"
    assert "ROTATED_AND_REVOKED" not in block, (
        "F-FREE-1 is LOCAL-ONLY-FAKE with no live rotation warranted — a "
        "different disposition from ROTATED_AND_REVOKED"
    )
