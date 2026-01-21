#!/bin/bash

# PaperFlow Mac Setup Script
# Creates a Python 3.11+ virtual environment with Mac-specific dependencies

echo "=================================================="
echo "PaperFlow Mac - Virtual Environment Setup"
echo "=================================================="
echo ""

# Check if Python 3.11+ is available
if ! command -v python3.11 &> /dev/null; then
    echo "⚠ Python 3.11 not found"
    echo "ℹ Checking for Python 3.12 or higher..."

    # Try to find any Python 3.11+
    for version in 3.12 3.13 3.14; do
        if command -v python$version &> /dev/null; then
            PYTHON_CMD="python$version"
            echo "✓ Found $PYTHON_CMD"
            break
        fi
    done

    if [ -z "$PYTHON_CMD" ]; then
        echo "✗ Python 3.11 or higher is required for Mac version"
        echo "ℹ Install Python 3.11+ with Homebrew:"
        echo "    brew install python@3.11"
        exit 1
    fi
else
    PYTHON_CMD="python3.11"
fi

echo "ℹ Using: $PYTHON_CMD"
$PYTHON_CMD --version
echo ""

# Check if virtual environment already exists
if [ -d ".venv_mac" ]; then
    echo "⚠ Virtual environment already exists at .venv_mac"
    read -p "Do you want to recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "ℹ Removing existing virtual environment..."
        rm -rf .venv_mac
    else
        echo "ℹ Using existing virtual environment"
        exit 0
    fi
fi

# Create virtual environment
echo "ℹ Creating virtual environment with $PYTHON_CMD..."
$PYTHON_CMD -m venv .venv_mac

if [ $? -ne 0 ]; then
    echo "✗ Failed to create virtual environment"
    exit 1
fi

echo "✓ Virtual environment created"
echo ""

# Activate virtual environment
source .venv_mac/bin/activate

# Upgrade pip
echo "ℹ Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "ℹ Installing Mac-specific dependencies..."
pip install -r requirements_mac.txt

if [ $? -ne 0 ]; then
    echo "✗ Failed to install dependencies"
    deactivate
    exit 1
fi

echo ""
echo "=================================================="
echo "✓ Setup Complete!"
echo "=================================================="
echo ""
echo "Next steps:"
echo "  1. Start Ollama service (if not running):"
echo "     ollama serve"
echo ""
echo "  2. Download translation model:"
echo "     ollama pull qwen3-vl:30b"
echo ""
echo "  3. Process PDFs:"
echo "     ./run_batch_mac.sh"
echo ""
echo "  4. View results:"
echo "     ./run_app_mac.sh"
echo ""

deactivate
