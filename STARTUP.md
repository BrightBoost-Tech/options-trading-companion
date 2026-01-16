# Startup Instructions

## One-Click Start (Recommended)

Double-click **`start.bat`** in the repository root, or use `scripts\win\start_all.cmd`.

This will:
1. Start **Redis** via Docker (if Docker is running)
2. Launch the **Backend** (Uvicorn) in a new terminal window
3. Launch the **Worker** (RQ with SimpleWorker) in a new terminal window
4. Launch the **Frontend** (Next.js) in a new terminal window

All services will stay running. Close the terminal windows to stop them, or run `scripts\win\stop_all.cmd`.

## Creating a Desktop Shortcut (Windows)

1. Right-click on your desktop → **New** → **Shortcut**
2. For the location, enter:
   ```
   C:\options-trading-companion\scripts\win\start_all.cmd
   ```
   (Replace with your actual repo path)
3. Name it "Options Trading Companion"
4. Click **Finish**

The shortcut will work without any "Start in" configuration needed.

## PowerShell Scripts

The launcher system is built on PowerShell for reliability. You can also run PowerShell scripts directly:

```powershell
# Start everything
.\scripts\win\start_all.ps1

# Start with options
.\scripts\win\start_all.ps1 -SkipFrontend    # Skip frontend
.\scripts\win\start_all.ps1 -WorkerOnly      # Only start Redis + Worker

# Stop everything
.\scripts\win\stop_all.ps1
.\scripts\win\stop_all.ps1 -KeepRedis        # Keep Redis running
```

## Individual Launchers

| Service | PowerShell | CMD | Port |
|---------|------------|-----|------|
| All Services | `start_all.ps1` | `start_all.cmd` | — |
| Backend API | `start_backend.ps1` | — | 8000 |
| Frontend | `start_frontend.ps1` | — | 3000 |
| Worker | `start_worker.ps1` | — | — |
| Redis | `start_redis.ps1` | — | 6379 |

Scripts are located in `scripts\win\`.

## Environment Variables

The PowerShell scripts automatically load environment variables from (in priority order):
1. `.env.local` (repo root)
2. `.env` (repo root)
3. `packages\quantum\.env.local`
4. `packages\quantum\.env`

Both frontend-style (`NEXT_PUBLIC_SUPABASE_URL`) and backend-style (`SUPABASE_URL`) variable names are supported.

## Stopping Services

```powershell
# PowerShell
.\scripts\win\stop_all.ps1

# CMD
scripts\win\stop_all.cmd
```

Or close the terminal windows individually.

## Sanity Checks (Windows)

If you see an error like `is not recognized` or cannot find the path:

1. **Check your folder:** Open `cmd` and type `dir`. You should see `scripts` and `packages` in the list.
2. **Check the script:** Run `dir scripts\win`. You should see `start_all.cmd` and `start_all.ps1`.
3. **Run with full path:** Use the full path to the script.
4. **Check if already running:** Run `netstat -ano | findstr :8000`. If you see a result, the port is busy.
5. **PowerShell execution policy:** If PowerShell scripts don't run, try:
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
   ```

## Prerequisites

* **Docker Desktop**: Required for Redis. Install from [docker.com](https://www.docker.com/products/docker-desktop/)
* **pnpm**: This repository uses `pnpm` workspaces. Enable via corepack:
    ```bash
    corepack enable
    corepack prepare pnpm@latest --activate
    ```
* **Python venv**: Ensure the backend virtual environment exists at `packages\quantum\venv`
* **Node.js 18+**: Required for the frontend

## Dependency Verification

If you encounter module resolution errors (e.g., `Module not found: Can't resolve ...`), run:

```bash
pnpm install
```

from the repository root. The frontend launcher automatically detects missing dependencies and runs `pnpm install` if needed.
