#!/bin/bash
set -e

# Navigate to the directory of the script
cd "$(dirname "$0")"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Run server
echo "Starting server..."
python -m uvicorn api:app --reload
