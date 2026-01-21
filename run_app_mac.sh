#!/bin/bash

# PaperFlow Mac - Streamlit Viewer Launch Script

echo "=================================================="
echo "PaperFlow Mac - Launching Web Viewer"
echo "=================================================="
echo ""

# Check if virtual environment exists
if [ ! -d ".venv_mac" ]; then
    echo "⚠ Mac virtual environment not found"
    echo "ℹ Please run ./setup_venv_mac.sh first"
    exit 1
fi

# Kill any existing Streamlit processes on port 8501
echo "ℹ Checking for existing Streamlit processes..."
lsof -ti:8501 | xargs kill -9 2>/dev/null
sleep 1

# Activate virtual environment
source .venv_mac/bin/activate

# Launch Streamlit app
echo "ℹ Starting Streamlit app..."
echo "ℹ Opening browser at http://localhost:8501"
echo ""

.venv_mac/bin/streamlit run app.py

# Deactivate when done
deactivate
