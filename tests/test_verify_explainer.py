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


def test_ratio_far_below_floor_is_review(tmp_path):
    """외국어 소스 대비 0.6x 미만 = 누락 의심 신호."""
    src = w(tmp_path, "p.md", "English source. " * 900)
    paras = [hap_para(i) for i in range(3)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f, src)
    assert res.verdict == "REVIEW"
    assert "ratio" in res.reason


def test_missing_image_reference_is_review(tmp_path):
    src = w(tmp_path, "p.md", "본문입니다.\n\n![](images/fig1.jpg)\n\n더 있습니다.")
    paras = [hap_para(i) for i in range(5)]
    f = w(tmp_path, "p_ko_explained.md", doc(paras))
    res = ve.check(f, src)
    assert any(c.name == "image-refs" and c.status != "PASS" for c in res.checks)


def test_preserved_image_reference_passes(tmp_path):
    src = w(tmp_path, "p.md", "본문입니다.\n\n![](images/fig1.jpg)\n\n더 있습니다.")
    paras = [hap_para(i) for i in range(5)]
    body = doc(paras) + "\n\n![](images/fig1.jpg)\n"
    f = w(tmp_path, "p_ko_explained.md", body)
    res = ve.check(f, src)
    assert any(c.name == "image-refs" and c.status == "PASS" for c in res.checks)


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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
