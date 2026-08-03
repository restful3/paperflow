"""verify_explainer 정적 게이트 테스트.

낭독판 `scripts/verify_audio.sh` 와 짝을 이루는 해설판 검증기.
게이트 의미론은 tmp/explainer_review/gate.py (2026-07-03 전수 감사에서 검증된 것) 를 따른다:
  FAIL   = 자동 반려 (translate-then-restate, 인접 near-dup 다수, 전체 해라체)
  REVIEW = 사람/에이전트 확인 필요하지만 자동 반려는 아님 (council 조언)
  PASS   = 정적 검사 통과
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import verify_explainer as ve  # noqa: E402


YAML = "---\ntitle: 테스트 논문\nlang: ko\n---\n\n"

GLOSSARY = "\n\n## 핵심 용어 해설\n\n| 용어 | 쉬운 설명 |\n|---|---|\n| 임베딩 | 뜻을 숫자로 바꾼 것 |\n"

# 인접 near-dup 검사는 문단 간 content-word 자카드 유사도를 본다. 픽스처가
# 골격 문장을 공유하면 주제어만 바꿔도 유사도가 임계를 넘어 의도치 않게 걸린다.
# → 문단마다 어휘·구문을 통째로 다르게 쓴 리터럴을 둔다.
HAP_PARAS = [
    "검색 증강 생성은 질문이 들어오면 먼저 외부 문서 창고를 뒤집니다. 거기서 뽑아 온 근거만 모델에게 건네주기 때문에, "
    "학습 당시에 없던 최신 사실도 답변에 반영할 수 있습니다. 환각이 줄어드는 이유가 바로 여기에 있습니다.",

    "계층적 메모리 구조는 자주 꺼내 보는 정보를 가까운 곳에, 오래된 기록을 먼 창고에 나누어 둡니다. 접근 빈도가 떨어진 항목은 "
    "요약본만 남기고 원본을 접어 두므로, 전체 용량이 커져도 탐색 시간이 급격히 늘지 않습니다.",

    "강화학습에서 보상 설계를 잘못하면 에이전트가 목표 대신 지표를 공략하기 시작합니다. 점수만 올리는 편법 경로가 열려 있으면 "
    "학습은 그쪽으로 수렴해 버립니다. 그래서 보상 항을 여러 개로 쪼개 균형을 잡는 방법이 자주 쓰입니다.",

    "이미지와 문장을 하나의 좌표계에 놓으려면 두 인코더가 같은 의미를 같은 위치로 보내야 합니다. 대조 학습은 짝이 맞는 쌍을 "
    "끌어당기고 어긋난 쌍을 밀어내며 이 좌표계를 다듬습니다. 남는 간극은 여전히 활발한 연구 주제입니다.",

    "추론 단계에서 계산을 더 쓰는 전략은 모델을 키우지 않고도 성능을 끌어올립니다. 답을 여러 번 뽑아 서로 대조하거나, "
    "스스로 검산하게 시키는 식입니다. 다만 응답이 느려지므로 어디까지 쓸지 선을 그어야 합니다.",

    "학습 데이터에 평가 문제가 섞여 들어가면 점수는 올라가지만 실력은 그대로입니다. 그래서 수집 단계에서 중복을 걷어내고 "
    "평가셋과 겹치는 조각을 찾아 걸러 냅니다. 이 과정을 건너뛴 보고서는 신뢰하기 어렵습니다.",

    "가중치를 낮은 비트로 눌러 담으면 같은 카드에 훨씬 큰 모델을 올릴 수 있습니다. 다만 눌린 만큼 정밀도가 깎이므로, "
    "민감한 층은 원래 정밀도로 남겨 두는 절충안이 흔히 쓰입니다. 손실과 절감을 저울질하는 셈입니다.",
]

HAE_PARAS = [
    "검색 증강 생성은 질문이 들어오면 먼저 외부 문서 창고를 뒤진다. 거기서 뽑아 온 근거만 모델에게 건네주기 때문에, "
    "학습 당시에 없던 최신 사실도 답변에 반영된다. 환각이 줄어드는 이유가 바로 여기에 있다.",

    "계층적 메모리 구조는 자주 꺼내 보는 정보를 가까운 곳에, 오래된 기록을 먼 창고에 나누어 둔다. 접근 빈도가 떨어진 항목은 "
    "요약본만 남기고 원본을 접어 두므로, 전체 용량이 커져도 탐색 시간이 급격히 늘지 않는다.",

    "강화학습에서 보상 설계를 잘못하면 에이전트가 목표 대신 지표를 공략하기 시작한다. 점수만 올리는 편법 경로가 열려 있으면 "
    "학습은 그쪽으로 수렴해 버린다. 그래서 보상 항을 여러 개로 쪼개 균형을 잡는 방법이 자주 쓰인다.",

    "이미지와 문장을 하나의 좌표계에 놓으려면 두 인코더가 같은 의미를 같은 위치로 보내야 한다. 대조 학습은 짝이 맞는 쌍을 "
    "끌어당기고 어긋난 쌍을 밀어내며 이 좌표계를 다듬는다. 남는 간극은 여전히 활발한 연구 주제이다.",

    "추론 단계에서 계산을 더 쓰는 전략은 모델을 키우지 않고도 성능을 끌어올린다. 답을 여러 번 뽑아 서로 대조하거나, "
    "스스로 검산하게 시키는 식이다. 다만 응답이 느려지므로 어디까지 쓸지 선을 그어야 한다.",

    "학습 데이터에 평가 문제가 섞여 들어가면 점수는 올라가지만 실력은 그대로다. 그래서 수집 단계에서 중복을 걷어내고 "
    "평가셋과 겹치는 조각을 찾아 걸러 낸다. 이 과정을 건너뛴 보고서는 신뢰하기 어렵다.",

    "가중치를 낮은 비트로 눌러 담으면 같은 카드에 훨씬 큰 모델을 올릴 수 있다. 다만 눌린 만큼 정밀도가 깎이므로, "
    "민감한 층은 원래 정밀도로 남겨 두는 절충안이 흔히 쓰인다. 손실과 절감을 저울질하는 셈이다.",
]


def w(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def hap_para(seed):
    """합니다체 산문 문단 (is_prose 통과용 120자 이상, 문단마다 고유 어휘)."""
    return HAP_PARAS[seed % len(HAP_PARAS)]


def hae_para(seed):
    """해라체 산문 문단 — 미변환 번역 반쪽의 시그니처."""
    return HAE_PARAS[seed % len(HAE_PARAS)]


def doc(paras, glossary=True):
    """클린 문서 조립 — 용어집 포함이 기본(스킬이 요구하는 산출물 형태)."""
    return YAML + "\n\n".join(paras) + (GLOSSARY if glossary else "")


# --- 파일/구조 게이트 -------------------------------------------------------


def test_missing_file_is_usage_error(tmp_path):
    rc, _ = ve.main([str(tmp_path / "nope_ko_explained.md")])
    assert rc == 2


def test_filename_must_end_with_ko_explained(tmp_path):
    f = w(tmp_path, "paper_ko.md", YAML + hap_para(0))
    res = ve.check(f)
    assert any(c.name == "filename" and c.status == "FAIL" for c in res.checks)


def test_duplicate_yaml_header_fails(tmp_path):
    body = YAML + hap_para(0) + "\n\n" + YAML + hap_para(1)
    f = w(tmp_path, "p_ko_explained.md", body)
    res = ve.check(f)
    assert any(c.name == "yaml-header" and c.status == "FAIL" for c in res.checks)


def test_single_yaml_header_passes(tmp_path):
    f = w(tmp_path, "p_ko_explained.md", YAML + hap_para(0))
    res = ve.check(f)
    assert any(c.name == "yaml-header" and c.status == "PASS" for c in res.checks)


def test_body_config_snippet_is_not_counted_as_header(tmp_path):
    """회귀: 본문 수평선 사이의 설정 스니펫을 중복 헤더로 오인하지 않는다.

    실측 오탐 — outputs/CONFIGURATION 해설판의 `paths: "src/api/**/*.ts"` 블록.
    """
    body = (YAML + hap_para(0)
            + '\n\n---\npaths: "src/api/**/*.ts"\n---\n\n'
            + hap_para(1))
    f = w(tmp_path, "p_ko_explained.md", body)
    res = ve.check(f)
    assert any(c.name == "yaml-header" and c.status == "PASS" for c in res.checks)


# --- 문체 게이트 (핵심 결함: translate-then-restate) ------------------------


def test_translate_then_restate_is_fail(tmp_path):
    """해라체 문단 4+ 와 합니다체 문단 3+ 공존 = 번역/재진술 이중구조."""
    paras = [hae_para(i) for i in range(4)] + [hap_para(i) for i in range(3)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f)
    assert res.verdict == "FAIL"
    assert "translate-then-restate" in res.reason


def test_all_haeche_is_fail(tmp_path):
    """합니다체가 거의 없이 해라체만 = 문체 전환 자체를 안 함."""
    paras = [hae_para(i) for i in range(5)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f)
    assert res.verdict == "FAIL"
    assert "해라체" in res.reason


def test_few_haeche_paragraphs_is_review_not_fail(tmp_path):
    """해라체 1~3 문단은 직접인용/제목 예외일 수 있으므로 REVIEW."""
    paras = [hap_para(i) for i in range(5)] + [hae_para(6)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f)
    assert res.verdict == "REVIEW"


def test_clean_haps_only_passes(tmp_path):
    paras = [hap_para(i) for i in range(5)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f)
    assert res.verdict == "PASS", res.reason


# --- 중복 게이트 ------------------------------------------------------------


def test_adjacent_near_duplicate_paragraphs_fail(tmp_path):
    """인접 문단이 같은 내용을 다른 말로 반복 = Rule 0 위반."""
    # 두 문단은 같은 주장을 어휘만 바꿔 되풀이한다 (is_prose 통과용 120자 이상).
    a = ("검색 증강 생성 기법은 외부 문서를 참조해 답변 정확도를 높입니다. "
         "이 방식은 모델이 학습하지 않은 최신 정보도 활용하게 해 줍니다. "
         "덕분에 사실과 어긋난 문장이 나올 가능성이 줄어듭니다. "
         "연구진이 진행한 실험에서 답변 정확도가 크게 향상되었습니다.")
    b = ("검색 증강 생성 기법은 외부 문서를 참조하여 답변 정확도를 향상시킵니다. "
         "이 방식은 모델이 학습하지 않은 최신 정보까지 활용하도록 해 줍니다. "
         "덕분에 사실과 어긋난 문장이 등장할 가능성이 감소합니다. "
         "연구진이 수행한 실험에서 답변 정확도가 크게 향상되었습니다.")
    paras = []
    for i in range(4):
        paras.extend([a, b])
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f)
    assert res.verdict == "FAIL"
    assert "near-dup" in res.reason


# --- 정형 마커 / 매체 과잉설명 ---------------------------------------------


def test_repeated_analogy_markers_is_review(tmp_path):
    paras = [hap_para(i) for i in range(5)]
    paras.append("비유로 설명하면 이렇습니다. " + hap_para(0))
    paras.append("비유로 설명하면 이렇습니다. " + hap_para(1))
    paras.append("쉽게 비유하자면 이렇습니다. " + hap_para(2))
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f)
    assert res.verdict == "REVIEW"
    assert "비유마커" in res.reason


def test_analogy_bold_label_is_review(tmp_path):
    paras = [hap_para(i) for i in range(5)]
    paras.append("**비유:** 계층적 메모리는 책상과 서랍장에 비유할 수 있습니다.")
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f)
    assert any(c.name == "analogy-label" and c.status != "PASS" for c in res.checks)


# --- 웹 잡동사니 ------------------------------------------------------------


def test_web_clutter_is_review(tmp_path):
    paras = [hap_para(i) for i in range(5)]
    paras.append("Subscribe to our newsletter for more updates.")
    paras.append("Sponsored by Acme Corp — try our product today.")
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f)
    assert any(c.name == "web-clutter" and c.status != "PASS" for c in res.checks)


# --- 소스 대조 게이트 -------------------------------------------------------


def test_ratio_below_floor_is_review(tmp_path):
    """외국어 소스 0.4~0.6x = 누락 의심(REVIEW) — 배치를 막지는 않는다."""
    paras = [hap_para(i) for i in range(5)]
    body = doc(paras)
    src = w(tmp_path, "p.md", "English source text. " * (int(len(body) / 0.5) // 21))
    f = w(tmp_path, "p_ko_explained.md", body)
    res = ve.check(f, src)
    assert res.metrics["ratio"] < ve.RATIO_FLOOR
    assert res.metrics["ratio"] >= ve.RATIO_FAIL
    assert res.verdict == "REVIEW"
    assert "ratio" in res.reason


def test_ratio_far_below_floor_is_fail(tmp_path):
    """외국어 소스 0.4x 미만 = 의심이 아니라 내용 소실."""
    src = w(tmp_path, "p.md", "English source. " * 900)
    paras = [hap_para(i) for i in range(3)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f, src)
    assert res.verdict == "FAIL"
    assert "ratio" in res.reason


def test_single_image_dropped_is_review_not_fail(tmp_path):
    """1/1 누락을 100% 로 반려하지 않는다 — 절대 개수 하한이 있다."""
    src = w(tmp_path, "p.md", "본문입니다.\n\n![](images/fig1.jpg)\n\n더 있습니다. " * 20)
    paras = [hap_para(i) for i in range(5)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f, src)
    assert any(c.name == "image-refs" and c.status == "REVIEW" for c in res.checks)


def test_missing_image_reference_is_review(tmp_path):
    """소수 누락은 REVIEW — 배치를 막지 않는다."""
    imgs = "\n\n".join(f"![](images/fig{i}.jpg)" for i in range(5))
    src = w(tmp_path, "p.md", "본문입니다.\n\n" + imgs + "\n\n더 있습니다.")
    kept = "\n\n".join(f"![](images/fig{i}.jpg)" for i in range(4))
    paras = [hap_para(i) for i in range(5)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras) + "\n\n" + kept)
    res = ve.check(f, src)
    assert any(c.name == "image-refs" and c.status == "REVIEW" for c in res.checks)
    assert res.verdict != "FAIL"


def test_most_images_dropped_is_fail(tmp_path):
    """대량 누락은 FAIL — 스킬은 이미지 참조 보존을 하드룰로 요구한다.

    실측(2026-08-03 Phase 2): Codex viz 산출물이 23개 중 21개(91%)를 버렸다.
    실데이터 보정: 기존 해설판 109편의 이미지 손실률 중앙값·p90 모두 0.00.
    """
    imgs = "\n\n".join(f"![](images/fig{i}.jpg)" for i in range(10))
    src = w(tmp_path, "p.md", "본문입니다.\n\n" + imgs + "\n\n더 있습니다.")
    paras = [hap_para(i) for i in range(5)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras) + "\n\n![](images/fig0.jpg)\n")
    res = ve.check(f, src)
    assert res.verdict == "FAIL"
    assert "이미지" in res.reason


def test_korean_source_far_below_floor_is_fail(tmp_path):
    """한국어 소스라도 절반 이하로 줄면 내용 소실이다.

    실데이터 보정: 한국어 소스 ratio 중앙값 1.93, p05 0.76 — 0.5 미만은 119편 중 4편뿐.
    """
    src = w(tmp_path, "p_ko.md", "한국어 소스 본문이 이어집니다. " * 400)
    paras = [hap_para(i) for i in range(3)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f, src)
    assert res.verdict == "FAIL"
    assert "ratio" in res.reason


def test_preserved_image_reference_passes(tmp_path):
    src = w(tmp_path, "p.md", "본문입니다.\n\n![](images/fig1.jpg)\n\n더 있습니다.")
    paras = [hap_para(i) for i in range(5)]
    body = doc(paras) + "\n\n![](images/fig1.jpg)\n"
    f = w(tmp_path, "p_ko_explained.md", body)
    res = ve.check(f, src)
    assert any(c.name == "image-refs" and c.status == "PASS" for c in res.checks)


def test_verbatim_source_copy_is_fail(tmp_path):
    """해설판이 소스를 그대로 옮긴 복사본이면 FAIL.

    실측(2026-08-03 Phase 2): Codex 첫 산출물이 소스 산문 문단의 100% 를 한 글자도
    바꾸지 않고 옮겼다. 자수비는 1.02x 라 ratio 게이트를 그냥 통과했다 — 별도 게이트가 필요하다.
    """
    body_paras = [hap_para(i) for i in range(5)]
    src = w(tmp_path, "p_ko.md", "\n\n".join(body_paras))
    f = w(tmp_path, "p_ko_explained.md", doc(body_paras))
    res = ve.check(f, src)
    assert res.verdict == "FAIL"
    assert "복사" in res.reason


def test_references_section_not_counted_as_copy(tmp_path):
    """회귀: 참고문헌 항목·그림 캡션은 원문 유지가 규칙 — 복사로 세면 안 된다.

    실측 오탐 — outputs/Agent Laboratory… 가 저자 명단 253문단 때문에 83% 로 잡혔다.
    """
    refs = "\n\n".join(
        "Josh Achiam, Steven Adler, Sandhini Agarwal, Lama Ahmad, Ilge Akkaya, "
        f"Florencia Leoni Aleman, Diogo Almeida, Janko Altenschmidt, Sam Altman {i}."
        for i in range(6)
    )
    caption = "그림 1. NeurIPS 점수 비교(인간 검토자 대 자동화된 검토자)\n![](images/fig1.jpg)"
    src = w(tmp_path, "p_ko.md",
            "\n\n".join([hae_para(0), caption]) + "\n\n## 참고문헌 (References)\n\n" + refs)
    body = (YAML + "\n\n".join([hap_para(i) for i in range(5)] + [caption])
            + GLOSSARY + "\n\n## 참고문헌 (References)\n\n" + refs)
    f = w(tmp_path, "p_ko_explained.md", body)
    res = ve.check(f, src)
    assert res.metrics.get("copy_ratio", 0) == 0, res.metrics
    assert res.verdict != "FAIL", res.reason


def test_partial_source_overlap_passes(tmp_path):
    """참고문헌·수식·직접인용은 원문 그대로 두는 것이 정상 — 일부 겹침으로 반려하지 않는다."""
    shared = [hap_para(0), hap_para(1)]                 # 그대로 옮긴 2문단
    rewritten = [hap_para(i) for i in range(2, 7)]      # 새로 쓴 5문단
    src = w(tmp_path, "p_ko.md", "\n\n".join(shared + [hae_para(3), hae_para(4)]))
    f = w(tmp_path, "p_ko_explained.md", doc(shared + rewritten))
    res = ve.check(f, src)
    assert res.verdict != "FAIL", res.reason


def _html_table(n_rows=3):
    rows = "".join(f"<tr><td>행{i}</td><td>0.{i}23</td></tr>" for i in range(n_rows))
    return f"<table>{rows}</table>"


def test_most_tables_dropped_is_fail(tmp_path):
    """결과 표를 버리면 FAIL — 표 안의 수치가 통째로 사라진다.

    실측(2026-08-03 Phase 2 r2): Codex 가 tech 논문의 HTML 표 4개 중 3개를 버려
    소스 수치 328개 중 36개(11%)가 사라졌다. 자수비 0.50x 는 FAIL 문턱 바로 위라
    ratio 게이트로는 못 잡았다.
    실데이터 보정(19편): 표 보존율 중앙 1.20 · p25 1.07 — 0.5 미만은 1편(기존 결함)뿐.
    """
    tables = "\n\n".join(_html_table() for _ in range(8))
    src = w(tmp_path, "p_ko.md", "\n\n".join([hae_para(i) for i in range(3)]) + "\n\n" + tables)
    # doc() 의 용어집이 마크다운 표 1개를 포함하므로 출력 표는 HTML 1 + 용어집 1 = 2/8
    body = doc([hap_para(i) for i in range(5)]) + "\n\n" + _html_table()
    f = w(tmp_path, "p_ko_explained.md", body)
    res = ve.check(f, src)
    assert res.verdict == "FAIL"
    assert "표" in res.reason


def test_html_table_converted_to_markdown_still_counts(tmp_path):
    """HTML 표를 마크다운 표로 바꾼 것은 유실이 아니다 — 형식 변환은 스킬이 권장한다(Rule 7).

    실측 정정: Codex tech 산출물을 `<table` 태그만 세면 1/4 로 보이지만,
    마크다운 표까지 세면 3/4 다.
    """
    tables = "\n\n".join(_html_table() for _ in range(3))
    src = w(tmp_path, "p_ko.md", "\n\n".join([hae_para(i) for i in range(3)]) + "\n\n" + tables)
    md_tables = "\n\n".join(
        f"| 항목{i} | 값 |\n|---|---|\n| a | 0.{i} |" for i in range(3))
    f = w(tmp_path, "p_ko_explained.md",
          doc([hap_para(i) for i in range(5)], glossary=False) + "\n\n" + md_tables)
    res = ve.check(f, src)
    assert any(c.name == "table-coverage" and c.status == "PASS" for c in res.checks)


def test_tables_preserved_passes(tmp_path):
    tables = "\n\n".join(_html_table() for _ in range(3))
    src = w(tmp_path, "p_ko.md", "\n\n".join([hae_para(i) for i in range(3)]) + "\n\n" + tables)
    f = w(tmp_path, "p_ko_explained.md", doc([hap_para(i) for i in range(5)]) + "\n\n" + tables)
    res = ve.check(f, src)
    assert any(c.name == "table-coverage" and c.status == "PASS" for c in res.checks)


def test_single_table_dropped_is_not_fail(tmp_path):
    """소스 표가 1개뿐이면 판정하지 않는다 — 표본이 작아 신호가 못 된다."""
    src = w(tmp_path, "p_ko.md", "\n\n".join([hae_para(i) for i in range(3)]) + "\n\n" + _html_table())
    f = w(tmp_path, "p_ko_explained.md", doc([hap_para(i) for i in range(5)]))
    res = ve.check(f, src)
    assert res.verdict != "FAIL", res.reason


def test_math_loss_is_review_not_fail(tmp_path):
    """수식 유실은 REVIEW — 실데이터 분포가 넓어 자동 반려 근거가 못 된다(p25 0.31)."""
    math = " ".join(f"$x_{{{i}}} = {i}$" for i in range(40))
    src = w(tmp_path, "p_ko.md", "\n\n".join([hae_para(i) for i in range(3)]) + "\n\n" + math)
    f = w(tmp_path, "p_ko_explained.md", doc([hap_para(i) for i in range(5)]))
    res = ve.check(f, src)
    assert any(c.name == "math-coverage" and c.status == "REVIEW" for c in res.checks)
    assert res.verdict != "FAIL", res.reason


def test_source_autodetected_from_folder(tmp_path):
    w(tmp_path, "p_ko.md", "한국어 소스 본문입니다. " * 50)
    paras = [hap_para(i) for i in range(5)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f)
    assert res.source is not None
    assert res.source.endswith("p_ko.md")


# --- 종료 코드 계약 (lane postflight 가 의존) -------------------------------


def test_exit_code_pass_is_zero(tmp_path):
    paras = [hap_para(i) for i in range(5)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    rc, _ = ve.main([f])
    assert rc == 0


def test_exit_code_review_is_zero(tmp_path):
    """REVIEW 는 자동 반려가 아니다 — lane 을 막지 않는다."""
    paras = [hap_para(i) for i in range(5)] + [hae_para(6)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    rc, _ = ve.main([f])
    assert rc == 0


def test_exit_code_fail_is_one(tmp_path):
    paras = [hae_para(i) for i in range(4)] + [hap_para(i) for i in range(3)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    rc, _ = ve.main([f])
    assert rc == 1


def test_strict_flag_makes_review_fail(tmp_path):
    """--strict 는 REVIEW 도 반려 — Phase 2 게이트/수동 감사용."""
    paras = [hap_para(i) for i in range(5)] + [hae_para(6)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    rc, _ = ve.main([f, "--strict"])
    assert rc == 1


# --- 본문 수치 coverage (피어 리뷰 2026-08-03 조건) -------------------------


def test_body_numbers_excludes_noise():
    """수치 추출은 YAML·URL/DOI·이미지 파일명·참고문헌·인용번호·그림표번호를 제외한다."""
    t = (
        "---\nlang: ko\nversion: 3\n---\n\n"
        "본문 정확도는 0.923 입니다.\n\n"
        "![](images/6ae127b08c7e012adc7d8713397ce4b676d06d08.jpg)\n\n"
        "자세한 건 https://arxiv.org/abs/2504.20073 과 doi:10.1145/3292500 참조 [12].\n\n"
        "그림 3 과 표 2 에 정리했습니다. 표본은 330개입니다.\n\n"
        "## 참고문헌 (References)\n\n[1] Kim et al., 2023, pp.145-147.\n"
    )
    got = ve.body_numbers(t)
    assert "0.923" in got
    assert "330" in got
    for noise in ("2504.20073", "10.1145", "3292500", "12", "3", "2", "2023", "145", "147"):
        assert noise not in got, f"{noise} 가 본문 수치로 잡혔다: {sorted(got)}"


def test_number_coverage_missing_values_is_fail(tmp_path):
    """소스 본문 수치가 여러 개 사라지면 FAIL — ratio 로는 못 잡는 누락이다."""
    vals = " ".join(f"지표{i} 는 0.{100+i} 입니다." for i in range(20))
    src = w(tmp_path, "p_ko.md", "\n\n".join([hae_para(0), vals, hae_para(1)]))
    kept = " ".join(f"지표{i} 는 0.{100+i} 입니다." for i in range(12))
    f = w(tmp_path, "p_ko_explained.md", doc([hap_para(i) for i in range(5)] + [kept]))
    res = ve.check(f, src)
    assert res.verdict == "FAIL"
    assert "수치" in res.reason


def test_number_coverage_full_passes(tmp_path):
    vals = " ".join(f"지표{i} 는 0.{100+i} 입니다." for i in range(20))
    src = w(tmp_path, "p_ko.md", "\n\n".join([hae_para(0), vals, hae_para(1)]))
    f = w(tmp_path, "p_ko_explained.md", doc([hap_para(i) for i in range(5)] + [vals]))
    res = ve.check(f, src)
    assert any(c.name == "number-coverage" and c.status == "PASS" for c in res.checks)


def test_numbers_dumped_into_glossary_do_not_count(tmp_path):
    """게이트 통과용 수치 덤프 방지 — 용어집/수치 인덱스에 몰아넣은 값은 coverage 로 안 친다."""
    vals = " ".join(f"지표{i} 는 0.{100+i} 입니다." for i in range(20))
    src = w(tmp_path, "p_ko.md", "\n\n".join([hae_para(0), vals, hae_para(1)]))
    body = (YAML + "\n\n".join(hap_para(i) for i in range(5))
            + "\n\n## 핵심 용어 해설\n\n| 용어 | 쉬운 설명 |\n|---|---|\n| 임베딩 | 뜻을 숫자로 |\n"
            + "\n\n## 수치 인덱스\n\n" + vals + "\n")
    f = w(tmp_path, "p_ko_explained.md", body)
    res = ve.check(f, src)
    assert res.verdict == "FAIL"
    assert "수치" in res.reason


# --- 표 행 시그니처 coverage -------------------------------------------------


def test_table_row_coverage_missing_row_is_fail(tmp_path):
    rows = "".join(
        f"<tr><td>지표{i}</td><td>0.{200+i}</td><td>0.{300+i}</td></tr>" for i in range(6))
    src = w(tmp_path, "p_ko.md", hae_para(0) + f"\n\n<table>{rows}</table>\n")
    kept = "\n".join(f"| 지표{i} | 0.{200+i} | 0.{300+i} |" for i in range(2))
    body = (YAML + "\n\n".join(hap_para(i) for i in range(5))
            + "\n\n| 항목 | A | B |\n|---|---|---|\n" + kept + "\n" + GLOSSARY)
    f = w(tmp_path, "p_ko_explained.md", body)
    res = ve.check(f, src)
    assert any(c.name == "table-row-coverage" and c.status == "FAIL" for c in res.checks)


def test_table_row_coverage_all_rows_kept_passes(tmp_path):
    rows = "".join(
        f"<tr><td>지표{i}</td><td>0.{200+i}</td><td>0.{300+i}</td></tr>" for i in range(6))
    src = w(tmp_path, "p_ko.md", hae_para(0) + f"\n\n<table>{rows}</table>\n")
    kept = "\n".join(f"| 지표{i} | 0.{200+i} | 0.{300+i} |" for i in range(6))
    body = (YAML + "\n\n".join(hap_para(i) for i in range(5))
            + "\n\n| 항목 | A | B |\n|---|---|---|\n" + kept + "\n" + GLOSSARY)
    f = w(tmp_path, "p_ko_explained.md", body)
    res = ve.check(f, src)
    assert any(c.name == "table-row-coverage" and c.status == "PASS" for c in res.checks)


# --- 위험도별 ratio ----------------------------------------------------------


def test_high_risk_korean_ratio_stricter(tmp_path):
    """high-risk 문서(수식·표 밀집)는 0.65x 미만이 FAIL — 저위험 기준(0.5)으로는 못 잡는다."""
    math = " ".join(f"$x_{{{i}}}={i}$" for i in range(30))
    src = w(tmp_path, "p_ko.md",
            "\n\n".join([hae_para(i % 7) for i in range(14)]) + "\n\n" + math)
    body = doc([hap_para(i) for i in range(5)]) + "\n\n" + math
    f = w(tmp_path, "p_ko_explained.md", body)
    res = ve.check(f, src)
    assert res.metrics["high_risk"] is True
    assert 0.5 <= res.metrics["ratio"] < 0.65, res.metrics["ratio"]
    assert res.verdict == "FAIL"


def test_low_risk_prose_ratio_not_blocking(tmp_path):
    """저위험 산문 0.63x 는 자동 반려하지 않는다 — Phase 2 산문이 실제로 충실했다."""
    src = w(tmp_path, "p_ko.md", "\n\n".join(hae_para(i % 7) for i in range(9)))
    f = w(tmp_path, "p_ko_explained.md", doc([hap_para(i) for i in range(5)]))
    res = ve.check(f, src)
    assert res.metrics["high_risk"] is False
    assert res.verdict != "FAIL"
    assert not res.blocking, res.reason


# --- BLOCKING / ADVISORY 분리 ------------------------------------------------


def test_advisory_review_does_not_block_production(tmp_path):
    """편집 품질 신호(용어집 없음·비유마커)는 publish 를 막지 않는다."""
    paras = [hap_para(i) for i in range(5)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras, glossary=False))
    res = ve.check(f)
    assert res.verdict == "REVIEW"
    assert not res.blocking, res.reason
    rc, _ = ve.main([f, "--production"])
    assert rc == 0


def test_blocking_review_fails_production(tmp_path):
    """coverage 계열 불확실성은 --production 에서 반려된다."""
    imgs = "\n\n".join(f"![](images/fig{i}.jpg)" for i in range(5))
    src = w(tmp_path, "p.md", "본문입니다.\n\n" + imgs + "\n\n더 있습니다.")
    kept = "\n\n".join(f"![](images/fig{i}.jpg)" for i in range(4))
    f = w(tmp_path, "p_ko_explained.md", doc([hap_para(i) for i in range(5)]) + "\n\n" + kept)
    res = ve.check(f, src)
    assert res.verdict == "REVIEW"
    assert res.blocking
    rc, _ = ve.main([f, src, "--production"])
    assert rc == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
