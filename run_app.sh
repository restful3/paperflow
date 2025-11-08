#!/bin/bash

# PaperFlow Streamlit Viewer Launcher
# Activates virtual environment and runs the Streamlit app

PORT=8501

echo "Starting PaperFlow Viewer..."
echo ""

# Check if port 8501 is already in use
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠ Port $PORT is already in use"
    PID=$(lsof -ti:$PORT)
    echo "  Process ID: $PID"
    echo "  Killing existing process..."
    kill -9 $PID 2>/dev/null
    sleep 1
    echo "✓ Port $PORT freed"
    echo ""
fi

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "✓ Virtual environment activated"
else
    echo "✗ Virtual environment not found. Please run ./setup_venv.sh first"
    exit 1
fi

# Check if streamlit is installed
if ! python -c "import streamlit" 2>/dev/null; then
    echo "✗ Streamlit not installed. Installing dependencies..."
    pip install -r requirements.txt
fi

echo ""
echo "========================================"
echo "  PaperFlow Viewer"
echo "========================================"
echo ""
echo "Server running at http://localhost:$PORT"
echo "Press Ctrl+C to stop the server"
echo ""

# Run Streamlit app without opening browser
streamlit run app.py --server.port=$PORT --server.headless=true
