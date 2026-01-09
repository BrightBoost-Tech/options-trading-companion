# Startup Instructions

## One-Click Start (Recommended)

Double-click **`start.bat`** (or `start_app.bat`) in the repository root.

This will:
1. Launch the **Backend** (Uvicorn) in a new terminal window.
2. Launch the **Frontend** (Next.js) in a separate terminal window.

Both services will stay running. You can close them by closing their respective terminal windows.

## Individual Launchers

If you need to launch services individually, you can use the scripts in `scripts\win\`:

*   **Backend:** `.\scripts\win\start_backend.cmd`
*   **Frontend:** `.\scripts\win\start_frontend.cmd`

### Sanity Checks (Windows)

If you see an error like `is not recognized` or cannot find the path:

1.  **Check your folder:** Open `cmd` and type `dir`. You should see `scripts` and `packages` in the list.
2.  **Check the script:** Run `dir scripts\win`. You should see `start_backend.cmd`.
3.  **Run with relative path:** Use `.\scripts\win\start_backend.cmd`.
4.  **Check if already running:** Run `netstat -ano | findstr :8000`. If you see a result, the port is busy.

## Dark Mode Verification

To verify the Dashboard dark mode:

1.  Open the application (e.g., http://localhost:3000).
2.  Navigate to the **Dashboard**.
3.  Toggle the theme to **Dark Mode** using the sun/moon icon in the top right.
4.  **Checklist:**
    *   [ ] **Dashboard Title**: Text should be readable (white/light gray) against the background.
    *   [ ] **Cards**: Cards should have a dark background (`bg-card`) with subtle borders.
    *   [ ] **Positions Table**:
        *   Headers should be readable.
        *   Row backgrounds should be dark (e.g., `bg-card` or transparent).
        *   Section headers (Option Plays, Long Term Holds) should have appropriate dark backgrounds (e.g., `dark:bg-purple-900/20`).
    *   [ ] **Optimizer Panel**:
        *   Backgrounds should be dark.
        *   Text should be `text-foreground` or `text-muted-foreground`.
        *   Icons should have appropriate contrast.
    *   [ ] **Trade Suggestions**:
        *   Suggestion cards should not be white.
        *   Badges (IV, Score) should use dark-mode compatible colors (e.g., `dark:bg-purple-900/30`).
    *   [ ] **Historical Simulation**:
        *   The panel should integrate seamlessly with the dark theme.
        *   Results text should be readable.

## Dependency Verification

If you encounter module resolution errors (e.g., `Module not found: Can't resolve ...`), verify that dependencies are correctly installed using pnpm.

**Note:** The frontend launcher (`start_frontend.cmd`) now automatically detects missing dependencies and runs `pnpm install` if needed.

If you pull changes that update Tailwind config, run pnpm install.

If you still see "Module not found", run:

```bash
pnpm install
```

from the repository root.

## Prerequisites

*   **pnpm**: This repository uses `pnpm` workspaces. Ensure `pnpm` is installed or enabled via corepack:
    ```bash
    corepack enable
    corepack prepare pnpm@latest --activate
    ```
*   **Python venv**: Ensure the backend virtual environment exists at `packages\quantum\venv`.
