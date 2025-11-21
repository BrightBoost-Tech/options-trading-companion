@echo off
SETLOCAL

REM Navigate to the directory of the script
CD /D "%~dp0"

REM Check if venv/Scripts/python.exe exists.
IF NOT EXIST "venv\Scripts\python.exe" (
    echo Virtual environment not found. Creating virtual environment...
    python -m venv venv
    IF %ERRORLEVEL% NEQ 0 (
        echo Error: Failed to create virtual environment. Please ensure python is installed and in your PATH.
        PAUSE
        EXIT /B 1
    )
)

REM Define the Python executable path within the virtual environment
SET PYTHON_EXEC=venv\Scripts\python.exe

REM Verify that the python executable exists now
IF NOT EXIST "%PYTHON_EXEC%" (
    echo Error: Python executable not found at %PYTHON_EXEC%
    PAUSE
    EXIT /B 1
)

REM Install/Upgrade dependencies
echo Installing dependencies...
"%PYTHON_EXEC%" -m pip install --upgrade pip
"%PYTHON_EXEC%" -m pip install -r requirements.txt

IF %ERRORLEVEL% NEQ 0 (
    echo Error: Failed to install dependencies.
    PAUSE
    EXIT /B 1
)

REM Run server
echo Starting server...
"%PYTHON_EXEC%" -m uvicorn api:app --reload --host 127.0.0.1 --port 8000

ENDLOCAL
