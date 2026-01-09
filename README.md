# Options Trading Companion — v2

**v2 (major)** — Active Development
*Next.js Frontend • FastAPI Backend • Supabase Database*

## 1. Architecture

The system is a monorepo composed of three main parts:

*   **Frontend (`apps/web`)**: A Next.js 14 application using Shadcn UI. It runs on `http://localhost:3000` and proxies auth/analytics requests.
*   **Backend (`packages/quantum`)**: A FastAPI Python service handling complex logic (optimization, market data, workflows). It runs on `http://127.0.0.1:8000`.
    *   API Documentation (Swagger) is available at `http://127.0.0.1:8000/docs`.
*   **Database (`supabase`)**: PostgreSQL managed via Supabase, containing migrations for schema management.

## 2. Local Development Workflow

We recommend using **pnpm** for package management.

### Prerequisites
*   Node.js & pnpm
*   Python 3.9+
*   Supabase CLI (for local DB)

### Step-by-Step Setup

1.  **Install Dependencies**
    ```bash
    pnpm install
    ```

2.  **Start Database**
    ```bash
    supabase start
    # If starting fresh or after schema changes:
    supabase db reset
    ```

3.  **Start Backend (Quantum)**
    Open a terminal:
    ```bash
    cd packages/quantum

    # Create/Activate Virtual Env
    # Mac/Linux:
    python3 -m venv venv
    source venv/bin/activate

    # Windows:
    # python -m venv venv
    # venv\Scripts\activate

    # Install Python Deps
    pip install -r requirements.txt

    # Run Server
    # Mac/Linux:
    ./run_server.sh
    # Windows:
    # .\run_server.bat
    ```

4.  **Start Frontend**
    Open a new terminal:
    ```bash
    pnpm --filter "./apps/web" dev
    ```

*Note: Windows users can use `start_app.bat` in the root for a one-click launch, but the manual steps above are preferred for debugging.*

## 3. Environment Variables

This project uses two separate `.env` contexts. **Do not mix them.**

### Frontend & Root (`.env.local` / `.env`)
Copy `.env.example` to `.env` (or `.env.local` for Next.js).
Required variables:
*   `NEXT_PUBLIC_SUPABASE_URL`
*   `NEXT_PUBLIC_SUPABASE_ANON_KEY` (Publishable)
*   `SUPABASE_SERVICE_ROLE_KEY` (Secret - used by backend, but often read from root in dev)

### Backend (`packages/quantum/.env`)
The backend **must** have its own `.env` file for secrets not shared with the client.
Required variables:
*   `SUPABASE_URL`: The API URL of your Supabase instance.
*   `SUPABASE_SERVICE_ROLE_KEY`: The service role key for database access (bypassing RLS).
*   `ENCRYPTION_KEY`: A Fernet URL-safe base64 key.
    *   *Generate one via:* `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
*   `APP_ENV`: Set to `development` to enable test-mode auth.
*   `CRON_SECRET`: A secret string to protect task endpoints.
*   `PLAID_ENV`, `PLAID_CLIENT_ID`, `PLAID_SECRET` (if using Plaid).

## 4. Authentication Modes

The backend supports two authentication methods:

1.  **Standard (Production)**
    *   Header: `Authorization: Bearer <SUPABASE_JWT>`
    *   Used by the frontend when a user is logged in.

2.  **Dev/Test Mode** (Only when `APP_ENV != production`)
    *   Header: `X-Test-Mode-User: <UUID>`
    *   Bypasses JWT validation and impersonates the specified UUID.
    *   Default Test User ID: `75ee12ad-b119-4f32-aeea-19b4ef55d587`

**Example (Curl):**
```bash
curl -X GET "http://127.0.0.1:8000/suggestions?window=midday_entry" \
     -H "X-Test-Mode-User: 75ee12ad-b119-4f32-aeea-19b4ef55d587"
```

## 5. Cron & Task Endpoints

Scheduled tasks are triggered via POST requests protected by the `X-Cron-Secret` header.

**Endpoints:**
*   `/tasks/morning-brief`: Runs morning exit logic (Take Profit).
*   `/tasks/midday-scan`: Runs scanner and sizing for new entries.
*   `/tasks/weekly-report`: Generates weekly performance summaries.
*   `/tasks/universe/sync`: Updates the scanner universe (market caps, volume).
*   `/tasks/plaid/backfill-history`: Backfills portfolio snapshots.

**Example:**
```bash
curl -X POST "http://127.0.0.1:8000/tasks/midday-scan" \
     -H "X-Cron-Secret: YOUR_SECRET_HERE"
```

## 6. Database & Migrations

Supabase migrations are the source of truth for the database schema.

*   **Location:** `supabase/migrations/`
*   **Key Migration:** `20250101000010_add_strategy_fields_to_learning_feedback_loops.sql` (Adds strategy/window tracking).
*   **To Apply:**
    ```bash
    supabase db reset
    ```
    *Warning: This wipes local data and reseeds it.*

## 7. Dark Mode

*   **Current Status:** The CSS (`apps/web/app/globals.css`) supports `.dark` class variables, but there is no UI toggle exposed yet.
*   **Planned:**
    *   Header toggle switch.
    *   Defaulting to dark mode.
    *   Persistence via localStorage or user settings.

## 8. Troubleshooting

*   **Backend Crashes on Start:**
    *   *Cause:* Missing `ENCRYPTION_KEY` in `packages/quantum/.env`.
    *   *Fix:* Generate a Fernet key and add it to the backend `.env`.

*   **401 Unauthorized on Task Endpoints:**
    *   *Cause:* Missing or incorrect `X-Cron-Secret` header.
    *   *Fix:* Ensure `CRON_SECRET` is set in backend env and matches the header in your request.

*   **Weekly Report Errors (`win_rate` NoneType):**
    *   *Risk:* In `workflow_orchestrator.py`, if a user has no trades, `win_rate` might be `None` or missing.
    *   *Workaround:* Ensure `JournalService` returns a valid default (0.0) or handle `None` explicitly in the reporting logic.

---
*Private use only.*
