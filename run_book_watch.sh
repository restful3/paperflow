#!/bin/bash
# PaperFlow Books Watch Mode — newbooks/<Book>/NN_chapter.pdf 증분 처리
# 챕터당 별도 Python 프로세스(CUDA 컨텍스트 오염 방지 + VRAM cleanup).

WATCH_INTERVAL="${BOOK_WATCH_INTERVAL:-5}"
NEWBOOKS_DIR="newbooks"
BOOKS_DIR="books"
LOGS_DIR="logs"
PROCESS_TIMEOUT_SECONDS="${PROCESS_TIMEOUT_SECONDS:-2400}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

if [ ! -d ".venv" ]; then
    log "ERROR: .venv not found — run ./setup_venv.sh first"
    exit 1
fi
source .venv/bin/activate
mkdir -p "$NEWBOOKS_DIR" "$BOOKS_DIR" "$LOGS_DIR"

cleanup() { log "Books watch stopped"; deactivate 2>/dev/null; exit 0; }
trap cleanup SIGINT SIGTERM

log "Watching '$NEWBOOKS_DIR' for chapter PDFs (interval ${WATCH_INTERVAL}s, Ctrl+C to stop)"

while true; do
    # newbooks/<Book>/NN_chapter.pdf — depth-2 PDFs only, ignore .part
    while IFS= read -r pdf; do
        [ -n "$pdf" ] && [ -f "$pdf" ] || continue
        case "$pdf" in *.part) continue;; esac
        name=$(basename "$pdf")
        log "Chapter found: $pdf — processing in fresh process"
        PAPERFLOW_TARGET_CHAPTER_PDF="$pdf" timeout "$PROCESS_TIMEOUT_SECONDS" \
            .venv/bin/python book_ingest.py "$pdf"
        rc=$?
        case "$rc" in
            0) log "Done: $name" ;;
            2) log "Not ready yet (size-stable gate): $name — will retry next pass" ;;
            *) log "Failed (rc=$rc): $name" ;;
        esac
    done < <(find "$NEWBOOKS_DIR" -mindepth 2 -maxdepth 2 -name "*.pdf" -type f 2>/dev/null | sort)

    sleep "$WATCH_INTERVAL"
done
