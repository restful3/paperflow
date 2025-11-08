#!/bin/bash

# PaperFlow Batch Processing Script (with virtual environment)
# This script processes all PDF files in the newones directory

echo "=================================================="
echo "PaperFlow - Batch PDF Processing"
echo "=================================================="
echo ""

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "⚠ Virtual environment not found"
    echo "ℹ Please run ./setup_venv.sh first"
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Create required directories
mkdir -p newones
mkdir -p outputs

# Check if newones directory has PDF files
pdf_count=$(find newones -maxdepth 1 -name "*.pdf" 2>/dev/null | wc -l)

if [ $pdf_count -eq 0 ]; then
    echo "⚠ No PDF files found in 'newones' directory"
    echo "ℹ Please add PDF files to the 'newones' directory and run this script again"
    exit 0
fi

echo "ℹ Found $pdf_count PDF file(s) to process"
echo ""

# Run the terminal version
python main_terminal.py

echo ""
echo "=================================================="
echo "Processing Complete"
echo "=================================================="
echo "ℹ Check the 'outputs' directory for results"

# Deactivate virtual environment
deactivate
