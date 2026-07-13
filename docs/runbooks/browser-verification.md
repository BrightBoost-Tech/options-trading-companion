# Browser Verification Runbook (operator-triggered)

Doctrine: CLAUDE.md "BROWSER USE". The browser is for LOCAL UI acceptance,
interaction-dependent source research, and comparing authoritative
API/receipt evidence with operator-facing rendering — nothing else. Browser
evidence is SECONDARY to Supabase, Railway, Alpaca MCP, and direct APIs;
prefer connectors, APIs, web retrieval, or CLI for structured facts. Every
procedure below is operator-run on its trigger; NONE belong to the
unattended nightly audit (`audit/v5-prompt.md` carries no browser
requirement by design — keep it that way).

Hard lines (restated because this file is the operating surface): never
place, modify, exercise, replace, or cancel broker orders from a browser;
never change production configuration; never persist an Alpaca login; never
add Browser requirements to the nightly audit.

Local UI acceptance target: `.claude/launch.json` launches the Next.js app
(`apps/web`, `pnpm dev` → `next dev`, localhost:3000). Local preview only —
it never points at production.

## Evidence artifact (required for EVERY browser claim)

A browser observation without this block is a hypothesis, not evidence
(CLAUDE.md §1). Record:

- **URL:**
- **Timestamp (UTC):**
- **Authentication state:** (logged out / logged in as `<role>`; for Alpaca:
  "session NOT persisted" — confirm logout)
- **Screenshot:** (path or attachment)
- **DOM result:** (the concrete element/text observed)
- **Console/network errors:** (or "none")
- **Expected vs observed:**

File the block in the session record; if it changes a decision, mirror the
conclusion into `audit/ledger.md` with a pointer to the artifact.

## 1. Morning page-truth check

**Extends:** the morning ritual, Part 2 (operator-run — NOT the nightly;
the receipts stay primary).
**Trigger:** any morning after a DOWN email · a quiet-looking week · the
weekly FULL read. **Cadence:** weekly + on-anomaly, not daily.

Steps:
1. Baseline first (receipts, primary): query the latest critical/high
   `risk_alerts` row (H11) so you know what the pages SHOULD show before
   looking at them.
2. Open the healthchecks dashboard: the nightly-audit check reads UP and
   the last ping is < 26h old. Read the PAGE's own values.
3. Open the Slack #risk-alerts web view: the latest DB critical from step 1
   has a RENDERED message in-channel (content visible, not just a delivery
   receipt).
4. Record the evidence artifact. Report what the PAGES say, not what the
   receipts imply. A page↔receipt disagreement IS the finding — report it,
   never average it (CLAUDE.md §1).

**Evidence artifact:** one block per page (healthchecks + Slack), DOM result
= the check status / last-ping value and the rendered alert text.

## 2. Queue-⑤ make-vs-fetch recon (credit-probability build)

**Extends:** the credit-probability build (queue item ⑤) as its PRE-BUILD
step.
**Trigger:** the ⑤ build session opens.

Steps:
1. In the browser, read the Polygon options-endpoint docs for the
   already-paid entitlements only (Stocks Starter + Options Developer; NO
   index entitlement — CLAUDE.md §6): implied-vol surfaces, greeks, chain
   snapshots.
2. Inventory the in-repo IV history (tables + the MIN_IV_HISTORY_DAYS
   window — query the DB, don't trust docs).
3. Produce the source-decision table: one row per input the ⑤ build needs
   (IV surface / greeks / chain snapshot / history depth), columns = make
   (compute in-repo) vs fetch (Polygon endpoint) · entitlement covered? ·
   history depth · staleness/latency · decision.

**Evidence artifact:** the source-decision table + one block per docs page
read (URL + timestamp; DOM result = the entitlement/endpoint facts relied
on).

## 3. Earnings-source evaluation

**Extends:** unblocks the P2 versioned-earnings cohort (pre-build).
**Trigger:** the earnings-cohort build is scheduled. Time-box: ~1 hour.

Steps:
1. Select 2–3 free earnings-calendar sources.
2. Spot-check announced dates against known filings for the 9 viable names
   (per the earnings-cohort recon list).
3. Read each source's API terms in the browser: rate limits, auth,
   redistribution/storage rights.
4. Recommend one source (+ fallback) with the comparison table.

**Evidence artifact:** comparison table + terms citations + recommendation;
one block per source (DOM result = the dates spot-checked and the terms
clauses relied on).

## 4. Broker-render spot-check

**Extends:** the incident/first-submit pin convention.
**Trigger:** FIRST-of-class order submits only (e.g. the first `otc1-*`
client_order_id) — never routine.

Steps:
1. Primary evidence first: pull the order (id + client_order_id + status)
   via Alpaca MCP / DB — that is the finding; the browser step checks only
   RENDERING.
2. Open the Alpaca order page ONCE; confirm the client_order_id renders
   where an incident responder would look (the order detail view).
3. Screenshot + evidence artifact.
4. Session teardown is part of the procedure: log out — do NOT persist the
   Alpaca login (doctrine hard line). Record "session NOT persisted" in the
   authentication-state field.

**Evidence artifact:** one block; DOM result = the rendered client_order_id
and where it appears; auth state MUST read "session NOT persisted".
