"""언어 스토어 기본값은 한국어여야 한다.

2026-08-23 신고: "목록 보기에서 제목과 요약이 번역 안된게 많아".
실제로는 문서 994건 중 992건에 한국어 제목·요약이 **이미 있었다**. 표시 조건이
`$store.lang.ko` 인데 스토어 기본값이 영어라, 저장된 선택이 없는 브라우저에서는
번역이 있어도 전부 영어로 나왔다. 원문이 한국어인 문서(HBR 등 약 160건)만 한글로
보이니 "많이 번역 안 됨" 으로 읽힌다.

앱은 한국어 우선이다(`<html lang="ko">`, UI 문구가 한국어). 저장된 선택이 없으면
한국어가 기본이고, 사용자가 명시적으로 고른 'en' 은 그대로 존중해야 한다.
"""
import re
from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "app" / "templates" / "base.html"


def _lang_store_block():
    html = TPL.read_text(encoding="utf-8")
    assert "Alpine.store('lang'" in html, "언어 스토어가 없다"
    start = html.index("Alpine.store('lang'")
    return html[start:start + 500]


def test_lang_defaults_to_korean_when_nothing_saved():
    block = _lang_store_block()
    # 저장값이 없을 때 'ko' 로 떨어지는 형태여야 한다.
    assert re.search(r"localStorage\.getItem\('pf-lang'\)\s*\|\|\s*'ko'", block), block


def test_explicit_english_choice_is_respected():
    """기본값만 바꾸고, 저장된 'en' 은 계속 영어여야 한다 — 비교 대상은 여전히 'ko'."""
    block = _lang_store_block()
    assert "=== 'ko'" in block, block


def test_toggle_still_persists_both_directions():
    block = _lang_store_block()
    assert "setItem('pf-lang', this.ko ? 'ko' : 'en')" in block, block
