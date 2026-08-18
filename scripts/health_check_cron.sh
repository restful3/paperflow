#!/usr/bin/env bash
# outputs/archives 건전성 일일 점검 (cron).
#
# 2026-08-09 교훈: 로그에만 남기면 아무도 안 본다 — 빈 카드 66건이 그렇게 쌓였다.
# 결함이 있을 때만 Tori 로 1회 통지하고, 없으면 조용히 로그만 남긴다.
set -uo pipefail
REPO="/media/restful3/data/workspace/paperflow"
LOG="$REPO/logs/health_check.log"
COUNCIL="${COUNCIL:-/home/restful3/.local/bin/council}"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

cd "$REPO" || exit 1
mkdir -p "$(dirname "$LOG")"

REPORT="$(python3 scripts/check_outputs_health.py --max-list 8 2>&1)"
RC=$?

if (( RC == 0 )); then
  echo "$STAMP  OK" >> "$LOG"
  exit 0
fi

# 자동 복구 — missing_meta 는 twin 복사만으로 결정적으로 고쳐진다(LLM 호출 없음).
#
# 2026-08-18 교훈: 08-16 에 감지된 빈 카드 53건이 08-18 까지 그대로 남아 있었다.
# "감지 → 사람이 복구 명령을 실행" 사이가 끊기면 감지는 무의미하다. 고칠 수
# 있는 결함은 스스로 고치고, 그 결과를 리포트에 반영한다.
if printf '%s' "$REPORT" | grep -q '\[missing_meta\]'; then
  REPAIR="$(python3 scripts/backfill_metadata.py --twin-only --apply 2>&1)"
  echo "$STAMP  AUTO-REPAIR (missing_meta, twin-only): $(printf '%s' "$REPAIR" | tail -1)" >> "$LOG"
  REPORT="$(python3 scripts/check_outputs_health.py --max-list 8 2>&1)"
  RC=$?
  if (( RC == 0 )); then
    echo "$STAMP  OK (자동 복구로 해소)" >> "$LOG"
    exit 0
  fi
fi

{
  echo "$STAMP  DEFECTS FOUND"
  echo "$REPORT"
  echo "---"
} >> "$LOG"

# 결함 있을 때만 통지 (없으면 침묵 — 알림 피로 방지)
#
# 2026-08-18 교훈: 전송 결과를 >/dev/null 2>&1 || true 로 버렸더니, 08-16~18 통지
# 3건이 hub.db 에 status='queued' 로 쌓인 채 Tori 가 집어가지 않았고 3일간 아무도
# 몰랐다. 감지 공백은 메웠지만 전달 공백이 남아 있었다 → 전송 결과도 로그에 남긴다.
if [[ -x "$COUNCIL" ]]; then
  SUMMARY="$(printf '%s\n' "$REPORT" | head -20)"
  SEND_OUT="$("$COUNCIL" send tori "PaperFlow 건전성 점검에서 결함이 발견됐습니다. 태영님께 텔레그램으로 알려주세요.

$SUMMARY

복구: cd $REPO && python3 scripts/backfill_metadata.py --apply
전체 리포트: python3 scripts/check_outputs_health.py" 2>&1)"
  SEND_RC=$?
  if (( SEND_RC == 0 )); then
    echo "$STAMP  notify enqueued (council send tori rc=0): $(printf '%s' "$SEND_OUT" | head -1)" >> "$LOG"
  else
    echo "$STAMP  notify FAILED rc=$SEND_RC: $(printf '%s' "$SEND_OUT" | head -3 | tr '\n' ' ')" >> "$LOG"
  fi

  # rc=0 은 "큐에 넣었다" 뿐이다 — Tori 가 집어가지 않으면 전달은 안 된다.
  # 이번 사고가 정확히 그것이었으므로(3건 queued 방치), 적체를 직접 센다.
  # hub.db·sqlite3 가 없으면 조용히 건너뛴다(통지 경로를 막지 않는다).
  HUB="${PEER_COUNCIL_DB:-$HOME/.peer-council/hub.db}"
  if [[ -r "$HUB" ]] && command -v sqlite3 >/dev/null 2>&1; then
    STUCK="$(sqlite3 "file:$HUB?mode=ro" \
      "select count(*) from requests where to_agent='tori' and status='queued' and payload like '%건전성%';" \
      2>/dev/null)"
    if [[ "${STUCK:-0}" =~ ^[0-9]+$ ]] && (( STUCK > 1 )); then
      echo "$STAMP  notify STUCK — 건전성 통지 ${STUCK}건이 queued 상태로 적체(Tori 드레인 정지 의심)" >> "$LOG"
    fi
  fi
else
  echo "$STAMP  notify SKIPPED — council not executable: $COUNCIL" >> "$LOG"
fi
exit "$RC"
