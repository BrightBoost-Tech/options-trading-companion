@echo off
SETLOCAL

REM Navigate to the directory of the script
CD /D "%~dp0"

REM Check if venv/Scripts/python.exe exists. If not, we assume venv is missing or broken and recreate it.
IF NOT EXIST "venv\Scripts\python.exe" (
    echo Virtual environment not found or broken. Creating virtual environment...
    python -m venv venv
)

REM Define the Python executable path within the virtual environment
SET PYTHON_EXEC=venv\Scripts\python.exe

REM Verify that the python executable exists now
IF NOT EXIST "%PYTHON_EXEC%" (
    echo Error: Failed to create virtual environment or find python executable at %PYTHON_EXEC%
    echo Please ensure python is installed and available in your PATH.
    EXIT /B 1
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
