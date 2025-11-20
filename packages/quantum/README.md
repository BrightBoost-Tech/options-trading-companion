# Quantum Backend

This directory contains the Python FastAPI backend for the Quantum application.

## Running Locally

To avoid environment mismatches (like `ModuleNotFoundError`), it is highly recommended to run the server using the provided helper scripts which set up a virtual environment for you.

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
