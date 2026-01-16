# Startup Instructions

## One-Click Start (Recommended)

Double-click **`start.bat`** in the repository root, or use `scripts\win\start_all.cmd`.

This will:
1. Start **Redis** via Docker (if Docker is running)
2. Launch the **Backend** (Uvicorn) in a new terminal window
3. Launch the **Worker** (background job processor) in a new terminal window
4. Launch the **Frontend** (Next.js) in a new terminal window

All services will stay running. Close the terminal windows to stop them, or run `scripts\win\stop_all.cmd`.

## Creating a Desktop Shortcut (Windows)

1. Right-click on your desktop → **New** → **Shortcut**
2. For the location, enter:
   ```
   cmd.exe /c "C:\path\to\options-trading-companion\scripts\win\start_all.cmd"
   ```
   (Replace `C:\path\to` with your actual repo path)
3. Name it "Options Trading Companion"
4. Right-click the shortcut → **Properties**
5. Set **Start in:** to your repo root (e.g., `C:\options-trading-companion`)
6. Click **OK**

**Alternative:** You can also create a shortcut directly to `start.bat` or `scripts\win\start_all.cmd`.

## Individual Launchers

If you need to launch services individually:

| Service | Script | Port |
|---------|--------|------|
| Backend API | `scripts\win\start_backend.cmd` | 8000 |
| Frontend | `scripts\win\start_frontend.cmd` | 3000 |
| Worker | `scripts\win\start_worker.cmd` | — |
| Redis | `docker compose -f docker-compose.redis.yml up -d` | 6379 |

## Stopping Services

Run `scripts\win\stop_all.cmd` to stop all services, or close the terminal windows individually.

## Sanity Checks (Windows)

If you see an error like `is not recognized` or cannot find the path:

1. **Check your folder:** Open `cmd` and type `dir`. You should see `scripts` and `packages` in the list.
2. **Check the script:** Run `dir scripts\win`. You should see `start_all.cmd`.
3. **Run with full path:** Use the full path to the script.
4. **Check if already running:** Run `netstat -ano | findstr :8000`. If you see a result, the port is busy.

## Dark Mode Verification

To verify the Dashboard dark mode:

1. Open the application (http://localhost:3000)
2. Navigate to the **Dashboard**
3. Toggle the theme to **Dark Mode** using the sun/moon icon in the top right
4. **Checklist:**
    * [ ] **Dashboard Title**: Text should be readable (white/light gray) against the background
    * [ ] **Cards**: Cards should have a dark background (`bg-card`) with subtle borders
    * [ ] **Positions Table**: Headers and rows should be readable with appropriate dark backgrounds
    * [ ] **Optimizer Panel**: Backgrounds should be dark with proper text contrast
    * [ ] **Trade Suggestions**: Suggestion cards should use dark-mode compatible colors

## Prerequisites

* **Docker Desktop**: Required for Redis. Install from [docker.com](https://www.docker.com/products/docker-desktop/)
* **pnpm**: This repository uses `pnpm` workspaces. Enable via corepack:
    ```bash
    corepack enable
    corepack prepare pnpm@latest --activate
    ```
* **Python venv**: Ensure the backend virtual environment exists at `packages\quantum\.venv` or `packages\quantum\venv`
* **Node.js 18+**: Required for the frontend

## Dependency Verification

If you encounter module resolution errors (e.g., `Module not found: Can't resolve ...`), run:

```bash
pnpm install
```

from the repository root. The frontend launcher automatically detects missing dependencies and runs `pnpm install` if needed.
