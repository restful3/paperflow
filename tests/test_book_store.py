"""Phase 1b-2: book_store 데이터 계층 단위 테스트."""
import json
import os
import threading

import book_store as bs


def test_book_id_deterministic_and_safe():
    a = bs.book_id_for("Chan - Quantitative Trading 2ed")
    b = bs.book_id_for("Chan - Quantitative Trading 2ed")
    assert a == b                      # deterministic
    assert a.startswith("book-")
    assert " " not in a                # filesystem/key safe


def test_atomic_write_json_roundtrip(tmp_path):
    p = tmp_path / "x.json"
    bs._atomic_write_json(p, {"k": 1, "한글": "값"})
    assert json.loads(p.read_text(encoding="utf-8")) == {"k": 1, "한글": "값"}
    assert not (tmp_path / "x.json.tmp").exists()   # tmp cleaned by os.replace


def test_book_lock_is_exclusive(tmp_path):
    """두 번째 lock 획득은 첫 lock 해제 전까지 대기(타임아웃으로 증명)."""
    bd = tmp_path / "book"
    bd.mkdir()
    import pytest
    with bs.book_lock(bd):
        with pytest.raises(TimeoutError):
            with bs.book_lock(bd, timeout=0.3, poll=0.05):
                pass


def test_init_book_meta_creates_then_preserves(tmp_path):
    bd = tmp_path / "MyBook"
    meta = bs.init_book_meta(bd, "MyBook")
    assert meta["book_id"].startswith("book-")
    assert meta["title"] == "MyBook"
    assert meta["chapters"] == []
    assert (bd / "book_meta.json").is_file()
    # 사람이 title 수정 후 재호출 → 덮어쓰지 않음(durable 보존)
    meta["title"] = "Edited Title"
    bs.save_book_meta(bd, meta)
    again = bs.init_book_meta(bd, "MyBook")
    assert again["title"] == "Edited Title"
    assert again["book_id"] == meta["book_id"]


def test_upsert_chapter_meta_add_update_and_sort(tmp_path):
    bd = tmp_path / "MyBook"
    meta = bs.init_book_meta(bd, "MyBook")
    bs.upsert_chapter_meta(meta, "02_b", 2, "B", "02_b.pdf", "shaB")
    bs.upsert_chapter_meta(meta, "01_a", 1, "A", "01_a.pdf", "shaA")
    assert [c["chapter_id"] for c in meta["chapters"]] == ["01_a", "02_b"]  # sorted by order
    # update existing chapter (same id) → no duplicate, fields updated
    bs.upsert_chapter_meta(meta, "01_a", 1, "A2", "01_a.pdf", "shaA2")
    a = [c for c in meta["chapters"] if c["chapter_id"] == "01_a"][0]
    assert a["title"] == "A2" and a["source_sha256"] == "shaA2"
    assert len(meta["chapters"]) == 2


def test_load_book_meta_migrates_old_schema(tmp_path):
    bd = tmp_path / "MyBook"
    bd.mkdir()
    bs._atomic_write_json(bd / "book_meta.json",
                          {"schema_version": 0, "book_id": "book-x", "chapters": []})
    meta = bs.load_book_meta(bd)
    assert meta["schema_version"] == bs.BOOK_META_SCHEMA_VERSION


def test_detect_chapter_formats(tmp_path):
    d = tmp_path / "01_intro"
    d.mkdir()
    (d / "01_intro.md").write_text("en")
    (d / "01_intro_ko.md").write_text("ko")
    (d / "01_intro_ko_explained.md").write_text("ex")
    fmts = bs.detect_chapter_formats(d)
    assert fmts == {"en": True, "ko": True, "ko_explained": True,
                    "ko_audio": False, "ko_audio_brief": False}


def test_update_chapter_state_no_lost_update(tmp_path):
    """기존 챕터 A 가 있을 때 B 를 갱신해도 A 가 보존된다(read-modify-write)."""
    bd = tmp_path / "MyBook"
    bd.mkdir()
    bs.update_chapter_state(bd, "01_a", "complete", {"en": True, "ko": True})
    bs.update_chapter_state(bd, "02_b", "converted", {"en": True, "ko": False})
    state = bs.load_book_state(bd)
    assert set(state["chapters"]) == {"01_a", "02_b"}
    assert state["chapters"]["01_a"]["pipeline_status"] == "complete"
    assert state["aggregate"] == {"chapters_total": 2, "chapters_complete": 1}


def test_update_chapter_state_concurrent_threads(tmp_path):
    """동시 스레드 갱신에도 lost update 없음(per-book lock)."""
    import threading
    bd = tmp_path / "MyBook"
    bd.mkdir()

    def worker(cid):
        bs.update_chapter_state(bd, cid, "complete", {"en": True, "ko": True})

    threads = [threading.Thread(target=worker, args=(f"ch{i:02d}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    state = bs.load_book_state(bd)
    assert len(state["chapters"]) == 8


def test_rebuild_book_state_from_disk(tmp_path):
    bd = tmp_path / "MyBook"
    meta = bs.init_book_meta(bd, "MyBook")
    bs.upsert_chapter_meta(meta, "01_a", 1, "A", "01_a.pdf", "sha")
    bs.save_book_meta(bd, meta)
    cd = bd / "01_a"
    cd.mkdir()
    (cd / "01_a.md").write_text("en")
    (cd / "01_a_ko.md").write_text("ko")
    state = bs.rebuild_book_state(bd)
    assert state["chapters"]["01_a"]["pipeline_status"] == "complete"
    assert state["chapters"]["01_a"]["formats"]["ko"] is True
