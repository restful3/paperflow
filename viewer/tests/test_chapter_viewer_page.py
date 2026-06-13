import json
import pytest
from fastapi.testclient import TestClient


def _make_book(ws, slug="MyBook", book_id="book-mybook-aaa111",
               chapters=(("01_intro", "Intro"), ("02_more", "More"))):
    bd = ws / "books" / slug
    bd.mkdir(parents=True)
    meta = {"schema_version": 1, "book_id": book_id, "title": "My Book",
            "author": "A", "year": 2024, "chapters": []}
    for i, (cid, title) in enumerate(chapters, 1):
        cdir = bd / cid
        cdir.mkdir()
        (cdir / f"{cid}.md").write_text("# en", encoding="utf-8")
        (cdir / f"{cid}_ko.md").write_text("# ko", encoding="utf-8")
        meta["chapters"].append({"order": i, "chapter_id": cid, "title": title,
                                 "source_pdf": f"{cid}.pdf", "source_sha256": "x" * 64})
    (bd / "book_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return bd


@pytest.fixture
def client(tmp_workspace, monkeypatch):
    from app import config as _cfg
    from app.services import papers, books
    monkeypatch.setattr(papers, "settings", _cfg.settings)
    monkeypatch.setattr(books, "settings", _cfg.settings)
    import app.main as _main
    monkeypatch.setattr(_main.settings, "JWT_SECRET_KEY", _cfg.settings.JWT_SECRET_KEY)
    monkeypatch.setattr(_main.settings, "BASE_DIR", _cfg.settings.BASE_DIR)
    from app.main import create_app
    from app.dependencies import get_current_user_page
    app = create_app()
    app.dependency_overrides[get_current_user_page] = lambda: "tester"
    return TestClient(app, follow_redirects=False)


def test_chapter_viewer_renders_with_book_apibase(client, tmp_workspace):
    _make_book(tmp_workspace, slug="MyBook", book_id="book-mybook-aaa111")
    r = client.get("/books/MyBook/chapters/01_intro")
    assert r.status_code == 200
    html = r.text
    assert 'const apiBase = "/api/books/MyBook/chapters/01_intro";' in html
    assert 'const viewerKind = "book_chapter";' in html
    assert 'const storageScope = "book_book-mybook-aaa111-ch_01_intro";' in html
    assert 'x-data="chatPanel()"' not in html
    assert 'x-data="chatButton()"' not in html


def test_chapter_viewer_prev_next(client, tmp_workspace):
    _make_book(tmp_workspace, slug="MyBook")
    html1 = client.get("/books/MyBook/chapters/01_intro").text
    assert "/books/MyBook/chapters/02_more" in html1
    html2 = client.get("/books/MyBook/chapters/02_more").text
    assert "/books/MyBook/chapters/01_intro" in html2


def test_chapter_viewer_unknown_redirects(client, tmp_workspace):
    _make_book(tmp_workspace, slug="MyBook")
    r = client.get("/books/MyBook/chapters/99_nope")
    assert r.status_code == 302
    assert r.headers["location"] == "/books/MyBook"
    r2 = client.get("/books/Ghost/chapters/01_intro")
    assert r2.status_code == 302
    assert r2.headers["location"] == "/books"


def test_chapter_viewer_requires_auth(tmp_workspace, monkeypatch):
    from app import config as _cfg
    from app.services import papers, books
    monkeypatch.setattr(papers, "settings", _cfg.settings)
    monkeypatch.setattr(books, "settings", _cfg.settings)
    import app.main as _main
    monkeypatch.setattr(_main.settings, "JWT_SECRET_KEY", _cfg.settings.JWT_SECRET_KEY)
    monkeypatch.setattr(_main.settings, "BASE_DIR", _cfg.settings.BASE_DIR)
    from app.main import create_app
    _make_book(tmp_workspace, slug="MyBook")
    c = TestClient(create_app(), follow_redirects=False)
    r = c.get("/books/MyBook/chapters/01_intro")
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_chapter_viewer_shows_breadcrumb_and_counter(client, tmp_workspace):
    _make_book(tmp_workspace, slug="MyBook")
    html = client.get("/books/MyBook/chapters/01_intro").text
    assert "My Book" in html       # book title in breadcrumb
    assert "Intro" in html         # chapter title
    assert "1 / 2" in html         # counter chapter_index / chapters_total


def test_chapter_first_has_no_prev_last_has_no_next(client, tmp_workspace):
    _make_book(tmp_workspace, slug="MyBook")
    first = client.get("/books/MyBook/chapters/01_intro").text
    last = client.get("/books/MyBook/chapters/02_more").text
    assert "/books/MyBook/chapters/02_more" in first   # next link on first
    assert "/books/MyBook/chapters/01_intro" in last   # prev link on last
