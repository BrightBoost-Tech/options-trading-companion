# Owner Packet 7 — Greek caps staged arming

**Decision:** choose a staged plan to eventually arm greek caps — **Plan A**
(alert-only → soft-size → never-block) or **Plan B** (alert-only → hard-block
tightest row only). **This packet executes nothing; caps stay 0 tonight.** The
greek-cap surface shipped **alert-only / observe-only** (PR #1282); it arms
nothing, blocks no entry, scales no size, writes no `risk_alerts` row, reads no
cap flag (`risk_envelope.py:491-536`). `ENABLE_LIVE_GREEK_CAPS` stays `false`.

**Recommendation:** **Plan A** — alert-only for 2 weeks, then a **soft-size**
(warn + down-weight) stage that **never hard-blocks**. It matches the project's
measurement-first, never-loosen-nor-suddenly-block posture and stays reversible
at every stage. Plan B (hard-block the tightest row) is offered for the owner
who wants an enforced ceiling once coverage is proven.

---

## 1. Starting truth: the greek envelope is DOUBLE-dormant

Verified 07-02 (CLAUDE.md §8, re-confirmed by this surface): **no leg jsonb has
ever carried a `greeks` key** (`check_greeks` sums zeros since inception) AND
all four production caps default 0 (no-limit). So **today every reference row
reads `would_block=None` (unavailable)** — there is no honest greek exposure to
cap yet. Arming anything before greeks are populated on legs would enforce
against fabricated zeros (H9 violation). **This is the binding prerequisite.**

## 2. The counterfactual surface (what #1282 gives the owner)

`compute_greek_cap_counterfactual` (`risk_envelope.py:646-770`) records, per
tightness row and per greek, a `would_block` / `cap_headroom` / typed-
unavailable reason — **without arming anything**. Three reference rows, each
**inverting an existing `EnvelopeConfig` loss fraction** (never invented,
`:513-536`):

| row | loss budget L | derivation of each cap |
|---|---|---|
| **tight** | `max_per_symbol_loss_pct × equity` (0.03) | delta=`L/spy_move`, gamma=`L/spy_move²`, vega=`L/(vix_move·100)`, theta=`L` |
| **medium** | `max_daily_loss_pct × equity` (0.05) | same inversion |
| **loose** | `max_weekly_loss_pct × equity` (0.10) | same inversion |

`would_block` compares `abs(portfolio_greeks[g]) > cap` — the **same value an
armed cap would read** inside `check_greeks` (`:503-505`) — and is asserted
**only** when greeks coverage is whole-book complete AND the canonical signed
aggregate is present AND the two **agree in sign**; a partial book, a missing
canonical value, or a **sign mismatch** → typed UNAVAILABLE, never a fabricated
block (`_greek_cf_availability`, `:603-630`). A flip-logger emits one INFO line
only when a row's `would_block` changes (`:774-799`).

## 3. Minimum coverage before ANY arming (both plans)

Arm nothing until the counterfactual has produced, over a review window:

1. **`greeks_coverage.complete = true`** on real books — i.e. legs actually
   carry populated `greeks` (the fix path in CLAUDE.md §8: populate greeks on
   legs at stage time from the snapshots that already carry them). Until then
   every row is `would_block=None` and there is nothing to arm.
2. **0 `sign_mismatch`** between `portfolio_greeks` and the canonical signed
   aggregate over the window — a sign divergence means the cap's own basis is
   untrustworthy (`:626-629`); arming on it would block on a number the system
   itself cannot corroborate.
3. **Structural evidence across book types** — the counterfactual has recorded
   `would_block` states for **vertical + condor + mixed** books (the
   `_greek_cf_book_summary` strategies field, `:633-643`), so the chosen cap
   is validated against the real structures the system trades, not one shape.

## 4. The two staged plans

### Plan A — alert-only → soft-size → never-block (recommended)

| stage | duration / gate | behavior | reversal |
|---|---|---|---|
| A0 alert-only | ≥ 2 weeks AND §3 coverage met | current #1282 surface + (new) a `risk_alerts` WARN when a row's `would_block` flips true; still zero enforcement | revert the alert PR |
| A1 soft-size | after A0 clean | on a corroborated `would_block=true` (complete + sign-agree), **down-weight** the candidate's size toward the cap headroom; **never reject** | `ENABLE_LIVE_GREEK_CAPS` unset → warn-only |
| A2 (terminal) | — | **never hard-block** — soft-size is the ceiling behavior by design | — |

- **Why:** matches the doctrine that measurement corrections and risk controls
  should tighten smoothly, never introduce a sudden hard reject that could
  starve the (already thin) entry funnel. A soft-size on a corroborated cap is
  a graduated, reversible tightening.
- **Kill:** `ENABLE_LIVE_GREEK_CAPS` (strict `=1`, default-OFF, behavioral
  polarity §3) — unset → the observe-only surface; recycle both workers.

### Plan B — alert-only → hard-block tightest row only

| stage | gate | behavior |
|---|---|---|
| B0 alert-only | = A0 | identical to A0 |
| B1 hard-block | §3 coverage met AND owner review | **reject** an entry only when the **`tight`** row (`max_per_symbol_loss_pct`, the strictest budget) `would_block=true` **and** corroborated; medium/loose stay observe-only |

- **Why:** a genuine enforced ceiling at the single tightest, best-anchored row,
  leaving the looser rows observational — the least-aggressive way to have a
  real block.
- **Cost:** a hard reject on an entry is exactly the funnel-starving risk Plan
  A avoids; only choose B if the owner wants enforcement, not just size
  attenuation. Same `ENABLE_LIVE_GREEK_CAPS` kill.

## 5. Notes on the reference caps

- `gamma_cap = L/spy_move²` is the **softest-anchored** of the four (the
  envelope has no first-class gamma scenario; no ½ convexity factor —
  deliberately conservative-tighter, `:529-533`). If either plan reaches a
  block/soft-size on gamma, treat it as the least-trusted row.
- The reference caps **invert** existing loss-envelope fractions, so a book
  sitting AT a cap loses exactly L under the doctrinal stress scenario — the
  caps are not new risk numbers, they are the existing loss budget re-expressed
  in each greek's unit (`:513-528`).

## 6. Tonight

**Caps stay 0.** `ENABLE_LIVE_GREEK_CAPS=false`. The only live behavior is the
observe-only counterfactual; the greeks-population prerequisite (§3.1) is not
yet met, so no arming is even eligible.

---

## APPROVAL TOKEN

> **`GREEK_CAPS_STAGED_PLAN=A`** (alert-only 2wks → soft-size → never-block) —
> approves the staged path in §4 Plan A, contingent on the §3 minimum coverage
> (`greeks_coverage.complete`, 0 sign_mismatch, vertical+condor+mixed evidence)
> being met first; each stage past A0 is armed only by `ENABLE_LIVE_GREEK_CAPS=1`
> (strict, default-OFF) and is instantly reversible by unsetting it.
> *(Alternative: `GREEK_CAPS_STAGED_PLAN=B` — alert-only → hard-block the
> `tight` row only.)* Caps remain 0 and unarmed until greeks are populated on
> legs and the owner issues the flag; nothing is armed by this packet.
