@echo off
SETLOCAL

REM Navigate to the directory of the script
CD /D "%~dp0"

REM Check if venv exists
IF NOT EXIST "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Define the Python executable path within the virtual environment
SET PYTHON_EXEC=venv\Scripts\python.exe

REM Fallback to global python if venv python is missing (unlikely if venv creation succeeded)
IF NOT EXIST "%PYTHON_EXEC%" (
    echo Warning: venv python not found. Falling back to system python.
    SET PYTHON_EXEC=python
)

REM Print environment info for debugging
echo Using Python executable: %PYTHON_EXEC%
"%PYTHON_EXEC%" -c "import sys; print(f'Python executable path: {sys.executable}'); print(f'Python version: {sys.version}')"

REM Install dependencies
echo Installing dependencies...
"%PYTHON_EXEC%" -m pip install -r requirements.txt

REM Run server
echo Starting server...
"%PYTHON_EXEC%" -m uvicorn api:app --reload

ENDLOCAL
