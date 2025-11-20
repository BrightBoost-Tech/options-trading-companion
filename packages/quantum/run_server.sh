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

# Activate venv
source venv/bin/activate

# Print environment info for debugging
echo "Using Python executable: $(which python)"
python -c "import sys; print(f'Python executable path: {sys.executable}'); print(f'Python version: {sys.version}')"

# Install dependencies
echo "Installing dependencies..."
python -m pip install -r requirements.txt

# Run server
echo "Starting server..."
python -m uvicorn api:app --reload
