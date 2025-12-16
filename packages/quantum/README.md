# Quantum Backend

This directory contains the Python FastAPI backend for the Quantum application.

## Security v3 Hardening

The backend implements strict security controls for authentication, task execution, and database access.

### 1. Authentication
- **JWT Verification:** All protected routes require a valid Supabase JWT signed with `HS256`. The server enforces `aud`, `exp`, and `sub` claims.
- **Fail-Fast Config:** The server will not start if critical security keys (`SUPABASE_JWT_SECRET`, `ENCRYPTION_KEY`, etc.) are missing.

### 2. Dev Auth Bypass
- A "Test Mode" user (`X-Test-Mode-User`) is available **only** if:
    1. `APP_ENV` is NOT `production`.
    2. `ENABLE_DEV_AUTH_BYPASS` is set to `1`.
    3. The request originates from `localhost`.
- Ensure `NEXT_PUBLIC_ENABLE_DEV_AUTH_BYPASS=1` is set in the frontend `.env.local` to allow the UI to send the required `X-Test-Mode-User` header.

### 3. Internal Tasks
- Scheduled tasks (Morning Brief, Midday Scan) are hosted on `/internal/tasks/...`.
- These endpoints are protected by HMAC-SHA256 signature verification.
- Requests must include `X-Task-Signature` and `X-Task-Timestamp`.
- Use `TASK_SIGNING_SECRET` to sign payloads.

### 4. Row Level Security (RLS)
- The API uses a user-scoped Supabase client for all user-initiated operations.
- RLS policies enforce that users can only access their own data.
- The Service Role Key is used strictly for internal system tasks.

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
