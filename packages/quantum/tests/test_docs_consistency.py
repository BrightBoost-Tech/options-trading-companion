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
    # order-robust: the full-counterfactual-selector definition must exist among
    # the E19-2B blocks (v1.5 EXTENDS-E19-2B cross-refs may precede it).
    blocks = re.findall(r"E19-2B[^\n]*\n(?:[^\n]*\n){0,6}", backlog)
    assert blocks, "E19-2B needs a definition block in the backlog"
    assert any("counterfactual" in b.lower() and "selector" in b.lower()
               for b in blocks), "E19-2B's counterfactual-selector definition must survive"


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
    # order-robust: SOME F-A9-5 block marks it DRAFT (cross-references from the
    # v1.5 adjudication may name F-A9-5 above its item definition).
    blocks = re.findall(r"F-A9-5[^\n]*(?:\n[^\n]*){0,3}", both)
    assert any("DRAFT" in b for b in blocks), "F-A9-5 must be marked DRAFT in its item block"


def test_f_a9_5_not_claimed_shipped(both: str):
    for m in re.finditer(r"F-A9-5", both):
        window = both[m.start(): m.end() + 260]
        assert "status:shipped" not in window, (
            "F-A9-5 must not be marked shipped — Lane A (#1203) is a DRAFT with one "
            "commit at 28e4990, block cleared by #1200 but not yet rebased/reviewed/merged"
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
    """9/9 decision_runs stamp the literal 'unknown'."""
    assert "decision_runs.git_sha" in both or "git_sha" in both
    assert "unknown" in both
    assert "api.py:154-157" in both, "the healthcheck already resolves this — cite the fix shape"


def test_git_sha_span_claim_is_two_not_four(ledger: str, backlog: str):
    """The run-set spans TWO deployed SHAs, not four.

    Regression guard for an erratum caught pre-merge in this lane's own first
    draft: it read the period's DEPLOYMENT LIST (8d93621 -> 1386834 -> f34d5cd ->
    bef2cdd) and called it four. But the count of SHAs a run-set spans is a JOIN
    against deployment WINDOWS, not a list of deployments in the period —
    `1386834` lived ~5min with no decision cycle, and `bef2cdd` deployed after the
    day's last cycle. The 9 runs sit under exactly two: `8d93621` (five 07-13
    runs) and `f34d5cd` (four 07-14 runs). Two SHAs with one identical stamp is
    already sufficient proof; overclaiming four would have been a stretch a
    reviewer could refute in one query.
    """
    for name, doc in (("ledger", ledger), ("backlog", backlog)):
        assert re.search(r"TWO distinct deployed SHAs", doc), (
            f"the {name} must state the SHA span as TWO"
        )
        assert not re.search(r"(?i)\bfour\b[^\n]{0,30}deployed SHAs", doc), (
            f"the {name} overclaims the deployed-SHA span"
        )


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


def test_credential_hygiene_doctrine_preserved(ledger: str):
    """Names-only diffs; never list_variables/printenv/env; never emit values.

    (Replaces an earlier `test_credential_incident_not_fabricated`, deleted with
    the credential-incident paragraph it pinned — operator decision 07-14 to drop
    that item entirely, so no security disposition is recorded either way. The
    standing hygiene doctrine below is independent of that item and still binds.)
    """
    assert "list_variables" in ledger, "the hygiene doctrine names the forbidden calls"
    assert re.search(r"NAMES\*?\*? only", ledger), "names-only diffs"
    assert "never values" in ledger.lower()


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


# --------------------------------------------------------------------------
# 12. 2026-07-15 universe-census adjudication — durable corrections only
#     (NO transient counts pinned as permanent strategy truth: '78 active' /
#     'universe_size=10' are recorded as FACTS in the docs but are deliberately
#     NOT asserted here, because they change and must not become brittle guards.)
# --------------------------------------------------------------------------

def test_census_62_is_force_close_stop_not_entry_gate(both: str):
    """$62.04 is a q15 mark-based force-close on open-position UPL, never an
    entry max-loss gate — the correction must not silently revert."""
    assert "NOT an entry max-loss gate" in both
    assert re.search(r"mark-based FORCE-CLOSE", both, re.IGNORECASE)
    assert "risk_envelope.py:444" in both


def test_census_binary_ev_labelled_lower_bound(both: str):
    """The PoP*credit - (1-PoP)*max_loss calc is a lower bound, not true EV;
    'negative economics' from it is never 'proven negative'."""
    assert re.search(r"BINARY MAX-LOSS LOWER\s+BOUND", both, re.IGNORECASE)
    assert "True credit-spread EV remains NOT_PROVEN pending queue-⑤" in both


def test_census_bkng_suitability_distinction_and_not_missed(both: str):
    """Ticker suitability != structure suitability; 'BKNG was missed' is
    recorded ONLY as the prohibited framing, never as a fact."""
    assert re.search(r"ticker suitability is DISTINCT from structure suitability",
                     both, re.IGNORECASE)
    assert 'Do NOT record "BKNG was missed."' in both


def test_census_no_ticker_change_from_one_snapshot(both: str):
    assert "No ticker activation/deactivation is justified from one snapshot" in both
    assert "no automatic reactivation of AAL/F/LYFT" in both


def test_census_width_rider_is_observe_only(both: str):
    """The $1-vs-$5 width work is a shadow rider on ①+②+③ — no live width change."""
    assert "SMALL-TIER WIDTH RIDER" in both
    assert re.search(r"no live config change\s+until its falsifier clears",
                     both, re.IGNORECASE)


def test_census_deduped_not_filed_list_present(backlog: str):
    """The do-not-file list guards against re-filing dupes an audit would waste
    a slot on."""
    assert "DEDUPLICATED" in backlog
    assert "empty execution universe" in backlog
    assert "stop-loosening" in backlog


def test_census_funnel_pack_extends_not_duplicates(backlog: str):
    """The funnel truth pack must EXTEND the existing mislabel item, not mint a
    second identifier for the same defect."""
    # exactly one pack (no second identifier for the same defect), and it
    # states it EXTENDS the pre-existing mislabel item.
    assert backlog.count("FUNNEL TELEMETRY TRUTH PACK") == 1
    assert "EXTENDS the existing" in backlog
    assert re.search(r"EXTENDS the existing[\s\S]{0,80}mislabel", backlog)


# --------------------------------------------------------------------------
# 13. 2026-07-15 v1.5 external-audit adjudication — brief vs results contract
# --------------------------------------------------------------------------

V15_BRIEF = REPO_ROOT / "docs" / "review" / "external-full-audit-v1.5-current.md"
V15_RESULTS = REPO_ROOT / "docs" / "review" / "external-full-audit-v1.5-results-2026-07-15.md"


def test_v15_one_brief_and_one_distinct_results_file():
    """The brief is the charter; the results file is a distinct completed report."""
    assert V15_BRIEF.is_file(), "the v1.5 brief must remain (charter)"
    assert V15_RESULTS.is_file(), "the completed v1.5 results file must exist"
    brief = V15_BRIEF.read_text(encoding="utf-8")
    results = V15_RESULTS.read_text(encoding="utf-8")
    assert brief != results
    # the brief carries charter imperatives; the results carry completed dispositions
    assert "THE TEN AREAS — KEEP THESE TEN" in brief
    assert "REQUIRED OUTPUT — IN THIS ORDER" in brief
    assert "Executive verdict" in results
    # a v1.5 charter instruction must not be mislabeled as a finding in results
    assert "THE TEN AREAS — KEEP THESE TEN" not in results


def test_v15_results_has_completed_dispositions_not_brief_imperatives():
    """Results must show completed E-dispositions (PASS/CONDITIONAL/...), not
    the brief's 'determine/verify' imperatives as if answered."""
    results = V15_RESULTS.read_text(encoding="utf-8")
    assert re.search(r"E1\s*\|\s*\*\*PASS\*\*", results), "E1-E20 table with dispositions"
    assert "CONDITIONAL" in results and "PASS" in results
    assert "RUNNING" in results and "UNSTARTED" in results, "W1-W5 table with statuses"


def test_v15_backlog_and_ledger_cite_the_results_file(backlog: str, ledger: str):
    fn = "external-full-audit-v1.5-results-2026-07-15.md"
    assert fn in backlog, "backlog must cite the results file, not the brief"
    assert fn in ledger, "ledger must cite the results file, not the brief"


def test_v15_adjudication_section_present_in_both(backlog: str, ledger: str):
    assert "v1.5 EXTERNAL-AUDIT ADJUDICATION" in backlog
    assert "ADJUDICATED: external full audit v1.5" in ledger


def test_v15_top_safety_finding_retained_once(backlog: str, ledger: str):
    """The headline live-entry finding is retained (not 'empty execution
    universe'), present in both docs, and the two-site framing survives."""
    for doc in (backlog, ledger):
        assert "F-MIDDAY-POSITION-READ-FAILOPEN" in doc
        assert "2 sites" in doc or "two site" in doc.lower()
    # its safety lane is explicit, above observational cleanup
    assert re.search(r"F-MIDDAY-POSITION-READ-FAILOPEN[\s\S]{0,400}(safety|fail-closed|fail OPEN|fail-open)",
                     backlog, re.IGNORECASE)


def test_v15_rejected_finding_in_exclusion_memory(ledger: str):
    """Internal-fill sign was adjudicated NOT PROVEN — it must sit in the
    ledger's REJECTED block so a future audit does not rediscover it."""
    assert "Internal-fill close-price sign" in ledger
    m = re.search(r"Internal-fill close-price sign[\s\S]{0,200}", ledger)
    assert m and ("NOT PROVEN" in m.group(0) or "REJECTED" in m.group(0))


def test_v15_first_operator_decision_is_shadow_capital_parity(both: str):
    assert re.search(r"(first operator decision|FIRST OPERATOR DECISION)", both)
    assert "shadow-capital parity" in both or "shadow capital parity" in both.lower()
    assert "48" in both  # the $100k-vs-$2k ratio is load-bearing


def test_v15_falsifier_grades_still_accurate(both: str):
    """The v1.5 adjudication must not contradict the graded falsifier results."""
    # #1200/#1201 remain PASS; #1200 stays INCONCLUSIVE-on-no-candidate rule intact
    assert "INCONCLUSIVE" in both
    assert "F-A9-5" in both and "56" in both  # materialized-lie count recorded


def test_v15_results_file_no_credential_values():
    if not V15_RESULTS.is_file():
        pytest.skip("results file absent")
    text = V15_RESULTS.read_text(encoding="utf-8")
    for pattern, label in SECRET_SHAPES:
        hit = re.search(pattern, text)
        assert hit is None, f"v1.5 results file contains a {label}-shaped string"


# --------------------------------------------------------------------------
# 14. v1.5 results — document-contract completeness + corrected-claim guards
#     (prove the report contract, not mere word presence)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def v15() -> str:
    return V15_RESULTS.read_text(encoding="utf-8")


def test_v15_e1_e20_enumerated_once_with_dispositions(v15: str):
    """E1..E20 each appear as a table row exactly once with a disposition."""
    valid = ("PASS", "CONDITIONAL", "REOPENED", "NOT_PROVEN", "NOT PROVEN")
    for n in range(1, 21):
        rows = re.findall(rf"\|\s*E{n}\s*\|\s*\*\*([A-Z_ ]+)\*\*", v15)
        assert len(rows) == 1, f"E{n} must appear exactly once with a disposition (got {rows})"
        assert rows[0].strip() in valid, f"E{n} disposition invalid: {rows[0]}"


def test_v15_w1_w5_enumerated_once_with_status(v15: str):
    for n in range(1, 6):
        assert re.search(rf"\|\s*W{n}\s*\|", v15), f"W{n} row missing"
    for status in ("RUNNING", "START-UNVERIFIED", "UNSTARTED"):
        assert status in v15, f"W-table status vocabulary incomplete: {status}"


def test_v15_a1_a10_have_pass_structure(v15: str):
    for area in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"):
        assert re.search(rf"\*\*{area} ", v15), f"{area} section missing"
    assert "Pass 1" in v15 and "DEFERRED-DORMANT" in v15, "A7 dormant passes must be explicit"


def test_v15_falsifier_grades_explicit_pass(v15: str):
    """Not merely that INCONCLUSIVE appears — #1200/#1201 are explicitly PASS."""
    assert "#1200 SOFI natural falsifier PASS" in v15
    assert "#1201 calibration PASS" in v15
    assert "#1201 thesis PASS" in v15


def test_v15_denominators_kept_separate(v15: str):
    """B5 — the live denominators are labeled, never a bare 'live n'."""
    assert "Post-epoch broker-live closes" in v15
    assert "All broker-live closes, total history" in v15
    assert re.search(r"live_eligible.{0,40}(routing).{0,40}(broker execution)", v15), \
        "routing vs broker-execution distinction must be explicit"


def test_v15_rejects_signal_quality_is_sound(v15: str, both: str):
    """B6 — the unsupported 'signal quality is sound' verdict must be gone."""
    assert "Signal quality is sound" not in v15
    assert "Signal quality is sound" not in both


def test_v15_rejects_reservation_equals_decision_identity(v15: str):
    """B3 — the false durable-identity claim must be gone; the narrowed
    order-not-identity statement present."""
    assert "reservation-id==decision-id VERIFIED" not in v15
    assert "no shared scan" in v15 or "no durable reservation identity" in v15


def test_v15_no_notrun_row_claims_observed_env_value(v15: str):
    """B4 — no single line combines 'RUNTIME CHECK — NOT RUN' with a claimed
    observed CONDOR_EV_MODEL value."""
    for line in v15.splitlines():
        if "CONDOR_EV_MODEL=tail" in line:
            assert "NOT RUN" not in line, (
                "a claimed observed condor value must not sit on a NOT-RUN line"
            )


def test_v15_rejects_in_place_capital_reseed(v15: str, both: str):
    """B8 — no instruction to rewrite/re-seed historical rows in place; the
    versioned-epoch decision + 'never rewrite historical' must be present."""
    assert "re-seed shadow portfolios to live scale" not in v15
    assert re.search(r"[Nn]ever rewrite historical", v15)
    assert "versioned" in v15 and "epoch" in v15


def test_v15_pr1203_not_described_zero_commit(both: str, v15: str):
    """B10 — nothing describes Lane A / #1203 as zero-commit."""
    for doc in (both, v15):
        assert "zero commit" not in doc.lower()


def test_v15_f_midday_causality_narrowed(both: str):
    """B11 — the finding is retained but not stated as an inevitable unsafe
    order; the P0 escalation trigger is present."""
    assert "F-MIDDAY-POSITION-READ-FAILOPEN" in both
    assert re.search(r"[Cc]ausality.{0,20}NOT inevitable", both) or "not inevitable" in both.lower()
    assert "P0-before-next-entry" in both


# --------------------------------------------------------------------------
# 15. v1.5 CHARTER-COMPLETION PATCH — parser-level structural guards
#     (R1-R4 truth corrections + C1-C10 charter structures). These PARSE the
#     report's tables/blocks and assert the document CONTRACT, not word
#     presence. Every guard below is exercised on the real file AND on a
#     mutated copy in test_v15_charter_mutations_each_bite — each mutation
#     must turn its guard red.
# --------------------------------------------------------------------------

def _cells(row: str) -> list:
    """Markdown table row → stripped data cells (outer pipes removed)."""
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _table(text: str, header_key: str):
    """Locate the first markdown table whose header line contains header_key;
    return (header_cells, [data_row_cells, ...]) skipping the separator row."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("|") and header_key in line:
            rows = []
            j = i + 2  # skip header (i) + separator (i+1)
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(_cells(lines[j]))
                j += 1
            return _cells(line), rows
    raise AssertionError(f"table with header {header_key!r} not found")


# ---- R1-R4 truth-correction guards ----

def _g_r1(t: str):
    """R1 — A7 says post-epoch(9 all-time), never equates 8 with total history."""
    assert "live broker closes = **8 total" not in t
    assert "closes = **8 total" not in t
    assert re.search(r"A7-1[\s\S]{0,200}8 post-epoch broker-live closes \(9 all-time", t), \
        "A7 denominator not scoped to post-epoch(9 all-time)"


def _g_r2(t: str):
    """R2 — Top-3 A6-2 is a versioned epoch, not an in-place reseed / DB op."""
    assert "parity re-seed" not in t
    assert "operator DB op" not in t
    _h, rows = _table(t, "Effort (single-dev")
    row2 = [r for r in rows if r and r[0] == "2"]
    assert row2, "Top-3 rank-2 row missing"
    assert "versioned live-tier cohort epoch" in row2[0][1]
    assert "newly versioned" in row2[0][9] and "NOT mutation of old" in row2[0][9]


def _g_r3(t: str):
    """R3 — F-MIDDAY fix tightens the FAILURE path (not 'no behavior change')."""
    assert "no decision-path behavior change" not in t
    assert re.search(r"intentionally changes the (FAILURE|failure) path", t)
    assert "does not loosen a threshold, gate, stop" in t


def _g_r4(t: str):
    """R4 — five-way window durability taxonomy, no '4/5 logs-only' collapse."""
    assert "4 of 5 windows INFO/logs-only" not in t
    assert not re.search(r"4 ?/ ?5 window", t)
    assert "only W1/W2 are strictly logs-only" in t
    assert "W3 is partially durable" in t and "W4 is semi-durable" in t


# ---- C1-C9 charter-structure guards ----

def _g_pass_matrix(t: str):
    """C1 — A1..A10 each exactly once with three non-empty Pass cells."""
    _h, rows = _table(t, "Pass 1 (state")
    areas = [r[0] for r in rows]
    for a in [f"A{i}" for i in range(1, 11)]:
        assert areas.count(a) == 1, f"{a} not exactly once in the pass matrix"
    for r in rows:
        assert len(r) >= 9, f"pass-matrix row too few cells: {r[0]}"
        for k in (1, 2, 3):
            assert r[k] and r[k] not in ("—", "-"), f"empty Pass cell in {r[0]}"


def _g_register(t: str):
    """C2 — every finding-register block has all 12 fields; FR ids unique."""
    heads = re.findall(r"### (FR-\d+) ·", t)
    assert len(heads) >= 15, f"too few register entries: {len(heads)}"
    assert len(heads) == len(set(heads)), f"duplicate FR id: {heads}"
    for part in re.split(r"\n### FR-", t)[1:]:
        block = "### FR-" + part
        m = re.match(r"### (FR-\d+)", block)
        if not m:
            continue
        fid = m.group(1)
        block = re.split(r"\n## ", block)[0]  # stop at the next H2 section
        for i in range(1, 13):
            assert f"**{i}." in block, f"{fid} missing field {i}"


def _g_w_table(t: str):
    """C3 — W1..W5 each once with all columns; sample never reuses a run-state."""
    _h, rows = _table(t, "First-valid boundary (UTC")
    ws = [r[0] for r in rows]
    for w in [f"W{i}" for i in range(1, 6)]:
        assert ws.count(w) == 1, f"{w} not exactly once"
    for r in rows:
        assert len(r) >= 13, f"{r[0]} too few columns"
        assert r[5], f"{r[0]} missing sample/sufficiency"
        assert r[5] not in ("RUNNING", "START-UNVERIFIED", "UNSTARTED"), \
            f"{r[0]} reuses a run-state word as sample/sufficiency"
        assert r[8], f"{r[0]} missing exact runtime check"
        assert r[12], f"{r[0]} missing verdict"
    assert "strictly logs-only" in t and "partially durable" in t and "semi-durable" in t


def _g_runtime_table(t: str):
    """C4 — every runtime-check row has read/source/PASS/FAIL/rationale/status."""
    _h, rows = _table(t, "Exact read / query")
    assert len(rows) >= 6, f"too few runtime checks: {len(rows)}"
    for r in rows:
        assert r[0].startswith("RC-"), f"bad RC id {r[0]}"
        assert len(r) >= 7, f"{r[0]} too few columns"
        for k in (1, 2, 3, 4, 5, 6):
            assert r[k], f"{r[0]} empty column {k}"
        assert "NOT RUN" in r[6], f"{r[0]} status is not NOT RUN"
        assert "CONDOR_EV_MODEL=tail" not in " | ".join(r)


def _g_instrument_table(t: str):
    """C5 — every instrument row carries natural-proof + exact-runtime-check."""
    _h, rows = _table(t, "Natural proof (observed")
    assert len(rows) >= 9, f"too few instrument rows: {len(rows)}"
    for r in rows:
        assert len(r) >= 9, f"instrument row too few cols: {r[0]}"
        assert r[6], f"{r[0]} missing natural proof"
        assert r[7], f"{r[0]} missing exact runtime check"


def _g_dep_and_top3(t: str):
    """C7/C8 — dependency matrix (8 fields) + Top-3 (10 fields) fully populated."""
    _h, dep = _table(t, "Supersedes / duplicates")
    assert len(dep) >= 8, f"too few dependency rows: {len(dep)}"
    for r in dep:
        assert len(r) >= 8, f"dep row too few cols: {r[0]}"
        for k in range(8):
            assert r[k], f"dep row empty col {k}: {r[0]}"
    _h2, top = _table(t, "Effort (single-dev")
    assert [r[0] for r in top[:3]] == ["1", "2", "3"], "Top-3 ranks must be 1/2/3"
    for r in top[:3]:
        assert len(r) >= 10, f"top-3 row too few cols: {r[0]}"
        for k in range(10):
            assert r[k], f"top-3 empty col {k} in rank {r[0]}"


def _g_basis_unit(t: str):
    """C6 — every economic row has a valid basis+unit; inline tags present."""
    _h, rows = _table(t, "Economic claim")
    assert len(rows) >= 10, f"too few basis/unit rows: {len(rows)}"
    bases = {"raw", "calibrated", "realized", "unknown", "n/a"}
    units = ("per-contract", "position-total", "score-points", "probability",
             "unknown", "ratio", "ev-multiplier")
    for r in rows:
        assert len(r) >= 5, f"basis/unit row too few cols: {r[0]}"
        assert r[3] and r[4], f"empty basis/unit in {r[0]}"
        base_tok = r[3].split()[0].lower().rstrip(",")
        assert base_tok in bases or r[3].lower() in bases, f"bad basis {r[3]!r} in {r[0]}"
        assert any(u in r[4].lower() for u in units), f"bad unit {r[4]!r} in {r[0]}"
    assert "[basis=realized, unit=position-total]" in t
    assert re.search(r"\[basis=raw", t)


def _g_design_score(t: str):
    """C9 — weights sum 100, earned sum == displayed scalar, label INFERRED."""
    _h, rows = _table(t, "Earned")
    wsum = esum = 0
    for r in rows:
        if r[0].replace("*", "").strip().lower() == "total":
            continue
        if len(r) >= 4 and r[1].isdigit() and r[3].isdigit():
            wsum += int(r[1])
            esum += int(r[3])
    assert wsum == 100, f"weights sum {wsum} != 100"
    m = re.search(r"INFERRED design-maturity score = (\d+) / 100", t)
    assert m, "reproducible design-maturity scalar missing"
    assert int(m.group(1)) == esum, f"displayed {m.group(1)} != earned sum {esum}"
    assert "INFERRED" in t and "85" in t


# ---- real-file tests (each guard passes on the committed report) ----

def test_v15_r1_a7_denominator_scoped(v15: str):
    _g_r1(v15)


def test_v15_r2_top3_versioned_epoch_not_reseed(v15: str):
    _g_r2(v15)


def test_v15_r3_midday_tightens_failure_path(v15: str):
    _g_r3(v15)


def test_v15_r4_window_five_way_taxonomy(v15: str, both: str):
    _g_r4(v15)
    assert "strictly logs-only" in both  # corrected in ledger + backlog too


def test_v15_c1_pass_matrix_complete(v15: str):
    _g_pass_matrix(v15)


def test_v15_c2_finding_register_twelve_fields(v15: str):
    _g_register(v15)


def test_v15_c3_window_table_complete(v15: str):
    _g_w_table(v15)


def test_v15_c4_runtime_check_table_complete(v15: str):
    _g_runtime_table(v15)


def test_v15_c5_instrument_table_complete(v15: str):
    _g_instrument_table(v15)


def test_v15_c6_basis_unit_tags(v15: str):
    _g_basis_unit(v15)


def test_v15_c7_c8_dependency_and_top3_complete(v15: str):
    _g_dep_and_top3(v15)


def test_v15_c9_design_score_reproducible(v15: str):
    _g_design_score(v15)


def test_v15_charter_key_invariants_preserved(v15: str, both: str):
    """C-consolidated — falsifier grades, denominators, credential hygiene,
    #1203 status, brief/results distinction, rejection memory stay correct."""
    assert "#1200 SOFI natural falsifier PASS" in v15
    assert "#1201 calibration PASS" in v15 and "#1201 thesis PASS" in v15
    assert "Post-epoch broker-live closes" in v15
    assert "All broker-live closes, total history" in v15
    assert "OPERATOR-ATTESTED" in v15
    assert "zero commit" not in v15.lower() and "zero commit" not in both.lower()
    assert "external-full-audit-v1.5-results-2026-07-15.md" in both


def test_v15_charter_mutations_each_bite(v15: str):
    """Every corrected-away defect, when reintroduced, turns its guard red."""
    mutations = [
        ("remove a Pass cell",
         lambda s: s.replace("`ReplayTruthLayer.from_decision_id` zero production callers", ""),
         _g_pass_matrix),
        ("remove a finding field",
         lambda s: s.replace("- **6. Instrument path + durable sink:**", "- ", 1),
         _g_register),
        ("duplicate a finding id",
         lambda s: s + "\n### FR-01 · duplicate id\n- **1. x:** y\n",
         _g_register),
        ("remove W3 exact runtime check",
         lambda s: s.replace(
             "query `risk_alerts` for the bucket would-block type over an armed window "
             "AND confirm INFO reservation-order emit", ""),
         _g_w_table),
        ("remove expected FAIL from a runtime row",
         lambda s: s.replace("env unset/strict on the bg worker (code default)", ""),
         _g_runtime_table),
        ("remove a basis/unit tag",
         lambda s: s.replace(
             "| MIN_EDGE_AFTER_COSTS gate | §6 (ranker) | edge floor | raw | position-total |",
             "| MIN_EDGE_AFTER_COSTS gate | §6 (ranker) | edge floor |  | position-total |"),
         _g_basis_unit),
        ("reintroduce 8 total",
         lambda s: s + "\nlive broker closes = **8 total**\n",
         _g_r1),
        ("reintroduce parity re-seed",
         lambda s: s + "\nA6-2 shadow-capital parity re-seed\n",
         _g_r2),
        ("reintroduce no decision-path behavior change",
         lambda s: s + "\nno decision-path behavior change\n",
         _g_r3),
        ("reintroduce 4/5 windows logs-only",
         lambda s: s + "\n4/5 windows logs-only\n",
         _g_r4),
        ("displayed design score != earned points",
         lambda s: s.replace("INFERRED design-maturity score = 60 / 100",
                             "INFERRED design-maturity score = 72 / 100"),
         _g_design_score),
    ]
    for label, mutate, guard in mutations:
        mutated = mutate(v15)
        assert mutated != v15, f"mutation {label!r} did not change the text"
        with pytest.raises(AssertionError):
            guard(mutated)
