"""리스트뷰 메인 행 슬림화 + 확장 패널 이동분 배선 어서션.

별점·메타(venue/크기/추가일)가 확장 패널로 이동했는지, 메인 행이 고정폭 열로
재구성됐는지를 마커/토큰으로 확인한다. 픽셀 정렬은 수동 시각 확인이 주 기준이다.
"""
from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "app" / "templates" / "papers.html"


def test_panel_relocations_markers_present():
    html = TPL.read_text(encoding="utf-8")
    assert "<!-- list-meta-line -->" in html
    assert "<!-- list-rating-detail -->" in html


def test_rating_setter_in_detail_panel():
    html = TPL.read_text(encoding="utf-8")
    after = html.split("<!-- list-rating-detail -->", 1)[1]
    assert "setRating(paper.name" in after
    assert "'list-rate-' + s" in after


def test_meta_line_has_venue_size_date():
    html = TPL.read_text(encoding="utf-8")
    after = html.split("<!-- list-meta-line -->", 1)[1][:800]
    assert "paper.venue || paper.source_domain" in after
    assert "paper.size_mb + ' MB'" in after
    assert "paperDateLabel(paper)" in after


def test_main_row_single_category_tag_removed():
    html = TPL.read_text(encoding="utf-8")
    # 리스트뷰 메인 행의 단일 카테고리 칩만 slice(0, 1)을 쓴다(파일 내 유일).
    assert "(paper.categories || []).slice(0, 1)" not in html


def test_main_row_fixed_width_columns():
    html = TPL.read_text(encoding="utf-8")
    assert 'class="hidden sm:flex w-16 justify-end shrink-0"' in html  # doc_type 열
    assert 'class="w-14 flex justify-end items-center gap-1 shrink-0"' in html  # 파일점 열


def test_card_and_list_use_visible_window():
    html = TPL.read_text(encoding="utf-8")
    assert "this.visiblePapers" in html              # cardColumns source
    assert 'x-for="paper in visiblePapers"' in html  # list loop source
    assert "renderLimit" in html
    assert "resetWindow" in html
    assert "loadMoreCards" in html
    assert ("x-intersect" in html) or ("IntersectionObserver" in html)


def test_reshuffle_resets_window():
    import re
    html = TPL.read_text(encoding="utf-8")
    # reshuffle() must reset the render window (watchers miss random reorder).
    # Capture the whole method body up to its closing `},` — a naive `.*?\}`
    # would stop at the inner `const keys = {}` empty-object literal.
    m = re.search(r"reshuffle\(\)\s*\{(.*?)\n    \},", html, re.S)
    assert m and "resetWindow()" in m.group(1)
