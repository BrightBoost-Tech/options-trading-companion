@echo off
SETLOCAL

REM Navigate to the directory of the script
CD /D "%~dp0"

REM Check if venv exists
IF NOT EXIST "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate venv
CALL venv\Scripts\activate

REM Print environment info for debugging
echo Using Python executable:
where python
python -c "import sys; print(f'Python executable path: {sys.executable}'); print(f'Python version: {sys.version}')"

REM Install dependencies
echo Installing dependencies...
python -m pip install -r requirements.txt

REM Run server
echo Starting server...
python -m uvicorn api:app --reload

ENDLOCAL
