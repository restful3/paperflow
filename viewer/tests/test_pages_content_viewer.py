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
