#!/bin/bash

# PaperFlow Mac - Watch Mode Script
# Continuously monitors for new PDFs and processes them automatically
# Uses Apple Silicon MPS GPU

echo "=================================================="
echo "PaperFlow Mac - Watch Mode"
echo "=================================================="
echo ""

# Check if virtual environment exists
if [ ! -d ".venv_mac" ]; then
    echo "⚠ Mac virtual environment not found"
    echo "ℹ Please run ./setup_venv_mac.sh first"
    exit 1
fi

# Create required directories
mkdir -p newones
mkdir -p outputs

echo "ℹ Watching 'newones' directory for PDF files..."
echo "ℹ Press Ctrl+C to stop"
echo ""

# Flag to track if we need to check for PDFs
check_needed=true

# Trap Ctrl+C to cleanly exit
trap ctrl_c INT
function ctrl_c() {
    echo ""
    echo "ℹ Shutting down watch mode..."
    echo "✓ Watch mode stopped"
    exit 0
}

while true; do
    # Check if newones directory has PDF files
    pdf_count=$(find newones -maxdepth 1 -name "*.pdf" 2>/dev/null | wc -l)

    if [ $pdf_count -gt 0 ]; then
        # Found PDFs, process them
        timestamp=$(date '+%Y-%m-%d %H:%M:%S')
        echo "[$timestamp] ✓ Found $pdf_count PDF file(s) - starting processing"
        echo ""

        # Process each PDF in a separate Python process to avoid CUDA context pollution
        for pdf in newones/*.pdf; do
            if [ -f "$pdf" ]; then
                timestamp=$(date '+%Y-%m-%d %H:%M:%S')
                pdf_name=$(basename "$pdf")
                echo "[$timestamp] ℹ Processing: $pdf_name (in new Python process)"

                # Activate venv and run in subprocess
                source .venv_mac/bin/activate
                .venv_mac/bin/python main_terminal_mac.py
                deactivate

                timestamp=$(date '+%Y-%m-%d %H:%M:%S')
                echo "[$timestamp] ✓ Completed: $pdf_name"
                echo ""
            fi
        done

        timestamp=$(date '+%Y-%m-%d %H:%M:%S')
        echo "[$timestamp] ✓ All PDFs processed"
        timestamp=$(date '+%Y-%m-%d %H:%M:%S')
        echo "[$timestamp] ℹ Returning to watch mode..."
        echo ""

        check_needed=false
    else
        # No PDFs found
        if [ "$check_needed" = true ]; then
            # Only print "no files" message once after processing
            timestamp=$(date '+%Y-%m-%d %H:%M:%S')
            echo "[$timestamp] ℹ No PDF files found, waiting..."
        fi
        check_needed=false
    fi

    # Wait 5 seconds before checking again
    sleep 5

    # Set flag to check again next iteration
    if [ $pdf_count -eq 0 ]; then
        check_needed=true
    fi
done
