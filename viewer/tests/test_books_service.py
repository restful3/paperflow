import json
import pytest


@pytest.fixture(autouse=True)
def _rebind_settings(tmp_workspace, monkeypatch):
    """papers.py and books.py bind settings at module load; rebind to tmp_workspace."""
    from app import config as _cfg
    from app.services import papers, books
    monkeypatch.setattr(papers, "settings", _cfg.settings)
    monkeypatch.setattr(books, "settings", _cfg.settings)


def test_save_markdown_in_dir_ko_creates_backup_and_writes(tmp_workspace):
    from app.services import papers
    d = tmp_workspace / "outputs" / "P"
    d.mkdir(parents=True)
    (d / "P.md").write_text("# en", encoding="utf-8")
    (d / "P_ko.md").write_text("# 원본", encoding="utf-8")

    ok, msg = papers.save_markdown_in_dir(d, "ko", "# 수정본")

    assert ok is True
    assert (d / "P_ko.md").read_text(encoding="utf-8") == "# 수정본"
    backups = list(d.glob("P_ko.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "# 원본"


def test_save_markdown_in_dir_missing_target_returns_false(tmp_workspace):
    from app.services import papers
    d = tmp_workspace / "outputs" / "Q"
    d.mkdir(parents=True)
    (d / "Q.md").write_text("# en", encoding="utf-8")  # no _ko.md

    ok, msg = papers.save_markdown_in_dir(d, "ko", "x")
    assert ok is False
    assert "not found" in msg.lower()


def _make_book(ws, slug="MyBook", book_id=None, chapters=(("01_intro", "Intro"),),
               archived=False, ko=True, state=None, cover=False):
    base = ws / ("book_archives" if archived else "books")
    bd = base / slug
    bd.mkdir(parents=True)
    bid = book_id or f"book-{slug.lower()}-aaa111"
    meta = {"schema_version": 1, "book_id": bid, "title": slug,
            "author": "A. Author", "year": 2024, "chapters": []}
    if cover:
        (bd / "cover.jpg").write_bytes(b"\xff\xd8\xff")
        meta["cover"] = "cover.jpg"
    for i, (cid, title) in enumerate(chapters, 1):
        cdir = bd / cid
        cdir.mkdir()
        (cdir / f"{cid}.md").write_text("# en body", encoding="utf-8")
        if ko:
            (cdir / f"{cid}_ko.md").write_text("# ko 본문", encoding="utf-8")
        meta["chapters"].append({"order": i, "chapter_id": cid, "title": title,
                                 "source_pdf": f"{cid}.pdf", "source_sha256": "x" * 64})
    (bd / "book_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if state is not None:
        (bd / "book_state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return bd, bid


def test_list_books_returns_cards_with_meta(tmp_workspace):
    from app.services import books
    _make_book(tmp_workspace, slug="BookA", chapters=(("01_intro", "Intro"), ("02_more", "More")))
    cards = books.list_books(tab="books")
    assert len(cards) == 1
    c = cards[0]
    assert c["name"] == "BookA"
    assert c["title"] == "BookA"
    assert c["author"] == "A. Author"
    assert c["year"] == 2024
    assert c["chapters_total"] == 2
    assert c["location"] == "books"
    assert c["progress_pct"] == 0


def test_list_books_archived_tab_reads_book_archives(tmp_workspace):
    from app.services import books
    _make_book(tmp_workspace, slug="OldBook", archived=True)
    assert books.list_books(tab="books") == []
    archived = books.list_books(tab="archived")
    assert len(archived) == 1
    assert archived[0]["location"] == "book_archives"


def test_list_books_skips_folder_without_meta(tmp_workspace):
    from app.services import books
    (tmp_workspace / "books" / "NoMeta").mkdir(parents=True)
    assert books.list_books(tab="books") == []
