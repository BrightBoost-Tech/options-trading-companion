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

# Activate the virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Run server
echo "Starting server..."
uvicorn api:app --reload --host 127.0.0.1 --port 8000
