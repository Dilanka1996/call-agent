#!/bin/bash
# Install dependencies and run tests
# Requires: Python 3.11+

set -e

echo "Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

echo "Installing dependencies..."
pip install -r requirements.txt

echo ""
echo "Running tests..."
PYTHONPATH=. pytest tests/ -v

echo ""
echo "Done! To run CLI: source .venv/bin/activate && PYTHONPATH=. python main.py"
