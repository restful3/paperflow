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


def detect_chapter_formats(chapter_dir) -> dict:
    """Scan a chapter dir for which output formats exist (mirrors viewer suffix rules)."""
    d = Path(chapter_dir)
    names = [f.name for f in d.iterdir() if f.is_file()] if d.is_dir() else []

    def has(suffix, exclude=()):
        return any(n.endswith(suffix) and not any(n.endswith(e) for e in exclude)
                   for n in names)

    return {
        "en": has(".md", exclude=("_ko.md", "_explained.md",
                                  "_ko_audio.md", "_ko_audio_brief.md")),
        "ko": has("_ko.md", exclude=("_ko_explained.md",
                                     "_ko_audio.md", "_ko_audio_brief.md")),
        "ko_explained": has("_ko_explained.md"),
        "ko_audio": has("_ko_audio.md", exclude=("_ko_audio_brief.md",)),
        "ko_audio_brief": has("_ko_audio_brief.md"),
    }


def _aggregate(state: dict) -> dict:
    chs = state.get("chapters", {})
    return {
        "chapters_total": len(chs),
        "chapters_complete": sum(1 for c in chs.values()
                                 if c.get("pipeline_status") == "complete"),
    }


def _migrate_book_state(state: dict) -> dict:
    return state


def load_book_state(book_dir):
    p = Path(book_dir) / "book_state.json"
    if not p.is_file():
        return None
    with open(p, encoding="utf-8") as f:
        state = json.load(f)
    if state.get("schema_version", 0) < BOOK_STATE_SCHEMA_VERSION:
        state = _migrate_book_state(state)
        state["schema_version"] = BOOK_STATE_SCHEMA_VERSION
        _atomic_write_json(p, state)
    return state


def save_book_state(book_dir, state: dict) -> None:
    state["schema_version"] = BOOK_STATE_SCHEMA_VERSION
    state["aggregate"] = _aggregate(state)
    _atomic_write_json(Path(book_dir) / "book_state.json", state)


def update_chapter_state(book_dir, chapter_id, pipeline_status, formats,
                         updated_at=None) -> dict:
    """Read-modify-write one chapter's state entry under the per-book lock."""
    book_dir = Path(book_dir)
    with book_lock(book_dir):
        state = load_book_state(book_dir) or {
            "schema_version": BOOK_STATE_SCHEMA_VERSION, "chapters": {}}
        state.setdefault("chapters", {})[chapter_id] = {
            "pipeline_status": pipeline_status,
            "formats": formats,
            "updated_at": updated_at,
        }
        save_book_state(book_dir, state)
    return state


def rebuild_book_state(book_dir, meta=None) -> dict:
    """Regenerate book_state.json from disk (chapter dirs). Does NOT touch book_meta."""
    book_dir = Path(book_dir)
    meta = meta or load_book_meta(book_dir) or {"chapters": []}
    chapters = {}
    for ch in meta.get("chapters", []):
        cid = ch["chapter_id"]
        fmts = detect_chapter_formats(book_dir / cid)
        status = "complete" if fmts["ko"] else ("converted" if fmts["en"] else "pending")
        chapters[cid] = {"pipeline_status": status, "formats": fmts}
    state = {"schema_version": BOOK_STATE_SCHEMA_VERSION, "chapters": chapters}
    save_book_state(book_dir, state)
    return state
