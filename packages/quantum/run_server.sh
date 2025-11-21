#!/bin/bash
set -e

# Navigate to the directory of the script
cd "$(dirname "$0")"

# Check if venv/bin/python exists
if [ ! -f "venv/bin/python" ]; then
    echo "Creating virtual environment..."
    # Try python3 first, then python
    if command -v python3 &> /dev/null; then
        python3 -m venv venv
    elif command -v python &> /dev/null; then
        python -m venv venv
    else
        echo "Error: Python not found. Please install python3 or python."
        exit 1
    fi
fi

# Define Python executable
PYTHON_EXEC="venv/bin/python"

# Verify it exists
if [ ! -f "$PYTHON_EXEC" ]; then
    echo "Error: Failed to create virtual environment or find python executable at $PYTHON_EXEC"
    exit 1
fi

# Print environment info for debugging
echo "Using Python executable: $PYTHON_EXEC"
"$PYTHON_EXEC" -c "import sys; print(f'Python executable path: {sys.executable}'); print(f'Python version: {sys.version}')"

# Install dependencies
echo "Installing dependencies..."
"$PYTHON_EXEC" -m pip install -r requirements.txt

# Run server
echo "Starting server..."
"$PYTHON_EXEC" -m uvicorn api:app --reload
