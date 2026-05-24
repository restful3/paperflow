#!/bin/bash

# PaperFlow Watch Mode - Continuous PDF Processing
# This script continuously monitors the newones directory and processes PDFs as they arrive

WATCH_INTERVAL=5  # Check every 5 seconds
NEWONES_DIR="newones"
OUTPUTS_DIR="outputs"
LOGS_DIR="logs"
FAILED_DIR="${NEWONES_DIR}/failed"
CANCEL_FILE="${LOGS_DIR}/cancel_requests.json"
RUNTIME_FILE="${LOGS_DIR}/processing_runtime.json"
FAIL_FILE="${LOGS_DIR}/fail_counts.json"
PROCESS_TIMEOUT_SECONDS="${PROCESS_TIMEOUT_SECONDS:-2400}"
MAX_RETRIES="${MAX_RETRIES:-2}"

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

get_cancel_action() {
    local filename="$1"
    python3 - "$CANCEL_FILE" "$filename" <<'PY'
import json,sys
p,fn=sys.argv[1],sys.argv[2]
try:
    d=json.load(open(p,'r',encoding='utf-8'))
    for r in d.get('requests',[]):
        if r.get('filename')==fn:
            print('delete' if r.get('delete_file',True) else 'cancel')
            sys.exit(0)
except Exception:
    pass
print('none')
PY
}

clear_cancel_action() {
    local filename="$1"
    python3 - "$CANCEL_FILE" "$filename" <<'PY'
import json,sys,os
p,fn=sys.argv[1],sys.argv[2]
try:
    d=json.load(open(p,'r',encoding='utf-8'))
except Exception:
    d={'requests':[]}
req=[r for r in d.get('requests',[]) if r.get('filename')!=fn]
d['requests']=req
os.makedirs(os.path.dirname(p),exist_ok=True)
tmp=p+'.tmp'
with open(tmp,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False)
os.replace(tmp,p)
PY
}

set_runtime_state() {
    local filename="$1"; local pid="$2"
    python3 - "$RUNTIME_FILE" "$filename" "$pid" <<'PY'
import json,sys,os,datetime
p,fn,pid=sys.argv[1],sys.argv[2],int(sys.argv[3])
os.makedirs(os.path.dirname(p),exist_ok=True)
d={'current_file':fn,'pid':pid,'started_at':datetime.datetime.now().isoformat()}
tmp=p+'.tmp'
with open(tmp,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False)
os.replace(tmp,p)
PY
}

clear_runtime_state() {
    [ -f "$RUNTIME_FILE" ] && rm -f "$RUNTIME_FILE"
}

write_idle_status() {
    local detail="$1"
    python3 - "$LOGS_DIR/processing_status.json" "$detail" <<'PY'
import json,sys,os,datetime
p,detail=sys.argv[1],sys.argv[2]
os.makedirs(os.path.dirname(p),exist_ok=True)
d={
  'current_file':None,'stage':'idle','stage_num':0,'total_stages':0,
  'stage_label':'Idle','updated_at':datetime.datetime.now().isoformat(),
  'error':None,'detail':detail,'sub_progress':None
}
tmp=p+'.tmp'
with open(tmp,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False)
os.replace(tmp,p)
PY
}

inc_fail_count() {
    local filename="$1"
    python3 - "$FAIL_FILE" "$filename" <<'PY'
import json,sys,os
p,fn=sys.argv[1],sys.argv[2]
try: d=json.load(open(p,'r',encoding='utf-8'))
except Exception: d={}
d[fn]=int(d.get(fn,0))+1
os.makedirs(os.path.dirname(p),exist_ok=True)
tmp=p+'.tmp'
with open(tmp,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False)
os.replace(tmp,p)
print(d[fn])
PY
}

reset_fail_count() {
    local filename="$1"
    python3 - "$FAIL_FILE" "$filename" <<'PY'
import json,sys,os
p,fn=sys.argv[1],sys.argv[2]
try: d=json.load(open(p,'r',encoding='utf-8'))
except Exception: d={}
if fn in d: del d[fn]
os.makedirs(os.path.dirname(p),exist_ok=True)
tmp=p+'.tmp'
with open(tmp,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False)
os.replace(tmp,p)
PY
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
mkdir -p "$FAILED_DIR"

log_info "Watching directory: $NEWONES_DIR"
log_info "Check interval: ${WATCH_INTERVAL}s"
log_info "Press Ctrl+C to stop"
echo ""

# Main watch loop
processing_pid=""
while true; do
    # Find all PDF files in newones
    pdf_files=$(find "$NEWONES_DIR" -maxdepth 1 -name "*.pdf" -type f 2>/dev/null)

    # Count PDF files safely
    if [ -n "$pdf_files" ]; then
        pdf_count=$(echo "$pdf_files" | wc -l)
    else
        pdf_count=0
    fi

    if [ "$pdf_count" -gt 0 ]; then
        # PDF files found - process each one separately in new Python process
        log_success "Found $pdf_count PDF file(s) - starting processing"
        echo ""

        # Process each PDF in a separate Python process to avoid CUDA context pollution
        echo "$pdf_files" | while read -r pdf_file; do
            if [ -n "$pdf_file" ] && [ -f "$pdf_file" ]; then
                pdf_name=$(basename "$pdf_file")
                log_info "Processing: $pdf_name (in new Python process)"

                # Run processing in background to allow cancel/timeout supervision
                PAPERFLOW_TARGET_PDF="$pdf_file" .venv/bin/python main_terminal.py &
                processing_pid=$!
                set_runtime_state "$pdf_name" "$processing_pid"
                start_ts=$(date +%s)
                processing_status=""

                while kill -0 "$processing_pid" 2>/dev/null; do
                    cancel_action=$(get_cancel_action "$pdf_name")
                    if [ "$cancel_action" != "none" ]; then
                        log_warning "Cancel requested for $pdf_name (action=$cancel_action)"
                        kill "$processing_pid" 2>/dev/null || true
                        sleep 3
                        kill -9 "$processing_pid" 2>/dev/null || true
                        wait "$processing_pid" 2>/dev/null || true
                        if [ "$cancel_action" = "delete" ]; then
                            rm -f "$pdf_file"
                            rm -f "${NEWONES_DIR}/.meta/${pdf_name}.url.txt" "${NEWONES_DIR}/${pdf_name}.url.txt" 2>/dev/null || true
                            rm -rf "${OUTPUTS_DIR}/${pdf_name%.pdf}" 2>/dev/null || true
                            # Also remove any output dir that already contains this source PDF
                            while IFS= read -r d; do
                                [ -n "$d" ] && rm -rf "$d" 2>/dev/null || true
                            done < <(find "${OUTPUTS_DIR}" -mindepth 1 -maxdepth 1 -type d -exec sh -c 'test -f "$1/$2" && echo "$1"' _ {} "$pdf_name" \; 2>/dev/null)
                        fi
                        clear_cancel_action "$pdf_name"
                        write_idle_status "Cancelled: $pdf_name"
                        processing_status=130
                        break
                    fi

                    now_ts=$(date +%s)
                    elapsed=$((now_ts - start_ts))
                    if [ "$elapsed" -gt "$PROCESS_TIMEOUT_SECONDS" ]; then
                        log_error "Timeout: $pdf_name exceeded ${PROCESS_TIMEOUT_SECONDS}s, killing"
                        kill "$processing_pid" 2>/dev/null || true
                        sleep 3
                        kill -9 "$processing_pid" 2>/dev/null || true
                        wait "$processing_pid" 2>/dev/null || true
                        write_idle_status "Timeout-killed: $pdf_name"
                        processing_status=124
                        break
                    fi
                    sleep 1
                done

                if [ -z "$processing_status" ]; then
                    wait "$processing_pid"
                    processing_status=$?
                fi
                clear_runtime_state

                if [ "$processing_status" -eq 0 ]; then
                    reset_fail_count "$pdf_name"
                    log_success "Completed: $pdf_name"
                else
                    retry_count=$(inc_fail_count "$pdf_name")
                    log_error "Failed: $pdf_name (exit code: $processing_status, retry=$retry_count/$MAX_RETRIES)"
                    if [ "$retry_count" -ge "$MAX_RETRIES" ] && [ -f "$pdf_file" ]; then
                        mv "$pdf_file" "$FAILED_DIR/$pdf_name" 2>/dev/null || true
                        log_warning "Moved to failed queue: $FAILED_DIR/$pdf_name"
                        write_idle_status "Moved to failed after retries: $pdf_name"
                    fi
                fi
                echo ""
            fi
        done

        echo ""
        log_success "All PDFs processed"
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
