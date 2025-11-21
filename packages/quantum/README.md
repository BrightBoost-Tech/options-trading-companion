# Quantum Backend

This directory contains the Python FastAPI backend for the Quantum application.

## Running Locally

To ensure a consistent environment and automated setup, please use the provided helper scripts. These scripts will:
1. Create a Python virtual environment (`venv`) if it doesn't exist.
2. Install or upgrade all required dependencies (including `python-multipart`).
3. Start the FastAPI server.

### Windows
Double-click `run_server.bat` or run it from the command line:
```cmd
.\run_server.bat
```

### Mac / Linux
Run the shell script:
```bash
./run_server.sh
```

## Manual Setup

If you prefer to run it manually, ensure you are using a virtual environment:

1. Create a virtual environment:
   ```bash
   python -m venv venv
   ```

2. Activate it:
   - Windows: `venv\Scripts\activate`
   - Mac/Linux: `source venv/bin/activate`

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run the server:
   ```bash
   uvicorn api:app --reload
   ```
