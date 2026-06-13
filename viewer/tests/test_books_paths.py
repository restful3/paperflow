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


def test_safe_book_dir_resolves_books_and_archives(tmp_workspace):
    from app.services import papers
    (tmp_workspace / "books" / "MyBook").mkdir(parents=True)
    (tmp_workspace / "book_archives" / "OldBook").mkdir(parents=True)
    assert papers.safe_book_dir("MyBook") == tmp_workspace / "books" / "MyBook"
    assert papers.safe_book_dir("OldBook") == tmp_workspace / "book_archives" / "OldBook"
    assert papers.safe_book_dir("Nope") is None


def test_safe_book_dir_rejects_traversal_and_slash(tmp_workspace):
    from app.services import papers
    assert papers.safe_book_dir("../outputs") is None
    assert papers.safe_book_dir("a/b") is None
    assert papers.safe_book_dir("..") is None


def test_safe_book_dir_rejects_symlink_escape(tmp_workspace):
    from app.services import papers
    outside = tmp_workspace / "secret"
    outside.mkdir()
    link = tmp_workspace / "books" / "evil"
    link.symlink_to(outside, target_is_directory=True)
    assert papers.safe_book_dir("evil") is None


def test_safe_book_chapter_dir(tmp_workspace):
    from app.services import papers
    ch = tmp_workspace / "books" / "MyBook" / "01_intro"
    ch.mkdir(parents=True)
    assert papers.safe_book_chapter_dir("MyBook", "01_intro") == ch
    assert papers.safe_book_chapter_dir("MyBook", "nope") is None
    assert papers.safe_book_chapter_dir("MyBook", "../..") is None
    assert papers.safe_book_chapter_dir("MyBook", "a/b") is None
    assert papers.safe_book_chapter_dir("Nope", "01_intro") is None


def test_safe_book_chapter_dir_in_archives(tmp_workspace):
    from app.services import papers
    ch = tmp_workspace / "book_archives" / "OldBook" / "02_ch"
    ch.mkdir(parents=True)
    assert papers.safe_book_chapter_dir("OldBook", "02_ch") == ch


def test_safe_book_chapter_dir_rejects_symlink_escape(tmp_workspace):
    from app.services import papers
    book = tmp_workspace / "books" / "MyBook"
    book.mkdir(parents=True)
    outside = tmp_workspace / "secret_ch"
    outside.mkdir()
    # a chapter that is a symlink pointing outside the book dir must be rejected
    (book / "evil_chapter").symlink_to(outside, target_is_directory=True)
    assert papers.safe_book_chapter_dir("MyBook", "evil_chapter") is None
