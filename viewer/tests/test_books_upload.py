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
