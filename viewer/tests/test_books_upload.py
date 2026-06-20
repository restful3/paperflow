import json
import pytest
from app import config as _cfg
from app.services import books as book_svc
from app.services import papers as paper_svc


@pytest.fixture
def ws(tmp_workspace, monkeypatch):
    # tmp_workspace rebuilds _cfg.settings; rebind the modules' captured ref.
    monkeypatch.setattr(paper_svc, "settings", _cfg.settings)
    monkeypatch.setattr(book_svc, "settings", _cfg.settings)
    return tmp_workspace


def test_save_book_upload_writes_ordered_chapters_and_meta(ws):
    files = [("intro.pdf", b"%PDF-a"), ("ch two.pdf", b"%PDF-b")]
    ok, msg, slug = book_svc.save_book_upload("Quant Trading", "E. Chan", 2021, files)
    assert ok is True
    assert slug == "Quant Trading"
    bdir = ws / "newbooks" / "Quant Trading"
    names = sorted(p.name for p in bdir.glob("*.pdf"))
    assert names == ["01_intro.pdf", "02_ch two.pdf"]
    assert (bdir / "01_intro.pdf").read_bytes() == b"%PDF-a"
    meta = json.loads((bdir / "book.json").read_text(encoding="utf-8"))
    assert meta == {"title": "Quant Trading", "author": "E. Chan", "year": 2021}


def test_save_book_upload_rejects_empty_title(ws):
    ok, msg, slug = book_svc.save_book_upload("   ", None, None, [("a.pdf", b"x")])
    assert ok is False and slug is None


def test_save_book_upload_rejects_no_files(ws):
    ok, msg, slug = book_svc.save_book_upload("Title", None, None, [])
    assert ok is False and slug is None


def test_save_book_upload_slug_collision_suffix(ws):
    (ws / "books" / "Dup").mkdir(parents=True)        # existing book collides
    ok, msg, slug = book_svc.save_book_upload("Dup", None, None, [("a.pdf", b"x")])
    assert ok is True
    assert slug == "Dup-2"
    assert (ws / "newbooks" / "Dup-2" / "01_a.pdf").is_file()


def test_save_book_upload_omits_blank_author_year(ws):
    ok, msg, slug = book_svc.save_book_upload("T", "", None, [("a.pdf", b"x")])
    meta = json.loads((ws / "newbooks" / slug / "book.json").read_text(encoding="utf-8"))
    assert meta == {"title": "T"}


from fastapi.testclient import TestClient


@pytest.fixture
def client(ws, monkeypatch):
    import app.main as _main
    monkeypatch.setattr(_main.settings, "JWT_SECRET_KEY", _cfg.settings.JWT_SECRET_KEY)
    monkeypatch.setattr(_main.settings, "BASE_DIR", _cfg.settings.BASE_DIR)
    from app.main import create_app
    from app.dependencies import get_current_user_api
    app = create_app()
    app.dependency_overrides[get_current_user_api] = lambda: "tester"
    return TestClient(app)


def test_upload_endpoint_creates_book(client, ws):
    resp = client.post("/api/books/upload",
                       data={"title": "My Book", "author": "A", "year": "2020"},
                       files=[("files", ("01.pdf", b"%PDF-1", "application/pdf")),
                              ("files", ("02.pdf", b"%PDF-2", "application/pdf"))])
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["chapters"] == 2 and body["slug"] == "My Book"
    assert (ws / "newbooks" / "My Book" / "01_01.pdf").is_file()


def test_upload_endpoint_rejects_non_pdf(client):
    resp = client.post("/api/books/upload",
                       data={"title": "X"},
                       files=[("files", ("a.txt", b"nope", "text/plain"))])
    assert resp.status_code == 400


def test_upload_endpoint_requires_title(client):
    resp = client.post("/api/books/upload",
                       data={"title": "  "},
                       files=[("files", ("a.pdf", b"%PDF", "application/pdf"))])
    assert resp.status_code == 400


def test_upload_endpoint_rejects_bad_year(client):
    resp = client.post("/api/books/upload",
                       data={"title": "X", "year": "notayear"},
                       files=[("files", ("a.pdf", b"%PDF", "application/pdf"))])
    assert resp.status_code == 400


def _put(p, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_list_book_processing_inflight_only(ws):
    import json
    # Book A: 2 chapters in newbooks, book_state says ch1 complete, ch2 missing -> in-flight
    _put(ws / "newbooks" / "A" / "01_intro.pdf")
    _put(ws / "newbooks" / "A" / "02_more.pdf")
    (ws / "newbooks" / "A" / "book.json").write_text(json.dumps({"title": "Book A"}), encoding="utf-8")
    (ws / "books" / "A").mkdir(parents=True)
    (ws / "books" / "A" / "book_state.json").write_text(json.dumps(
        {"schema_version": 1, "chapters": {"01_intro": {"pipeline_status": "complete"}}}), encoding="utf-8")
    # Book B: all chapters complete -> excluded
    _put(ws / "newbooks" / "B" / "01_x.pdf")
    (ws / "newbooks" / "B" / "book.json").write_text(json.dumps({"title": "Book B"}), encoding="utf-8")
    (ws / "books" / "B").mkdir(parents=True)
    (ws / "books" / "B" / "book_state.json").write_text(json.dumps(
        {"schema_version": 1, "chapters": {"01_x": {"pipeline_status": "complete"}}}), encoding="utf-8")

    out = book_svc.list_book_processing()
    slugs = {b["slug"] for b in out}
    assert slugs == {"A"}                      # B excluded (all complete)
    a = next(b for b in out if b["slug"] == "A")
    assert a["title"] == "Book A"
    statuses = {c["chapter_id"]: c["status"] for c in a["chapters"]}
    assert statuses == {"01_intro": "complete", "02_more": "queued"}
    assert a["pending"] == 1


def test_list_book_processing_no_state_all_queued(ws):
    import json
    _put(ws / "newbooks" / "C" / "01_a.pdf")
    (ws / "newbooks" / "C" / "book.json").write_text(json.dumps({"title": "C"}), encoding="utf-8")
    out = book_svc.list_book_processing()
    assert len(out) == 1
    assert out[0]["chapters"][0]["status"] == "queued"   # no books/<slug> yet


def test_list_book_processing_empty(ws):
    assert book_svc.list_book_processing() == []


def test_list_book_processing_processing_status_stem_match_only(ws):
    """Regression: ensure 'processing' is marked only by exact stem match, not substring.

    Demonstrates the bug: if we have chapters with stems that are substrings of each other,
    the OLD substring match would wrongly mark both as processing.
    E.g., chapters '01' and '01_intro': current_file '/path/01_intro.pdf' would match both
    ('01' in '01_intro.pdf' is True). The NEW stem match only marks '01_intro' as processing.
    """
    import json
    # Create a book with two chapters: 01.pdf and 02_01_intro.pdf
    # (This is a pathological case, but demonstrates substring false positive)
    _put(ws / "newbooks" / "TestBook" / "01.pdf")
    _put(ws / "newbooks" / "TestBook" / "02_01_intro.pdf")
    (ws / "newbooks" / "TestBook" / "book.json").write_text(
        json.dumps({"title": "Test Book"}), encoding="utf-8")

    # Create corresponding books/ dir with book_state (empty chapters state = no state_chapters entries)
    (ws / "books" / "TestBook").mkdir(parents=True)
    (ws / "books" / "TestBook" / "book_state.json").write_text(
        json.dumps({"schema_version": 1, "chapters": {}}), encoding="utf-8")

    # Simulate converter processing 02_01_intro.pdf
    (ws / "logs").mkdir(parents=True, exist_ok=True)
    processing_status = {"current_file": "/some/path/02_01_intro.pdf"}
    (ws / "logs" / "processing_status.json").write_text(
        json.dumps(processing_status), encoding="utf-8")

    out = book_svc.list_book_processing()
    assert len(out) == 1
    book = out[0]
    assert book["slug"] == "TestBook"

    statuses = {c["chapter_id"]: c["status"] for c in book["chapters"]}
    # With the BUGGY substring code:
    #   '01' in '/some/path/02_01_intro.pdf' -> True (FALSE POSITIVE, marks '01' as processing)
    # With the fixed stem code:
    #   '01' != '02_01_intro' -> False (CORRECT, keeps '01' as queued)
    assert statuses["01"] == "queued", f"01 should NOT be marked processing (substring false positive), got {statuses['01']}"
    assert statuses["02_01_intro"] == "processing", f"02_01_intro should be marked processing (exact stem match), got {statuses['02_01_intro']}"
    # pending = queued + processing = 1 queued + 1 processing = 2
    assert book["pending"] == 2
