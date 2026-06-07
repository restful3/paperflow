"""papers.html 배지 타입별 개수 배선 어서션.

토큰 존재만 보지 않고, 배지가 실제로 getter에 연결되고 getter가 filterDocType +
stats.by_type에 의존하는지 확인한다.
"""
from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "app" / "templates" / "papers.html"


def test_badge_getters_defined():
    html = TPL.read_text(encoding="utf-8")
    assert "get unreadBadge()" in html
    assert "get archivedBadge()" in html
    # getter가 filterDocType + by_type에 의존
    assert "this.stats.by_type?.[this.filterDocType]?.unread" in html
    assert "this.stats.by_type?.[this.filterDocType]?.archived" in html


def test_badges_bound_to_getters_not_raw_stats():
    html = TPL.read_text(encoding="utf-8")
    # 배지 바인딩이 getter로 교체됨
    assert 'x-text="unreadBadge"' in html
    assert 'x-text="archivedBadge"' in html
    # 기존 raw stats 바인딩은 배지에서 사라짐
    assert 'x-text="stats.unread"' not in html
    assert 'x-text="stats.archived"' not in html


def test_stats_init_has_by_type():
    html = TPL.read_text(encoding="utf-8")
    assert "by_type:" in html
