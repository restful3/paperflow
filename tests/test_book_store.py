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
