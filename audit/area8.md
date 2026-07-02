# AREA 8 — NEGATIVE-DECISION EFFICACY (the counterfactual lens: "the road not taken")

**Adopted:** 2026-06-10 (first Area 8 spec, v5 run 1). **Replaces:** none (slot was empty).
**RESTORED:** 2026-07-02 by owner correction (v5.1 contract) — the 2026-07-01 swap to
Entry-Fill Efficacy was ADOPTED IN ERROR and is REVERTED. A8 is a GRADUATED STANDING AREA
(audited every run like A1–A7; it does NOT rotate — the rotating slot is Area 9). The
superseded Entry-Fill Efficacy spec is preserved below (move-don't-lose), RETIRED, not
relocated.

**Rationale for adoption:** Areas 1–7 share one structural condition — every evidence base they are chartered to read (realized P&L, fills, hold times, calibration inputs, funnel COUNTS) is conditioned on a candidate having SURVIVED every gate. The pipeline's negative decisions (~2,400/30d: scanner rejects, dismissals, NOT_EXECUTABLE blocks, executor risk blocks) have zero outcome measurement anywhere in the live system, so a wrong gate is invisible in data and is only ever caught by a code-reading audit (#1044 and #1047 both were; #1047 ran 11 days, ~250 would-pass kills). Area 6 sees reject counts but its objective is volume, not reject CORRECTNESS in dollars; Area 3 audits integrity of collected outcomes — data about non-trades is never collected at all. This is a missing lens, not a deeper version of an existing one.

**Goal:** Measure, in dollars from this system's own data, whether the pipeline's reject/block/dismiss decisions are correct — per gate and per reason — so that gate regressions become data-detectable (bounded detection latency) instead of code-audit-only, and so the survivorship bias in the learning loop is quantified rather than invisible.

## Look-at list (each run)

1. **Negative-decision inventory (30d, day-over-day):** `suggestion_rejections` count + reason mix; `trade_suggestions` rows in status dismissed / NOT_EXECUTABLE / blocked; executor blocked results in `job_runs.result` (e.g. `reason:"risk_envelope_breach"`); which of these carry a reconstructable structure (full OCC leg symbols + qty + side + limit).
2. **Reconstructability drift:** does the rejection capture (`spread_debug`, `capture_version`) carry expiry + strikes + side (priceable) or strikes only (not priceable)? Track capture_version changes. (Baseline 2026-06-10: d8_v1 has per-leg strike/side/premium/bid/ask, NO expiry → 0% of 2,361 reject rows repriceable; 100% of dismissed/blocked `trade_suggestions` rows ARE repriceable via `order_json.legs` OCC symbols.)
3. **Hand-marked counterfactuals (sample, every run):** pick the highest-EV blocked/dismissed candidates since the prior run; reprice their exact legs at the broker (executable-side = conservative bound, mid = upper); compare against the realized/unrealized P&L of what the book actually held over the same window. Report the dollar gap with fill-realism caveats.
4. **Gate-efficacy distribution (once a counterfactual marker exists):** per gate/reason, counterfactual P&L of rejects vs realized P&L of accepts; flag any gate whose reject class beats its accept class for ≥3 consecutive windows as a REGRESSION CANDIDATE for operator investigation.
5. **Survivorship exposure of learning:** what fraction and which strategy/price classes of the candidate population reach calibration training data (`calibration_service._fetch_outcomes` ← `learning_trade_outcomes_v3`); name the classes structurally absent from training (e.g. a class a mis-keyed gate is killing can NEVER appear in calibration while killed).
6. **Surface integrity:** `outcomes_log` row count (0 all time as of 2026-06-10; chain ticketed #67 for deletion — deletion is consistent, do not propose revival); `policy_decisions` rejected-with-outcome coverage (1/30d baseline); whether executor blocks stamp anything on the suggestion row (baseline: they don't — `blocked_reason` written only by marketdata_quality_gate / edge_below_minimum; executor risk blocks return without writing, `paper_autopilot_service.py:269-275`). NEW since 2026-06-30: `ENTRY_ROUNDTRIP_COST_GATE` rejects stamp `blocked_reason='ev_below_roundtrip_cost'` — a fully-reconstructable reject class; include its count + spread-eaten-vs-edge-lost classification each run.

## Constraints

- READ-ONLY, same as the whole audit: SELECT-only SQL, broker read-tools only; counterfactual marks are computed in-run from live quotes, never persisted by the audit itself.
- Mark at EXECUTABLE-side prices for the conservative bound (sell-at-bid/buy-at-ask), mid as upper bound — the #1017 shadow-fill lesson; a counterfactual that fills at exact mid is an upper bound, not an estimate.
- State fill-realism explicitly: a staged limit may never have filled (06-03 watchdog-cancel precedent; live entry fill rate is instant-or-never-shaped).
- Recommendations must be ADDITIVE observability only (capture fields, observe tables, read-only marker jobs, info-severity alerts).
- A REJECT that avoided a loss is a WIN for this lens — do not read declined trades as missed profit by default.

## Disqualifiers (what is NOT a finding under this lens)

- Any proposal to loosen, bypass, or remove a gate because counterfactual data says rejects were profitable — the lens may only flag a gate for operator investigation. (Most rejects, e.g. spread_too_wide_real, are cost-avoidance; their counterfactual P&L ignores the slippage the gate exists to avoid unless marked executable-side.)
- A single-instance counterfactual (N=1) presented as a gate-quality verdict — instances illustrate the stakes; a finding requires the structural measurement gap plus a mechanism.
- Re-finding ledger items: the dead outcomes_log/outcome_aggregator chain (#67), the dismissed-status funnel gap (status plumbing ≠ outcome marking), dead instrumentation fields, or shipped gate bugs #1044/#1047 (usable as historical evidence of the blind spot's cost, not as findings). A leg DARK at decision time (XLE dead-leg class) is UNMARKABLE by doctrine — its counterfactual is indeterminate, not lazily skipped.
- Anything requiring new write permissions for the audit loop, new market-data entitlements, or modification of the v5 contract.
- Generic "log more" recommendations without a quantified decision consequence (which gate, which dollar gap, which detection latency improves).

**HARD BOUNDARY (restating the contract):** Area 8 may never propose loosening a risk control, expanding this loop's write permissions, or modifying the contract sections. This spec content is the only editable surface.

---

*First audit under this spec: 2026-06-10 (see `audit/reports/2026-06-10.md` §5 — FINDING, confirmed: negative decisions 100% outcome-unmeasured, ~400:1 unmeasured-to-measured ratio, 0% of scanner rejects repriceable for want of an expiry field, live +$32..$66 hand-computed counterfactual on the 06-09 blocked XLF).*

*Second audit (full protocol supplement): 2026-06-11 (see `audit/reports/2026-06-11.md` "AREA 8 SUPPLEMENT"). Lens KEPT after re-evaluation. Baseline numbers updated: 30d ratio 2,527 negatives : 6 measured closes ≈ 421:1. Reconstructability unchanged — capture_version still d8_v1 at the NESTED path `spread_debug.spread_debug.capture_version` (top-level key probe returns NULL); 0/95 d8_v1 rows 06-09→06-10 carry expiry (0% repriceable); dismissed/blocked suggestions remain 100% repriceable via order_json. First TWO-SIDED counterfactual evidence: 06-09 XLF block = missed +$32..$66; 06-10 all-5-fork rejects/skips = AVOIDED −$347 (mid) .. −$740 (executable) same-day MTM loss. Counterfactual sign varies day-to-day — the net is unmeasurable without the systematic marker; recommendation unchanged.*

*(Audits three through six ran 2026-06-13 → 2026-06-30 under this spec — see those reports; standing recommendation (expiry/proxy capture + systematic counterfactual marker + per-gate reject-vs-accept metric) remains in docs/backlog.md RESEARCH. Strongest single datapoint to date, 06-30: the conservative fork's SOFI REJECT (edge_below_minimum, EV 19.1) beat both accepting books (−$40 live / −$1,044.48 shadow) — a rejection was the day's best decision.)*

*Restored-lens audit: 2026-07-02 (see `audit/reports/2026-07-02.md` §A8). No new negative-decision population since the prior run (0 scans, 0 suggestions); ratio and reconstructability unchanged; roundtrip-gate reject class still N=0 (armed 06-30, unexercised). NO FINDING.*

---

## SUPERSEDED — Entry-Fill Efficacy (adopted 2026-07-01, RETIRED 2026-07-02 by owner correction)

*The following spec occupied this file for one run (2026-07-01). The owner's v5.1 contract
records the swap as adopted in error: A8 is the graduated standing area and does not rotate;
single-run lens replacement is the Area 9 rotating slot's mechanism, not A8's. The spec is
preserved verbatin-in-substance below for history; its subject matter (staged-live inventory,
#1101 gate telemetry, #1102 close-fill-gap accrual, basis unification, watchdog interaction,
shadow-vs-live fill fidelity) remains auditable under A1/A6/A7 and may be re-proposed for the
A9 slot on its own merits in any future run. It does NOT audit as a standing area.*

- Goal (as adopted): measure the gap between the price basis a decision was made on and the price basis reality delivered — entry (staged limit vs fill vs executable cross), rest (fill-or-watchdog-cancel rates), exit (trigger basis vs achievable vs actual fill) — so execution-quality regressions become data-detectable and Phase-3 reopens on a measured distribution.
- Look-at list (as adopted): staged-live inventory (baseline N=2: NFLX 06-03 watchdog-cancel ~5min; SOFI 06-30 filled at the 1.44 limit ~10s); #1101 gate telemetry (0 evaluations to date); #1102 close-fill-gap accrual toward the Phase-3 reopen gate (1 informative datapoint ever: SOFI 06-30 live, gap≈0.23; accrual ≈1 live close/week → gate ~2–3 months out); entry-vs-exit basis unification (the UNIFICATION TRAP note); watchdog cancels via `cancelled_reason`; shadow-vs-live fill fidelity (SOFI pair −40 vs −1,044.48, sizing 5 vs 17 + overnight + open-rotation cross).
- First and only audit under the spec: 2026-07-01 (report §A8) — NO FINDING beyond the accrual-rate observation.
- Predecessor-retirement note it carried (now moot — the predecessor is restored): NDE's standing recommendation stays in docs/backlog.md RESEARCH; parting datapoint = the conservative SOFI fork's winning REJECT.
