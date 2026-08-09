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

{
  echo "$STAMP  DEFECTS FOUND"
  echo "$REPORT"
  echo "---"
} >> "$LOG"

# 결함 있을 때만 통지 (없으면 침묵 — 알림 피로 방지)
if [[ -x "$COUNCIL" ]]; then
  SUMMARY="$(printf '%s\n' "$REPORT" | head -20)"
  "$COUNCIL" send tori "PaperFlow 건전성 점검에서 결함이 발견됐습니다. 태영님께 텔레그램으로 알려주세요.

$SUMMARY

복구: cd $REPO && python3 scripts/backfill_metadata.py --apply
전체 리포트: python3 scripts/check_outputs_health.py" >/dev/null 2>&1 || true
fi
exit "$RC"
