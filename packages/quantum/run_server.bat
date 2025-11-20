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

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

REM Run server
echo Starting server...
python -m uvicorn api:app --reload

ENDLOCAL
