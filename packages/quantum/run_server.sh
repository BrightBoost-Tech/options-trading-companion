#!/bin/bash
set -e

# Navigate to the directory of the script
cd "$(dirname "$0")"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    # Try python3 first, then python
    if command -v python3 &> /dev/null; then
        python3 -m venv venv
    else
        python -m venv venv
    fi
fi

# Define Python executable
PYTHON_EXEC="venv/bin/python"

# Fallback if not found (though venv creation should ensure it)
if [ ! -f "$PYTHON_EXEC" ]; then
    echo "Warning: venv python not found. Falling back to system python."
    PYTHON_EXEC="python"
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
