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


def _migrate_book_meta(meta: dict) -> dict:
    """Schema upgrade hook. v1 is current → no-op; future versions add steps here."""
    return meta


def load_book_meta(book_dir):
    """Load durable book_meta.json (migrating + rewriting if stale). None if absent."""
    p = Path(book_dir) / "book_meta.json"
    if not p.is_file():
        return None
    with open(p, encoding="utf-8") as f:
        meta = json.load(f)
    if meta.get("schema_version", 0) < BOOK_META_SCHEMA_VERSION:
        meta = _migrate_book_meta(meta)
        meta["schema_version"] = BOOK_META_SCHEMA_VERSION
        _atomic_write_json(p, meta)
    return meta


def save_book_meta(book_dir, meta: dict) -> None:
    meta["schema_version"] = BOOK_META_SCHEMA_VERSION
    _atomic_write_json(Path(book_dir) / "book_meta.json", meta)


def init_book_meta(book_dir, slug: str, book_json: dict | None = None) -> dict:
    """Create durable book_meta.json if absent; return it. NEVER overwrites existing."""
    existing = load_book_meta(book_dir)
    if existing:
        return existing
    book_json = book_json or {}
    meta = {
        "schema_version": BOOK_META_SCHEMA_VERSION,
        "book_id": book_json.get("book_id") or book_id_for(slug),
        "title": book_json.get("title") or slug,
        "author": book_json.get("author"),
        "year": book_json.get("year"),
        "cover": book_json.get("cover", "cover.jpg"),
        "created_at": book_json.get("created_at"),
        "chapters": [],
    }
    Path(book_dir).mkdir(parents=True, exist_ok=True)
    save_book_meta(book_dir, meta)
    return meta


def upsert_chapter_meta(meta: dict, chapter_id, order, title, source_pdf, source_sha256) -> dict:
    """Add or update a chapter entry in `meta` in place; keep chapters order-sorted."""
    for ch in meta["chapters"]:
        if ch["chapter_id"] == chapter_id:
            ch.update({"order": order, "title": title,
                       "source_pdf": source_pdf, "source_sha256": source_sha256})
            break
    else:
        meta["chapters"].append({
            "order": order, "chapter_id": chapter_id, "title": title,
            "source_pdf": source_pdf, "source_sha256": source_sha256})
    meta["chapters"].sort(key=lambda c: (c["order"] if c["order"] is not None else 10**9,
                                         c["chapter_id"]))
    return meta
