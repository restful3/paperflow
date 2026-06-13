"""Phase 1b-2: book_ingest 단위 테스트."""
import os

import book_ingest as bi


def test_chapter_order_from_filename():
    assert bi.chapter_order_from_filename("01_intro.pdf") == 1
    assert bi.chapter_order_from_filename("12-backtesting.pdf") == 12
    assert bi.chapter_order_from_filename("intro.pdf") is None


def test_chapter_id_from_pdf():
    assert bi.chapter_id_from_pdf("/x/newbooks/B/01_intro.pdf") == "01_intro"


def test_sha256_of(tmp_path):
    p = tmp_path / "a.bin"
    p.write_bytes(b"hello")
    import hashlib
    assert bi.sha256_of(p) == hashlib.sha256(b"hello").hexdigest()


def test_is_size_stable(tmp_path, monkeypatch):
    p = tmp_path / "a.pdf"
    p.write_bytes(b"x")
    # stable: two identical signatures
    monkeypatch.setattr(bi, "file_signature", lambda path: (10, 123))
    assert bi.is_size_stable(p, settle=0) is True
    # unstable: signature changes between samples
    seq = iter([(10, 123), (20, 124)])
    monkeypatch.setattr(bi, "file_signature", lambda path: next(seq))
    assert bi.is_size_stable(p, settle=0) is False


def test_classify_chapter():
    meta = {"chapters": [
        {"chapter_id": "01_a", "order": 1, "source_sha256": "shaA"},
    ]}
    assert bi.classify_chapter(meta, "02_b", "shaB", 2) == "new"
    assert bi.classify_chapter(meta, "01_a", "shaA", 1) == "skip"          # same id+sha
    assert bi.classify_chapter(meta, "01_a", "shaDIFF", 1) == "needs_review"
    assert bi.classify_chapter(meta, "03_c", "shaC", 1) == "order_conflict"  # order 1 taken by 01_a


def test_ingest_chapter_new_happy_path(tmp_path, monkeypatch):
    """신규 챕터: 챕터 폴더·book_meta(book_id+chapter)·book_state(complete) 산출."""
    import json
    import book_store
    monkeypatch.chdir(tmp_path)
    (tmp_path / "books").mkdir()
    nb = tmp_path / "newbooks" / "MyBook"
    nb.mkdir(parents=True)
    pdf = nb / "01_intro.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    def fake_process(pdf_path, output_dir, base_name, config, prompt, mode="paper"):
        assert mode == "book_chapter"
        with open(os.path.join(output_dir, base_name + ".md"), "w") as f:
            f.write("# Intro\n")
        with open(os.path.join(output_dir, base_name + "_ko.md"), "w") as f:
            f.write("# 서론\n")
        with open(os.path.join(output_dir, "paper_meta.json"), "w") as f:
            json.dump({"title": "Introduction"}, f)
        import shutil
        shutil.move(pdf_path, os.path.join(output_dir, os.path.basename(pdf_path)))
        return True

    import main_terminal as mt
    monkeypatch.setattr(mt, "process_pdf_to_output_dir", fake_process)

    result = bi.ingest_chapter(pdf, config={"processing_pipeline": {}}, prompt="P")

    assert result["status"] == "complete"
    cdir = tmp_path / "books" / "MyBook" / "01_intro"
    assert (cdir / "01_intro_ko.md").is_file()
    assert (cdir / "01_intro.pdf").is_file()              # pdf moved in
    meta = book_store.load_book_meta(tmp_path / "books" / "MyBook")
    assert meta["book_id"].startswith("book-")
    assert len(meta["chapters"]) == 1
    assert meta["chapters"][0]["chapter_id"] == "01_intro"
    assert meta["chapters"][0]["title"] == "Introduction"   # from paper_meta.json
    assert meta["chapters"][0]["order"] == 1
    state = book_store.load_book_state(tmp_path / "books" / "MyBook")
    assert state["chapters"]["01_intro"]["pipeline_status"] == "complete"


def _setup_book_with_chapter(tmp_path, monkeypatch, sha="shaA"):
    """books/MyBook with one ingested chapter 01_a (order 1, given sha)."""
    import book_store
    monkeypatch.chdir(tmp_path)
    bd = tmp_path / "books" / "MyBook"
    bd.mkdir(parents=True)
    meta = book_store.init_book_meta(bd, "MyBook")
    book_store.upsert_chapter_meta(meta, "01_a", 1, "A", "01_a.pdf", sha)
    book_store.save_book_meta(bd, meta)
    return bd


def test_ingest_skip_identical(tmp_path, monkeypatch):
    import main_terminal as mt
    called = []
    monkeypatch.setattr(mt, "process_pdf_to_output_dir",
                        lambda *a, **k: called.append(1) or True)
    nb = tmp_path / "newbooks" / "MyBook"
    nb.mkdir(parents=True)
    pdf = nb / "01_a.pdf"
    pdf.write_bytes(b"data")
    sha = bi.sha256_of(pdf)
    _setup_book_with_chapter(tmp_path, monkeypatch, sha=sha)
    result = bi.ingest_chapter(pdf, config={"processing_pipeline": {}}, prompt="P")
    assert result["status"] == "skip"
    assert called == []                 # converter NOT invoked
    assert pdf.exists()                 # source untouched on skip


def test_ingest_needs_review_on_changed_content(tmp_path, monkeypatch):
    import book_store
    import main_terminal as mt
    called = []
    monkeypatch.setattr(mt, "process_pdf_to_output_dir",
                        lambda *a, **k: called.append(1) or True)
    nb = tmp_path / "newbooks" / "MyBook"
    nb.mkdir(parents=True)
    pdf = nb / "01_a.pdf"
    pdf.write_bytes(b"NEW different content")
    _setup_book_with_chapter(tmp_path, monkeypatch, sha="OLDsha")
    result = bi.ingest_chapter(pdf, config={"processing_pipeline": {}}, prompt="P")
    assert result["status"] == "needs_review"
    assert called == []                 # not auto-overwritten
    state = book_store.load_book_state(tmp_path / "books" / "MyBook")
    assert state["chapters"]["01_a"]["pipeline_status"] == "needs_review"


def test_ingest_order_conflict(tmp_path, monkeypatch):
    import main_terminal as mt
    called = []
    monkeypatch.setattr(mt, "process_pdf_to_output_dir",
                        lambda *a, **k: called.append(1) or True)
    nb = tmp_path / "newbooks" / "MyBook"
    nb.mkdir(parents=True)
    pdf = nb / "01_different.pdf"        # order 1, but 01_a already holds order 1
    pdf.write_bytes(b"x")
    _setup_book_with_chapter(tmp_path, monkeypatch, sha="shaA")
    result = bi.ingest_chapter(pdf, config={"processing_pipeline": {}}, prompt="P")
    assert result["status"] == "order_conflict"
    assert called == []


def test_ingest_replace_overrides_needs_review(tmp_path, monkeypatch):
    """replace=True 면 내용이 달라도 처리한다."""
    import main_terminal as mt
    monkeypatch.setattr(mt, "process_pdf_to_output_dir",
                        lambda p, o, b, c, pr, mode="paper":
                        open(os.path.join(o, b + "_ko.md"), "w").write("ko") or True)
    nb = tmp_path / "newbooks" / "MyBook"
    nb.mkdir(parents=True)
    pdf = nb / "01_a.pdf"
    pdf.write_bytes(b"NEW")
    _setup_book_with_chapter(tmp_path, monkeypatch, sha="OLDsha")
    result = bi.ingest_chapter(pdf, config={"processing_pipeline": {}}, prompt="P", replace=True)
    assert result["status"] == "complete"
