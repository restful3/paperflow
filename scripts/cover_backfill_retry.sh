#!/usr/bin/env bash
# 커버(썸네일) 상시 유지보수 — 새로 등록된 문서도 하루 안에 썸네일을 갖게 한다.
#
# 2026-08-18 사고 배경:
#   ① 커버 선별은 폴더 안 이미지 중에서만 고르고 표·플롯·로고·인물샷은 거절한다
#      → arXiv 논문처럼 그림이 전부 표·플롯이면 영구히 썸네일이 없다
#   ② 비전 모델이 쿨다운(429)이면 커버 선별이 조용히 실패한다
#   두 경우 모두 "새 글에 썸네일이 없다" 로 나타나고, 사람이 눈으로 발견할 때까지
#   아무도 몰랐다. 그래서 파이프라인 밖에서 주기적으로 메꾼다.
#
# 매 실행:
#   1. 비전 후보가 있는 폴더가 있으면 값싼 프로브 1회 → 살아 있을 때만 비전 백필
#   2. 그래도 커버가 없고 원본 PDF 가 있으면 PDF 1페이지 상단을 커버로 (멱등)
#   3. 한 줄 요약만 로그. 할 일이 없으면 조용히 종료
set -uo pipefail
REPO="/media/restful3/data/workspace/paperflow"
LOG="$REPO/logs/cover_backfill_retry.log"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

cd "$REPO" || exit 1
mkdir -p "$(dirname "$LOG")"

_eligible() {
  python3 scripts/backfill_covers.py 2>/dev/null \
    | sed -n 's/^=> \([0-9]\{1,\}\) folders ELIGIBLE.*/\1/p' | head -1
}
_pdf_targets() {
  python3 scripts/backfill_pdf_page_covers.py 2>/dev/null \
    | sed -n 's/^대상 \([0-9]\{1,\}\)건.*/\1/p' | head -1
}

ELIG="$(_eligible)"
PDFT="$(_pdf_targets)"
[[ "${ELIG:-}" =~ ^[0-9]+$ ]] || ELIG=0
[[ "${PDFT:-}" =~ ^[0-9]+$ ]] || PDFT=0

if (( ELIG == 0 && PDFT == 0 )); then
  exit 0                      # 할 일 없음 — 로그도 남기지 않는다(로그 팽창 방지)
fi

VISION="skipped"
if (( ELIG > 0 )); then
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
    print(f"PROBE_FAIL model={model} {str(e).splitlines()[0][:140]}")
    sys.exit(1)
print(f"PROBE_OK model={model}")
PY
)"
  if (( $? == 0 )); then
    OUT="$(python3 scripts/backfill_covers.py --apply 2>&1)"
    VISION="$(printf '%s' "$OUT" | sed -n 's/^.*covered *: *\([0-9]\{1,\}\).*/covered=\1/p' | head -1)"
    VISION="${VISION:-ran}"
  else
    VISION="probe_fail($(printf '%s' "$PROBE" | tail -1 | cut -c1-70))"
  fi
fi

PDFOUT="none"
if (( PDFT > 0 )); then
  OUT2="$(python3 scripts/backfill_pdf_page_covers.py --apply 2>&1)"
  PDFOUT="$(printf '%s' "$OUT2" | tail -1)"
fi

echo "$STAMP  vision-eligible=$ELIG vision=$VISION | pdf-targets=$PDFT pdf=$PDFOUT" >> "$LOG"
exit 0
