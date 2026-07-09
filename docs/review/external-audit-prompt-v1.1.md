# External Audit Prompt — v1.1 (eleven-area)

> **PROVENANCE / READ FIRST.** This file is the *methodology* prompt an
> external reviewer (or model) runs against the platform, paired with the
> data briefing in [`2026-07-09-external-packet.md`](2026-07-09-external-packet.md).
> **Version: external prompt v1.1 · aligned to internal `audit/v5-prompt.md`
> v5.5 (eleven-area) · date 2026-07-09 · supersedes: none (first external cut).**
> The body below is assembled from the in-repo nightly-audit framework
> (`audit/v5-prompt.md` v5.5 + `audit/area8.md`/`area9.md`/`area10.md`),
> reframed and **redacted for an outside reader with full code access but no
> DB / Railway / broker access.** If the operator holds a canonical v1.1 text
> that differs, that text wins — reconcile before external handoff (this
> reconstruction stands until then; no canonical text was supplied at v5.5).
>
> **STATE block re-stamped 2026-07-09 EOD** (to match v5.5's refresh). ⚠ REFRESH
> the STATE section again after the **2026-07-10 16:00Z** first-calibrated-scan
> proof before handing this to an external reviewer — several STATE facts flip
> that morning.
>
> **Redaction rules (applied):** the live brokerage account is "the live
> account"; the operator identity is "the owner"; the three books are
> **champion / neutral / conservative**. No account numbers, UUIDs,
> connection strings, keys, or webhook/ping URLs. **Dollar P&L and equity are
> REAL and included** — the ~$2k scale is the story.

---

## ROLE

You are a senior quantitative engineer reviewing a LIVE, real-money,
fully-automated options-income platform running in explicit **learning mode
(correctness > capital deployment; low trade frequency is a feature)**. Stack:
Python 3.11 / FastAPI · Postgres · a background worker fleet (every merge
auto-deploys and recycles all workers; the repo squash-merges — verify
deployed code by content at the squashed commit, never assume merged ==
running) · a live options-L3 margin account at **~$2k equity** plus a paper
mirror · defined-risk structures only (iron condors, vertical debit spreads)
at 1–7 contracts. Three books run the same signal: **champion** (live money)
plus **neutral** and **conservative** (shadow — internal fills, no capital).

## FOUR-SOURCE TRUTH DOCTRINE (precedence, low → high)

1. **CODE** — what's written. Read it; comments/docstrings routinely describe
   unbuilt behavior.
2. **DATABASE** — what happened (rows of record are authoritative; stored
   marks / unrealized P&L are NOT — they lag and can be wrong-signed).
3. **RUNTIME** — what is actually deployed and running (commit + container
   start + effective env).
4. **BROKER** — fills, positions, buying power. Outranks everything.

Multi-source agreement = a FINDING. Anything else = a HYPOTHESIS, labeled,
with what would confirm it. **If two sources disagree, the disagreement IS the
finding — report it, never average it.** Displays lie the way marks lie; the
decision path is the only truth. Verify before asserting — including your own
confident reads.

## HOW TO WORK

- Plan before reading; state the plan in ≤10 lines, then execute.
- Every WHERE is a `file:line` you verified this run. Every IMPACT is
  quantified from this system's own data (the packet's ledgers/tables).
- **"No high-value finding" is a valid, creditable answer. Do not pad.**
- A finding must either **contradict or extend** the packet's framing; merely
  confirming it is a weak finding.
- Never propose loosening a risk control on outcome or hindsight. A losing
  trade that passed every gate is not evidence a gate is wrong; a killed trade
  that would have won is one counterfactual data point, not a loosening
  argument. A **proven arithmetic error** is the only basis for passing more
  trades — and even then, cautiously.

---

## THE ELEVEN AREAS

For each: answer its charter with something NOT already in the packet, or give
a 1–3 line "unchanged, conditions checked." Per finding: **WHAT · WHERE
(file:line) · WHY it's #1 for this area · IMPACT (quantified) · HOW to fix ·
EVIDENCE · does it touch the live close/stop path? · CONFIDENCE.**

**A1 — PROFITS.** What would most improve the system's ability to make money,
and what is the CURRENT binding constraint — edge, volume, universe,
structure, or scale? Components: honest-EV ordering vs live outcomes as closes
accrue; structural economics (arithmetic, not outcomes); and **sizing custody**
— the allocator → risk-budget → small-account-compounder path, historically
where findings die. Hard guardrail: at single-digit live closes, profit
findings must be structural/arithmetic — outcome-pattern findings are
disqualified regardless of confidence.

**A2 — MINIMIZING LOSSES.** The single most likely way the system loses money
it shouldn't, and what ADDITIVE control prevents it. Custody: exit/close-path
integrity — exit evaluator, stop/clamp chain, force-close, single-submitter,
the resting take-profit pilot. (Latent: correlated one-book exposure the
moment ≥2 live positions coexist.)

**A3 — SELF-LEARNING.** What most improves what/how fast the system learns
from its own outcomes. The calibration loop trains on **live outcomes only**;
below 8 live post-epoch closes it serves ×1.0 (do-no-harm); a clamp floor and
an anti-overfit winsorize guard tiny-N fits.

**A4 — SELF-SUSTAINING.** Which silent failure would take longest to notice,
and what makes it loud? (The oversight layer — delivery receipts, silent-
failure detector, dead-man ping — is the current answer; find the next gap.)

**A5 — EFFICIENCY.** Where is spend (tokens, API calls, scan work) buying no
information? Own the alert-noise classes.

**A6 — TRADING VOLUME / VIABLE-SET HANDLING.** What most improves a viable
name's path from scan to fill — and is the viable-set definition still true?
(Today ~1 of ~78 names clears the round-trip cost floor cleanly; the binding
constraint is per-contract executable cost vs typical structure EV.)

**A7 — TIME IN TRADE.** Can average hold shorten WITHOUT degrading realized
edge? (Currently coupled to A2's exit path; treat as a rider until the live
close count supports independent analysis.)

**A8 — NEGATIVE-DECISION EFFICACY.** Are the NOs correct — which rejection
class most likely hides money on the table, provably? Distinguish
economics/structure rejections from capital-state/error rejections. (Sentinel:
a name kept in the universe *because* it never clears the gate; if it ever
clears, that is itself the finding.)

**A9 — ALERT & SIGNAL INTEGRITY.** Which of the system's own signals most
misleads its reader right now? New alert writers must use the current typed
taxonomy; a new pre-split-style "costume" type is a finding. Fresh territory:
new liars, known-liar completeness, noise classes poisoning the alert
baseline.

**A10 — CALENDAR & CLOCK INTEGRITY.** Which time boundary next composes
correct components into a wrong system? (Look-list: holiday sessions, the
DST/winter-close boundary, month/quarter rolls.) Ground every timestamp
against both the DB clock and the broker clock before any date arithmetic —
**the clocks win over any header or assumption.**

**A11 — STRUCTURAL VIABILITY & SCALE (the external's headline remit).** Given
the code and the packet evidence: **is the per-contract cost floor a dead-end
at this account size** — can a ~$2k defined-risk options book ever clear real
executable costs often enough to learn — and **what would you change first**
(account scale, structure class, universe, or the cost model)? Trade cadence
is ≈1 live close/week; every learning/promotion gate needs 10–15. This is the
central tension the review exists to pressure-test.

---

## THE TWO QUESTIONS WE MOST WANT OUTSIDE EYES ON (from the packet §1)

1. **Trace why the calibration multiplier computes and stores but returns
   ×1.0 at application** (the `_overall`-only blob vs the `{strategy:{regime}}`
   return-shape the apply path consumes). Is the protection inert?
2. **Structural viability at ~$2k** (= A11).

## STATE (stamped 2026-07-09 EOD — verify cheaply; REFRESH after 07-10 16:00Z)

- Live edge dataset: **9 real closes all-time (1W/8L, −$262); post-epoch 8
  (1W/7L, −$178)**; equity ≈ **$2,068**. This is the entire real-money edge
  sample — small and currently losing, by design of learning mode.
- **Calibration is now ENABLED (`CALIBRATION_ENABLED=1` since 07-09 21:29Z).**
  Root cause of "the multiplier isn't reaching the scan" was a stale
  `CALIBRATION_ENABLED=0` (since the 06-11 epoch — RAW EV served for ~a month;
  fail-loud logs added). First calibrated PRODUCTION scan pends **07-10 16:00Z**.
  ⚠ **RE-SCOPE:** a persisted `ev == ev_raw×0.5` proves the multiplier reaches
  the persisted ev + the final round-trip gate ONLY — apply is downstream of
  selection/sizing, so SCORE/SELECTION/SIZING consume RAW ev regardless. Do not
  read the proof as "calibration changed which trades were selected."
- **Live-close custody has a LATENT hole (queued #1 build):** a raised submit
  exception can fall through to an internal fill on a live position (never fired
  — all 9 closes broker-reconciled). The broker-acknowledged-close invariant is
  the next build.
- **Risk stack is book-blind** (no per-position cost/max-loss columns → the
  allocator/RBE see the open book as ~$0; utilization costs candidates at premium
  not max-loss). Reached in practice: **3 concurrent** live positions ran
  06-11→06-12 (not the once-assumed ≤1).
- Entry funnel correctly near-zero at ~$2k (round-trip cost ≈ EV). The entry-gate
  qty-scaling fix is **observe-only on live** (default-OFF flag); shadow-detection
  value-match + calibration fail-loud shipped 07-09 EOD.
- Greedy-stop candidate loop DOWNGRADED (replay: the budget break never fired).
- Breaker: N=3 consecutive live losses pause entries; an **edge-trigger content
  fingerprint** means a standing already-reviewed window does NOT re-pause —
  only a NEW loss re-trips (suppression proven live 07-09). Recovery is
  operator-only.

## OUTPUT

Header with the grounded clock time and a run-limitation note (no broker/DB/
runtime access → broker-dependent claims are hypotheses). Then A1–A11: each
charter answered, or a 1-line "unchanged, conditions checked." Then: the top
3 by value/effort/risk, conflicts & synergies, any four-source disagreements.
**Recommend nothing that loosens a risk control. Implement nothing. Diagnose
only.** STOP.
