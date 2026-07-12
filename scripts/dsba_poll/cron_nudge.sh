#!/usr/bin/env bash
# 매일 cron 이 호출: tmux paperflow:claude(구독 내 인터랙티브 Claude) 입력창에
# /dsba-playlist-poll 스킬을 주입해 재생목록 폴링을 돌린다. (claude -p 미사용 = 과금 회피)
#
# 한계: 그 윈도우의 Claude 가 살아 있고 입력 가능 상태여야 한다. 세션/윈도우 부재 시 조용히 skip.
set -euo pipefail

SESSION="paperflow"
WIN="claude"
LOG="/media/restful3/data/workspace/paperflow/logs/dsba_poll.log"

ts() { date '+%F %T'; }
log() { echo "$(ts) [nudge] $*" >>"$LOG" 2>/dev/null || true; }

if ! command -v tmux >/dev/null 2>&1; then log "tmux 없음 — skip"; exit 0; fi
if ! tmux has-session -t "$SESSION" 2>/dev/null; then log "tmux 세션 '$SESSION' 없음 — skip"; exit 0; fi
if ! tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$WIN"; then
  log "윈도우 '$WIN' 없음 — skip"; exit 0
fi

TARGET="${SESSION}:${WIN}"
# -l = 리터럴(슬래시를 tmux 명령으로 해석하지 않음). Enter 는 약간의 텀을 두고 별도 전송.
tmux send-keys -t "$TARGET" -l "/dsba-playlist-poll daily auto-run"
sleep 1
tmux send-keys -t "$TARGET" Enter
log "nudged $TARGET"
