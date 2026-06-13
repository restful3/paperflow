"""Phase 1a: books 경로 추상화 + 설정 단위/회귀 테스트."""
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _rebind_papers_settings(tmp_workspace, monkeypatch):
    """papers.py imports settings at module level; rebind so resolvers see tmp_workspace."""
    from app import config as _cfg
    from app.services import papers
    monkeypatch.setattr(papers, "settings", _cfg.settings)


def test_books_dir_settings_under_base(tmp_workspace):
    from app import config as _cfg
    s = _cfg.settings
    assert s.books_dir == Path(tmp_workspace) / "books"
    assert s.newbooks_dir == Path(tmp_workspace) / "newbooks"
    assert s.book_archives_dir == Path(tmp_workspace) / "book_archives"


def test_tmp_workspace_creates_book_dirs(tmp_workspace):
    assert (tmp_workspace / "books").is_dir()
    assert (tmp_workspace / "newbooks").is_dir()
    assert (tmp_workspace / "book_archives").is_dir()


RESOLVERS = [
    ("get_pdf_path", "get_pdf_path_in_dir", "paper.pdf"),
    ("get_md_ko_path", "get_md_ko_path_in_dir", "paper_ko.md"),
    ("get_md_en_path", "get_md_en_path_in_dir", "paper.md"),
    ("get_md_ko_explained_path", "get_md_ko_explained_path_in_dir", "paper_ko_explained.md"),
    ("get_md_en_explained_path", "get_md_en_explained_path_in_dir", "paper_explained.md"),
    ("get_md_ko_audio_path", "get_md_ko_audio_path_in_dir", "paper_ko_audio.md"),
    ("get_md_ko_audio_brief_path", "get_md_ko_audio_brief_path_in_dir", "paper_ko_audio_brief.md"),
]


@pytest.mark.parametrize("name_fn,dir_fn,fname", RESOLVERS)
def test_resolver_roundtrip(tmp_workspace, name_fn, dir_fn, fname):
    """name API 와 *_in_dir 가 같은 파일을 가리킨다."""
    from app.services import papers
    d = tmp_workspace / "outputs" / "paper"
    d.mkdir(parents=True)
    (d / fname).write_text("x")
    by_name = getattr(papers, name_fn)("paper")
    by_dir = getattr(papers, dir_fn)(d)
    assert by_dir == d / fname
    assert by_name == by_dir


def test_get_asset_path_in_dir_roundtrip_and_traversal(tmp_workspace):
    from app.services import papers
    d = tmp_workspace / "outputs" / "paper"
    (d / "images").mkdir(parents=True)
    (d / "images" / "f.jpg").write_text("x")
    # sibling file outside the paper dir — must not be reachable via ../
    (tmp_workspace / "outputs" / "secret.txt").write_text("nope")
    assert papers.get_asset_path_in_dir(d, "images/f.jpg") == d / "images" / "f.jpg"
    assert papers.get_asset_path("paper", "images/f.jpg") == d / "images" / "f.jpg"
    assert papers.get_asset_path_in_dir(d, "../secret.txt") is None


def test_paper_info_from_dir_alias(tmp_workspace):
    from app.services import papers
    d = tmp_workspace / "outputs" / "paper"
    d.mkdir(parents=True)
    (d / "paper.md").write_text("# hi")
    info = papers.paper_info_from_dir(d, "outputs")
    assert info["name"] == "paper"
    assert info["location"] == "outputs"
    assert info["formats"]["md_en"] is True
