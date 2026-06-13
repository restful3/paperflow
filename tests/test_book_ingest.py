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
