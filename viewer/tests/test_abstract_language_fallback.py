"""요약 표시는 한쪽 언어가 비어 있으면 다른 쪽으로 폴백해야 한다.

2026-08-23 조사: 문서 227건은 한국어 요약(`abstract_ko`)만 있고 영어 요약
(`abstract`)이 빈 문자열이다(HBR·이코노미스트 수집기가 한국어 요약만 생성).
템플릿이 영어 모드에서 `paper.abstract` 를 그대로 그려서 **요약칸이 빈 채로**
나왔고, 이것이 "요약이 번역 안 됐다" 로 보고됐다.

언어 토글은 선호일 뿐이다. 선호 언어가 비어 있으면 있는 쪽을 보여주는 편이
빈칸보다 항상 낫다. 제목은 이미 `(paper.title || paper.name)` 로 폴백하고 있다.
"""
import re
from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "app" / "templates" / "papers.html"

# 요약을 그리는 x-text 표현식들
ABSTRACT_EXPR = re.compile(r"\$store\.lang\.ko && paper\.abstract_ko[^\"]*")


def _abstract_exprs():
    html = TPL.read_text(encoding="utf-8")
    return ABSTRACT_EXPR.findall(html)


def test_every_abstract_render_site_falls_back_both_ways():
    exprs = _abstract_exprs()
    assert len(exprs) >= 3, f"요약 렌더 지점이 3곳 미만: {exprs}"
    for e in exprs:
        # 한국어 선호가 비면 영어로, 영어 선호가 비면 한국어로.
        assert "paper.abstract || paper.abstract_ko" in e, e


def test_no_bare_english_abstract_fallback_remains():
    """`: paper.abstract` 로 끝나는 맨 폴백이 남아 있으면 빈칸이 다시 생긴다."""
    html = TPL.read_text(encoding="utf-8")
    assert "? paper.abstract_ko : paper.abstract\"" not in html
