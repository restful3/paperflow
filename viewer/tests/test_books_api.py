import json
import pytest
from fastapi.testclient import TestClient


def _make_book(ws, slug="MyBook", book_id="book-mybook-aaa111",
               chapters=(("01_intro", "Intro"),), archived=False, ko=True, cover=False):
    base = ws / ("book_archives" if archived else "books")
    bd = base / slug
    bd.mkdir(parents=True)
    meta = {"schema_version": 1, "book_id": book_id, "title": slug,
            "author": "A. Author", "year": 2024, "chapters": []}
    if cover:
        (bd / "cover.jpg").write_bytes(b"\xff\xd8\xff")
        meta["cover"] = "cover.jpg"
    for i, (cid, title) in enumerate(chapters, 1):
        cdir = bd / cid
        cdir.mkdir()
        (cdir / f"{cid}.md").write_text("# en", encoding="utf-8")
        if ko:
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
    # tmp_workspace already set JWT_SECRET_KEY="x"*48 via env; _cfg.settings is
    # the fresh Settings() instance.  main.py holds a direct reference to the old
    # singleton, so patch the JWT field on that singleton too so validate_runtime passes.
    import app.main as _main
    monkeypatch.setattr(_main.settings, "JWT_SECRET_KEY", _cfg.settings.JWT_SECRET_KEY)
    monkeypatch.setattr(_main.settings, "BASE_DIR", _cfg.settings.BASE_DIR)
    from app.main import create_app
    from app.dependencies import get_current_user_api
    app = create_app()
    app.dependency_overrides[get_current_user_api] = lambda: "tester"
    return TestClient(app)


def test_list_books_endpoint(client, tmp_workspace):
    _make_book(tmp_workspace, slug="BookA")
    r = client.get("/api/books")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "BookA"


def test_list_books_archived_tab(client, tmp_workspace):
    _make_book(tmp_workspace, slug="OldB", archived=True)
    assert client.get("/api/books").json() == []
    arch = client.get("/api/books?tab=archived").json()
    assert len(arch) == 1


def test_book_info_endpoint(client, tmp_workspace):
    _make_book(tmp_workspace, slug="BookB", chapters=(("01_intro", "Intro"),))
    r = client.get("/api/books/BookB/info")
    assert r.status_code == 200
    assert r.json()["chapters"][0]["chapter_id"] == "01_intro"
    assert client.get("/api/books/Ghost/info").status_code == 404


def test_chapter_md_ko_endpoint(client, tmp_workspace):
    _make_book(tmp_workspace, slug="BookC", chapters=(("01_intro", "Intro"),))
    r = client.get("/api/books/BookC/chapters/01_intro/md-ko")
    assert r.status_code == 200
    assert r.text == "# ko"
    assert client.get("/api/books/BookC/chapters/01_intro/pdf").status_code == 404


def test_chapter_progress_save_and_book_info_reflects(client, tmp_workspace):
    _make_book(tmp_workspace, slug="BookD", book_id="book-d-1",
               chapters=(("01_intro", "Intro"),))
    r = client.post("/api/books/BookD/chapters/01_intro/progress", json={"progress": 80})
    assert r.status_code == 200
    info = client.get("/api/books/BookD/info").json()
    assert info["chapters"][0]["progress"] == 80


def test_chapter_markdown_put(client, tmp_workspace):
    _make_book(tmp_workspace, slug="BookE", chapters=(("01_intro", "Intro"),))
    r = client.put("/api/books/BookE/chapters/01_intro/markdown/ko",
                   json={"content": "# 수정"})
    assert r.status_code == 200
    assert client.get("/api/books/BookE/chapters/01_intro/md-ko").text == "# 수정"


def test_archive_restore_delete_endpoints(client, tmp_workspace):
    _make_book(tmp_workspace, slug="BookF", chapters=(("01_intro", "Intro"),))
    assert client.post("/api/books/BookF/archive").status_code == 200
    assert (tmp_workspace / "book_archives" / "BookF").is_dir()
    assert client.post("/api/books/BookF/restore").status_code == 200
    assert (tmp_workspace / "books" / "BookF").is_dir()
    assert client.delete("/api/books/BookF").status_code == 200
    assert not (tmp_workspace / "books" / "BookF").exists()


def test_cover_endpoint(client, tmp_workspace):
    _make_book(tmp_workspace, slug="BookG", chapters=(("01_intro", "Intro"),), cover=True)
    r = client.get("/api/books/BookG/cover")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


def test_books_require_auth(tmp_workspace, monkeypatch):
    from app import config as _cfg
    from app.services import papers, books
    import app.main as _main
    monkeypatch.setattr(papers, "settings", _cfg.settings)
    monkeypatch.setattr(books, "settings", _cfg.settings)
    monkeypatch.setattr(_main.settings, "JWT_SECRET_KEY", _cfg.settings.JWT_SECRET_KEY)
    monkeypatch.setattr(_main.settings, "BASE_DIR", _cfg.settings.BASE_DIR)
    from app.main import create_app
    c = TestClient(create_app())  # no auth override
    assert c.get("/api/books").status_code == 401
