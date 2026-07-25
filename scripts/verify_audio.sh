#!/usr/bin/env bash
# verify_audio.sh — 낭독판(_ko_audio.md / _ko_audio_brief.md) CRITICAL 검증기.
#
# WHY: 이 검증들은 "특정 패턴이 0건이어야 통과"다. GNU grep 은 0건일 때 exit 1,
#      실행 오류일 때 exit 2 를 낸다. 스킬 지시를 그냥 grep 으로 돌리면
#      (특히 `set -e`) 통과 케이스(0건, exit 1)를 실패로 오독하기 쉽다.
#      이 스크립트가 "명령 / 매치 수 / exit code" 를 분리해 판정을 고정한다.
#
# 사용법:
#   scripts/verify_audio.sh <file> [audio|brief]
#     기본 모드 = 파일명으로 추론(_ko_audio_brief.md → brief, 그 외 → audio)
# 종료 코드: 모든 CRITICAL 통과 시 0, 하나라도 실패 시 1.
#
# 이 스크립트는 grep/구조 게이트만 본다. 분량 비율(wc -m 대 소스 해설판)과
# 그림 묘사-실물 대조(vision)는 스킬이 별도로 수행한다.

set -u  # NOTE: set -e 는 쓰지 않는다 (grep 0건=exit1 을 실패로 만들기 때문)

file="${1:-}"
mode="${2:-}"
if [[ -z "$file" || ! -f "$file" ]]; then
  echo "usage: $0 <file> [audio|brief]" >&2
  echo "  (file not found: '$file')" >&2
  exit 2
fi
if [[ -z "$mode" ]]; then
  case "$file" in
    *_ko_audio_brief.md) mode="brief" ;;
    *) mode="audio" ;;
  esac
fi

fail=0
pass_line() { printf '  PASS  %-38s %s\n' "$1" "$2"; }
fail_line() { printf '  FAIL  %-38s %s\n' "$1" "$2"; fail=1; }

# count_matches <name> <regex>
# 통과 = 0건. grep exit: 0(매치있음)→FAIL, 1(0건)→PASS, 2(오류)→FAIL.
must_be_zero() {
  local name="$1" re="$2" out rc n
  out="$(grep -nE "$re" "$file" 2>/dev/null)"; rc=$?
  if [[ $rc -eq 2 ]]; then fail_line "$name" "grep 실행 오류(exit 2)"; return; fi
  if [[ $rc -eq 1 || -z "$out" ]]; then pass_line "$name" "0건"; return; fi
  n="$(printf '%s\n' "$out" | grep -c . )"
  fail_line "$name" "${n}건 (예: $(printf '%s' "$out" | head -1 | cut -c1-70))"
}

echo "== verify_audio ($mode) : $file =="

# 1) 금지 마크업 0건 (수식·표구분선·code fence·[N]인용·footnote·HTML태그·앵커·bare URL)
#    그림 이미지 ![](경로) 는 의도적 허용 → 패턴에서 제외.
must_be_zero "no-markup" '\$\$|\$[^$]+\$|\\\(|\\\[|^[[:space:]]*\|.*---|^```|\[[0-9]+\]|\[\^|<sup|<span|<br|</?[a-zA-Z]|\]\(#|https?://'

# 2) alt 있는 이미지 0건 (alt 는 반드시 비움 — raw TTS 가 alt/ title 을 읽음)
must_be_zero "no-alt-image" '!\[[^]]+\]\('
# 2b) title 문법 ![](경로 "title") 0건
must_be_zero "no-image-title" '!\[\][(][^)]*"[^)]*[)]'

# 3) 단독 라틴 변수 잔존 (변수 기호가 알파벳 그대로 — 이미지 경로 줄은 오탐 가능, 육안 확인 필요)
#    참고용 리포트: 0건 강제하지 않고 카운트만 (이미지 경로 오탐 때문).
lat="$(grep -nE '(^|[ "(])[a-zA-Z]([ ,.]|는|은|이|가|의|$)' "$file" 2>/dev/null | grep -vE '!\[\]\(' )"
if [[ -n "$lat" ]]; then
  n="$(printf '%s\n' "$lat" | grep -c .)"
  printf '  WARN  %-38s %s\n' "latin-var-residue" "${n}건 — 육안 확인(변수기호면 한글 음차)"
else
  pass_line "latin-var-residue" "0건"
fi

# 4) 마무리 한 줄 존재 (마지막 비어있지 않은 줄이 낭독 종료를 알리는 문장인가 — 육안)
last="$(grep -nE '.' "$file" | tail -1 | cut -d: -f2-)"
printf '  INFO  %-38s %s\n' "last-line" "$(printf '%s' "$last" | cut -c1-60)"

# 5) brief 전용: 섹션 골격 (## 헤더 ≥4)
if [[ "$mode" == "brief" ]]; then
  h="$(grep -cE '^## ' "$file" 2>/dev/null || true)"
  if [[ "${h:-0}" -ge 4 ]]; then pass_line "brief-h2-skeleton" "## 헤더 ${h}개(≥4)"; else fail_line "brief-h2-skeleton" "## 헤더 ${h:-0}개(<4) — 벽 문단 실패"; fi
fi

echo "== 결과: $([[ $fail -eq 0 ]] && echo PASS || echo FAIL) =="
exit $fail
