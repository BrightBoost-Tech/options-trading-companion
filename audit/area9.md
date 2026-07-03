# AREA 9 — ALERT & SIGNAL INTEGRITY (STANDING, PERMANENT — graduated)

**GRADUATED to standing:** 2026-07-03, by owner decision (first exercise of the
graduation rule; founding finding shipped #1106 + #1115 with measured impact —
39→0 job-arm false HIGHs). Does not rotate; the rotating slot moved to Area 10.
This spec is FROZEN as the standing contract (edit only on owner-recorded change).

**Adopted:** 2026-07-02 (v5.1 run 1; slot was OPEN — prior occupant Entry-Fill Efficacy was
retired as an erroneous A8 adoption, carrying no incumbency here). **Replaces:** none.

**Rationale for adoption:** A1–A7 audit the trading pipeline; A8 audits its negative
decisions; every one of them TRUSTS the alert/signal layer as its instrument. Nothing audits
the instrument. The system already maintains a "Known Liars" list for displays and debug
prints (CLAUDE.md §8) — but no standing measurement exists for whether `risk_alerts` rows
tell the truth about their own trigger. The cost is concrete and already realized: the
2026-07-01 audit itself mislabeled 4 high-severity `ops_data_stale` alerts as a
"chronic calibration-freshness artifact" because the alert's message says "Market data is
stale" while its own details said `stale_symbols=[] / Reason: ok` — the alert lied about its
source, and the audit (and any operator) was deceived. With `OPS_ALERT_WEBHOOK_URL` about to
go live (standing TOP-3 #1), every self-contradictory high egresses to the operator's phone:
a cry-wolf channel buries exactly the criticals it was built to carry. A structurally
dishonest alert is a phantom-read generator for EVERY other area.

**Goal:** Measure, from this system's own `risk_alerts` rows and code, whether each
alert_type's content (message, severity, metadata) faithfully reflects the predicate that
fired it — so alert-layer regressions (mislabeled source, self-contradictory content,
severity inflation, fingerprint collapse) are caught by data instead of by an operator
noticing the message reads wrong.

## Look-at list (each run)

1. **Self-contradiction rate per alert_type (30d):** rows whose message/metadata contradict
   their own details (e.g. "is stale" + `stale_symbols=[]` + `Reason: ok`). Track the rate
   day-over-day per type.
2. **Message-source vs trigger-source wiring:** for any alert built from multiple OR'd
   predicates, does the emitted content come from the arm that actually fired?
   (`ops_health_check.py:117` vs `:139-149` is the type case.)
3. **Fingerprint/cooldown integrity:** does the fingerprint distinguish genuinely different
   triggers (per-source, per-symbol), or does one fingerprint swallow distinct conditions so
   cooldown suppresses a NEW condition as a repeat?
4. **Egress-channel noise budget:** of the alerts that WOULD egress once the ops webhook is
   set (ops channel + `_RISK_EGRESS_ALERT_TYPES`), what fraction of the last 30d would have
   been false/self-contradictory? Report it as alerts/day the operator would have received
   wrongly.
5. **Severity honesty:** alert_types whose severity is fixed at write-time regardless of
   magnitude (a 54-second "staleness" high vs an 11-minute one carries identical severity);
   flag inflation/deflation only when it changes an operator decision (e.g. H11 sweep
   membership).
6. **Known-liars regression check:** the ledgered display-layer liars (EXIT_EVAL_DEBUG flat
   prints, Alpaca chart) stay ledgered — this lens covers the ALERT layer only; a new liar
   found elsewhere is reported to the area that owns that surface.

## Constraints

- READ-ONLY: SELECT-only SQL + code reads; never mutes, rewrites, or acknowledges an alert.
- An alert that is NOISY but honest (correct content, unfortunate threshold) is a tuning
  note for the owning area, not an integrity finding — integrity findings require the
  content to be WRONG about the trigger.
- Never propose deleting/suppressing an alert class as the fix — additive corrections only
  (fix the wiring, split the fingerprint, add the missing source field). Suppression
  proposals belong to the owner.

## Disqualifiers

- Re-finding ledgered items: the 30-min-threshold-vs-daily-cadence data_stale false-positive
  ROOT CAUSE (ledger 2026-06-10 A4 line), N2 delivery path (pre-approved), ghost_position
  shadow-sweep noise (ledgered P2→P1), EXIT_EVAL_DEBUG (ledgered). The NEW surface here is
  content/wiring integrity, not those predicates' existence.
- N=1 mislabeled alert presented as a verdict; a finding requires a rate + mechanism.
- "Log more" without a quantified decision consequence (which operator/audit decision was or
  would be wrong because the alert lied).
- Anything that loosens a risk control, expands the loop's write permissions, or edits the
  contract. Graduation to a standing area requires an explicit owner decision in the ledger
  — never automatic.

---

*First audit under this spec: 2026-07-02 (see `audit/reports/2026-07-02.md` §A9 — FINDING,
confirmed two-source: `ops_data_stale` fired 69× in 30d; **57/69 (83%) self-contradictory**
("Market data is stale ... Stale: 0 ... Reason: ok"); mechanism at
`jobs/handlers/ops_health_check.py:117` (OR of market_freshness | job_freshness) vs
`:139-149` (message + details built from market_freshness ONLY) — every job-arm firing wears
a market-data costume. The job arm is the ledgered 30-min-vs-daily-cadence predicate
(`ops_health_service.py:198-227`, `DATA_STALE_THRESHOLD_MINUTES=30` against
suggestions_open/close that run 1×/day each) — root cause ledgered 2026-06-10, STILL FIRING;
what's new is the mislabel. Fingerprint built from empty `stale_symbols[:5]` + source →
one fingerprint for all job-arm firings (`:124-128`). Realized diagnostic cost: the 07-01
audit report itself mislabeled the class. Projected egress cost: ~2–4 false highs/RTH-day to
the ops webhook the day it is set.)*
