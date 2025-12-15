# Startup Instructions

## One-Click Start (Recommended)

Double-click **`start.bat`** in the repository root.

This will:
1. Launch the **Backend** (Uvicorn) in a new terminal window.
2. Launch the **Frontend** (Next.js) in a separate terminal window.

Both services will stay running. You can close them by closing their respective terminal windows.

## Backend Only

If you only need to run the backend:
1. Go to `packages\quantum`.
2. Double-click **`run_server.bat`**.

## Configuration

If the frontend directory changes, open `start.bat` in a text editor and update the `FRONTEND_DIR` variable.

```bat
set "FRONTEND_DIR=%REPO_ROOT%\apps\web"
```
