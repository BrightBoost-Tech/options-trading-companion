# Options Trading Companion – Architecture Overview

_Last updated: 2025-11-27_

## 1. Purpose

Options Trading Companion is a web application that helps retail traders make more informed options decisions.  
It combines:

- A **Next.js 14** frontend for portfolio views, dashboards, and settings
- A **Python / FastAPI** backend for analytics, data orchestration, and “quantum / advanced” optimization logic
- **Supabase** for authentication and data
- **Plaid** for brokerage account connectivity
- **Polygon (or similar)** for market data

The long-term goal is to support live portfolio optimization (including options), weekly trade scouting, and eventually quantum-powered optimizers.

---

## 2. High-Level Architecture

**Frontend (apps/web)**  
- Framework: Next.js 14 (App Router)  
- Key areas:
  - `app/layout.tsx` – global layout & providers
  - `app/(protected)/dashboard` – main logged-in dashboard
  - `app/(protected)/portfolio` – positions & P/L views (if present)
  - `app/(protected)/settings` – account, Plaid linking, preferences
- Talks to backend via HTTPS API calls (REST/JSON).
- Uses Supabase session/JWT on the client and forwards it to backend for auth.

**Backend (packages/quantum)**  
- Framework: FastAPI
- Entrypoint: `api.py`
  - Initializes FastAPI app
  - Mounts routers (e.g. Plaid, optimizer, health)
  - Handles Supabase auth verification (JWT)
- Routers:
  - `plaid_endpoints.py` – Plaid Link exchange, item/token handling, account / positions sync
  - Other routers (e.g. optimizer) may live in this package as the app matures
- Core logic:
  - `optimizer.py` – portfolio optimization logic (risk/return, options, “high conviction” ideas, quantum hooks)

**Data & External Services**

- **Supabase**
  - Auth: JWT session for logged-in users
  - Database: positions, accounts, user preferences, optimizer outputs (planned / partial)
- **Plaid**
  - Used to connect user’s brokerage account(s)
  - Fetches accounts, holdings, transactions as source of truth for portfolio
- **Polygon (or similar)**
  - Live market prices, options chains, and analytics inputs
- **Quantum / Advanced Backends (future / in progress)**
  - Planned integration with a quantum or quantum-inspired engine (e.g. Dirac 3) for optimization runs

---

## 3. Core Application Flows

### 3.1 Authentication Flow (Supabase → Frontend → Backend)

1. User logs in through Supabase on the frontend.
2. Supabase returns a session containing a JWT.
3. Frontend stores session (usually in a provider or cookie) and includes the JWT on API calls to the backend.
4. Backend (FastAPI) validates the Supabase JWT before executing protected routes:
   - Extract token from Authorization header or cookie
   - Verify via Supabase client or shared signing key
   - Attach current user / user_id to the request context

**Fragility to watch:**

- Any refactor of auth helpers or environment variable names can easily break this chain.
- Circular imports between `api.py` and auth / router modules can cause `ImportError` and crash startup.

---

### 3.2 Plaid Flow (Link → Holdings → Portfolio View)

1. User opens **Settings** in the frontend and starts Plaid Link.
2. Plaid returns a `public_token` to the frontend.
3. Frontend calls a backend route (in `plaid_endpoints.py`) to exchange the `public_token` for an `access_token` and link identifier.
4. Backend stores the Plaid item/access token and initiates or schedules:
   - Account sync (balances, account metadata)
   - Holdings / positions sync (symbol, quantity, cost basis, etc.)
5. Backend writes holdings into the Supabase DB.
6. Dashboard / portfolio pages fetch positions from the backend (which reads from the DB, not from Plaid every time).

**Key invariants:**

- `plaid_endpoints.py` should be a *leaf* module imported by `api.py`, not importing `api.py` itself.
- Frontend should treat Plaid connection state as “derived from backend,” not local flags.

---

### 3.3 Optimizer & Weekly Scout (Current / Planned)

1. Frontend requests optimization or weekly trade suggestions.
2. Backend gathers:
   - Current positions (from DB)
   - Live market prices / options data (from Polygon or other)
3. `optimizer.py`:
   - Builds an internal representation of the portfolio.
   - Applies algorithms (risk targeting, diversification, options signals).
   - Returns:
     - Target weights and/or allocations,
     - Recommended trades (shares, contracts, directions),
     - Risk/return metrics, and possibly a P&L projection.
4. Backend sends the result as JSON to the frontend for display.

Planned enhancements:

- Explicit “high conviction” option plays when signals are strong.
- Ability to choose between classical optimizer vs. quantum-backed optimizer (Dirac-3 or similar).

---

## 4. Current Risk Areas

Based on recent debugging and refactors, these are the most fragile zones:

1. **Auth & Security**
   - Supabase JWT verification logic in `api.py` can easily break if environment variables or helper functions are renamed.
   - Centralizing auth logic without introducing circular imports is an ongoing challenge.

2. **Plaid Router & Import Graph**
   - `ImportError: cannot import name 'router' from 'plaid_endpoints'` has happened when:
     - `plaid_endpoints.py` imports something that imports `api.py` back.
   - `plaid_endpoints.py` must remain a leaf module.

3. **State Sync Between Settings and Dashboard**
   - After linking Plaid in Settings, the Dashboard sometimes does not reflect the live connection, suggesting:
     - missing refetch / cache invalidation, or
     - missing backend route wiring for “current connection state”.

4. **Readme vs. Code Drift**
   - README and docs sometimes reflect old functionality (“next steps” already implemented), making it easy for AI agents to follow outdated guidance.

---

## 5. Safe Extension Zones

When extending the app (manually or with AI assistance), it is safest to:

1. **Add new routers and modules instead of rewriting core ones**
   - Example: create `auth_routes.py` or `analytics_routes.py` and mount them in `api.py`.
   - Keep `plaid_endpoints.py` focused on Plaid and free of cross-imports.

2. **Wrap existing behavior instead of inlining new logic everywhere**
   - Example: add small helper functions in `optimizer.py` for new strategies rather than rewriting `generate_trade_instructions`.

3. **Guard critical flows with tests**
   - Startup tests: import `api.py` and confirm the app creates without crashing.
   - Integration tests: “Plaid connected → dashboard shows live balances” (even basic ones).

4. **Keep environment variable usage centralized**
   - One place where `SUPABASE_URL`, `SUPABASE_KEY`, `PLAID_*`, etc. are loaded,
   - Then passed into the rest of the code as parameters or via a config object.

---

## 6. Documents & Snapshots for External Review

For external tools (Gemini, ChatGPT, etc.), the following helper files exist in the repo root:

- `repo_structure.txt` – full file tree snapshot
- `backend_structure.txt` – structure of `packages/quantum`
- `frontend_structure.txt` – structure of `apps/web`
- `key_files_backend.txt` – concatenated contents of key backend files:
  - `packages/quantum/api.py`
  - `packages/quantum/plaid_endpoints.py`
  - `packages/quantum/optimizer.py`
- `key_files_frontend.txt` – concatenated contents of key frontend files:
  - `apps/web/app/layout.tsx`
  - `apps/web/app/(protected)/dashboard/page.tsx`
  - `apps/web/app/(protected)/settings/page.tsx`

These files provide a safe “architecture snapshot” to share with AI tools for suggestions without exposing secrets.

---
