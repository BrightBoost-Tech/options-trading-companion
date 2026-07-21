# Fable Overnight Priority Sprint — Results (2026-07-21)

**Orchestrator:** Fable · **Build/review agents:** Opus (≤7 parallel). Merges serialized by Fable.
Zero broker / fleet-activation / policy-registry / control / env / schedule / data-correction writes.
Broker flat throughout; market closed for every merge/migration.

Proof labels per the brief: VERIFIED-LOCAL / -CODE / -TEST / -GITHUB / -CI / -DEPLOYMENT / -DB /
-BROKER / HONEST-EMPTY / INFERRED / NOT-PROVEN / BLOCKED.

## Phase 0 — grounding (VERIFIED-DB/-BROKER/-LOCAL)
DB `01:59Z` ≈ broker `21:59 ET` = market CLOSED; broker flat (0 pos / 0 orders, L3, OBP $2,067.86);
origin/main `94aa6528` (expected basis, all 4 services green); entries_paused=false; fleet 50
inactive / 0 active / 0 bindings / 0 receipts / 0 activations. **Power (VERIFIED-LOCAL):** desktop
(no battery, always-AC); active Balanced scheme Sleep-after(AC)=**Never** (registry-verified);
`UNATTENDSLEEP` had no explicit scheme override (**NOT-PROVEN as literal 0**) — on a desktop that
never idle-sleeps this was assessed likely-moot, and the natural nightly confirmed it (PASS, wake
lock held). No power setting was changed.

## Serialized merges — final main `f28906ff9162ce878aa970a6be6e25285fc859b8`

| # | Lane | PR | merge SHA | migration / apply receipt | CI | deploy | live/dark state |
|---|------|----|-----------|---------------------------|----|--------|-----------------|
| 1 | A+B receipt writer + privilege | #1335 | `8eeb11f4` | `20260721010000` (`a5294476`) + `20260721010500` (`7e882073`) applied | pass | 4/4 SUCCESS | **live writer, 0 receipts issued**; erase hole closed |
| 2 | C OI enrichment | #1325 | `f105377b` | — | pass | 4/4 | **default-OFF** (byte-identity + 0 calls); flag false |
| 3 | F alert dedup | #1332 | `4a0739f9` | — | pass | 4/4 | live; no historical-row mutation |
| 4 | D tier-taper | #1334 | `dd551207` | — | pass | 4/4 | **DARK** `[800,1000]` v2; live sizing byte-identical |
| 5 | E E19 v3 refreeze | #1331 | `76c06c28` | — | pass | 4/4 | **frozen, execution BLOCKED**; min=8; v2 immutable |
| 6 | G url-sec | #1330 | `ada5ce96` | — | pass | 4/4 | `.gitignore` guard + local `url.txt` archived+removed |
| 7 | H single-leg manifest | #1336 | `609cae01` | — | pass | 4/4 | **draft-only**, no registry write |
| 8 | I H7 ratify | #1333 | `3eb85d7e` | — | pass | 4/4 | docs; all elements VERIFIED-CODE |
| 9 | J hygiene (non-runner) | #1337 | `ad495be3` | — | pass | 4/4 | OI-overflow guard + docs + nonce text + `.Jules` dedup |
| 10 | J hygiene (runner) | #1338 | `f28906ff` | — | pass | 4/4 | assert run_tag + marker-sink rotation (post-nightly) |

Adversarial review before each merge: the receipt-writer (#1335) got a dedicated independent opus
review (VERDICT PASS on real Postgres 16); #1325 OI got an independent update-and-review (PASS);
lower-risk lanes were built with their own tests + Fable's scope/CI verification.

## Phase 1 — natural 00:00 CT nightly: **PASS** (VERIFIED-LOCAL, no trigger)
Run `2026-07-21-25320-45cbf6d9`, PID 25320 → child 25516, 05:00:02Z→05:12:42Z (757.8s), exit 0.
Contract **met=True, missing=[]**: scheduled task started (Last Result 0) · fresh `%LOCALAPPDATA%\
otc-audit-worktree` → `ad495be3` (stale=false) · per-run START+END markers · 60s heartbeats ·
dated report `audit/reports/2026-07-21.md` (sha256 `4cc0d77df4f4b8c4dccaa159a5f1d1d1be34d9e147b2b05e4fabcd429e04c110`,
16,004B) · preflight manifest · dead-man UP ping (curl 0) · **operator checkout unchanged** (HEAD
`94aa6528`, zero tracked-dirty; only the report copy-back is untracked). **The wake lock HELD**
(ES_CONTINUOUS|ES_SYSTEM_REQUIRED) — the 07-20 `0xC000013A` sleep-kill is resolved; the power fix
worked. Report: 0 critical, 6 HIGH = the ledgered 07-20 calendar trail (zero new after 20:07Z),
findings LOW/MED, no live money at risk; Monday ran clean on the hotfixed calendar path.
**Caveat (non-blocking):** `broker snapshot available=False` — ALPACA creds unset in the runner env
(F-RUNNER-BROKER-CREDS, 2nd consecutive broker-blind run); the audit ran broker-blind, broker claims
DB-corroborated. Classification **PASS** (broker-blindness is a known runner-env gap, not a run
failure).

## Receipt writer + fleet state (VERIFIED-DB)
`rpc_issue_fleet_reconciliation_receipt_v1` live (server-gen id, source-marker-validated, idempotent,
`orphan_run` RAISEs — job_runs has no user_id, matching the D2 BLOCKED verdict). Privilege hardening
reduced `service_role` on `fleet_reconciliation_receipts` from `arwdDxtm` → `arm`: **TRUNCATE/UPDATE/
DELETE all revoked** (erase hole closed) + a `BEFORE TRUNCATE` guard; SELECT+INSERT retained. The
activation RPC's existence SELECT still works (**non-regression proven**). Residual `MAINTAIN` (`m`)
is benign (VACUUM/ANALYZE only; cannot erase/mutate rows) — optional future micro-hardening `REVOKE
MAINTAIN`. **No production producer is wired → 0 receipts issued.** Fleet unchanged: **50 inactive /
0 active / 0 bindings / 0 receipts / 0 activations ever**; `ACTIVATE_FLEET=false`; activation stays
fail-closed on the empty receipt table.

## Lane dispositions
- **OI (#1325):** merged, default-OFF, zero provider calls when off; provider = Alpaca
  `/v2/options/contracts` (OI + observation date), fails safe with no cred; no gate/rank/sizing/
  selection consumer; `OI_ENRICHMENT_ENABLED` NOT enabled.
- **Tier-taper (#1334):** DARK, band reconciled `[900,1100]`→ratified `[800,1000]`, engine v2, live
  sizing byte-identical, monotonic no-increase-on-decline proven, old/new evidence version-partitioned;
  no live-tier-taper enable.
- **E19 v3 (#1331):** v3 pinned `cfdcfc9e…`, v2 preserved immutable `50e7e237…`, minimum=8, execution
  BLOCKED (fleet epoch + evidence); no E19 job triggered. Noted: §12 upstream module hashes are only
  transitively pinned and pre-date this work (deliberately not re-pinned) — a separate governance lane.
- **Alert dedup (#1332):** identity `(job_run_id, alert_type, detector_version, failure_signature)`;
  first emits, repeats suppressed-typed, changed-reason/new-detector re-emits; no historical row
  deletion/update; no severity downgrade; relay intact. Race caveat: exactly-once under the serialized
  single-`otc`-worker model.
- **URL secret (#1330 + local):** `url.txt` **NEVER-TRACKED** (0 commits/0 blobs); every secret-shaped
  repo match is security tooling / synthetic fixtures — **no real leak, no rotation warranted**;
  `.gitignore` guard merged; local file archived to a restricted path (sha256 `a74d1055…`, content
  never read) + removed. `ROTATE_CREDENTIALS=false` honored.
- **Single-leg manifest (#1336):** 2 experimental + 2 control policy definitions, **draft-only**, in
  `docs/specs/` + an UNAPPLIED seed in `supabase/seed-transactions/` (not a migration); deterministic
  hashes; independent typed EV (no fabricated scalar); **no policy-registry row written**; a separate
  operator seed-authorization prompt was produced (`docs/review/single-leg-seed-prompt-2026-07-21.md`).
- **H7 taxonomy (#1333):** ratified — `h7_dropped` retained as backward-compatible parent; 5 canonical
  subreasons; `sizing_outcome` separate. All VERIFIED-CODE (no contradiction); doc-contract test pins
  drift.
- **Palette triage (Lane K):** 66 UI PRs analyzed; **40 exact-duplicate PRs closed** against 5 kept
  canonicals (#885/#1196/#1103/#798/#1136), each with a canonical-naming comment; conservative KEEP
  otherwise; zero merged-supersession, no UI PR merged, #733 flagged stale. `MERGE_UI_PRS=false`.
- **F-REDATE (Lane L):** 20 rows (fingerprint `4f1999db…`), none broker-live, live-calibration excluded
  (is_paper gate), paper-window contamination confirmed (go_live 14d 3→22 = 91% phantom on the
  graduation gate; context 30d 7→26; walk_forward 60d 21→40), currently latent. Recommendation
  **`CORRECT_ALL_CONFIRMED_ROWS`** (date-only `updated_at:=created_at`). **NOT executed**
  (`APPLY_F_REDATE_CORRECTION=false`) — operator-owned; packet at
  `%TEMP%\otc-overnight-2026-07-21\f-redate-decision-packet-2026-07-21.md`.

## Natural evidence still pending (HONEST-EMPTY / INCONCLUSIVE — do not trigger)
- **#1327 alternate-disposition coverage:** Monday's cycle (pre-#1327) produced 4 `candidate_terminal_
  dispositions` finals; the alternate-`rank_blocked` coverage falsifier awaits the NEXT natural midday
  cycle (Tuesday 07-21) — INCONCLUSIVE.
- **Receipt writer runtime:** no production producer wired → issues no receipt; first real receipt is
  the falsifier (operator-driven future reconciliation).
- **Runner PR #1338 runtime:** merged to main; the nightly wrapper invokes `nightly_runner.py` from the
  operator checkout, so the assert-run_tag/rotation changes take runtime effect only after the operator
  checkout absorbs main (currently blocked by the local `.Jules` case-collision — see below).
- Atomic internal-close (0 natural fires, book flat) · TCM-v2 (0/15) · model-review (no_scorable_closes)
  — all HONEST-EMPTY.

## Known residuals / operator follow-ups (non-blocking)
- **`.Jules`/`.jules` case-collision phantom:** #1337 removed the stale `.Jules/palette.md` index entry
  (fix now in main), but the operator checkout + older worktrees on case-insensitive Windows still carry
  the phantom, which BLOCKED the operator-checkout ff-pull and the local runner-branch update (resolved
  server-side via `gh pr update-branch` for #1338). The operator checkout stays at `94aa6528` (its
  runner/wrapper are byte-identical to main — #1338 aside — and the nightly uses a fresh worktree, so
  the nightly was unaffected). Morning: reconcile the `.Jules` phantom, then ff the operator checkout.
- **F-RUNNER-BROKER-CREDS:** the nightly ran broker-blind (creds unset in the runner shim env) — a
  wiring fix, non-blocking.
- **Fleet receipt-table `MAINTAIN` residual** (above) — optional micro-hardening.

## Safety ledger (this run)
Production DB writes limited to: 2 reviewed migrations applied by exact name (D1/D2 — receipt writer +
privilege hardening) + 2 repo-standard `migration_apply` receipts (`a5294476` / `7e882073`).
No fleet receipt row, policy row, F-REDATE row, suggestion row, or broker/order row written. No fleet
provisioning/activation; no env/schedule change; no entry/risk/liquidity/cost/calibration/DTE/width/
sizing change. `ACTIVATE_FLEET=false`; `entries_paused=false` throughout; 0 activations ever.
