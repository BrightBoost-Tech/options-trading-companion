# Startup Instructions

## One-Click Start (Recommended)

Double-click **`start.bat`** (or `start_app.bat`) in the repository root.

This will:
1. Launch the **Backend** (Uvicorn) in a new terminal window.
2. Launch the **Frontend** (Next.js) in a separate terminal window.

Both services will stay running. You can close them by closing their respective terminal windows.

## Individual Launchers

If you need to launch services individually, you can use the scripts in `scripts\win\`:

*   **Backend:** `scripts\win\start_backend.cmd`
*   **Frontend:** `scripts\win\start_frontend.cmd`

## Dependency Verification

If you encounter module resolution errors (e.g., `Module not found: Can't resolve ...`), verify that dependencies are correctly installed using pnpm:

```bash
# Verify a specific package exists in the frontend workspace
pnpm --filter @app/web list @radix-ui/react-tooltip

# If missing or broken, run:
pnpm install
```

## Prerequisites

*   **pnpm**: This repository uses `pnpm` workspaces. Ensure `pnpm` is installed or enabled via corepack:
    ```bash
    corepack enable
    corepack prepare pnpm@latest --activate
    ```
*   **Python venv**: Ensure the backend virtual environment exists at `packages\quantum\venv`.
