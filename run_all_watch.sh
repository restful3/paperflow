#!/bin/bash
# PaperFlow combined watch entrypoint (converter container):
# runs the papers watch (newones/) and the books watch (newbooks/) concurrently.
# Both pipelines serialize on the shared GPU flock (main_terminal._gpu_lock),
# so concurrent processing is safe.

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [all-watch] $1"; }

log "Starting papers watch (run_batch_watch.sh) + books watch (run_book_watch.sh)"
./run_batch_watch.sh &
BATCH_PID=$!
./run_book_watch.sh &
BOOK_PID=$!

cleanup() { log "stopping"; kill "$BATCH_PID" "$BOOK_PID" 2>/dev/null; }
trap cleanup SIGINT SIGTERM

# If either watch exits, stop the other so the container restarts cleanly.
wait -n
log "a watch exited; shutting down the other"
cleanup
wait
