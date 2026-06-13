"""PaperFlow Books — durable/cache 데이터 계층.

book_meta.json (DURABLE: 사람·파이프라인이 만든 장기 상태) 와
book_state.json (REBUILDABLE CACHE: 디스크에서 재생성 가능) 을 분리 관리한다.
atomic write + per-book file lock 로 챕터별 fresh process 간 lost update 를 막는다.
컨버터(main_terminal)·뷰어 양쪽에서 import 가능한 순수 표준 라이브러리 모듈.
"""
import fcntl
import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

BOOK_META_SCHEMA_VERSION = 1
BOOK_STATE_SCHEMA_VERSION = 1


def book_id_for(slug: str) -> str:
    """Deterministic internal key from a book slug: book-<short>-<sha1[:6]>."""
    h = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:6]
    short = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")[:32] or "book"
    return f"book-{short}-{h}"


def _atomic_write_json(path, data) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


@contextmanager
def book_lock(book_dir, timeout: float = 60.0, poll: float = 0.1):
    """Per-book exclusive flock on <book_dir>/.lock.

    Serializes read-modify-write of book_state.json across the chapter-level
    fresh processes. Models main_terminal._gpu_lock. Raises TimeoutError.
    """
    book_dir = Path(book_dir)
    book_dir.mkdir(parents=True, exist_ok=True)
    fh = open(book_dir / ".lock", "w")
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() > deadline:
                fh.close()
                raise TimeoutError(f"book lock timeout: {book_dir}")
            time.sleep(poll)
    try:
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
