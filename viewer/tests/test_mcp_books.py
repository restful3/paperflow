import base64
import json
import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _rebind_settings(tmp_workspace, monkeypatch):
    from app import config as _cfg
    from app.services import books, mcp_books, papers
    monkeypatch.setattr(books, "settings", _cfg.settings)
    monkeypatch.setattr(mcp_books, "settings", _cfg.settings)
    monkeypatch.setattr(papers, "settings", _cfg.settings)


def _pdf_b64(label: bytes = b"x") -> str:
    return base64.b64encode(b"%PDF-1.4 " + label).decode()


@pytest.mark.asyncio
async def test_submit_book_chapters_validates_then_publishes_batch(tmp_workspace):
    from app.services import mcp_books

    rec = await mcp_books.submit_book_chapters(
        title="Quant Book",
        author="A. Author",
        year=2026,
        chapters=[
            {"chapter_id": "intro", "order": 1, "file_base64": _pdf_b64(b"a")},
            {"chapter_id": "methods", "order": 2, "file_base64": _pdf_b64(b"b")},
        ],
    )

    assert rec.status == "queued"
    assert rec.book_id.startswith("book-")
    book_dir = tmp_workspace / "newbooks" / "Quant Book"
    assert (book_dir / "book.json").is_file()
    assert sorted(p.name for p in book_dir.glob("*.pdf")) == [
        "01_intro.pdf", "02_methods.pdf",
    ]
    meta = json.loads((book_dir / "book.json").read_text(encoding="utf-8"))
    assert meta["book_id"] == rec.book_id
    assert meta["title"] == "Quant Book"
    assert rec.chapters[0].chapter_id == "01_intro"


@pytest.mark.asyncio
async def test_submit_book_chapters_rejects_duplicate_order_without_publish(tmp_workspace):
    from app.services import mcp_books

    with pytest.raises(ValueError, match="duplicate chapter order"):
        await mcp_books.submit_book_chapters(
            title="Bad Book",
            chapters=[
                {"chapter_id": "a", "order": 1, "file_base64": _pdf_b64(b"a")},
                {"chapter_id": "b", "order": 1, "file_base64": _pdf_b64(b"b")},
            ],
        )

    assert not (tmp_workspace / "newbooks" / "Bad Book").exists()


@pytest.mark.asyncio
async def test_reconcile_book_job_complete_from_book_state(tmp_workspace):
    from app.services import mcp_books

    rec = await mcp_books.submit_book_chapters(
        title="Done Book",
        chapters=[{"chapter_id": "intro", "file_base64": _pdf_b64()}],
    )
    out = tmp_workspace / "books" / rec.book_slug
    cdir = out / "01_intro"
    cdir.mkdir(parents=True)
    (cdir / "01_intro.md").write_text("# en", encoding="utf-8")
    (cdir / "01_intro_ko.md").write_text("# ko", encoding="utf-8")
    (out / "book_meta.json").write_text(json.dumps({
        "schema_version": 1,
        "book_id": rec.book_id,
        "title": rec.title,
        "chapters": [{
            "order": 1,
            "chapter_id": "01_intro",
            "title": "Intro",
            "source_pdf": "01_intro.pdf",
            "source_sha256": "x" * 64,
        }],
    }), encoding="utf-8")
    (out / "book_state.json").write_text(json.dumps({
        "schema_version": 1,
        "chapters": {"01_intro": {"pipeline_status": "complete"}},
    }), encoding="utf-8")

    final = await mcp_books.reconcile_book_job(rec.job_id)

    assert final.status == "complete"
    assert final.percent == 100
    assert final.completed_at is not None


@pytest.mark.asyncio
async def test_reconcile_book_job_processing_status_overrides_converted(tmp_workspace):
    from app.services import mcp_books

    rec = await mcp_books.submit_book_chapters(
        title="Translating Book",
        chapters=[{"chapter_id": "intro", "file_base64": _pdf_b64()}],
    )
    out = tmp_workspace / "books" / rec.book_slug
    cdir = out / "01_intro"
    cdir.mkdir(parents=True)
    (cdir / "01_intro.md").write_text("# en", encoding="utf-8")
    (out / "book_meta.json").write_text(json.dumps({
        "schema_version": 1,
        "book_id": rec.book_id,
        "title": rec.title,
        "chapters": [{"order": 1, "chapter_id": "01_intro", "title": "Intro"}],
    }), encoding="utf-8")
    (tmp_workspace / "logs" / "processing_status.json").write_text(json.dumps({
        "current_file": "01_intro.pdf",
        "stage": "translating",
        "stage_label": "Translating to Korean",
    }), encoding="utf-8")

    current = await mcp_books.reconcile_book_job(rec.job_id)

    assert current.status == "processing"
    assert current.stage == "translating"
    assert current.chapters[0].status == "processing"


def test_book_zip_endpoint_requires_complete_job(mcp_enabled_workspace):
    from app import main as _main
    from app.config import settings

    client = TestClient(_main.app)
    r = client.get(
        "/api/mcp/books/jobs/missing/zip",
        headers={"Authorization": f"Bearer {settings.MCP_API_KEY}"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_book_zip_endpoint_streams_manifest(mcp_enabled_workspace, monkeypatch):
    from app import config as _cfg
    from app.routers import mcp_router
    from app.services import books, mcp_books, papers
    monkeypatch.setattr(books, "settings", _cfg.settings)
    monkeypatch.setattr(mcp_books, "settings", _cfg.settings)
    monkeypatch.setattr(papers, "settings", _cfg.settings)
    monkeypatch.setattr(mcp_router, "settings", _cfg.settings)

    rec = await mcp_books.submit_book_chapters(
        title="Zip Book",
        chapters=[{"chapter_id": "intro", "file_base64": _pdf_b64()}],
    )
    out = mcp_enabled_workspace / "books" / rec.book_slug
    cdir = out / "01_intro"
    cdir.mkdir(parents=True)
    (cdir / "01_intro.md").write_text("# en", encoding="utf-8")
    (cdir / "01_intro_ko.md").write_text("# ko", encoding="utf-8")
    (out / "book_meta.json").write_text(json.dumps({
        "schema_version": 1,
        "book_id": rec.book_id,
        "title": rec.title,
        "chapters": [{"order": 1, "chapter_id": "01_intro", "title": "Intro"}],
    }), encoding="utf-8")
    (out / "book_state.json").write_text(json.dumps({
        "schema_version": 1,
        "chapters": {"01_intro": {"pipeline_status": "complete"}},
    }), encoding="utf-8")

    import importlib
    from app import main as _main
    importlib.reload(_main)
    client = TestClient(_main.app)
    r = client.get(
        f"/api/mcp/books/jobs/{rec.job_id}/zip",
        headers={"Authorization": f"Bearer {_cfg.settings.MCP_API_KEY}"},
    )

    assert r.status_code == 200
    with zipfile.ZipFile(BytesIO(r.content)) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "book_meta.json" in names
        assert "chapters/01_01_intro/01_intro.md" in names
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["book_id"] == rec.book_id
