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

# Install common requirements
echo ""
echo "ℹ Installing common requirements..."
pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "✗ Failed to install common requirements"
    exit 1
fi

# Determine PDF converter from .env (default: marker)
PDF_CONVERTER="marker"
if [ -f ".env" ]; then
    env_val=$(grep -E "^PDF_CONVERTER=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' "'"'"'')
    if [ -n "$env_val" ]; then
        PDF_CONVERTER="$env_val"
    fi
fi

echo ""
echo "ℹ PDF converter: $PDF_CONVERTER"

# Install converter-specific requirements
if [ "$PDF_CONVERTER" = "mineru" ]; then
    echo "ℹ Installing MinerU requirements..."
    pip install -r requirements-mineru.txt
else
    echo "ℹ Installing marker-pdf requirements..."
    pip install -r requirements-marker.txt
fi

if [ $? -ne 0 ]; then
    echo "✗ Failed to install converter requirements"
    exit 1
fi

echo ""
echo "=================================================="
echo "✓ Setup Complete!"
echo "=================================================="
echo ""
echo "PDF Converter: $PDF_CONVERTER"
echo ""
echo "To activate the virtual environment, run:"
echo "  source .venv/bin/activate"
echo ""
echo "To run the application:"
echo "  ./run_batch_watch.sh    # Watch mode (recommended)"
echo "  ./run_batch.sh          # One-shot batch"
echo ""
echo "To change the PDF converter, edit .env:"
echo "  PDF_CONVERTER=marker    # Fast, general-purpose"
echo "  PDF_CONVERTER=mineru    # Better math/table recognition"
echo "Then re-run: ./setup_venv.sh"
echo ""
