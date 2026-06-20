"""폭 독립화: viewer.html 의 콘텐츠 폭이 md/split 뷰별로 독립 저장되는지 배선 검증.

토큰 존재(present)와 실제 연결(connected)을 분리해, 레거시 전역 단일 키
(`pf-content-width`) 가 그대로 남아 뷰별 분리가 무력화되는 회귀를 막는다.
"""
from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "app" / "templates" / "viewer.html"


def test_per_view_width_wiring_present():
    html = TPL.read_text(encoding="utf-8")
    for token in [
        "contentWidthKey(",
        "loadContentWidthForView(",
        "defaultContentWidth(",
        "pf-content-width-split",
        "pf-content-width-md",
    ]:
        assert token in html, f"missing per-view width token: {token}"


def test_per_view_width_actually_connected():
    html = TPL.read_text(encoding="utf-8")
    # setContentWidth writes the view-scoped key, NOT the legacy global one.
    assert "localStorage.setItem(this.contentWidthKey(), width)" in html
    assert "localStorage.setItem('pf-content-width', width)" not in html
    # switchView reloads width for the new view so md/split don't bleed.
    assert "this.loadContentWidthForView();" in html
    # storage sync handles the view-scoped keys (prefix), not the bare key only.
    assert "startsWith('pf-content-width')" in html
    # legacy global is still read as a migration fallback.
    assert "localStorage.getItem('pf-content-width')" in html
