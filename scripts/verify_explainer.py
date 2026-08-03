#!/usr/bin/env python3
"""verify_explainer.py — 해설판(_ko_explained.md) 정적 검사기.

낭독판 `scripts/verify_audio.sh` 와 짝을 이루는 해설판 게이트. 로직은
`tmp/explainer_review/{scan,gate}.py` (2026-07-03 전수 감사에서 실측 검증) 를
승격·정리한 것이다.

범위: **자동화 가능한 정적 게이트만** 본다 —
  파일명/YAML 헤더, 문체(해라체 vs 합니다체), 인접 near-dup, 정형 비유마커,
  매체 과잉설명, 웹 잡동사니, 용어집 유무, 소스 대비 분량비, 이미지 참조 보존.
다음은 여기서 보지 않는다 (스킬 Quality Checks 에서 사람/에이전트가 확인):
  섹션별 claim/숫자/예외 coverage, 비유의 적절성, 수식 해설의 정확성,
  차트 전사 내용이 실물 이미지와 맞는지.
즉 이 스크립트의 PASS 는 "정적 검사 통과"이지 "스킬 전체 통과"가 아니다.

판정 3단계 (council 조언 반영 — hae_p 는 자동 반려가 아니라 REVIEW):
  FAIL   자동 반려. translate-then-restate, 인접 near-dup 다수, 전체 해라체.
  REVIEW 사람 확인 필요하나 lane 을 막지는 않음.
  PASS   정적 검사 통과.

사용법:
  scripts/verify_explainer.py <explained.md> [source.md] [--strict] [--json]
    source.md 생략 시 같은 폴더에서 자동 탐색 (*_ko.md 우선, 없으면 영문 *.md)
    --strict 는 REVIEW 도 반려 (Phase 2 게이트·수동 감사용)
종료 코드: PASS/REVIEW 0, FAIL 1 (--strict 면 REVIEW 도 1), 사용법/입력 오류 2.
"""
import glob
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional

# --- 임계값 (gate.py 실측값 계승) -------------------------------------------
HAE_FAIL = 4          # 해라체 문단 4+ → 실패 계열
HAP_COEXIST = 3       # 합니다체 3+ 와 공존하면 translate-then-restate
ADJDUP_FAIL = 4       # 인접 near-dup 4곳+ → 실패
ADJDUP_JACCARD = 0.5  # 인접 문단 content-word 자카드 유사도 임계
CLICHE_REVIEW = 3     # 정형 비유마커 3회+ → REVIEW
MEDIA_REVIEW = 2      # 매체 과잉설명 2회+ → REVIEW
RATIO_FLOOR = 0.6     # 외국어 소스 대비 하한 (미만이면 누락 의심)
RATIO_RESTATE = 2.5   # 비논문 소스에서 이 이상이면 재진술 의심

CLICHE_MARKERS = [
    r"비유로 설명하면",
    r"학술 논문이라기보다는",
    r"쉽게 비유하자면",
    r"비유하자면",
    r"쉽게 말하면 이렇습니다",
]
MEDIA_OVEREXPLAIN = [
    r"영국의?\s*(시사)?주간지",
    r"이 매체는",
    r"[은는]\s*[^\n]{0,20}발행되는",
    r"경제\s*전문\s*(주간|매체|잡지)",
    r"[은는]\s*[^\n]{0,15}대표적인\s*(시사|경제|매체)",
]
WEB_CLUTTER = [
    r"Subscribe(\s+to)?\b",
    r"Sign\s+up\b",
    r"Sponsored\s+by",
    r"Follow\s+us\b",
    r"We\s+use\s+cookies",
    r"Related\s+articles",
    r"뉴스레터\s*구독",
    r"구독하기",
    r"쿠키\s*동의",
]
ANALOGY_LABEL = [
    r"^\s*>?\s*\*\*비유[:：]\*\*",
    r"^\s*\*\*비유\s*\d*[:：]?\*\*",
]

HAE_END = re.compile(
    r"(었다|았다|였다|했다|된다|한다|이다|린다|진다|난다|온다|는다|겠다|같다|없다|있다"
    r"|친다|쥔다|긴다|뜬다|판다|샀다|팔다)$"
)


# --- 헬퍼 -------------------------------------------------------------------
def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def strip_yaml(text: str) -> str:
    if text.startswith("---"):
        m = re.match(r"^---\n.*?\n---\n", text, re.S)
        if m:
            return text[m.end():]
    return text


# front-matter 로 인정하는 첫 키. 본문 안의 설정 스니펫(`paths: "src/**"` 등)이
# 수평선 사이에 놓였다고 헤더로 세지 않기 위해 실제 사용 키로 좁힌다.
FM_KEY = r"(?:lang|title|format|author|date|toc|theme|subtitle|categories)"


def yaml_header_count(text: str) -> int:
    """문서 전체에서 front-matter 블록 수 (본문 수평선·설정 스니펫과 구분)."""
    if not text.startswith("---"):
        return 0
    m = re.match(r"^---\n.*?\n---\n", text, re.S)
    if not m:
        return 0
    # 섹션 append 시 헤더가 다시 붙는 결함만 잡는다 — 블록 첫 키가 front-matter 키일 때만.
    rest = text[m.end():]
    dup = re.findall(rf"\n---\n{FM_KEY}:.*?\n---\n", rest, re.S)
    return 1 + len(dup)


def content_words(s: str):
    return set(re.findall(r"[가-힣]{2,}|[A-Za-z]{3,}", s))


def paragraphs(text: str) -> List[str]:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]


def is_prose(b: str) -> bool:
    if b.startswith(("#", "|", ">", "![", "$$", "\\")):
        return False
    if re.match(r"^[\-\*\d]+[\.\)]?\s", b):
        return False
    return len(b) >= 120


def register_paras(body: str):
    """산문 문단을 합니다체/해라체로 분류. 해라체 문단 = 미변환 번역 반쪽 시그니처."""
    t = re.sub(r"```.*?```", "", body, flags=re.S)
    t = re.sub(r"\$\$.*?\$\$", "", t, flags=re.S)
    hae_p = hap_p = 0
    for b in re.split(r"\n\s*\n", t):
        b = b.strip()
        if not b or b.startswith(("#", "|", ">", "!", "-", "*", "$")):
            continue
        if re.match(r"^\d+[\.\)]", b) or len(b) < 80:
            continue
        hap = hae = 0
        for s in re.split(r"[.!?]\s*", b):
            s = s.strip().rstrip('"\'」’)')
            if not s:
                continue
            if s.endswith("니다"):
                hap += 1
            elif HAE_END.search(s) or s.endswith("다"):
                hae += 1
        if hae > hap and hae >= 2:
            hae_p += 1
        elif hap > hae:
            hap_p += 1
    return hap_p, hae_p


def adj_dup_count(body: str) -> int:
    paras = paragraphs(body)
    prose = [(i, b) for i, b in enumerate(paras) if is_prose(b)]
    n = 0
    for k in range(len(prose) - 1):
        (i1, b1), (i2, b2) = prose[k], prose[k + 1]
        if i2 != i1 + 1:
            continue
        w1, w2 = content_words(b1), content_words(b2)
        if len(w1) < 8 or len(w2) < 8:
            continue
        if len(w1 & w2) / len(w1 | w2) >= ADJDUP_JACCARD:
            n += 1
    return n


def count_patterns(text: str, pats, flags=0) -> int:
    return sum(len(re.findall(p, text, flags)) for p in pats)


def is_paperish(src_body: str) -> bool:
    """학술 논문 여부 프록시: 수식 or 다수 인용."""
    math = src_body.count("$$") + len(re.findall(r"\$[^$\n]{1,40}\$", src_body))
    cites = len(re.findall(r"\[\d{1,3}\]", src_body))
    return math >= 3 or cites >= 8


def is_korean_source(text: str) -> bool:
    ko = len(re.findall(r"[가-힣]", text))
    return ko >= max(200, len(text) * 0.15)


def find_source(folder: str) -> Optional[str]:
    def excluded(p):
        b = os.path.basename(p)
        return any(x in b for x in
                   ("_ko_explained", "_explained", "_backup_", "_ko_audio", ".part"))

    cands = [p for p in glob.glob(os.path.join(folder, "*.md")) if not excluded(p)]
    ko = [p for p in cands if p.endswith("_ko.md")]
    if ko:
        return sorted(ko)[0]
    en = sorted(p for p in cands if not p.endswith("_ko.md"))
    return en[0] if en else None


def image_refs(text: str):
    return set(re.findall(r"!\[[^\]]*\]\(([^)\s]+)", text))


# --- 결과 모델 --------------------------------------------------------------
@dataclass
class Check:
    name: str
    status: str  # PASS | REVIEW | FAIL | INFO
    detail: str


@dataclass
class Result:
    path: str
    source: Optional[str]
    verdict: str = "PASS"
    reason: str = ""
    checks: List[Check] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def check(path: str, source: Optional[str] = None) -> Result:
    raw = read(path)
    body = strip_yaml(raw)
    folder = os.path.dirname(os.path.abspath(path))
    if source is None:
        source = find_source(folder)

    res = Result(path=path, source=source)
    fails: List[str] = []
    reviews: List[str] = []

    def add(name, status, detail):
        res.checks.append(Check(name, status, detail))

    # 1) 파일명
    if path.endswith("_ko_explained.md"):
        add("filename", "PASS", "_ko_explained.md")
    else:
        add("filename", "FAIL", f"'{os.path.basename(path)}' — _ko_explained.md 로 끝나야 함")
        fails.append("파일명 규칙 위반")

    # 2) YAML 헤더 정확히 1회
    nh = yaml_header_count(raw)
    if nh == 1:
        add("yaml-header", "PASS", "1회")
    elif nh == 0:
        add("yaml-header", "REVIEW", "0회 — 헤더 누락")
        reviews.append("YAML 헤더 없음")
    else:
        add("yaml-header", "FAIL", f"{nh}회 — 섹션 append 시 헤더 중복")
        fails.append(f"YAML 헤더 {nh}회")

    # 3) 문체 (핵심 게이트)
    hap, hae = register_paras(body)
    res.metrics.update(hap_p=hap, hae_p=hae)
    if hae >= HAE_FAIL and hap >= HAP_COEXIST:
        add("register", "FAIL", f"해라체 {hae} + 합니다체 {hap} — 번역/재진술 이중구조")
        fails.append(f"translate-then-restate(hae{hae}+hap{hap})")
    elif hae >= HAE_FAIL:
        add("register", "FAIL", f"해라체 {hae} 문단 (합니다체 {hap}) — 문체 전환 미수행")
        fails.append(f"전체 해라체 문체위반(hae{hae})")
    elif hae >= 1:
        add("register", "REVIEW", f"해라체 {hae} 문단 — 직접인용·제목 예외인지 확인")
        reviews.append(f"해라체 문단 {hae}(직접인용·제목 예외 확인)")
    else:
        add("register", "PASS", f"합니다체 {hap} 문단, 해라체 0")

    # 4) 인접 near-dup
    adj = adj_dup_count(body)
    res.metrics["adj_dup"] = adj
    if adj >= ADJDUP_FAIL:
        add("adjacent-dup", "FAIL", f"{adj}곳 — 같은 내용 재진술")
        fails.append(f"인접 near-dup {adj}곳")
    elif adj >= 1:
        add("adjacent-dup", "REVIEW", f"{adj}곳 — 육안 확인")
        reviews.append(f"인접 near-dup {adj}곳")
    else:
        add("adjacent-dup", "PASS", "0곳")

    # 5) 정형 비유마커
    cliche = count_patterns(body, CLICHE_MARKERS)
    res.metrics["cliche"] = cliche
    if cliche >= CLICHE_REVIEW:
        add("analogy-cliche", "REVIEW", f"{cliche}회 — 정형 도입구 반복")
        reviews.append(f"정형 비유마커 {cliche}회")
    else:
        add("analogy-cliche", "PASS", f"{cliche}회")

    # 5b) 비유 볼드 라벨 (스킬은 0건 요구)
    label = count_patterns(body, ANALOGY_LABEL, re.M)
    res.metrics["analogy_label"] = label
    if label:
        add("analogy-label", "REVIEW", f"{label}건 — '**비유:**' 라벨은 0건이어야 함")
        reviews.append(f"비유 라벨 {label}건")
    else:
        add("analogy-label", "PASS", "0건")

    # 6) 매체 과잉설명
    media = count_patterns(body, MEDIA_OVEREXPLAIN)
    res.metrics["media"] = media
    if media >= MEDIA_REVIEW:
        add("media-overexplain", "REVIEW", f"{media}회 — 매체 소개는 최대 1회")
        reviews.append(f"매체 과잉설명 {media}")
    else:
        add("media-overexplain", "PASS", f"{media}회")

    # 7) 웹 잡동사니
    clutter = count_patterns(body, WEB_CLUTTER, re.I)
    res.metrics["web_clutter"] = clutter
    if clutter:
        add("web-clutter", "REVIEW", f"{clutter}건 — 광고·구독 유도 잔존")
        reviews.append(f"웹 잡동사니 {clutter}건")
    else:
        add("web-clutter", "PASS", "0건")

    # 8) 용어집
    if re.search(r"^\|\s*용어\s*\|", body, re.M):
        add("glossary", "PASS", "용어집 표 있음")
    else:
        add("glossary", "REVIEW", "용어집 표 없음")
        reviews.append("용어집 없음")

    # --- 소스 대조 ---------------------------------------------------------
    if source and os.path.exists(source):
        src_raw = read(source)
        src_body = strip_yaml(src_raw)
        src_chars = len(src_body)
        ratio = round(len(body) / src_chars, 2) if src_chars else None
        res.metrics["ratio"] = ratio
        res.metrics["src_chars"] = src_chars
        res.metrics["out_chars"] = len(body)
        ko_src = is_korean_source(src_body)
        paperish = is_paperish(src_body)

        if ratio is None:
            add("ratio", "INFO", "소스 본문 없음")
        elif not ko_src and ratio < RATIO_FLOOR:
            add("ratio", "REVIEW", f"{ratio}x (<{RATIO_FLOOR}) — 외국어 소스 누락 의심")
            reviews.append(f"ratio {ratio}x(누락 의심)")
        elif not paperish and ratio >= RATIO_RESTATE:
            add("ratio", "REVIEW", f"{ratio}x (≥{RATIO_RESTATE}) — 비논문 재진술 의심")
            reviews.append(f"비논문 ratio {ratio}x(재진술 의심)")
        else:
            add("ratio", "PASS", f"{ratio}x ({'한국어' if ko_src else '외국어'} 소스)")

        # 이미지 참조 보존
        src_imgs = image_refs(src_body)
        out_imgs = image_refs(body)
        missing = sorted(src_imgs - out_imgs)
        res.metrics["img_src"] = len(src_imgs)
        res.metrics["img_out"] = len(out_imgs)
        if not src_imgs:
            add("image-refs", "PASS", "소스에 이미지 없음")
        elif missing:
            add("image-refs", "REVIEW",
                f"{len(missing)}/{len(src_imgs)} 누락 (예: {missing[0]})")
            reviews.append(f"이미지 참조 {len(missing)}건 누락")
        else:
            add("image-refs", "PASS", f"{len(src_imgs)}건 전부 보존")
    else:
        add("source", "INFO", "소스 MD 미발견 — 대조 검사 생략")

    if fails:
        res.verdict = "FAIL"
        res.reason = "; ".join(fails + reviews)
    elif reviews:
        res.verdict = "REVIEW"
        res.reason = "; ".join(reviews)
    else:
        res.verdict = "PASS"
    return res


def main(argv: List[str]):
    args = [a for a in argv if not a.startswith("--")]
    strict = "--strict" in argv
    as_json = "--json" in argv

    if not args:
        print("usage: verify_explainer.py <explained.md> [source.md] [--strict] [--json]",
              file=sys.stderr)
        return 2, None
    path = args[0]
    source = args[1] if len(args) > 1 else None
    if not os.path.isfile(path):
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2, None
    if source and not os.path.isfile(source):
        print(f"error: source not found: {source}", file=sys.stderr)
        return 2, None

    res = check(path, source)

    if as_json:
        print(json.dumps({
            "path": res.path, "source": res.source, "verdict": res.verdict,
            "reason": res.reason, "metrics": res.metrics,
            "checks": [{"name": c.name, "status": c.status, "detail": c.detail}
                       for c in res.checks],
        }, ensure_ascii=False))
    else:
        print(f"== verify_explainer [정적 검사] : {res.path} ==")
        if res.source:
            print(f"   source: {res.source}")
        for c in res.checks:
            print(f"  {c.status:<6} {c.name:<22} {c.detail}")
        print(f"== 정적 검사 결과(STATIC CHECKS): {res.verdict} ==")
        if res.reason:
            print(f"   사유: {res.reason}")
        print("   (섹션 coverage·비유 적절성·수식 정확성·차트 전사는 스킬 Quality Checks 에서 별도 확인)")

    if res.verdict == "FAIL":
        return 1, res
    if res.verdict == "REVIEW" and strict:
        return 1, res
    return 0, res


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:])[0])
