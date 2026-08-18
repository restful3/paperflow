#!/usr/bin/env bash
# 커버 백필 재시도 — 비전 모델 쿨다운이 풀리면 1회 실행하고 스스로 멈춘다.
#
# 2026-08-18: 썸네일 없는 폴더 50건을 백필하려 했으나 프록시의 모델 10종 전부가
# `model_cooldown`(429, reset ≈46h) 이었다. 사람이 날짜를 기억해 다시 돌리는 대신
# 주기적으로 값싼 프로브 1회만 던져 보고, 살아나면 그때 백필한다.
#
# 동작:
#   1. 완료 마커가 있으면 즉시 종료 (cron 을 지우지 않아도 무해)
#   2. 남은 대상 0건이면 마커를 남기고 종료
#   3. 비전 프로브 1회 실패(쿨다운 등) → 로그만 남기고 종료 0 (다음 틱에 재시도)
#   4. 프로브 성공 → backfill_covers.py --apply 실행, 결과 기록, 잔여 0건이면 마커
set -uo pipefail
REPO="/media/restful3/data/workspace/paperflow"
LOG="$REPO/logs/cover_backfill_retry.log"
DONE="$REPO/logs/.cover_backfill_done"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

cd "$REPO" || exit 1
mkdir -p "$(dirname "$LOG")"
[[ -f "$DONE" ]] && exit 0

_eligible() {
  python3 scripts/backfill_covers.py 2>/dev/null \
    | sed -n 's/^=> \([0-9]\{1,\}\) folders ELIGIBLE.*/\1/p' | head -1
}

ELIG="$(_eligible)"
if [[ ! "${ELIG:-}" =~ ^[0-9]+$ ]]; then
  echo "$STAMP  ABORT — 대상 수를 읽지 못했습니다(backfill_covers.py 출력 형식 변경?)" >> "$LOG"
  exit 1
fi
if (( ELIG == 0 )); then
  echo "$STAMP  DONE — 남은 대상 0건, 재시도 종료" >> "$LOG"
  : > "$DONE"
  exit 0
fi

# 값싼 프로브 1회 — 64px 단색 이미지로 비전 경로만 확인한다.
PROBE="$(python3 - <<'PY' 2>&1
import base64, io, os, sys

for line in open(".env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

model = os.getenv("COVER_MODEL") or os.getenv("TRANSLATION_MODEL", "")
try:
    from PIL import Image
    from openai import OpenAI
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 40, 40)).save(buf, format="JPEG")
    url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"])
    client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": 'JSON 으로만: {"ok": true}'},
            {"type": "image_url", "image_url": {"url": url}}]}],
        temperature=0.1, timeout=60,
    )
except Exception as e:
    print(f"PROBE_FAIL model={model} {str(e).splitlines()[0][:160]}")
    sys.exit(1)
print(f"PROBE_OK model={model}")
PY
)"
PROBE_RC=$?

if (( PROBE_RC != 0 )); then
  echo "$STAMP  WAIT — 대상 ${ELIG}건, 비전 프로브 실패: $(printf '%s' "$PROBE" | tail -1)" >> "$LOG"
  exit 0
fi

echo "$STAMP  RUN — 대상 ${ELIG}건, $(printf '%s' "$PROBE" | tail -1)" >> "$LOG"
OUT="$(python3 scripts/backfill_covers.py --apply 2>&1)"
printf '%s\n' "$OUT" | tail -8 >> "$LOG"

LEFT="$(_eligible)"
if [[ "${LEFT:-}" =~ ^[0-9]+$ ]] && (( LEFT == 0 )); then
  echo "$STAMP  DONE — 백필 완료, 잔여 0건" >> "$LOG"
  : > "$DONE"
else
  echo "$STAMP  PARTIAL — 잔여 ${LEFT:-?}건 (모델이 커버를 거절한 문서는 계속 남습니다)" >> "$LOG"
  : > "$DONE"   # 프로브가 살아 있는데도 남은 건은 '거절'이므로 무한 재시도하지 않는다
fi
exit 0
