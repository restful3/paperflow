#!/bin/bash

# PaperFlow Watch Mode - Continuous PDF Processing
# This script continuously monitors the newones directory and processes PDFs as they arrive

WATCH_INTERVAL=5  # Check every 5 seconds
NEWONES_DIR="newones"
OUTPUTS_DIR="outputs"
LOGS_DIR="logs"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print with timestamp
log_info() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} ℹ $1"
}

log_success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} ✓ $1"
}

log_warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} ⚠ $1"
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} ✗ $1"
}

# Cleanup function for Ctrl+C
cleanup() {
    echo ""
    log_info "Shutting down watch mode..."
    if [ -n "$processing_pid" ]; then
        log_warning "Waiting for current processing to complete..."
        wait $processing_pid
    fi
    deactivate 2>/dev/null
    log_success "Watch mode stopped"
    exit 0
}

trap cleanup SIGINT SIGTERM

echo "=================================================="
echo "PaperFlow - Watch Mode"
echo "=================================================="
echo ""

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    log_error "Virtual environment not found"
    log_info "Please run ./setup_venv.sh first"
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate
log_success "Virtual environment activated"

# Create required directories
mkdir -p "$NEWONES_DIR"
mkdir -p "$OUTPUTS_DIR"
mkdir -p "$LOGS_DIR"

log_info "Watching directory: $NEWONES_DIR"
log_info "Check interval: ${WATCH_INTERVAL}s"
log_info "Press Ctrl+C to stop"
echo ""

# Main watch loop
processing_pid=""
while true; do
    # Count PDF files in newones
    pdf_count=$(find "$NEWONES_DIR" -maxdepth 1 -name "*.pdf" -type f 2>/dev/null | wc -l)

    if [ $pdf_count -gt 0 ]; then
        # PDF files found - start processing
        log_success "Found $pdf_count PDF file(s) - starting processing"
        echo ""

        # Run processing
        .venv/bin/python main_terminal.py &
        processing_pid=$!

        # Wait for processing to complete
        wait $processing_pid
        processing_status=$?
        processing_pid=""

        echo ""
        if [ $processing_status -eq 0 ]; then
            log_success "Processing completed successfully"
        else
            log_error "Processing failed with exit code: $processing_status"
        fi
        echo ""
        log_info "Returning to watch mode..."
        echo ""
    fi

    # Print watching indicator (only every 12th iteration = 1 minute)
    if [ $(($(date +%s) % 60)) -lt $WATCH_INTERVAL ]; then
        log_info "Watching for new PDF files in '$NEWONES_DIR'..."
    fi

    # Sleep before next check
    sleep $WATCH_INTERVAL
done
