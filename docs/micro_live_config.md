# micro_live Configuration & Apply Runbook

Operator runbook for flipping `alpaca_paper` → `micro_live` with
$500 starting capital. Companion to PR
`feat/micro-live-500-calibration` (3 commits) and the manual
migration-apply procedure in `CLAUDE.md`.

---

## Capital scaling rule

| Capital | Utilization | Trigger to next stage |
|---|---|---|
| $500 → $1,000 | 100% | Account reaches $1,000 |
| $1,000 → $2,000 | 90% | Account reaches $2,000 |
| $2,000+ | **Reassess** | Operator decision point — no automated trigger |

**Per-trade max derivation:**
`max_per_trade = baseline_capital × RISK_MAX_SYMBOL_PCT`
At $500 × 0.40 = **$200 per single trade**. Scales naturally with
capital — no separate per-trade cap to maintain.

**Reassess scope at $2,000:** review trade history, evaluate cohort
tuning, reconsider ticker expansion, decide whether to step capital
up further or compress back down.

---

## Apply runbook (Monday morning, pre-market)

The order below is **enforced by physics**, not by code. The auto-sync
in `progression_service.py:138-176` reads `alpaca.get_account()["equity"]`
at phase promotion and writes it to `v3_go_live_state.paper_baseline_capital`,
overwriting any manual value. If Steps A–B are not complete before
Step D, the auto-sync will clobber the $500 with whatever the current
Alpaca client returns (paper account = ~$97k).

### Step A — Fund Alpaca live account ($500)

Operator action, pre-market. Confirm cash settled and visible in
the live (not paper) Alpaca dashboard before proceeding.

### Step B — Railway environment flip + redeploy

Set on backend + worker services:
- `ALPACA_PAPER=false`
- `EXECUTION_MODE=micro_live`

Trigger redeploy. **Verify from worker logs**: next sync cycle
shows the live Alpaca account, equity ≈ $500. Do not proceed to
Step C until logs confirm.

### Step C — DB UPDATE baseline capital

Run via `mcp__supabase__execute_sql` (or Dashboard SQL editor):

```sql
UPDATE v3_go_live_state
   SET paper_baseline_capital = 500,
       updated_at = NOW()
 WHERE user_id = '75ee12ad-b119-4f32-aeea-19b4ef55d587';

-- Verify
SELECT user_id, paper_baseline_capital, updated_at
  FROM v3_go_live_state
 WHERE user_id = '75ee12ad-b119-4f32-aeea-19b4ef55d587';
```

Expected: row updated, `paper_baseline_capital = 500`.

### Step D — Phase promotion (auto or manual)

Auto-promotion fires at the next `daily_progression_eval` if green
days threshold is met. Manual promotion via the existing admin path.

**CRITICAL:** This step calls `alpaca.get_account()["equity"]` and
writes the result to `v3_go_live_state.paper_baseline_capital`. If
Steps A–B are incomplete, the auto-sync OVERWRITES the $500 from
Step C with paper-account equity (~$97k).

If the Alpaca env still points at paper at this moment, **do not**
trigger the promotion. Roll back to Step B, fix env, then resume.

### Step E — Universe sync after Step B redeploy

After the redeploy completes (Commit 2's `BASE_UNIVERSE` edit is
live in the worker image), trigger one `UniverseService.sync_universe()`
run. This upserts the 6 new symbols into `scanner_universe`.

Verify:

```sql
SELECT COUNT(*) FROM scanner_universe WHERE is_active = true;
-- Expected: 62 (was 56)

SELECT symbol FROM scanner_universe
 WHERE symbol IN ('F','BAC','SOFI','T','KO','VZ')
 ORDER BY symbol;
-- Expected: 6 rows
```

### Step F — Audit `risk_alert` (config_change)

```sql
INSERT INTO risk_alerts (user_id, alert_type, severity, message, metadata)
VALUES (
  '75ee12ad-b119-4f32-aeea-19b4ef55d587',
  'config_change',
  'info',
  'micro_live $500 calibration applied (PR #<NUMBER>)',
  jsonb_build_object(
    'pr_number',              <PR NUMBER>,
    'commit_shas',            jsonb_build_object(
                                'commit_1', '<SHA1>',
                                'commit_2', '<SHA2>',
                                'commit_3', '<SHA3>'
                              ),
    'step_a_completed_at',    '<ISO timestamp>',
    'step_b_completed_at',    '<ISO timestamp>',
    'step_c_completed_at',    '<ISO timestamp>',
    'step_d_completed_at',    '<ISO timestamp>',
    'step_e_completed_at',    '<ISO timestamp>',
    'baseline_before',        100000,
    'baseline_after',         500,
    'universe_count_before',  56,
    'universe_count_after',   62,
    'phase_before',           'alpaca_paper',
    'phase_after',            'micro_live'
  )
);
```

Sanity-check that PR #803's Phase 2 constraints are still intact
(this calibration must not have touched them):

```sql
SELECT conname, pg_get_constraintdef(oid)
  FROM pg_constraint
 WHERE conrelid = 'paper_positions'::regclass
   AND conname IN ('check_close_reason_enum', 'close_path_required');
```

Expected:
- `check_close_reason_enum` — 9 canonical values (no legacy values)
- `close_path_required` — Phase 1 definition (`status IS DISTINCT
  FROM 'closed'` gate, strict `<` cutoff)

### Step G — Post-market-open verification (13:00 UTC)

After the first sync cycle of the trading day:

1. Scanner sees 62 symbols (logs / DB).
2. Position sizing reflects $500 baseline (e.g. cohort × multiplier
   × $500 ≈ $12.50 at NEUTRAL — small).
3. **Expected: zero trade entries.** Per Option B in the planning
   thread — cohort sizing math at $500 produces sub-spread amounts.
   This is the deferred follow-up audit's responsibility.
4. No CHECK violations in `risk_alerts` (PR #803 sanity).

---

## Rollback procedure

Each commit reverts independently.

### Rollback Commit 1 (CLAUDE.md target capital line)

```
git revert <SHA1>
```

Plus reverse the DB UPDATE:

```sql
UPDATE v3_go_live_state
   SET paper_baseline_capital = 100000,
       updated_at = NOW()
 WHERE user_id = '75ee12ad-b119-4f32-aeea-19b4ef55d587';
```

### Rollback Commit 2 (BASE_UNIVERSE expansion)

```
git revert <SHA2>
```

Plus deactivate the 6 new symbols in `scanner_universe`:

```sql
UPDATE scanner_universe
   SET is_active = false, last_updated = NOW()
 WHERE symbol IN ('F','BAC','SOFI','T','KO','VZ');
```

(Soft-delete preserves history. Hard-delete with `DELETE FROM` is
also valid if metric pollution from these symbols is a concern.)

### Rollback Commit 3 (this docs file)

```
git revert <SHA3>
```

No DB or env action required.

### Rollback the operational env flip (Steps A–B)

If the live trading needs to halt entirely:
- Railway env: revert `ALPACA_PAPER=true`, `EXECUTION_MODE=alpaca_paper`
- Trigger redeploy
- Phase: manually demote via admin path (no auto-demote exists)
- Auto-sync does NOT fire on demotion — `paper_baseline_capital`
  stays at whatever it was set to. Rerun the rollback SQL from
  Commit 1 above to restore $100k baseline if needed.

---

## Liquidity evidence (for audit trail)

Per-ticker top-5 ATM OI for the 9 evaluated candidates (calls, May
2026 expiries, queried 2026-04-25):

| Sym | Px | Top-5 ATM OI | Decision |
|---|---|---|---|
| F | $12.39 | 20,237 | ✅ added |
| BAC | $52.04 | 18,962 | ✅ added |
| SOFI | $18.45 | 18,369 | ✅ added |
| T | $26.20 | 6,454 | ✅ added |
| KO | $76.62 | 14,902 | ✅ added |
| VZ | $46.39 | 8,928 | ✅ added |
| GE | $284.69 | 1,836 | ❌ outside $20-80 range; lowest cohort liquidity |
| PLTR | $142.73 | 479 | ❌ fails OI>1000 ATM (clustered far OTM) |
| NIO | $6.21 | 32,071 | ❌ Chinese ADR risk; spreads too small for fee profile |

Stock volumes are IEX-only (Alpaca subscription denies SIP feed
on this account). The original >5M daily-volume threshold cannot
be validated against IEX data; included symbols are within the
liquidity ordering of the existing 56-symbol universe based on
the relative IEX-feed numbers observed.

---

## Known unknowns (deferred to follow-up audits)

- **Cohort selection.** 3 active cohorts (conservative / neutral /
  aggressive) live in `policy_lab_cohorts.policy_config`. Which one
  drives live trades is genuinely unknown — needs separate
  investigation of the cohort-routing logic before any tuning.
  Out of scope for this PR.

- **Base-risk multiplier source.** `CLAUDE.md` says "8% base risk"
  but cohort `max_risk_pct_per_trade` tops out at 3.5% (aggressive).
  There's a multiplier layer somewhere upstream that wasn't pinpointed
  in the discovery pass. Needs trace before any sizing tuning.

- **Risk multiplier `1.08` source.** Observed in production logs but
  not traced to a single config knob. Likely a runtime computation
  involving `COMPOUNDING_MODE` and the cohort multiplier. Needs a
  log line + line number to resolve.

- **Auto-sync hardening.** The Alpaca-environment / phase-promotion
  ordering (Steps A–D above) is enforced by runbook discipline, not
  code. The right code-side hardening is a guard in
  `progression_service.py` that refuses to auto-sync
  `paper_baseline_capital` when `ALPACA_PAPER=true` and the live-vs-
  baseline equity differs significantly. Out of scope for this PR;
  tracked as backlog item.

---

## Post-flip expectations

- **Infrastructure validated:** $500 baseline live, 62-symbol scanner,
  Phase 2 constraints intact, env vars correct.
- **Trading paused by design:** cohort sizing at $500 produces sub-
  spread budgets (~$12.50 at NEUTRAL × 1.0). Zero trade entries
  expected until the cohort-tuning follow-up PR.
- **Monday is an infrastructure-validation day, not a trading day.**
  This is the chosen Option B path — safer than coupling cohort
  unknowns into the same PR.
