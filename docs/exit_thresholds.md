# Exit thresholds — sample-size discussion + re-evaluation criterion

Reference document for CLAUDE.md "Exit thresholds (defaults under empirical review)". CLAUDE.md keeps the current values, time-scaling status, and the empirical observation table. Sample-size discussion, derivation of within-strategy vs aggregate hold ratios, and the re-evaluation criterion detail live here.

## Status: inherited defaults, under empirical review

The exit threshold values (35% target profit, 50% stop loss) were inherited rather than set by deliberate design. They produce an asymmetric exit profile (system tolerates more loss than gain before exiting):

- Threshold ratio: 50/35 = 1.43× (loss tolerance vs gain capture)
- Within-strategy hold ratio observed: ~2.5× (debit spreads, N=15 across both buckets)
- Aggregate hold ratio observed: ~5× (across full strategy mix — partly inflated by iron-condor wins resolving fast vs debit-spread losses bleeding slow)

The aggregate "5×" framing overstates the in-class effect. Within `debit_spread` alone the asymmetry is 2.5×; iron condor profits resolve in ~5h on average, which inflates the aggregate ratio when mixed in.

## Re-evaluation criterion

When debit-spread sample reaches **N=20 per outcome bucket** (as of 2026-05-13 there were 9 winners / 6 losers, so this threshold has not been met), re-investigate whether 35/50 is the right threshold pair for micro-tier behavior. Earlier re-evaluation may be triggered if outcome-bucket pattern shifts substantially. See `docs/backlog.md` "[2026-05-13] WATCH: Exit threshold re-evaluation trigger (N=20)" entry.

## What this note does NOT claim

- That 35/50 is the right design (they're inherited, not validated)
- That they should be changed (insufficient evidence either way)
- That asymmetry is wrong (asymmetric thresholds are common in options strategies; just not deliberately chosen here)

## Cross-references

- Hold-ratio investigation 2026-05-13 (session history)
- PR #928 (`hold_period_buckets` v1 view that surfaces this data)
- PR #929 (operational note + view v2 relabel)
- `docs/audit_hold_period_asymmetry.md` (LOW-confidence audit at N=6; sample 5+ weeks stale)
- Learning-mode codification — micro tier IS the development environment for evaluating these defaults
