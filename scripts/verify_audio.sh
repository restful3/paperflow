#!/usr/bin/env bash
# verify_audio.sh — 낭독판(_ko_audio.md / _ko_audio_brief.md) 정적 검사기.
#
# 범위: 이 스크립트는 "자동화 가능한 정적 게이트"만 본다 —
#   (1) 금지 마크업 0건  (2) alt/title 있는 이미지 0건  (3) brief 의 `## 헤더 ≥4`.
# 다음은 여기서 보지 않는다(스킬 Verification 에서 사람이/에이전트가 확인):
#   분량 비율(wc -m 대 소스), 섹션 coverage, 마무리 한 줄, 용어집 잔향,
#   그림 묘사-실물 일치. 라틴 변수 잔존은 이미지 경로 오탐 때문에 WARN 로만 낸다.
# 즉 이 스크립트의 PASS 는 "정적 검사 통과"이지 "스킬 전체 통과"가 아니다.
#
# WHY: 이 정적 검사들은 "특정 패턴이 0건이어야 통과"다. GNU grep 은 0건일 때 exit 1,
#      실행 오류일 때 exit 2 를 낸다. 스킬 지시를 그냥 grep 으로 돌리면
#      (특히 `set -e`) 통과 케이스(0건, exit 1)를 실패로 오독하기 쉽다.
#      이 스크립트가 "명령 / 매치 수 / exit code" 를 분리해 판정을 고정한다.
#
# 사용법:
#   scripts/verify_audio.sh <file> [audio|brief]
#     기본 모드 = 파일명으로 추론(_ko_audio_brief.md → brief, 그 외 → audio)
# 종료 코드: 정적 검사 모두 통과 시 0, 하나라도 실패 시 1, 사용법/입력 오류 2.

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
if [[ "$mode" != "audio" && "$mode" != "brief" ]]; then
  echo "error: mode must be 'audio' or 'brief' (got '$mode')" >&2
  exit 2
fi

# 멀티바이트 안전 truncation (cut -c 는 바이트 단위라 한글을 깨뜨림)
clip() { awk -v n="${2:-70}" 'BEGIN{FS="\n"} {print substr($0,1,n); exit}'; }

fail=0
pass_line() { printf '  PASS  %-38s %s\n' "$1" "$2"; }
fail_line() { printf '  FAIL  %-38s %s\n' "$1" "$2"; fail=1; }

# must_be_zero <name> <regex>
# 통과 = 0건. grep exit: 0(매치있음)→FAIL, 1(0건)→PASS, 2(오류)→FAIL.
must_be_zero() {
  local name="$1" re="$2" out rc n
  out="$(grep -nE "$re" "$file" 2>/dev/null)"; rc=$?
  if [[ $rc -eq 2 ]]; then fail_line "$name" "grep 실행 오류(exit 2)"; return; fi
  if [[ $rc -eq 1 || -z "$out" ]]; then pass_line "$name" "0건"; return; fi
  n="$(printf '%s\n' "$out" | grep -c . )"
  fail_line "$name" "${n}건 (예: $(printf '%s' "$out" | head -1 | clip 70))"
}

echo "== verify_audio [정적 검사] ($mode) : $file =="

# 1) 금지 마크업 0건 (수식·표구분선·code fence·[N]인용·footnote·HTML태그·앵커·bare URL)
#    그림 이미지 ![](경로) 는 의도적 허용 → 패턴에서 제외.
must_be_zero "no-markup" '\$\$|\$[^$]+\$|\\\(|\\\[|^[[:space:]]*\|.*---|^```|\[[0-9]+\]|\[\^|<sup|<span|<br|</?[a-zA-Z]|\]\(#|https?://'

# 2) alt 있는 이미지 0건 (alt 는 반드시 비움 — raw TTS 가 alt/ title 을 읽음)
must_be_zero "no-alt-image" '!\[[^]]+\]\('
# 2b) title 문법 ![](경로 "title") 0건
must_be_zero "no-image-title" '!\[\][(][^)]*"[^)]*[)]'

# 3) 단독 라틴 변수 잔존 (변수 기호가 알파벳 그대로 — 이미지 경로 줄은 오탐 가능)
#    WARN 만: 이미지 경로 오탐이 있어 자동 FAIL 하지 않고 육안 확인을 유도.
lat="$(grep -nE '(^|[ "(])[a-zA-Z]([ ,.]|는|은|이|가|의|$)' "$file" 2>/dev/null | grep -vE '!\[\]\(' )"
if [[ -n "$lat" ]]; then
  n="$(printf '%s\n' "$lat" | grep -c .)"
  printf '  WARN  %-38s %s\n' "latin-var-residue" "${n}건 — 육안 확인(변수기호면 한글 음차)"
else
  pass_line "latin-var-residue" "0건"
fi

# 4) 마무리 한 줄 — INFO 만(닫는 문장 여부 자동판정 불가). 스킬 CRITICAL 로 별도 확인.
last="$(grep -nE '.' "$file" | tail -1 | cut -d: -f2-)"
printf '  INFO  %-38s %s\n' "last-line(스킬이 별도 확인)" "$(printf '%s' "$last" | clip 60)"

# 5) brief 전용: 섹션 골격 (## 헤더 ≥4)
if [[ "$mode" == "brief" ]]; then
  h="$(grep -cE '^## ' "$file" 2>/dev/null || true)"
  if [[ "${h:-0}" -ge 4 ]]; then pass_line "brief-h2-skeleton" "## 헤더 ${h}개(≥4)"; else fail_line "brief-h2-skeleton" "## 헤더 ${h:-0}개(<4) — 벽 문단 실패"; fi
fi

echo "== 정적 검사 결과(STATIC CHECKS): $([[ $fail -eq 0 ]] && echo PASS || echo FAIL) =="
echo "   (분량·coverage·마무리·그림 실물일치는 스킬 Verification 에서 별도 확인)"
exit $fail
