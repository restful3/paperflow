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
# 아래는 "의심"이 아니라 내용 소실로 보는 선. 실데이터 보정(2026-08-03, 119편):
# 한국어 소스 ratio 중앙값 1.93 · p05 0.76 — 0.5 미만은 4편(전부 실제 결함)뿐.
RATIO_FAIL = 0.4      # 외국어 소스가 이 미만이면 FAIL
KO_RATIO_REVIEW = 0.75
KO_RATIO_FAIL = 0.5   # 한국어 소스가 이 미만이면 FAIL
# 이미지 손실 실데이터 보정(109편): 중앙값·p90 모두 0.00 — 대량 손실은 이상치다.
IMG_LOSS_FAIL = 0.5   # 소스 이미지의 이 비율 이상을 버리면 FAIL …
IMG_LOSS_MIN_N = 3    # … 단 절대 개수도 이 이상일 때만 (1/1 누락을 100% 로 반려하지 않도록)
# 표 보존 실데이터 보정(19편, 소스 표 2개 이상): 중앙 1.20 · p25 1.07 — 0.5 미만은 1편(기존 결함).
TBL_MIN_N = 2         # 소스 표가 이 개수 이상일 때만 판정
TBL_KEEP_FAIL = 0.5   # 표 보존율이 이 미만이면 FAIL
# 수식은 분포가 넓다(p25 0.31) — 자동 반려 근거가 못 되어 REVIEW 까지만.
MATH_MIN_N = 20
MATH_KEEP_REVIEW = 0.5
# 위험도 — 검증 강도만 고른다(모델 라우팅 아님). 크기만 보면 소형 기술 문서를 놓쳐서
# 표 셀·수식 밀도를 함께 본다(피어 리뷰 2026-08-03).
HIGH_RISK_CHARS = 30_000
HIGH_RISK_TBL_CELLS = 20
HIGH_RISK_MATH = 20
KO_RATIO_FAIL_HIGH = 0.65   # high-risk 한국어 문서의 FAIL 하한 (저위험은 KO_RATIO_FAIL)
# 본문 수치 coverage — ratio 로는 증명되지 않는 누락을 직접 잡는다.
# 실데이터 보정(46편, 소스 수치 15개 이상): 수치를 몇 개 흘리는 것은 기존 Claude 산출물에서도
# 상시다(미등장 중앙값 2~4). 완벽 recall 은 기존 주체도 못 맞춘 기준이라 자동 반려선으로 쓸 수 없다.
# → FAIL 은 "명백한 이상치"로만 잡고(레거시 17%, 전부 recall 6.7~60.6% 의 실제 결함),
#   중간대는 BLOCKING_REVIEW 로 격리한다(레거시 24%).
NUM_MIN_N = 15            # 소스 본문 수치가 이 개수 이상일 때만 판정
NUM_MISSING_FAIL = 8      # 미등장 개수가 이 이상이고 …
NUM_RECALL_FAIL = 0.90    # … recall 이 이 미만이면 FAIL
NUM_MISSING_BLOCK = 3     # 미등장 개수가 이 이상이고 …
NUM_RECALL_BLOCK = 0.95   # … recall 이 이 미만이면 BLOCKING_REVIEW
# 표 행 시그니처 coverage
TBL_ROW_MIN_N = 4
TBL_ROW_KEEP_FAIL = 0.5
TBL_ROW_KEEP_BLOCK = 0.9
# 소스를 그대로 옮긴 복사본 탐지. 참고문헌·수식·직접인용은 원문 유지가 정상이라
# 일부 겹침은 허용하고, 산문 문단 대부분이 그대로면 해설판이 아니다.
COPY_FAIL = 0.70      # 산문 문단 중 소스와 동일한 비율이 이 이상이면 FAIL
COPY_REVIEW = 0.45    # 이 이상이면 REVIEW

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


REF_HEAD = re.compile(r"^#{1,4}\s*(참고문헌|References|Bibliography|감사의 글|Acknowledge)", re.M | re.I)


def _before_references(t: str) -> str:
    """참고문헌 이후를 잘라낸다 — 스킬이 원문 유지를 요구하는 구간이라 중복·복사로 세면 안 된다."""
    m = REF_HEAD.search(t)
    return t[:m.start()] if m else t


def adj_dup_count(body: str) -> int:
    # 참고문헌 항목들은 저자 명단이 겹쳐 서로 비슷해 보인다 — 본문 중복과 구분해 제외한다.
    paras = paragraphs(_before_references(body))
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


# --- 본문 수치 추출 ---------------------------------------------------------
# coverage 는 ratio 로 증명되지 않는다(피어 리뷰 2026-08-03). 본문 수치를 직접 대조하되,
# 아래 잡음은 제외한다 — 잡음을 세면 recall 이 희석돼 진짜 누락이 묻힌다.
_NOISE_PATTERNS = [
    r"^---\n.*?\n---\n",                     # YAML front matter
    r"!\[[^\]]*\]\([^)]*\)",                 # 이미지 참조(파일명이 hex+숫자)
    r"https?://\S+",                         # URL
    r"\bdoi:\s*\S+",                         # DOI
    r"\[\^?\d{1,3}\]",                       # 인용번호 [12]
    r"(?:그림|표|Figure|Table|Fig\.?)\s*\d+", # 그림/표 번호
    r"\bpp?\.\s*\d+(?:\s*[-~–]\s*\d+)?",     # 페이지 범위
]
# NOTE: `\b\d+\b` 를 쓰면 안 된다 — 한국어는 단위가 바로 붙어("330개", "52편") 뒤쪽
# word boundary 가 생기지 않아 수치를 통째로 놓친다(실측 버그).
_NUM_TOKEN = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?![\d])"
                        r"|(?<![\d.])\d+\.\d+(?![\d])"
                        r"|(?<![\d.])\d+%?(?![\d.])")


def body_numbers(text: str) -> set:
    """본문에서 의미 있는 수치 토큰 집합. 참고문헌 이후와 아래 잡음은 제외.

    수식·코드 블록 안의 숫자는 제외한다 — 그쪽은 math-coverage 가 전담한다
    (여기서도 세면 같은 유실이 두 번 감점된다).
    """
    t = _before_references(text)
    for pat in _NOISE_PATTERNS:
        t = re.sub(pat, " ", t, flags=re.S)
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"\$\$.*?\$\$", " ", t, flags=re.S)
    t = re.sub(r"(?<!\$)\$[^$\n]{1,120}\$(?!\$)", " ", t)
    out = set()
    for m in _NUM_TOKEN.finditer(t):
        tok = m.group(0)
        # 연도·한 자리 순번은 신호 대비 잡음이 커서 제외
        if re.fullmatch(r"\d{4}", tok) and 1900 <= int(tok) <= 2100:
            continue
        if re.fullmatch(r"\d", tok):
            continue
        out.add(tok)
    return out


# 게이트 통과용 수치 덤프를 막기 위해, 출력에서 이 절들은 coverage 계산에서 뺀다.
DUMP_SECTION = re.compile(
    r"^#{1,4}\s*(핵심 용어 해설|용어 해설|용어집|Glossary|수치 인덱스|수치 목록|부록 수치)",
    re.M | re.I)


def strip_dump_sections(text: str) -> str:
    """용어집·수치 인덱스 절을 제거 — 거기 몰아넣은 수치는 coverage 로 치지 않는다."""
    out, pos = [], 0
    for m in DUMP_SECTION.finditer(text):
        out.append(text[pos:m.start()])
        nxt = re.search(r"^#{1,4}\s+", text[m.end():], re.M)
        pos = m.end() + (nxt.start() if nxt else len(text) - m.end())
    out.append(text[pos:])
    return "".join(out)


def table_rows(text: str):
    """표 행 시그니처 목록 — (라벨, 그 행의 수치 집합). 수치가 없는 행은 버린다.

    같은 숫자가 다른 곳에 우연히 한 번 나온 것으로 표 누락을 숨기지 못하게,
    라벨과 수치를 함께 본다.
    """
    sigs = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        if not cells:
            continue
        nums = {t for c in cells[1:] for t in _NUM_TOKEN.findall(c)}
        if cells[0] and nums:
            sigs.append((re.sub(r"\s+", "", cells[0]), nums))
    for line in re.findall(r"^\s*\|(.+)\|\s*$", text, re.M):
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 2 or re.fullmatch(r"[\s:\-]+", cells[0] or " "):
            continue
        nums = {t for c in cells[1:] for t in _NUM_TOKEN.findall(c)}
        if cells[0] and nums:
            sigs.append((re.sub(r"\s+", "", cells[0]), nums))
    return sigs


def table_count(text: str) -> int:
    """HTML 표 + 마크다운 표 블록 수."""
    return (len(re.findall(r"<table", text))
            + len(re.findall(r"^\s*\|[^\n]*\n\s*\|[\s:\-|]+\|", text, re.M)))


def math_count(text: str) -> int:
    """블록 수식 + 인라인 수식 개수."""
    return text.count("$$") // 2 + len(re.findall(r"(?<!\$)\$[^$\n]{1,80}\$(?!\$)", text))


def _copy_key(p: str) -> str:
    """복사 비교용 정규화 — 공백/강조 마크업 차이는 무시한다.

    볼드만 몇 개 씌우고 그대로 옮긴 것도 복사로 잡기 위함.
    """
    p = re.sub(r"\*\*|__|\*|_|`", "", p)
    return re.sub(r"\s+", " ", p).strip()


def copy_ratio(out_body: str, src_body: str):
    """출력 산문 문단 중 소스에 그대로 있는 비율. (비율, 동일수, 전체수)

    제외: 참고문헌·감사의 글 이후 전체(원문 유지가 규칙), 이미지 참조를 포함한 블록
    (`![](...)` 이 붙은 캡션 줄은 경로가 같아 항상 일치한다).
    """
    def prose_paras(t):
        t = _before_references(t)
        t = re.sub(r"```.*?```", "", t, flags=re.S)
        out = []
        for b in re.split(r"\n\s*\n", t):
            b = b.strip()
            if len(b) < 80 or b.startswith(("#", "|", ">", "!", "-", "*", "$")):
                continue
            if "![" in b:          # 캡션+이미지 블록
                continue
            out.append(b)
        return out

    op = prose_paras(out_body)
    if not op:
        return None, 0, 0
    sp = {_copy_key(p) for p in prose_paras(src_body)}
    same = sum(1 for p in op if _copy_key(p) in sp)
    return same / len(op), same, len(op)


# --- 결과 모델 --------------------------------------------------------------
@dataclass
class Check:
    name: str
    status: str  # PASS | REVIEW | FAIL | INFO
    detail: str
    # REVIEW 의 무게. blocking = coverage 계열 불확실성이라 자동 publish 금지.
    # advisory = 편집 품질 신호라 로그만 남기고 통과.
    severity: str = "advisory"


@dataclass
class Result:
    path: str
    source: Optional[str]
    verdict: str = "PASS"
    reason: str = ""
    checks: List[Check] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    blocking: bool = False   # FAIL 이거나 blocking REVIEW 가 하나라도 있으면 True


def check(path: str, source: Optional[str] = None) -> Result:
    raw = read(path)
    body = strip_yaml(raw)
    folder = os.path.dirname(os.path.abspath(path))
    if source is None:
        source = find_source(folder)

    res = Result(path=path, source=source)
    fails: List[str] = []
    reviews: List[str] = []
    blocking_reviews: List[str] = []

    def add(name, status, detail, severity="advisory"):
        res.checks.append(Check(name, status, detail, severity))

    def review(name, detail, reason, severity="advisory"):
        add(name, "REVIEW", detail, severity)
        reviews.append(reason)
        if severity == "blocking":
            blocking_reviews.append(reason)

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
        review("yaml-header", "0회 — 헤더 누락", "YAML 헤더 없음", "blocking")
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
        review("register", f"해라체 {hae} 문단 — 직접인용·제목 예외인지 확인",
               f"해라체 문단 {hae}(직접인용·제목 예외 확인)", "blocking")
    else:
        add("register", "PASS", f"합니다체 {hap} 문단, 해라체 0")

    # 4) 인접 near-dup
    adj = adj_dup_count(body)
    res.metrics["adj_dup"] = adj
    if adj >= ADJDUP_FAIL:
        add("adjacent-dup", "FAIL", f"{adj}곳 — 같은 내용 재진술")
        fails.append(f"인접 near-dup {adj}곳")
    elif adj >= 1:
        review("adjacent-dup", f"{adj}곳 — 육안 확인", f"인접 near-dup {adj}곳", "blocking")
    else:
        add("adjacent-dup", "PASS", "0곳")

    # 5) 정형 비유마커
    cliche = count_patterns(body, CLICHE_MARKERS)
    res.metrics["cliche"] = cliche
    if cliche >= CLICHE_REVIEW:
        review("analogy-cliche", f"{cliche}회 — 정형 도입구 반복", f"정형 비유마커 {cliche}회")
    else:
        add("analogy-cliche", "PASS", f"{cliche}회")

    # 5b) 비유 볼드 라벨 (스킬은 0건 요구)
    label = count_patterns(body, ANALOGY_LABEL, re.M)
    res.metrics["analogy_label"] = label
    if label:
        review("analogy-label", f"{label}건 — '**비유:**' 라벨은 0건이어야 함", f"비유 라벨 {label}건")
    else:
        add("analogy-label", "PASS", "0건")

    # 6) 매체 과잉설명
    media = count_patterns(body, MEDIA_OVEREXPLAIN)
    res.metrics["media"] = media
    if media >= MEDIA_REVIEW:
        review("media-overexplain", f"{media}회 — 매체 소개는 최대 1회", f"매체 과잉설명 {media}")
    else:
        add("media-overexplain", "PASS", f"{media}회")

    # 7) 웹 잡동사니
    clutter = count_patterns(body, WEB_CLUTTER, re.I)
    res.metrics["web_clutter"] = clutter
    if clutter:
        review("web-clutter", f"{clutter}건 — 광고·구독 유도 잔존", f"웹 잡동사니 {clutter}건")
    else:
        add("web-clutter", "PASS", "0건")

    # 8) 용어집
    if re.search(r"^\|\s*용어\s*\|", body, re.M):
        add("glossary", "PASS", "용어집 표 있음")
    else:
        review("glossary", "용어집 표 없음", "용어집 없음")

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

        # 위험도 — 검증 강도만 고른다(모델 라우팅이 아니다). 오분류해도 더 엄격히 볼 뿐이다.
        src_tbl_cells = sum(len(n) for _, n in table_rows(src_body))
        high_risk = (src_chars >= HIGH_RISK_CHARS
                     or src_tbl_cells >= HIGH_RISK_TBL_CELLS
                     or math_count(src_body) >= HIGH_RISK_MATH)
        res.metrics["high_risk"] = high_risk

        ko_fail = KO_RATIO_FAIL_HIGH if high_risk else KO_RATIO_FAIL
        ko_rev_sev = "blocking" if high_risk else "advisory"
        if ratio is None:
            add("ratio", "INFO", "소스 본문 없음")
        elif not ko_src and ratio < RATIO_FAIL:
            add("ratio", "FAIL", f"{ratio}x (<{RATIO_FAIL}) — 외국어 소스 내용 소실")
            fails.append(f"ratio {ratio}x(내용 소실)")
        elif ko_src and ratio < ko_fail:
            add("ratio", "FAIL",
                f"{ratio}x (<{ko_fail}, {'high' if high_risk else 'low'}-risk) — 한국어 소스 내용 소실")
            fails.append(f"ratio {ratio}x(내용 소실)")
        elif not ko_src and ratio < RATIO_FLOOR:
            review("ratio", f"{ratio}x (<{RATIO_FLOOR}) — 외국어 소스 누락 의심",
                   f"ratio {ratio}x(누락 의심)", ko_rev_sev)
        elif ko_src and ratio < KO_RATIO_REVIEW:
            review("ratio", f"{ratio}x (<{KO_RATIO_REVIEW}) — 한국어 소스 누락 의심",
                   f"ratio {ratio}x(누락 의심)", ko_rev_sev)
        elif not paperish and ratio >= RATIO_RESTATE:
            review("ratio", f"{ratio}x (≥{RATIO_RESTATE}) — 비논문 재진술 의심",
                   f"비논문 ratio {ratio}x(재진술 의심)")
        else:
            add("ratio", "PASS", f"{ratio}x ({'한국어' if ko_src else '외국어'} 소스)")

        # 본문 수치 coverage — ratio 로 증명되지 않는 누락을 직접 잡는다.
        # 출력에서 용어집·수치 인덱스는 뺀다(게이트 통과용 덤프 방지).
        src_nums = body_numbers(src_body)
        out_nums = body_numbers(strip_dump_sections(body))
        missing = src_nums - out_nums
        res.metrics.update(num_src=len(src_nums), num_missing=len(missing))
        if len(src_nums) < NUM_MIN_N:
            add("number-coverage", "INFO", f"소스 본문 수치 {len(src_nums)}개 — 판정 안 함")
        else:
            recall = 1 - len(missing) / len(src_nums)
            res.metrics["num_recall"] = round(recall, 4)
            detail = f"recall {recall:.1%} (미등장 {len(missing)}/{len(src_nums)})"
            if missing:
                detail += f" 예: {sorted(missing)[:6]}"
            if len(missing) >= NUM_MISSING_FAIL and recall < NUM_RECALL_FAIL:
                add("number-coverage", "FAIL", detail + " — 본문 수치 소실")
                fails.append(f"수치 {len(missing)}개 미등장(recall {recall:.1%})")
            elif len(missing) >= NUM_MISSING_BLOCK and recall < NUM_RECALL_BLOCK:
                review("number-coverage", detail, f"수치 {len(missing)}개 미등장", "blocking")
            elif missing:
                review("number-coverage", detail, f"수치 {len(missing)}개 미등장")
            else:
                add("number-coverage", "PASS", detail)

        # 표 행 시그니처 coverage — 라벨+수치를 함께 봐서 우연한 숫자 일치로 못 숨기게 한다
        srows = table_rows(src_body)
        res.metrics["tbl_rows_src"] = len(srows)
        if len(srows) < TBL_ROW_MIN_N:
            add("table-row-coverage", "INFO", f"소스 표 행 {len(srows)}개 — 판정 안 함")
        else:
            # 라벨·수치 모두 덤프 절을 뺀 본문에서 찾는다 — 용어집에 표를 통째로
            # 복사해 두고 본문에서는 버리는 우회를 막는다.
            out_kept = strip_dump_sections(body)
            out_flat = re.sub(r"\s+", "", out_kept)
            lost = [lab for lab, nums in srows
                    if not (lab in out_flat and all(n in out_kept for n in nums))]
            res.metrics["tbl_rows_lost"] = len(lost)
            keep = 1 - len(lost) / len(srows)
            detail = f"{len(srows)-len(lost)}/{len(srows)} 행 ({keep:.0%})"
            if keep < TBL_ROW_KEEP_FAIL:
                add("table-row-coverage", "FAIL",
                    detail + f" — 표 행 소실 예: {lost[:4]}")
                fails.append(f"표 행 {len(lost)}개 소실({keep:.0%} 보존)")
            elif keep < TBL_ROW_KEEP_BLOCK:
                review("table-row-coverage", detail + f" 예: {lost[:4]}",
                       f"표 행 {len(lost)}개 소실", "blocking")
            elif lost:
                review("table-row-coverage", detail, f"표 행 {len(lost)}개 소실")
            else:
                add("table-row-coverage", "PASS", detail)

        # 소스 그대로 복사 (해설이 아니라 사본인 경우)
        cr, same, total = copy_ratio(body, src_body)
        if cr is None:
            add("source-copy", "INFO", "비교할 산문 문단 없음")
        else:
            res.metrics["copy_ratio"] = round(cr, 3)
            detail = f"산문 {same}/{total} 문단이 소스와 동일 ({cr:.0%})"
            if cr >= COPY_FAIL:
                add("source-copy", "FAIL", detail + " — 해설이 아니라 사본")
                fails.append(f"소스 복사 {cr:.0%}")
            elif cr >= COPY_REVIEW:
                review("source-copy", detail + " — 재작성 부족 의심", f"소스 복사 {cr:.0%}", "blocking")
            else:
                add("source-copy", "PASS", detail)

        # 결과 표 보존 — 표를 버리면 그 안의 수치가 통째로 사라진다
        st, ot = table_count(src_body), table_count(body)
        res.metrics.update(tbl_src=st, tbl_out=ot)
        if st < TBL_MIN_N:
            add("table-coverage", "INFO", f"소스 표 {st}개 — 판정 안 함(표본 부족)")
        else:
            keep = ot / st
            detail = f"{ot}/{st} 표 ({keep:.0%})"
            if keep < TBL_KEEP_FAIL:
                add("table-coverage", "FAIL", detail + " — 표 안의 수치가 통째로 소실")
                fails.append(f"표 {st-ot}개 소실({keep:.0%} 보존)")
            else:
                add("table-coverage", "PASS", detail)

        # 수식 보존 — 실데이터 분포가 넓어 REVIEW 까지만
        sm, om = math_count(src_body), math_count(body)
        res.metrics.update(math_src=sm, math_out=om)
        if sm < MATH_MIN_N:
            add("math-coverage", "INFO", f"소스 수식 {sm}개 — 판정 안 함")
        else:
            keep = om / sm
            if keep < MATH_KEEP_REVIEW:
                review("math-coverage", f"{om}/{sm} 수식 ({keep:.0%}) — 유실 확인",
                       f"수식 {keep:.0%} 보존", "blocking")
            else:
                add("math-coverage", "PASS", f"{om}/{sm} 수식 ({keep:.0%})")

        # 이미지 참조 보존
        src_imgs = image_refs(src_body)
        out_imgs = image_refs(body)
        missing = sorted(src_imgs - out_imgs)
        res.metrics["img_src"] = len(src_imgs)
        res.metrics["img_out"] = len(out_imgs)
        if not src_imgs:
            add("image-refs", "PASS", "소스에 이미지 없음")
        elif missing:
            loss = len(missing) / len(src_imgs)
            detail = f"{len(missing)}/{len(src_imgs)} 누락 ({loss:.0%}, 예: {missing[0]})"
            if loss >= IMG_LOSS_FAIL and len(missing) >= IMG_LOSS_MIN_N:
                add("image-refs", "FAIL", detail + " — 이미지 보존은 하드룰")
                fails.append(f"이미지 참조 {len(missing)}건 누락({loss:.0%})")
            else:
                review("image-refs", detail, f"이미지 참조 {len(missing)}건 누락", "blocking")
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
    res.blocking = bool(fails or blocking_reviews)
    if blocking_reviews and not fails:
        res.metrics["blocking_reviews"] = blocking_reviews
    return res


def main(argv: List[str]):
    args = [a for a in argv if not a.startswith("--")]
    strict = "--strict" in argv          # 모든 REVIEW 반려 (수동 감사용)
    production = "--production" in argv  # FAIL + blocking REVIEW 만 반려 (배치 lane 용)
    as_json = "--json" in argv

    if not args:
        print("usage: verify_explainer.py <explained.md> [source.md] "
              "[--production|--strict] [--json]", file=sys.stderr)
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

    # 판정 라벨: REVIEW 는 무게를 드러내야 운영 의도가 분명해진다.
    label = res.verdict
    if res.verdict == "REVIEW":
        label = "BLOCKING_REVIEW" if res.blocking else "ADVISORY_REVIEW"

    if as_json:
        print(json.dumps({
            "path": res.path, "source": res.source, "verdict": res.verdict,
            "label": label, "blocking": res.blocking,
            "reason": res.reason, "metrics": res.metrics,
            "checks": [{"name": c.name, "status": c.status,
                        "severity": c.severity, "detail": c.detail}
                       for c in res.checks],
        }, ensure_ascii=False))
    else:
        print(f"== verify_explainer [정적 검사] : {res.path} ==")
        if res.source:
            print(f"   source: {res.source}")
        for c in res.checks:
            mark = "!" if (c.status == "REVIEW" and c.severity == "blocking") else " "
            print(f" {mark}{c.status:<6} {c.name:<22} {c.detail}")
        print(f"== 정적 검사 결과(STATIC CHECKS): {label} ==")
        if res.reason:
            print(f"   사유: {res.reason}")
        print("   (비유 적절성·수식 해설의 정확성·차트 전사 내용은 스킬 Quality Checks 에서 별도 확인)")

    if res.verdict == "FAIL":
        return 1, res
    if res.verdict == "REVIEW" and (strict or (production and res.blocking)):
        return 1, res
    return 0, res


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:])[0])
