# Quantum Backend

This directory contains the Python FastAPI backend for the Quantum application.
Quantum / Dirac development requires Python 3.11–3.12.

## Security v3 Hardening

The backend implements strict security controls for authentication, task execution, and database access.

### 1. Authentication
- **JWT Verification:** All protected routes require a valid Supabase JWT signed with `HS256`. The server enforces `aud`, `exp`, and `sub` claims.
- **Fail-Fast Config:** The server will not start if critical security keys (`SUPABASE_JWT_SECRET`, `ENCRYPTION_KEY`, etc.) are missing.

### 2. Dev Auth Bypass
- A "Test Mode" user (`X-Test-Mode-User`) is available **only** if:
    1. `APP_ENV` is NOT `production`.
    2. `ENABLE_DEV_AUTH_BYPASS` is set to `1` in `packages/quantum/.env`.
    3. The request originates from `localhost`.
- Ensure `NEXT_PUBLIC_ENABLE_DEV_AUTH_BYPASS=1` is set in the frontend `.env.local` to allow the UI to send the required `X-Test-Mode-User` header.

**Verification:**
Use the debug endpoint to check authentication status:
```bash
curl http://127.0.0.1:8000/__auth_debug
```

### 3. Job Runs API: /jobs/*

The canonical surface for job visibility is `/jobs/runs`.

- **Endpoints**:
  - `GET /jobs/runs`: List recent job runs.
  - `GET /jobs/runs/{id}`: Get details of a specific job run.
  - `POST /jobs/runs/{id}/retry`: Manually retry a failed job.

- **Authentication**:
  These endpoints support two authentication methods:
  1. **User Auth**: Standard Supabase JWT (for Frontend Dashboard).
  2. **Cron Auth**: `X-Cron-Secret` header (for System/Cron tasks).

### 4. Internal Tasks
- Scheduled tasks (Morning Brief, Midday Scan) are hosted on `/internal/tasks/...`.
- These endpoints are protected by HMAC-SHA256 signature verification.
- Requests must include `X-Task-Signature` and `X-Task-Timestamp`.
- Use `TASK_SIGNING_SECRET` to sign payloads.

### 5. Row Level Security (RLS)
- The API uses a user-scoped Supabase client for all user-initiated operations.
- RLS policies enforce that users can only access their own data.
- The Service Role Key is used strictly for internal system tasks.

## Learning & Attribution Model (Phase 2 Update)

The outcome attribution model has been updated to tie learning signals directly to the *decisions* made by the system, rather than just the input portfolio state.

### Attribution Logic
When computing the "Surprise" score and realized PnL for a trace (an inference/decision event), the system prioritizes sources in the following order:

1.  **Execution (`trade_executions`)**: If the system's suggestion resulted in a trade, the actual realized PnL of that trade is used. This provides the strongest learning signal.
2.  **Suggestion (`trade_suggestions`)**: If a suggestion was generated but not executed (e.g., limit price not hit, or ignored by user), the outcome is marked as `no_action`.
3.  **Optimizer Decision (`decision_logs`)**: If the optimizer generated target weights (e.g., for rebalancing) but no specific trade suggestion was created, the theoretical performance of the target portfolio is simulated.
4.  **Portfolio Snapshot (`inputs_snapshot`)**: Fallback to the legacy method of measuring the performance of the input portfolio (passive hold) if no active decision was recorded.

### Decision Logging
A new table `decision_logs` captures the granular output of the optimizer (target weights) and sizing engines. This ensures that even if a trade is not executed, the *intent* of the system is preserved for "counterfactual" learning (what would have happened if we traded).

## Running Locally

To ensure a consistent environment and automated setup, please use the provided helper scripts. These scripts will:
1. Create a Python virtual environment (`venv`) if it doesn't exist.
2. Install or upgrade all required dependencies (including `python-multipart`).
3. Start the FastAPI server.

### Windows
Double-click `run_server.bat` or run it from the command line:
```cmd
.\run_server.bat
```

### Mac / Linux
Run the shell script:
```bash
./run_server.sh
```

### Verification
To verify you are running the correct backend server (packages/quantum/api.py) and not a rogue instance, run:

```bash
curl http://127.0.0.1:8000/__whoami
```

It should return: `{"server": "packages.quantum.api", "version": "..."}`.

## Manual Setup

If you prefer to run it manually, ensure you are using a virtual environment:

1. Create a virtual environment:
   ```bash
   python -m venv venv
   ```

2. Activate it:
   - Windows: `venv\Scripts\activate`
   - Mac/Linux: `source venv/bin/activate`

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run the server:
   ```bash
   uvicorn api:app --reload
   ```
