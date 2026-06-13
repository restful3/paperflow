import pytest
from fastapi.testclient import TestClient


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


def _make_paper(ws, name="P"):
    d = ws / "outputs" / name
    d.mkdir(parents=True)
    (d / f"{name}.md").write_text("# en", encoding="utf-8")
    (d / f"{name}_ko.md").write_text("# ko", encoding="utf-8")
    return d


def test_paper_viewer_route_renders(client, tmp_workspace):
    _make_paper(tmp_workspace, "P")
    r = client.get("/viewer/P")
    assert r.status_code == 200  # paper viewer still renders after adding keys


def test_paper_viewer_unknown_redirects(client, tmp_workspace):
    r = client.get("/viewer/DoesNotExist")
    assert r.status_code == 302
    assert r.headers["location"] == "/papers"


def test_paper_viewer_injects_consts(client, tmp_workspace):
    _make_paper(tmp_workspace, "P")
    html = client.get("/viewer/P").text
    assert 'const apiBase = "/api/papers/P";' in html
    assert 'const viewerKind = "paper";' in html
    assert 'const storageScope = "P";' in html
    assert 'const storageScopeRaw = "P";' in html


def test_paper_viewer_consts_are_escape_safe(client, tmp_workspace):
    # |tojson must escape so a folder name with an apostrophe can't break the JS.
    # Jinja2 tojson renders apostrophe as ' (Unicode escape for HTML safety),
    # NOT as a bare ' — this is the safe form.
    _make_paper(tmp_workspace, "O'Brien Paper")
    html = client.get("/viewer/O'Brien%20Paper").text
    assert html
    # Jinja2 tojson escapes ' as ' inside the JSON string literal
    assert "const storageScopeRaw = \"O\\u0027Brien Paper\";" in html


def test_paper_viewer_uses_apibase_not_hardcoded_content_paths(client, tmp_workspace):
    _make_paper(tmp_workspace, "P")
    html = client.get("/viewer/P").text
    assert "apiBase + '/pdf'" in html
    assert "apiBase + '/md-ko'" in html
    assert "${apiBase}/progress" in html
    assert "${apiBase}/markdown/" in html
    assert "${apiBase}/assets/" in html
    assert "apiBase + '/md-ko-explained'" in html
    assert "navigator.sendBeacon(apiBase + '/progress'" in html
    assert "'/api/papers/' + name + '/pdf'" not in html
    assert "'/api/papers/' + name + '/md-ko'" not in html
    assert "/api/papers/${name}/progress" not in html
    assert "navigator.sendBeacon('/api/papers/' + name + '/progress'" not in html


def _render_viewer_html_with_kind(kind):
    """Render viewer.html directly via the pages.py Jinja env with a chapter-kind context."""
    from app.main import create_app
    create_app()
    from app.routers import pages as pages_mod
    templates = pages_mod.templates
    ctx = {
        "request": None,
        "paper_name": "X", "paper_name_encoded": "X",
        "paper_title": "T", "paper_title_ko": "", "paper_authors": [],
        "paper_year": None, "paper_venue": None, "paper_doi": None,
        "paper_url": None, "paper_doc_type": None,
        "has_pdf": True, "has_md_ko": True, "has_md_en": False,
        "has_md_ko_explained": False, "has_md_en_explained": False,
        "has_md_ko_audio": False, "has_md_ko_audio_brief": False,
        "has_audio_mp3": False, "has_video": False,
        "video_poster_url": "", "video_duration_hms": None,
        "video_position": 0, "video_watched": False,
        "location": "books", "default_view": "md", "server_progress": 0,
        "api_base": "/api/books/B/chapters/X", "viewer_kind": "book_chapter",
        "storage_scope": "book_b-ch_X", "storage_scope_raw": "book_b-ch_X",
        "book_name": "B", "book_title": "Book B", "chapter_title": "Chap X",
        "chapter_index": 1, "chapters_total": 1, "prev_url": None, "next_url": None,
    }
    return templates.get_template("viewer.html").render(**ctx)


def test_chapter_kind_render_omits_paper_only_ui(tmp_workspace):
    html = _render_viewer_html_with_kind("book_chapter")
    assert 'x-data="chatPanel()"' not in html
    assert 'x-data="chatButton()"' not in html
    assert 'const viewerKind = "book_chapter";' in html
    # Desktop ⋯ menu Download must NOT be gated — chapters can download too
    assert '다운받기' in html


def test_paper_only_fetch_functions_have_js_guard(tmp_workspace):
    html = _render_viewer_html_with_kind("book_chapter")
    assert html.count("viewerKind !== 'paper'") >= 8


def test_paper_kind_render_keeps_paper_only_blocks(client, tmp_workspace):
    _make_paper(tmp_workspace, "P")
    html = client.get("/viewer/P").text
    assert 'x-data="chatPanel()"' in html
    assert 'x-data="chatButton()"' in html
