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


@pytest.fixture
def client_anon(tmp_workspace, monkeypatch):
    from app import config as _cfg
    from app.services import papers, books
    monkeypatch.setattr(papers, "settings", _cfg.settings)
    monkeypatch.setattr(books, "settings", _cfg.settings)
    import app.main as _main
    monkeypatch.setattr(_main.settings, "JWT_SECRET_KEY", _cfg.settings.JWT_SECRET_KEY)
    monkeypatch.setattr(_main.settings, "BASE_DIR", _cfg.settings.BASE_DIR)
    from app.main import create_app
    return TestClient(create_app(), follow_redirects=False)


def test_books_page_renders_for_authed_user(client):
    resp = client.get("/books")
    assert resp.status_code == 200
    body = resp.text
    assert 'booksApp()' in body
    assert '/api/books' in body
    assert 'href="/papers"' in body   # nav reciprocity


def test_books_page_redirects_anon_to_login(client_anon):
    resp = client_anon.get("/books")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"
