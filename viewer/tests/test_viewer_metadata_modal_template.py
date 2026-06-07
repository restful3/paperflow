"""뷰어 메타데이터 모달 배선 어서션.

데스크톱 ⓘ 버튼·모바일 햄버거 항목이 모달을 열고, 모달이 서지 필드를 Jinja로
렌더하며, ESC/바깥클릭/닫기로 닫히는지 확인한다. 렌더·링크는 수동 시각 확인이 주 기준.
"""
from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "app" / "templates" / "viewer.html"


def test_meta_modal_marker_and_state():
    html = TPL.read_text(encoding="utf-8")
    assert "<!-- meta-modal -->" in html
    assert "metaModal: { show: false }" in html


def test_meta_modal_open_wired_desktop_and_mobile():
    html = TPL.read_text(encoding="utf-8")
    # 데스크톱 ⓘ 버튼 + 모바일 햄버거 항목 = 2회 이상
    assert html.count("metaModal.show = true") >= 2


def test_meta_modal_close_wired():
    html = TPL.read_text(encoding="utf-8")
    assert "metaModal.show = false" in html
    assert '@keydown.escape.window="metaModal.show = false"' in html


def test_meta_modal_shows_bibliographic_fields():
    html = TPL.read_text(encoding="utf-8")
    after = html.split("<!-- meta-modal -->", 1)[1]
    for token in ["paper_authors", "paper_venue", "paper_doi", "paper_url"]:
        assert token in after, f"missing meta field: {token}"
