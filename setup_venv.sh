#!/bin/bash

echo "=================================================="
echo "PaperFlow - Virtual Environment Setup"
echo "=================================================="
echo ""

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "ℹ Python version: $python_version"

# Create virtual environment
echo ""
echo "ℹ Creating virtual environment (.venv)..."
python3 -m venv .venv

if [ $? -ne 0 ]; then
    echo "✗ Failed to create virtual environment"
    exit 1
fi

echo "✓ Virtual environment created"

# Activate virtual environment
echo ""
echo "ℹ Activating virtual environment..."
source .venv/bin/activate

# Upgrade pip
echo ""
echo "ℹ Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo ""
echo "ℹ Installing requirements..."
pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "✗ Failed to install requirements"
    exit 1
fi

echo ""
echo "=================================================="
echo "✓ Setup Complete!"
echo "=================================================="
echo ""
echo "To activate the virtual environment, run:"
echo "  source .venv/bin/activate"
echo ""
echo "To deactivate, run:"
echo "  deactivate"
echo ""
echo "To run the application:"
echo "  source .venv/bin/activate"
echo "  ./run_batch.sh"
echo ""
