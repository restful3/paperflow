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


def test_book_progress_save_get_roundtrip(tmp_workspace):
    from app.services import books
    assert books.save_chapter_progress("book-x-1", "01_intro", 42) is True
    assert books.get_book_progress("book-x-1") == {"01_intro": 42}
    # clamp 0..100
    books.save_chapter_progress("book-x-1", "01_intro", 250)
    assert books.get_book_progress("book-x-1")["01_intro"] == 100
    books.save_chapter_progress("book-x-1", "02_more", -5)
    assert books.get_book_progress("book-x-1")["02_more"] == 0


def test_book_progress_nested_no_key_collision(tmp_workspace):
    from app.services import books
    books.save_chapter_progress("book-a", "ch::weird", 10)
    books.save_chapter_progress("book-b", "ch::weird", 20)
    assert books.get_book_progress("book-a") == {"ch::weird": 10}
    assert books.get_book_progress("book-b") == {"ch::weird": 20}
    raw = json.loads((tmp_workspace / "books" / "book_progress.json").read_text(encoding="utf-8"))
    assert raw == {"book-a": {"ch::weird": 10}, "book-b": {"ch::weird": 20}}


def test_delete_book_progress_removes_book(tmp_workspace):
    from app.services import books
    books.save_chapter_progress("book-a", "01", 10)
    books.save_chapter_progress("book-b", "01", 20)
    books.delete_book_progress("book-a")
    assert books.get_book_progress("book-a") == {}
    assert books.get_book_progress("book-b") == {"01": 20}


def test_get_book_progress_unknown_returns_empty(tmp_workspace):
    from app.services import books
    assert books.get_book_progress("nope") == {}


def test_get_book_lists_chapters_with_status_and_progress(tmp_workspace):
    from app.services import books
    _bd, bid = _make_book(
        tmp_workspace, slug="BookB",
        chapters=(("01_intro", "Intro"), ("02_more", "More")),
    )
    books.save_chapter_progress(bid, "01_intro", 100)

    detail = books.get_book("BookB")
    assert detail is not None
    assert detail["book_id"] == bid
    assert detail["title"] == "BookB"
    assert detail["location"] == "books"
    assert len(detail["chapters"]) == 2
    ch1 = detail["chapters"][0]
    assert ch1["chapter_id"] == "01_intro"
    assert ch1["order"] == 1
    assert ch1["title"] == "Intro"
    assert ch1["status"] == "complete"        # has _ko.md
    assert ch1["formats"]["md_ko"] is True
    assert ch1["progress"] == 100
    assert detail["chapters"][1]["progress"] == 0
    assert detail["aggregate"]["chapters_total"] == 2
    assert detail["aggregate"]["progress_pct"] == 50  # (100+0)/200


def test_get_book_uses_state_status_when_present(tmp_workspace):
    from app.services import books
    state = {"schema_version": 1, "chapters": {
        "01_intro": {"pipeline_status": "needs_review", "formats": {}}}}
    _make_book(tmp_workspace, slug="BookC", chapters=(("01_intro", "Intro"),),
               ko=False, state=state)
    detail = books.get_book("BookC")
    assert detail["chapters"][0]["status"] == "needs_review"


def test_get_book_unknown_returns_none(tmp_workspace):
    from app.services import books
    assert books.get_book("Nope") is None


def test_chapter_content_path_resolves_ko_and_en(tmp_workspace):
    from app.services import books
    _make_book(tmp_workspace, slug="BookD", chapters=(("01_intro", "Intro"),))
    ko = books.get_chapter_content_path("BookD", "01_intro", "md_ko")
    en = books.get_chapter_content_path("BookD", "01_intro", "md_en")
    assert ko is not None and ko.name == "01_intro_ko.md"
    assert en is not None and en.name == "01_intro.md"
    assert books.get_chapter_content_path("BookD", "01_intro", "pdf") is None  # no pdf written


def test_chapter_content_path_rejects_unknown_kind(tmp_workspace):
    from app.services import books
    _make_book(tmp_workspace, slug="BookE", chapters=(("01_intro", "Intro"),))
    assert books.get_chapter_content_path("BookE", "01_intro", "bogus") is None


def test_chapter_content_path_traversal_blocked(tmp_workspace):
    from app.services import books
    _make_book(tmp_workspace, slug="BookF", chapters=(("01_intro", "Intro"),))
    assert books.get_chapter_content_path("BookF", "../01_intro", "md_ko") is None
    assert books.get_chapter_content_path("../BookF", "01_intro", "md_ko") is None


def test_chapter_asset_path_resolves(tmp_workspace):
    from app.services import books
    bd, _ = _make_book(tmp_workspace, slug="BookG", chapters=(("01_intro", "Intro"),))
    imgdir = bd / "01_intro" / "images"
    imgdir.mkdir()
    (imgdir / "fig1.jpg").write_bytes(b"\xff\xd8\xff")
    p = books.get_chapter_asset_path("BookG", "01_intro", "images/fig1.jpg")
    assert p is not None and p.name == "fig1.jpg"
    assert books.get_chapter_asset_path("BookG", "01_intro", "../../book_meta.json") is None


def test_save_chapter_markdown_writes_and_backs_up(tmp_workspace):
    from app.services import books
    _make_book(tmp_workspace, slug="BookH", chapters=(("01_intro", "Intro"),))
    ok, msg = books.save_chapter_markdown("BookH", "01_intro", "ko", "# 새 본문")
    assert ok is True
    p = books.get_chapter_content_path("BookH", "01_intro", "md_ko")
    assert p.read_text(encoding="utf-8") == "# 새 본문"


def test_get_chapter_info_returns_formats(tmp_workspace):
    from app.services import books
    _make_book(tmp_workspace, slug="BookK2", chapters=(("01_intro", "Intro"),))
    info = books.get_chapter_info("BookK2", "01_intro")
    assert info is not None
    assert info["formats"]["md_ko"] is True
    assert info["book"] == "BookK2"
    assert info["chapter_id"] == "01_intro"
    assert books.get_chapter_info("BookK2", "nope") is None


def test_get_book_cover_path(tmp_workspace):
    from app.services import books
    _make_book(tmp_workspace, slug="BookI", chapters=(("01_intro", "Intro"),), cover=True)
    p = books.get_book_cover_path("BookI")
    assert p is not None and p.name == "cover.jpg"
    _make_book(tmp_workspace, slug="BookJ", chapters=(("01_intro", "Intro"),), cover=False)
    assert books.get_book_cover_path("BookJ") is None
