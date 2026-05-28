"""Integration tests for /viewer/by-id/{source_id} (T1-T11)."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def page_app(tmp_workspace):
    """Fresh app under an isolated workspace. pages.router is always included."""
    from app import main as _main
    importlib.reload(_main)
    return _main.app


def _authed_client(app):
    from app.dependencies import get_current_user_page
    app.dependency_overrides[get_current_user_page] = lambda: "tester"
    return TestClient(app, follow_redirects=False)


def _anon_client(app):
    from app.dependencies import get_current_user_page
    app.dependency_overrides[get_current_user_page] = lambda: None
    return TestClient(app, follow_redirects=False)


def _make_paper(tmp_workspace, location, folder, source_id):
    d = tmp_workspace / location / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / source_id).touch()
    return d


def test_by_id_valid_redirects_to_viewer(page_app, tmp_workspace):
    """T1 — valid source_id, authed → 302 /viewer/{quoted name} + no-store."""
    sid = "pfmcp-aaaaaaaaaaaa-doc.pdf"
    _make_paper(tmp_workspace, "outputs", "Some Paper", sid)
    client = _authed_client(page_app)
    r = client.get(f"/viewer/by-id/{sid}")
    assert r.status_code == 302
    assert r.headers["location"] == "/viewer/Some%20Paper"
    assert r.headers["cache-control"] == "no-store"


def test_by_id_archives_location(page_app, tmp_workspace):
    """T2 — source only in archives/ resolves and redirects to that folder."""
    sid = "pfmcp-bbbbbbbbbbbb-doc.pdf"
    _make_paper(tmp_workspace, "archives", "Archived Paper", sid)
    client = _authed_client(page_app)
    r = client.get(f"/viewer/by-id/{sid}")
    assert r.status_code == 302
    assert r.headers["location"] == "/viewer/Archived%20Paper"


def test_by_id_anonymous_redirects_login(page_app, tmp_workspace):
    """T3 — unauthenticated → 302 /login + no-store."""
    sid = "pfmcp-aaaaaaaaaaaa-doc.pdf"
    _make_paper(tmp_workspace, "outputs", "Some Paper", sid)
    client = _anon_client(page_app)
    r = client.get(f"/viewer/by-id/{sid}")
    assert r.status_code == 302
    assert r.headers["location"] == "/login"
    assert r.headers["cache-control"] == "no-store"


def test_by_id_unresolved_redirects_papers(page_app, tmp_workspace):
    """T4 — unknown source_id → 302 /papers + no-store."""
    client = _authed_client(page_app)
    r = client.get("/viewer/by-id/pfmcp-zzzzzzzzzzzz-missing.pdf")
    assert r.status_code == 302
    assert r.headers["location"] == "/papers"
    assert r.headers["cache-control"] == "no-store"


def test_by_id_encoded_dot_segment_rejected(page_app, tmp_workspace):
    """T5c — %2e%2e decodes to '..' (single segment), reaches handler,
    validator rejects → 302 /papers."""
    client = _authed_client(page_app)
    r = client.get("/viewer/by-id/%2e%2e")
    assert r.status_code == 302
    assert r.headers["location"] == "/papers"


def test_by_id_encoded_slash_not_processed_by_resolver(page_app, tmp_workspace, monkeypatch):
    """T5d — encoded slash is absorbed by the catch-all /viewer/{path} route,
    NOT processed by the by-id resolver. Env-confirmed: authed → 302 /papers."""
    from app.services import mcp_jobs
    spy = {"called_with": []}
    real = mcp_jobs.resolve_paper_by_source_id
    def _spy(s):
        spy["called_with"].append(s)
        return real(s)
    monkeypatch.setattr(mcp_jobs, "resolve_paper_by_source_id", _spy)

    client = _authed_client(page_app)
    r = client.get("/viewer/by-id/a%2Fb.pdf")
    # catch-all absorbs the slashed path → by-id resolver is never invoked
    assert spy["called_with"] == []
    assert r.status_code == 302
    assert r.headers["location"] == "/papers"


def test_by_id_rename_durability(page_app, tmp_workspace):
    """T6 — same source_id resolves to the new folder after a rename."""
    sid = "pfmcp-cccccccccccc-doc.pdf"
    old = _make_paper(tmp_workspace, "outputs", "Old Name", sid)
    client = _authed_client(page_app)
    r1 = client.get(f"/viewer/by-id/{sid}")
    assert r1.headers["location"] == "/viewer/Old%20Name"

    old.rename(tmp_workspace / "outputs" / "New Name")
    r2 = client.get(f"/viewer/by-id/{sid}")
    assert r2.status_code == 302
    assert r2.headers["location"] == "/viewer/New%20Name"


def test_by_id_route_order_resolver_is_invoked(page_app, tmp_workspace, monkeypatch):
    """T8 — a valid pfmcp source_id reaches the by-id handler (resolver called),
    proving the route is registered ABOVE the catch-all /viewer/{path}."""
    from app.services import mcp_jobs
    sid = "pfmcp-eeeeeeeeeeee-doc.pdf"
    _make_paper(tmp_workspace, "outputs", "Routed", sid)
    spy = {"n": 0}
    real = mcp_jobs.resolve_paper_by_source_id
    def _spy(s):
        spy["n"] += 1
        return real(s)
    monkeypatch.setattr(mcp_jobs, "resolve_paper_by_source_id", _spy)

    client = _authed_client(page_app)
    r = client.get(f"/viewer/by-id/{sid}")
    assert spy["n"] == 1  # by-id handler ran; not absorbed by catch-all
    assert r.headers["location"] == "/viewer/Routed"


def test_existing_viewer_route_still_redirects_unknown(page_app, tmp_workspace):
    """T11 — existing /viewer/{paper_name} regression: unknown paper → /papers,
    anonymous → /login (auth override isolates the two cases)."""
    authed = _authed_client(page_app)
    r1 = authed.get("/viewer/Nonexistent%20Paper")
    assert r1.status_code == 302
    assert r1.headers["location"] == "/papers"

    anon = _anon_client(page_app)
    r2 = anon.get("/viewer/Nonexistent%20Paper")
    assert r2.status_code == 302
    assert r2.headers["location"] == "/login"
